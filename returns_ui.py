"""
Vyro — returns_ui.py
Sales returns (credit notes) + WhatsApp bill sharing.
"""

import re
import urllib.parse
import webbrowser
from tkinter import messagebox

import customtkinter as ctk
from tkinter import ttk

RUPEE = "\u20b9"


def money(n):
    try:
        return f"{RUPEE}{float(n):,.2f}"
    except (TypeError, ValueError):
        return f"{RUPEE}0.00"


def _tree(parent, columns, widths=None, height=10):
    frame = ctk.CTkFrame(parent)
    tv = ttk.Treeview(frame, columns=columns, show="headings", height=height)
    for i, c in enumerate(columns):
        tv.heading(c, text=c)
        tv.column(c, width=(widths[i] if widths else 110), anchor="w")
    vsb = ttk.Scrollbar(frame, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=vsb.set)
    tv.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")
    return frame, tv


class ReturnDialog(ctk.CTkToplevel):
    """Record a sales return against a finalized bill.

    Each row shows billed qty, already-returned qty and an entry for the
    return qty (capped). On confirm a credit note is created, stock goes
    back up, and for credit bills the khata balance is reduced.
    """

    def __init__(self, master, db, bill_id, on_done=None):
        super().__init__(master)
        self.db = db
        self.bill_id = bill_id
        self.on_done = on_done
        self.bill = db.get_bill(bill_id)
        self.title(f"Return items \u2014 {self.bill['bill_no']}")
        self.geometry("640x560")
        self.transient(master)
        self.grab_set()

        ctk.CTkLabel(
            self,
            text=f"{self.bill['bill_no']}  \u00b7  {self.bill['date']}  \u00b7  "
                 f"{self.bill.get('customer_name') or 'Walk-in'}",
            font=ctk.CTkFont(size=14, weight="bold")).pack(
                anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            self,
            text="Enter the quantity being returned for each item. "
                 "Already-returned quantities are tracked so nothing can be "
                 "returned twice.",
            text_color="gray", wraplength=600,
            justify="left").pack(anchor="w", padx=12, pady=(0, 6))

        fr, self.tv = _tree(self, ("Item", "Billed", "Returned", "Amount"),
                             widths=(240, 90, 90, 120), height=8)
        fr.pack(fill="x", padx=12, pady=4)

        self.entries = {}  # bill_item_id -> (entry, max_qty, name)
        form = ctk.CTkScrollableFrame(self, height=170)
        form.pack(fill="both", expand=True, padx=12, pady=4)
        for it in db.bill_items(bill_id):
            ret = db.returned_qty(it["id"])
            max_q = float(it["qty"]) - ret
            row = ctk.CTkFrame(form, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(
                row,
                text=f"{it['name']}  ({it['qty']:g} {it['unit']} billed"
                     + (f", {ret:g} already returned" if ret > 0 else "")
                     + ")",
                wraplength=380, justify="left").pack(side="left", padx=4)
            e = ctk.CTkEntry(row, width=90, placeholder_text="0")
            e.pack(side="right", padx=8)
            ctk.CTkLabel(row, text="Return qty:").pack(side="right")
            self.entries[it["id"]] = (e, max_q, it["name"])
            self.tv.insert("", "end", values=(
                it["name"], f"{it['qty']:g} {it['unit']}",
                f"{ret:g} {it['unit']}", money(it["line_total"])))

        ctk.CTkLabel(self, text="Note (optional)").pack(anchor="w", padx=12,
                                                        pady=(6, 0))
        self.note_e = ctk.CTkEntry(self, placeholder_text="reason for return")
        self.note_e.pack(fill="x", padx=12)

        self.tot_lbl = ctk.CTkLabel(self, text="",
                                    font=ctk.CTkFont(size=14, weight="bold"))
        self.tot_lbl.pack(anchor="w", padx=12, pady=6)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkButton(btns, text="Preview credit amount",
                      command=self.preview).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Confirm return", fg_color="#1f6f43",
                      hover_color="#175733",
                      command=self.confirm).pack(side="right", padx=4)

    def _gather(self):
        """Return list of {bill_item_id, qty}; raises ValueError on bad input."""
        out = []
        for bi_id, (e, max_q, name) in self.entries.items():
            raw = e.get().strip()
            if not raw:
                continue
            try:
                q = float(raw)
            except ValueError:
                raise ValueError(f"Invalid return qty for '{name}'.")
            if q <= 0:
                raise ValueError(f"Return qty must be > 0 for '{name}'.")
            if q - max_q > 0.0001:
                raise ValueError(
                    f"Only {max_q:g} of '{name}' can still be returned.")
            out.append({"bill_item_id": bi_id, "qty": q})
        return out

    def preview(self):
        try:
            items = self._gather()
        except ValueError as e:
            messagebox.showerror("Return", str(e))
            return
        if not items:
            self.tot_lbl.configure(text="Nothing to return.")
            return
        total = 0.0
        for it in items:
            bi = self.db._one("SELECT * FROM bill_items WHERE id=?",
                              (it["bill_item_id"],))
            taxable = max(it["qty"] * float(bi["price"])
                          - float(bi["line_discount"] or 0), 0.0)
            total += taxable * (1 + float(bi["gst_percent"] or 0) / 100)
        self.tot_lbl.configure(
            text=f"Credit amount: {money(total)}"
                 + ("  \u2014 will reduce the khata balance"
                    if self.bill["payment_type"] == "Credit"
                    and self.bill["customer_id"] else ""))

    def confirm(self):
        try:
            items = self._gather()
        except ValueError as e:
            messagebox.showerror("Return", str(e))
            return
        if not items:
            messagebox.showinfo("Return", "Enter a return qty first.")
            return
        if not messagebox.askyesno(
                "Confirm return",
                f"Create a credit note for {len(items)} line(s)?\n\n"
                "Stock will be added back"
                + (" and the customer's khata balance reduced."
                   if self.bill["payment_type"] == "Credit"
                   and self.bill["customer_id"] else ".")):
            return
        try:
            rid = self.db.create_return(self.bill_id, items,
                                        self.note_e.get().strip())
        except ValueError as e:
            messagebox.showerror("Return", str(e))
            return
        cn = self.db.get_return(rid)
        self.destroy()
        messagebox.showinfo(
            "Return",
            f"Credit note {cn['credit_note_no']} created \u2014 "
            f"{money(cn['total'])} credited.")
        if self.on_done:
            self.on_done(rid)


# ---------------------------------------------------------------------------
# WhatsApp bill sharing (no API keys, no extra dependencies)
# ---------------------------------------------------------------------------
def normalize_in_phone(raw):
    """Indian mobile normalization: strip non-digits; 10 digits starting
    6-9 -> prefix 91; 11 digits starting 0 -> drop 0, prefix 91."""
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 10 and d[0] in "6789":
        return "91" + d
    if len(d) == 11 and d.startswith("0"):
        return "91" + d[1:]
    if len(d) == 12 and d.startswith("91"):
        return d
    return d


def build_bill_message(db, bill_id):
    """Plain-text bill summary for WhatsApp. Returns (message, phone)."""
    bill = db.get_bill(bill_id)
    items = db.bill_items(bill_id)
    shop = db.shop_profile()["shop_name"] or "Vyro Shop"
    lines = [
        f"*{shop}*",
        f"Bill {bill['bill_no']}  \u00b7  {bill['date']}",
        "--------------------------",
    ]
    for it in items:
        lines.append(
            f"{it['name']} x {float(it['qty']):g} = "
            f"{RUPEE}{float(it['line_total']):,.2f}")
    lines.append("--------------------------")
    lines.append(f"Total: {RUPEE}{float(bill['grand_total']):,.2f}")
    lines.append(f"Payment: {bill['payment_type']}")
    if bill["payment_type"] == "Credit" and bill["customer_id"]:
        bal = db.customer_outstanding(bill["customer_id"])
        lines.append(f"Balance due: {RUPEE}{bal:,.2f}")
    return "\n".join(lines), (bill.get("customer_phone") or "").strip()


def share_bill_whatsapp(parent, db, bill_id, open_fn=None):
    """Open wa.me with the bill summary. If the customer has no phone,
    prompt to add one first."""
    bill = db.get_bill(bill_id)
    if not bill:
        return
    msg, phone = build_bill_message(db, bill_id)
    if not phone and bill.get("customer_id"):
        if not messagebox.askyesno(
                "WhatsApp",
                f"{bill.get('customer_name') or 'Customer'} has no phone "
                f"number saved.\n\nAdd one now?"):
            return
        win = ctk.CTkToplevel(parent)
        win.title("Add phone number")
        win.geometry("360x180")
        win.transient(parent)
        win.grab_set()
        ctk.CTkLabel(win, text=f"Phone for {bill.get('customer_name')}",
                     font=ctk.CTkFont(weight="bold")).pack(pady=(14, 4))
        p_e = ctk.CTkEntry(win, placeholder_text="10-digit mobile number")
        p_e.pack(fill="x", padx=16)
        p_e.focus_set()

        def save():
            ph = p_e.get().strip()
            if not re.sub(r"\D", "", ph):
                messagebox.showerror("Phone", "Enter a valid phone number.")
                return
            db.update_customer(bill["customer_id"], phone=ph)
            win.destroy()
            share_bill_whatsapp(parent, db, bill_id, open_fn=open_fn)

        p_e.bind("<Return>", lambda e: save())
        ctk.CTkButton(win, text="Save & share", command=save).pack(pady=12)
        return
    if not phone:
        messagebox.showinfo(
            "WhatsApp",
            "This bill has no customer phone number.\n"
            "Add the customer with a phone number first.")
        return
    digits = normalize_in_phone(phone)
    if len(digits) < 12:
        messagebox.showerror(
            "WhatsApp",
            f"'{phone}' does not look like a valid Indian mobile number.")
        return
    url = f"https://wa.me/{digits}?text={urllib.parse.quote(msg)}"
    (open_fn or webbrowser.open)(url)
