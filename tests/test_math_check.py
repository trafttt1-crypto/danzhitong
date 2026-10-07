# -*- coding: utf-8 -*-
"""数学验算：程序算，不让模型心算。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.math_check import check, facts_block  # noqa: E402
from services.consistency_sample import INVOICE, PACKING  # noqa: E402

# 真实 OCR 输出（表格被拆成一行一个格子），来自一次实测：模型把 3,000 × 5.20 算成了 15,000
OCR_TABLE = """商业发票
COMMERCIAL INVOICE
货物描述 Description
数量 Qty
单价 Unit Price
金额 Amount
CERAMIC DINNER SET
3,000 PCS
USD 5.20
USD 15,000.00
20-PIECE, WHITE PORCELAIN
总价 Total Amount
USD 15,000.00
件数 Packages
150 CTNS
毛重 Gross Weight
2,700 KGS
净重 Net Weight
2,850 KGS
唛头 Shipping Mark
GTL/DUBAI/1-75
"""


def rules(r):
    return sorted(p["rule"] for p in r["problems"])


class MathCheckTest(unittest.TestCase):
    def test_ocr_table_layout_finds_all_three(self):
        r = check(OCR_TABLE)
        self.assertEqual(rules(r), ["R01", "R04", "R43"])
        r01 = [p for p in r["problems"] if p["rule"] == "R01"][0]["text"]
        self.assertIn("15,600.00", r01)
        self.assertIn("600.00", r01)

    def test_correct_invoice_has_no_problem(self):
        r = check(INVOICE)          # 3000 × 5.40 = 16,200 正确（它的错在与信用证不符，不归这里管）
        self.assertEqual(r["problems"], [])
        self.assertTrue(any("16,200.00" in f and "一致" in f for f in r["facts"]))

    def test_packing_weights_and_marks_ok(self):
        r = check(PACKING)          # 净重 2,450 ≤ 毛重 2,700；唛头 1-150 = 150 箱
        self.assertEqual(r["problems"], [])
        self.assertEqual(len(r["facts"]), 2)

    def test_label_colon_format(self):
        t = "数量 Quantity: 2000 PCS\n单价 Unit Price: USD 4.50\n金额 Amount: USD 8,900.00\n"
        self.assertEqual(rules(check(t)), ["R01"])

    def test_date_is_not_a_mark_range(self):
        t = "唛头 Shipping Mark: N/M\n日期 Date: 2026-06-20\n件数 Packages: 150 CTNS\n"
        self.assertEqual(check(t)["problems"], [])

    def test_nothing_to_check_injects_nothing(self):
        self.assertEqual(facts_block("信用证 MT700\n:20: LC2026-0088\n"), "")

    def test_ambiguous_weights_are_skipped(self):
        t = "毛重 Gross Weight: 2,700 KGS\n毛重 Gross Weight: 2,760 KGS\n净重 Net Weight: 2,800 KGS\n"
        self.assertEqual(check(t)["problems"], [])

    # ---- 2026-10-07：折扣/扣款行会让"各行之和 ≠ 总价"，原来把正确的发票判成 R01 ----
    TWO_ROWS = ("1. COTTON T-SHIRT 1000 PCS USD 5.00 USD 5,000.00\n"
                "2. DENIM JEANS 500 PCS USD 10.00 USD 5,000.00\n")

    def test_discount_line_is_not_a_sum_error(self):
        t = self.TWO_ROWS + "Less Discount 5%: USD 500.00\nTotal Amount: USD 9,500.00\n"
        r = check(t)
        self.assertEqual(r["problems"], [])
        self.assertTrue(any("调整项" in f for f in r["facts"]))

    def test_chinese_deduction_line_is_not_a_sum_error(self):
        t = self.TWO_ROWS + "扣除预付款 USD 3,000.00\n总金额 USD 7,000.00\n"
        self.assertEqual(check(t)["problems"], [])

    def test_subtotal_discount_grand_is_not_an_error(self):
        t = self.TWO_ROWS + ("Sub Total: USD 10,000.00\nDiscount: USD 500.00\n"
                             "Freight: USD 300.00\nGrand Total: USD 9,800.00\n")
        self.assertEqual(check(t)["problems"], [])

    def test_line_items_still_checked_when_discounted(self):
        # 有调整项只是不比合计，单行算错照样要报
        t = ("1. COTTON T-SHIRT 1000 PCS USD 5.00 USD 4,000.00\n"
             "2. DENIM JEANS 500 PCS USD 10.00 USD 5,000.00\n"
             "Less Discount: USD 500.00\nTotal Amount: USD 8,500.00\n")
        self.assertEqual(rules(check(t)), ["R01"])

    def test_payment_terms_without_amount_keep_sum_check(self):
        # "30% IN ADVANCE" 是付款条款，不带金额，不算调整项，合计照常核对
        t = self.TWO_ROWS + "Payment: T/T 30% IN ADVANCE, 70% AGAINST B/L COPY\nTotal Amount: USD 9,000.00\n"
        self.assertEqual(rules(check(t)), ["R01"])

    def test_combined_weight_line_is_skipped(self):
        # 毛重净重合写一行时，原来两个都取成 1,200，还当成"已核实事实"
        for t in ("G.W./N.W.: 1,200 KGS / 1,000 KGS\n", "净重/毛重: 1000 KGS / 1200 KGS\n"):
            r = check(t)
            self.assertEqual(r["facts"], [], t)
            self.assertEqual(r["problems"], [], t)

    def test_separate_weight_lines_still_checked(self):
        t = "净重 Net Weight: 1,300 KGS\n毛重 Gross Weight: 1,200 KGS\n"
        self.assertEqual(rules(check(t)), ["R04"])


if __name__ == "__main__":
    unittest.main()
