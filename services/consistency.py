# -*- coding: utf-8 -*-
"""单证一致性比对：把信用证、发票、装箱单、提单的同一字段排在一起，逐项判断对不对得上。

银行审单的核心原则是「单证相符、单单相符」：单据要和信用证相符，单据之间也要互相相符。
这个模块把这件事做成一张可以看的图 —— 但**全程是确定性的代码，不调用大模型**：

  - 字段用正则从原文里抽，抽不到就是「未提取」，不猜；
  - 比对用规范化后的字符串/数值，规则写死，同样的输入永远得同样的图；
  - 结果分四档：一致 / 近似（疑似拼写差异）/ 不一致 / 未提取。

设计上最怕的是"图是错的"。所以宁可多画灰色的「未提取」，也不能把抽取失败画成红色的「不一致」：
只有两边都**明确抽到了值**、并且确实对不上，才会标红。

纯函数，不碰数据库、不联网，方便单元测试（见 tests/test_consistency.py）。
"""
import re
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

# ============================================================ 字段定义
# key -> (中文名, 类型)。类型决定怎么规范化、怎么比。
FIELDS = [
    ("invoice_no", "发票号", "ref"),
    ("date", "日期", "date"),
    ("shipper", "发货人 / 受益人", "party"),
    ("consignee", "收货人 / 申请人", "party"),
    ("port_loading", "装运港", "port"),
    ("port_discharge", "目的港", "port"),
    ("trade_terms", "贸易术语", "term"),
    ("currency", "币别", "currency"),
    ("amount", "总金额", "amount"),
    ("goods", "品名", "goods"),
    ("quantity", "数量", "number"),
    ("packages", "件数", "number"),
    ("gross_weight", "毛重", "number"),
    ("net_weight", "净重", "number"),
    ("measurement", "体积", "number"),
    ("marks", "唛头", "marks"),
]
FIELD_LABEL = {k: n for k, n, _ in FIELDS}
FIELD_KIND = {k: t for k, _, t in FIELDS}

DOC_LABEL = {"lc": "信用证", "invoice": "商业发票", "packing": "装箱单", "bl": "提单", "unknown": "未识别单证"}
DOC_ORDER = ["lc", "invoice", "packing", "bl", "unknown"]

# 各字段在原文里可能出现的标签（中英文都要认；长的放前面，避免短标签抢先匹配）
LABELS = {
    "invoice_no": ["发票号码", "发票号", "Invoice\\s*No\\.?", "INV\\.?\\s*NO\\.?", "Invoice\\s*Number", "Ref\\.?\\s*No\\.?"],
    "date": ["发票日期", "日期", "Date\\s+of\\s+Issue", "Invoice\\s*Date", "Date"],
    "shipper": ["发货人", "出口商", "受益人", "Shipper\\s*/\\s*Exporter", "Shipper", "Exporter", "Beneficiary"],
    "consignee": ["收货人", "进口商", "申请人", "开证申请人", "Consignee", "Importer", "Applicant"],
    "port_loading": ["装运港", "起运港", "Port\\s+of\\s+Loading", "Loading\\s+Port", "From\\s+Port"],
    "port_discharge": ["目的港", "卸货港", "Port\\s+of\\s+Discharge", "Discharge\\s+Port", "Destination", "To\\s+Port"],
    "trade_terms": ["贸易术语", "成交方式", "Trade\\s*Terms", "Incoterms?", "Terms\\s+of\\s+Delivery"],
    "amount": ["总金额", "总价", "金额", "信用证金额", "Total\\s+Amount", "Grand\\s+Total", "Invoice\\s+Amount", "Amount", "Credit\\s+Amount"],
    "goods": ["货物描述", "货描", "品名", "Description\\s+of\\s+Goods", "Goods\\s+Description", "Description", "Goods"],
    "quantity": ["数量", "Quantity", "Qty"],
    "packages": ["件数", "总件数", "Total\\s+Packages", "No\\.?\\s*of\\s+Packages", "Packages", "Cartons"],
    "gross_weight": ["毛重", "Gross\\s+Weight", "G\\.?\\s*W\\.?"],
    "net_weight": ["净重", "Net\\s+Weight", "N\\.?\\s*W\\.?"],
    "measurement": ["体积", "尺码", "Measurement", "Volume", "CBM"],
    "marks": ["唛头", "Shipping\\s+Marks?", "Marks\\s*(?:&|and)\\s*Numbers?", "Marks"],
}
# 「换行后才是值」的字段里，下一行如果长得像另一个标签，说明这一栏在原文里是空的
_ALL_LABELS = sorted({p for ps in LABELS.values() for p in ps}, key=len, reverse=True)
_LABEL_START_RE = re.compile(r"^\s*(?:%s)\b" % "|".join(_ALL_LABELS), re.I)
# 不在可比字段里、但同样会出现在单证里的标签。列得具体（"Port of …"、"Total …"），
# 不写裸的 "Port"/"Total"，免得把 "PORT LOGISTICS CO" 这种公司名当成标签丢掉。
_EXTRA_LABEL_RE = re.compile(
    r"^\s*(?:Payment|付款方式|Port\s+of\s+\w+|装运日期|Shipment\s+Date|Total\s+\w+|合计|Unit\s*Price|单价|单位|"
    r"Notify(?:\s+Party)?|通知人|B/L\s*No|Vessel|Signed|签署|Bank|开户行)\b", re.I)


def _is_other_label(line):
    """这一行是不是另一栏的标签行（说明前一栏在原文里是空的）。"""
    return bool(_LABEL_START_RE.match(line) or _EXTRA_LABEL_RE.match(line))


# ============================================================ 单证类型识别
def detect_type(text):
    """按关键词判断是哪种单证。判断不了返回 unknown，不硬猜。"""
    t = text or ""
    head = t[:600]
    scores = {
        "lc": len(re.findall(r"MT\s*700|信用证|LETTER\s+OF\s+CREDIT|:\s*(?:40A|31D|32B|44E|44F)\s*:|DOCUMENTARY\s+CREDIT", t, re.I)),
        "invoice": len(re.findall(r"COMMERCIAL\s+INVOICE|商业发票|发票号|Invoice\s*No", head, re.I)) * 2
                   + len(re.findall(r"Total\s+Amount|Unit\s+Price|单价", t, re.I)),
        "packing": len(re.findall(r"PACKING\s+LIST|装箱单|Gross\s+Weight|Net\s+Weight|毛重|净重", t, re.I)),
        "bl": len(re.findall(r"BILL\s+OF\s+LADING|提单|B/L\s*No|Vessel|Notify\s+Party|SHIPPED\s+ON\s+BOARD", t, re.I)) * 2,
    }
    # 标题行优先：开头 600 字里直接写了单证名，比正文里零星出现的词可靠得多
    if re.search(r"PACKING\s+LIST|装箱单", head, re.I):
        scores["packing"] += 6
    if re.search(r"COMMERCIAL\s+INVOICE|商业发票", head, re.I):
        scores["invoice"] += 6
    if re.search(r"BILL\s+OF\s+LADING|提单", head, re.I):
        scores["bl"] += 6
    if re.search(r"MT\s*700|信用证|LETTER\s+OF\s+CREDIT", head, re.I):
        scores["lc"] += 6
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= 2 else "unknown"


# ============================================================ 抽取
def _first_line_value(rest):
    """标签之后的文本里取值：先吃掉冒号、空白、斜杠，再取第一行；空就取下一行。"""
    rest = re.sub(r"^(?:\s|[:：./])+", "", rest)
    lines = [ln.strip() for ln in rest.split("\n")]
    # 第一行就有内容（"Label: value"）
    if lines and lines[0]:
        return lines[0], lines[1:]
    return "", [ln for ln in lines if ln]


# 值里出现这些词，说明已经串到同一行的下一栏去了（"GTL/DUBAI/1-100 备注 Remarks: …"），在这里截断
_INLINE_LABEL_RE = re.compile(
    r"\s+(?:备注|Remarks?\b|提单收货人|B/L\s+Cons|Notify\b|通知人|付款方式|Payment\b|Signed\b|签署)", re.I)


def _clean_value(key, value):
    """抽出来的值可信吗？不可信就返回空串（= 未提取，画成灰色），绝不猜。

    这是整个模块最关键的一道闸：表格排版、PDF 转出来的单据里，标签和值之间可能隔着表头、
    虚线、别的列。抽错了一个值，图上就会多一条假的红线 —— 宁可空着也不能画错。
    """
    if not value:
        return ""
    # 表格列：一行里出现多段 3 个以上的连续空格，说明是按列对齐的表格行，值取不准
    if len(re.findall(r"\S\s{3,}(?=\S)", value)) >= 3:
        return ""
    m = _INLINE_LABEL_RE.search(value)
    if m:
        value = value[:m.start()]
    value = re.sub(r"\s+", " ", value).strip(" 	:：-=_*")
    if not value:
        return ""
    # 大半是虚线、等号、括号之类的装饰字符
    body = sum(1 for ch in value if ch.isalnum() or "一" <= ch <= "鿿")
    if body / float(len(value)) < 0.5:
        return ""
    # 数值、金额、日期类字段必须带数字（"(KGS) N.W.(KGS)" 这种表头残片不是值）
    if FIELD_KIND.get(key) in ("number", "amount", "date") and not re.search(r"\d", value):
        return ""
    return value


def _grab(text, field, multiline=False):
    """按标签找值。找不到、或这一栏是空的（下一行是别的标签）返回空串。"""
    for label in LABELS[field]:
        # 中文标签后面常常直接贴着英文标签（"发货人Shipper"），所以中文标签不要求后面有分隔符；
        # 英文标签仍要求，免得 "Date" 匹配到 "Dated" 之类
        tail = r"(?=[\s:：./（(]|$)" if not re.search(r"[一-鿿]", label) else ""
        for m in re.finditer(r"(?:^|[\s（(])(?:%s)%s" % (label, tail), text, re.I | re.M):
            rest = text[m.end():]
            # 同一栏的中英双标签："发票号 Invoice No.: INV-1" —— 继续吃掉紧跟的同栏别名
            for _ in range(3):
                stripped = re.sub(r"^(?:\s|[:：./])+", "", rest)
                hit = None
                for alias in LABELS[field]:
                    hit = re.match(r"(?:%s)(?=[\s:：./]|$)" % alias, stripped, re.I)
                    if hit:
                        rest = stripped[hit.end():]
                        break
                if not hit:
                    break
            value, following = _first_line_value(rest)
            # 值的位置上放的是另一栏的标签："发货人:" 后面直接是 "Port of Loading: …" ——
            # 这一栏在原文里是空的，必须当成"没抽到"，不能把标签当值
            if value and _is_other_label(value):
                value = ""
            if not value and following and not _is_other_label(following[0]):
                value = following[0]
            if multiline and value:
                extra = []
                for ln in following[:2]:
                    if _is_other_label(ln):
                        break
                    extra.append(ln)
                value = " ".join([value] + extra)
            value = value.strip(" \t:：")
            if value:
                return value
    return ""


_CUR_RE = r"(USD|US\$|EUR|GBP|CNY|RMB|JPY|HKD|AUD|CAD|CHF|\$|€|£)"


def parse_amount(s):
    """'USD 15,600.00' / 'USD15600,00' / '15600.00 USD' -> ('USD', Decimal('15600.00'))。失败返回 (None, None)。"""
    if not s:
        return None, None
    m = re.search(_CUR_RE + r"?\s*(\d[\d.,]*\d|\d)\s*" + _CUR_RE + r"?", s, re.I)
    if not m:
        return None, None
    cur = (m.group(1) or m.group(3) or "").upper().replace("US$", "USD").replace("$", "USD").replace("€", "EUR").replace("£", "GBP")
    num = m.group(2)
    if "," in num and "." in num:
        num = num.replace(",", "") if num.rfind(".") > num.rfind(",") else num.replace(".", "").replace(",", ".")
    elif "," in num:
        head, _, tail = num.rpartition(",")
        # 15600,00（小数逗号，MT700 的写法） vs 15,600（千分位）
        num = (head.replace(",", "") + "." + tail) if len(tail) != 3 or num.count(",") == 1 and len(tail) == 2 else num.replace(",", "")
    try:
        return (cur or None), Decimal(num)
    except InvalidOperation:
        return None, None


def parse_number(s):
    if not s:
        return None
    m = re.search(r"\d[\d,]*(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return Decimal(m.group(0).replace(",", ""))
    except InvalidOperation:
        return None


def parse_date(s):
    """2026-06-20 / 2026/06/20 / 20 JUN 2026 / 2026年6月20日 -> 'YYYY-MM-DD'。"""
    if not s:
        return None
    m = re.search(r"(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})", s)
    if m:
        return "%04d-%02d-%02d" % tuple(int(x) for x in m.groups())
    months = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
    m = re.search(r"(\d{1,2})\s*([A-Za-z]{3})[A-Za-z]*\.?,?\s*(\d{4})", s)
    if m and m.group(2).upper() in months:
        return "%04d-%02d-%02d" % (int(m.group(3)), months[m.group(2).upper()], int(m.group(1)))
    return None


def _mt700(text):
    """MT700 报文里的 :32B: :50: :59: :44E: :44F: :45A: —— 有就用，没有返回空字典。"""
    out = {}
    tags = {}
    parts = re.split(r"(?m)^\s*:(\d{2}[A-Z]?):", text)
    # parts = [前缀, tag1, 内容1, tag2, 内容2, ...]
    for i in range(1, len(parts) - 1, 2):
        tags[parts[i]] = parts[i + 1].strip()
    if "32B" in tags:
        out["amount"] = tags["32B"].split("\n")[0]
    if "50" in tags:
        out["consignee"] = tags["50"].split("\n")[0].strip()
    if "59" in tags:
        out["shipper"] = re.sub(r"^\d+/", "", tags["59"].split("\n")[0]).strip()
    if "44E" in tags:
        out["port_loading"] = tags["44E"].split("\n")[0].strip()
    if "44F" in tags:
        out["port_discharge"] = tags["44F"].split("\n")[0].strip()
    if "45A" in tags:
        out["goods"] = " ".join(tags["45A"].split("\n")[:2]).strip()
    return out


def extract_fields(text, doc_type=None):
    """从一份单证原文里抽字段。返回 {key: 原文里的写法}，抽不到的键不出现。"""
    text = text or ""
    doc_type = doc_type or detect_type(text)
    found = {}
    if doc_type == "lc":
        found.update({k: v for k, v in ((k, _clean_value(k, v)) for k, v in _mt700(text).items()) if v})
    for key in LABELS:
        if key in found:
            continue
        # 信用证里"金额/日期"这类标签有歧义（开证日、效期、装运日都叫日期），不拿来当可比字段
        if doc_type == "lc" and key in ("date", "invoice_no", "quantity", "packages", "gross_weight", "net_weight", "measurement", "marks"):
            continue
        v = _clean_value(key, _grab(text, key, multiline=(key in ("marks", "goods"))))
        if v:
            found[key] = v
    # 币别：来自金额字段本身
    if "amount" in found:
        cur, _ = parse_amount(found["amount"])
        if cur:
            found["currency"] = cur
    # 装箱单/提单里没有金额是正常的，不用补
    return found


# ============================================================ 规范化与比对
def _norm_text(s):
    s = re.sub(r"[^\w\s一-鿿]", " ", (s or "").upper())
    return re.sub(r"\s+", " ", s).strip()


def _city(s):
    return _norm_text(re.split(r"[,，]", s or "")[0])


def _similar(a, b):
    return SequenceMatcher(None, a, b).ratio()


def _status_text(a, b, contain=False):
    na, nb = _norm_text(a), _norm_text(b)
    if na == nb:
        return "ok", ""
    if contain and (na in nb or nb in na):
        return "ok", ""
    r = _similar(na, nb)
    if r >= 0.88:
        return "near", "两处只差个别字符，疑似拼写或录入差异"
    return "conflict", ""


def compare_values(key, a_type, a_raw, b_type, b_raw):
    """比较同一字段在两份单证里的写法。返回 (status, note)。

    status: ok / near / conflict / unknown（任一侧抽不出来）。
    """
    if not a_raw or not b_raw:
        return "unknown", ""
    kind = FIELD_KIND[key]
    pair = {a_type, b_type}

    if kind == "amount":
        ca, va = parse_amount(a_raw)
        cb, vb = parse_amount(b_raw)
        if va is None or vb is None:
            return "unknown", ""
        if ca and cb and ca != cb:
            return "conflict", "币别不同（%s 与 %s）" % (ca, cb)
        # 信用证与发票：发票金额不得超过信用证金额，低于是允许的（UCP600 第 18 条 b 款）
        if pair == {"lc", "invoice"}:
            lc_v = va if a_type == "lc" else vb
            inv_v = vb if a_type == "lc" else va
            if inv_v > lc_v:
                return "conflict", "发票金额超过信用证金额"
            return "ok", "未超证" if inv_v < lc_v else ""
        return ("ok", "") if va == vb else ("conflict", "")

    if kind == "currency":
        return ("ok", "") if a_raw.upper() == b_raw.upper() else ("conflict", "")

    if kind == "number":
        va, vb = parse_number(a_raw), parse_number(b_raw)
        if va is None or vb is None:
            return "unknown", ""
        return ("ok", "") if va == vb else ("conflict", "")

    if kind == "date":
        da, db = parse_date(a_raw), parse_date(b_raw)
        if not da or not db:
            return "unknown", ""
        return ("ok", "") if da == db else ("conflict", "")

    if kind == "port":
        ca, cb = _city(a_raw), _city(b_raw)
        if not ca or not cb:
            return "unknown", ""
        if ca == cb or ca in cb or cb in ca:
            return "ok", ""
        return ("near", "两处只差个别字符，疑似拼写差异") if _similar(ca, cb) >= 0.88 else ("conflict", "")

    if kind == "goods":
        return _status_text(a_raw, b_raw, contain=True)

    if kind == "marks":
        na, nb = re.sub(r"\s+", "", a_raw.upper()), re.sub(r"\s+", "", b_raw.upper())
        if na == nb:
            return "ok", ""
        return ("near", "两处只差个别字符，疑似录入差异") if _similar(na, nb) >= 0.88 else ("conflict", "")

    if kind == "term":
        ta = re.match(r"[A-Za-z]{3}", a_raw.strip())
        tb = re.match(r"[A-Za-z]{3}", b_raw.strip())
        if not ta or not tb:
            return "unknown", ""
        return ("ok", "") if ta.group(0).upper() == tb.group(0).upper() else ("conflict", "")

    # ref / party
    return _status_text(a_raw, b_raw)


# 只给有把握的配对挂规则编号：依据是规则名称本身，不硬凑
def rule_hint(key, a_type, b_type):
    pair = {a_type, b_type}
    if key == "amount" and pair == {"lc", "invoice"}:
        return "R11"
    if key == "currency" and "lc" in pair:
        return "R12"
    if key == "goods" and pair == {"lc", "invoice"}:
        return "R19"
    if key in ("port_loading", "port_discharge") and "lc" in pair:
        return "R21"
    if key == "consignee" and pair == {"lc", "invoice"}:
        return "R31"
    if key == "shipper" and pair == {"lc", "invoice"}:
        return "R32"
    if key == "consignee" and pair == {"lc", "bl"}:
        return "R33"
    if key in ("shipper", "consignee") and "lc" not in pair:
        return "R36"
    return ""


# ============================================================ 建图
def _comparable(key, a_type, b_type):
    """这两种单证的这一栏，业务上本来就该一致吗？不该的不画线，免得凭空画出红线。

    信用证的 :50: 是开证申请人，而提单/装箱单的收货人常常合法地写成「TO ORDER OF 某银行」，
    把它们直接比一定会"不一致"，但那不是差错。
    """
    if key == "consignee" and "lc" in (a_type, b_type) and ({a_type, b_type} & {"bl", "packing"}):
        return False
    return True


def build_graph(texts):
    """texts: 若干份单证原文。返回可直接画图的结构。"""
    docs = []
    for i, text in enumerate(texts):
        dtype = detect_type(text)
        docs.append({"type": dtype, "text": text, "fields": extract_fields(text, dtype)})

    # 列顺序：信用证在最左，其后发票、装箱单、提单；同类型按输入顺序
    docs.sort(key=lambda d: DOC_ORDER.index(d["type"]))
    counts = {}
    for d in docs:
        counts[d["type"]] = counts.get(d["type"], 0) + 1
    seen = {}
    for idx, d in enumerate(docs):
        d["id"] = idx
        seen[d["type"]] = seen.get(d["type"], 0) + 1
        name = DOC_LABEL[d["type"]]
        d["label"] = name if counts[d["type"]] == 1 else "%s %d" % (name, seen[d["type"]])
        d.pop("text")

    rows, edges = [], []
    for key, label, _kind in FIELDS:
        cells = [{"doc": d["id"], "raw": d["fields"].get(key, "")} for d in docs]
        if not any(c["raw"] for c in cells):
            continue                      # 所有单证都没有这一栏，不占行
        present = [c for c in cells if c["raw"]]
        for a, b in zip(present, present[1:]):
            da, db = docs[a["doc"]], docs[b["doc"]]
            if not _comparable(key, da["type"], db["type"]):
                continue
            status, note = compare_values(key, da["type"], a["raw"], db["type"], b["raw"])
            edges.append({
                "key": key, "label": label, "a": a["doc"], "b": b["doc"],
                "a_raw": a["raw"], "b_raw": b["raw"],
                "a_label": da["label"], "b_label": db["label"],
                "status": status, "note": note, "rule": rule_hint(key, da["type"], db["type"]),
            })
        rows.append({"key": key, "label": label, "cells": cells})

    summary = {s: sum(1 for e in edges if e["status"] == s) for s in ("ok", "near", "conflict", "unknown")}
    return {"docs": docs, "rows": rows, "edges": edges, "summary": summary}
