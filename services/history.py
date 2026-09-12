import sqlite3
from datetime import datetime
from flask import g, current_app
from config.settings import Config


def init_db():
    db = sqlite3.connect(Config.DB_PATH)
    db.execute(
        """CREATE TABLE IF NOT EXISTS audit_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            input_type TEXT NOT NULL,
            input_summary TEXT NOT NULL,
            ocr_text TEXT,
            audit_result TEXT NOT NULL
        )"""
    )
    # 助手每次对话都会按 created_at 做 LIKE 查询 + 倒序取最近若干条，
    # archive 表早就建了同样的索引，这里漏了
    db.execute("CREATE INDEX IF NOT EXISTS idx_history_created ON audit_history(created_at)")
    db.commit()
    db.close()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(Config.DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def save_audit_record(input_type, input_summary, ocr_text, audit_result):
    db = get_db()
    db.execute(
        "INSERT INTO audit_history (created_at, input_type, input_summary, ocr_text, audit_result) VALUES (?, ?, ?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), input_type, input_summary, ocr_text, audit_result),
    )
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]
