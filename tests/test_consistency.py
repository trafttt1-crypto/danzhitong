# -*- coding: utf-8 -*-
"""单证一致性比对的单元测试。运行：python -m unittest discover -s tests -v"""
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import consistency as c  # noqa: E402
from services.consistency_sample import SAMPLE_DOCS  # noqa: E402


class AmountParsing(unittest.TestCase):
    def test_common_writings(self):
        cases = {
            "USD 15,600.00": ("USD", Decimal("15600.00")),
            "USD15600,00": ("USD", Decimal("15600.00")),      # MT700 的小数逗号
            "15600.00 USD": ("USD", Decimal("15600.00")),
            "US$ 1,234.56": ("USD", Decimal("1234.56")),
            "USD 15,600": ("USD", Decimal("15600")),          # 千分位，不是小数
        }
        for raw, want in cases.items():
            self.assertEqual(c.parse_amount(raw), want, raw)

    def test_garbage_is_none_not_zero(self):
        self.assertEqual(c.parse_amount("TBD"), (None, None))
        self.assertEqual(c.parse_amount(""), (None, None))


class DetectType(unittest.TestCase):
    def test_sample_types(self):
        self.assertEqual([c.detect_type(t) for t in SAMPLE_DOCS], ["lc", "invoice", "packing", "bl"])

    def test_unknown_when_no_signal(self):
        self.assertEqual(c.detect_type("今天天气不错"), "unknown")


class Extraction(unittest.TestCase):
    def test_label_value_same_line(self):
        f = c.extract_fields(SAMPLE_DOCS[1], "invoice")
        self.assertEqual(f["invoice_no"], "INV-2026-0620")
        self.assertEqual(f["amount"], "USD 16,200.00")
        self.assertEqual(f["currency"], "USD")
        self.assertTrue(f["shipper"].startswith("NINGBO SUNRISEE"))

    def test_ocr_value_on_next_line_and_glued_bilingual_label(self):
        # OCR 常把中英标签连着写，值在下一行（档案里 #67 那种）
        text = "商业发票\nCOMMERCIAL INVOICE\n发票号 Invoice No.\nINV-9\n发货人Shipper\nNINGBO A CO., LTD.\n收货人 Consignee\nGLOBAL B LLC\n"
        f = c.extract_fields(text, "invoice")
        self.assertEqual(f["invoice_no"], "INV-9")
        self.assertEqual(f["shipper"], "NINGBO A CO., LTD.")
        self.assertEqual(f["consignee"], "GLOBAL B LLC")

    def test_empty_field_is_missing_not_next_label(self):
        # "发货人:" 后面直接是下一栏标签 —— 必须是"没抽到"，不能把标签当成值
        text = "COMMERCIAL INVOICE\nShipper:\nPort of Loading: NINGBO\nConsignee: X LLC\n"
        f = c.extract_fields(text, "invoice")
        self.assertNotIn("shipper", f)
        self.assertEqual(f["port_loading"], "NINGBO")

    def test_mt700_tags(self):
        f = c.extract_fields(SAMPLE_DOCS[0], "lc")
        self.assertEqual(c.parse_amount(f["amount"]), ("USD", Decimal("15600.00")))
        self.assertEqual(f["shipper"], "NINGBO SUNRISE IMP & EXP CO., LTD.")
        self.assertEqual(f["consignee"], "GLOBAL TRADING LLC, DUBAI, UAE")
        self.assertEqual(f["port_discharge"], "JEBEL ALI, UAE")


class ValueSanity(unittest.TestCase):
    """抽不准的值必须变成「未提取」，不能进入比对画出假红线。这些都是从真实档案原文里见过的坏样子。"""

    def test_dashed_rule_line_is_not_a_value(self):
        self.assertEqual(c._clean_value("port_discharge", "------------------------------------------------------------"), "")

    def test_table_header_fragment_is_not_a_weight(self):
        self.assertEqual(c._clean_value("gross_weight", "(KGS)  N.W.(KGS) Meas.(CBM)"), "")

    def test_table_row_is_not_a_goods_description(self):
        row = "1     STAINLESS STEEL WATER BOTTLE 500ML   2000  PCS    USD 4.50      USD 9000.00"
        self.assertEqual(c._clean_value("goods", row), "")

    def test_marks_are_cut_before_the_next_inline_label(self):
        v = c._clean_value("marks", "GTL/DUBAI/1-100 备注 Remarks: PACKED IN EXPORT STANDARD CARTONS")
        self.assertEqual(v, "GTL/DUBAI/1-100")

    def test_normal_values_survive_and_spaces_collapse(self):
        self.assertEqual(c._clean_value("amount", "USD    1001.01"), "USD 1001.01")
        self.assertEqual(c._clean_value("shipper", "NINGBO SUNRISE IMP & EXP CO., LTD."), "NINGBO SUNRISE IMP & EXP CO., LTD.")

    def test_garbage_never_becomes_a_red_line(self):
        # 一边是虚线、一边是正常港口：必须是 unknown（灰），不能是 conflict（红）
        a = c.extract_fields("COMMERCIAL INVOICE\nPort of Discharge: ------------------------------------------------------------\n", "invoice")
        self.assertNotIn("port_discharge", a)


class Comparison(unittest.TestCase):
    def test_invoice_below_lc_is_ok_above_is_conflict(self):
        self.assertEqual(c.compare_values("amount", "lc", "USD 15,600.00", "invoice", "USD 15,000.00")[0], "ok")
        self.assertEqual(c.compare_values("amount", "lc", "USD 15,600.00", "invoice", "USD 16,200.00")[0], "conflict")
        # 顺序反过来（发票在前）结论不能变
        self.assertEqual(c.compare_values("amount", "invoice", "USD 16,200.00", "lc", "USD 15,600.00")[0], "conflict")

    def test_currency_mismatch_is_conflict(self):
        st, note = c.compare_values("amount", "lc", "USD 100", "invoice", "EUR 100")
        self.assertEqual(st, "conflict")
        self.assertIn("币别", note)

    def test_party_punctuation_insensitive_but_typo_is_near(self):
        self.assertEqual(c.compare_values("shipper", "lc", "NINGBO SUNRISE IMP & EXP CO., LTD.",
                                          "invoice", "Ningbo Sunrise Imp & Exp Co Ltd")[0], "ok")
        self.assertEqual(c.compare_values("shipper", "lc", "NINGBO SUNRISE IMP & EXP CO., LTD.",
                                          "invoice", "NINGBO SUNRISEE IMP & EXP CO., LTD.")[0], "near")

    def test_different_company_is_conflict_not_near(self):
        self.assertEqual(c.compare_values("shipper", "invoice", "NINGBO SUNRISE CO", "bl", "SHANGHAI RISING TRADING")[0], "conflict")

    def test_numbers_compare_by_value(self):
        self.assertEqual(c.compare_values("gross_weight", "packing", "2,700 KGS", "bl", "2700 KG")[0], "ok")
        self.assertEqual(c.compare_values("gross_weight", "packing", "2,700 KGS", "bl", "2,760 KGS")[0], "conflict")

    def test_missing_side_is_unknown_never_conflict(self):
        self.assertEqual(c.compare_values("amount", "lc", "USD 1", "invoice", "")[0], "unknown")

    def test_unparseable_amount_is_unknown_not_conflict(self):
        self.assertEqual(c.compare_values("amount", "lc", "TBD", "invoice", "USD 100")[0], "unknown")

    def test_port_country_suffix_ignored(self):
        self.assertEqual(c.compare_values("port_discharge", "lc", "JEBEL ALI, UAE", "bl", "JEBEL ALI")[0], "ok")
        self.assertEqual(c.compare_values("port_discharge", "lc", "JEBEL ALI, UAE", "bl", "DUBAI, UAE")[0], "conflict")


class SampleGraph(unittest.TestCase):
    """样例里埋了 4 处差异，图必须正好找出这 4 处，不多不少。"""

    @classmethod
    def setUpClass(cls):
        cls.g = c.build_graph(SAMPLE_DOCS)
        cls.bad = {(e["key"], e["status"]) for e in cls.g["edges"] if e["status"] in ("conflict", "near")}

    def test_column_order(self):
        self.assertEqual([d["type"] for d in self.g["docs"]], ["lc", "invoice", "packing", "bl"])

    def test_exactly_the_planted_differences(self):
        self.assertEqual(self.bad, {
            ("amount", "conflict"),
            ("shipper", "near"),
            ("gross_weight", "conflict"),
            ("port_discharge", "conflict"),
        })

    def test_rule_hints_only_where_certain(self):
        bad = [e for e in self.g["edges"] if e["status"] in ("conflict", "near")]
        rules = lambda key, st: sorted(e["rule"] for e in bad if e["key"] == key and e["status"] == st)
        self.assertEqual(rules("amount", "conflict"), ["R11"])
        # 发票里的拼写错误让"信用证-发票"（R32 发票出具人）和"发票-装箱单"（R36 三方名称）两条边都变黄：
        # 发票是那个出错的，两条边都该亮
        self.assertEqual(rules("shipper", "near"), ["R32", "R36"])
        self.assertEqual(rules("port_discharge", "conflict"), [""])      # 装箱单-提单这一对没有对应规则
        self.assertEqual(rules("gross_weight", "conflict"), [""])

    def test_many_consistent_edges_exist(self):
        self.assertGreaterEqual(self.g["summary"]["ok"], 10)

    def test_deterministic(self):
        self.assertEqual(c.build_graph(SAMPLE_DOCS), self.g)

    def test_lc_applicant_not_compared_with_bl_consignee(self):
        only_lc_and_bl = c.build_graph([SAMPLE_DOCS[0], SAMPLE_DOCS[3]])
        keys = {(e["key"], e["a"], e["b"]) for e in only_lc_and_bl["edges"]}
        self.assertFalse(any(k[0] == "consignee" for k in keys))


if __name__ == "__main__":
    unittest.main()
