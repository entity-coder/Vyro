"""
Vyro — invoices.py
Generates a printable GST invoice as a standalone HTML file.

Honors:
  * shop profile  (name, tagline, address, phone, GSTIN) — bill header
  * print prefs   (accent color, paper size A4 vs thermal 80mm,
                   field toggles, header/footer notes)
  * GST breakup per slab, round-off line, payment type

The file is opened in the user's default browser (Ctrl+P to print).
"""

import html
from datetime import datetime
from pathlib import Path

from db import DB


def _e(x):
    return html.escape("" if x is None else str(x))


def fmt_money(n):
    return f"\u20b9{float(n):,.2f}"


def generate_invoice_html(bill, items, profile, prefs):
    """Return a complete standalone HTML invoice document."""
    accent = prefs.get("accent", "#1f6f43") or "#1f6f43"
    paper = prefs.get("paper", "A4")
    show_gstin = prefs.get("show_gstin", True)
    show_codes = prefs.get("show_item_codes", True)
    show_disc = prefs.get("show_discounts", True)
    header_note = prefs.get("header_note", "")
    footer_note = prefs.get("footer_note", "")

    # GST breakup by slab (taxable + gst amounts)
    slabs = {}
    for it in items:
        slab = float(it.get("gst_percent", 0))
        taxable = max(float(it["qty"]) * float(it["price"])
                    - float(it.get("line_discount", 0)), 0.0)
        gst = taxable * slab / 100.0
        if slab not in slabs:
            slabs[slab] = [0.0, 0.0]
        slabs[slab][0] += taxable
        slabs[slab][1] += gst

    if paper == "thermal":
        width_css, pad = "76mm", "6px"
        fs_base, fs_big = "11px", "15px"
        page_rule = "@page { size: 80mm auto; margin: 2mm; }"
    else:
        width_css, pad = "190mm", "18px"
        fs_base, fs_big = "13px", "22px"
        page_rule = "@page { size: A4; margin: 10mm; }"

    # Item rows
    rows = []
    for i, it in enumerate(items, 1):
        code_cell = ""
        if show_codes:
            code_cell = f"<br><span class='muted'>{_e(it.get('sku') or '')}</span>"
        disc_cell = ""
        if show_disc:
            d = float(it.get("line_discount", 0))
            disc_cell = (f"<td class='num'>{fmt_money(d)}</td>" if d > 0
                         else "<td class='num muted'>\u2014</td>")
        rows.append(
            f"<tr><td>{i}</td>"
            f"<td>{_e(it['name'])}{code_cell}</td>"
            f"<td class='num'>{it['qty']} { _e(it.get('unit', ''))}</td>"
            f"<td class='num'>{fmt_money(it['price'])}</td>"
            f"{disc_cell}"
            f"<td class='num'>{it.get('gst_percent', 0):g}%</td>"
            f"<td class='num amt'>{fmt_money(it['line_total'])}</td></tr>")

    disc_col = "<th class='num'>Disc.</th>" if show_disc else ""
    disc_w = "<col style='width:12%'>" if show_disc else ""

    slab_rows = "".join(
        f"<tr><td class='num'>{slab:g}%</td>"
        f"<td class='num'>{fmt_money(v[0])}</td>"
        f"<td class='num'>{fmt_money(v[1] / 2)}</td>"
        f"<td class='num'>{fmt_money(v[1] / 2)}</td>"
        f"<td class='num'>{fmt_money(v[1])}</td></tr>"
        for slab, v in sorted(slabs.items()))

    gstin_line = (f"<div class='muted'>GSTIN: {_e(profile['shop_gstin'])}</div>"
                  if show_gstin and profile.get("shop_gstin") else "")

    header_note_html = (f"<div class='note'>{_e(header_note)}</div>"
                        if header_note else "")
    footer_note_html = (f"<div class='note foot'>{_e(footer_note)}</div>"
                        if footer_note else "")

    pay = _e(bill.get("payment_type", ""))
    credit_badge = (" <span class='badge'>CREDIT \u2014 due</span>"
                    if bill.get("payment_type") == "Credit" else "")

    now = datetime.now().strftime("%d-%m-%Y %I:%M %p")
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Invoice { _e(bill['bill_no'])}</title>
<style>
  {page_rule}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: {fs_base};
          color: #222; margin: 0; padding: {pad}; }}
  .sheet {{ max-width: {width_css}; margin: 0 auto; }}
  .head {{ text-align: center; border-bottom: 3px solid {accent};
           padding-bottom: 8px; margin-bottom: 10px; }}
  .shop {{ font-size: {fs_big}; font-weight: 700; color: {accent}; }}
  .muted {{ color: #777; font-size: 0.85em; }}
  .note {{ text-align: center; color: #555; margin: 6px 0; }}
  .meta {{ display: flex; justify-content: space-between; margin: 10px 0;
           flex-wrap: wrap; gap: 8px; }}
  .box {{ border: 1px solid #ccc; border-radius: 6px; padding: 8px 10px; flex: 1;
          min-width: 200px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
  th {{ background: {accent}; color: #fff; padding: 6px; text-align: left; }}
  td {{ padding: 6px; border-bottom: 1px solid #e0e0e0; }}
  .num {{ text-align: right; }}
  .amt {{ font-weight: 600; }}
  .totals {{ width: 46%; min-width: 220px; margin-left: auto; margin-top: 10px; }}
  .totals td {{ border: none; padding: 3px 6px; }}
  .grand td {{ font-size: 1.15em; font-weight: 700; color: {accent};
               border-top: 2px solid {accent}; }}
  .badge {{ background: #b3261e; color: #fff; border-radius: 4px; padding: 2px 8px;
            font-size: 0.8em; }}
  .slab {{ margin-top: 12px; }}
  .slab th {{ font-size: 0.85em; }}
  .foot {{ margin-top: 14px; border-top: 1px dashed #aaa; padding-top: 8px; }}
  .sig {{ display: flex; justify-content: space-between; margin-top: 28px; }}
  @media print {{ body {{ padding: 0; }} }}
</style></head>
<body><div class="sheet">
  <div class="head">
    <div class="shop">{_e(profile.get('shop_name') or 'Vyro Shop')}</div>
    {f"<div>{_e(profile['shop_tagline'])}</div>" if profile.get('shop_tagline') else ""}
    {f"<div class='muted'>{_e(profile['shop_address'])}</div>" if profile.get('shop_address') else ""}
    {f"<div class='muted'>Phone: {_e(profile['shop_phone'])}</div>" if profile.get('shop_phone') else ""}
    {gstin_line}
    {header_note_html}
  </div>

  <div class="meta">
    <div class="box">
      <b>Bill No:</b> {_e(bill['bill_no'])}{credit_badge}<br>
      <b>Date:</b> {_e(bill['date'])}<br>
      <b>Payment:</b> {pay}
    </div>
    <div class="box">
      <b>Customer:</b> {_e(bill.get('customer_name') or 'Walk-in')}<br>
      {f"<span class='muted'>{_e(bill.get('customer_phone'))}</span><br>" if bill.get('customer_phone') else ""}
      {f"<span class='muted'>{_e(bill.get('customer_address'))}</span>" if bill.get('customer_address') else ""}
    </div>
  </div>

  <table>
    <col style="width:5%"><col><col style="width:11%"><col style="width:13%">
    {disc_w}<col style="width:9%"><col style="width:15%">
    <tr><th>#</th><th>Item</th><th class="num">Qty</th><th class="num">Rate</th>
        {disc_col}<th class="num">GST</th><th class="num">Amount</th></tr>
    {''.join(rows)}
  </table>

  <table class="slab">
    <tr><th class="num">GST Slab</th><th class="num">Taxable</th>
        <th class="num">CGST</th><th class="num">SGST</th><th class="num">GST</th></tr>
    {slab_rows if slab_rows else "<tr><td colspan='5' class='muted'>No GST</td></tr>"}
  </table>

  <table class="totals">
    <tr><td>Subtotal</td><td class="num">{fmt_money(bill['subtotal'])}</td></tr>
    <tr><td>Total GST</td><td class="num">{fmt_money(bill['gst_total'])}</td></tr>
    {f"<tr><td>Discount</td><td class='num'>\u2212 {fmt_money(bill['discount'])}</td></tr>" if bill['discount'] else ""}
    <tr><td>Round off</td><td class="num">{fmt_money(bill['round_off'])}</td></tr>
    <tr class="grand"><td>Grand Total</td><td class="num">{fmt_money(bill['grand_total'])}</td></tr>
  </table>

  {footer_note_html}
  <div class="sig"><div>Customer signature</div><div>For {_e(profile.get('shop_name') or 'Shop')}</div></div>
  <div class="muted" style="text-align:center;margin-top:10px">Generated by Vyro \u2014 {now}</div>
</div></body></html>"""


def write_invoice_pdf(bill, items, profile, prefs, dest_dir=None):
    """Write the invoice PDF (universal printing, no browser needed).
    Returns the Path of the written file."""
    from printing import generate_invoice_pdf
    if dest_dir:
        safe = str(bill["bill_no"]).replace("/", "-")
        dest = Path(dest_dir) / f"{safe}_invoice.pdf"
    else:
        dest = None
    return generate_invoice_pdf(bill, items, profile, prefs, dest)


def print_bill(bill_id, db_path=None, printer=None, copies=1, preview=False):
    """Build the PDF invoice for a saved bill and print it (Windows) or
    open it for manual printing anywhere else.

    Returns (pdf_path, printed: bool, message). `printed` is True only
    when the OS accepted the print job — callers must not claim a print
    otherwise. Kept import-compatible with the old browser-based flow.
    """
    from printing import print_bill_pdf
    return print_bill_pdf(bill_id, db_path=db_path, printer=printer,
                          copies=copies, preview=preview)
