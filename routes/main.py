import json
import logging
import os
import re
import traceback
import uuid
import requests
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, send_file

from config import COMPARE_PROMPT, LC_FIELD_KEYS, rules_catalog, AUDIT_RULES

logger = logging.getLogger(__name__)
from config.settings import Config
from services import (
    baidu_ocr, pdf_ocr, deepseek_audit,
    get_db, save_audit_record, generate_pdf,
    generate_docs, generate_docs_pdf, generate_fixed_pdf,
    save_archive, query_archive, get_archive_stats, build_excel, get_archive_db,
    as_text, to_dec,
    deepseek_lc_review, deepseek_lc_fields,
    presentation_deadline, build_deadline_facts,
    parse_issues, generate_discrepancy_pdf, parse_report_section, extract_doc_fields,
)
from services.deepseek_audit import deepseek_compare
from services.discrepancy import severity_label
from services.archive import auto_archive_text
from services import assistant
from services import practice

main_bp = Blueprint("main", __name__)


def _parse_lc_terms(raw):
    """信用证条款：接受 dict 或 JSON 字符串。返回 (terms, error)。

    旧写法在 /api/audit 里先花钱 OCR、再校验参数，参数错了钱也花了；
    /api/audit-text 则完全不校验，传个 list 进去会在 build_lc_prefix 里炸成 500。
    """
    if raw is None or raw == "" or raw == {}:
        return None, None
    if isinstance(raw, dict):
        return raw, None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None, "信用证条款格式错误，请检查输入"
        if isinstance(parsed, dict):
            return parsed, None
    return None, "信用证条款格式错误，请检查输入"


def _req_text(value):
    """接口入参里的正文必须是真字符串。

    只要"不为空"就放行的话，{"text": 12345} 这种传错字段的请求会把垃圾内容
    直接送去调 AI（真花钱），本该在门口拦下。
    """
    return value.strip() if isinstance(value, str) else ""


def _display_filename(file_storage):
    """历史摘要里显示的文件名。

    secure_filename 会把中文名绞成 "pdf"、"jpg"（非 ASCII 字符全丢），
    摘要就变成没意义的字符；这里只取文件名本身并去掉路径分隔符。
    """
    raw = (file_storage.filename or "").replace("\\", "/")
    return os.path.basename(raw).strip()[:80] or "文件"


def _remove_upload(path):
    """用完即删：客户单证原件不该长期留在硬盘上。"""
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        logger.warning("临时文件删除失败: %s", path)

# ---- File signature (magic bytes) for type validation ----
_MAGIC_SIGNATURES = {
    b"\xff\xd8\xff": "jpg",
    b"\x89PNG\r\n\x1a\n": "png",
    b"%PDF-": "pdf",
}


def _validate_file_magic(file_bytes, claimed_ext):
    """Verify file content matches its claimed extension using magic bytes."""
    for magic, ext in _MAGIC_SIGNATURES.items():
        if file_bytes.startswith(magic):
            return ext == claimed_ext or (claimed_ext == "jpeg" and ext == "jpg")
    return False


def _save_upload_secure(file_storage):
    """Save uploaded file with a random name after validating extension and magic bytes."""
    if file_storage.filename == "":
        raise ValueError("文件名为空")

    # Check extension
    ext = file_storage.filename.rsplit(".", 1)[1].lower() if "." in file_storage.filename else ""
    if ext not in Config.ALLOWED_EXTENSIONS:
        raise ValueError("仅支持 JPG、JPEG、PNG、PDF 格式")

    # Read file content and validate magic bytes
    file_bytes = file_storage.read()
    if not _validate_file_magic(file_bytes, ext):
        raise ValueError("文件格式与内容不匹配，拒绝上传")
    file_storage.seek(0)

    # Save with random filename
    safe_name = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(Config.UPLOAD_FOLDER, safe_name)
    file_storage.save(filepath)
    return filepath, ext


def _extract_upload_text(file_storage):
    """上传文件 → 文字，返回 (text, filepath, ext)。

    调用方负责用完调 _remove_upload(filepath)。这段"存盘 → 按类型 OCR"原先在
    /api/audit 和 /api/compare 里各写了一遍，体检接口再加一遍就是三份，
    所以抽出来。抽取失败时这里自己把临时文件删掉 —— 文件已落盘但路径还没交出去，
    调用方的 finally 够不着它。
    """
    filepath, ext = _save_upload_secure(file_storage)
    try:
        text = (pdf_ocr(filepath) if ext == "pdf" else baidu_ocr(filepath)).strip()
    except Exception:
        _remove_upload(filepath)
        raise
    return text, filepath, ext


def _parse_deadline_input(raw):
    """体检请求里带的交单时间参数。前端传 dict，也容忍 JSON 字符串。"""
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None
    if not isinstance(raw, dict):
        return None
    if not (raw.get("shipment_date") or raw.get("expiry")):
        return None
    return raw


# ---- Pages ----
def _runtime_info():
    """设置页的「本机配置」。

    只收非敏感项。密钥（DeepSeek / 百度双 Key / 访问口令 / SECRET_KEY）
    一个都不许进这个 dict —— 它会被渲染成 HTML。
    """
    return {
        "edition": "教育版（实训）" if Config.EDITION == "edu" else "标准版（外贸）",
        "model": Config.DEEPSEEK_MODEL,
        "base_url": Config.DEEPSEEK_BASE_URL,
        "max_upload_mb": max(1, Config.MAX_CONTENT_LENGTH // (1024 * 1024)),
        "formats": " / ".join(sorted(e.upper() for e in Config.ALLOWED_EXTENSIONS)),
        "rate_limit": "每 %d 秒 %d 次" % (Config.RATE_WINDOW, Config.RATE_LIMIT),
        "db_path": Config.DB_PATH,
        "uploads_dir": Config.UPLOAD_FOLDER,
        "password_on": bool(getattr(Config, "ACCESS_PASSWORD", "")),
    }


@main_bp.route("/")
@main_bp.route("/app")
def index():
    return render_template(
        "index.html",
        rule_series=rules_catalog(),
        runtime=_runtime_info(),
    )


# ---- Text Audit ----
@main_bp.route("/api/audit-text", methods=["POST"])
def audit_text():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "未提供文字内容"}), 400
    text = _req_text(data.get("text"))
    if not text:
        return jsonify({"error": "未提供文字内容"}), 400

    lc_terms, lc_err = _parse_lc_terms(data.get("lc_terms"))
    if lc_err:
        return jsonify({"error": lc_err}), 400
    try:
        audit_result = deepseek_audit(text, lc_terms)
        record_id = save_audit_record("text", text[:200], text, audit_result)
        auto_archive_text(text, audit_result, "上传审核", record_id)
        return jsonify({"success": True, "ocr_text": text, "audit_result": audit_result, "record_id": record_id})
    except requests.RequestException as e:
        return jsonify({"error": f"API 调用失败: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"处理失败: {str(e)}"}), 500


# ---- File Audit (Image / PDF) ----
@main_bp.route("/api/audit", methods=["POST"])
def audit():
    if "file" not in request.files:
        return jsonify({"error": "未上传文件"}), 400

    file = request.files["file"]
    # 信用证参数先校验：旧顺序是先 OCR（花钱）再校验，参数错了白花钱
    lc_terms, lc_err = _parse_lc_terms(request.form.get("lc_terms"))
    if lc_err:
        return jsonify({"error": lc_err}), 400

    try:
        ocr_text, filepath, ext = _extract_upload_text(file)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        is_pdf = ext == "pdf"

        if not ocr_text:
            return jsonify({"error": "OCR 未能识别到文字，请确认文件清晰度"}), 400

        audit_result = deepseek_audit(ocr_text, lc_terms)
        record_id = save_audit_record(
            "pdf" if is_pdf else "image", _display_filename(file), ocr_text, audit_result,
        )
        auto_archive_text(ocr_text, audit_result, "上传审核", record_id)
        return jsonify({"success": True, "ocr_text": ocr_text, "audit_result": audit_result, "record_id": record_id})
    except requests.RequestException as e:
        return jsonify({"error": f"API 调用失败: {str(e)}"}), 500
    except Exception as e:
        logger.warning("审核失败: %s", traceback.format_exc())
        return jsonify({"error": f"处理失败: {str(e)}"}), 500
    finally:
        # 成功、失败、异常都删 —— 用户以为"审核失败"就等于没上传
        _remove_upload(filepath)


# ---- Multi-Doc Compare ----
@main_bp.route("/api/compare", methods=["POST"])
def compare_docs():
    saved_paths = []

    def get_text(key_text, key_file):
        text = as_text(request.form.get(key_text))
        file = request.files.get(key_file)
        if file and file.filename:
            text, filepath, _ext = _extract_upload_text(file)
            saved_paths.append(filepath)
        return text

    try:
        text_a = get_text("text_a", "file_a")
        text_b = get_text("text_b", "file_b")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        for path in saved_paths:
            _remove_upload(path)

    if not text_a or not text_b:
        return jsonify({"error": "两边都需要提供单证内容（文字或文件）"}), 400

    try:
        compare_result = deepseek_compare(text_a, text_b, COMPARE_PROMPT)
        return jsonify({"success": True, "text_a": text_a, "text_b": text_b, "audit_result": compare_result})
    except requests.RequestException as e:
        return jsonify({"error": f"API 调用失败: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"处理失败: {str(e)}"}), 500


# ---- LC Review（信用证体检 / 审证）----
@main_bp.route("/api/lc-review", methods=["POST"])
def lc_review():
    """审核信用证本身。可粘贴原文（JSON），也可上传 LC 的图片/PDF（multipart）。

    审的是"这张信用证有没有坑"，和 /api/audit 审单据是两回事，
    所以结果不进档案（auto_archive_text 会去抽发票号那套字段，抽出来全是噪音）。
    """
    file = request.files.get("file")
    filepath = None
    if file and file.filename:
        deadline_input = _parse_deadline_input(request.form.get("deadline"))
        try:
            lc_text, filepath, _ext = _extract_upload_text(file)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except requests.RequestException as e:
            return jsonify({"error": f"信用证文件识别失败: {str(e)}"}), 500
        except Exception:
            logger.warning("信用证文件识别失败: %s", traceback.format_exc())
            return jsonify({"error": "信用证文件识别失败"}), 500
    else:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({"error": "未提供信用证内容"}), 400
        lc_text = _req_text(data.get("text"))
        deadline_input = _parse_deadline_input(data.get("deadline"))

    try:
        if not lc_text:
            return jsonify({"error": "未提供信用证内容"}), 400
        if len(lc_text) > 60000:
            return jsonify({"error": "信用证内容过长，请分段处理"}), 400

        # 日期先用本地算法算死，再当事实喂给模型 —— 不让它自己算
        deadline_result = None
        deadline_facts = ""
        if deadline_input:
            deadline_result = presentation_deadline(
                deadline_input.get("shipment_date", ""),
                deadline_input.get("expiry", ""),
                days=deadline_input.get("days"),
                mailing_days=deadline_input.get("mailing_days", 5),
            )
            deadline_facts = build_deadline_facts(deadline_result)

        review = deepseek_lc_review(lc_text, deadline_facts=deadline_facts)
        record_id = save_audit_record("lc", lc_text[:200], lc_text, review)
        return jsonify({
            "success": True, "lc_text": lc_text, "audit_result": review,
            "record_id": record_id, "deadline": deadline_result,
        })
    except requests.RequestException as e:
        return jsonify({"error": f"API 调用失败: {str(e)}"}), 500
    except Exception as e:
        logger.warning("审证失败: %s", traceback.format_exc())
        return jsonify({"error": f"处理失败: {str(e)}"}), 500
    finally:
        _remove_upload(filepath)


@main_bp.route("/api/lc-deadline", methods=["POST"])
def lc_deadline_calc():
    """交单时间计算。纯本地计算，不调 AI、不花钱。

    "资料没填全"是正常状态不是错误，所以一律返回 200，用 ok 字段区分。
    """
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "参数格式错误"})
    result = presentation_deadline(
        _req_text(data.get("shipment_date")),
        _req_text(data.get("expiry")),
        days=data.get("days"),
        mailing_days=data.get("mailing_days", 5),
    )
    return jsonify(result)


@main_bp.route("/api/lc-fields", methods=["POST"])
def lc_fields():
    """从信用证原文抽取那 14 个字段，供一键回填到审单表单。"""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "未提供信用证内容"}), 400
    lc_text = _req_text(data.get("text"))
    if not lc_text:
        return jsonify({"error": "未提供信用证内容"}), 400
    try:
        fields = deepseek_lc_fields(lc_text)
    except Exception:
        logger.warning("信用证字段抽取失败: %s", traceback.format_exc())
        return jsonify({"error": "字段抽取失败，请手动填写"}), 500
    return jsonify({
        "success": True, "fields": fields,
        "count": len(fields), "expected": len(LC_FIELD_KEYS),
    })


# ---- Discrepancy List（不符点清单导出）----
@main_bp.route("/api/export-discrepancy", methods=["POST"])
def export_discrepancy():
    """把审核报告导成银行交单用的不符点清单。

    条目来自报告里的问题行，抬头信息从单证原文里抽 —— 都是本地解析，
    不重新调 AI：报告里已经写清楚的东西，再让模型复述一遍只会引入新的错。
    """
    data = request.get_json(silent=True) or {}
    audit_result = _req_text(data.get("audit_result"))
    if not audit_result:
        return jsonify({"error": "无审核结果"}), 400

    items = parse_issues(audit_result)
    if not items:
        return jsonify({"error": "这份报告里没有「问题N」条目，无法生成不符点清单"}), 400

    ocr_text = _req_text(data.get("ocr_text"))
    meta = {"doc_type": parse_report_section(audit_result, "单证类型")}
    if ocr_text:
        try:
            fields = extract_doc_fields(ocr_text)
        except Exception:
            logger.warning("清单抬头字段抽取失败: %s", traceback.format_exc())
            fields = {}
        meta["invoice_no"] = fields.get("invoice_no") or ""
        meta["shipper"] = fields.get("shipper_name") or ""
        meta["consignee"] = fields.get("consignee_name") or ""

    try:
        buf, file_name = generate_discrepancy_pdf(items, meta)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        logger.warning("不符点清单导出失败: %s", traceback.format_exc())
        return jsonify({"error": "导出失败：清单内容无法渲染"}), 500
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=file_name)


# ---- Assistant (总控智能助手) ----
@main_bp.route("/api/assistant", methods=["POST"])
def assistant_chat():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "消息为空"}), 400
    message = _req_text(data.get("message"))
    if not message:
        return jsonify({"error": "消息为空"}), 400
    if len(message) > 20000:
        return jsonify({"error": "内容过长，请分段发送"}), 400
    thread_id = data.get("thread_id")
    if thread_id is not None:
        try:
            thread_id = int(thread_id)
        except (TypeError, ValueError):
            return jsonify({"error": "thread_id 无效"}), 400
        if not assistant.thread_exists(thread_id):
            # 会话已被删除或 id 是伪造的 → 另起一个，避免消息写进去成孤儿
            thread_id = None
    try:
        reply, tid = assistant.answer(message, thread_id)
        return jsonify({"success": True, "reply": reply, "kind": "chat", "thread_id": tid})
    except requests.RequestException as e:
        return jsonify({"error": f"API 调用失败: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": f"处理失败: {str(e)}"}), 500


@main_bp.route("/api/assistant/threads", methods=["GET"])
def assistant_threads():
    return jsonify({"success": True, "threads": assistant.list_threads()})


@main_bp.route("/api/assistant/history", methods=["GET"])
def assistant_history():
    thread_id = request.args.get("thread_id", type=int)
    if thread_id is None:
        return jsonify({"error": "缺少 thread_id"}), 400
    return jsonify({"success": True, "messages": assistant.list_messages(thread_id, limit=300)})


@main_bp.route("/api/assistant/history", methods=["DELETE"])
def assistant_clear():
    raw = request.args.get("thread_id")
    if raw in (None, ""):
        # 不传 thread_id = 明确要清空全部
        assistant.clear_all()
        return jsonify({"success": True})
    try:
        thread_id = int(raw)
    except (TypeError, ValueError):
        # 旧行为：?thread_id=abc 这种转不出整数的值会当成"清空全部"，
        # 一次参数拼错就静默删掉所有会话
        return jsonify({"error": "thread_id 无效"}), 400
    assistant.clear_thread(thread_id)
    return jsonify({"success": True})


# ---- History ----
@main_bp.route("/api/history", methods=["GET"])
def list_history():
    db = get_db()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    # 只挡上限不挡负数时，per_page=-1 会让 SQLite 的 LIMIT -1 变成"返回全表"
    per_page = max(1, min(per_page, 100))
    page = max(1, page)
    offset = (page - 1) * per_page
    q = as_text(request.args.get("q"))
    date_from = as_text(request.args.get("date_from"))
    date_to = as_text(request.args.get("date_to"))

    where_parts, params = [], []
    if q:
        where_parts.append("input_summary LIKE ?")
        params.append(f"%{q}%")
    # 前端一直有日期筛选框，后端原来没有对应参数 —— 选了日期毫无反应
    if date_from:
        where_parts.append("created_at >= ?")
        params.append(date_from)
    if date_to:
        where_parts.append("created_at <= ?")
        params.append(date_to + " 23:59:59")
    where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    total = db.execute(f"SELECT COUNT(*) FROM audit_history {where}", params).fetchone()[0]
    rows = db.execute(
        f"SELECT id, created_at, input_type, input_summary, audit_result FROM audit_history {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [per_page, offset],
    ).fetchall()
    return jsonify({
        "items": [{"id": r["id"], "created_at": r["created_at"], "input_type": r["input_type"],
                   "input_summary": r["input_summary"], "audit_preview": r["audit_result"][:300]} for r in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
    })


@main_bp.route("/api/history/<int:record_id>", methods=["GET"])
def get_history(record_id):
    db = get_db()
    row = db.execute("SELECT * FROM audit_history WHERE id = ?", (record_id,)).fetchone()
    if not row:
        return jsonify({"error": "记录不存在"}), 404
    return jsonify({
        "id": row["id"], "created_at": row["created_at"], "input_type": row["input_type"],
        "input_summary": row["input_summary"], "ocr_text": row["ocr_text"], "audit_result": row["audit_result"],
    })


@main_bp.route("/api/history/<int:record_id>", methods=["DELETE"])
def delete_history(record_id):
    db = get_db()
    cur = db.execute("DELETE FROM audit_history WHERE id = ?", (record_id,))
    if cur.rowcount == 0:
        db.commit()
        return jsonify({"error": "记录不存在"}), 404
    db.execute("DELETE FROM archive WHERE history_id = ?", (record_id,))
    db.commit()
    return jsonify({"success": True})


@main_bp.route("/api/history", methods=["DELETE"])
def clear_all_history():
    """Delete all audit history records."""
    db = get_db()
    # 单条删除会级联删掉关联档案，清空全部却不删 —— 两条路径行为不一致，
    # 清完后档案全成孤儿（关联失效、来源记录永久丢失）。
    # history_id=0 的智能制单档案不属于任何历史记录，保留。
    db.execute("DELETE FROM archive WHERE history_id IN (SELECT id FROM audit_history)")
    db.execute("DELETE FROM audit_history")
    db.commit()
    return jsonify({"success": True, "message": "已清空全部历史记录"})


# ---- Archive Management ----
@main_bp.route("/api/archive", methods=["GET"])
def list_archive():
    filters = {k: request.args.get(k) for k in
               ["invoice_no", "date_from", "date_to", "shipper", "consignee", "operation_type"]
               if request.args.get(k)}
    sort_by = request.args.get("sort_by", "created_at")
    sort_dir = request.args.get("sort_dir", "DESC")
    rows = query_archive(filters, sort_by, sort_dir)
    # 与全站 {success: ...} 契约保持一致：裸数组在出错时会让前端静默空白
    return jsonify({"success": True, "items": [dict(r) for r in rows]})


@main_bp.route("/api/archive/stats", methods=["GET"])
def archive_stats():
    return jsonify({"success": True, "stats": get_archive_stats()})


@main_bp.route("/api/archive/export-excel", methods=["GET"])
def export_archive_excel():
    filters = {k: request.args.get(k) for k in
               ["invoice_no", "date_from", "date_to", "shipper", "consignee", "operation_type"]
               if request.args.get(k)}
    rows = query_archive(filters)
    if not rows:
        return jsonify({"error": "暂无档案数据，无法导出"}), 400
    buf = build_excel(rows)
    month = datetime.now().strftime("%Y%m")
    return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True, download_name=f"档案报表_{month}.xlsx")


@main_bp.route("/api/archive/<int:record_id>", methods=["GET"])
def get_archive_detail(record_id):
    db = get_archive_db()
    row = db.execute("SELECT * FROM archive WHERE id = ?", (record_id,)).fetchone()
    if not row:
        return jsonify({"error": "记录不存在"}), 404
    data = dict(row)
    # If linked to a history record, include the original OCR text and audit from history
    history_id = data.get("history_id", 0)
    if history_id:
        hrow = db.execute("SELECT * FROM audit_history WHERE id = ?", (history_id,)).fetchone()
        if hrow:
            data["linked_history"] = {"id": hrow["id"], "created_at": hrow["created_at"],
                                       "input_type": hrow["input_type"]}
    return jsonify(data)


@main_bp.route("/api/archive", methods=["DELETE"])
def clear_all_archive():
    db = get_archive_db()
    db.execute("DELETE FROM archive")
    db.commit()
    return jsonify({"success": True, "message": "已清空全部档案记录"})


@main_bp.route("/api/archive/<int:record_id>", methods=["DELETE"])
def delete_archive(record_id):
    db = get_archive_db()
    cur = db.execute("DELETE FROM archive WHERE id = ?", (record_id,))
    db.commit()
    if cur.rowcount == 0:
        return jsonify({"error": "记录不存在"}), 404
    return jsonify({"success": True})


# ---- Smart Document Generation ----
# 制单自审用统一的规则表生成提示词（不再单独写一份，免得和主审核规则漂移）：
# 生成的是商业发票 + 装箱单两份，所以跨单据规则在这一步是可执行的。
_GEN_AUDIT_INTRO = ("【本次输入说明】以上两份单证是系统刚刚按表单自动生成的，"
                    "请把它们当作待审单证，审核其自身是否自洽。")


def _validate_generate_payload(data):
    """制单必填项校验，返回错误信息或 None。

    以前前后端都没有校验（表单上的 * 只是装饰）：全空白请求也会拼出一张空单证、
    真调一次 AI 审核、再写一条档案记录 —— 白花钱还留脏数据。
    """
    if not _req_text(data.get("invoice_no")):
        return "请填写发票号 Invoice No"
    if not _req_text(data.get("date")):
        return "请选择日期 Date"

    raw = data.get("goods")
    try:
        rows = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        rows = []
    if not isinstance(rows, list):
        rows = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        if as_text(row.get("name")) and to_dec(row.get("qty")) > 0 and to_dec(row.get("price")) > 0:
            return None
    return "请在货物明细里至少填写一行完整的货物：品名、数量、单价（数量和单价要大于 0）"


@main_bp.route("/api/generate-docs", methods=["POST"])
def generate_documents():
    from services.deepseek_audit import deepseek_audit

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "未提供数据"}), 400

    invalid = _validate_generate_payload(data)
    if invalid:
        return jsonify({"error": invalid}), 400

    try:
        result = generate_docs(data)
    except Exception as e:
        logger.warning("单证生成失败: %s", traceback.format_exc())
        return jsonify({"error": f"生成失败: {str(e)}"}), 400

    # Auto-audit the generated documents
    try:
        audit_result = deepseek_audit(
            result["combined_text"], doc_count=2, intro=_GEN_AUDIT_INTRO,
        )
        if not (audit_result or "").strip():
            audit_result = "（自动审核未返回内容，请手动审核）"
    except Exception:
        logger.warning("Generate-docs auto-audit failed: %s", traceback.format_exc())
        audit_result = "（自动审核暂时不可用，请手动审核）"

    result["audit_result"] = audit_result
    # Auto-archive the generated docs
    try:
        goods_raw = data.get("goods", "[]")
        goods_list = json.loads(goods_raw) if isinstance(goods_raw, str) else (goods_raw if isinstance(goods_raw, list) else [])
        goods_name = goods_list[0].get("name", "") if goods_list else ""
        save_archive({
            "invoice_no": data.get("invoice_no", ""),
            "doc_type": "商业发票+装箱单",
            "shipper_name": data.get("shipper_name", ""),
            "consignee_name": data.get("consignee_name", ""),
            "goods_name": goods_name,
            "total_amount": result.get("grand_total", 0),
            "operation_type": "智能制单",
            "ocr_text": result.get("combined_text", ""),
            "audit_result": audit_result,
        })
    except Exception:
        logger.warning("Generate-docs auto-archive failed: %s", traceback.format_exc())
    return jsonify({"success": True, **result})


@main_bp.route("/api/export-docs-pdf", methods=["POST"])
def export_docs_pdf():
    data = request.get_json(silent=True) or {}
    invoice_text = _req_text(data.get("invoice_text"))
    pl_text = _req_text(data.get("pl_text"))
    invoice_no = _req_text(data.get("invoice_no")) or "单证"

    if not invoice_text and not pl_text:
        return jsonify({"error": "无单证内容"}), 400

    try:
        buf, file_name = generate_docs_pdf(invoice_text, pl_text, invoice_no)
    except Exception:
        logger.warning("单证 PDF 导出失败: %s", traceback.format_exc())
        return jsonify({"error": "导出失败：单证内容无法渲染"}), 500
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=file_name)


# ---- One-Click Fix ----
@main_bp.route("/api/fix-doc", methods=["POST"])
def fix_doc():
    data = request.get_json(silent=True) or {}
    original = _req_text(data.get("original"))
    audit_result = _req_text(data.get("audit_result"))
    if not original or not audit_result:
        return jsonify({"error": "缺少原始内容或审核结果"}), 400

    url = Config.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions"
    prompt = f"""以下是原始单证内容：
{original}

审核发现了以下问题：
{audit_result}

请根据以上问题，输出一份完整的修复后单证，保持原有格式，只修改有问题的字段。
修复后的内容用---修复后单证---标记"""

    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {Config.DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": Config.DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": "你是外贸单证修正专家，根据审核意见输出修复后的单证。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
                # 推理模型思考也占额度，4096 会被吃光导致返回空内容
                "max_tokens": 16384,
            },
            timeout=120,
        )
        resp.raise_for_status()
        try:
            fixed = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError):
            fixed = ""
        if not (fixed or "").strip():
            return jsonify({"error": "AI 未返回修复内容，请重试"}), 502
        return jsonify({"success": True, "fixed_text": fixed})
    except requests.RequestException as e:
        return jsonify({"error": f"API调用失败: {str(e)}"}), 500


# ---- PDF Export ----
@main_bp.route("/api/export-pdf", methods=["POST"])
def export_pdf():
    data = request.get_json(silent=True) or {}
    audit_result = _req_text(data.get("audit_result"))
    if not audit_result:
        return jsonify({"error": "无审核结果"}), 400

    # 标题可由调用方指定：信用证体检的报告不能也叫"审核报告"
    title = _req_text(data.get("title")) or "单智通审核报告"
    try:
        buf, file_name = generate_pdf(audit_result, title=title)
    except Exception:
        logger.warning("审核报告 PDF 导出失败: %s", traceback.format_exc())
        return jsonify({"error": "导出失败：报告内容无法渲染"}), 500
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=file_name)


@main_bp.route("/api/export-fixed-pdf", methods=["POST"])
def export_fixed_pdf():
    """Export AI-fixed invoice/packing list as a proper document PDF (NOT audit report)."""
    data = request.get_json(silent=True) or {}
    fixed_text = _req_text(data.get("fixed_text"))
    if not fixed_text:
        return jsonify({"error": "无修复内容"}), 400

    invoice_no = _req_text(data.get("invoice_no"))
    try:
        buf, file_name = generate_fixed_pdf(fixed_text, invoice_no)
    except Exception:
        logger.warning("修复后单证 PDF 导出失败: %s", traceback.format_exc())
        return jsonify({"error": "导出失败：内容无法渲染"}), 500
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=file_name)


# ============================================================ 实训练习（教育版）
#
# 判卷全程在服务端做，标准答案绝不进 JSON 响应 —— 前端 F12 一看 Network
# 就能拿到答案的话，这个功能等于没做。列表和详情只给「有几处问题」。


@main_bp.route("/api/practice/cases", methods=["GET"])
def practice_cases():
    """题目列表。返回体里只有 answer_count（几处），没有 answer_rules（是哪几处）。"""
    try:
        return jsonify({"success": True, "items": practice.list_cases()})
    except Exception:
        logger.warning("读取练习题列表失败: %s", traceback.format_exc())
        return jsonify({"error": "读取题目失败"}), 500


@main_bp.route("/api/practice/cases/<int:case_id>", methods=["GET"])
def practice_case_detail(case_id):
    """题目详情。同样不含答案 —— 作答页拿到的就是这份数据。"""
    try:
        item = practice.get_case(case_id, with_answer=False)
    except Exception:
        logger.warning("读取练习题失败: %s", traceback.format_exc())
        return jsonify({"error": "读取题目失败"}), 500
    if item is None:
        return jsonify({"error": "题目不存在"}), 404
    return jsonify({"success": True, "case": item})


@main_bp.route("/api/practice/cases", methods=["POST"])
def practice_case_create():
    """新建题目（教师）。答案由调用方给出，可以是 draft 生成的初稿再手改。"""
    data = request.get_json(silent=True) or {}
    title = _req_text(data.get("title"))
    doc_text = _req_text(data.get("doc_text"))
    if not title:
        return jsonify({"error": "请填写题目标题"}), 400
    if not doc_text:
        return jsonify({"error": "请填写单据原文"}), 400

    rules = data.get("answer_rules")
    if not isinstance(rules, list):
        rules = []
    rules = [_req_text(r).upper() for r in rules if _req_text(r)]
    # 只收规则表里真有的编号，别让手滑打进来的字符串污染判卷
    known = {r["id"] for r in AUDIT_RULES}
    unknown = [r for r in rules if r not in known]
    if unknown:
        return jsonify({"error": "无法识别的规则编号：%s" % "、".join(unknown)}), 400

    try:
        case_id = practice.create_case(
            title=title,
            doc_text=doc_text,
            lc_text=_req_text(data.get("lc_text")),
            answer_rules=rules,
            hint=_req_text(data.get("hint")),
            doc_count=1,
        )
    except Exception:
        logger.warning("新建练习题失败: %s", traceback.format_exc())
        return jsonify({"error": "保存题目失败"}), 500
    return jsonify({"success": True, "id": case_id})


@main_bp.route("/api/practice/cases/<int:case_id>", methods=["DELETE"])
def practice_case_delete(case_id):
    try:
        practice.delete_case(case_id)
    except Exception:
        logger.warning("删除练习题失败: %s", traceback.format_exc())
        return jsonify({"error": "删除失败"}), 500
    return jsonify({"success": True})


@main_bp.route("/api/practice/draft", methods=["POST"])
def practice_draft():
    """教师出题用：拿一份单据跑一次审核，把命中的规则编号抽出来当答案初稿。

    这只是一个**初稿**。模型会漏报也会误报，出题人必须对着规则表复核后再保存。
    这是整个练习功能里唯一调用大模型的接口。
    """
    data = request.get_json(silent=True) or {}
    doc_text = _req_text(data.get("doc_text"))
    if not doc_text:
        return jsonify({"error": "请先粘贴单据原文"}), 400
    lc_terms, lc_err = _parse_lc_terms(data.get("lc_terms"))
    if lc_err:
        return jsonify({"error": lc_err}), 400

    try:
        report = deepseek_audit(doc_text, lc_terms)
    except requests.RequestException as e:
        return jsonify({"error": "API 调用失败: %s" % str(e)}), 500
    except Exception:
        logger.warning("出题初稿生成失败: %s", traceback.format_exc())
        return jsonify({"error": "生成失败"}), 500

    # 两个来源合并：问题条目里的编号 + 【本轮执行】里声明的命中编号。
    # 只看前者的话，模型偶尔漏写编号就整条丢了。
    found = {i["rule"] for i in parse_issues(report, source="draft") if i["rule"]}
    tail = parse_report_section(report, "本轮执行") or ""
    # 只认「执行：」那一段。「未执行：R11-R13 R17-R27」列的是本次压根没跑的规则，
    # 把它们收进来会把答案撑成一大串 —— 实测一份只错 1 处的装箱单，
    # 混进未执行清单后建议了 11 条，出题人还得逐条删。
    run_part = re.split(r"未执行", tail)[0]
    for m in re.finditer(r"\b([RL]\d{2})\b", run_part):
        found.add(m.group(1))
    found = sorted(found)

    known = {r["id"] for r in AUDIT_RULES}
    return jsonify({
        "success": True,
        "suggested_rules": [r for r in found if r in known],
        "dropped_rules": [r for r in found if r not in known],
        "report": report,
    })


@main_bp.route("/api/practice/grade", methods=["POST"])
def practice_grade():
    """提交作答并判卷。标准答案只在这个函数里读出来，不返回给前端。"""
    data = request.get_json(silent=True) or {}
    try:
        case_id = int(data.get("case_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "缺少题目编号"}), 400

    picked = data.get("picked")
    if not isinstance(picked, list):
        return jsonify({"error": "作答格式错误"}), 400
    picked = [_req_text(p).upper() for p in picked if _req_text(p)]

    try:
        case = practice.get_case(case_id, with_answer=True)
    except Exception:
        logger.warning("判卷读取题目失败: %s", traceback.format_exc())
        return jsonify({"error": "读取题目失败"}), 500
    if case is None:
        return jsonify({"error": "题目不存在"}), 404

    result = practice.grade(picked, case["answer_rules"])
    result["picked"] = sorted(set(picked))
    try:
        attempt_id = practice.save_attempt(case_id, result)
    except Exception:
        # 成绩存不下不该拦住学生看判卷结果
        logger.warning("保存作答记录失败: %s", traceback.format_exc())
        attempt_id = 0

    # 逐条讲解要用规则表原文，这里一并带上，省得前端再查一次
    detail = {}
    for r in AUDIT_RULES:
        if r["id"] in set(result["hit"]) | set(result["missed"]) | set(result["wrong"]):
            detail[r["id"]] = {
                "name": r["name"], "category": r["category"],
                "severity": r["severity"],
                # 徽标上要显示中文，别让页面冒出 critical / warning 这种英文
                "severity_cn": severity_label(r["severity"]),
                "basis": r["basis"], "check": r["check"], "fix": r["fix"],
            }

    return jsonify({
        "success": True,
        "attempt_id": attempt_id,
        "score": result["score"],
        "hit": result["hit"],
        "missed": result["missed"],
        "wrong": result["wrong"],
        "answer_count": result["answer_count"],
        "picked_count": len(result["picked"]),
        "rules": detail,
    })
