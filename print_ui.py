"""
Vyro — print_ui.py
Print offer dialog, print settings dialog, invoice live preview,
and the accent palette. Extracted from ui.py so the main UI module
stays under the push size limit.
"""

import customtkinter as ctk
from tkinter import messagebox

import invoices
import printing

RUPEE = "\u20b9"


def money(n):
    try:
        return f"{RUPEE}{float(n):,.2f}"
    except (TypeError, ValueError):
        return f"{RUPEE}0.00"


class PrintOfferDialog(ctk.CTkToplevel):

    def __init__(self, app, billing, db, bill_id, msg):
        super().__init__(app)
        self.db = db
        self.bill_id = bill_id
        self.billing = billing           # BillingFrame — has _do_saved_bill_print
        self.title("Bill saved")
        self.geometry("360x260")
        self.transient(app)
        self.grab_set()

        ctk.CTkLabel(self, text=msg, wraplength=320,
                     font=ctk.CTkFont(size=14)).pack(pady=(16, 6))
        self.remember = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self, text="Remember my choice",
                        variable=self.remember).pack(pady=6)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(pady=10)
        ctk.CTkButton(btns, text="Print", fg_color="#1f6f43",
                      hover_color="#175733",
                      command=lambda: self.done("print")).pack(
                          side="left", padx=6)
        ctk.CTkButton(btns, text="Preview",
                      command=lambda: self.done("preview")).pack(
                          side="left", padx=6)
        ctk.CTkButton(btns, text="Skip", fg_color="gray",
                      command=lambda: self.done("skip")).pack(
                          side="left", padx=6)

    def done(self, choice):
        if self.remember.get():
            self.db.set_setting("print_on_save", choice)
        self.destroy()
        if choice == "print":
            self.billing._do_saved_bill_print(self.bill_id, preview=False)
        elif choice == "preview":
            self.billing._do_saved_bill_print(self.bill_id, preview=True)


ACCENTS = {"Green": "#1f6f43", "Blue": "#0b5fa5", "Maroon": "#8f1d17",
           "Orange": "#b26a00", "Purple": "#5b2d8e", "Black": "#222222"}


def render_invoice_preview(container, prof, bill, items, prefs):
    for ch in container.winfo_children():
        ch.destroy()
    accent = prefs.get("accent", "#1f6f43") or "#1f6f43"
    fg = "black"
    narrow = prefs.get("paper") == "thermal"

    head = ctk.CTkFrame(container, fg_color="white")
    head.pack(fill="x", pady=4)
    logo_path = prefs.get("logo_path") or ""
    if logo_path:
        try:
            from PIL import Image
            img = Image.open(logo_path)
            img.thumbnail((90, 60))
            photo = ctk.CTkImage(light_image=img, dark_image=img,
                                 size=img.size)
            lbl = ctk.CTkLabel(head, image=photo, text="", fg_color="white")
            lbl.pack()
            container._logo_img = photo  # keep a reference (no GC)
        except Exception:
            pass
    ctk.CTkLabel(head, text=prof.get("shop_name") or "Your Shop Name",
                 text_color=accent, fg_color="white",
                 font=ctk.CTkFont(size=18 if not narrow else 13,
                                   weight="bold")).pack()
    if prefs.get("show_tagline", True) and prof.get("shop_tagline"):
        ctk.CTkLabel(head, text=prof["shop_tagline"], text_color="gray",
                     fg_color="white", font=ctk.CTkFont(size=11)).pack()
    if prefs.get("show_address", True) and prof.get("shop_address"):
        ctk.CTkLabel(head, text=prof["shop_address"], text_color="gray",
                     fg_color="white", font=ctk.CTkFont(size=11)).pack()
    if prefs.get("show_phone", True) and prof.get("shop_phone"):
        ctk.CTkLabel(head, text=f"Phone: {prof['shop_phone']}",
                     text_color="gray", fg_color="white",
                     font=ctk.CTkFont(size=11)).pack()
    if prefs.get("show_gstin") and prof.get("shop_gstin"):
        ctk.CTkLabel(head, text=f"GSTIN: {prof['shop_gstin']}",
                     text_color="gray", fg_color="white",
                     font=ctk.CTkFont(size=11)).pack()
    if prefs.get("header_note"):
        ctk.CTkLabel(head, text=prefs["header_note"], text_color=fg,
                     fg_color="white", font=ctk.CTkFont(size=11)).pack()
    ctk.CTkFrame(container, height=3, fg_color=accent).pack(fill="x",
                                                           pady=4)
    ctk.CTkLabel(container,
                 text=prefs.get("invoice_title") or "TAX INVOICE",
                 text_color=accent, fg_color="white",
                 font=ctk.CTkFont(size=14 if not narrow else 12,
                                   weight="bold")).pack()

    b = bill
    ctk.CTkLabel(container,
                 text=f"Bill {b['bill_no']}  \u00b7  {b['date']}  \u00b7  "
                      f"{b.get('payment_type', '')}"
                      + ("  \u00b7  CREDIT \u2014 due"
                         if prefs.get("show_payment_badge", True)
                         and b.get("payment_type") == "Credit" else ""),
                 text_color=fg, fg_color="white",
                 font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
    cust_line = f"Customer: {b.get('customer_name') or 'Walk-in'}"
    if prefs.get("show_customer_address", True) and b.get("customer_address"):
        cust_line += f"  \u00b7  {b['customer_address']}"
    ctk.CTkLabel(container, text=cust_line,
                 text_color=fg, fg_color="white",
                 font=ctk.CTkFont(size=12)).pack(anchor="w")

    cols = ["Item", "Qty", "Rate"]
    if prefs.get("show_discounts"):
        cols.append("Disc.")
    cols += ["GST", "Amount"]
    grid = ctk.CTkFrame(container, fg_color="white")
    grid.pack(fill="x", pady=6)
    for j, c in enumerate(cols):
        ctk.CTkLabel(grid, text=c, text_color="white", fg_color=accent,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(
                         row=0, column=j, sticky="ew", padx=1)
        grid.grid_columnconfigure(j, weight=1)
    for i, it in enumerate(items, 1):
        vals = [it["name"] + (f"\n{it.get('sku', '')}"
                              if prefs.get("show_item_codes")
                              and it.get("sku") else ""),
                f"{it['qty']:g}", f"{money(it['price'])}"]
        if prefs.get("show_discounts"):
            vals.append(money(it.get("line_discount", 0))
                        if it.get("line_discount") else "\u2014")
        taxable = max(it["qty"] * it["price"]
                      - it.get("line_discount", 0), 0)
        vals += [f"{it.get('gst_percent', 0):g}%",
                 money(taxable * (1 + it.get("gst_percent", 0) / 100))]
        for j, v in enumerate(vals):
            ctk.CTkLabel(grid, text=v, text_color=fg, fg_color="white",
                         font=ctk.CTkFont(size=11)).grid(
                             row=i, column=j, sticky="w", padx=2, pady=2)

    if prefs.get("show_gst_table", True):
        ctk.CTkLabel(container, text="(GST slab breakup table \u2014 on the PDF)",
                     text_color="gray", fg_color="white",
                     font=ctk.CTkFont(size=10, slant="italic")).pack(anchor="w")

    tot = ctk.CTkFrame(container, fg_color="white")
    tot.pack(fill="x", pady=6)
    rows = [("Subtotal", money(b["subtotal"])),
            ("GST", money(b["gst_total"]))]
    if prefs.get("show_discounts") and float(b.get("discount", 0) or 0):
        rows.append(("Discount", money(b["discount"])))
    if prefs.get("show_roundoff", True):
        rows.append(("Round off", money(b["round_off"])))
    for label, val in rows:
        r = ctk.CTkFrame(tot, fg_color="white")
        r.pack(fill="x")
        ctk.CTkLabel(r, text=label, text_color=fg,
                     fg_color="white").pack(side="left")
        ctk.CTkLabel(r, text=val, text_color=fg,
                     fg_color="white").pack(side="right")
    r = ctk.CTkFrame(tot, fg_color="white")
    r.pack(fill="x", pady=(4, 0))
    ctk.CTkLabel(r, text="Grand Total", text_color=accent, fg_color="white",
                 font=ctk.CTkFont(size=15, weight="bold")).pack(side="left")
    ctk.CTkLabel(r, text=money(b["grand_total"]), text_color=accent,
                 fg_color="white",
                 font=ctk.CTkFont(size=15, weight="bold")).pack(side="right")
    if prefs.get("footer_note"):
        ctk.CTkLabel(container, text=prefs["footer_note"],
                     text_color="gray", fg_color="white",
                     font=ctk.CTkFont(size=11)).pack(pady=(8, 0))
    if prefs.get("show_thankyou", True):
        ctk.CTkLabel(container,
                     text=prefs.get("thankyou_text")
                     or "Thank you for your business!",
                     text_color=accent, fg_color="white",
                     font=ctk.CTkFont(size=11, weight="bold")).pack(pady=(2, 8))
    if prefs.get("show_signature", True) and not narrow:
        sig = ctk.CTkFrame(container, fg_color="white")
        sig.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(sig, text="Customer signature", text_color="gray",
                     fg_color="white").pack(side="left")
        ctk.CTkLabel(sig, text=f"For {prof.get('shop_name') or 'Shop'}",
                     text_color="gray", fg_color="white").pack(side="right")


class PrintDialog(ctk.CTkToplevel):

    def __init__(self, master, db, bill, items):
        super().__init__(master)
        self.db = db
        self.bill = bill
        self.items = items
        self.bill_id = bill.get("id") if isinstance(bill, dict) else None
        prefs = db.print_prefs()
        self.title(f"Print {bill['bill_no']}")
        self.geometry("980x700")
        self.transient(master)
        self.grab_set()

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        left = ctk.CTkScrollableFrame(self, width=300)
        left.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        ctk.CTkLabel(left, text="Print settings",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(
                         anchor="w", pady=(4, 8))

        self.vars = {}
        for key, label in (("show_gstin", "Show shop GSTIN"),
                           ("show_item_codes", "Show item codes / SKU"),
                           ("show_discounts", "Show discount column")):
            v = ctk.BooleanVar(value=prefs[key])
            ctk.CTkCheckBox(left, text=label, variable=v,
                            command=self.render_preview).pack(
                                anchor="w", pady=4, padx=4)
            self.vars[key] = v

        ctk.CTkLabel(left, text="Printer").pack(anchor="w", pady=(10, 2),
                                                padx=4)
        self.printer_list = printing.list_printers()
        self.printer_default = printing.get_default_printer()
        saved = db.get_setting("print_printer") or ""
        values = ["(OS default)"] + self.printer_list
        if saved and saved in self.printer_list:
            sel = saved
        elif self.printer_default and self.printer_default in self.printer_list:
            sel = self.printer_default
        else:
            sel = "(OS default)"
        self.printer_var = ctk.StringVar(value=sel)
        if self.printer_list:
            ctk.CTkOptionMenu(left, values=values,
                              variable=self.printer_var).pack(fill="x", padx=4)
        else:
            ctk.CTkLabel(left, text="No printers found \u2014 use Preview PDF",
                         text_color="gray").pack(anchor="w", padx=4)

        ctk.CTkLabel(left, text="Copies").pack(anchor="w", pady=(8, 2), padx=4)
        self.copies_e = ctk.CTkEntry(left, width=80)
        self.copies_e.insert(0, db.get_setting("print_copies", "1") or "1")
        self.copies_e.pack(anchor="w", padx=4)

        ctk.CTkLabel(left, text="Accent color").pack(anchor="w", pady=(10, 2),
                                                    padx=4)
        inv = {v: k for k, v in ACCENTS.items()}
        self.accent_var = ctk.StringVar(
            value=inv.get(prefs["accent"], "Green"))
        ctk.CTkOptionMenu(left, values=list(ACCENTS.keys()),
                          variable=self.accent_var,
                          command=lambda v: self.render_preview()).pack(
                              fill="x", padx=4)

        ctk.CTkLabel(left, text="Paper size").pack(anchor="w", pady=(10, 2),
                                                  padx=4)
        self.paper_var = ctk.StringVar(
            value="Thermal 80mm" if prefs["paper"] == "thermal" else "A4")
        ctk.CTkSegmentedButton(left, values=["A4", "Thermal 80mm"],
                               variable=self.paper_var,
                               command=lambda v: self.render_preview()).pack(
                                   fill="x", padx=4)

        ctk.CTkLabel(left, text="Header note").pack(anchor="w", pady=(10, 2),
                                                   padx=4)
        self.header_e = ctk.CTkEntry(left)
        self.header_e.insert(0, prefs["header_note"])
        self.header_e.pack(fill="x", padx=4)
        self.header_e.bind("<KeyRelease>", lambda e: self.render_preview())
        ctk.CTkLabel(left, text="Footer note").pack(anchor="w", pady=(8, 2),
                                                   padx=4)
        self.footer_e = ctk.CTkEntry(left)
        self.footer_e.insert(0, prefs["footer_note"])
        self.footer_e.pack(fill="x", padx=4)
        self.footer_e.bind("<KeyRelease>", lambda e: self.render_preview())

        ctk.CTkButton(left, text="Save as defaults",
                      command=self.save_defaults).pack(fill="x", padx=4,
                                                       pady=(14, 4))
        ctk.CTkButton(left, text="Print invoice (Ctrl+P)",
                      fg_color="#1f6f43", hover_color="#175733",
                      command=self.do_print).pack(fill="x", padx=4, pady=4)
        ctk.CTkButton(left, text="Preview PDF",
                      command=self.do_preview).pack(fill="x", padx=4, pady=4)

        right = ctk.CTkFrame(self)
        right.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
        ctk.CTkLabel(right, text="Live preview",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(
                         anchor="w", padx=10, pady=(8, 2))
        self.preview = ctk.CTkScrollableFrame(right, fg_color="white")
        self.preview.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.bind("<Control-p>", lambda e: self.do_print())
        self.render_preview()

    def current_prefs(self):
        return {
            "accent": ACCENTS[self.accent_var.get()],
            "paper": "thermal" if self.paper_var.get() == "Thermal 80mm"
                     else "A4",
            "show_gstin": self.vars["show_gstin"].get(),
            "show_item_codes": self.vars["show_item_codes"].get(),
            "show_discounts": self.vars["show_discounts"].get(),
            "header_note": self.header_e.get(),
            "footer_note": self.footer_e.get(),
        }

    def effective_prefs(self):
        prefs = self.db.print_prefs()
        prefs.update(self.current_prefs())
        return prefs

    def render_preview(self):
        render_invoice_preview(self.preview, self.db.shop_profile(),
                               self.bill, self.items, self.effective_prefs())

    def save_defaults(self):
        p = self.current_prefs()
        self.db.set_setting("print_accent", p["accent"])
        self.db.set_setting("print_paper", p["paper"])
        for k in ("show_gstin", "show_item_codes", "show_discounts"):
            self.db.set_setting(f"print_{k}", "1" if p[k] else "0")
        self.db.set_setting("print_header_note", p["header_note"])
        self.db.set_setting("print_footer_note", p["footer_note"])
        self.db.set_setting("print_printer", self._printer_choice() or "")
        self.db.set_setting("print_copies", self._copies())
        messagebox.showinfo("Print", "Print defaults saved.")

    def _printer_choice(self):
        v = self.printer_var.get()
        return None if v == "(OS default)" else v

    def _copies(self):
        try:
            return str(max(int(self.copies_e.get() or 1), 1))
        except ValueError:
            return "1"

    def do_preview(self):
        p = self.effective_prefs()
        try:
            path = invoices.write_invoice_pdf(
                self.bill, self.items, self.db.shop_profile(), p)
            if self.bill_id:
                self.db.log_bill_action(
                    self.bill_id, "reprinted",
                    f"Invoice preview opened: {path.name}")
            printing.open_pdf(path)
        except Exception as e:
            messagebox.showerror("Print", f"Could not build the invoice: {e}")

    def _print_failed_dialog(self, path, text):
        """Show a print failure WITHOUT auto-opening the PDF.

        The user reads the reason + saved path and chooses: open the PDF
        manually, or just close. Nothing opens on its own.
        """
        win = ctk.CTkToplevel(self)
        win.title("Print failed")
        win.geometry("480x260")
        win.transient(self)
        ctk.CTkLabel(win, text="Could not print directly.",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
                         pady=(14, 4))
        ctk.CTkLabel(win, text=text, wraplength=440,
                     justify="left").pack(padx=14, pady=4)
        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(pady=10)
        ctk.CTkButton(btns, text="Open PDF",
                      command=lambda: printing.open_pdf(path)).pack(
                          side="left", padx=6)
        ctk.CTkButton(btns, text="Close", fg_color="transparent",
                      command=win.destroy).pack(side="left", padx=6)

    def do_print(self):
        p = self.effective_prefs()
        printer = self._printer_choice()
        copies = int(self._copies())
        try:
            if self.bill_id:
                path, printed, msg = invoices.print_bill(
                    self.bill_id, printer=printer, copies=copies)
                if printed:
                    messagebox.showinfo("Print", msg)
                    self.destroy()
                else:
                    # msg already carries reason + saved path + fix hint.
                    self._print_failed_dialog(path, msg)
            else:
                from printing import generate_invoice_pdf, print_pdf
                path = generate_invoice_pdf(self.bill, self.items,
                                            self.db.shop_profile(), p)
                ok, msg = print_pdf(path, printer=printer, copies=copies)
                if ok:
                    messagebox.showinfo("Print", msg)
                    self.destroy()
                else:
                    self._print_failed_dialog(path, msg)
        except Exception as e:
            messagebox.showerror("Print", f"Could not print: {e}")


# Sample bill + items for the invoice-design live preview.
# Moved here from ui.py (Round 25) to keep ui.py under the push
# size limit; the preview in InvoiceDesignFrame uses these.
DESIGN_SAMPLE_BILL = {
    "bill_no": "BB-0001", "date": "16-10-2026",
    "customer_name": "Sample Customer", "customer_phone": "98765 43210",
    "customer_address": "Main Bazaar, Chikhli",
    "payment_type": "Credit", "subtotal": 4350.00, "discount": 100.00,
    "gst_total": 212.50, "round_off": 0.50, "grand_total": 4463.00,
}
DESIGN_SAMPLE_ITEMS = [
    {"name": "Wheat Flour 5kg", "sku": "WF5", "qty": 10, "unit": "bag",
     "price": 240.00, "line_discount": 100.00, "gst_percent": 5},
    {"name": "Sugar 1kg", "sku": "SG1", "qty": 20, "unit": "kg",
     "price": 45.00, "line_discount": 0, "gst_percent": 5},
    {"name": "Basmati Rice 25kg", "sku": "BR25", "qty": 2, "unit": "bag",
     "price": 1450.00, "line_discount": 0, "gst_percent": 0},
]
