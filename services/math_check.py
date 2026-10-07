# -*- coding: utf-8 -*-
"""单据数学验算：由程序算，不让模型心算。

背景：实测模型会把 3,000 × 5.20 算成 15,000（正确是 15,600），还在【数学验算】里写"一致"。
大模型擅长读懂单据、解释规则，但不擅长乘法。所以和交单期限（lc_deadline.py）、
一致性图（consistency.py）一样：能算的程序先算完，结果作为「已核实事实」交给模型，
模型只负责写进报告、解释原因。

原则：取不准就不下结论。任何一个数没取到或取到多个说不清的值，这一项就跳过，
宁可少说一句，也不能用一个取错的数去指控单据算错。

对外只有一个函数：check(text) -> dict，见文末。
"""
import re
from decimal import Decimal, InvalidOperation

# 数量单位（不含 KGS/CTNS：前者是重量，后者是件数，都不参与单价×数量）
_QTY_UNITS = r"PCS|PC|PIECES?|SETS?|UNITS?|PAIRS?|DOZ(?:ENS?)?|ROLLS?|BAGS?|BOXES|DRUMS?|MTS|METERS?|YDS|YARDS?"
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_CUR = r"USD|US\$|EUR|GBP|JPY|CNY|RMB|HKD|AED"

# 数字后面不能再接 ",5" ".5" 这种尾巴：4,50 / 9.000,00 是欧洲写法，这里认不准就整段不认
_END = r"(?![.,]\d)"
_QTY_RE = re.compile(r"(?<![\w.,(])(%s)%s\s*(%s)\b(?!\s*(?:PER|/|EACH))" % (_NUM, _END, _QTY_UNITS), re.I)
_MONEY_RE = re.compile(r"(?:%s)\s*\$?\s*(%s)%s" % (_CUR, _NUM, _END), re.I)
# 形如 4,50 / 9.000,00 的歧义数字：出现在金额位置就放弃这一项
_AMBIGUOUS_RE = re.compile(r"(?:%s)\s*\$?\s*\d+(?:\.\d{3})*,\d{1,2}(?!\d)" % _CUR, re.I)


def _dec(s):
    try:
        return Decimal(s.replace(",", ""))
    except (InvalidOperation, AttributeError):
        return None


def _fmt(d):
    """15600 -> '15,600.00'；数量这种整数 -> '3,000'"""
    if d == d.to_integral_value() and d.as_tuple().exponent >= 0:
        return "{:,}".format(int(d))
    return "{:,.2f}".format(d)


def _money(d):
    return "{:,.2f}".format(d)


def _lines(text):
    return [ln.strip() for ln in (text or "").replace("\r", "").split("\n")]


def _label_value(lines, label_re, value_re, lookahead=2, exclude_re=None):
    """找「标签 值」：值在同一行标签后面，或紧接着的下 1~2 行（OCR 常把表格拆成一行一个格子）。
    同一个标签出现多次且取到的值不同 -> 说不清，返回 None。
    exclude_re：同一行里还出现这个标签就跳过该行 —— "G.W./N.W.: 1,200 KGS / 1,000 KGS"
    这种合写的行分不清哪个数归谁，原来毛重、净重都会取成 1,200。"""
    found = []
    for i, ln in enumerate(lines):
        m = label_re.search(ln)
        if not m or (exclude_re is not None and exclude_re.search(ln)):
            continue
        v = value_re.search(ln[m.end():])
        if not v:
            for j in range(i + 1, min(i + 1 + lookahead, len(lines))):
                if label_re.search(lines[j]):
                    break
                v = value_re.search(lines[j])
                if v:
                    break
        if v:
            found.append(_dec(v.group(1)))
    found = [f for f in found if f is not None]
    if not found or any(f != found[0] for f in found):
        return None
    return found[0]


def _line_items(lines):
    """找货物行：一个「数量+单位」之后紧跟的两个金额，按惯例依次是单价、行金额。
    这是发票表格的通行列序（数量 / 单价 / 金额）；OCR 按格子拆行也保持这个顺序。"""
    items = []
    flat = "\n".join(lines)
    for m in _QTY_RE.finditer(flat):
        qty = _dec(m.group(1))
        tail = flat[m.end(): m.end() + 160]
        ms = list(_MONEY_RE.finditer(tail))[:2]
        monies = [_dec(x.group(1)) for x in ms]
        # 两个金额之前又冒出一个数量，说明这不是一条完整的货物行（例如汇总区），跳过
        nxt_qty = _QTY_RE.search(tail)
        if nxt_qty and len(ms) == 2 and nxt_qty.start() < ms[1].start():
            continue
        if qty and len(monies) == 2 and all(monies):
            items.append({"qty": qty, "unit": m.group(2).upper(), "price": monies[0], "amount": monies[1]})
    # 同一行被匹配两次（表格汇总行重复数量）时去重
    uniq = []
    for it in items:
        if it not in uniq:
            uniq.append(it)
    return uniq


_SUB_RE = re.compile(r"(小计|Sub\s*-?\s*Total)", re.I)
_GRAND_RE = re.compile(r"(Grand\s+Total)", re.I)
_TOTAL_RE = re.compile(r"(总价|总金额|合计金额|Total\s+Amount|TOTAL\s+VALUE|Grand\s+Total)", re.I)
_FREIGHT_RE = re.compile(r"(运费|Freight(?!\s*(?:Prepaid|Collect)))", re.I)
_INSUR_RE = re.compile(r"(保险费|Insurance(?:\s+Premium)?)(?!\s*Policy)", re.I)
# 折扣、扣款、佣金、预付款、杂费这类调整项：货物行加起来本来就不等于总价，
# 这时拿"各行之和"去比总价，会把一张正确的发票判成算错（R01 被强制写进【发现问题】）。
# 只认"标签 + 同一行有金额"的行：付款条款里的"30% IN ADVANCE"不带金额，不算。
_ADJUST_RE = re.compile(
    r"(折扣|扣除|扣减|扣款|减去|预付|定金|订金|佣金|回扣|返利|附加费|手续费|"
    r"Discount|\bLess\b|Deduct|Rebate|Commission|Advance|Deposit|Allowance|Surcharge|"
    r"Handling\s+(?:Fee|Charge)|Bank\s+Charges?|Other\s+Charges?)", re.I)
_QTY_LABEL_RE = re.compile(r"(数量|Quantity|Qty)", re.I)
_PRICE_LABEL_RE = re.compile(r"(单价|Unit\s*Price)", re.I)
_GW_RE = re.compile(r"(毛重|Gross\s*Weight|G\.\s*W\.)", re.I)
_NW_RE = re.compile(r"(净重|Net\s*Weight|N\.\s*W\.)", re.I)
_PKG_RE = re.compile(r"(件数|总件数|Total\s*Packages|No\.\s*of\s*Packages|Packages)", re.I)
_MARK_RE = re.compile(r"(唛头|Shipping\s*Marks?|Marks\s*(?:&|and)\s*Nos\.?)", re.I)
_KG_RE = re.compile(r"(%s)\s*(?:KGS?|KILOGRAMS?)\b" % _NUM, re.I)
_CTN_RE = re.compile(r"(%s)\s*(?:CTNS?|CARTONS?|PKGS?|PACKAGES|CASES?|PALLETS?|BALES?)\b" % _NUM, re.I)
_RANGE_RE = re.compile(r"(?<![\d.])(\d{1,5})\s*[-–~]\s*(\d{1,5})(?![\d.])")


def _mark_range(lines):
    for i, ln in enumerate(lines):
        m = _MARK_RE.search(ln)
        if not m:
            continue
        seg = " ".join([ln[m.end():]] + lines[i + 1:i + 3])
        # 唛头区间：形如 1-150、NO.1-150、C/NO.1-150；日期（2026-06-20）不算
        for r in _RANGE_RE.finditer(seg):
            a, b = int(r.group(1)), int(r.group(2))
            before = seg[max(0, r.start() - 1):r.start()]
            if before.isdigit() or a > b or a == 0 and b == 0:
                continue
            if a <= 5:          # 箱号区间一般从 1 起；从 2026 起的是日期
                return a, b
        return None
    return None


def check(text):
    """返回 {"facts": [...], "problems": [...]}。

    facts：给模型的「已核实事实」，每条一句话。
    problems：程序确认的错误，每项 {"rule": "R01", "text": "..."}，供报告兜底与测试。
    """
    lines = _lines(text)
    facts, problems = [], []

    # ---- R01 单价 × 数量 = 行金额；各行之和 = 小计（或总价）；小计 + 运费 + 保费 = 总计 ----
    amb = bool(_AMBIGUOUS_RE.search(text or ""))
    sub = _label_value(lines, _SUB_RE, _MONEY_RE)
    grand = _label_value(lines, _GRAND_RE, _MONEY_RE)
    freight = _label_value(lines, _FREIGHT_RE, _MONEY_RE)
    insur = _label_value(lines, _INSUR_RE, _MONEY_RE)
    has_extra = freight is not None or insur is not None
    adjusted = any(_ADJUST_RE.search(ln) and _MONEY_RE.search(ln) for ln in lines)
    total_plain = None if sub is not None else _label_value(lines, _TOTAL_RE, _MONEY_RE)
    # 货物本身的合计：有小计用小计；没有小计且有运费/保费/折扣等调整项时，
    # 总价里混着这些，不能拿来比货物
    goods_total = sub if sub is not None else (None if has_extra or adjusted else total_plain)

    items = [] if amb else _line_items(lines)
    labeled = False
    if not amb and not items:
        # 标签式单据（数量: 2000 SETS / 单价: USD 4.50 / 总价: USD 9000.00）：
        # 只有全文只出现一个数量时才这样配对，多行货物配不准就不配
        qtys = {(_dec(m.group(1)), m.group(2).upper()) for m in _QTY_RE.finditer(text or "")}
        qty = _label_value(lines, _QTY_LABEL_RE, _QTY_RE)
        price = _label_value(lines, _PRICE_LABEL_RE, _MONEY_RE)
        if len(qtys) == 1 and qty is not None and price is not None and goods_total is not None:
            unit = next(iter(qtys))[1]
            items = [{"qty": qty, "unit": unit, "price": price, "amount": goods_total}]
            labeled = True

    for n, it in enumerate(items, 1):
        calc = (it["qty"] * it["price"]).quantize(Decimal("0.01"))
        tag = "第 %d 行" % n if len(items) > 1 else "货物行"
        col = "总价" if labeled else "金额栏"
        if calc == it["amount"].quantize(Decimal("0.01")):
            facts.append("%s：%s %s × 单价 %s = %s，与%s %s 一致。" % (
                tag, _fmt(it["qty"]), it["unit"], _money(it["price"]), _money(calc), col, _money(it["amount"])))
        else:
            diff = calc - it["amount"]
            t = "%s：%s %s × 单价 %s = %s，但%s写的是 %s，相差 %s。%s与数量、单价至少有一个是错的。" % (
                tag, _fmt(it["qty"]), it["unit"], _money(it["price"]), _money(calc), col,
                _money(it["amount"]), _money(abs(diff)), col)
            facts.append(t + "（R01 不成立）")
            problems.append({"rule": "R01", "text": t})

    if items and not labeled and goods_total is not None:
        s = sum((it["amount"] for it in items), Decimal("0"))
        name = "小计" if sub is not None else "总价"
        if s == goods_total:
            facts.append("各行金额合计 %s，与%s %s 一致。" % (_money(s), name, _money(goods_total)))
        elif len(items) > 1:
            t = "各行金额合计 %s，与%s %s 不一致，相差 %s。" % (_money(s), name, _money(goods_total), _money(abs(s - goods_total)))
            facts.append(t + "（R01 不成立）")
            problems.append({"rule": "R01", "text": t})

    if not amb and sub is not None and grand is not None and has_extra and not adjusted:
        exp = sub + (freight or Decimal("0")) + (insur or Decimal("0"))
        parts = "小计 %s" % _money(sub)
        if freight is not None:
            parts += " + 运费 %s" % _money(freight)
        if insur is not None:
            parts += " + 保费 %s" % _money(insur)
        if exp == grand:
            facts.append("%s = %s，与总计 %s 一致。" % (parts, _money(exp), _money(grand)))
        else:
            t = "%s = %s，但总计写的是 %s，相差 %s。" % (parts, _money(exp), _money(grand), _money(abs(exp - grand)))
            facts.append(t + "（R01 不成立）")
            problems.append({"rule": "R01", "text": t})
    if adjusted and not amb:
        facts.append("单据上有折扣、扣款、佣金或预付款等调整项，程序不核对各行合计与总价/总计的关系，"
                     "请人工核对：货物行合计 ± 各调整项 = 总价。")
    if amb:
        facts.append("金额写法有歧义（如 4,50 或 9.000,00 这类小数点与千分位混用的写法），程序不做金额验算，请人工核对金额格式。")

    # ---- R04 净重 ≤ 毛重 ----
    gw = _label_value(lines, _GW_RE, _KG_RE, exclude_re=_NW_RE)
    nw = _label_value(lines, _NW_RE, _KG_RE, exclude_re=_GW_RE)
    if gw is not None and nw is not None:
        if nw <= gw:
            facts.append("净重 %s KGS ≤ 毛重 %s KGS，重量逻辑成立。" % (_fmt(nw), _fmt(gw)))
        else:
            t = "净重 %s KGS 大于毛重 %s KGS，多出 %s KGS，净重不可能超过毛重。" % (_fmt(nw), _fmt(gw), _fmt(nw - gw))
            facts.append(t + "（R04 不成立）")
            problems.append({"rule": "R04", "text": t})

    # ---- R43 唛头箱号区间 = 件数 ----
    pkgs = _label_value(lines, _PKG_RE, _CTN_RE)
    rng = _mark_range(lines)
    if pkgs is not None and rng is not None:
        a, b = rng
        cnt = b - a + 1
        if cnt == int(pkgs):
            facts.append("唛头箱号 %d-%d 共 %d 箱，与件数 %s 一致。" % (a, b, cnt, _fmt(pkgs)))
        else:
            t = "唛头箱号 %d-%d 共 %d 箱，与件数 %s 箱不符，相差 %d 箱。" % (a, b, cnt, _fmt(pkgs), abs(cnt - int(pkgs)))
            facts.append(t + "（R43 不成立）")
            problems.append({"rule": "R43", "text": t})

    return {"facts": facts, "problems": problems}


def facts_block(text):
    """拼成提示词里的一段。没有任何可验算的数就返回空串（不注入，照旧让模型审）。"""
    r = check(text)
    if not r["facts"]:
        return ""
    out = ["【系统已验算的数值】（由程序精确计算，以此为准，不要自己重算）"]
    out += ["- " + f for f in r["facts"]]
    out.append("凡标注「不成立」的，必须写进【发现问题】，规则编号照标注；"
               "【数学验算】照抄上面的算式与结论。上面没有覆盖到的数，仍按规则自行核对。")
    return "\n".join(out) + "\n\n"
