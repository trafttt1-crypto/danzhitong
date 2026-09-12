import io
import logging
import re
import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.colors import HexColor
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from config.settings import Config

logger = logging.getLogger(__name__)

# ---- Multi-platform font discovery ----
_FONT_DIRS = [
    Config.FONT_PATH,                          # 1) Project fonts/ folder
    "/usr/share/fonts/truetype",               # 2) Linux
    "/usr/share/fonts",                        #    Linux fallback
    "/usr/local/share/fonts",                  #    Linux manual installs
    "/Library/Fonts",                          # 3) macOS
    "C:/Windows/Fonts",                        # 4) Windows
]

_CN_FONT = "Helvetica"
_EU_FONT = "Helvetica"
_FONT_OK = False


def _find_font(candidates):
    for name in candidates:
        for d in _FONT_DIRS:
            path = os.path.join(d, name)
            if os.path.exists(path):
                yield path


def _register_first_working(candidates, alias):
    """逐个候选尝试注册，跳过 reportlab 不支持的字体（如 CFF/PostScript 轮廓的 .otf）。

    旧写法只取第一个存在的文件直接注册，撞上不支持的格式会在模块导入期抛异常，
    整个应用起不来，而报错信息跟"放了个字体文件"看起来毫无关系。
    """
    for path in _find_font(candidates):
        try:
            pdfmetrics.registerFont(TTFont(alias, path))
            return path
        except Exception as e:
            logger.warning("字体不可用，跳过 %s：%s", path, e)
    return None


# Chinese font: SimHei / WenQuanYi / Noto Sans CJK（Windows 实际文件名是 .ttc，不是 .ttf）
_cn_candidates = ["simhei.ttf", "SimHei.ttf", "msyh.ttc", "msyhbd.ttc", "msyh.ttf", "msyhbd.ttf",
                  "simsun.ttc", "wqy-microhei.ttc", "wqy-zenhei.ttc",
                  "NotoSansCJK-Regular.ttc", "NotoSansSC-Regular.otf",
                  "NotoSansCJKsc-Regular.otf"]
_cn_path = _register_first_working(_cn_candidates, "SimHei")
if _cn_path:
    _CN_FONT = "SimHei"
    _FONT_OK = True

# European font: Arial / DejaVu Sans / Liberation Sans
_eu_candidates = ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf",
                  "DejaVuSansMono.ttf", "FreeSans.ttf"]
_eu_path = _register_first_working(_eu_candidates, "ArialUni")
if _eu_path:
    _EU_FONT = "ArialUni"
else:
    _EU_FONT = _CN_FONT  # fallback to Chinese font or Helvetica

if not _FONT_OK:
    logger.warning(
        "No Chinese font found. PDF export will not render Chinese characters. "
        "Place simhei.ttf or msyh.ttc in the fonts/ directory. "
        "Searched: %s", _FONT_DIRS)


def _strip_md(text):
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    return text


def _esc_xml(text):
    """ReportLab 把文本当 XML 解析：& < > 都必须转义。

    旧版只转了 < 和 >，漏了 &（R&D 会渲染成 R&D;）；未转义的 <字母 会直接抛
    ValueError 让导出 500。
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _parse_section(text, heading):
    """取【heading】这一节的内容，遇到下一个【标题】就停。

    旧实现用 split 后取 parts[1]，那是"从此标题一直到文末"，
    导出的报告里每个章节下面都跟着整篇全文，重复约 5 遍。
    """
    if not text:
        return ""
    m = re.search(r"【%s】\s*(.*?)(?=\n?\s*【|\Z)" % re.escape(heading), text, re.S)
    return m.group(1).strip() if m else ""


# 报告里可能出现的小节，按显示顺序排列。
# 审核报告用前五个里的四个，信用证体检报告用后几个 —— 同一份列表，
# 各自缺的节自动跳过，省得两套代码各维护一份还会漂移。
REPORT_SECTIONS = [
    "单证类型", "信用证概要",
    "发现问题", "风险条款",
    "数学验算", "时间安排", "单据要求清单",
    "风险提示",
    "审核结论",
]


def parse_report_section(text, heading):
    """对外入口：取报告里【heading】这一节的内容。"""
    return _parse_section(text, heading)


def generate_pdf(audit_result, title="单智通审核报告"):
    now = datetime.now()
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")
    file_name = f"审核报告_{now.strftime('%Y%m%d_%H%M%S')}.pdf"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=45, rightMargin=45, topMargin=45, bottomMargin=50,
    )

    cn_body = ParagraphStyle("CNBody", fontName=_CN_FONT, fontSize=10.5, leading=18, spaceAfter=6)
    cn_title = ParagraphStyle("CNTitle", fontName=_CN_FONT, fontSize=20, leading=28, alignment=TA_CENTER, spaceAfter=20)
    cn_h2 = ParagraphStyle("CNH2", fontName=_CN_FONT, fontSize=13, leading=20, spaceBefore=14, spaceAfter=6)
    cn_footer = ParagraphStyle("CNFooter", fontName=_CN_FONT, fontSize=9, leading=14, alignment=TA_CENTER, textColor=HexColor("#94a3b8"))

    story = []
    story.append(Paragraph(_esc_xml(title), cn_title))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"生成时间：{time_str}", cn_body))
    story.append(Spacer(1, 10))

    for heading in REPORT_SECTIONS:
        content = _parse_section(audit_result, heading)
        if not content:
            continue
        story.append(Paragraph(heading, cn_h2))
        for line in content.split("\n"):
            line = line.strip()
            if not line:
                continue
            story.append(Paragraph(_esc_xml(_strip_md(line)), cn_body))
        story.append(Spacer(1, 4))

    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#e2e8f0")))
    story.append(Spacer(1, 6))
    story.append(Paragraph("本文件由单智通生成，受软件著作权保护", cn_footer))
    story.append(Paragraph(f"生成时间：{time_str}", cn_footer))
    story.append(Spacer(1, 4))
    story.append(Paragraph("本报告由AI生成，仅供参考，最终以人工确认为准", cn_footer))

    doc.build(story)
    buf.seek(0)
    return buf, file_name


def _mono_para(text, style, indent=0):
    """等宽排版：先做 XML 转义，再把空格换成 &nbsp; 保住对齐。

    缩进单独用 indent 传进来 —— 拼好的 &nbsp; 是标记不是内容，不能跟着一起被转义。
    """
    return Paragraph("&nbsp;" * indent + _esc_xml(text).replace(" ", "&nbsp;"), style)


def generate_docs_pdf(invoice_text, pl_text, invoice_no):
    """Generate a clean PDF containing both Commercial Invoice and Packing List."""
    now = datetime.now()
    time_str = now.strftime("%Y%m%d_%H%M%S")
    file_name = f"{invoice_no or '单证'}_{time_str}.pdf"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40,
    )

    cn_mono = ParagraphStyle("CNMono", fontName=_EU_FONT, fontSize=8.5, leading=12, spaceAfter=1)
    cn_title = ParagraphStyle("DocTitle", fontName=_CN_FONT, fontSize=16, leading=22, alignment=TA_CENTER, spaceAfter=6)
    cn_sub = ParagraphStyle("DocSub", fontName=_CN_FONT, fontSize=9, leading=14, alignment=TA_CENTER, textColor=HexColor("#64748b"), spaceAfter=16)
    cn_footer = ParagraphStyle("DocFooter", fontName=_CN_FONT, fontSize=8, leading=12, alignment=TA_CENTER, textColor=HexColor("#94a3b8"))

    story = []

    def _render_block(text, title_label):
        story.append(Paragraph(title_label, cn_title))
        story.append(Paragraph(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", cn_sub))
        for line in text.split("\n"):
            line = line.rstrip()
            # 前导空格作为缩进，走 indent 参数
            stripped = line.lstrip(" ")
            story.append(_mono_para(stripped, cn_mono, len(line) - len(stripped)))
        story.append(Spacer(1, 20))

    _render_block(invoice_text, "Commercial Invoice 商业发票")
    _render_block(pl_text, "Packing List 装箱单")

    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#e2e8f0")))
    story.append(Spacer(1, 6))
    story.append(Paragraph("本文件由单智通生成，受软件著作权保护", cn_footer))
    story.append(Paragraph(f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", cn_footer))
    story.append(Spacer(1, 4))
    story.append(Paragraph("本单证由单智通AI生成，仅供参考，最终以人工确认为准", cn_footer))

    doc.build(story)
    buf.seek(0)
    return buf, file_name


def generate_fixed_pdf(fixed_text, invoice_no=""):
    """Generate PDF for AI-corrected invoice/packing list — document format, NOT audit report."""
    now = datetime.now()
    time_str = now.strftime("%Y%m%d_%H%M%S")
    file_name = f"修复后单证_{invoice_no or '单证'}_{time_str}.pdf"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40,
    )

    cn_mono = ParagraphStyle("FixMono", fontName=_EU_FONT, fontSize=8.5, leading=12, spaceAfter=1)
    cn_title = ParagraphStyle("FixTitle", fontName=_CN_FONT, fontSize=16, leading=22, alignment=TA_CENTER, spaceAfter=6)
    cn_sub = ParagraphStyle("FixSub", fontName=_CN_FONT, fontSize=9, leading=14, alignment=TA_CENTER, textColor=HexColor("#64748b"), spaceAfter=16)
    cn_footer = ParagraphStyle("FixFooter", fontName=_CN_FONT, fontSize=8, leading=12, alignment=TA_CENTER, textColor=HexColor("#94a3b8"))

    story = []
    story.append(Paragraph("修复后单证 / Corrected Invoice", cn_title))
    story.append(Paragraph(f"修复时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", cn_sub))

    # Strip markdown and AI markup artifacts
    clean = fixed_text
    clean = re.sub(r"---修复后单证---", "", clean)
    clean = re.sub(r"\*\*(.+?)\*\*", r"\1", clean)
    clean = re.sub(r"\*(.+?)\*", r"\1", clean)

    for line in clean.split("\n"):
        line = line.rstrip()
        if not line.strip():
            story.append(Spacer(1, 6))
            continue
        stripped = line.lstrip(" ")
        story.append(_mono_para(stripped, cn_mono, len(line) - len(stripped)))

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#e2e8f0")))
    story.append(Spacer(1, 6))
    story.append(Paragraph("本文件由单智通生成，受软件著作权保护", cn_footer))
    story.append(Paragraph(f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", cn_footer))
    story.append(Spacer(1, 4))
    story.append(Paragraph("本文件由AI修复生成，请人工确认后使用", cn_footer))

    doc.build(story)
    buf.seek(0)
    return buf, file_name


def generate_discrepancy_pdf(items, meta=None):
    """按银行交单的「不符点清单」格式导出。

    items 来自 services/discrepancy.py:parse_issues()，meta 放抬头信息。
    条目为空直接抛 ValueError —— 一张空白清单交到银行手里毫无意义，
    让路由层给出明确提示比导出一份空表好。
    """
    if not items:
        raise ValueError("没有解析到不符点条目")

    meta = meta or {}
    now = datetime.now()
    file_name = "不符点清单_%s.pdf" % now.strftime("%Y%m%d_%H%M%S")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=45, rightMargin=45, topMargin=45, bottomMargin=50,
    )

    cn_title = ParagraphStyle("DTitle", fontName=_CN_FONT, fontSize=18, leading=26,
                              alignment=TA_CENTER, spaceAfter=2)
    cn_sub = ParagraphStyle("DSub", fontName=_EU_FONT, fontSize=9, leading=14,
                            alignment=TA_CENTER, textColor=HexColor("#64748b"), spaceAfter=14)
    cn_body = ParagraphStyle("DBody", fontName=_CN_FONT, fontSize=10.5, leading=18, spaceAfter=6)
    cn_meta = ParagraphStyle("DMeta", fontName=_CN_FONT, fontSize=10, leading=16)
    cn_th = ParagraphStyle("DTH", fontName=_CN_FONT, fontSize=10, leading=15,
                           textColor=HexColor("#ffffff"))
    cn_td = ParagraphStyle("DTD", fontName=_CN_FONT, fontSize=9.5, leading=15)
    cn_td_sm = ParagraphStyle("DTDSm", fontName=_CN_FONT, fontSize=8, leading=12,
                              textColor=HexColor("#475569"))
    cn_footer = ParagraphStyle("DFooter", fontName=_CN_FONT, fontSize=9, leading=14,
                               alignment=TA_CENTER, textColor=HexColor("#94a3b8"))

    story = []
    story.append(Paragraph("不符点清单", cn_title))
    story.append(Paragraph("DISCREPANCY LIST", cn_sub))

    # 抬头：能抽到的就填，抽不到的留横线给人工写
    pairs = [
        ("发票号 Invoice No.", meta.get("invoice_no")),
        ("单证类型 Document", meta.get("doc_type")),
        ("发货人 Shipper", meta.get("shipper")),
        ("收货人 Consignee", meta.get("consignee")),
    ]
    header_rows = []
    for label, value in pairs:
        header_rows.append(Paragraph(
            "<b>%s</b>：%s" % (_esc_xml(label), _esc_xml(value or "________________")), cn_meta))
    story.append(header_rows[0])
    story.append(header_rows[1])
    story.append(header_rows[2])
    story.append(header_rows[3])
    story.append(Spacer(1, 12))

    head = [Paragraph("序号", cn_th), Paragraph("涉及位置", cn_th),
            Paragraph("不符点描述", cn_th), Paragraph("修改建议", cn_th),
            Paragraph("依据", cn_th)]
    rows = [head]
    for it in items:
        rows.append([
            Paragraph(str(it.get("no", "")), cn_td),
            Paragraph(_esc_xml(_strip_md(it.get("location") or "—")), cn_td),
            Paragraph(_esc_xml(_strip_md(it.get("desc") or "")), cn_td),
            Paragraph(_esc_xml(_strip_md(it.get("suggestion") or "—")), cn_td),
            Paragraph(_esc_xml(_strip_md(it.get("basis") or "—")), cn_td_sm),
        ])

    table = Table(rows, colWidths=[30, 72, 158, 158, 87], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#1D3AF0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        # 隔行浅底，长表格不容易看串行
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#ffffff"), HexColor("#f8fafc")]),
    ]))
    story.append(table)
    story.append(Spacer(1, 12))

    story.append(Paragraph("共 %d 条不符点，建议全部修改后再行交单。" % len(items), cn_body))
    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor("#e2e8f0")))
    story.append(Spacer(1, 6))
    story.append(Paragraph("本文件由单智通生成，受软件著作权保护", cn_footer))
    story.append(Paragraph("生成时间：%s" % now.strftime("%Y-%m-%d %H:%M:%S"), cn_footer))
    story.append(Spacer(1, 4))
    story.append(Paragraph("本清单由AI生成，仅供参考，最终以银行审单结论为准", cn_footer))

    doc.build(story)
    buf.seek(0)
    return buf, file_name
