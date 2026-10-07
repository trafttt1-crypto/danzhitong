# -*- coding: utf-8 -*-
"""一致性图的样例单证：一套故意埋了几处差异的四联单据，供「载入样例」和单元测试共用。

埋了什么（测试里逐条断言，改这里必须同步改 tests/test_consistency.py）：
  1. 发票金额 USD 16,200.00 超过信用证金额 USD 15,600.00      -> 红（R11）
  2. 发票发货人 "SUNRISEE" 多一个 E，与信用证受益人对不上      -> 黄（疑似拼写差异，R32）
  3. 装箱单毛重 2,700 KGS，提单毛重 2,760 KGS                  -> 红
  4. 提单目的港写成 DUBAI，信用证规定 JEBEL ALI                -> 红（R21）
其余字段（发票号、日期、品名、件数、唛头、体积等）都是对得上的，用来画绿线。
"""

LC = """信用证（MT700 报文摘录）
:20: LC2026-0088
:31D: 261031 IN CHINA
:32B: USD15600,00
:50: GLOBAL TRADING LLC, DUBAI, UAE
:59: NINGBO SUNRISE IMP & EXP CO., LTD.
:44E: NINGBO, CHINA
:44F: JEBEL ALI, UAE
:45A: CERAMIC DINNER SET, CIF JEBEL ALI
"""

INVOICE = """商业发票
COMMERCIAL INVOICE

发票号 Invoice No.: INV-2026-0620
日期 Date: 2026-06-20

发货人 Shipper: NINGBO SUNRISEE IMP & EXP CO., LTD.
收货人 Consignee: GLOBAL TRADING LLC, DUBAI, UAE

装运港 Port of Loading: NINGBO, CHINA
目的港 Port of Discharge: JEBEL ALI, UAE
贸易术语 Trade Terms: CIF JEBEL ALI

货物描述 Description: CERAMIC DINNER SET
数量 Quantity: 3000 PCS
单价 Unit Price: USD 5.40
总价 Total Amount: USD 16,200.00
"""

PACKING = """装箱单
PACKING LIST

发票号 Invoice No.: INV-2026-0620
日期 Date: 2026-06-20

发货人 Shipper: NINGBO SUNRISE IMP & EXP CO., LTD.
收货人 Consignee: GLOBAL TRADING LLC, DUBAI, UAE

装运港 Port of Loading: NINGBO, CHINA
目的港 Port of Discharge: JEBEL ALI, UAE

货物描述 Description: CERAMIC DINNER SET
数量 Quantity: 3000 PCS
件数 Total Packages: 150 CTNS
毛重 Gross Weight: 2,700 KGS
净重 Net Weight: 2,450 KGS
体积 Measurement: 18.6 CBM
唛头 Shipping Mark: GTL/DUBAI/1-150
"""

BL = """BILL OF LADING
B/L No.: COSU6201234567

Shipper: NINGBO SUNRISE IMP & EXP CO., LTD.
Consignee: GLOBAL TRADING LLC, DUBAI, UAE

Port of Loading: NINGBO, CHINA
Port of Discharge: DUBAI, UAE

Description of Goods: CERAMIC DINNER SET
Total Packages: 150 CTNS
Gross Weight: 2,760 KGS
Measurement: 18.6 CBM
Shipping Marks: GTL/DUBAI/1-150
"""

SAMPLE_DOCS = [LC, INVOICE, PACKING, BL]
