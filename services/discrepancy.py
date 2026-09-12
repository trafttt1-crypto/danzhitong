# -*- coding: utf-8 -*-
"""把审核报告拆成结构化的不符点条目，供「不符点清单」导出用。

报告里的固定行格式（config/prompts.py 里定的）：

    问题1：[R01][critical] 发票金额栏 - 单价×数量=8900，与行金额不符 → 按 9000 重算

解析要写得宽容些：模型不一定每次都听话，可能漏掉规则编号、把方括号写成中文括号、
用 -> 代替箭头、或者在标签外面套一层 markdown 粗体。宁可少解析出位置信息，
也不能把整条漏掉 —— 漏掉一条不符点，业务员就可能真的漏改一处。
"""
import re

from config import AUDIT_RULES, LC_RULES

# 与 services/archive.py 的 ISSUE_RE 同一个口径（都是"问题N："），
# 只是这里只认开头，正文按"到下一个'问题N：'为止"整块取
_ISSUE_LINE_RE = re.compile(r"问题\s*(\d+)\s*[：:．.、]\s*")
# 编号的方括号可有可无：模型常把提示词里的 "[规则编号]" 当成"这里填编号"
_RULE_RE = re.compile(r"[\[【(（]?\s*([RL]\d{2})\s*[\]】)）]?")
_SEV_RE = re.compile(r"[\[【(（]?\s*(critical|error|warning|严重|需改|提示|错误)\s*[\]】)）]?")

_SEV_ALIAS = {"严重": "critical", "需改": "error", "提示": "warning", "错误": "error"}
_SEV_LABEL = {"critical": "严重", "error": "需改", "warning": "提示"}

# 描述与建议的分隔：箭头（半角/全角/ASCII 写法都认）
_ARROW_RE = re.compile(r"\s*(?:→|->|＝>|=>|⇒)\s*")
# 位置与描述的分隔：要求两侧有空白，避免把"单证-发票"这种词拆开
_LOC_SEP_RE = re.compile(r"\s+[-—–]\s+")
# 模型常写成"46A 第 4 项——客检条款"（破折号没空格、前面也没空格），
# 上面那条就拆不出来。宽松版只用于兜底，并且要求左边长得像条款位置
# （带"项/条/栏"或 SWIFT 栏位号），否则宁可不拆。
_LOC_SEP_LOOSE_RE = re.compile(r"^([^—–\-]{1,24}?)\s*[—–]{1,2}\s*")
_CLAUSE_HINT_RE = re.compile(r"(项|条|款|栏|字段|[0-9]{2}[A-Z])")

_RULE_BASIS = None


def _basis_index():
    """规则编号 → 依据条款。审核规则和审证规则一起收进来。"""
    global _RULE_BASIS
    if _RULE_BASIS is None:
        _RULE_BASIS = {}
        for r in list(AUDIT_RULES) + list(LC_RULES):
            _RULE_BASIS[r["id"]] = r.get("basis", "")
    return _RULE_BASIS


def rule_basis(rule_id):
    """反查规则的依据条款，例如 R31 → UCP600 Art.18(a)(ii)。查不到返回空串。"""
    if not rule_id:
        return ""
    return _basis_index().get(rule_id.upper(), "")


def severity_label(severity):
    return _SEV_LABEL.get(severity, "")


def parse_issues(audit_result, source=""):
    """把审核报告解析成不符点条目列表。

    返回 [{no, rule, severity, severity_label, location, desc, suggestion, basis, source}]

    以「问题N：」为界把报告切成块，而不是只按行读 —— 模型很爱把"→ 改证建议：…"
    另起一行写，只读第一行的话，清单里"修改建议"那列会整列空着。

    解析不出条目就返回空列表（调用方据此提示"本报告没有可导出的不符点"），
    绝不去正文里硬凑 —— 银行交单用的清单上多一条凭空捏造的不符点，
    比少一条更糟。
    """
    if not audit_result:
        return []
    text = str(audit_result)
    marks = list(_ISSUE_LINE_RE.finditer(text))
    items = []
    for idx, m in enumerate(marks):
        end = marks[idx + 1].start() if idx + 1 < len(marks) else len(text)
        item = _parse_issue_block(int(m.group(1)), text[m.end():end], source)
        if item:
            items.append(item)
    return items


def _parse_issue_block(no, block, source):
    # 切到下一个【小节】为止，否则最后一条会把后面每一节都吞进来
    block = re.split(r"\n\s*【", block)[0]
    lines = [ln.replace("**", "").strip() for ln in block.split("\n")]
    lines = [ln for ln in lines if ln]
    if not lines:
        return None

    head = lines[0]
    rule = ""
    severity = ""

    m = _RULE_RE.search(head)
    if m:
        rule = m.group(1).upper()
        head = (head[:m.start()] + head[m.end():]).strip()
    m = _SEV_RE.search(head)
    if m:
        raw = m.group(1).lower()
        severity = _SEV_ALIAS.get(raw, raw)
        head = (head[:m.start()] + head[m.end():]).strip()

    desc_part, suggestion = _split_arrow(head)

    # 后续行：带箭头的收作建议，没箭头的当描述的续写
    for ln in lines[1:]:
        d2, s2 = _split_arrow(ln)
        if s2:
            if not suggestion:
                suggestion = s2
            if d2:
                desc_part = (desc_part + " " + d2).strip()
        elif not suggestion:
            desc_part = (desc_part + " " + ln).strip()

    location = ""
    m = _LOC_SEP_RE.search(desc_part)
    if m:
        location = desc_part[:m.start()].strip()
        desc_part = desc_part[m.end():].strip()
    if not location:
        m = _LOC_SEP_LOOSE_RE.match(desc_part)
        if m and _CLAUSE_HINT_RE.search(m.group(1)):
            location = m.group(1).strip()
            desc_part = desc_part[m.end():].strip()
    # 位置写得太长（超过 30 字）多半是模型没按格式来，那句其实是描述本身，
    # 硬当位置会把描述截断，不如不做拆分
    if len(location) > 30:
        desc_part = (location + " " + desc_part).strip()
        location = ""

    return {
        "no": no,
        "rule": rule,
        "severity": severity,
        "severity_label": severity_label(severity),
        "location": location or "—",
        "desc": desc_part or head,
        "suggestion": suggestion,
        "basis": rule_basis(rule) or "—",
        "source": source,
    }


def _split_arrow(text):
    """把 "描述 → 建议" 拆开。没有箭头就整段都是描述。"""
    m = _ARROW_RE.search(text)
    if not m:
        return text.strip(), ""
    return text[:m.start()].strip(), text[m.end():].strip()
