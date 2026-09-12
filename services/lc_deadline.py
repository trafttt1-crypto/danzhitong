# -*- coding: utf-8 -*-
"""交单时间计算：纯函数、不碰网络、不花 AI 的钱。

为什么单开一个模块、还在本地算：

    最迟交单日 = min(最迟装运日 + 交单期, 信用证效期)

这个式子简单，但它决定了业务员还有几天能把单据交到银行，算错一天就是真金白银的
拒付。让大模型心算日期是靠不住的（它会算错、还会按自己的"今天"算），所以这里算
完把结论作为事实注入提示词——模型只负责解释，不负责算。这做法是从 OpenNER
"validated, not just extracted" 学来的。

UCP600 Art.14(c)：交单不得迟于信用证效期；未规定交单期时为装运日后 21 个日历日，
且不得晚于效期。注意是**日历日**，不是工作日。
"""
import re
from datetime import date, datetime, timedelta

# 未规定交单期时 UCP600 Art.14(c) 的默认值
DEFAULT_PRESENTATION_DAYS = 21
# 装运期与效期之间少于这么多天就提示缓冲不足（实务：制单 3-5 天 + 寄单 3-5 天）
TIGHT_BUFFER_DAYS = 10
# 制单所需天数，倒排时间表用
DOC_PREP_DAYS = 3

_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def parse_flexible_date(raw):
    """把用户/信用证里五花八门的日期写法归一成 date。

    认得的写法：2026-09-15、2026/09/15、2026.09.15、20260915、
    15 SEP 2026、15 September 2026、2026年9月15日。

    认不出、或者有歧义（03/04/2026 到底是 3 月 4 日还是 4 月 3 日）一律返回 None，
    由调用方给出明确提示 —— 交单日期猜错比让用户重填一次严重得多。
    """
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw

    s = str(raw).strip()
    if not s:
        return None
    s = s.replace("年", "-").replace("月", "-").replace("日", " ").replace("号", " ")
    s = re.sub(r"\s+", " ", s).strip()

    # 2026-09-15 / 2026/09/15 / 2026.09.15
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # 20260915
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # 260915 —— MT700 报文的日期就是 YYMMDD（如 44C: 260915）
    m = re.fullmatch(r"(\d{2})(\d{2})(\d{2})", s)
    if m:
        return _safe_date(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # 15 SEP 2026 / 15 September 2026
    m = re.fullmatch(r"(\d{1,2})[\s\-]*([A-Za-z]{3,9})[\s\-,]*(\d{4})", s)
    if m:
        mon = _MONTHS.get(m.group(2)[:3].upper())
        if mon:
            return _safe_date(int(m.group(3)), mon, int(m.group(1)))

    # SEP 15, 2026
    m = re.fullmatch(r"([A-Za-z]{3,9})[\s\-]*(\d{1,2})[\s\-,]*(\d{4})", s)
    if m:
        mon = _MONTHS.get(m.group(1)[:3].upper())
        if mon:
            return _safe_date(int(m.group(3)), mon, int(m.group(2)))

    # 03/04/2026 这类：两边都 <=12 时无法判断月日，宁可让用户重填也不猜
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a <= 12 and b <= 12:
            return None
        # 有一边 >12，那它就是日
        if a > 12:
            return _safe_date(int(m.group(3)), b, a)
        return _safe_date(int(m.group(3)), a, b)

    return None


def _safe_date(year, month, day):
    try:
        return date(year, month, day)
    except ValueError:
        return None


def is_ambiguous_date(raw):
    """是不是"认不出"里那种"有歧义"的情况（用来给出更准的提示语）。"""
    if not raw:
        return False
    s = str(raw).strip()
    m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)
    return bool(m and int(m.group(1)) <= 12 and int(m.group(2)) <= 12)


def presentation_deadline(shipment_date, expiry, days=None, mailing_days=5, today=None):
    """算出最迟交单日与倒排时间表。

    shipment_date 最迟装运日（信用证规定）
    expiry        信用证效期
    days          交单期天数；传 None 或 0 按 UCP600 默认 21 天
    mailing_days  预计寄单到银行的在途天数，倒排用

    返回 dict，永远不抛异常：字段错误走 ok=False + error，前端直接显示。
    """
    today = today or date.today()
    days = int(days) if days else DEFAULT_PRESENTATION_DAYS
    if days <= 0:
        days = DEFAULT_PRESENTATION_DAYS
    try:
        mailing_days = max(0, int(mailing_days))
    except (TypeError, ValueError):
        mailing_days = 5

    ship = parse_flexible_date(shipment_date)
    exp = parse_flexible_date(expiry)

    if not ship and not exp:
        return {"ok": False, "error": "请至少填写「最迟装运日」或「信用证效期」"}
    if shipment_date and not ship:
        return {"ok": False, "error": _date_error_msg(shipment_date, "最迟装运日")}
    if expiry and not exp:
        return {"ok": False, "error": _date_error_msg(expiry, "信用证效期")}

    warnings = []

    # 最迟交单日：装运日 + 交单期 与 效期 取早者
    from_presentation = ship + timedelta(days=days) if ship else None
    candidates = [d for d in (from_presentation, exp) if d]
    deadline = min(candidates)
    if from_presentation and exp and exp < from_presentation:
        deadline_source = "信用证效期"
        # 效期不晚于装运日（多半是双到期）时不报"截断"——那是废话，而且会把
        # 真正该看的那条双到期预警淹没在噪音里
        if exp > ship:
            warnings.append(
                "信用证效期（%s）早于「装运日 + %d 天」，交单期实际被效期截断，"
                "按效期为准" % (exp.isoformat(), days))
        elif exp < ship:
            warnings.append("信用证效期（%s）竟然早于最迟装运日（%s），两条时间条款自相矛盾"
                            % (exp.isoformat(), ship.isoformat()))
    elif from_presentation:
        deadline_source = "装运日后 %d 天" % days
    else:
        deadline_source = "信用证效期"

    # 双到期：最迟装运日与效期同一天，装运后一天缓冲都没有
    is_dual = bool(ship and exp and ship == exp)
    gap = (exp - ship).days if (ship and exp) else None

    if is_dual:
        warnings.append("双到期：最迟装运日与信用证效期是同一天（%s），"
                        "装运后必须当天完成交单，实务上做不到" % ship.isoformat())
    elif gap is not None and gap <= TIGHT_BUFFER_DAYS:
        warnings.append("装运期与效期只隔 %d 天，制单加寄单通常需要 %d 天左右，缓冲偏紧"
                        % (gap, DOC_PREP_DAYS + mailing_days))

    days_left = (deadline - today).days
    if days_left < 0:
        warnings.append("最迟交单日 %s 已经过去 %d 天" % (deadline.isoformat(), -days_left))
    elif days_left <= 7:
        warnings.append("距最迟交单日只剩 %d 天" % days_left)

    if exp and exp < today:
        warnings.append("信用证效期 %s 已过" % exp.isoformat())
    if ship and ship < today:
        warnings.append("最迟装运日 %s 已过" % ship.isoformat())

    schedule = _build_schedule(deadline, ship, mailing_days)

    return {
        "ok": True,
        "today": today.isoformat(),
        "shipment_date": ship.isoformat() if ship else "",
        "expiry": exp.isoformat() if exp else "",
        "days": days,
        "mailing_days": mailing_days,
        "deadline": deadline.isoformat(),
        "deadline_source": deadline_source,
        "days_left": days_left,
        "is_dual_expiry": is_dual,
        "gap_days": gap,
        "warnings": warnings,
        "schedule": schedule,
    }


def _date_error_msg(raw, label):
    if is_ambiguous_date(raw):
        return "%s「%s」写法有歧义（分不清月和日），请改用 2026-09-15 这样的格式" % (label, raw)
    return "%s「%s」无法识别，请改用 2026-09-15 这样的格式（或 15 SEP 2026）" % (label, raw)


def _build_schedule(deadline, ship, mailing_days):
    """从最迟交单日往前倒排。

    倒排出来的日期可能落到最迟装运日之前 —— 那意味着"装船之前就得把单据寄出去"，
    这套时间表根本执行不了（双到期时必然如此）。这种条目照旧列出来，但要明说是
    排不开，而不是当成一条可执行的建议——否则用户看到"建议寄单日 9-10"、
    装运日却是 9-15，只会以为系统算错了。
    """
    mail_date = deadline - timedelta(days=mailing_days)
    prep_date = deadline - timedelta(days=mailing_days + DOC_PREP_DAYS)
    impossible = bool(ship and mail_date < ship)
    bad_note = "早于最迟装运日，这套时间表排不开，必须改证"

    items = []
    if ship:
        items.append({"label": "最迟装运日", "date": ship.isoformat(),
                      "note": "信用证规定，不得晚于此日装运", "tone": "key"})
    items.append({"label": "建议寄单日", "date": mail_date.isoformat(),
                  "note": bad_note if impossible
                          else "按在途 %d 天倒推，晚于此日就有迟交单风险" % mailing_days,
                  "tone": "impossible" if impossible else "warn"})
    items.append({"label": "建议制单完成", "date": prep_date.isoformat(),
                  "note": bad_note if impossible
                          else "留出 %d 天制单与核对时间" % DOC_PREP_DAYS,
                  "tone": "impossible" if impossible else "normal"})
    items.append({"label": "最迟交单日", "date": deadline.isoformat(),
                  "note": "超过此日银行即可拒收单据", "tone": "key"})
    return items


def build_deadline_facts(result):
    """把计算结果写成注入提示词的事实块。只解释，不让模型算。"""
    if not result or not result.get("ok"):
        return ""
    lines = []
    lines.append("最迟交单日 = min(最迟装运日 + 交单期, 信用证效期) = %s（依据：%s）"
                 % (result["deadline"], result["deadline_source"]))
    if result.get("shipment_date"):
        lines.append("最迟装运日：%s" % result["shipment_date"])
    if result.get("expiry"):
        lines.append("信用证效期：%s" % result["expiry"])
    lines.append("交单期按 %d 个日历日计（UCP600 Art.14(c)；日历日不是工作日）" % result["days"])
    lines.append("以 %s 为今天计算，距最迟交单日还有 %d 天" % (result["today"], result["days_left"]))
    lines.append("双到期判定：%s" % ("是" if result.get("is_dual_expiry") else "否"))
    if result.get("gap_days") is not None:
        lines.append("最迟装运日与效期相隔 %d 天" % result["gap_days"])
    for w in result.get("warnings") or []:
        lines.append("系统预警：" + w)
    return "\n".join(lines)
