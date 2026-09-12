import json
import re
import requests
from datetime import datetime
from config.settings import Config
from config.prompts import (
    build_system_prompt, build_lc_review_prompt, LC_FIELDS_PROMPT, LC_FIELD_KEYS,
)

# 提示词里已经不写这些符号了，但模型有惯性、可能还会自己带出来。
# 报告要落库、还会导出成 PDF，脏符号进去就一直在，所以这里兜一道。
# 项目规矩：输出里不允许出现 emoji 与装饰符号。
_EMOJI_RE = re.compile("[⚠✅❌❗❓✨⭐️‍\U0001F300-\U0001FAFF]+")


def strip_emoji(text):
    return _EMOJI_RE.sub("", text or "")


def build_lc_prefix(lc_terms):
    """把用户填的信用证关键条款拼成提示词前缀。没提供就返回空串 ——
    "本次未提供信用证条款"这句话现在由提示词自己的【本次审核范围】负责说明。"""
    if not isinstance(lc_terms, dict):
        # 传进来 list/字符串时 .get 会抛 AttributeError，直接当没提供处理
        return ""
    fields = [
        ("信用证金额", lc_terms.get("lc_amount", "")),
        ("信用证效期/最迟交单日", lc_terms.get("lc_expiry", "")),
        ("申请人", lc_terms.get("lc_applicant", "")),
        ("分批装运", lc_terms.get("lc_partial", "")),
        ("转运", lc_terms.get("lc_transship", "")),
        ("最迟装船日", lc_terms.get("lc_shipment_date", "")),
        ("运费条款", lc_terms.get("lc_freight_terms", "")),
        ("正本份数", lc_terms.get("lc_originals", "")),
        ("收货人措辞", lc_terms.get("lc_consignee", "")),
        ("货物描述须包含", lc_terms.get("lc_description", "")),
        ("计量单位", lc_terms.get("lc_measurement", "")),
        ("LC基准数量", lc_terms.get("lc_base_qty", "")),
        ("溢短装比例", lc_terms.get("lc_tolerance_pct", "")),
        ("溢短装条款原文", lc_terms.get("lc_tolerance_clause", "")),
    ]
    filled = [(k, v) for k, v in fields if v]
    if not filled:
        return ""

    lines = ["【信用证关键条款】"]
    for k, v in filled:
        lines.append(f"- {k}：{v}")
    lines.append("请严格按照以上LC条款逐项核查，发现不符立即标记。\n")
    return "\n".join(lines) + "\n"


def deepseek_audit(ocr_text, lc_terms=None, system_prompt=None, doc_count=1, intro=None):
    """审核单证。

    system_prompt 传 None 时，按"本次到底能查什么"自动生成：
    给了 LC 才会带上信用证那 11 条规则，单份单证不会带上跨单据规则。
    intro 用来加一句本次输入的特殊说明（例如"这是系统刚生成的两份单证"）。
    """
    if system_prompt is None:
        system_prompt = build_system_prompt(has_lc=bool(lc_terms), doc_count=doc_count, intro=intro)
    lc_prefix = build_lc_prefix(lc_terms)
    # 不给基准日期的话，模型会自己猜"今天"，把正常单据判成"未来日期"
    date_prefix = "【审核基准日期】今天是 %s，涉及日期先后、有效期、是否为未来日期的判断一律以此为准。\n\n" % datetime.now().strftime("%Y-%m-%d")
    # rstrip：.env 里多个结尾斜杠就会拼出 //chat/completions，网关 404
    url = Config.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {Config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": Config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{date_prefix}{lc_prefix}请审核以下单证内容：\n\n{ocr_text}"},
        ],
        "temperature": 0.3,
        "max_tokens": 16384,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    # 推理模型被截断时 content 可能是 null，落库会撞 NOT NULL 约束
    return _pick_content(data)


def _pick_content(data):
    """从响应里取正文，任何异常形状都退化成空串而不是抛出去。"""
    try:
        content = data["choices"][0]["message"].get("content")
    except (KeyError, IndexError, TypeError, AttributeError):
        return ""
    return strip_emoji(content)


def deepseek_lc_review(lc_text, deadline_facts=None):
    """审证（信用证体检）：审核信用证本身，不是审核单据。"""
    system_prompt = build_lc_review_prompt(deadline_facts=deadline_facts)
    date_prefix = "【审核基准日期】今天是 %s，涉及日期先后、有效期、是否为未来日期的判断一律以此为准。\n\n" % datetime.now().strftime("%Y-%m-%d")
    url = Config.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions"
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {Config.DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": Config.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{date_prefix}请审以下信用证：\n\n{lc_text}"},
            ],
            "temperature": 0.3,
            "max_tokens": 16384,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return _pick_content(resp.json())


def deepseek_lc_fields(lc_text):
    """从信用证原文抽出 14 个结构化字段，供一键回填到审单表单。

    返回 dict（只含认得的键，值都是字符串）。抽不到任何字段返回 {}。
    这里不抛异常：抽字段失败不该让整个体检流程报错，前端提示"请手动填写"即可。
    """
    url = Config.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions"
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {Config.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": Config.DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": LC_FIELDS_PROMPT},
                    {"role": "user", "content": f"信用证原文：\n\n{lc_text}"},
                ],
                "temperature": 0,
                "max_tokens": 16384,
            },
            timeout=120,
        )
        resp.raise_for_status()
        raw = _pick_content(resp.json())
    except requests.RequestException:
        return {}
    return parse_lc_fields(raw)


def parse_lc_fields(raw):
    """从模型回复里抠出 JSON。模型很可能套一层 ```json 代码块，或者前后带一句话。"""
    if not raw:
        return {}
    text = raw.strip()
    # 去掉代码块围栏
    text = re.sub(r"^\s*```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    # 退一步：直接截第一个 { 到最后一个 }
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for k in LC_FIELD_KEYS:
        v = data.get(k)
        if v is None:
            continue
        v = str(v).strip()
        if v:
            out[k] = v
    return out


def deepseek_compare(text_a, text_b, system_prompt):
    url = Config.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions"
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {Config.DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": Config.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请对比以下两份单证：\n\n=== 单证A ===\n{text_a}\n\n=== 单证B ===\n{text_b}"},
            ],
            "temperature": 0.3,
            "max_tokens": 16384,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return _pick_content(resp.json())
