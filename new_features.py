"""
Vyro — new features (round 13).

Pure functions first (no GUI imports, so they can be tested headless);
CustomTkinter dialogs at the bottom, imported lazily by ui.py.

Features:
  1. Sales summary export to CSV (summary + day-wise + GST + item-wise
     sales + profit by product, in one file with labelled sections).
  2. Item-wise profit report (sale price - current purchase price per
     line, same approximation as DB.estimated_profit: ignores overheads
     and uses the product's current purchase price, not historical cost).
  3. Customer outstanding reminders — ready-to-send WhatsApp text per customer.
  4. Barcode label PDF (Code128, from the product SKU; falls back to the
     product id when no SKU is saved).
  5. Sale Register: bills by customer name / bill no AND date range.
  6. Outstanding CSV export (2026-11-04): full outstanding list to CSV,
     largest balance first, with a total row. Customers with a negative
     balance (an advance) never appear — outstanding_list() only returns
     balance > 0.
  7. Month-wise sales (2026-11-05): day-wise sales rolled up by
     month (YYYY-MM) with bills, sales, discount and GST per month,
     plus a totals row; shown as a Reports tab and as a section of
     the report CSV export.
  8. Party-wise sales (2026-11-06): customers ranked by total purchases
     in the period, largest first, with bills, total and last purchase
     date, plus a totals row; shown as a Reports tab and as a section
     of the report CSV export.
  9. Round 17 renames (2026-11-07): the Reports data functions now use
     Marg-ERP-style names — sale_register, month_wise_sales,
     item_wise_profit, party_wise_sales — with matching tab labels
     ("Month-wise sales", "Item-wise profit", "Party-wise sales").
     No behaviour changed; only names and labels.
 10. Round 18 renames (2026-11-08): the customer-outstanding area now uses the Marg-ERP
     word "Outstanding" — outstanding_reminder_message,
     outstanding_reminders, export_outstanding_csv (CSV headers
     "Outstanding (Rs.)" / "Total outstanding") and
     open_outstanding_reminders_dialog — with matching Customers-tab
     buttons, column and total labels. The db layer was untouched then;
     renaming it is Round 19 (see item 11).
     No behaviour changed; only names and labels.
 11. Round 19 renames (2026-11-09): the db layer now uses the same
     Marg-ERP words — outstanding_list and total_outstanding
     (customers), suppliers_with_payables (suppliers) — with
     matching callers, labels and README wording updated.
     No behaviour changed; only names and labels.
 12. Round 20 renames (2026-11-10): the db Reports query helpers now
     use Marg-ERP-style names — day_book, sales_in_period,
     day_wise_sales, gst_register, item_wise_sales, estimated_profit
     — with matching callers, tab labels ("GST register",
     "Item-wise sales") and CSV section headers.
     No behaviour changed; only names and labels.
"""

import csv
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# 5. Sale Register: customer / bill no + date range
# ---------------------------------------------------------------------------

def sale_register(db, start, end, search=""):
    """Bills between start and end (YYYY-MM-DD, inclusive), optionally
    filtered by bill number or customer name. Newest first."""
    sql = ("SELECT b.*, c.name AS customer_name FROM bills b "
           "LEFT JOIN customers c ON c.id=b.customer_id "
           "WHERE b.date BETWEEN ? AND ?")
    params = [start, end]
    if search:
        sql += " AND (b.bill_no LIKE ? OR c.name LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    sql += " ORDER BY b.id DESC"
    return db._rows(sql, tuple(params))


# ---------------------------------------------------------------------------
# 2. Item-wise profit
# ---------------------------------------------------------------------------

def item_wise_profit(db, start, end):
    """Per-product profit for the period, highest profit first.
    Returns dict rows: name, qty, sales, cost, profit."""
    rows = db._rows(
        "SELECT bi.name, bi.unit, SUM(bi.qty) qty, "
        "SUM(bi.qty*bi.price - bi.line_discount) sales, "
        "SUM(bi.qty * COALESCE(p.purchase_price, 0)) cost "
        "FROM bill_items bi JOIN bills b ON b.id=bi.bill_id "
        "LEFT JOIN products p ON p.id=bi.product_id "
        "WHERE b.date BETWEEN ? AND ? "
        "GROUP BY bi.product_id, bi.name ORDER BY sales DESC",
        (start, end))
    out = []
    for r in rows:
        sales = float(r["sales"] or 0)
        cost = float(r["cost"] or 0)
        out.append({"name": r["name"], "unit": r["unit"],
                    "qty": float(r["qty"] or 0), "sales": sales,
                    "cost": cost, "profit": sales - cost})
    return out


# ---------------------------------------------------------------------------
# 7. Month-wise sales
# ---------------------------------------------------------------------------

def month_wise_sales(db, start, end):
    """Day-wise sales rolled up by month. Returns dict rows, oldest
    month first: month ('YYYY-MM', from the YYYY-MM-DD bill date),
    bills, sales (grand totals), discount (bill-level), gst.
    Months with no bills do not appear — same as day_wise_sales.
    Same convention as sales_in_period: every bill in the range counts,
    regardless of status."""
    rows = db._rows(
        "SELECT substr(date, 1, 7) month, COUNT(*) n, "
        "SUM(grand_total) t, SUM(discount) d, SUM(gst_total) g "
        "FROM bills WHERE date BETWEEN ? AND ? "
        "GROUP BY month ORDER BY month",
        (start, end))
    return [{"month": r["month"], "bills": int(r["n"]),
             "sales": float(r["t"] or 0),
             "discount": float(r["d"] or 0),
             "gst": float(r["g"] or 0)} for r in rows]


# ---------------------------------------------------------------------------
# 8. Party-wise sales
# ---------------------------------------------------------------------------

def party_wise_sales(db, start, end):
    """Customers ranked by total purchases in the period, largest
    first. Returns dict rows: rank (1-based), name, phone, bills,
    total (grand totals), last (latest bill date).
    Same convention as month_wise_sales: every bill in the range
    counts, regardless of status. Bills with no customer (walk-in)
    have no name to rank and are excluded."""
    rows = db._rows(
        "SELECT c.name, c.phone, COUNT(*) n, SUM(b.grand_total) t, "
        "MAX(b.date) last_date FROM bills b "
        "JOIN customers c ON c.id=b.customer_id "
        "WHERE b.date BETWEEN ? AND ? "
        "GROUP BY c.id, c.name, c.phone ORDER BY t DESC",
        (start, end))
    return [{"rank": i + 1, "name": r["name"],
             "phone": r.get("phone") or "", "bills": int(r["n"]),
             "total": float(r["t"] or 0),
             "last": r["last_date"]} for i, r in enumerate(rows)]


# ---------------------------------------------------------------------------
# 1. Sales summary export
# ---------------------------------------------------------------------------

def export_reports_csv(db, start, end, path):
    """Write the full period report to one CSV file. Sections are
    labelled in the first column so the file opens cleanly in Excel."""
    path = Path(path)
    s = db.sales_in_period(start, end)
    profit = db.estimated_profit(start, end)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Vyro report", f"{start} to {end}"])
        w.writerow([])
        w.writerow(["Summary"])
        w.writerow(["Bills", s["n"]])
        w.writerow(["Total sales", f"{float(s['t']):.2f}"])
        w.writerow(["Discount given", f"{float(s['d']):.2f}"])
        w.writerow(["GST collected", f"{float(s['g']):.2f}"])
        w.writerow(["Profit estimate*", f"{float(profit):.2f}"])
        w.writerow(["* Profit = sale price - purchase price per line; "
                    "approx, ignores overheads."])
        w.writerow([])
        w.writerow(["Day-wise sales"])
        w.writerow(["Date", "Bills", "Sales", "GST"])
        for d in db.day_wise_sales(start, end):
            w.writerow([d["date"], d["n"], f"{float(d['t']):.2f}",
                        f"{float(d['g']):.2f}"])
        w.writerow([])
        w.writerow(["Month-wise sales"])
        w.writerow(["Month", "Bills", "Sales", "Discount", "GST"])
        for m in month_wise_sales(db, start, end):
            w.writerow([m["month"], m["bills"], f"{m['sales']:.2f}",
                        f"{m['discount']:.2f}", f"{m['gst']:.2f}"])
        w.writerow([])
        w.writerow(["GST register"])
        w.writerow(["GST slab", "Taxable value", "GST"])
        for g in db.gst_register(start, end):
            w.writerow([f"{float(g['gst_percent']):g}%",
                        f"{float(g['taxable']):.2f}",
                        f"{float(g['gst']):.2f}"])
        w.writerow([])
        w.writerow(["Item-wise sales"])
        w.writerow(["Product", "Qty sold", "Amount"])
        for t in db.item_wise_sales(start, end, limit=50):
            w.writerow([t["name"], f"{float(t['qty']):g} {t['unit']}",
                        f"{float(t['total']):.2f}"])
        w.writerow([])
        w.writerow(["Item-wise profit"])
        w.writerow(["Product", "Qty", "Sales", "Cost", "Profit"])
        for p in item_wise_profit(db, start, end):
            w.writerow([p["name"], f"{p['qty']:g} {p['unit']}",
                        f"{p['sales']:.2f}", f"{p['cost']:.2f}",
                        f"{p['profit']:.2f}"])
        w.writerow([])
        w.writerow(["Party-wise sales"])
        w.writerow(["Rank", "Customer", "Phone", "Bills",
                    "Total purchases", "Last purchase"])
        for c in party_wise_sales(db, start, end):
            w.writerow([c["rank"], c["name"], c["phone"], c["bills"],
                        f"{c['total']:.2f}", c["last"]])
    return path


# ---------------------------------------------------------------------------
# 3. Outstanding reminders
# ---------------------------------------------------------------------------

def outstanding_reminder_message(shop_name, customer_name, balance):
    """Polite, copy-ready reminder text. No phone number is used here;
    the caller decides how to send it."""
    shop = shop_name or "Vyro"
    return (f"Hello {customer_name}, this is {shop}. "
            f"Your outstanding balance is Rs. {float(balance):.2f}. "
            f"Kindly pay at your convenience. Thank you!")


def outstanding_reminders(db, shop_name=""):
    """One reminder per customer with an outstanding balance, largest balance first."""
    out = []
    for c in db.outstanding_list():
        out.append({"customer_id": c["id"], "name": c["name"],
                    "phone": c.get("phone") or "",
                    "balance": float(c["balance"]),
                    "message": outstanding_reminder_message(
                        shop_name, c["name"], c["balance"])})
    return out


def whatsapp_link(phone, message):
    """wa.me link for a message, or '' when no usable phone is saved."""
    from urllib.parse import quote
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        digits = "91" + digits
    if len(digits) < 12:
        return ""
    return f"https://wa.me/{digits}?text={quote(message)}"


# ---------------------------------------------------------------------------
# 6. Outstanding CSV export
# ---------------------------------------------------------------------------

def export_outstanding_csv(db, path):
    """Write every customer with an outstanding balance to one CSV file,
    largest balance first, with a total row at the end. A customer
    with a negative balance (an advance) is not outstanding and never
    appears, because db.outstanding_list() only returns balance > 0.
    An empty outstanding list still writes a header and a zero total."""
    path = Path(path)
    rows = db.outstanding_list()
    total = sum(float(r["balance"]) for r in rows)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Customer", "Phone", "Outstanding (Rs.)"])
        for r in rows:
            w.writerow([r["name"], r.get("phone") or "",
                        f"{float(r['balance']):.2f}"])
        w.writerow([])
        w.writerow(["Total outstanding", "", f"{total:.2f}"])
    return path


# ---------------------------------------------------------------------------
# 4. Barcode label PDF
# ---------------------------------------------------------------------------

def generate_barcode_labels_pdf(products, dest_path, shop_name=""):
    """A4 sheet of barcode labels, 3 across. Each label: product name,
    Code128 barcode of the SKU (or 'BB-<id>' when no SKU is saved),
    and the wholesale price. Returns the Path written."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.graphics.barcode import code128

    dest_path = Path(dest_path)
    c = canvas.Canvas(str(dest_path), pagesize=A4)
    page_w, page_h = A4
    cols, label_w, label_h = 3, 62 * mm, 32 * mm
    margin_x, margin_y, gap = 8 * mm, 10 * mm, 4 * mm
    x0, y = margin_x, page_h - margin_y - label_h
    col = 0
    for p in products:
        code = (p.get("sku") or "").strip() or f"BB-{p['id']}"
        price = p.get("wholesale_price") or p.get("retail_price") or 0
        x = x0 + col * (label_w + gap)
        c.rect(x, y, label_w, label_h, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x + 3 * mm, y + label_h - 6 * mm,
                     str(p["name"])[:28])
        try:
            bc = code128.Code128(code, barHeight=11 * mm, barWidth=0.4 * mm)
            bc.drawOn(c, x + 3 * mm, y + 8 * mm)
        except Exception:
            c.setFont("Helvetica", 8)
            c.drawString(x + 3 * mm, y + 10 * mm, code)
        c.setFont("Helvetica", 9)
        c.drawString(x + 3 * mm, y + 3.5 * mm,
                     f"{code}  |  Rs. {float(price):.2f}")
        col += 1
        if col >= cols:
            col = 0
            y -= label_h + gap
            if y < margin_y:
                c.showPage()
                y = page_h - margin_y - label_h
    if shop_name:
        c.setFont("Helvetica", 8)
        c.drawRightString(page_w - margin_x, 8 * mm, shop_name)
    c.save()
    return dest_path


# ---------------------------------------------------------------------------
# GUI dialogs (lazy imports so the pure functions stay headless-testable)
# ---------------------------------------------------------------------------

def open_outstanding_reminders_dialog(parent, db, shop_name=""):
    """Window listing every customer with an outstanding balance + their reminder text,
    with a Copy button and a WhatsApp button per row."""
    import webbrowser
    from tkinter import messagebox
    import customtkinter as ctk

    win = ctk.CTkToplevel(parent)
    win.title("Outstanding reminders")
    win.geometry("760x480")
    win.transient(parent)
    rows = outstanding_reminders(db, shop_name)
    if not rows:
        ctk.CTkLabel(win, text="No customers have outstanding balances.",
                     font=ctk.CTkFont(size=14)).pack(pady=30)
        return
    total = sum(r["balance"] for r in rows)
    ctk.CTkLabel(win, text=f"{len(rows)} customers  |  "
                            f"Total outstanding: Rs. {total:.2f}",
                 font=ctk.CTkFont(size=14, weight="bold")).pack(
                     anchor="w", padx=12, pady=10)
    scroll = ctk.CTkScrollableFrame(win)
    scroll.pack(fill="both", expand=True, padx=10, pady=6)
    for r in rows:
        fr = ctk.CTkFrame(scroll)
        fr.pack(fill="x", pady=4, padx=4)
        ctk.CTkLabel(fr, text=f"{r['name']}  —  Rs. {r['balance']:.2f}",
                     font=ctk.CTkFont(weight="bold")).pack(
                         anchor="w", padx=8, pady=(6, 0))
        msg = ctk.CTkLabel(fr, text=r["message"], wraplength=700)
        msg.pack(anchor="w", padx=8)

        def copy_msg(m=r["message"]):
            win.clipboard_clear()
            win.clipboard_append(m)
            messagebox.showinfo("Copied", "Reminder text copied.")

        def wa(m=r["message"], ph=r["phone"]):
            link = whatsapp_link(ph, m)
            if link:
                webbrowser.open(link)
            else:
                messagebox.showinfo(
                    "WhatsApp",
                    "No phone number saved for this customer.")

        ctk.CTkButton(fr, text="Copy", width=70,
                      command=copy_msg).pack(side="left", padx=8, pady=6)
        ctk.CTkButton(fr, text="WhatsApp", width=90, fg_color="#1f6f43",
                      hover_color="#175733",
                      command=wa).pack(side="left", padx=4, pady=6)
