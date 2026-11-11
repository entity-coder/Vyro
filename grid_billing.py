"""Vyro - grid_billing.py
Marg-ERP-style sale-entry product grid for the Billing screen.

Columns: DESCRIPTION | PACKING | STOCK | UNIT | RATE, a "Find Name ? >>"
type-to-filter box (filters live on name and SKU, like Marg), arrow-key
navigation with Enter to pick, and an item-detail footer (PurRate, M.R.P.,
Margin %, Company) for the highlighted row.

The panel is data-only: picking a product calls the parent's on_add hook,
which reuses the existing billing flow (fill product entry -> qty -> rate ->
discount). It never touches bill state itself.
"""

from tkinter import ttk
from datetime import date

import customtkinter as ctk

RUPEE = "\u20b9"
WARN = "\u26a0"


def money(n):
    try:
        return f"{RUPEE}{float(n):,.2f}"
    except (TypeError, ValueError):
        return f"{RUPEE}0.00"


def margin_pct(p):
    cp = float(p.get("purchase_price") or 0)
    wp = float(p.get("wholesale_price") or 0)
    if cp <= 0:
        return "\u2014"
    return f"{(wp - cp) / cp * 100:.1f}%"


class GridPanel(ctk.CTkFrame):
    """Marg-style product grid + find box + detail footer."""

    COLS = ("DESCRIPTION", "PACKING", "STOCK", "UNIT", "RATE")

    def __init__(self, master, db, on_add, price_mode="wholesale",
                 on_line_select=None, on_line_edit=None):
        super().__init__(master, fg_color="transparent")
        self.db = db
        self.on_add = on_add
        self.on_line_select = on_line_select
        self.on_line_edit = on_line_edit
        self.price_mode = price_mode
        self._products = []   # full product list (dicts)
        self._shown = []      # products currently in the grid

        gframe = ctk.CTkFrame(self)
        gframe.pack(fill="both", expand=True)
        self.tv = ttk.Treeview(gframe, columns=self.COLS,
                               show="headings", height=14)
        for c, w, a in (("DESCRIPTION", 260, "w"), ("PACKING", 90, "center"),
                        ("STOCK", 130, "e"), ("UNIT", 70, "center"),
                        ("RATE", 110, "e")):
            self.tv.heading(c, text=c)
            self.tv.column(c, width=w, anchor=a)
        vsb = ttk.Scrollbar(gframe, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=vsb.set)
        self.tv.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tv.bind("<<TreeviewSelect>>", self._on_select)
        self.tv.bind("<Return>", self._pick_selected)
        self.tv.bind("<Double-1>", self._pick_selected)

        find = ctk.CTkFrame(self, fg_color="transparent")
        find.pack(fill="x", pady=(6, 2))
        ctk.CTkLabel(find, text="Find Name ? >>",
                     font=ctk.CTkFont(weight="bold")).pack(side="left",
                                                           padx=(2, 6))
        self.find_e = ctk.CTkEntry(find, width=280,
                                   placeholder_text="type product name "
                                                    "to list matches...")
        self.find_e.pack(side="left")
        self.find_e.bind("<KeyRelease>", self._on_find_key)
        ctk.CTkLabel(find, text="(type to list matches \u00b7 Enter enters "
                                "the list \u00b7 arrows move \u00b7 Enter picks)",
                     text_color="gray").pack(side="left", padx=8)

        self.detail = ctk.CTkLabel(
            self, text="", anchor="w", justify="left",
            font=ctk.CTkFont(size=12))
        self.detail.pack(fill="x", pady=(2, 0))
        self._blank_detail()

        ctk.CTkLabel(self, text="Bill lines", text_color="gray",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(
                         anchor="w", pady=(6, 0))
        lframe = ctk.CTkFrame(self)
        lframe.pack(fill="x", pady=(0, 2))
        self.LCOLS = ("ITEM", "QTY", "UNIT", "RATE", "DISC", "AMOUNT")
        self.lines_tv = ttk.Treeview(lframe, columns=self.LCOLS,
                                     show="headings", height=6)
        for c, wd, a in (("ITEM", 220, "w"), ("QTY", 70, "e"),
                         ("UNIT", 60, "center"), ("RATE", 90, "e"),
                         ("DISC", 80, "e"), ("AMOUNT", 100, "e")):
            self.lines_tv.heading(c, text=c)
            self.lines_tv.column(c, width=wd, anchor=a)
        lvsb = ttk.Scrollbar(lframe, orient="vertical",
                             command=self.lines_tv.yview)
        self.lines_tv.configure(yscrollcommand=lvsb.set)
        self.lines_tv.pack(side="left", fill="x", expand=True)
        lvsb.pack(side="right", fill="y")
        self.lines_tv.bind("<<TreeviewSelect>>", self._on_line_select)
        self.lines_tv.bind("<Double-1>", self._on_line_dbl)

    def set_lines(self, items, sel=None):
        """Rebuild the bill-lines table; reselect sel when valid."""
        tv = self.lines_tv
        for r in tv.get_children():
            tv.delete(r)
        for idx, it in enumerate(items):
            amt = (float(it.get("qty") or 0) * float(it.get("price") or 0)
                   - float(it.get("line_discount") or 0))
            tv.insert("", "end", iid=str(idx), values=(
                it.get("name") or "", f"{float(it.get('qty') or 0):g}",
                it.get("unit") or "", money(it.get("price") or 0),
                money(it.get("line_discount") or 0), money(amt)))
        if sel is not None and 0 <= sel < len(items):
            try:
                tv.selection_set(str(sel))
                tv.see(str(sel))
            except Exception:
                pass

    def _on_line_select(self, _event=None):
        if self.on_line_select is None:
            return
        sel = self.lines_tv.selection()
        if sel:
            try:
                self.on_line_select(int(sel[0]))
            except (ValueError, IndexError):
                pass

    def _on_line_dbl(self, _event=None):
        if self.on_line_edit is not None:
            self.on_line_edit()
        return "break"

    def _rate_of(self, p):
        return (p["wholesale_price"] if self.price_mode == "wholesale"
                else p["retail_price"])

    def _low(self, p):
        th = float(p.get("low_stock_threshold") or 0)
        return th > 0 and float(p.get("stock") or 0) <= th

    def _blank_detail(self):
        self.detail.configure(
            text="PurRate: \u2014      M.R.P.: \u2014      "
                 "Margin%: \u2014      Company: \u2014")

    def _update_detail(self, p):
        if not p:
            self._blank_detail()
            return
        mrp = p.get("mrp") or 0
        comp = (p.get("company") or "").strip()
        self.detail.configure(
            text=f"PurRate: {money(p.get('purchase_price') or 0)}      "
                 f"M.R.P.: {money(mrp) if mrp else '\u2014'}      "
                 f"Margin%: {margin_pct(p)}      "
                 f"Company: {comp if comp else '\u2014'}")

    def set_price_mode(self, mode):
        self.price_mode = mode
        self._render()

    def set_products(self, products):
        self._products = list(products)
        self.refresh()

    def refresh(self):
        q = self.find_e.get().strip().lower()
        if q:
            self._shown = [p for p in self._products
                           if q in (p.get("name") or "").lower()
                           or q in (p.get("sku") or "").lower()]
        else:
            self._shown = []
        self._render()

    def focus_find(self):
        self.find_e.focus_set()
        self.find_e.select_range(0, "end")

    def selected_product(self):
        sel = self.tv.selection()
        if not sel:
            return None
        pid = sel[0]
        for p in self._shown:
            if str(p["id"]) == pid:
                return p
        return None

    def _render(self):
        tv = self.tv
        for r in tv.get_children():
            tv.delete(r)
        for p in self._shown:
            pack = int(p.get("pack_size") or 1)
            stock = float(p.get("stock") or 0)
            stock_txt = (f"{WARN} {stock:g}" if self._low(p)
                         else f"{stock:g}")
            tv.insert("", "end", iid=str(p["id"]), values=(
                p.get("name") or "", pack, stock_txt, p.get("unit") or "",
                money(self._rate_of(p))))
        if self._shown:
            first = str(self._shown[0]["id"])
            tv.selection_set(first)
            tv.focus(first)
            tv.see(first)
            self._update_detail(self._shown[0])
        else:
            self._blank_detail()

    def _on_select(self, _event=None):
        self._update_detail(self.selected_product())

    def _pick_selected(self, _event=None):
        p = self.selected_product()
        if p is None and self._shown:
            p = self._shown[0]
        if p:
            self.on_add(p)
        return "break"

    def _on_find_key(self, event):
        if event.keysym == "Down":
            if self._shown:
                self.tv.focus_set()
            return "break"
        if event.keysym == "Return":
            if self._shown:
                self.tv.focus_set()
            return "break"
        if event.keysym == "Escape":
            self.find_e.delete(0, "end")
            self.refresh()
            return "break"
        if event.keysym in ("Up", "Shift_L", "Shift_R", "Control_L",
                            "Control_R", "Alt_L", "Alt_R", "Caps_Lock",
                            "Tab", "ISO_Left_Tab"):
            return
        self.refresh()


# -- wiring helpers for BillingFrame (kept here to keep ui.py small) --------

def install_header(billing):
    """Grid | Cards toggle row under the Billing heading."""
    import customtkinter as ctk
    hdr = ctk.CTkFrame(billing, fg_color="transparent")
    hdr.pack(fill="x", pady=(0, 4))
    ctk.CTkLabel(hdr, text="Product picker",
                 text_color="gray").pack(side="left", padx=(2, 6))
    billing.view_var = ctk.StringVar(
        value="Grid" if billing.db.get_setting("billing_view",
                                               "grid") == "grid" else "Cards")
    ctk.CTkSegmentedButton(hdr, values=["Grid", "Cards"],
                           variable=billing.view_var,
                           command=billing.set_bill_view).pack(side="left")
    ctk.CTkLabel(hdr, text="(Ctrl+G toggles)",
                 text_color="gray",
                 font=ctk.CTkFont(size=11)).pack(side="left", padx=6)

def build_panel(frame, billing, tab, w):
    """Create the GridPanel for a billing tab and stash it in w."""
    panel = GridPanel(
        frame, billing.db,
        on_add=lambda p: billing._suggest_pick(tab, w, p),
        price_mode=tab.price_mode,
        on_line_select=lambda i: billing._select_line(tab, w, i),
        on_line_edit=lambda: billing.edit_line(tab, w))
    w["grid_panel"] = panel
    view = billing.db.get_setting("billing_view", "grid")
    w["bill_view"] = view if view in ("grid", "cards") else "grid"


def boxes_qty(w, p):
    """Pieces from the Boxes entry (grid view); None when not applicable."""
    if (w.get("bill_view") or "grid") != "grid":
        return None
    be = w.get("boxes_e")
    if be is None:
        return None
    try:
        boxes = float(be.get().strip() or 0)
    except ValueError:
        return None
    if boxes <= 0:
        return None
    return boxes * (int((p or {}).get("pack_size") or 1) or 1)


def focus_picker(w):
    """Focus the product picker for the current view."""
    gp = w.get("grid_panel")
    if (w.get("bill_view") or "grid") == "grid" and gp is not None:
        gp.focus_find()
    else:
        w["prod_e"].focus_set()


def escape_in_find(app, w):
    """True when Escape was pressed inside the grid find box."""
    gp = w.get("grid_panel")
    if (w.get("bill_view") or "grid") != "grid" or gp is None:
        return False
    try:
        foc = app.focus_get()
        if foc is None:
            return False
        fp, ff = str(foc), str(gp.find_e)
        # CTkEntry wraps a real tk Entry child (find_e.!entry) which
        # is the widget that actually holds keyboard focus.
        return foc == gp.find_e or fp == ff or fp.startswith(ff + ".")
    except Exception:
        return False


def apply_view(billing, tab, w):
    gp = w.get("grid_panel")
    is_grid = (w.get("bill_view") or "grid") == "grid"
    bl, be = w.get("boxes_lbl"), w.get("boxes_e")
    if is_grid:
        w["cards_sf"].pack_forget()
        if bl is not None and be is not None:
            bl.pack(side="left", padx=(6, 2), after=w.get("qty_e"))
            be.pack(side="left", padx=4, after=bl)
        if gp is not None:
            gp.set_price_mode(tab.price_mode)
            gp.set_products(billing.db.list_products(""))
            gp.set_lines(tab.items, w.get("card_sel"))
            gp.pack(fill="both", expand=True, pady=6)
    else:
        if gp is not None:
            gp.pack_forget()
        if bl is not None:
            bl.pack_forget()
        if be is not None:
            be.pack_forget()
        w["cards_sf"].pack(fill="both", expand=True, pady=6)


def set_view(billing, value):
    cur = billing.current()
    if not cur:
        return
    tab, w = cur
    w["bill_view"] = "grid" if value == "Grid" else "cards"
    billing.db.set_setting("billing_view", w["bill_view"])
    apply_view(billing, tab, w)


def toggle_view(billing):
    cur = billing.current()
    if not cur:
        return
    tab, w = cur
    new = "cards" if (w.get("bill_view") or "grid") == "grid" else "grid"
    try:
        billing.view_var.set("Grid" if new == "grid" else "Cards")
    except Exception:
        pass
    set_view(billing, "Grid" if new == "grid" else "Cards")


def sync_view_var(billing):
    cur = billing.current()
    if cur:
        v = cur[1].get("bill_view") or "grid"
        try:
            billing.view_var.set("Grid" if v == "grid" else "Cards")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Billing tab chrome helpers.
#
# These build/refresh small pieces of the billing tab (compact bill header,
# Boxes entry, Last Bills strip) and live here — not in ui.py — so the main
# UI module stays under the push size limit. Behavior is unchanged from the
# previous inline code.
# ---------------------------------------------------------------------------

def bill_no_preview(db, tab):
    """Next bill number for the header (peek — no counter side effects)."""
    if tab.edit_bill_id:
        try:
            b = db.get_bill(tab.edit_bill_id)
            return b["bill_no"] if b else ""
        except Exception:
            return ""
    try:
        n = int(db.get_setting("bill_counter", "1") or 1)
    except ValueError:
        n = 1
    prefix = db.get_setting("invoice_number_prefix", "BB-") or "BB-"
    return f"{prefix}{n:04d}"


def build_bill_head(r1, db, tab, f_muted):
    """Compact 'Bill No. <next> · Date <today>' labels for the header row."""
    ctk.CTkLabel(r1, text="Bill No.", text_color="gray",
                 font=f_muted).pack(side="left", padx=(10, 2))
    ctk.CTkLabel(r1, text=bill_no_preview(db, tab),
                 font=ctk.CTkFont(weight="bold")).pack(side="left", padx=2)
    ctk.CTkLabel(r1, text="Date", text_color="gray",
                 font=f_muted).pack(side="left", padx=(10, 2))
    ctk.CTkLabel(r1, text=date.today().strftime("%d-%m-%Y"),
                 font=f_muted).pack(side="left", padx=2)


def build_boxes_entry(r2, on_return):
    """Boxes entry for wholesale billing (grid view only).

    Returns (label, entry); the view switch packs/pack_forgets them.
    on_return() runs on <Return>.
    """
    lbl = ctk.CTkLabel(r2, text="Boxes")
    lbl.pack(side="left", padx=(6, 2))
    e = ctk.CTkEntry(r2, width=60, placeholder_text="boxes")
    e.pack(side="left", padx=4)
    e.bind("<Return>", lambda ev: on_return())
    return lbl, e


def build_last_bills_strip(frame, w, f_muted):
    """'Last Bills :' strip under the totals row; refresh fills the chips."""
    fr = ctk.CTkFrame(frame, fg_color="transparent")
    fr.pack(fill="x", pady=(0, 2))
    ctk.CTkLabel(fr, text="Last Bills :", text_color="gray",
                 font=f_muted).pack(side="left", padx=(4, 6))
    box = ctk.CTkFrame(fr, fg_color="transparent")
    box.pack(side="left", fill="x", expand=True)
    w["last_bills_box"] = box


def refresh_last_bills(billing, w):
    """Rebuild the Last Bills strip: 5 most recent bills, clickable chips."""
    box = w.get("last_bills_box")
    if box is None:
        return
    for ch in box.winfo_children():
        ch.destroy()
    try:
        bills = billing.db.list_bills(limit=5)
    except Exception:
        bills = []
    for b in bills:
        cname = (b.get("customer_name") or "Walk-in").strip() or "Walk-in"
        txt = f"{cname}:{b['bill_no']}:{money(b['grand_total'])}"
        ctk.CTkButton(
            box, text=txt, anchor="w", height=24, fg_color="transparent",
            text_color=("black", "white"),
            hover_color=("gray80", "gray25"),
            command=lambda bid=b["id"]: view_last_bill(billing, bid)).pack(
                side="left", padx=4)


def view_last_bill(billing, bill_id):
    """Open a Last-Bills chip: invoice preview + print (same as Reprint)."""
    from print_ui import PrintDialog  # lazy: avoids any import cycle
    db = billing.db
    bill = db.get_bill(bill_id)
    if not bill:
        return
    items = db.bill_items(bill_id)
    for it in items:
        p = db.get_product(it["product_id"]) if it.get("product_id") else None
        it["sku"] = (p or {}).get("sku", "")
    PrintDialog(billing, db, bill, items)
