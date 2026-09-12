"""Archive management — auto-classify and store document records."""
import sqlite3
import io
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
    return ("需修改" in conclusion) or ("不通过" in conclusion)


def extract_doc_fields(ocr_text):
    """对外入口：从单证原文里抽关键字段。

    不符点清单的抬头（发票号、发货人、收货人）就是从这里来的 —— 让业务员
    在导出时再手填一遍发票号，是没必要的手工活。
    """
    return _extract_fields(ocr_text)


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
    # 旧数据回填：只把该标 1 的补上，幂等且可自愈
    for rid, result in db.execute(
        "SELECT id, audit_result FROM archive WHERE has_issue IS NULL OR has_issue = 0"
    ).fetchall():
        if has_issue(result):
            db.execute("UPDATE archive SET has_issue = 1 WHERE id = ?", (rid,))
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

    # 中英双标签时，去掉粘在前面的英文标签（"Shipper: NINGBO ..." → "NINGBO ..."）
    _LEAD_LABEL_RE = re.compile(r'^(?:Shipper|Exporter|Consignee|Importer|发货人|收货人)\s*[：:.]\s*', re.I)

    shipper = ""
    m = re.search(r'(?:Shipper|Exporter|发货人)\s*[：:]*\s*\n?\s*(.+)', text, re.I)
    if m:
        shipper = _LEAD_LABEL_RE.sub("", m.group(1).strip())[:80]

    consignee = ""
    m = re.search(r'(?:Consignee|Importer|收货人)\s*[：:]*\s*\n?\s*(.+)', text, re.I)
    if m:
        consignee = _LEAD_LABEL_RE.sub("", m.group(1).strip())[:80]

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
        "doc_type": "审核报告",
        "shipper_name": fields.get("shipper_name", ""),
        "consignee_name": fields.get("consignee_name", ""),
        "goods_name": fields.get("goods_name", ""),
        "total_amount": fields.get("total_amount", 0.0),
        "operation_type": operation_type,
        "ocr_text": ocr_text,
        "audit_result": audit_result,
    })
