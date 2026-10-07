# -*- coding: utf-8 -*-
"""2026-10-07 一轮查 bug 修掉的问题，每条一个回归测试。

接口类测试用临时数据库、把 AI 调用替换成假函数：不碰真实 history.db，也不花 API 额度。
"""
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.archive import has_issue  # noqa: E402
from services.lc_deadline import presentation_deadline  # noqa: E402

# 真实记录 #86 的结论原文：通过的单据，但句中有"未发现需修改项"
PASS_86 = ("【发现问题】\n未发现明显错误\n\n【审核结论】\n"
           "通过（单证内部自查未发现问题）：数量、包装、唛头箱数、毛净重、体积及 HS 归类逻辑自洽，"
           "未发现需修改项；仅日期时效、易碎品包装标识等事项需人工复核。\n")


class VerdictTest(unittest.TestCase):
    def test_pass_with_need_fix_words_is_pass(self):
        self.assertFalse(has_issue(PASS_86))

    def test_pass_in_bold_is_pass(self):
        self.assertFalse(has_issue("【审核结论】\n**通过**：未发现需修改项"))

    def test_need_fix_is_issue(self):
        self.assertTrue(has_issue("【审核结论】\n需修改：发票金额与单价×数量不符"))

    def test_not_pass_is_not_read_as_pass(self):
        self.assertTrue(has_issue("【审核结论】\n不通过，金额错误"))

    def test_listed_issue_beats_pass_word(self):
        self.assertTrue(has_issue("【发现问题】\n问题1：[R01][error] 金额栏 - 算错 → 改\n【审核结论】\n通过"))

    def test_no_verdict_word_falls_back(self):
        self.assertTrue(has_issue("【审核结论】\n单据存在错误，需修改金额"))
        self.assertFalse(has_issue("【审核结论】\n单据整体正常"))


class DeadlineRobustTest(unittest.TestCase):
    T = date(2026, 10, 7)

    def test_bad_days_fall_back_to_21(self):
        for d in ("abc", "21.5", 10 ** 9, -5):
            r = presentation_deadline("2026-10-01", "", days=d, today=self.T)
            self.assertTrue(r["ok"], d)
            self.assertEqual(r["days"], 21, d)

    def test_huge_mailing_days_is_capped(self):
        r = presentation_deadline("2026-10-01", "", mailing_days=10 ** 9, today=self.T)
        self.assertTrue(r["ok"])
        self.assertEqual(r["mailing_days"], 60)

    def test_out_of_range_year_is_an_input_error(self):
        r = presentation_deadline("9999-12-31", "", today=self.T)
        self.assertFalse(r["ok"])
        self.assertIn("无法识别", r["error"])

    def test_single_ambiguous_date_gets_ambiguity_hint(self):
        r = presentation_deadline("03/04/2026", "", today=self.T)
        self.assertFalse(r["ok"])
        self.assertIn("歧义", r["error"])

    def test_normal_case_unchanged(self):
        r = presentation_deadline("2026-10-01", "2026-10-31", days=15, today=self.T)
        self.assertEqual(r["deadline"], "2026-10-16")


class RouteGuardTest(unittest.TestCase):
    """create_app 只建一次：它会起一个后台清理线程。"""

    @classmethod
    def setUpClass(cls):
        import app as app_module
        from config.settings import Config
        cls.tmp = tempfile.mkdtemp(prefix="dzt_test_")
        cls._saved = {k: getattr(Config, k) for k in ("DB_PATH", "ACCESS_PASSWORD", "SECRET_KEY")}
        Config.DB_PATH = os.path.join(cls.tmp, "test.db")
        Config.ACCESS_PASSWORD = "pw123"
        Config.SECRET_KEY = "test-secret"
        for k in ("DEEPSEEK_API_KEY", "BAIDU_API_KEY", "BAIDU_SECRET_KEY"):
            os.environ.setdefault(k, "test")
        cls.mod = app_module
        cls.app = app_module.create_app()
        cls.app.config["TESTING"] = True

    @classmethod
    def tearDownClass(cls):
        from config.settings import Config
        for k, v in cls._saved.items():
            setattr(Config, k, v)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.mod.login_limiter._clients.clear()
        self.mod.limiter._clients.clear()
        self.c = self.app.test_client()

    def login(self):
        self.c.post("/login", data={"password": "pw123"})

    def test_chinese_password_is_wrong_not_500(self):
        r = self.c.post("/login", data={"password": "密码"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("口令不正确", r.get_data(as_text=True))

    def test_correct_password_logs_in(self):
        r = self.c.post("/login", data={"password": "pw123"})
        self.assertEqual(r.status_code, 302)

    def test_lockout_after_ten_wrong(self):
        for _ in range(10):
            self.c.post("/login", data={"password": "nope"})
        r = self.c.post("/login", data={"password": "pw123"})
        self.assertEqual(r.status_code, 429)

    def test_cf_header_only_trusted_from_localhost(self):
        # 隧道过来的两个人各有各的名额；一个人输错 10 次不该把另一个锁在门外
        for _ in range(10):
            self.c.post("/login", data={"password": "nope"},
                        headers={"CF-Connecting-IP": "1.1.1.1"})
        r = self.c.post("/login", data={"password": "pw123"},
                        headers={"CF-Connecting-IP": "2.2.2.2"})
        self.assertEqual(r.status_code, 302)

    def _history_count(self):
        import sqlite3
        from config.settings import Config
        db = sqlite3.connect(Config.DB_PATH)
        try:
            return db.execute("SELECT COUNT(*) FROM audit_history").fetchone()[0]
        finally:
            db.close()

    def test_empty_ai_reply_is_error_and_not_saved(self):
        self.login()
        before = self._history_count()
        with mock.patch("routes.main.deepseek_audit", return_value="  \n"):
            r = self.c.post("/api/audit-text", json={"text": "COMMERCIAL INVOICE"})
        self.assertEqual(r.status_code, 502)
        self.assertIn("没有返回内容", r.get_json()["error"])
        self.assertEqual(self._history_count(), before)

    def test_empty_lc_review_is_error(self):
        self.login()
        with mock.patch("routes.main.deepseek_lc_review", return_value=""):
            r = self.c.post("/api/lc-review", json={"text": "MT700 :20: LC1"})
        self.assertEqual(r.status_code, 502)

    def test_huge_page_number_is_clamped(self):
        self.login()
        r = self.c.get("/api/history?page=99999999999999999999")
        self.assertEqual(r.status_code, 200)

    def test_duplicate_answer_rules_are_merged(self):
        self.login()
        r = self.c.post("/api/practice/cases",
                        json={"title": "t", "doc_text": "d", "answer_rules": ["R01", "r01"]})
        cid = r.get_json()["id"]
        detail = self.c.get("/api/practice/cases/%d" % cid).get_json()
        self.assertEqual(detail["case"]["answer_count"], 1)

    def test_bad_deadline_input_is_not_500(self):
        self.login()
        r = self.c.post("/api/lc-deadline", json={"shipment_date": "2026-10-01", "days": "abc"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])


if __name__ == "__main__":
    unittest.main()
