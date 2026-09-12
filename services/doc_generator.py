"""Trade document generation: Commercial Invoice + Packing List."""
import html
import json
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

_CENT = Decimal("0.01")


# ---- 输入解析：容错，不因一个脏字段废掉整张单证 ----
def as_text(value):
    """任何值转成去空白的字符串（None / 数字 / 空串都安全）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def to_dec(value, default="0"):
    """容错解析成 Decimal：接受数字、'1,000.00'、'USD 12.5'、'100元' 等写法。"""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(default)
    if isinstance(value, bool):
        return Decimal(default)
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).replace(",", "").replace("，", "").strip()
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    if not m:
        return Decimal(default)
    try:
        return Decimal(m.group(0))
    except Exception:
        return Decimal(default)


def money(value):
    """金额四舍五入到分（ROUND_HALF_UP，不是 Python 默认的银行家舍入）。"""
    return to_dec(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def to_int(value, default=0):
    """件数等整数：容忍 '20.0'、'1,000' 这类写法。"""
    try:
        return int(to_dec(value, str(default)).to_integral_value(rounding=ROUND_HALF_UP))
    except Exception:
        return default


def fmt_price(value):
    """单价显示：最多 4 位小数、至少 2 位，保证打印出来的行自身乘得开。"""
    text = format(to_dec(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if "." not in text:
        return text + ".00"
    head, frac = text.split(".")
    return head + "." + frac.ljust(2, "0")


def fmt_qty(value):
    """数量显示：去掉无意义的尾随零（1.9 保持 1.9，3.0 显示 3）。"""
    text = format(to_dec(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def fmt_money(value):
    return format(money(value), ",.2f")


# ---- English amount-to-words converter ----
_ONES = ["", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE",
         "TEN", "ELEVEN", "TWELVE", "THIRTEEN", "FOURTEEN", "FIFTEEN", "SIXTEEN", "SEVENTEEN", "EIGHTEEN", "NINETEEN"]
_TENS = ["", "", "TWENTY", "THIRTY", "FORTY", "FIFTY", "SIXTY", "SEVENTY", "EIGHTY", "NINETY"]
_SCALES = [("TRILLION", 10 ** 12), ("BILLION", 10 ** 9), ("MILLION", 10 ** 6), ("THOUSAND", 10 ** 3)]


def _convert_hundreds(n):
    """Convert 0-999 to English words."""
    if n == 0:
        return ""
    parts = []
    if n >= 100:
        parts.append(f"{_ONES[n // 100]} HUNDRED")
        n %= 100
        if n > 0:
            parts.append("AND")
    if n >= 20:
        if n % 10 > 0:
            parts.append(f"{_TENS[n // 10]}-{_ONES[n % 10]}")
        else:
            parts.append(_TENS[n // 10])
    elif n > 0:
        parts.append(_ONES[n])
    return " ".join(parts)


def _int_to_words(n):
    """非负整数转英文（覆盖到万亿级）。"""
    if n == 0:
        return "ZERO"
    parts = []
    for name, scale in _SCALES:
        if n >= scale:
            count, n = divmod(n, scale)
            parts.append(f"{_convert_hundreds(count)} {name}")
    if n > 0:
        parts.append(_convert_hundreds(n))
    return " ".join(p for p in parts if p.strip())


def amount_to_english(amount):
    """Convert amount to English words, e.g. 1234.56 -> ONE THOUSAND TWO HUNDRED AND THIRTY-FOUR DOLLARS AND FIFTY-SIX CENTS ONLY."""
    value = money(amount)
    negative = value < 0
    total_cents = int((abs(value) * 100).to_integral_value(rounding=ROUND_HALF_UP))
    dollars, cents = divmod(total_cents, 100)

    parts = []
    if dollars:
        parts.append("%s %s" % (_int_to_words(dollars), "DOLLAR" if dollars == 1 else "DOLLARS"))
    if cents:
        parts.append("%s %s" % (_int_to_words(cents), "CENT" if cents == 1 else "CENTS"))
    if not parts:
        parts.append("ZERO DOLLARS")

    result = " AND ".join(parts) + " ONLY"
    return "MINUS " + result if negative else result


def esc(value):
    """转义后拼进 HTML —— 品名里一个 < 就能打乱预览区，更要挡住脚本注入。"""
    return html.escape(as_text(value))


def _build_invoice_html(invoice_no, date, trade_terms, payment, shipper_name, shipper_addr,
                        consignee_name, consignee_addr, port_loading, port_discharge,
                        goods_rows, total_amount, freight, grand_total, amount_words, invoice_remarks):
    rows_html = ""
    for i, row in enumerate(goods_rows, 1):
        rows_html += f"""<tr>
            <td>{i}</td><td>{esc(row.get('name'))}</td>
            <td class="num">{esc(fmt_qty(row.get('qty')))}</td><td>{esc(row.get('unit') or 'PCS')}</td>
            <td class="num">USD {esc(fmt_price(row.get('price')))}</td>
            <td class="num">USD {esc(fmt_money(row.get('amount')))}</td>
        </tr>"""

    remarks = f'<tr><td colspan="6" class="remarks"><strong>Remarks:</strong> {esc(invoice_remarks)}</td></tr>' if as_text(invoice_remarks) else ""

    return f"""<div class="trade-doc">
    <h2>COMMERCIAL INVOICE 商业发票</h2>
    <div class="doc-header">
        <div class="doc-field"><label>Invoice No</label><span>{esc(invoice_no)}</span></div>
        <div class="doc-field"><label>Date</label><span>{esc(date)}</span></div>
        <div class="doc-field"><label>Trade Terms</label><span>{esc(trade_terms)}</span></div>
        <div class="doc-field"><label>Payment</label><span>{esc(payment)}</span></div>
    </div>
    <div class="doc-party">
        <div><label>Shipper / Exporter</label><span>{esc(shipper_name)}<br>{esc(shipper_addr)}</span></div>
        <div><label>Consignee / Importer</label><span>{esc(consignee_name)}<br>{esc(consignee_addr)}</span></div>
    </div>
    <div class="doc-header">
        <div class="doc-field"><label>Port of Loading</label><span>{esc(port_loading)}</span></div>
        <div class="doc-field"><label>Port of Discharge</label><span>{esc(port_discharge)}</span></div>
    </div>
    <table>
        <thead><tr><th>#</th><th>Description</th><th>Qty</th><th>Unit</th><th>Unit Price</th><th>Amount</th></tr></thead>
        <tbody>{rows_html}</tbody>
        <tfoot>
            <tr><td colspan="5">Sub Total</td><td class="num">USD {esc(fmt_money(total_amount))}</td></tr>
            <tr><td colspan="5">Freight</td><td class="num">USD {esc(fmt_money(freight))}</td></tr>
            <tr class="total"><td colspan="5">Grand Total</td><td class="num">USD {esc(fmt_money(grand_total))}</td></tr>
            <tr class="words"><td colspan="6">SAY {esc(amount_words)}</td></tr>
            {remarks}
        </tfoot>
    </table>
</div>"""


def _build_pl_html(invoice_no, date, shipper_name, consignee_name, port_loading, port_discharge,
                   shipping_mark, goods_rows, pl_remarks):
    rows_html = ""
    for i, row in enumerate(goods_rows, 1):
        rows_html += f"""<tr>
            <td>{i}</td><td>{esc(row.get('name'))}</td>
            <td class="num">{esc(fmt_qty(row.get('qty')))}</td><td>{esc(row.get('unit') or 'PCS')}</td>
            <td class="num">{esc(row.get('gw'))}</td>
            <td class="num">{esc(row.get('nw'))}</td>
            <td class="num">{esc(row.get('cbm'))}</td>
        </tr>"""

    total_pkgs = sum(to_int(row.get("pkgs")) for row in goods_rows)
    remarks = f'<tr><td colspan="7" class="remarks"><strong>Remarks:</strong> {esc(pl_remarks)}</td></tr>' if as_text(pl_remarks) else ""

    return f"""<div class="trade-doc">
    <h2>PACKING LIST 装箱单</h2>
    <div class="doc-header">
        <div class="doc-field"><label>Invoice No</label><span>{esc(invoice_no)}</span></div>
        <div class="doc-field"><label>Date</label><span>{esc(date)}</span></div>
    </div>
    <div class="doc-party">
        <div><label>Shipper</label><span>{esc(shipper_name)}</span></div>
        <div><label>Consignee</label><span>{esc(consignee_name)}</span></div>
    </div>
    <div class="doc-header">
        <div class="doc-field"><label>Port of Loading</label><span>{esc(port_loading)}</span></div>
        <div class="doc-field"><label>Port of Discharge</label><span>{esc(port_discharge)}</span></div>
        <div class="doc-field"><label>Shipping Marks</label><span>{esc(shipping_mark)}</span></div>
    </div>
    <table>
        <thead><tr><th>#</th><th>Description</th><th>Qty</th><th>Unit</th><th>G.W.(KGS)</th><th>N.W.(KGS)</th><th>Meas.(CBM)</th></tr></thead>
        <tbody>{rows_html}</tbody>
        <tfoot>
            <tr class="total"><td colspan="7">Total Packages: {total_pkgs} CTNS</td></tr>
            {remarks}
        </tfoot>
    </table>
</div>"""


# ---- Document Generator ----
def generate_docs(form_data):
    """Generate Commercial Invoice and Packing List text from form data."""
    now = datetime.now().strftime("%Y-%m-%d")
    invoice_no = as_text(form_data.get("invoice_no"))
    # 前端日期框默认是空的，键存在但值为空串时也要回退到今天
    date = as_text(form_data.get("date")) or now
    trade_terms = as_text(form_data.get("trade_terms"))
    payment = as_text(form_data.get("payment"))

    shipper_name = as_text(form_data.get("shipper_name"))
    shipper_addr = as_text(form_data.get("shipper_addr"))
    consignee_name = as_text(form_data.get("consignee_name"))
    consignee_addr = as_text(form_data.get("consignee_addr"))

    port_loading = as_text(form_data.get("port_loading"))
    port_discharge = as_text(form_data.get("port_discharge"))

    shipping_mark = as_text(form_data.get("shipping_mark")) or invoice_no
    invoice_remarks = as_text(form_data.get("invoice_remarks"))
    pl_remarks = as_text(form_data.get("pl_remarks"))

    freight = money(form_data.get("freight"))

    # Parse goods rows
    try:
        goods_rows = json.loads(form_data.get("goods") or "[]")
    except (TypeError, ValueError):
        goods_rows = []
    if not isinstance(goods_rows, list):
        goods_rows = []
    goods_rows = [r for r in goods_rows if isinstance(r, dict)]

    # Calculate totals —— 全程 Decimal，行金额先舍入再累加，保证列和等于合计
    total_qty = Decimal("0")
    total_amount = Decimal("0")
    for row in goods_rows:
        qty = to_dec(row.get("qty"))
        price = to_dec(row.get("price"))
        amount = money(qty * price)
        row["amount"] = float(amount)
        total_qty += qty
        total_amount += amount

    total_amount = money(total_amount)
    grand_total = money(total_amount + freight)
    amount_words = amount_to_english(grand_total)

    # ---- Generate Invoice ----
    inv_lines = []
    inv_lines.append("=" * 60)
    inv_lines.append("                    COMMERCIAL INVOICE")
    inv_lines.append("=" * 60)
    inv_lines.append(f"  Invoice No: {invoice_no}")
    inv_lines.append(f"  Date: {date}")
    inv_lines.append("")
    inv_lines.append(f"  Trade Terms: {trade_terms}")
    inv_lines.append(f"  Payment: {payment}")
    inv_lines.append("")
    inv_lines.append(f"  Shipper/Exporter:")
    inv_lines.append(f"    {shipper_name}")
    inv_lines.append(f"    {shipper_addr}")
    inv_lines.append("")
    inv_lines.append(f"  Consignee/Importer:")
    inv_lines.append(f"    {consignee_name}")
    inv_lines.append(f"    {consignee_addr}")
    inv_lines.append("")
    inv_lines.append(f"  Port of Loading: {port_loading}")
    inv_lines.append(f"  Port of Discharge: {port_discharge}")
    inv_lines.append("")
    inv_lines.append("-" * 60)
    header = f"  {'Item':<4} {'Description':<24} {'Qty':>8} {'Unit':>6} {'U/Price':>10} {'Amount':>12}"
    inv_lines.append(header)
    inv_lines.append("-" * 60)

    for i, row in enumerate(goods_rows, 1):
        inv_lines.append(
            f"  {i:<4} {as_text(row.get('name')):<24} "
            f"{fmt_qty(row.get('qty')):>8} {as_text(row.get('unit') or 'PCS'):>6} "
            f"USD {fmt_price(row.get('price')):>8} "
            f"USD {row['amount']:>10.2f}"
        )
    inv_lines.append("-" * 60)
    inv_lines.append(f"  {'Sub Total':>48} USD {total_amount:>10.2f}")
    inv_lines.append(f"  {'Freight':>48} USD {freight:>10.2f}")
    inv_lines.append(f"  {'Grand Total':>48} USD {grand_total:>10.2f}")
    inv_lines.append("=" * 60)
    inv_lines.append(f"  Amount in Words: SAY {amount_words}")
    inv_lines.append("=" * 60)
    if invoice_remarks:
        inv_lines.append(f"  Remarks: {invoice_remarks}")

    # ---- Generate Packing List ----
    pl_lines = []
    pl_lines.append("=" * 60)
    pl_lines.append("                      PACKING LIST")
    pl_lines.append("=" * 60)
    pl_lines.append(f"  Invoice No: {invoice_no}")
    pl_lines.append(f"  Date: {date}")
    pl_lines.append("")
    pl_lines.append(f"  Shipper: {shipper_name}")
    pl_lines.append(f"  Consignee: {consignee_name}")
    pl_lines.append("")
    pl_lines.append(f"  Port of Loading: {port_loading}")
    pl_lines.append(f"  Port of Discharge: {port_discharge}")
    pl_lines.append(f"  Shipping Marks: {shipping_mark}")
    pl_lines.append("")
    pl_lines.append("-" * 60)
    header2 = f"  {'Item':<4} {'Description':<24} {'Qty':>8} {'Unit':>6} {'G.W.(KGS)':>10} {'N.W.(KGS)':>10} {'Meas.(CBM)':>10}"
    pl_lines.append(header2)
    pl_lines.append("-" * 60)

    total_pkgs = 0
    for i, row in enumerate(goods_rows, 1):
        total_pkgs += to_int(row.get("pkgs"))
        pl_lines.append(
            f"  {i:<4} {as_text(row.get('name')):<24} "
            f"{fmt_qty(row.get('qty')):>8} {as_text(row.get('unit') or 'PCS'):>6} "
            f"{as_text(row.get('gw')):>10} "
            f"{as_text(row.get('nw')):>10} "
            f"{as_text(row.get('cbm')):>10}"
        )
    pl_lines.append("-" * 60)
    # Dynamic unit display — per-unit totals（小数数量不再被 int() 抹掉）
    unit_totals = {}
    for r in goods_rows:
        u = as_text(r.get("unit")) or "PCS"
        unit_totals[u] = unit_totals.get(u, Decimal("0")) + to_dec(r.get("qty"))
    unit_str = " / ".join(f"{fmt_qty(v)} {k}" for k, v in unit_totals.items())

    pl_lines.append(f"  Total Packages: {total_pkgs} CTNS")
    pl_lines.append(f"  Total Quantity: {unit_str}")
    pl_lines.append("=" * 60)
    if pl_remarks:
        pl_lines.append(f"  Remarks: {pl_remarks}")

    invoice_text = "\n".join(inv_lines)
    pl_text = "\n".join(pl_lines)
    combined = f"=== 商业发票 (COMMERCIAL INVOICE) ===\n\n{invoice_text}\n\n\n=== 装箱单 (PACKING LIST) ===\n\n{pl_text}"

    invoice_html = _build_invoice_html(invoice_no, date, trade_terms, payment, shipper_name, shipper_addr,
                                       consignee_name, consignee_addr, port_loading, port_discharge,
                                       goods_rows, total_amount, freight, grand_total, amount_words, invoice_remarks)
    pl_html = _build_pl_html(invoice_no, date, shipper_name, consignee_name, port_loading, port_discharge,
                             shipping_mark, goods_rows, pl_remarks)

    return {
        "invoice_text": invoice_text,
        "pl_text": pl_text,
        "invoice_html": invoice_html,
        "pl_html": pl_html,
        "combined_text": combined,
        # Decimal 不能直接 JSON 序列化，出口一律转 float
        "total_amount": float(total_amount),
        "freight": float(freight),
        "grand_total": float(grand_total),
        "amount_words": amount_words,
        "total_qty": float(total_qty),
        "total_pkgs": total_pkgs,
        "goods_rows": goods_rows,
    }
