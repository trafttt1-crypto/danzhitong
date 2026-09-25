"""总控智能助手 — 多会话对话 + 基于系统数据快照的问答 + 长对话自动压缩"""
import sqlite3
from datetime import datetime

import requests
from flask import g

from config.settings import Config
from config.prompts import AUDIT_RULES
from .archive import iter_issues
from .deepseek_audit import strip_emoji


def _rule_index():
    """审核规则索引，拼进助手人设里。

    不给的话，助手讲"R14 是什么"只能靠编 —— 规则编号是它最容易瞎猜的地方。
    """
    return "、".join("%s %s" % (r["id"], r["name"]) for r in AUDIT_RULES)

_SYSTEM_PROMPT_TRADE = """你是"单智通"系统的总控智能助手。单智通是一个外贸单证 AI 审核系统，功能包括：智能制单、图片审核、文字审核、PDF 审核、多单证对比、信用证体检、历史记录、档案管理。

回答规则：
1. 只依据下方【系统数据快照】里的事实回答；数字必须准确，绝不编造；快照里没有的信息就直说"没有查到相关记录"。
2. 用中文口语化回答，简洁（一般 3~6 句，或简短列表）；问到统计先把关键数字说清楚。
3. 用户说"今天 / 昨天 / 本周 / 本月 / 最近"等时间，按快照里的当前时间推算。
4. 如果用户问系统怎么用，可以正常介绍；但不要假装执行了任何实际操作。
5. 不要虚构或猜测用户之前发过什么内容，只围绕当前问题回答。
6. 如果用户贴来了单证内容，提醒他：审核单证请到左侧导航的「粘贴文字」「上传图片」「上传 PDF」页面；本对话只负责查询系统数据与答疑，不在这里执行审核。
7. 遇到专业术语可以顺带用一句话解释；用户问"为什么错 / 怎么改"时，结合审核规则编号给出修改思路。
   系统现有的审核规则（只能引用这些编号，不要编造）：{rules}

【系统数据快照】
{snapshot}"""

# 教育版（实训）：AI 助教人设
_SYSTEM_PROMPT_EDU = """你是"单智通"系统的总控智能助手，同时是职业院校外贸 / 跨境电商 / 报关专业师生的 AI 助教。单智通是一个外贸单证 AI 审核系统，功能包括：智能制单、图片审核、文字审核、PDF 审核、多单证对比、信用证体检、实训练习、历史记录、档案管理。

回答规则：
1. 只依据下方【系统数据快照】里的事实回答；数字必须准确，绝不编造；快照里没有的信息就直说"没有查到相关记录"。
2. 用中文口语化回答，简洁（一般 3~6 句，或简短列表）；问到统计先把关键数字说清楚。
3. 用户说"今天 / 昨天 / 本周 / 本月 / 最近"等时间，按快照里的当前时间推算。
4. 如果用户问系统怎么用，可以正常介绍；但不要假装执行了任何实际操作。
5. 不要虚构或猜测用户之前发过什么内容，只围绕当前问题回答。
6. 如果用户贴来了单证内容，提醒他：审核单证请到左侧导航的「粘贴文字」「上传图片」「上传 PDF」页面；本对话只负责查询系统数据与答疑，不在这里执行审核。
7. 带着助教的心态回答：遇到专业术语顺带用一句话解释；学生问"为什么错 / 怎么改"时，结合审核规则的编号给出修改思路。
   系统现有的审核规则（只能引用这些编号，不要编造）：{rules}
8. 语气友好、鼓励，鼓励学生多练多问，但不要啰嗦。

【系统数据快照】
{snapshot}"""


def _system_prompt():
    """按版本选择助手人设：edu=教育版（助教），trade=标准版。
    规则索引在这里就填好，调用方只需要再填 {snapshot}。"""
    tpl = _SYSTEM_PROMPT_EDU if Config.EDITION == "edu" else _SYSTEM_PROMPT_TRADE
    return tpl.replace("{rules}", _rule_index())

# 摘要结构参考 Gemini CLI 的 state_snapshot 格式（google-gemini/gemini-cli）
_SUMMARY_PROMPT = """请把以下多轮对话压缩成结构化摘要（中文，总长不超过 600 字），严格按下面的 XML 结构输出，没有的内容写"无"，不要输出结构以外的任何文字：
<state_snapshot>
<overall_goal>用户在本次会话中的整体目标</overall_goal>
<key_knowledge>关键事实与数字：回答过的统计结果、重要结论</key_knowledge>
<recent_actions>最近做过的事：查询过什么、得到了什么结果</recent_actions>
<current_plan>用户交代的待办事项、偏好与后续计划</current_plan>
</state_snapshot>"""

# 长对话压缩阈值与保留条数
COMPRESS_THRESHOLD = 40
KEEP_RECENT = 16
MAX_SUMMARIES_IN_CONTEXT = 3
_CONTEXT_RECENT = 10
_CONTEXT_CLIP = 800


def _db():
    if "db" not in g:
        g.db = sqlite3.connect(Config.DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def init_chat():
    db = sqlite3.connect(Config.DB_PATH)
    db.execute(
        """CREATE TABLE IF NOT EXISTS chat_message (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'chat',
            created_at TEXT NOT NULL
        )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS chat_thread (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    # 旧库升级：给 chat_message 加 thread_id
    try:
        db.execute("ALTER TABLE chat_message ADD COLUMN thread_id INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    # 一次性迁移：把旧的无会话消息归入"历史对话"
    n = db.execute("SELECT COUNT(*) FROM chat_message WHERE thread_id = 0").fetchone()[0]
    if n:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute(
            "INSERT INTO chat_thread (title, created_at, updated_at) VALUES ('历史对话', ?, ?)",
            (now, now),
        )
        tid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("UPDATE chat_message SET thread_id = ? WHERE thread_id = 0", (tid,))
    db.commit()
    db.close()


def create_thread(title=""):
    db = _db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        "INSERT INTO chat_thread (title, created_at, updated_at) VALUES (?, ?, ?)",
        (title, now, now),
    )
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def thread_exists(thread_id):
    """会话是否真实存在（防止消息写进已被删除或伪造的 thread_id）。"""
    db = _db()
    return db.execute("SELECT 1 FROM chat_thread WHERE id = ?", (thread_id,)).fetchone() is not None


def _touch_thread(thread_id):
    db = _db()
    db.execute(
        "UPDATE chat_thread SET updated_at = ? WHERE id = ?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), thread_id),
    )
    db.commit()


def list_threads():
    db = _db()
    rows = db.execute(
        """SELECT t.id, t.title, t.created_at, t.updated_at,
                  (SELECT COUNT(*) FROM chat_message m WHERE m.thread_id = t.id) AS msg_count
           FROM chat_thread t
           WHERE (SELECT COUNT(*) FROM chat_message m WHERE m.thread_id = t.id) > 0
           ORDER BY t.updated_at DESC"""
    ).fetchall()
    return [
        {"id": r["id"], "title": r["title"], "created_at": r["created_at"],
         "updated_at": r["updated_at"], "msg_count": r["msg_count"]}
        for r in rows
    ]


def save_message(role, content, kind="chat", thread_id=0):
    db = _db()
    db.execute(
        "INSERT INTO chat_message (role, content, kind, created_at, thread_id) VALUES (?, ?, ?, ?, ?)",
        (role, content, kind, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), thread_id),
    )
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_messages(thread_id, limit=300):
    db = _db()
    rows = db.execute(
        """SELECT * FROM (
               SELECT * FROM chat_message WHERE thread_id = ? ORDER BY id DESC LIMIT ?
           ) ORDER BY id ASC""",
        (thread_id, limit),
    ).fetchall()
    return [
        {"id": r["id"], "role": r["role"], "content": r["content"],
         "kind": r["kind"], "created_at": r["created_at"]}
        for r in rows
    ]


def clear_thread(thread_id):
    db = _db()
    db.execute("DELETE FROM chat_message WHERE thread_id = ?", (thread_id,))
    db.execute("DELETE FROM chat_thread WHERE id = ?", (thread_id,))
    db.commit()


def clear_all():
    db = _db()
    db.execute("DELETE FROM chat_message")
    db.execute("DELETE FROM chat_thread")
    db.commit()


def _extract_problems(audit_result, max_items=8, clip=90):
    """从审核报告里提取"问题N："条目（口径与档案统计共用，避免两处漂移）"""
    items = []
    for line in iter_issues(audit_result):
        if not line:
            continue
        items.append(line[:clip] + ("…" if len(line) > clip else ""))
        if len(items) >= max_items:
            break
    return items


def _practice_source_ids():
    """实训题目的题面来源记录 id —— 这些单证的内容不能进快照。

    实训练习是**故意藏答案**的（标准答案不进 JSON 响应，前端 F12 也看不到）。
    但助手要是从审核历史里读到同一份单证的问题清单，等于把答案念给了学生。

    三道预置题是内置的（source_record_id = 0），不受影响；
    这里挡的是「从历史记录一键转成题目」造出来的那些题。

    为什么写在代码里而不是人设里：**模型判断不出「这一条是练习题」**。
    实测把答案塞进快照后，edu 版（带禁止条款）和 trade 版（没这条）答得一模一样，
    照样把规则编号念了出来。判不了的条件就别交给提示词。
    """
    try:
        rows = _db().execute(
            "SELECT source_record_id FROM practice_case WHERE source_record_id > 0"
        ).fetchall()
    except sqlite3.OperationalError:
        return ()
    return tuple(r[0] for r in rows)


def build_snapshot():
    """从数据库实时生成数据快照（助手回答的唯一事实来源）"""
    db = _db()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")

    # 题面来源记录整体排除。三条查询（今天列表 / 今天计数 / 最近 20 条）
    # 必须用同一个条件 —— 只挡列表不挡计数的话，会出现
    # 「今天共 N 条，仅列 N-1 条」这种能被学生看出「有东西藏着」的破绽。
    hide = _practice_source_ids()
    excl = (" AND id NOT IN (%s)" % ",".join("?" * len(hide))) if hide else ""

    today_rows = db.execute(
        "SELECT created_at, input_type, input_summary, audit_result FROM audit_history"
        " WHERE created_at LIKE ?" + excl + " ORDER BY id DESC LIMIT 40",
        (today + "%",) + hide,
    ).fetchall()
    today_total = db.execute(
        "SELECT COUNT(*) FROM audit_history WHERE created_at LIKE ?" + excl,
        (today + "%",) + hide,
    ).fetchone()[0]
    recent_rows = db.execute(
        "SELECT created_at, input_type, input_summary, audit_result FROM audit_history"
        " WHERE 1=1" + excl + " ORDER BY id DESC LIMIT 20",
        hide,
    ).fetchall()

    month_count = db.execute(
        "SELECT COUNT(*) FROM archive WHERE created_at LIKE ?", (month + "%",)
    ).fetchone()[0]
    month_errors = db.execute(
        "SELECT COUNT(*) FROM archive WHERE created_at LIKE ? AND has_issue = 1",
        (month + "%",),
    ).fetchone()[0]
    total_count = db.execute("SELECT COUNT(*) FROM archive").fetchone()[0]
    total_amount = db.execute("SELECT COALESCE(SUM(total_amount), 0) FROM archive").fetchone()[0]

    type_names = {"text": "粘贴文字", "image": "图片", "pdf": "PDF"}
    lines = ["【系统数据快照】（实时读取自数据库）"]
    lines.append("当前时间：" + now.strftime("%Y-%m-%d %H:%M"))
    lines.append("")
    lines.append("一、今天（%s）的审核记录：共 %d 条" % (today, today_total))
    if not today_rows:
        lines.append("（今天还没有审核记录）")
    for i, r in enumerate(today_rows, 1):
        probs = _extract_problems(r["audit_result"])
        ptext = ("发现 %d 处问题：%s" % (len(probs), "；".join(probs))) if probs else "未发现问题"
        lines.append("%d. %s [%s] %s ｜ %s" % (
            i, r["created_at"][11:16], type_names.get(r["input_type"], r["input_type"]),
            (r["input_summary"] or "").replace("\n", " ")[:60], ptext))
    if today_total > len(today_rows):
        lines.append("（今天共 %d 条，仅列最近 %d 条）" % (today_total, len(today_rows)))
    lines.append("")
    lines.append("二、最近 20 条记录概览（含今天）：")
    for r in recent_rows:
        probs = _extract_problems(r["audit_result"], max_items=3, clip=60)
        ptext = ("%d 处问题" % len(probs)) if probs else "无问题"
        lines.append("- %s [%s] %s ｜ %s" % (
            r["created_at"][:16], type_names.get(r["input_type"], r["input_type"]),
            (r["input_summary"] or "").replace("\n", " ")[:50], ptext))
    if not recent_rows:
        lines.append("（暂无记录）")
    lines.append("")
    lines.append("三、档案与金额统计：")
    lines.append("- 本月（%s）档案单数：%d 单，其中 %d 单发现问题" % (month, month_count, month_errors))
    lines.append("- 历史累计档案：%d 单；累计金额：USD %.2f" % (total_count, total_amount))
    return "\n".join(lines)


def _chat(messages):
    url = Config.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions"
    resp = requests.post(
        url,
        headers={
            "Authorization": "Bearer " + Config.DEEPSEEK_API_KEY,
            "Content-Type": "application/json",
        },
        json={
            "model": Config.DEEPSEEK_MODEL,
            "messages": messages,
            "temperature": 0.4,
            "max_tokens": 16384,
        },
        timeout=120,
    )
    resp.raise_for_status()
    content = strip_emoji((resp.json()["choices"][0]["message"].get("content") or "").strip())
    return content or "抱歉，这次没组织好回答，请再问一次。"


def _build_context(thread_id):
    """组装发给模型的会话上下文：历史摘要（如有）+ 最近若干条原文"""
    all_msgs = list_messages(thread_id, limit=300)
    summaries = [m for m in all_msgs if m["kind"] == "summary"][-MAX_SUMMARIES_IN_CONTEXT:]
    recent = [m for m in all_msgs if m["kind"] != "summary"][-_CONTEXT_RECENT:]

    msgs = []
    for s in summaries:
        msgs.append({"role": "user", "content": "【本会话更早对话的摘要】\n" + s["content"]})
    for m in recent:
        content = m["content"]
        if len(content) > _CONTEXT_CLIP:
            content = content[:_CONTEXT_CLIP] + "……（此处省略）"
        msgs.append({"role": m["role"], "content": content})
    return msgs


def _summarize(messages):
    text_parts = []
    for m in messages:
        clip = m["content"][:400] + ("…" if len(m["content"]) > 400 else "")
        tag = "用户" if m["role"] == "user" else "助手"
        text_parts.append("%s：%s" % (tag, clip))
    payload = {
        "model": Config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": _SUMMARY_PROMPT},
            {"role": "user", "content": "\n".join(text_parts)},
        ],
        "temperature": 0.3,
        # 推理模型思考也占用额度，须留足空间，否则 content 为空
        "max_tokens": 16384,
    }
    resp = requests.post(
        Config.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions",
        headers={
            "Authorization": "Bearer " + Config.DEEPSEEK_API_KEY,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    content = strip_emoji((resp.json()["choices"][0]["message"].get("content") or "").strip())
    if not content:
        return ""
    return content[:600]


def maybe_compress(thread_id):
    """会话消息超过阈值时：把最早的旧消息压缩成一条摘要，只保留最近若干条原文"""
    all_msgs = list_messages(thread_id, limit=300)
    if len(all_msgs) <= COMPRESS_THRESHOLD:
        return False
    head = all_msgs[:-KEEP_RECENT]
    if not head:
        return False
    # 头部如果只剩摘要消息就不重复压缩
    if all(m["kind"] == "summary" for m in head):
        return False
    try:
        summary = _summarize(head)
    except Exception:
        return False
    if not summary:
        return False
    db = _db()
    head_ids = [m["id"] for m in head]
    db.execute(
        "DELETE FROM chat_message WHERE thread_id = ? AND id IN (%s)" % ",".join("?" * len(head_ids)),
        [thread_id] + head_ids,
    )
    db.execute(
        "INSERT INTO chat_message (role, content, kind, created_at, thread_id) VALUES (?, ?, ?, ?, ?)",
        ("summary", summary, "summary", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), thread_id),
    )
    db.commit()
    return True


def answer(message, thread_id=None):
    """处理一条消息，返回 (reply, thread_id)。两端消息都会落库；长会话自动压缩。"""
    text = (message or "").strip()
    if not text:
        raise ValueError("消息为空")

    if thread_id is None:
        title = text.replace("\n", " ")[:24]
        thread_id = create_thread(title)

    save_message("user", text, "chat", thread_id)
    _touch_thread(thread_id)

    snapshot = build_snapshot()
    msgs = [{"role": "system", "content": _system_prompt().replace("{snapshot}", snapshot)}]
    msgs.extend(_build_context(thread_id))
    msgs.append({"role": "user", "content": text})
    reply = _chat(msgs)

    save_message("assistant", reply, "chat", thread_id)
    _touch_thread(thread_id)
    maybe_compress(thread_id)

    return reply, thread_id
