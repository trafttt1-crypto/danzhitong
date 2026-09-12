// 示例单证库 — 一键载入，供快速试用与演示（含典型错误 / 规范样板）
window.TEACHING_CASES = [
    {
        title: "商业发票（含典型错误）",
        text: `商业发票
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
唛头 Shipping Mark: N/M`
    },
    {
        title: "装箱单（含典型错误）",
        text: `装箱单
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
唛头 Shipping Mark: GTL/DUBAI/1-100`
    },
    {
        title: "商业发票（规范样板）",
        text: `商业发票
COMMERCIAL INVOICE

发票号 Invoice No.: INV-2024-0666
日期 Date: 2024-06-06

发货人 Shipper: NINGBO SUNRISE IMP & EXP CO., LTD., NO.88 ZHONGSHAN ROAD, NINGBO, CHINA
收货人 Consignee: GLOBAL TRADING LLC, OFFICE 1204, AL MAS TOWER, SHEIKH ZAYED ROAD, DUBAI, UAE

装运港 Port of Loading: NINGBO, CHINA
目的港 Port of Discharge: JEBEL ALI, UAE
贸易术语 Trade Terms: CIF JEBEL ALI

货物描述 Description: CERAMIC DINNER SET (PORCELAIN), HS CODE 6911.10
数量 Quantity: 2000 SETS
单价 Unit Price: USD 4.50
总价 Total Amount: USD 9000.00
金额大写 Amount in Words: SAY US DOLLARS NINE THOUSAND ONLY
件数 Total Packages: 100 CTNS (20 SETS PER CARTON)

付款方式 Payment: T/T
保险 Insurance: COVERED BY SELLER, ALL RISKS, 110 PCT OF INVOICE VALUE
唛头 Shipping Mark: GTL/DUBAI/1-100
备注 Remarks: PACKED IN EXPORT STANDARD CARTONS WITH FRAGILE MARKING AND SHOCK-ABSORBING LINING`
    }
];
