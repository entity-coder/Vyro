"""
Vyro — shop_ui.py
Marg-ERP parity screens: Cash Book (day book), Delivery Challans,
Supplier ledger (creditor payments), Outstanding Aging report,
Re-Order list (low-stock purchase planning).
"""

from datetime import date
from tkinter import messagebox

import customtkinter as ctk
from tkinter import ttk

RUPEE = "\u20b9"


def money(n):
    try:
        return f"{RUPEE}{float(n):,.2f}"
    except (TypeError, ValueError):
        return f"{RUPEE}0.00"


def today_iso():
    return date.today().isoformat()


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


CASH_CATEGORIES = ["General", "Rent", "Salary", "Owner drawing",
                   "Supplier payment", "Customer receipt", "Other"]


# ---------------------------------------------------------------------------
# Cash Book (day book) — non-bill cash movement only
# ---------------------------------------------------------------------------
class CashBookFrame(ctk.CTkFrame):
    def __init__(self, parent, db, app):
        super().__init__(parent, fg_color="transparent")
        self.db, self.app = db, app

        ctk.CTkLabel(self, text="Cash Book \u2014 day book",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                         anchor="w", pady=(4, 2))
        ctk.CTkLabel(
            self,
            text="Records cash movement OUTSIDE bills (expenses, owner "
                 "drawings, salary, rent...). Bill payments stay on the "
                 "bills themselves \u2014 nothing is double counted.",
            text_color="gray", wraplength=760, justify="left").pack(
                anchor="w", pady=(0, 6))

        self.bal_lbl = ctk.CTkLabel(self, text="",
                                    font=ctk.CTkFont(size=16, weight="bold"))
        self.bal_lbl.pack(anchor="w", pady=(0, 6))

        form = ctk.CTkFrame(self, corner_radius=10, border_width=1)
        form.pack(fill="x", pady=(2, 8), padx=2)
        r1 = ctk.CTkFrame(form, fg_color="transparent")
        r1.pack(fill="x", padx=10, pady=(10, 4))
        ctk.CTkLabel(r1, text="Date").pack(side="left", padx=(4, 2))
        self.date_e = ctk.CTkEntry(r1, width=110)
        self.date_e.insert(0, today_iso())
        self.date_e.pack(side="left", padx=4)
        ctk.CTkLabel(r1, text="Type").pack(side="left", padx=(10, 2))
        self.kind_var = ctk.StringVar(value="OUT")
        ctk.CTkSegmentedButton(r1, values=["IN", "OUT"],
                               variable=self.kind_var).pack(side="left",
                                                            padx=4)
        ctk.CTkLabel(r1, text="Category").pack(side="left", padx=(10, 2))
        self.cat_var = ctk.StringVar(value="General")
        ctk.CTkOptionMenu(r1, values=CASH_CATEGORIES,
                          variable=self.cat_var, width=150).pack(side="left",
                                                                 padx=4)
        ctk.CTkLabel(r1, text=f"Amount {RUPEE} *").pack(side="left",
                                                        padx=(10, 2))
        self.amt_e = ctk.CTkEntry(r1, width=110)
        self.amt_e.pack(side="left", padx=4)

        r2 = ctk.CTkFrame(form, fg_color="transparent")
        r2.pack(fill="x", padx=10, pady=(4, 10))
        ctk.CTkLabel(r2, text="Description *").pack(side="left", padx=(4, 2))
        self.desc_e = ctk.CTkEntry(r2, width=340,
                                   placeholder_text="e.g. shop rent for October")
        self.desc_e.pack(side="left", padx=4)
        ctk.CTkButton(r2, text="Record entry", fg_color="#1f6f43",
                      hover_color="#175733",
                      command=self.save_entry).pack(side="left", padx=12)

        op = ctk.CTkFrame(self, fg_color="transparent")
        op.pack(fill="x", pady=2)
        ctk.CTkLabel(op, text="Opening cash balance:").pack(side="left",
                                                             padx=4)
        self.open_e = ctk.CTkEntry(op, width=120)
        self.open_e.insert(0, f"{db.cash_opening_balance():g}")
        self.open_e.pack(side="left", padx=4)
        ctk.CTkButton(op, text="Set opening", width=100,
                      command=self.save_opening).pack(side="left", padx=4)
        ctk.CTkButton(op, text="Delete selected", fg_color="#b3261e",
                      hover_color="#8f1d17",
                      command=self.delete_selected).pack(side="right", padx=4)

        fr, self.tv = _tree(self, ("Date", "Type", "Description", "Category",
                                   "In", "Out", "Balance"),
                            widths=(100, 60, 260, 120, 110, 110, 120),
                            height=16)
        fr.pack(fill="both", expand=True, pady=6)
        self.refresh()

    def save_opening(self):
        try:
            v = float(self.open_e.get() or 0)
            assert v >= 0
        except (ValueError, AssertionError):
            messagebox.showerror("Cash Book",
                                 "Opening balance must be a number \u2265 0.")
            return
        self.db.set_cash_opening_balance(v)
        self.refresh()

    def save_entry(self):
        try:
            amt = float(self.amt_e.get())
            assert amt > 0
        except (ValueError, AssertionError):
            messagebox.showerror("Cash Book", "Enter an amount greater than 0.")
            return
        desc = self.desc_e.get().strip()
        if not desc:
            messagebox.showerror("Cash Book", "Description is required.")
            return
        kind = "in" if self.kind_var.get() == "IN" else "out"
        try:
            self.db.add_cash_entry(self.date_e.get().strip() or today_iso(),
                                   kind, desc, self.cat_var.get(), amt)
        except ValueError as e:
            messagebox.showerror("Cash Book", str(e))
            return
        self.amt_e.delete(0, "end")
        self.desc_e.delete(0, "end")
        self.refresh()

    def delete_selected(self):
        sel = self.tv.selection()
        if not sel:
            messagebox.showinfo("Cash Book", "Select an entry first.")
            return
        if messagebox.askyesno("Cash Book", "Delete this cash entry?"):
            self.db.delete_cash_entry(int(sel[0]))
            self.refresh()

    def refresh(self):
        for r in self.tv.get_children():
            self.tv.delete(r)
        # Running balance: walk oldest -> newest.
        entries = sorted(self.db.list_cash_entries(limit=100000),
                         key=lambda e: (e["date"], e["id"]))
        bal = self.db.cash_opening_balance()
        rows = []
        for e in entries:
            bal += float(e["amount"]) if e["kind"] == "in" else -float(e["amount"])
            rows.append((e, bal))
        for e, bal in reversed(rows[-500:]):
            self.tv.insert("", "end", iid=e["id"], values=(
                e["date"], "IN" if e["kind"] == "in" else "OUT",
                e["description"], e["category"],
                money(e["amount"]) if e["kind"] == "in" else "",
                money(e["amount"]) if e["kind"] == "out" else "",
                money(bal)))
        self.bal_lbl.configure(
            text=f"Cash in hand: {money(self.db.cash_balance())}  "
                 f"(opening {money(self.db.cash_opening_balance())})")


# ---------------------------------------------------------------------------
# Delivery challans
# ---------------------------------------------------------------------------
class ChallanDialog(ctk.CTkToplevel):
    """Create a delivery challan: customer + items, no GST, no stock/khata
    movement until converted to a bill."""

    def __init__(self, master, db, on_done=None):
        super().__init__(master)
        self.db = db
        self.on_done = on_done
        self.customer = None
        self.items = []
        self.title("New delivery challan")
        self.geometry("680x600")
        self.transient(master)
        self.grab_set()

        ctk.CTkLabel(self, text="Delivery challan",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(
                         anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            self, text="Goods sent on approval \u2014 not a tax invoice. "
                       "Stock and khata move only when this is converted "
                       "to a bill.",
            text_color="gray", wraplength=640, justify="left").pack(
                anchor="w", padx=12, pady=(0, 6))

        r1 = ctk.CTkFrame(self, fg_color="transparent")
        r1.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(r1, text="Customer *").pack(side="left", padx=(0, 2))
        self.cust_btn = ctk.CTkButton(r1, text="Choose customer...", width=220,
                                      anchor="w", fg_color=("gray80", "gray20"),
                                      command=self.pick_customer)
        self.cust_btn.pack(side="left", padx=4)
        ctk.CTkLabel(r1, text="Date").pack(side="left", padx=(12, 2))
        self.date_e = ctk.CTkEntry(r1, width=110)
        self.date_e.insert(0, today_iso())
        self.date_e.pack(side="left", padx=4)

        r2 = ctk.CTkFrame(self, fg_color="transparent")
        r2.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(r2, text="Product").pack(side="left", padx=(0, 2))
        self.prod_btn = ctk.CTkButton(r2, text="Choose product...", width=200,
                                      anchor="w", fg_color=("gray80", "gray20"),
                                      command=self.pick_product)
        self.prod_btn.pack(side="left", padx=4)
        self.picked = None
        ctk.CTkLabel(r2, text="Qty *").pack(side="left", padx=(8, 2))
        self.qty_e = ctk.CTkEntry(r2, width=70)
        self.qty_e.insert(0, "1")
        self.qty_e.pack(side="left", padx=4)
        ctk.CTkLabel(r2, text=f"Rate {RUPEE}").pack(side="left", padx=(8, 2))
        self.rate_e = ctk.CTkEntry(r2, width=90)
        self.rate_e.pack(side="left", padx=4)
        ctk.CTkButton(r2, text="Add", command=self.add_item).pack(
            side="left", padx=8)

        fr, self.tv = _tree(self, ("Product", "Qty", "Rate", "Amount"),
                             widths=(260, 80, 100, 120), height=8)
        fr.pack(fill="x", padx=12, pady=4)
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.pack(fill="x", padx=12, pady=2)
        ctk.CTkButton(bot, text="Remove selected",
                      command=self.remove_item).pack(side="left")
        self.tot_lbl = ctk.CTkLabel(bot, text="",
                                    font=ctk.CTkFont(weight="bold"))
        self.tot_lbl.pack(side="left", padx=16)

        ctk.CTkLabel(self, text="Note").pack(anchor="w", padx=12, pady=(6, 0))
        self.note_e = ctk.CTkEntry(self, placeholder_text="optional")
        self.note_e.pack(fill="x", padx=12)

        ctk.CTkButton(self, text="Save challan", fg_color="#1f6f43",
                      hover_color="#175733", height=40,
                      command=self.save).pack(pady=14)

    def pick_customer(self):
        from ui import SearchPicker
        SearchPicker(
            self, "Choose customer",
            lambda q: self.db.list_customers(q),
            lambda c: f"{c['name']}" + (f" \u2014 {c['phone']}"
                                        if c["phone"] else ""),
            self._set_customer)

    def _set_customer(self, c):
        self.customer = c
        self.cust_btn.configure(text=c["name"])

    def pick_product(self):
        from ui import SearchPicker
        SearchPicker(
            self, "Choose product",
            lambda q: self.db.list_products(q)[:60],
            lambda p: (f"{p['name']}  \u00b7 {p['sku'] or '\u2014'}  \u00b7 "
                       f"stock {p['stock']:g}"),
            self._set_product)

    def _set_product(self, p):
        self.picked = p
        self.prod_btn.configure(text=p["name"])
        self.rate_e.delete(0, "end")
        self.rate_e.insert(0, f"{p['wholesale_price']:g}")
        self.qty_e.focus_set()
        self.qty_e.select_range(0, "end")

    def add_item(self):
        if not self.picked:
            messagebox.showerror("Challan", "Choose a product first.")
            return
        p = self.picked
        try:
            qty = float(self.qty_e.get())
            rate = float(self.rate_e.get() or 0)
            assert qty > 0 and rate >= 0
        except (ValueError, AssertionError):
            messagebox.showerror("Challan",
                                 "Enter a valid qty (> 0) and rate (\u2265 0).")
            return
        for it in self.items:
            if it["product_id"] == p["id"] and it["price"] == rate:
                it["qty"] += qty
                break
        else:
            self.items.append({"product_id": p["id"], "name": p["name"],
                               "unit": p["unit"], "qty": qty, "price": rate})
        self.picked = None
        self.prod_btn.configure(text="Choose product...")
        self.qty_e.delete(0, "end")
        self.qty_e.insert(0, "1")
        self.rate_e.delete(0, "end")
        self.refresh_items()

    def remove_item(self):
        sel = self.tv.selection()
        if sel:
            del self.items[int(sel[0])]
            self.refresh_items()

    def refresh_items(self):
        for r in self.tv.get_children():
            self.tv.delete(r)
        total = 0.0
        for i, it in enumerate(self.items):
            amt = it["qty"] * it["price"]
            total += amt
            self.tv.insert("", "end", iid=str(i), values=(
                it["name"], f"{it['qty']:g} {it['unit']}",
                money(it["price"]), money(amt)))
        self.tot_lbl.configure(text=f"Total: {money(total)}")

    def save(self):
        if not self.customer:
            messagebox.showerror("Challan", "Choose a customer first.")
            return
        if not self.items:
            messagebox.showerror("Challan", "Add at least one item.")
            return
        try:
            cid = self.db.create_challan(
                self.customer["id"], self.date_e.get().strip() or today_iso(),
                self.note_e.get().strip(), self.items)
        except ValueError as e:
            messagebox.showerror("Challan", str(e))
            return
        ch = self.db.get_challan(cid)
        self.destroy()
        messagebox.showinfo("Challan",
                            f"Challan {ch['challan_no']} saved.\n"
                            "Convert it to a bill when the goods are accepted.")
        if self.on_done:
            self.on_done(cid)


class ChallansFrame(ctk.CTkFrame):
    def __init__(self, parent, db, app):
        super().__init__(parent, fg_color="transparent")
        self.db, self.app = db, app
        ctk.CTkLabel(self, text="Delivery challans",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                         anchor="w", pady=(4, 8))

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", pady=4)
        ctk.CTkButton(btns, text="New challan", fg_color="#1f6f43",
                      hover_color="#175733",
                      command=self.new_challan).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Print challan",
                      command=self.print_challan).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Convert to bill", fg_color="#0b5fa5",
                      hover_color="#084a82",
                      command=self.convert_to_bill).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Delete", fg_color="#b3261e",
                      hover_color="#8f1d17",
                      command=self.delete_challan).pack(side="right", padx=4)

        fr, self.tv = _tree(self, ("Challan No", "Date", "Customer", "Items",
                                   "Amount", "Status"),
                            widths=(90, 100, 220, 60, 120, 100), height=20)
        fr.pack(fill="both", expand=True, pady=6)
        self.tv.bind("<Double-1>", lambda e: self.print_challan())
        self.refresh()

    def refresh(self):
        for r in self.tv.get_children():
            self.tv.delete(r)
        for ch in self.db.list_challans():
            items = self.db.challan_items(ch["id"])
            amt = sum(float(it["qty"]) * float(it["price"]) for it in items)
            self.tv.insert("", "end", iid=ch["id"], values=(
                ch["challan_no"], ch["date"], ch["customer_name"] or "Walk-in",
                len(items), money(amt), ch["status"]))

    def selected_id(self):
        sel = self.tv.selection()
        if not sel:
            messagebox.showinfo("Challans", "Select a challan first.")
            return None
        return int(sel[0])

    def new_challan(self):
        ChallanDialog(self, self.db, on_done=lambda cid: self.refresh())

    def print_challan(self):
        cid = self.selected_id()
        if cid is None:
            return
        ch = self.db.get_challan(cid)
        items = self.db.challan_items(cid)
        try:
            import printing
            pdf = printing.generate_challan_pdf(
                ch, items, self.db.shop_profile(), self.db.print_prefs())
            ok, pmsg = printing.print_pdf(pdf)
            if ok:
                messagebox.showinfo("Challan", "Challan sent to printer.")
            else:
                # Never auto-open: show reason + path + fix hint.
                messagebox.showinfo("Challan", pmsg)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Challan", f"Could not build the PDF: {e}")

    def convert_to_bill(self):
        cid = self.selected_id()
        if cid is None:
            return
        ch = self.db.get_challan(cid)
        items = self.db.challan_items(cid)
        if ch["status"] == "converted" and not messagebox.askyesno(
                "Convert challan",
                f"{ch['challan_no']} was already converted once.\n\n"
                "Convert it again into a fresh bill?"):
            return
        cust = (self.db.get_customer(ch["customer_id"])
                if ch["customer_id"] else None)
        # Mark converted BEFORE switching screens: open_billing_tab destroys
        # this frame (content children are rebuilt on every nav).
        self.db.mark_challan_converted(cid)
        self.app.open_billing_tab(label=f"Challan {ch['challan_no']}")
        bf = self.app.screens["billing"]
        tab, w = bf.current()
        if cust:
            bf._set_customer(tab, cust, w)
        n = 0
        for it in items:
            p = (self.db.get_product(it["product_id"])
                 if it.get("product_id") else None)
            if p:
                gst, sku, unit = p["gst_percent"], p["sku"], p["unit"]
            else:
                gst, sku, unit = 0, "", it["unit"]
            tab.items.append({
                "product_id": it["product_id"], "name": it["name"],
                "unit": unit, "qty": it["qty"], "price": float(it["price"]),
                "line_discount": 0, "gst_percent": gst, "sku": sku})
            n += 1
        bf._refresh_totals(tab.name)
        messagebox.showinfo(
            "Convert challan",
            f"Loaded {n} item(s) from {ch['challan_no']} into a new bill.\n"
            "Save the bill normally \u2014 stock and khata move then.")

    def delete_challan(self):
        cid = self.selected_id()
        if cid is None:
            return
        ch = self.db.get_challan(cid)
        if messagebox.askyesno("Delete challan",
                               f"Delete {ch['challan_no']} permanently?"):
            self.db.delete_challan(cid)
            self.refresh()


# ---------------------------------------------------------------------------
# Supplier ledger (creditor payments) — mirror of customer outstanding collection
# ---------------------------------------------------------------------------
class SuppliersFrame(ctk.CTkFrame):
    def __init__(self, parent, db, app):
        super().__init__(parent, fg_color="transparent")
        self.db, self.app = db, app
        ctk.CTkLabel(self, text="Supplier ledger (creditors)",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                         anchor="w", pady=(4, 8))

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", pady=4)
        self.search = ctk.CTkEntry(top, placeholder_text="Search suppliers...",
                                   width=260)
        self.search.pack(side="left", padx=4)
        self.search.bind("<KeyRelease>", lambda e: self.refresh())
        ctk.CTkButton(top, text="Pay supplier", fg_color="#1f6f43",
                      hover_color="#175733",
                      command=self.payment_dialog).pack(side="left", padx=4)
        ctk.CTkButton(top, text="Payment history",
                      command=self.history_dialog).pack(side="left", padx=4)
        self.payable_lbl = ctk.CTkLabel(top, text="",
                                     font=ctk.CTkFont(weight="bold"))
        self.payable_lbl.pack(side="right", padx=12)

        fr, self.tv = _tree(self, ("Supplier", "Phone", "Payable \u20b9"),
                           widths=(260, 140, 130), height=20)
        fr.pack(fill="both", expand=True, pady=6)
        self.tv.bind("<Double-1>", lambda e: self.history_dialog())
        self.refresh()

    def refresh(self):
        for r in self.tv.get_children():
            self.tv.delete(r)
        q = self.search.get().strip().lower()
        total = 0.0
        for s in self.db.list_suppliers():
            due = self.db.supplier_outstanding(s["id"])
            total += due
            if q and q not in s["name"].lower() \
                    and q not in (s["phone"] or "").lower():
                continue
            self.tv.insert("", "end", iid=s["id"], values=(
                s["name"], s["phone"],
                f"{due:.2f}" if due > 0.004 else "\u2014"))
        self.payable_lbl.configure(
            text=f"Total payable: {money(self.db.total_creditors())}")

    def selected_id(self):
        sel = self.tv.selection()
        if not sel:
            messagebox.showinfo("Suppliers", "Select a supplier first.")
            return None
        return int(sel[0])

    def payment_dialog(self):
        sid = self.selected_id()
        if sid is None:
            return
        s = self.db.get_supplier(sid)
        outstanding = self.db.supplier_outstanding(sid)
        if outstanding <= 0.004:
            messagebox.showinfo("Payment",
                                f"{s['name']} has no outstanding payable.")
            return
        win = ctk.CTkToplevel(self)
        win.title("Pay supplier")
        win.geometry("380x400")
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(
            win, text=f"{s['name']} \u2014 payable {money(outstanding)}",
            font=ctk.CTkFont(weight="bold")).pack(pady=10)
        ctk.CTkLabel(win, text="Amount paid (\u20b9) *").pack(
            anchor="w", padx=14)
        amt_e = ctk.CTkEntry(win)
        amt_e.pack(fill="x", padx=14)
        amt_e.focus_set()
        ctk.CTkLabel(win, text="Date").pack(anchor="w", padx=14, pady=(6, 0))
        date_e = ctk.CTkEntry(win)
        date_e.insert(0, today_iso())
        date_e.pack(fill="x", padx=14)
        ctk.CTkLabel(win, text="Mode").pack(anchor="w", padx=14, pady=(6, 0))
        mode_var = ctk.StringVar(value="Cash")
        ctk.CTkOptionMenu(win, values=["Cash", "UPI", "Bank"],
                          variable=mode_var).pack(anchor="w", padx=14)
        ctk.CTkLabel(win, text="Note").pack(anchor="w", padx=14, pady=(6, 0))
        note_e = ctk.CTkEntry(win, placeholder_text="e.g. part payment")
        note_e.pack(fill="x", padx=14)

        def save():
            try:
                amt = float(amt_e.get())
                assert amt > 0
            except (ValueError, AssertionError):
                messagebox.showerror("Payment", "Enter a valid amount.")
                return
            try:
                self.db.record_supplier_payment(
                    sid, amt, mode_var.get(), note_e.get().strip(),
                    date_e.get().strip() or today_iso())
            except ValueError as e:
                messagebox.showerror("Payment", str(e))
                return
            win.destroy()
            self.refresh()
            messagebox.showinfo(
                "Payment",
                f"Recorded {money(amt)} paid to {s['name']}.\n"
                f"Remaining payable: "
                f"{money(self.db.supplier_outstanding(sid))}.")

        amt_e.bind("<Return>", lambda e: save())
        ctk.CTkButton(win, text="Record payment", command=save).pack(pady=14)

    def history_dialog(self):
        sid = self.selected_id()
        if sid is None:
            return
        s = self.db.get_supplier(sid)
        win = ctk.CTkToplevel(self)
        win.title(f"Payments \u2014 {s['name']}")
        win.geometry("560x440")
        win.transient(self)
        ctk.CTkLabel(
            win, text=f"{s['name']}  \u00b7  outstanding "
                     f"{money(self.db.supplier_outstanding(sid))}",
            font=ctk.CTkFont(size=14, weight="bold")).pack(
                anchor="w", padx=12, pady=8)
        fr, tv = _tree(win, ("Date", "Amount", "Mode", "Note"),
                       widths=(110, 100, 70, 240), height=12)
        fr.pack(fill="both", expand=True, padx=12, pady=4)
        for p in self.db.supplier_payments(sid):
            tv.insert("", "end", values=(p["date"], money(p["amount"]),
                                         p.get("mode") or "Cash",
                                         p["note"] or ""))


# ---------------------------------------------------------------------------
# Outstanding aging report (wholesale khata view)
# ---------------------------------------------------------------------------
class AgingFrame(ctk.CTkFrame):
    BUCKETS = ["1\u201330", "31\u201360", "61\u201390", "91\u2013120",
               "121\u2013240", "241+"]

    def __init__(self, parent, db, app):
        super().__init__(parent, fg_color="transparent")
        self.db, self.app = db, app
        ctk.CTkLabel(self, text="Outstanding aging",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                         anchor="w", pady=(4, 2))
        ctk.CTkLabel(
            self,
            text="Outstanding grouped by the age of the originating bill. Payments "
                 "are assumed to settle the oldest bills first (FIFO).",
            text_color="gray", wraplength=760, justify="left").pack(
                anchor="w", pady=(0, 6))

        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True, pady=4)
        tabs.add("Customers (debtors)")
        tabs.add("Suppliers (creditors)")
        self.tv_c = self._build_tab(tabs.tab("Customers (debtors)"),
                                    self.db.customer_aging)
        self.tv_s = self._build_tab(tabs.tab("Suppliers (creditors)"),
                                    self.db.supplier_aging)
        ctk.CTkButton(self, text="Refresh",
                      command=self.refresh).pack(anchor="w", pady=6)
        self.refresh()

    def _build_tab(self, tab, fetch_fn):
        cols = ("Party",) + tuple(self.BUCKETS) + ("Total",)
        widths = (220,) + (90,) * 6 + (120,)
        fr, tv = _tree(tab, cols, widths=widths, height=16)
        fr.pack(fill="both", expand=True, padx=8, pady=8)
        tot = ctk.CTkLabel(tab, text="", font=ctk.CTkFont(weight="bold"))
        tot.pack(anchor="w", padx=10, pady=4)
        tv._fetch = fetch_fn
        tv._tot = tot
        return tv

    def refresh(self):
        for tv in (self.tv_c, self.tv_s):
            for r in tv.get_children():
                tv.delete(r)
            sums = [0.0] * 6
            grand = 0.0
            for row in tv._fetch():
                vals = [f"{b:,.2f}" if b > 0.004 else "\u2014"
                        for b in row["buckets"]]
                tv.insert("", "end", values=(row["name"],) + tuple(vals)
                          + (f"{row['total']:,.2f}",))
                for i, b in enumerate(row["buckets"]):
                    sums[i] += b
                grand += row["total"]
            tv._tot.configure(
                text="Totals:  " + "  \u00b7  ".join(
                    f"{lbl}: {money(s)}"
                    for lbl, s in zip(self.BUCKETS, sums))
                + f"  \u00b7  Grand total: {money(grand)}")


# ---------------------------------------------------------------------------
# Re-Order list (low-stock purchase planning) — Marg's "Re-Order" menu item
# ---------------------------------------------------------------------------
class ReOrderFrame(ctk.CTkFrame):
    """One screen answering "what do I order from which supplier today?":
    every product at/below its low-stock threshold (threshold > 0 only),
    sorted by urgency (stock / threshold, lowest first), with a suggested
    order qty, the last (weighted-average) purchase rate and the supplier."""

    def __init__(self, parent, db, app):
        super().__init__(parent, fg_color="transparent")
        self.db, self.app = db, app
        ctk.CTkLabel(self, text="Re-Order list",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                         anchor="w", pady=(4, 2))
        ctk.CTkLabel(
            self,
            text="Products at or below their low-stock threshold (products "
                 "with no threshold set are skipped). Suggested order qty is "
                 "2 x threshold minus stock. Select rows, then load them "
                 "into Purchases.",
            text_color="gray", wraplength=760, justify="left").pack(
                anchor="w", pady=(0, 6))

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", pady=4)
        ctk.CTkButton(btns, text="Load into Purchases", fg_color="#1f6f43",
                      hover_color="#175733",
                      command=self.load_into_purchases).pack(side="left",
                                                             padx=4)
        ctk.CTkButton(btns, text="Print list",
                      command=self.print_list).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Refresh",
                      command=self.refresh).pack(side="right", padx=4)
        ctk.CTkLabel(btns,
                     text="Keys: arrows move, Enter toggles row, Esc clears",
                     text_color="gray").pack(side="right", padx=12)

        self.empty_lbl = ctk.CTkLabel(
            self, text="All stock is healthy — nothing is below its "
                       "low-stock threshold.",
            font=ctk.CTkFont(size=14), text_color="gray")
        fr, self.tv = _tree(self,
                            ("Pick", "Product", "SKU", "Stock", "Threshold",
                             "Order qty", "Last rate", "Est. amount",
                             "Supplier", "Phone", "Nearest expiry"),
                            widths=(50, 200, 90, 70, 80, 80, 90, 100,
                                    140, 100, 110),
                            height=18)
        self.tree_frame = fr
        self.tv.bind("<Return>", self._toggle_focused)
        self.tv.bind("<Escape>", lambda e: self._clear_selection())
        # Left-click on the "Pick" column toggles selection too.
        self.tv.bind("<ButtonRelease-1>", self._click_toggle)
        self._click_x = None
        self.tv.bind("<Button-1>", lambda e: setattr(
            self, "_click_x", e.x))
        self.rows = []
        self.refresh()

    def _row_data(self, p):
        stock = float(p["stock"] or 0)
        th = float(p["low_stock_threshold"] or 0)
        order_qty = max(1.0, 2 * th - stock)
        last_rate = float(p["purchase_price"] or 0)
        sup_name = (p["supplier"] or "").strip()
        phone = ""
        if sup_name:
            s = self.db.get_supplier_by_name(sup_name)
            if s:
                phone = s["phone"] or ""
        expiry = self.db.product_earliest_expiry(p["id"]) or ""
        return {"product_id": p["id"], "name": p["name"],
                "sku": p["sku"] or "", "unit": p["unit"] or "",
                "stock": stock, "threshold": th, "order_qty": order_qty,
                "last_rate": last_rate,
                "est_amount": order_qty * last_rate,
                "supplier": sup_name, "phone": phone, "expiry": expiry}

    def refresh(self):
        for r in self.tv.get_children():
            self.tv.delete(r)
        self.rows = [self._row_data(p) for p in self.db.reorder_products()]
        if not self.rows:
            self.tree_frame.pack_forget()
            self.empty_lbl.pack(fill="both", expand=True, pady=40)
            return
        self.empty_lbl.pack_forget()
        self.tree_frame.pack(fill="both", expand=True, pady=6)
        for r in self.rows:
            self.tv.insert("", "end", iid=str(r["product_id"]), values=(
                "\u2610", r["name"], r["sku"] or "-",
                f"{r['stock']:g}", f"{r['threshold']:g}",
                f"{r['order_qty']:g}", money(r["last_rate"]),
                money(r["est_amount"]),
                r["supplier"] or "-", r["phone"] or "-",
                r["expiry"] or "-"))
        self._paint_checks()

    def _paint_checks(self):
        sel = set(self.tv.selection())
        for iid in self.tv.get_children():
            vals = list(self.tv.item(iid, "values"))
            vals[0] = "\u2611" if iid in sel else "\u2610"
            self.tv.item(iid, values=vals)

    def _toggle_focused(self, event=None):
        foc = self.tv.focus()
        if not foc:
            return "break"
        if foc in self.tv.selection():
            self.tv.selection_remove(foc)
        else:
            self.tv.selection_add(foc)
        self._paint_checks()
        return "break"

    def _click_toggle(self, event=None):
        # Toggle only when the click landed in the "Pick" column.
        if self._click_x is None:
            return
        col = self.tv.identify_column(self._click_x)
        row = self.tv.identify_row(self._click_x)
        if col == "#1" and row:
            self.tv.selection_toggle(row)
            self._paint_checks()

    def _clear_selection(self):
        self.tv.selection_remove(self.tv.selection())
        self._paint_checks()

    def selected_rows(self):
        by_id = {str(r["product_id"]): r for r in self.rows}
        return [by_id[i] for i in self.tv.selection() if i in by_id]

    def load_into_purchases(self):
        sel = self.selected_rows()
        if not sel:
            messagebox.showinfo("Re-Order",
                                "Select one or more products first "
                                "(Enter toggles a row).")
            return
        self.app.show("purchases")
        pf = self.app.screens["purchases"]
        payload = [{
            "product_id": r["product_id"], "name": r["name"],
            "unit": r["unit"], "qty": r["order_qty"],
            "cost": r["last_rate"],
            "gst_percent": float(self.db.get_product(
                r["product_id"])["gst_percent"] or 0),
            "expiry_date": ""} for r in sel]
        n = pf.prefill_items(payload)
        messagebox.showinfo(
            "Re-Order",
            f"Loaded {n} item(s) into Purchases at the last purchase "
            "rate.\nChoose the supplier and save — stock updates then.")

    def print_list(self):
        if not self.rows:
            messagebox.showinfo("Re-Order", "Nothing to print — stock is "
                                           "healthy.")
            return
        try:
            import printing
            pdf = printing.generate_reorder_pdf(
                self.rows, self.db.shop_profile(), self.db.print_prefs())
            ok, pmsg = printing.print_pdf(pdf)
            if ok:
                messagebox.showinfo("Re-Order", "Re-order list sent to printer.")
            else:
                # Never auto-open: show reason + path + fix hint.
                messagebox.showinfo("Re-Order", pmsg)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Re-Order", f"Could not build the PDF: {e}")
