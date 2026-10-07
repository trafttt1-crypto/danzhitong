"""Archive management — auto-classify and store document records."""
import sqlite3
import io
import os
import logging
import re
import traceback
from datetime import datetime
from flask import g
from config.settings import Config
from .doc_generator import as_text, to_dec, to_int

logger = logging.getLogger(__name__)

# "问题1：" / "问题 1:" / "问题2." —— 审核报告的固定格式，全项目统计以此为唯一口径
ISSUE_RE = re.compile(r"问题\s*\d+\s*[：:．.、]\s*(.*)")


def doc_type_from_report(audit_result):
    """从审核报告的【单证类型】小节取单据类型，如「商业发票」「装箱单」。取不到返回空串。

    档案的"单证类型"列原来对所有记录一律写死成「审核报告」，整列没有信息量。
    """
    m = re.search(r"【单证类型】\s*([^\n]+)", audit_result or "")
    if not m:
        return ""
    line = m.group(1).replace("**", "").strip()
    # 模型这一行的写法五花八门（"商业发票（COMMERCIAL INVOICE，发票号…）"、
    # "商业发票 COMMERCIAL INVOICE"、"1. COMMERCIAL INVOICE"、"经识别为商业发票…"），
    # 直接截断会得到"商业发票 COMMERCIAL INVO"这种半截字。先按已知单据名认，认不出再退而求其次。
    for pat, name in _DOC_TYPE_NAMES:
        if re.search(pat, line, re.I):
            return name
    head = re.sub(r"^\d+[.、)）]\s*", "", re.split(r"[（(，,]", line)[0]).strip()
    cn = re.match(r"[一-鿿]+", head)
    return (cn.group(0) if cn else head)[:20]


# (正则, 规范名)：顺序即优先级，更具体的放前面（"形式发票"要先于"商业发票"里的"发票"）
_DOC_TYPE_NAMES = [
    (r"并非外贸单证|非外贸单证|不是外贸单证", "非外贸单证"),
    (r"形式发票|PROFORMA", "形式发票"),
    (r"商业发票|COMMERCIAL\s+INVOICE", "商业发票"),
    (r"装箱单|PACKING\s+LIST", "装箱单"),
    (r"海运提单|BILL\s+OF\s+LADING|\bB/L\b", "提单"),
    (r"提单", "提单"),
    (r"空运单|AIR\s*WAYBILL", "空运单"),
    (r"报关单", "报关单"),
    (r"保险单|INSURANCE\s+POLICY", "保险单"),
    (r"原产地证|CERTIFICATE\s+OF\s+ORIGIN", "原产地证"),
    (r"信用证|LETTER\s+OF\s+CREDIT|MT\s*700", "信用证"),
]


def iter_issues(audit_result):
    """逐条产出"问题N："后面的描述文字。"""
    if not audit_result:
        return []
    return [m.strip() for m in ISSUE_RE.findall(audit_result)]


def count_issues(audit_result):
    """数审核报告里的"问题N："条目。"""
    return len(iter_issues(audit_result))


def has_issue(audit_result):
    """这份审核报告是否发现了问题。

    旧口径是 SQL 里 audit_result LIKE '%问题%'，而报告里必然有【发现问题】
    这个标题，连"未发现明显错误"里的"错误"二字也会命中 —— 结果"发现问题
    单数"恒等于总单数，这个假数字还会被助手当事实讲给用户。
    """
    if count_issues(audit_result):
        return True
    text = audit_result or ""
    m = re.search(r"【审核结论】\s*(.*)", text, re.S)
    conclusion = m.group(1)[:200] if m else ""
    # 先认结论开头的判定词。只做子串匹配的话，「通过（…）：…未发现需修改项」
    # 里的"需修改"会把一份通过的单据记成有问题（实测 #86）
    head = _VERDICT_HEAD_RE.match(conclusion.replace("**", ""))
    if head:
        return head.group(1) not in ("通过", "可接受")
    return ("需修改" in conclusion) or ("不通过" in conclusion)


# 审核结论开头的判定词（提示词规定的写法：通过 / 需修改；体检：可接受 / 建议改证）。
# "不通过"要排在"通过"前面，否则会被当成"通过"
_VERDICT_HEAD_RE = re.compile(r"[\s\-#>]*(不通过|需修改|需修正|建议改证|通过|可接受)")


def extract_doc_fields(ocr_text):
    """对外入口：从单证原文里抽关键字段。

    不符点清单的抬头（发票号、发货人、收货人）就是从这里来的 —— 让业务员
    在导出时再手填一遍发票号，是没必要的手工活。
    """
    return _extract_fields(ocr_text)


# 当事人栏里不该出现的"脏"值：纯标签词、带标签前缀（"Shipper: NINGBO…"）、斜杠残留（"/ Exporter:"）。
# 这些都是早期版本的抽取逻辑留在库里的旧数据，当前抽取器已经不会再产出。
_DIRTY_PARTY_RE = re.compile(r"^\s*(?:/|(?:Shipper|Consignee|Exporter|Importer|Notify)\b)", re.I)


def _is_dirty_party(name):
    return bool(name) and bool(_DIRTY_PARTY_RE.match(name))


def _backfill_archive_fields(db):
    """旧档案两处数据质量问题的回填：单证类型写死成「审核报告」、当事人栏带着标签。

    只改明确错误的行（类型是占位词、当事人名命中 _DIRTY_PARTY_RE），并且只在确有
    要改的行时才动手，动手之前把数据库文件备份一份。幂等：改完再跑不会再命中任何行。
    新值用当前抽取器从原文重算；重算结果本身还是脏的就不动，宁可保留原值。
    """
    rows = db.execute(
        "SELECT id, doc_type, shipper_name, consignee_name, ocr_text, audit_result FROM archive "
        "WHERE doc_type = '审核报告' "
        "OR shipper_name LIKE '/%' OR consignee_name LIKE '/%' "
        "OR shipper_name LIKE 'Shipper%' OR shipper_name LIKE 'Consignee%' "
        "OR shipper_name LIKE 'Exporter%' OR shipper_name LIKE 'Importer%' OR shipper_name LIKE 'Notify%' "
        "OR consignee_name LIKE 'Shipper%' OR consignee_name LIKE 'Consignee%' "
        "OR consignee_name LIKE 'Exporter%' OR consignee_name LIKE 'Importer%' OR consignee_name LIKE 'Notify%'"
    ).fetchall()
    changes = []
    for rid, doc_type, shipper, consignee, ocr_text, audit_result in rows:
        new_type = (doc_type_from_report(audit_result) if doc_type == "审核报告" else doc_type) or doc_type
        new_shipper, new_consignee = shipper, consignee
        if _is_dirty_party(shipper) or _is_dirty_party(consignee):
            try:
                f = _extract_fields(ocr_text)
            except Exception:
                f = {}
            if _is_dirty_party(shipper) and not _is_dirty_party(f.get("shipper_name", "")):
                new_shipper = f.get("shipper_name", "")
            if _is_dirty_party(consignee) and not _is_dirty_party(f.get("consignee_name", "")):
                new_consignee = f.get("consignee_name", "")
        if new_type != doc_type or new_shipper != shipper or new_consignee != consignee:
            changes.append((new_type, new_shipper, new_consignee, rid))
    if not changes:
        return
    try:
        import shutil
        bak = Config.DB_PATH + ".bak-before-archive-backfill"
        if not os.path.exists(bak):
            shutil.copy2(Config.DB_PATH, bak)
    except Exception:
        logger.warning("备份数据库失败，仍继续回填: %s", traceback.format_exc())
    db.executemany(
        "UPDATE archive SET doc_type = ?, shipper_name = ?, consignee_name = ? WHERE id = ?", changes
    )
    logger.info("档案回填：修正了 %d 条记录的单证类型/当事人", len(changes))


def init_archive():
    db = sqlite3.connect(Config.DB_PATH)
    db.execute(
        """CREATE TABLE IF NOT EXISTS archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            history_id INTEGER DEFAULT 0,
            invoice_no TEXT NOT NULL DEFAULT '',
            doc_type TEXT NOT NULL DEFAULT '',
            shipper_name TEXT DEFAULT '',
            consignee_name TEXT DEFAULT '',
            goods_name TEXT DEFAULT '',
            total_amount REAL DEFAULT 0,
            created_at TEXT NOT NULL,
            operation_type TEXT NOT NULL,
            pdf_path TEXT DEFAULT '',
            ocr_text TEXT DEFAULT '',
            audit_result TEXT DEFAULT '',
            has_issue INTEGER DEFAULT 0
        )"""
    )
    # Add column if upgrading from old schema
    try:
        db.execute("ALTER TABLE archive ADD COLUMN history_id INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        db.execute("ALTER TABLE archive ADD COLUMN has_issue INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists
    # 旧数据回填：按当前口径重算，两个方向都纠正（判定口径修过，
    # 以前被误标成 1 的通过单据也要改回 0）。幂等：算出来一样就不写
    for rid, result, old in db.execute(
        "SELECT id, audit_result, has_issue FROM archive"
    ).fetchall():
        new = 1 if has_issue(result) else 0
        if old != new:
            db.execute("UPDATE archive SET has_issue = ? WHERE id = ?", (new, rid))
    _backfill_archive_fields(db)
    db.execute("CREATE INDEX IF NOT EXISTS idx_archive_invoice ON archive(invoice_no)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_archive_created ON archive(created_at)")
    db.commit()
    db.close()


def get_archive_db():
    if "db" not in g:
        g.db = sqlite3.connect(Config.DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def save_archive(record):
    """Insert an archive record. `record` is a dict with keys matching table columns."""
    db = get_archive_db()
    audit_result = as_text(record.get("audit_result"))
    db.execute(
        """INSERT INTO archive (history_id, invoice_no, doc_type, shipper_name, consignee_name,
           goods_name, total_amount, created_at, operation_type, pdf_path, ocr_text, audit_result, has_issue)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            to_int(record.get("history_id")),
            as_text(record.get("invoice_no")),
            as_text(record.get("doc_type")),
            as_text(record.get("shipper_name")),
            as_text(record.get("consignee_name")),
            as_text(record.get("goods_name")),
            float(to_dec(record.get("total_amount"))),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            as_text(record.get("operation_type")),
            as_text(record.get("pdf_path")),
            as_text(record.get("ocr_text")),
            audit_result,
            1 if has_issue(audit_result) else 0,
        ),
    )
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def query_archive(filters=None, sort_by="created_at", sort_dir="DESC"):
    """Query archive with optional filters and sorting."""
    db = get_archive_db()
    where = ["1=1"]
    params = []

    if filters:
        if filters.get("invoice_no"):
            where.append("invoice_no LIKE ?")
            params.append(f"%{filters['invoice_no']}%")
        if filters.get("date_from"):
            where.append("created_at >= ?")
            params.append(filters["date_from"])
        if filters.get("date_to"):
            where.append("created_at <= ?")
            params.append(filters["date_to"] + " 23:59:59")
        if filters.get("shipper"):
            where.append("shipper_name LIKE ?")
            params.append(f"%{filters['shipper']}%")
        if filters.get("consignee"):
            where.append("consignee_name LIKE ?")
            params.append(f"%{filters['consignee']}%")
        if filters.get("operation_type"):
            where.append("operation_type = ?")
            params.append(filters["operation_type"])

    allowed_sort = {"created_at", "total_amount", "invoice_no"}
    if sort_by not in allowed_sort:
        sort_by = "created_at"
    if sort_dir.upper() not in ("ASC", "DESC"):
        sort_dir = "DESC"

    sql = f"SELECT * FROM archive WHERE {' AND '.join(where)} ORDER BY {sort_by} {sort_dir} LIMIT 500"
    return db.execute(sql, params).fetchall()


def get_archive_stats():
    """Return summary statistics."""
    db = get_archive_db()
    month = datetime.now().strftime("%Y-%m")

    month_count = db.execute(
        "SELECT COUNT(*) FROM archive WHERE created_at LIKE ?", (f"{month}%",)
    ).fetchone()[0]

    month_errors = db.execute(
        "SELECT COUNT(*) FROM archive WHERE created_at LIKE ? AND has_issue = 1",
        (f"{month}%",),
    ).fetchone()[0]

    total_count = db.execute("SELECT COUNT(*) FROM archive").fetchone()[0]

    total_amount = db.execute("SELECT COALESCE(SUM(total_amount), 0) FROM archive").fetchone()[0]

    return {
        "month_count": month_count,
        "month_errors": month_errors,
        "total_count": total_count,
        "total_amount": round(total_amount, 2),
    }


def build_excel(records):
    """Generate an Excel workbook from archive records."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    wb = Workbook()
    ws = wb.active
    ws.title = "单证档案"

    headers = [
        "ID", "发票号", "单证类型", "发货人", "收货人",
        "货物品名", "总金额(USD)", "操作时间", "操作类型"
    ]
    header_font = Font(bold=True, size=11)
    header_fill = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border

    for row_idx, r in enumerate(records, 2):
        values = [
            r["id"], r["invoice_no"], r["doc_type"], r["shipper_name"],
            r["consignee_name"], r["goods_name"], r["total_amount"],
            r["created_at"], r["operation_type"],
        ]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row_idx, column=col, value=val)
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center" if col in (1, 7, 9) else "left")

    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 12
    ws.column_dimensions["D"].width = 22
    ws.column_dimensions["E"].width = 22
    ws.column_dimensions["F"].width = 20
    ws.column_dimensions["G"].width = 14
    ws.column_dimensions["H"].width = 20
    ws.column_dimensions["I"].width = 12

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# 当事人栏的标签词。OCR 常把中英标签连着写（"发货人Shipper"、"Shipper/Exporter"），
# 紧跟在标签后面的这些词、斜杠、冒号、空白（含换行）都要一起吃掉，剩下才是公司名。
# 旧写法只认「标签 + 冒号」，遇到"发货人Shipper\nNINGBO…"会把 "Shipper" 当成公司名存进档案。
_PARTY_LABELS = r'(?:Shipper|Exporter|Consignee|Importer|Notify|发货人|收货人|出口商|进口商)'


def _value_after_label(text, label_pattern):
    m = re.search(label_pattern, text, re.I)
    if not m:
        return ""
    rest = text[m.end():]
    # 标签后面还可能跟一段括号注释："Consignee (Buyer): AL NOOR…"
    rest = re.sub(r'^(?:\s|[/／：:.]|\([^)\n]{1,20}\)|（[^）\n]{1,20}）|%s)+' % _PARTY_LABELS, '', rest, flags=re.I)
    value = rest.split("\n", 1)[0].strip()
    # 这一栏在原文里是空的，紧跟着的是下一个栏目的标签（"Port of Loading:"、"日期 Date"）：
    # 宁可留空也不能把标签当成公司名存进档案
    if re.search(r'[:：]\s*$', value) or re.match(
            r'(?:Port|Date|Invoice|Payment|Trade|Terms|Description|Total|Notify|Marks|Goods|'
            r'日期|发票|付款|贸易|装运|目的|货物|总)', value, re.I):
        return ""
    return value


def _extract_fields(ocr_text):
    """从 OCR 文本里抽关键字段。每个字段独立兜底，一个抽不到不影响其它。"""
    text = ocr_text or ""

    invoice_no = ""
    # 中文单证用的是全角冒号「：」，旧正则只认半角，导致发票号大面积为空；
    # "Invoice No." 带点也要能匹配。
    #
    # 分两趟找，是因为中英双标签的写法「发票号 Invoice No.: INV-2024-0508」：
    # 分隔符里一旦允许空白，"发票号"后面的那个空格就算分隔符，抓到的会是
    # 紧跟其后的英文标签 "Invoice" —— 银行清单抬头上印个 "Invoice" 当发票号，
    # 比空着还糟。所以先按"必须有冒号/句点"找，找不到再放宽，且要求抓到的值
    # 里含数字（发票号几乎必然带数字，光一个英文单词不算）。
    _INV_LABEL = r'(?:Invoice\s+No\.?|发票号|INV[-\s]*NO\.?)'
    for pat in (r'%s\s*[：:.]\s*([A-Za-z0-9\-/_]+)' % _INV_LABEL,
                r'%s\s+([A-Za-z0-9\-/_]+)' % _INV_LABEL):
        for m in re.finditer(pat, text, re.I):
            if any(ch.isdigit() for ch in m.group(1)):
                invoice_no = m.group(1)
                break
        if invoice_no:
            break

    shipper = _value_after_label(text, r'(?:Shipper|Exporter|发货人|出口商)')[:80]
    consignee = _value_after_label(text, r'(?:Consignee|Importer|收货人|进口商)')[:80]

    goods = ""
    m = re.search(r'(?:\d+\.\s*|品名[：:]\s*)([A-Za-z一-鿿\s\-]+)', text)
    if m:
        goods = m.group(1).strip()[:60]

    total = 0.0
    # (\d[\d,]*...) 要求以数字开头：旧写法 [\d,]+ 能匹配到一个孤零零的逗号，
    # 随后 float("") 抛异常，把整条档案（连 OCR 原文）一起丢掉
    m = re.search(r'(?:Grand\s+Total|Total\s+Amount|总金额|合计)\s*[：:]*\s*(?:USD|US\$|\$)?\s*(\d[\d,]*(?:\.\d+)?)', text, re.I)
    if m:
        total = float(m.group(1).replace(",", ""))

    return {
        "invoice_no": invoice_no,
        "shipper_name": shipper,
        "consignee_name": consignee,
        "goods_name": goods,
        "total_amount": total,
    }


def auto_archive_text(ocr_text, audit_result, operation_type, history_id=0):
    """Auto-archive from OCR text by extracting key fields."""
    fields = {}
    try:
        fields = _extract_fields(ocr_text)
    except Exception:
        # 字段抽不出来也要把原文和审核结论存下来，不能整条丢
        logger.warning("字段提取失败，仅保存原文: %s", traceback.format_exc())

    save_archive({
        "history_id": history_id,
        "invoice_no": fields.get("invoice_no", ""),
        "doc_type": doc_type_from_report(audit_result) or "审核报告",
        "shipper_name": fields.get("shipper_name", ""),
        "consignee_name": fields.get("consignee_name", ""),
        "goods_name": fields.get("goods_name", ""),
        "total_amount": fields.get("total_amount", 0.0),
        "operation_type": operation_type,
        "ocr_text": ocr_text,
        "audit_result": audit_result,
    })
