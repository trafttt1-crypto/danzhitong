# -*- coding: utf-8 -*-
"""实训练习（教育版专属）：出题、作答、判卷。

这个模块的存在理由：审核功能是「贴进去出答案」，工作场景对，练习场景是反教学的
—— 学生一个脑子都不用动。实训要的是反过来：**先让学生自己找，再对答案**。

判卷全程是集合运算，不调用大模型。快、不花钱、结果可复现，
而且同一份作答永远得同一个分数 —— 这对教学场景比「AI 打分」重要得多。
"""
import json
import sqlite3
from datetime import datetime

from flask import g

from config.settings import Config


def _db():
    """请求上下文里的连接。与 services/history.py 的 get_db() 共用 g.db，
    所以同一次请求里几个 service 拿到的是同一个连接（项目现状如此）。"""
    if "db" not in g:
        g.db = sqlite3.connect(Config.DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _loads(raw):
    """把库里存的 JSON 数组读回来。脏数据一律退化成空列表，不让它把页面搞崩。"""
    try:
        v = json.loads(raw or "[]")
        return [str(x) for x in v] if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


def _dumps(items):
    return json.dumps(sorted({str(x) for x in items if x}))


# ============================================================ 建表


def init_practice():
    db = sqlite3.connect(Config.DB_PATH)
    db.execute(
        """CREATE TABLE IF NOT EXISTS practice_case (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            doc_text TEXT NOT NULL,
            lc_text TEXT DEFAULT '',
            doc_count INTEGER DEFAULT 1,
            answer_rules TEXT NOT NULL DEFAULT '[]',
            hint TEXT DEFAULT '',
            source_record_id INTEGER DEFAULT 0,
            is_builtin INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )"""
    )
    # 加列一律走这个写法：重复执行会抛 OperationalError，吞掉即可
    for col in ("is_builtin INTEGER DEFAULT 0", "doc_count INTEGER DEFAULT 1",
                "hint TEXT DEFAULT ''", "source_record_id INTEGER DEFAULT 0"):
        try:
            db.execute("ALTER TABLE practice_case ADD COLUMN " + col)
        except sqlite3.OperationalError:
            pass  # column already exists

    db.execute(
        """CREATE TABLE IF NOT EXISTS practice_attempt (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL,
            picked_rules TEXT NOT NULL DEFAULT '[]',
            hit_rules TEXT NOT NULL DEFAULT '[]',
            missed_rules TEXT NOT NULL DEFAULT '[]',
            wrong_rules TEXT NOT NULL DEFAULT '[]',
            score INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )"""
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_attempt_case ON practice_attempt(case_id)")
    db.commit()

    _seed_builtin(db)
    db.commit()
    db.close()


# ============================================================ 判卷


def grade(picked, answer):
    """把学生勾的和标准答案比一遍。纯集合运算，没有随机性。

    为什么要扣误报：不扣的话「全选 60 条」就是满分，练习立刻失去意义。
    真实银行审单里误报不符点同样不专业，扣分是有实务依据的，不是为难学生。

    返回 找对 / 漏报 / 多报 三个清单和百分制得分。
    """
    p = {str(x) for x in (picked or []) if x}
    a = {str(x) for x in (answer or []) if x}

    hit = sorted(p & a)
    missed = sorted(a - p)
    wrong = sorted(p - a)

    if not a:
        # 规范样板题：正确答案是「没有问题」，学生勾了任何一条都算多报
        score = 100 if not p else 0
    else:
        raw = (len(hit) - len(wrong)) / float(len(a))
        score = int(round(max(0.0, min(1.0, raw)) * 100))

    return {
        "hit": hit,
        "missed": missed,
        "wrong": wrong,
        "score": score,
        "answer_count": len(a),
    }


# ============================================================ 增删查


def list_cases():
    """题目列表。**故意不带 answer_rules** —— 这个函数的结果会直接进 JSON 响应。"""
    db = _db()
    rows = db.execute(
        """SELECT c.id, c.title, c.hint, c.doc_count, c.is_builtin, c.created_at,
                  LENGTH(c.answer_rules) AS _n,
                  (SELECT COUNT(*) FROM practice_attempt a WHERE a.case_id = c.id) AS attempts,
                  (SELECT MAX(score) FROM practice_attempt a WHERE a.case_id = c.id) AS best_score,
                  (SELECT score FROM practice_attempt a WHERE a.case_id = c.id
                   ORDER BY a.id DESC LIMIT 1) AS last_score
           FROM practice_case c ORDER BY c.id"""
    ).fetchall()
    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "title": r["title"],
            "hint": r["hint"] or "",
            "doc_count": r["doc_count"] or 1,
            "is_builtin": bool(r["is_builtin"]),
            "created_at": r["created_at"],
            "attempts": r["attempts"] or 0,
            "best_score": r["best_score"],
            "last_score": r["last_score"],
            # 只给数量不给内容：学生需要知道「要找几处」，但不能知道是哪几处
            "answer_count": len(_loads(
                db.execute("SELECT answer_rules FROM practice_case WHERE id = ?",
                           (r["id"],)).fetchone()[0])),
        })
    return items


def get_case(case_id, with_answer=False):
    """题目详情。默认不含答案；只有判卷和出题编辑两处才要 with_answer=True。"""
    row = _db().execute(
        "SELECT * FROM practice_case WHERE id = ?", (case_id,)).fetchone()
    if row is None:
        return None
    item = {
        "id": row["id"],
        "title": row["title"],
        "doc_text": row["doc_text"],
        "lc_text": row["lc_text"] or "",
        "doc_count": row["doc_count"] or 1,
        "hint": row["hint"] or "",
        "is_builtin": bool(row["is_builtin"]),
        "created_at": row["created_at"],
        "answer_count": len(_loads(row["answer_rules"])),
    }
    if with_answer:
        item["answer_rules"] = _loads(row["answer_rules"])
    return item


def create_case(title, doc_text, lc_text, answer_rules, hint="",
                doc_count=1, source_record_id=0, is_builtin=0):
    db = _db()
    db.execute(
        """INSERT INTO practice_case
           (title, doc_text, lc_text, doc_count, answer_rules, hint,
            source_record_id, is_builtin, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, doc_text, lc_text or "", int(doc_count or 1),
         _dumps(answer_rules), hint or "", int(source_record_id or 0),
         int(is_builtin or 0), _now()),
    )
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def delete_case(case_id):
    db = _db()
    db.execute("DELETE FROM practice_case WHERE id = ?", (case_id,))
    db.execute("DELETE FROM practice_attempt WHERE case_id = ?", (case_id,))
    db.commit()
    return True


def save_attempt(case_id, result):
    db = _db()
    db.execute(
        """INSERT INTO practice_attempt
           (case_id, picked_rules, hit_rules, missed_rules, wrong_rules, score, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (case_id, _dumps(result.get("picked", [])), _dumps(result.get("hit", [])),
         _dumps(result.get("missed", [])), _dumps(result.get("wrong", [])),
         int(result.get("score", 0)), _now()),
    )
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


# ============================================================ 预置题库


# 预置题库的标准答案。**这是人工对着规则表复核过的结论，不是模型输出** ——
# 跑一次审核只能得到初稿，模型会漏报也会误报，不能直接拿来当答案。
#
# 复核只认两条：该规则在当前输入下确实可执行（config.prompts.rule_available），
# 且单据本身确实违反。宁可少列一条，也不塞进有争议的 ——
# 一道题的答案错了，学生照着背下来比不做还糟。
#
# 前两道的单据取自 static/js/cases.js 的内置样例（真实业务里常见的错法）；
# 第三道是为教学另编的，考点密度更高，四个错误彼此独立、互不牵连。
_BUILTIN_CASES = [
    {
        # 2000 × 4.50 = 9000，总价写 8900 → R01
        # 收货人只有公司名，无城市无国别 → R35
        # 发票没有 TOTAL PKGS 栏，R43 的检查条件不成立，故不列
        "title": "商业发票 INV-2024-0508（找不符点）",
        "hint": "单份商业发票，未提供信用证条款。共 2 处问题，一处很明显，一处容易被放过。",
        "answer": ["R01", "R35"],
        "doc_text": """商业发票
COMMERCIAL INVOICE

发票号 Invoice No.: INV-2024-0508
日期 Date: 2024-05-08

发货人 Shipper: NINGBO SUNRISE IMP & EXP CO., LTD.
收货人 Consignee: GLOBAL TRADING LLC

装运港 Port of Loading: NINGBO, CHINA
目的港 Port of Discharge: JEBEL ALI, UAE
贸易术语 Trade Terms: FOB NINGBO

货物描述 Description: CERAMIC DINNER SET
数量 Quantity: 2000 PCS
单价 Unit Price: USD 4.50
总价 Total Amount: USD 8900.00

付款方式 Payment: T/T
唛头 Shipping Mark: N/M""",
    },
    {
        # 净重 1920 大于毛重 1850 → R04
        # 收货人写了 DUBAI, UAE，地址完整，R35 不列
        # 唛头区间 1-100 = 100 箱，与包装栏 100 CARTONS 相符，R43 不列
        "title": "装箱单 INV-2024-0508（找不符点）",
        "hint": "单份装箱单，未提供信用证条款。只错了一处，但错得很典型。",
        "answer": ["R04"],
        "doc_text": """装箱单
PACKING LIST

发票号 Invoice No.: INV-2024-0508
日期 Date: 2024-05-08

发货人 Shipper: NINGBO SUNRISE IMP & EXP CO., LTD.
收货人 Consignee: GLOBAL TRADING LLC, DUBAI, UAE

货物描述 Description: CERAMIC DINNER SET
数量 Quantity: 2000 PCS
包装 Packing: 100 CARTONS
毛重 Gross Weight: 1850 KGS
净重 Net Weight: 1920 KGS
体积 Measurement: 12.5 CBM
唛头 Shipping Mark: GTL/DUBAI/1-100""",
    },
    {
        # 四个考点互相独立，一份单据上把最常见的几类错都摊开：
        #   2000 × 4.50 = 9000，总价写 8900        → R01 金额验算
        #   净重 1920 > 毛重 1850                  → R04 重量逻辑
        #   收货人只有公司名                        → R35 地址完整性
        #   唛头区间 1-50 = 50 箱，件数栏 100 CTNS  → R43 唛头与件数
        "title": "商业发票 INV-2026-0312（综合练习）",
        "hint": "四个错误分属不同类别，一处一处核。金额、重量、当事人、唛头各看一遍，别只看金额。",
        "answer": ["R01", "R04", "R35", "R43"],
        "doc_text": """商业发票
COMMERCIAL INVOICE

发票号 Invoice No.: INV-2026-0312
日期 Date: 2026-03-12

发货人 Shipper: NINGBO SUNRISE IMP & EXP CO., LTD., NO.88 ZHONGSHAN ROAD, NINGBO, CHINA
收货人 Consignee: GLOBAL TRADING LLC

装运港 Port of Loading: NINGBO, CHINA
目的港 Port of Discharge: JEBEL ALI, UAE
贸易术语 Trade Terms: CIF JEBEL ALI

货物描述 Description: CERAMIC DINNER SET
数量 Quantity: 2000 PCS
单价 Unit Price: USD 4.50
总价 Total Amount: USD 8,900.00
金额大写 Amount in Words: SAY US DOLLARS EIGHT THOUSAND NINE HUNDRED ONLY

件数 Total Packages: 100 CTNS
毛重 Gross Weight: 1,850 KGS
净重 Net Weight: 1,920 KGS
体积 Measurement: 12.5 CBM

付款方式 Payment: T/T
唛头 Shipping Mark: GTL/DUBAI/1-50""",
    },
]


def _seed_builtin(db):
    """只在题库为空时铺预置题。用户自己出的题不会被覆盖。"""
    n = db.execute("SELECT COUNT(*) FROM practice_case").fetchone()[0]
    if n:
        return
    for item in _BUILTIN_CASES:
        db.execute(
            """INSERT INTO practice_case
               (title, doc_text, lc_text, doc_count, answer_rules, hint,
                source_record_id, is_builtin, created_at)
               VALUES (?, ?, '', 1, ?, ?, 0, 1, ?)""",
            (item["title"], item["doc_text"], _dumps(item["answer"]),
             item["hint"], _now()),
        )
