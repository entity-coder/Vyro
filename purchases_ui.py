"""
Vyro — purchases_ui.py
Purchases screen: record stock bought from suppliers (stock in).
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


def fnum(widget, default=0.0):
    try:
        return float(widget.get().strip() or default)
    except ValueError:
        return default


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


class PurchasesFrame(ctk.CTkFrame):
    """Record supplier purchases: stock in + weighted-average cost."""

    def __init__(self, parent, db, app):
        super().__init__(parent, fg_color="transparent")
        self.db, self.app = db, app
        self.supplier = None
        self.items = []

        ctk.CTkLabel(self, text="Purchases \u2014 stock in",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                         anchor="w", pady=(4, 8))

        form = ctk.CTkFrame(self, corner_radius=10, border_width=1)
        form.pack(fill="x", pady=(2, 8), padx=2)

        r1 = ctk.CTkFrame(form, fg_color="transparent")
        r1.pack(fill="x", padx=10, pady=(10, 4))
        ctk.CTkLabel(r1, text="Supplier *").pack(side="left", padx=(4, 2))
        self.sup_btn = ctk.CTkButton(r1, text="Choose supplier...",
                                     width=220, anchor="w",
                                     fg_color=("gray80", "gray20"),
                                     command=self.pick_supplier)
        self.sup_btn.pack(side="left", padx=4)
        ctk.CTkButton(r1, text="+ New", width=60,
                      command=self.new_supplier_dialog).pack(side="left",
                                                             padx=2)
        ctk.CTkLabel(r1, text="Date").pack(side="left", padx=(12, 2))
        self.date_e = ctk.CTkEntry(r1, width=110)
        self.date_e.insert(0, today_iso())
        self.date_e.pack(side="left", padx=4)
        ctk.CTkLabel(r1, text="Supplier inv./ref no.").pack(
            side="left", padx=(12, 2))
        self.ref_e = ctk.CTkEntry(r1, width=140,
                                  placeholder_text="optional")
        self.ref_e.pack(side="left", padx=4)

        r2 = ctk.CTkFrame(form, fg_color="transparent")
        r2.pack(fill="x", padx=10, pady=(4, 6))
        ctk.CTkLabel(r2, text="Product").pack(side="left", padx=(4, 2))
        self.prod_btn = ctk.CTkButton(r2, text="Choose product...",
                                      width=220, anchor="w",
                                      fg_color=("gray80", "gray20"),
                                      command=self.pick_product)
        self.prod_btn.pack(side="left", padx=4)
        self.picked = None
        ctk.CTkLabel(r2, text="Qty *").pack(side="left", padx=(8, 2))
        self.qty_e = ctk.CTkEntry(r2, width=80)
        self.qty_e.insert(0, "1")
        self.qty_e.pack(side="left", padx=4)
        ctk.CTkLabel(r2, text=f"Cost/unit {RUPEE} *").pack(
            side="left", padx=(8, 2))
        self.cost_e = ctk.CTkEntry(r2, width=90)
        self.cost_e.pack(side="left", padx=4)
        ctk.CTkLabel(r2, text="GST %").pack(side="left", padx=(8, 2))
        self.gst_e = ctk.CTkEntry(r2, width=60)
        self.gst_e.pack(side="left", padx=4)
        ctk.CTkLabel(r2, text="Expiry").pack(side="left", padx=(8, 2))
        self.exp_e = ctk.CTkEntry(r2, width=100,
                                  placeholder_text="YYYY-MM-DD")
        self.exp_e.pack(side="left", padx=4)
        ctk.CTkButton(r2, text="Add item",
                      command=self.add_item).pack(side="left", padx=10)
        ctk.CTkLabel(
            r2,
            text="Saving updates stock and sets the purchase price to the "
                 "weighted average of old + new stock.",
            text_color="gray", font=ctk.CTkFont(size=11),
            wraplength=300, justify="left").pack(side="left", padx=10)

        fr, self.tv = _tree(self, ("Product", "Qty", "Cost/unit", "GST%",
                                   "Expiry", "Amount"),
                             widths=(200, 80, 100, 60, 100, 120), height=7)
        fr.pack(fill="x", pady=4)
        self.tv.bind("<Double-1>", lambda e: self.remove_item())

        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.pack(fill="x", pady=4)
        ctk.CTkButton(bot, text="Remove selected",
                      command=self.remove_item).pack(side="left", padx=4)
        self.tot_lbl = ctk.CTkLabel(bot, text="",
                                    font=ctk.CTkFont(size=15, weight="bold"))
        self.tot_lbl.pack(side="left", padx=16)
        ctk.CTkButton(bot, text="Save purchase", fg_color="#1f6f43",
                      hover_color="#175733", height=40,
                      command=self.save_purchase).pack(side="right", padx=4)

        ctk.CTkLabel(self, text="Past purchases",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(
                         anchor="w", pady=(10, 2))
        fr2, self.tv2 = _tree(self, ("ID", "Date", "Supplier", "Ref no.",
                                     "Items", "Total"),
                              widths=(50, 100, 220, 120, 60, 120), height=9)
        fr2.pack(fill="both", expand=True, pady=4)
        fr2_btns = ctk.CTkFrame(self, fg_color="transparent")
        fr2_btns.pack(fill="x", pady=2)
        ctk.CTkButton(fr2_btns, text="View items",
                      command=self.view_purchase).pack(side="left", padx=4)
        ctk.CTkButton(fr2_btns, text="Delete (reverses stock)",
                      fg_color="#b3261e", hover_color="#8f1d17",
                      command=self.delete_purchase).pack(side="left", padx=4)
        self.refresh_list()

    # -- suppliers ------------------------------------------------------
    def pick_supplier(self):
        from ui import SearchPicker
        SearchPicker(
            self, "Choose supplier",
            lambda q: self.db.list_suppliers(q),
            lambda s: f"{s['name']}" + (f" \u2014 {s['phone']}"
                                        if s['phone'] else ""),
            self._set_supplier)

    def _set_supplier(self, s):
        self.supplier = s
        self.sup_btn.configure(text=s["name"])

    def new_supplier_dialog(self):
        win = ctk.CTkToplevel(self)
        win.title("New supplier")
        win.geometry("380x300")
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(win, text="Name *").pack(anchor="w", padx=14,
                                              pady=(10, 0))
        n_e = ctk.CTkEntry(win)
        n_e.pack(fill="x", padx=14)
        n_e.focus_set()
        ctk.CTkLabel(win, text="Phone").pack(anchor="w", padx=14, pady=(6, 0))
        p_e = ctk.CTkEntry(win)
        p_e.pack(fill="x", padx=14)
        ctk.CTkLabel(win, text="Address").pack(anchor="w", padx=14,
                                               pady=(6, 0))
        a_e = ctk.CTkEntry(win)
        a_e.pack(fill="x", padx=14)

        def save():
            name = n_e.get().strip()
            if not name:
                messagebox.showerror("Supplier", "Name is required.")
                return
            sid = self.db.add_supplier(name, p_e.get().strip(),
                                       a_e.get().strip())
            self._set_supplier(self.db.get_supplier(sid))
            win.destroy()

        n_e.bind("<Return>", lambda e: save())
        ctk.CTkButton(win, text="Save & select", command=save).pack(pady=12)

    # -- items ----------------------------------------------------------
    def pick_product(self):
        from ui import SearchPicker
        SearchPicker(
            self, "Choose product",
            lambda q: self.db.list_products(q)[:60],
            lambda p: (f"{p['name']}  \u00b7 {p['sku'] or '\u2014'}  \u00b7 "
                       f"stock {p['stock']:g}  \u00b7 cost {money(p['purchase_price'])}"),
            self._set_product)

    def _set_product(self, p):
        self.picked = p
        self.prod_btn.configure(text=p["name"])
        self.cost_e.delete(0, "end")
        self.cost_e.insert(0, f"{p['purchase_price']:g}")
        self.gst_e.delete(0, "end")
        self.gst_e.insert(0, f"{p['gst_percent']:g}")
        self.qty_e.focus_set()
        self.qty_e.select_range(0, "end")

    def add_item(self):
        if not self.picked:
            messagebox.showerror("Purchase", "Choose a product first.")
            return
        p = self.picked
        expiry = self.exp_e.get().strip()
        if expiry:
            from datetime import date as _date
            try:
                _date.fromisoformat(expiry)
            except ValueError:
                messagebox.showerror(
                    "Purchase",
                    "Expiry must be YYYY-MM-DD (or left blank).")
                return
        try:
            qty = float(self.qty_e.get())
            cost = float(self.cost_e.get())
            gst = float(self.gst_e.get() or 0)
            assert qty > 0 and cost >= 0 and gst >= 0
        except (ValueError, AssertionError):
            messagebox.showerror("Purchase",
                                 "Enter valid qty (> 0), cost (\u2265 0) "
                                 "and GST %.")
            return
        for it in self.items:
            if it["product_id"] == p["id"] and it["cost"] == cost \
                    and it["gst_percent"] == gst \
                    and it.get("expiry_date") == expiry:
                it["qty"] += qty
                break
        else:
            self.items.append({
                "product_id": p["id"], "name": p["name"], "unit": p["unit"],
                "qty": qty, "cost": cost, "gst_percent": gst,
                "expiry_date": expiry})
        self.picked = None
        self.prod_btn.configure(text="Choose product...")
        self.qty_e.delete(0, "end")
        self.qty_e.insert(0, "1")
        self.cost_e.delete(0, "end")
        self.gst_e.delete(0, "end")
        self.exp_e.delete(0, "end")
        self.refresh_items()

    def remove_item(self):
        sel = self.tv.selection()
        if not sel:
            return
        del self.items[int(sel[0])]
        self.refresh_items()

    def refresh_items(self):
        for r in self.tv.get_children():
            self.tv.delete(r)
        total = 0.0
        for i, it in enumerate(self.items):
            amt = it["qty"] * it["cost"] * (1 + it["gst_percent"] / 100)
            total += amt
            self.tv.insert("", "end", iid=str(i), values=(
                it["name"], f"{it['qty']:g} {it['unit']}",
                money(it["cost"]), f"{it['gst_percent']:g}%",
                it.get("expiry_date") or "-", money(amt)))
        self.tot_lbl.configure(text=f"Total: {money(total)}")

    # -- re-order prefill -------------------------------------------------
    def prefill_items(self, item_dicts):
        """Pre-fill the entry rows from the Re-Order screen (or anywhere
        else): list of dicts with product_id, name, unit, qty, cost,
        gst_percent, expiry_date. Duplicate product+rate rows are merged,
        matching the normal add-item behaviour."""
        added = 0
        for d in item_dicts:
            if float(d.get("qty") or 0) <= 0:
                continue
            for it in self.items:
                if it["product_id"] == d["product_id"] \
                        and it["cost"] == float(d.get("cost") or 0) \
                        and it.get("gst_percent") == float(
                            d.get("gst_percent") or 0) \
                        and it.get("expiry_date") == (d.get("expiry_date")
                                                      or ""):
                    it["qty"] += float(d["qty"])
                    break
            else:
                self.items.append({
                    "product_id": d["product_id"], "name": d["name"],
                    "unit": d.get("unit") or "",
                    "qty": float(d["qty"]),
                    "cost": float(d.get("cost") or 0),
                    "gst_percent": float(d.get("gst_percent") or 0),
                    "expiry_date": d.get("expiry_date") or ""})
            added += 1
        self.refresh_items()
        return added

    # -- save / list ----------------------------------------------------
    def save_purchase(self):
        if not self.supplier:
            messagebox.showerror("Purchase", "Choose a supplier first.")
            return
        if not self.items:
            messagebox.showerror("Purchase", "Add at least one item.")
            return
        d = self.date_e.get().strip() or today_iso()
        try:
            pid = self.db.create_purchase(self.supplier["id"], d,
                                          self.ref_e.get().strip(),
                                          self.items)
        except ValueError as e:
            messagebox.showerror("Purchase", str(e))
            return
        pur = self.db.get_purchase(pid)
        self.items = []
        self.refresh_items()
        self.refresh_list()
        self.ref_e.delete(0, "end")
        messagebox.showinfo(
            "Purchase",
            f"Purchase #{pid} saved \u2014 {money(pur['grand_total'])}.\n"
            f"Stock updated for {len(self.db.purchase_items(pid))} item(s).")

    def refresh_list(self):
        for r in self.tv2.get_children():
            self.tv2.delete(r)
        for p in self.db.list_purchases():
            n = len(self.db.purchase_items(p["id"]))
            self.tv2.insert("", "end", iid=p["id"], values=(
                p["id"], p["date"], p["supplier_name"] or "-",
                p["ref_no"] or "-", n, money(p["grand_total"])))

    def _selected_purchase(self):
        sel = self.tv2.selection()
        if not sel:
            messagebox.showinfo("Purchases", "Select a purchase first.")
            return None
        return int(sel[0])

    def view_purchase(self):
        pid = self._selected_purchase()
        if pid is None:
            return
        p = self.db.get_purchase(pid)
        win = ctk.CTkToplevel(self)
        win.title(f"Purchase #{pid}")
        win.geometry("560x440")
        win.transient(self)
        ctk.CTkLabel(
            win,
            text=f"#{pid}  \u00b7  {p['date']}  \u00b7  "
                 f"{p['supplier_name'] or '-'}  \u00b7  "
                 f"Ref: {p['ref_no'] or '-'}",
            font=ctk.CTkFont(size=14, weight="bold")).pack(
                anchor="w", padx=12, pady=8)
        fr, tv = _tree(win, ("Product", "Qty", "Cost/unit", "GST%", "Expiry",
                               "Amount"),
                       widths=(190, 70, 90, 55, 100, 110), height=12)
        fr.pack(fill="both", expand=True, padx=12, pady=4)
        for it in self.db.purchase_items(pid):
            tv.insert("", "end", values=(
                it["name"], f"{it['qty']:g} {it['unit']}",
                money(it["cost"]), f"{it['gst_percent']:g}%",
                it.get("expiry_date") or "-", money(it["line_total"])))
        ctk.CTkLabel(win, text=f"Grand total: {money(p['grand_total'])}",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(
                         anchor="w", padx=12, pady=8)

    def delete_purchase(self):
        pid = self._selected_purchase()
        if pid is None:
            return
        p = self.db.get_purchase(pid)
        if not messagebox.askyesno(
                "Delete purchase",
                f"Delete purchase #{pid} ({money(p['grand_total'])})?\n\n"
                "The stock added by this purchase will be reversed."):
            return
        self.db.delete_purchase(pid)
        self.refresh_list()
        messagebox.showinfo("Purchases", f"Purchase #{pid} deleted; "
                                        "stock reversed.")
