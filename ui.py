"""
BillBook — ui.py
All CustomTkinter screens: dashboard, product catalog, stock, multi-tab billing,
customer ledger, invoices, reports, backup/restore, settings.
"""

import csv
import os
import shutil
import tempfile
import threading
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from tkinter import ttk

import invoices
import printing
import grid_billing
from backup import BackupFrame, auto_backup_on_exit
from db import data_dir
from print_ui import ACCENTS, PrintDialog, PrintOfferDialog, render_invoice_preview

RUPEE = "\u20b9"


def money(n):
    try:
        return f"{RUPEE}{float(n):,.2f}"
    except (TypeError, ValueError):
        return f"{RUPEE}0.00"


def today_iso():
    return date.today().isoformat()


def fnum(widget, default=0.0):
    try:
        return float(widget.get().strip() or default)
    except ValueError:
        return default


def tree(parent, columns, widths=None, height=12):
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


class SearchPicker(ctk.CTkToplevel):

    def __init__(self, master, title, fetch_fn, display_fn, on_pick):
        super().__init__(master)
        self.title(title)
        self.geometry("460x420")
        self.fetch_fn = fetch_fn
        self.display_fn = display_fn
        self.on_pick = on_pick
        self.transient(master)
        self.grab_set()

        self.entry = ctk.CTkEntry(self, placeholder_text="Type to search...")
        self.entry.pack(fill="x", padx=12, pady=(12, 6))
        self.entry.bind("<KeyRelease>", lambda e: self.refresh())
        self.entry.bind("<Return>", lambda e: self.choose())
        self.listbox = ctk.CTkScrollableFrame(self)
        self.listbox.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.entry.focus()
        self.refresh()
        self.bind("<Escape>", lambda e: self.destroy())

    def refresh(self):
        q = self.entry.get().strip()
        for w in self.listbox.winfo_children():
            w.destroy()
        for row in self.fetch_fn(q)[:60]:
            b = ctk.CTkButton(self.listbox, text=self.display_fn(row),
                              anchor="w", fg_color="transparent",
                              text_color=("black", "white"),
                              hover_color=("gray75", "gray25"),
                              command=lambda r=row: self.pick(r))
            b.pack(fill="x", pady=1)

    def pick(self, row):
        self.destroy()
        self.on_pick(row)

    def choose(self):
        rows = self.fetch_fn(self.entry.get().strip())[:1]
        if rows:
            self.pick(rows[0])


NAV = [
    ("Dashboard", "dashboard"),
    ("Billing", "billing"),
    ("Products", "products"),
    ("Purchases", "purchases"),
    ("Stock", "stock"),
    ("Re-Order", "reorder"),
    ("Customers", "customers"),
    ("Suppliers", "suppliers"),
    ("Cash Book", "cashbook"),
    ("Challans", "challans"),
    ("Aging", "aging"),
    ("Invoices", "invoices"),
    ("Reports", "reports"),
    ("Invoice Design", "invoice_design"),
    ("Backup", "backup"),
    ("Settings", "settings"),
]


class App(ctk.CTk):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.title("BillBook \u2014 Wholesale Billing")
        self.geometry("1280x800")
        self.minsize(1080, 680)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=190, corner_radius=0)
        self.sidebar.grid(row=0, column=1, sticky="nsew")
        ctk.CTkLabel(self.sidebar, text="BillBook",
                     font=ctk.CTkFont(size=24, weight="bold")).pack(
                         pady=(18, 2), padx=12)
        prof = db.shop_profile()
        ctk.CTkLabel(self.sidebar,
                     text=prof.get("shop_name") or "Wholesale Billing",
                     text_color="gray").pack(pady=(0, 14), padx=12)

        self.nav_buttons = {}
        for label, key in NAV:
            b = ctk.CTkButton(self.sidebar, text=label, anchor="w",
                              fg_color="transparent",
                              command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=10, pady=2)
            self.nav_buttons[key] = b

        self.theme_var = ctk.StringVar(
            value="Dark" if db.get_setting("theme") == "dark" else "Light")
        self._theme_lbl = ctk.CTkLabel(self.sidebar, text="Theme")
        self._theme_lbl.pack(pady=(16, 0))
        ctk.CTkSegmentedButton(self.sidebar, values=["Dark", "Light"],
                               variable=self.theme_var,
                               command=self.switch_theme).pack(
                                   padx=10, pady=6, fill="x")

        self.update_btn = ctk.CTkButton(
            self.sidebar, text="\u2b06 Update available",
            fg_color="#0b5fa5", hover_color="#084a82",
            command=self._on_update_clicked)

        from nav_travel import install_nav_travel
        install_nav_travel(self)

        self.content = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.content.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.screens = {}
        self.show("dashboard")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._update_sha = None
        self._update_checking = False
        self.after(2500, self._start_update_check)

    def _start_update_check(self):
        if self._update_checking:
            return
        self._update_checking = True
        threading.Thread(target=self._bg_update_check, daemon=True).start()

    def _bg_update_check(self):
        try:
            import updater
            status, sha = updater.check_update()
        except Exception:
            status, sha = "offline", None
        try:
            self.after(0, lambda: self._on_update_checked(status, sha))
        except Exception:
            pass

    def _on_update_checked(self, status, sha):
        self._update_checking = False
        if status == "available" and sha:
            self._update_sha = sha
            try:
                self.update_btn.pack(fill="x", padx=10, pady=6,
                                     before=self._theme_lbl)
            except Exception:
                self.update_btn.pack(fill="x", padx=10, pady=6)

    def _on_update_clicked(self):
        sha = self._update_sha
        if not sha:
            return
        if not messagebox.askyesno(
                "Update BillBook",
                "A new version of BillBook is available.\n\n"
                "The update downloads the latest version, rebuilds the app "
                "(takes a few minutes) and restarts it automatically.\n"
                "Your bills, products and backups are never touched.\n\n"
                "Update now?"):
            return
        dlg = ctk.CTkToplevel(self)
        dlg.title("Updating BillBook")
        dlg.geometry("380x140")
        dlg.transient(self)
        dlg.grab_set()
        ctk.CTkLabel(dlg, text="Downloading update...",
                     font=ctk.CTkFont(weight="bold")).pack(pady=(18, 8))
        bar = ctk.CTkProgressBar(dlg, width=300)
        bar.pack(pady=6)
        bar.set(0)
        status_lbl = ctk.CTkLabel(dlg, text="", text_color="gray")
        status_lbl.pack(pady=4)

        def progress(frac):
            self.after(0, lambda: bar.set(frac))

        def work():
            try:
                import updater
                updater.download_and_stage(sha, progress=progress)
                bat = updater.write_apply_bat()
            except Exception as e:  # noqa: BLE001
                self.after(0, lambda: (dlg.destroy(),
                                       messagebox.showerror(
                                           "Update",
                                           f"Update failed:\n{e}\n\n"
                                           "Nothing was changed.")))
                return
            self.after(0, lambda: self._finish_update(dlg, bat, sha))

        threading.Thread(target=work, daemon=True).start()

    def _finish_update(self, dlg, bat, sha):
        import updater
        try:
            dlg.destroy()
        except Exception:
            pass
        messagebox.showinfo(
            "Update",
            "Download complete.\n\nBillBook will now close, apply the update "
            "and restart itself.")
        updater.launch_apply_and_quit(bat, os.getpid(), sha, self.on_close)

    def switch_theme(self, value):
        mode = "dark" if value == "Dark" else "light"
        ctk.set_appearance_mode(mode)
        self.db.set_setting("theme", mode)
        self.show(self.current)

    def show(self, key):
        self.current = key
        for w in self.content.winfo_children():
            w.destroy()
        for k, b in self.nav_buttons.items():
            b.configure(fg_color=("gray75", "gray25") if k == key
                        else "transparent")
        if key == "purchases":
            from purchases_ui import PurchasesFrame
            screen_cls = PurchasesFrame
        elif key == "cashbook":
            from shop_ui import CashBookFrame
            screen_cls = CashBookFrame
        elif key == "challans":
            from shop_ui import ChallansFrame
            screen_cls = ChallansFrame
        elif key == "suppliers":
            from shop_ui import SuppliersFrame
            screen_cls = SuppliersFrame
        elif key == "aging":
            from shop_ui import AgingFrame
            screen_cls = AgingFrame
        elif key == "reorder":
            from shop_ui import ReOrderFrame
            screen_cls = ReOrderFrame
        else:
            screen_cls = {"dashboard": DashboardFrame, "billing": BillingFrame,
                          "products": ProductsFrame, "stock": StockFrame,
                          "customers": CustomersFrame,
                          "invoices": InvoicesFrame,
                          "reports": ReportsFrame,
                          "invoice_design": InvoiceDesignFrame,
                          "backup": BackupFrame,
                          "settings": SettingsFrame}[key]
        screen = screen_cls(self.content, self.db, self)
        screen.grid(row=0, column=0, sticky="nsew")
        self.screens[key] = screen

    def open_billing_tab(self, **kwargs):
        self.show("billing")
        self.screens["billing"].new_tab(**kwargs)

    def on_close(self):
        try:
            auto_backup_on_exit(self.db)
        except Exception:
            pass
        try:
            self.db.close()
        except Exception:
            pass
        self.destroy()


class DashboardFrame(ctk.CTkFrame):
    def __init__(self, parent, db, app):
        super().__init__(parent, fg_color="transparent")
        self.db, self.app = db, app
        ctk.CTkLabel(self, text="Dashboard",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                         anchor="w", pady=(4, 10))

        n, total = db.sales_on(today_iso())
        outstanding = db.total_outstanding()
        creditors = db.total_creditors()
        cash = db.cash_balance()
        stock_val = db.stock_value()
        low = db.low_stock_products()
        week_ago = (date.today() - timedelta(days=7)).isoformat()
        top = db.top_products(week_ago, today_iso(), limit=8)
        near_exp = db.near_expiry_products(60)
        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.pack(fill="x", pady=6)
        glance = [
                ("Bills today", str(n), "#0b5fa5"),
                ("Sales today", money(total), "#1f6f43"),
                ("Cash in hand", money(cash), "#1f6f43"),
                ("Debtors (to receive)", money(outstanding), "#b3261e"),
                ("Creditors (to pay)", money(creditors), "#b26a00"),
                ("Stock value", money(stock_val), "#0b5fa5")]
        for title, value, color in glance:
            card = ctk.CTkFrame(cards, corner_radius=10, border_width=1,
                                border_color=color)
            card.pack(side="left", fill="x", expand=True, padx=4)
            ctk.CTkLabel(card, text=title, text_color="gray",
                         font=ctk.CTkFont(size=11)).pack(
                anchor="w", padx=10, pady=(6, 0))
            ctk.CTkLabel(card, text=value,
                         font=ctk.CTkFont(size=15, weight="bold")).pack(
                             anchor="w", padx=10, pady=(0, 8))
        ctk.CTkLabel(
            self,
            text="Cash in hand = cash-book opening + IN \u2212 OUT "
                 "(non-bill cash only; bill cash stays on the bills). "
                 "Bank is not tracked separately yet.",
            text_color="gray", font=ctk.CTkFont(size=11),
            wraplength=900, justify="left").pack(anchor="w", pady=(0, 4))

        cols = ctk.CTkFrame(self, fg_color="transparent")
        cols.pack(fill="both", expand=True, pady=8)
        cols.grid_columnconfigure(0, weight=1)
        cols.grid_columnconfigure(1, weight=1)

        left = ctk.CTkFrame(cols)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ctk.CTkLabel(left, text="\u26a0 Low stock alerts",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w",
                                                           padx=10, pady=6)
        fr, tv = tree(left, ("Product", "Stock", "Threshold"),
                      widths=(220, 80, 90), height=10)
        fr.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        for p in low:
            tv.insert("", "end", values=(p["name"],
                                         f"{p['stock']:g} {p['unit']}",
                                         f"{p['low_stock_threshold']:g}"))

        right = ctk.CTkFrame(cols)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ctk.CTkLabel(right, text="Top sellers \u2014 last 7 days",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w",
                                                           padx=10, pady=6)
        fr2, tv2 = tree(right, ("Product", "Qty sold", "Amount"),
                        widths=(220, 90, 110), height=10)
        fr2.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        for t in top:
            tv2.insert("", "end", values=(t["name"], f"{t['qty']:g} {t['unit']}",
                                          money(t["total"])))

        if near_exp:
            warn = ctk.CTkFrame(self, corner_radius=10, border_width=1,
                                border_color="#b3261e")
            warn.pack(fill="x", pady=6, padx=2)
            ctk.CTkLabel(warn, text="\u26a0 Near expiry \u2014 60 days",
                         font=ctk.CTkFont(weight="bold")).pack(
                             anchor="w", padx=10, pady=(6, 0))
            fr3, tv3 = tree(warn, ("Product", "Expiry", "Stock"),
                            widths=(260, 120, 90), height=5)
            fr3.pack(fill="x", padx=10, pady=(4, 10))
            for p in near_exp[:8]:
                tag = "expired" if (p["expiry"] or "") < today_iso() else ""
                tv3.insert("", "end", values=(
                    p["name"], p["expiry"], f"{p['stock']:g} {p['unit']}"),
                    tags=(tag,) if tag else ())
            tv3.tag_configure("expired", foreground="#b3261e")

        ctk.CTkButton(self, text="New bill (F2)",
                      command=lambda: app.show("billing")).pack(
                          anchor="w", pady=6)


UNITS = ["pcs", "kg", "g", "bag", "box", "litre", "packet", "dozen"]


class ProductsFrame(ctk.CTkFrame):
    COLS = ("ID", "Name", "SKU", "Purchase", "Wholesale", "Retail", "MRP",
            "Company", "Margin%", "Pack", "Unit", "GST%", "Stock",
            "Supplier")

    @staticmethod
    def margin_pct(p):
        cp = float(p.get("purchase_price") or 0)
        wp = float(p.get("wholesale_price") or 0)
        if cp <= 0:
            return "-"
        return f"{(wp - cp) / cp * 100:.1f}%"

    def __init__(self, parent, db, app):
        super().__init__(parent, fg_color="transparent")
        self.db, self.app = db, app

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", pady=(4, 8))
        ctk.CTkLabel(top, text="Product catalog",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                         side="left")
        self.search = ctk.CTkEntry(top, placeholder_text="Search name / SKU / supplier...",
                                   width=300)
        self.search.pack(side="right", padx=6)
        self.search.bind("<KeyRelease>", lambda e: self.refresh())

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", pady=4)
        ctk.CTkButton(btns, text="Add product", command=self.add_dialog).pack(
            side="left", padx=4)
        ctk.CTkButton(btns, text="Edit selected", command=self.edit_dialog).pack(
            side="left", padx=4)
        ctk.CTkButton(btns, text="Delete selected", fg_color="#b3261e",
                      hover_color="#8f1d17", command=self.delete_selected).pack(
                          side="left", padx=4)
        ctk.CTkButton(btns, text="Import CSV", command=self.import_csv).pack(
            side="right", padx=4)
        ctk.CTkButton(btns, text="Export CSV", command=self.export_csv).pack(
            side="right", padx=4)
        ctk.CTkButton(btns, text="Barcode labels",
                      command=self.barcode_labels).pack(side="right", padx=4)

        fr, self.tv = tree(self, self.COLS,
                            widths=(40, 200, 100, 75, 75, 75, 75, 110, 65,
                                    45, 50, 50, 65, 110),
                            height=22)
        fr.pack(fill="both", expand=True, pady=6)
        self.tv.bind("<Double-1>", lambda e: self.edit_dialog())
        self.refresh()

    def refresh(self):
        for r in self.tv.get_children():
            self.tv.delete(r)
        for p in self.db.list_products(self.search.get().strip()):
            self.tv.insert("", "end", iid=p["id"], values=(
                p["id"], p["name"], p["sku"], money(p["purchase_price"]),
                money(p["wholesale_price"]), money(p["retail_price"]),
                money(p.get("mrp") or 0), p.get("company") or "",
                self.margin_pct(p), int(p.get("pack_size") or 1),
                p["unit"], f"{p['gst_percent']:g}",
                f"{p['stock']:g}", p["supplier"]))

    def selected_id(self):
        sel = self.tv.selection()
        if not sel:
            messagebox.showinfo("Products", "Select a product first.")
            return None
        return int(sel[0])

    def product_dialog(self, product=None):
        win = ctk.CTkToplevel(self)
        win.title("Edit product" if product else "Add product")
        win.geometry("480x620")
        win.transient(self)
        win.grab_set()
        p = product or {}
        entries = {}

        def row(label, key, default=""):
            ctk.CTkLabel(win, text=label).pack(anchor="w", padx=14, pady=(8, 0))
            e = ctk.CTkEntry(win)
            e.insert(0, str(p.get(key, default)))
            e.pack(fill="x", padx=14)
            entries[key] = e

        row("Name *", "name")
        row("SKU / barcode", "sku")
        row("Purchase price (\u20b9)", "purchase_price", "0")
        row("Wholesale price (\u20b9)", "wholesale_price", "0")
        row("Retail price (\u20b9)", "retail_price", "0")
        row("MRP (\u20b9)", "mrp", "0")
        row("Company / manufacturer", "company")
        ctk.CTkLabel(win, text="Unit").pack(anchor="w", padx=14, pady=(8, 0))
        unit = ctk.CTkOptionMenu(win, values=UNITS)
        unit.set(p.get("unit", "pcs") or "pcs")
        unit.pack(fill="x", padx=14)
        row("Pack size (pieces per pack)", "pack_size",
            str(int(p.get("pack_size") or 1)))
        row("GST %", "gst_percent", "0")
        row("Current stock", "stock", "0")
        row("Low-stock alert below", "low_stock_threshold", "5")
        row("Supplier", "supplier")

        result = {}

        def save():
            if not entries["name"].get().strip():
                messagebox.showerror("Products", "Name is required.")
                return
            try:
                for k in ("purchase_price", "wholesale_price", "retail_price",
                          "mrp", "gst_percent", "stock",
                          "low_stock_threshold"):
                    float(entries[k].get() or 0)
                pack_size = int(entries["pack_size"].get() or 1)
                assert pack_size >= 1
            except ValueError:
                messagebox.showerror("Products",
                                     "Prices, MRP, GST, stock and threshold "
                                     "must be numbers.")
                return
            except AssertionError:
                messagebox.showerror("Products",
                                     "Pack size must be a whole number "
                                     "\u2265 1.")
                return
            result.update({
                "name": entries["name"].get().strip(),
                "sku": entries["sku"].get().strip(),
                "purchase_price": float(entries["purchase_price"].get() or 0),
                "wholesale_price": float(entries["wholesale_price"].get() or 0),
                "retail_price": float(entries["retail_price"].get() or 0),
                "mrp": float(entries["mrp"].get() or 0),
                "company": entries["company"].get().strip(),
                "unit": unit.get(),
                "pack_size": pack_size,
                "gst_percent": float(entries["gst_percent"].get() or 0),
                "stock": float(entries["stock"].get() or 0),
                "low_stock_threshold": float(
                    entries["low_stock_threshold"].get() or 5),
                "supplier": entries["supplier"].get().strip(),
            })
            win.destroy()

        ctk.CTkButton(win, text="Save", command=save).pack(pady=16)
        for e in entries.values():
            e.bind("<Return>", lambda _e: save())
        win.bind("<Escape>", lambda _e: win.destroy())
        win.after(60, lambda: entries["name"].focus_set())
        win.wait_window()
        return result or None

    def add_dialog(self):
        data = self.product_dialog()
        if data:
            self.db.add_product(**data)
            self.refresh()

    def edit_dialog(self):
        pid = self.selected_id()
        if pid is None:
            return
        data = self.product_dialog(self.db.get_product(pid))
        if data:
            self.db.update_product(pid, **data)
            self.refresh()

    def delete_selected(self):
        pid = self.selected_id()
        if pid is None:
            return
        p = self.db.get_product(pid)
        if not messagebox.askyesno("Delete",
                                    f"Delete '{p['name']}' permanently?"):
            return
        if not self.db.delete_product(pid):
            messagebox.showerror(
                "Delete",
                "This product appears on saved bills, so it cannot be "
                "deleted (invoice history must stay intact).")
        self.refresh()

    def import_csv(self):
        path = filedialog.askopenfilename(
            filetypes=[("CSV files", "*.csv")],
            title="Import products from CSV")
        if not path:
            return
        count = 0
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if not (row.get("name") or "").strip():
                    continue
                def num(k, d=0.0):
                    try:
                        return float(row.get(k, d) or d)
                    except ValueError:
                        return d
                self.db.add_product(
                    name=row["name"].strip(), sku=(row.get("sku") or "").strip(),
                    purchase_price=num("purchase_price"),
                    wholesale_price=num("wholesale_price"),
                    retail_price=num("retail_price"),
                    mrp=num("mrp"),
                    company=(row.get("company") or "").strip(),
                    unit=(row.get("unit") or "pcs").strip(),
                    pack_size=max(int(num("pack_size", 1)), 1),
                    gst_percent=num("gst_percent"),
                    stock=num("stock"), low_stock_threshold=num(
                        "low_stock_threshold", 5),
                    supplier=(row.get("supplier") or "").strip())
                count += 1
        messagebox.showinfo("Import", f"Imported {count} products.")
        self.refresh()

    def export_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV files", "*.csv")],
            title="Export products to CSV")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["name", "sku", "purchase_price", "wholesale_price",
                        "retail_price", "mrp", "company", "unit", "pack_size",
                        "gst_percent", "stock", "low_stock_threshold",
                        "supplier"])
            for p in self.db.list_products():
                w.writerow([p["name"], p["sku"], p["purchase_price"],
                            p["wholesale_price"], p["retail_price"],
                            p.get("mrp") or 0, p.get("company") or "",
                            p["unit"], int(p.get("pack_size") or 1),
                            p["gst_percent"], p["stock"],
                            p["low_stock_threshold"], p["supplier"]])
        messagebox.showinfo("Export", f"Exported to {path}")

    def barcode_labels(self):
        products = self.db.list_products(self.search.get().strip())
        if not products:
            messagebox.showinfo("Barcode labels", "No products to print.")
            return
        try:
            from new_features import generate_barcode_labels_pdf
            from db import data_dir
            shop = self.db.shop_profile().get("shop_name") or ""
            pdf = generate_barcode_labels_pdf(
                products, data_dir() / "barcode_labels.pdf", shop)
            printing.open_pdf(pdf)
            messagebox.showinfo(
                "Barcode labels",
                f"Label sheet saved at:\n{pdf}\n\n"
                f"{len(products)} product(s), 3 labels per row.")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Barcode labels",
                                 f"Could not build the labels: {e}")


class StockFrame(ctk.CTkFrame):
    def __init__(self, parent, db, app):
        super().__init__(parent, fg_color="transparent")
        self.db, self.app = db, app
        ctk.CTkLabel(self, text="Stock management",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                         anchor="w", pady=(4, 8))

        cards = ctk.CTkFrame(self, fg_color="transparent")
        cards.pack(fill="x", pady=4)
        self.value_lbl = ctk.CTkLabel(cards, text="",
                                     font=ctk.CTkFont(size=16, weight="bold"))
        self.value_lbl.pack(side="left", padx=6)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", pady=4)
        ctk.CTkButton(btns, text="Stock IN (purchase)",
                      command=lambda: self.move_dialog("in")).pack(
                          side="left", padx=4)
        ctk.CTkButton(btns, text="Stock OUT (damage / return)",
                      fg_color="#b26a00", hover_color="#8a5200",
                      command=lambda: self.move_dialog("out")).pack(
                          side="left", padx=4)
        ctk.CTkButton(btns, text="Refresh",
                      command=self.refresh).pack(side="right", padx=4)

        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True, pady=6)
        tabs.add("Current stock")
        tabs.add("Movement log")

        fr, self.tv = tree(tabs.tab("Current stock"),
                           ("Product", "SKU", "Stock", "Unit",
                            "Purchase price", "Value", "Earliest expiry",
                            "Supplier"),
                           widths=(200, 100, 80, 55, 95, 100, 105, 120),
                           height=16)
        fr.pack(fill="both", expand=True, padx=8, pady=8)

        fr2, self.tv2 = tree(tabs.tab("Movement log"),
                             ("Date", "Product", "Change", "Reason", "Note"),
                             widths=(130, 220, 80, 100, 220), height=16)
        fr2.pack(fill="both", expand=True, padx=8, pady=8)
        self.refresh()

    def refresh(self):
        for r in self.tv.get_children():
            self.tv.delete(r)
        for p in self.db.list_products():
            exp = self.db.product_earliest_expiry(p["id"]) or "-"
            self.tv.insert("", "end", values=(
                p["name"], p["sku"], f"{p['stock']:g} {p['unit']}", p["unit"],
                money(p["purchase_price"]),
                money(p["purchase_price"] * p["stock"]), exp, p["supplier"]))
        for r in self.tv2.get_children():
            self.tv2.delete(r)
        for m in self.db.stock_movements(limit=200):
            ch = f"{m['qty_change']:+g}"
            self.tv2.insert("", "end", values=(
                m["date"], m["name"] or "?", ch, m["reason"], m["note"]))
        self.value_lbl.configure(
            text=f"Total stock value: {money(self.db.stock_value())}")

    def move_dialog(self, direction):
        win = ctk.CTkToplevel(self)
        win.title("Stock IN" if direction == "in" else "Stock OUT")
        win.geometry("420x400")
        win.transient(self)
        win.grab_set()

        chosen = {}

        def pick_product():
            SearchPicker(
                win, "Pick product",
                lambda q: self.db.list_products(q),
                lambda p: f"{p['name']}  ({p['stock']:g} {p['unit']})",
                lambda p: (chosen.update(p), prod_lbl.configure(
                    text=f"{p['name']} \u2014 now {p['stock']:g} {p['unit']}")))

        ctk.CTkButton(win, text="Choose product...",
                      command=pick_product).pack(pady=10, padx=14, fill="x")
        prod_lbl = ctk.CTkLabel(win, text="No product chosen",
                                text_color="gray")
        prod_lbl.pack(pady=4)

        ctk.CTkLabel(win, text="Quantity").pack(anchor="w", padx=14, pady=(6, 0))
        qty_e = ctk.CTkEntry(win)
        qty_e.pack(fill="x", padx=14)
        ctk.CTkLabel(win, text="Note (supplier / reason)").pack(
            anchor="w", padx=14, pady=(6, 0))
        note_e = ctk.CTkEntry(win)
        note_e.pack(fill="x", padx=14)

        def save():
            if not chosen:
                messagebox.showerror("Stock", "Choose a product first.")
                return
            try:
                qty = float(qty_e.get())
                assert qty > 0
            except (ValueError, AssertionError):
                messagebox.showerror("Stock", "Enter a positive quantity.")
                return
            delta = qty if direction == "in" else -qty
            reason = "stock-in" if direction == "in" else "stock-out"
            self.db.adjust_stock(chosen["id"], delta, reason, note_e.get())
            win.destroy()
            self.refresh()
            messagebox.showinfo(
                "Stock", f"{'Added' if direction == 'in' else 'Removed'} "
                         f"{qty:g} {chosen['unit']} of {chosen['name']}.")

        ctk.CTkButton(win, text="Save", command=save).pack(pady=16)


class BillTab:

    def __init__(self, name):
        self.name = name
        self.edit_bill_id = None     # set when editing a finalized bill
        self.customer = None         # customer row dict
        self.payment_type = "Cash"   # Cash / UPI / Credit (Cash default)
        self.price_mode = "wholesale"
        self.items = []              # dicts: product_id,name,unit,qty,price,
        self.bill_discount = 0.0

    def totals(self, db):
        return db.compute_totals(self.items, self.bill_discount)


class BillingFrame(ctk.CTkFrame):
    def __init__(self, parent, db, app):
        super().__init__(parent, fg_color="transparent")
        self.db, self.app = db, app
        self.tabs = {}          # tab name -> (tabview-name, BillTab, widgets)
        self.counter = 0

        self.f_card_name = ctk.CTkFont(size=15, weight="bold")
        self.f_card_total = ctk.CTkFont(size=16, weight="bold")
        self.f_card_name_sm = ctk.CTkFont(size=13, weight="bold")
        self.f_card_total_sm = ctk.CTkFont(size=14, weight="bold")
        self.f_muted = ctk.CTkFont(size=12)
        self.f_grand = ctk.CTkFont(size=24, weight="bold")
        self.CARD_BG = ("gray94", "gray16")
        self.CARD_BORDER = ("gray76", "gray30")
        self.ACCENT = "#1f6f43"
        self.ACCENT_TEXT = ("#166534", "#86efac")
        self.DANGER = "#b3261e"

        ctk.CTkLabel(self, text="Billing",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                         anchor="w", pady=(4, 6))

        grid_billing.install_header(self)

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True)
        self.tabview.configure(command=self._sync_view_var)

        app.bind("<F1>", lambda e: self.shortcuts_help())
        app.bind("<F2>", lambda e: self.new_tab())
        app.bind("<Control-s>", lambda e: self.finalize_current())
        app.bind("<Control-Return>", lambda e: self.finalize_current())
        app.bind("<Control-p>", lambda e: self.print_current())
        app.bind("<F3>", lambda e: self.focus_search())
        app.bind("<F4>", lambda e: self.pick_customer_current())
        app.bind("<F6>", lambda e: self.toggle_price_mode())
        app.bind("<F8>", lambda e: self.focus_bill_discount())
        app.bind("<F9>", lambda e: self.repeat_last_bill_current())
        app.bind("<Insert>", self._guarded_key(lambda: self.product_dialog()))
        app.bind("<Control-g>", self._guarded_key(self.toggle_bill_view))
        app.bind("<Prior>", lambda e: self.switch_tab(-1))
        app.bind("<Next>", lambda e: self.switch_tab(1))
        app.bind("<End>", self.end_bill_key)
        app.bind("<Delete>", self.delete_key)
        app.bind("<Escape>", lambda e: self.clear_line_inputs())
        self.new_tab()

    def _guarded_key(self, fn):
        def handler(event):
            if self._typing_focus():
                return
            fn()
            return "break"
        return handler

    def pick_customer_current(self):
        cur = self.current()
        if cur:
            pick = cur[1].get("pick_customer")
            if pick:
                pick()

    def focus_search(self):
        cur = self.current()
        if cur:
            tab, w = cur
            if (w.get("bill_view") or "grid") == "grid" \
                    and w.get("grid_panel"):
                w["grid_panel"].focus_find()
                w["grid_panel"].refresh()
            else:
                w["prod_e"].focus_set()
                self._suggest_show(tab, w, show_all=True)

    def set_bill_view(self, value):
        grid_billing.set_view(self, value)

    def toggle_bill_view(self):
        grid_billing.toggle_view(self)

    def _sync_view_var(self):
        grid_billing.sync_view_var(self)

    def _apply_bill_view(self, tab, w):
        grid_billing.apply_view(self, tab, w)

    def _typing_focus(self):
        try:
            foc = self.app.focus_get()
            if foc is None:
                return False
            return foc.winfo_class() in ("Entry", "Text", "TEntry", "TText")
        except Exception:
            return False

    def end_bill_key(self, event):
        if self._typing_focus():
            return
        self.end_bill_dialog()
        return "break"

    def end_bill_dialog(self):
        cur = self.current()
        if not cur:
            return
        tab, w = cur
        win = ctk.CTkToplevel(self.app)
        win.title("End bill")
        win.geometry("340x180")
        win.transient(self.app)
        win.grab_set()
        ctk.CTkLabel(win, text=f"End {tab.name}?",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(
                         pady=(18, 2))
        ctk.CTkLabel(win,
                     text=f"{len(tab.items)} item(s) on this bill",
                     text_color="gray").pack(pady=(0, 12))
        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(pady=6)
        save_b = ctk.CTkButton(
            btns, text="Save bill", fg_color="#1f6f43",
            hover_color="#175733",
            command=lambda: (win.destroy(), self.finalize_current()))
        save_b.pack(side="left", padx=6)
        ctk.CTkButton(
            btns, text="Discard", fg_color="#b3261e",
            hover_color="#8f1d17",
            command=lambda: (win.destroy(), self.close_tab(tab.name))).pack(
                side="left", padx=6)
        ctk.CTkButton(btns, text="Cancel", fg_color="transparent",
                      command=win.destroy).pack(side="left", padx=6)
        save_b.focus_set()
        win.bind("<Return>", lambda e: (win.destroy(),
                                        self.finalize_current()))
        win.bind("<Escape>", lambda e: win.destroy())

    def delete_key(self, event):
        if self._typing_focus():
            return
        cur = self.current()
        if not cur:
            return
        tab, w = cur
        if w.get("card_sel") is not None:
            self.remove_line(tab, w)
            return "break"

    def toggle_price_mode(self):
        cur = self.current()
        if not cur:
            return
        tab, w = cur
        new = "Retail" if tab.price_mode == "wholesale" else "Wholesale"
        try:
            w["mode_var"].set(new)
        except Exception:
            pass
        self._on_mode_change(tab, new)

    def focus_bill_discount(self):
        cur = self.current()
        if not cur:
            return
        try:
            cur[1]["disc_e"].focus_set()
            cur[1]["disc_e"].select_range(0, "end")
        except Exception:
            pass

    def repeat_last_bill_current(self):
        cur = self.current()
        if cur:
            self.repeat_last_bill(cur[0], cur[1])

    def switch_tab(self, delta):
        names = list(self.tabs.keys())
        if len(names) < 2:
            return
        try:
            i = names.index(self.current_name())
        except ValueError:
            return
        self.tabview.set(names[(i + delta) % len(names)])

    def shortcuts_help(self):
        win = ctk.CTkToplevel(self.app)
        win.title("Keyboard shortcuts")
        win.geometry("460x480")
        win.transient(self.app)
        ctk.CTkLabel(win, text="Keyboard shortcuts",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(
                         pady=(14, 8))
        rows = [
            ("F1", "This help"),
            ("F2", "New bill tab"),
            ("F3", "Jump to product search / grid Find box"),
            ("F4", "Choose customer (Esc closes)"),
            ("F6", "Toggle Wholesale / Retail prices"),
            ("F8", "Jump to bill discount field"),
            ("F9", "Repeat last bill for a customer"),
            ("Enter", "Add line \u00b7 qty \u2192 rate \u2192 discount \u2192 product list"),
            ("Up / Down", "Move in product dropdown"),
            ("Esc", "Close dropdown / clear entry"),
            ("Tab", "Next field"),
            ("Delete", "Remove selected bill line"),
            ("End", "End bill: Save (default) or Discard"),
            ("Insert", "Add new product"),
            ("PgUp / PgDn", "Switch bill tabs"),
            ("Ctrl+S / Ctrl+Enter", "Save bill"),
            ("Ctrl+P", "Print bill"),
            ("Ctrl+G", "Toggle Grid / Cards product view"),
        ]
        for key, desc in rows:
            r = ctk.CTkFrame(win, fg_color="transparent")
            r.pack(fill="x", padx=24, pady=2)
            ctk.CTkLabel(r, text=key, width=140, anchor="w",
                         font=ctk.CTkFont(weight="bold")).pack(side="left")
            ctk.CTkLabel(r, text=desc, anchor="w").pack(side="left")
        ctk.CTkButton(win, text="Close",
                      command=win.destroy).pack(pady=14)
        win.bind("<Escape>", lambda e: win.destroy())

    def clear_line_inputs(self):
        cur = self.current()
        if not cur:
            return
        w = cur[1]
        if grid_billing.escape_in_find(self.app, w):
            return
        w["prod_e"].delete(0, "end")
        w["qty_e"].delete(0, "end")
        w["qty_e"].insert(0, "1")
        w["ldisc_e"].delete(0, "end")
        if w.get("boxes_e") is not None:
            w["boxes_e"].delete(0, "end")
        w["picked"] = None
        self._suggest_hide(w)
        grid_billing.focus_picker(w)

    def _rank_products(self, q):
        ql = q.lower()

        def rank(p):
            name = (p.get("name") or "").lower()
            sku = (p.get("sku") or "").lower()
            if name.startswith(ql):
                return (0, name)
            if ql in name:
                return (1, name)
            if sku.startswith(ql) or ql in sku:
                return (2, name)
            return (3, name)

        return sorted(self.db.list_products(q), key=rank)[:10]

    def _suggest_show(self, tab, w, show_all=False):
        prod_e, suggest = w["prod_e"], w["suggest"]
        for ch in suggest.winfo_children():
            ch.destroy()
        w["suggest_items"] = []
        w["suggest_idx"] = -1
        q = prod_e.get().strip()
        if not q:
            if not show_all:
                suggest.place_forget()
                return
            items = sorted(self.db.list_products(""),
                           key=lambda p: (p.get("name") or "").lower())[:40]
        else:
            items = self._rank_products(q)
        if not items:
            suggest.place_forget()
            return
        w["suggest_items"] = items
        for p in items:
            price = (p["wholesale_price"] if tab.price_mode == "wholesale"
                     else p["retail_price"])
            sku = p["sku"] or "\u2014"
            mrp = f"  \u00b7 MRP {money(p.get('mrp') or 0)}" \
                if (p.get("mrp") or 0) > 0 else ""
            b = ctk.CTkButton(
                suggest,
                text=f"{p['name']}  \u00b7 {sku}  \u00b7 "
                     f"{money(price)}/{p['unit']}{mrp}",
                anchor="w", fg_color="transparent",
                text_color=("black", "white"),
                hover_color=("gray75", "gray25"),
                command=lambda pp=p: self._suggest_pick(tab, w, pp))
            b.pack(fill="x", pady=1)
        x = prod_e.winfo_x()
        y = prod_e.winfo_y() + prod_e.winfo_height() + 4
        suggest.place(x=x, y=y)
        suggest.lift()

    def _suggest_hide(self, w):
        try:
            w["suggest"].place_forget()
        except Exception:
            pass
        w["suggest_items"] = []
        w["suggest_idx"] = -1

    def _suggest_move(self, tab, w, delta):
        items = w.get("suggest_items") or []
        if not items:
            return
        idx = w.get("suggest_idx", -1) + delta
        idx = max(0, min(idx, len(items) - 1))
        w["suggest_idx"] = idx
        for i, b in enumerate(w["suggest"].winfo_children()):
            if i == idx:
                b.configure(fg_color=self.ACCENT, text_color="white")
            else:
                b.configure(fg_color="transparent",
                            text_color=("black", "white"))

    def _suggest_pick(self, tab, w, p):
        w["prod_e"].delete(0, "end")
        w["prod_e"].insert(0, p["name"])
        w["picked"] = p
        self._suggest_hide(w)
        w["qty_e"].focus_set()
        w["qty_e"].select_range(0, "end")

    def new_tab(self, edit_bill_id=None, label=None):
        self.counter += 1
        if edit_bill_id:
            bill = self.db.get_bill(edit_bill_id)
            tab_name = f"Edit {bill['bill_no']}"
        else:
            tab_name = label or f"Bill {self.counter}"
        base, i = tab_name, 1
        while tab_name in self.tabs:
            i += 1
            tab_name = f"{base} ({i})"
        self.tabview.add(tab_name)
        tab = BillTab(tab_name)
        if edit_bill_id:
            self._load_bill_into_tab(tab, edit_bill_id)
        widgets = self._build_tab_ui(self.tabview.tab(tab_name), tab)
        self.tabs[tab_name] = (tab, widgets)
        self.tabview.set(tab_name)
        self._refresh_totals(tab_name)
        self.after(80, lambda: self._focus_tab_search(tab_name))
        return tab_name

    def _focus_tab_search(self, tab_name):
        cur = self.tabs.get(tab_name)
        if cur:
            try:
                cur[1]["prod_e"].focus_set()
            except Exception:
                pass

    def current_name(self):
        return self.tabview.get()

    def current(self):
        name = self.current_name()
        return self.tabs.get(name)

    def _load_bill_into_tab(self, tab, bill_id):
        bill = self.db.get_bill(bill_id)
        tab.edit_bill_id = bill_id
        tab.customer = self.db.get_customer(bill["customer_id"]) if bill["customer_id"] else None
        tab.payment_type = bill["payment_type"]
        tab.bill_discount = bill["discount"]
        for it in self.db.bill_items(bill_id):
            tab.items.append({
                "product_id": it["product_id"], "name": it["name"],
                "unit": it["unit"], "qty": it["qty"], "price": it["price"],
                "line_discount": it["line_discount"],
                "gst_percent": it["gst_percent"],
                "sku": "", })
        self.db.log_bill_action(bill_id, "edited",
                                "Bill reopened for editing in Billing")

    def close_tab(self, name):
        if name in self.tabs:
            self.tabview.delete(name)
            del self.tabs[name]
        if not self.tabs:
            self.new_tab()

    def _build_tab_ui(self, frame, tab):
        w = {}  # widget refs
        frame.grid_columnconfigure(0, weight=1)

        meta = ctk.CTkFrame(frame, corner_radius=10, border_width=1,
                            fg_color=self.CARD_BG,
                            border_color=self.CARD_BORDER)
        meta.pack(fill="x", pady=(2, 6))
        r1 = ctk.CTkFrame(meta, fg_color="transparent")
        r1.pack(fill="x", padx=8, pady=6)

        ctk.CTkLabel(r1, text="Customer *").pack(side="left", padx=(4, 2))
        cust_btn = ctk.CTkButton(r1, text="Walk-in \u2014 F4 to choose",
                                 width=170, anchor="w", fg_color=("gray80", "gray20"))
        cust_btn.pack(side="left", padx=4)

        ctk.CTkButton(r1, text="+ New", width=60,
                      command=lambda: self.new_customer_dialog(tab, w)).pack(
                          side="left", padx=2)

        ctk.CTkLabel(r1, text="Payment *").pack(side="left", padx=(10, 2))
        pay_var = ctk.StringVar(value=tab.payment_type)
        for pt in ("Cash", "UPI", "Credit"):
            ctk.CTkRadioButton(r1, text=pt, variable=pay_var, value=pt,
                               command=lambda: self._on_pay_change(tab, pay_var, w)
                               ).pack(side="left", padx=4)

        ctk.CTkLabel(r1, text="Price").pack(side="left", padx=(10, 2))
        mode_var = ctk.StringVar(value="Wholesale")
        ctk.CTkSegmentedButton(r1, values=["Wholesale", "Retail"],
                               variable=mode_var,
                               command=lambda v: self._on_mode_change(tab, v)
                               ).pack(side="left", padx=4)

        ctk.CTkLabel(r1, text="Bill disc. \u20b9").pack(side="left", padx=(10, 2))
        disc_e = ctk.CTkEntry(r1, width=64)
        disc_e.insert(0, f"{tab.bill_discount:g}" if tab.bill_discount else "")
        disc_e.pack(side="left", padx=4)
        disc_e.bind("<KeyRelease>",
                    lambda e: self._on_disc_change(tab, disc_e, w))
        grid_billing.build_bill_head(r1, self.db, tab, self.f_muted)

        def pick_customer():
            SearchPicker(
                frame, "Choose customer",
                lambda q: self.db.list_customers(q),
                lambda c: (f"{c['name']}  \u2014 {c['phone']}"
                           + ("  [wholesale]" if c["is_wholesale"] else "  [retail]")
                           + (f"  \u2014 outstanding {money(c['balance'])}"
                              if c["balance"] > 0 else "")),
                lambda c: self._set_customer(tab, c, w))

        cust_btn.configure(command=pick_customer)
        w["pick_customer"] = pick_customer

        r2 = ctk.CTkFrame(frame, fg_color="transparent")
        r2.pack(fill="x", pady=4)
        ctk.CTkLabel(r2, text="Product").pack(side="left", padx=(4, 2))
        prod_e = ctk.CTkEntry(r2, placeholder_text="Type product name or SKU...",
                              width=280)
        prod_e.pack(side="left", padx=4)
        ctk.CTkLabel(r2, text="Qty").pack(side="left", padx=(6, 2))
        qty_e = ctk.CTkEntry(r2, width=80)
        qty_e.insert(0, "1")
        qty_e.pack(side="left", padx=4)
        boxes_lbl, boxes_e = grid_billing.build_boxes_entry(
            r2, lambda: self.add_line(tab, w))
        ctk.CTkLabel(r2, text="Line disc. \u20b9").pack(side="left", padx=(6, 2))
        ldisc_e = ctk.CTkEntry(r2, width=80)
        ldisc_e.pack(side="left", padx=4)
        add_btn = ctk.CTkButton(r2, text="Add line (Enter)",
                                command=lambda: self.add_line(tab, w))
        add_btn.pack(side="left", padx=8)
        ctk.CTkLabel(r2, text="Tip: scan barcode to add instantly",
                     text_color="gray", font=ctk.CTkFont(size=11)).pack(
                         side="left", padx=8)
        repeat_note = ctk.CTkLabel(r2, text="", text_color="#0b5fa5",
                                   font=ctk.CTkFont(size=11))
        repeat_note.pack(side="left", padx=8)

        suggest = ctk.CTkScrollableFrame(r2, width=360, height=190,
                                         fg_color=("gray95", "gray14"),
                                         border_width=1,
                                         border_color=("gray70", "gray30"))
        suggest.place_forget()
        w["suggest"] = suggest
        w["suggest_items"] = []
        w["suggest_idx"] = -1

        def on_type(event):
            if event.keysym in ("Up", "Down", "Return", "Escape", "Tab",
                                "ISO_Left_Tab", "Shift_L", "Shift_R",
                                "Control_L", "Control_R", "Alt_L", "Alt_R",
                                "Caps_Lock"):
                return
            self._suggest_show(tab, w)

        def on_prod_return(event):
            q = prod_e.get().strip()
            if q:
                hit = self.db.find_by_sku(q)
                if hit:
                    self._suggest_hide(w)
                    w["picked"] = hit
                    w["qty_e"].delete(0, "end")
                    w["qty_e"].insert(0, "1")
                    self.add_line(tab, w)
                    return "break"
            if w["suggest"].winfo_ismapped() and w.get("suggest_items"):
                idx = w.get("suggest_idx", -1)
                if idx < 0:
                    idx = 0
                self._suggest_pick(tab, w, w["suggest_items"][idx])
                return "break"
            self.add_line(tab, w)
            return "break"

        def on_prod_nav(event, delta):
            if w["suggest"].winfo_ismapped() and w.get("suggest_items"):
                self._suggest_move(tab, w, delta)
                return "break"
            return None

        def on_prod_esc(event):
            if w["suggest"].winfo_ismapped():
                self._suggest_hide(w)
                return "break"
            return None

        prod_e.bind("<KeyRelease>", on_type)
        prod_e.bind("<Return>", on_prod_return)
        prod_e.bind("<Down>", lambda e: on_prod_nav(e, 1))
        prod_e.bind("<Up>", lambda e: on_prod_nav(e, -1))
        prod_e.bind("<Escape>", on_prod_esc)
        qty_e.bind("<Return>", lambda e: self.add_line(tab, w))
        ldisc_e.bind("<Return>", lambda e: self.add_line(tab, w))
        w.update({"picked": None})

        cards_sf = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        cards_sf.pack(fill="both", expand=True, pady=6)

        grid_billing.build_panel(frame, self, tab, w)

        r3 = ctk.CTkFrame(frame, fg_color="transparent")
        r3.pack(fill="x", pady=2)
        ctk.CTkButton(r3, text="Remove selected",
                      command=lambda: self.remove_line(tab, w)).pack(
                          side="left", padx=4)
        ctk.CTkButton(r3, text="Edit selected (double-click card)",
                      command=lambda: self.edit_line(tab, w)).pack(
                          side="left", padx=4)

        ctk.CTkFrame(frame, height=2,
                     fg_color=("gray75", "gray25")).pack(fill="x", pady=(2, 0))
        tot = ctk.CTkFrame(frame)
        tot.pack(fill="x", pady=(0, 6))
        tot_lbl = ctk.CTkLabel(tot, text="", justify="left",
                               font=ctk.CTkFont(size=13))
        tot_lbl.pack(side="left", padx=12, pady=8)
        warn_lbl = ctk.CTkLabel(tot, text="", text_color="#b3261e",
                                font=ctk.CTkFont(size=13, weight="bold"))
        warn_lbl.pack(side="left", padx=8, pady=8)
        grand_lbl = ctk.CTkLabel(tot, text="", font=self.f_grand,
                                 text_color=self.ACCENT_TEXT)
        grand_lbl.pack(side="right", padx=12, pady=8)

        grid_billing.build_last_bills_strip(frame, w, self.f_muted)

        r4 = ctk.CTkFrame(frame, fg_color="transparent")
        r4.pack(fill="x", pady=4)
        fin_label = ("Save changes (Ctrl+S)" if tab.edit_bill_id
                     else "Finalize bill (Ctrl+S)")
        ctk.CTkButton(r4, text=fin_label, fg_color="#1f6f43",
                      hover_color="#175733",
                      command=lambda: self.finalize_current()).pack(
                          side="left", padx=4)
        ctk.CTkButton(r4, text="Print / Preview (Ctrl+P)",
                      command=lambda: self.print_current()).pack(
                          side="left", padx=4)
        ctk.CTkButton(r4, text="Repeat last bill",
                      command=lambda: self.repeat_last_bill(tab, w)).pack(
                          side="left", padx=4)
        ctk.CTkButton(r4, text="Discard tab", fg_color="#b3261e",
                      hover_color="#8f1d17",
                      command=lambda: self.close_tab(tab.name)).pack(
                          side="right", padx=4)
        ctk.CTkLabel(r4, text="Shortcuts: F1 help \u00b7 F2 new tab \u00b7 F3 search \u00b7 "
                              "F4 customer \u00b7 F9 repeat bill \u00b7 Enter next field \u00b7 "
                              "Del remove line \u00b7 End finish bill \u00b7 "
                              "Ctrl+S save \u00b7 Ctrl+P print",
                     text_color="gray").pack(side="right", padx=10)

        w.update({"cust_btn": cust_btn, "pay_var": pay_var,
                  "mode_var": mode_var, "disc_e": disc_e, "prod_e": prod_e,
                  "qty_e": qty_e, "boxes_lbl": boxes_lbl, "boxes_e": boxes_e,
                  "ldisc_e": ldisc_e, "cards_sf": cards_sf,
                  "repeat_note": repeat_note,
                  "card_sel": None, "card_widgets": [], "card_fields": {},
                  "tot_lbl": tot_lbl, "warn_lbl": warn_lbl,
                  "grand_lbl": grand_lbl,
                  "suggest": suggest, "frame": frame})
        self._refresh_customer_btn(tab, w)
        self._apply_bill_view(tab, w)
        return w

    def _set_customer(self, tab, c, w):
        tab.customer = c
        tab.price_mode = "wholesale" if c["is_wholesale"] else "retail"
        w["mode_var"].set("Wholesale" if tab.price_mode == "wholesale"
                          else "Retail")
        self._refresh_customer_btn(tab, w)
        w["prod_e"].focus_set()

    def _refresh_customer_btn(self, tab, w):
        if tab.customer:
            c = tab.customer
            outst = f" \u00b7 outstanding {money(c['balance'])}" if c["balance"] > 0 else ""
            w["cust_btn"].configure(
                text=f"{c['name']}{outst}")
        else:
            w["cust_btn"].configure(text="Walk-in \u2014 F4 to choose")

    def _on_pay_change(self, tab, pay_var, w):
        tab.payment_type = pay_var.get()

    def _on_mode_change(self, tab, value):
        tab.price_mode = value.lower()
        for _name, (t, w) in self.tabs.items():
            if t is tab:
                gp = w.get("grid_panel")
                if gp is not None:
                    gp.set_price_mode(tab.price_mode)
                break

    def _on_disc_change(self, tab, disc_e, w):
        tab.bill_discount = fnum(disc_e)
        self._refresh_totals(tab.name)

    def new_customer_dialog(self, tab, w):
        win = ctk.CTkToplevel(self)
        win.title("New customer")
        win.geometry("400x360")
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(win, text="Name *").pack(anchor="w", padx=14, pady=(10, 0))
        n_e = ctk.CTkEntry(win)
        n_e.pack(fill="x", padx=14)
        ctk.CTkLabel(win, text="Phone").pack(anchor="w", padx=14, pady=(6, 0))
        p_e = ctk.CTkEntry(win)
        p_e.pack(fill="x", padx=14)
        ctk.CTkLabel(win, text="Address").pack(anchor="w", padx=14, pady=(6, 0))
        a_e = ctk.CTkEntry(win)
        a_e.pack(fill="x", padx=14)
        ws_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(win, text="Wholesale customer (wholesale prices)",
                        variable=ws_var).pack(anchor="w", padx=14, pady=10)

        def save():
            name = n_e.get().strip()
            if not name:
                messagebox.showerror("Customer", "Name is required.")
                return
            cid = self.db.add_customer(name, p_e.get().strip(),
                                       a_e.get().strip(), ws_var.get())
            self._set_customer(tab, self.db.get_customer(cid), w)
            win.destroy()

        ctk.CTkButton(win, text="Save & select", command=save).pack(pady=12)

    def add_line(self, tab, w):
        name = w["prod_e"].get().strip()
        if not name:
            return
        picked = w.get("picked")
        p = None
        if picked and picked["name"].lower() == name.lower():
            p = self.db.get_product(picked["id"])
        else:
            rows = self.db.list_products(name)
            exact = [r for r in rows if r["name"].lower() == name.lower()
                     or r["sku"].lower() == name.lower()]
            p = exact[0] if exact else (rows[0] if rows else None)
        if not p:
            messagebox.showerror("Billing",
                                 f"No product found for '{name}'.")
            return
        bq = grid_billing.boxes_qty(w, p)
        if bq is not None:
            qty = bq
        else:
            try:
                qty = float(w["qty_e"].get())
                assert qty > 0
            except (ValueError, AssertionError):
                messagebox.showerror("Billing", "Enter a valid quantity.")
                w["qty_e"].focus_set()
                return
        if qty > p["stock"] and not messagebox.askyesno(
                "Billing",
                f"Only {p['stock']:g} {p['unit']} of '{p['name']}' in stock. "
                f"Bill {qty:g} anyway?"):
            return
        price = (p["wholesale_price"] if tab.price_mode == "wholesale"
                 else p["retail_price"])
        line_disc = fnum(w["ldisc_e"])
        merged_idx = None
        for i, it in enumerate(tab.items):
            if it.get("product_id") == p["id"] and it["price"] == price \
                    and it.get("gst_percent") == p["gst_percent"] \
                    and not it.get("line_discount") and not line_disc:
                it["qty"] += qty
                merged_idx = i
                break
        else:
            tab.items.append({
                "product_id": p["id"], "name": p["name"], "unit": p["unit"],
                "qty": qty, "price": price,
                "line_discount": line_disc, "gst_percent": p["gst_percent"],
                "sku": p["sku"]})
            merged_idx = len(tab.items) - 1
        w["prod_e"].delete(0, "end")
        w["qty_e"].delete(0, "end")
        w["qty_e"].insert(0, "1")
        w["ldisc_e"].delete(0, "end")
        if w.get("boxes_e") is not None:
            w["boxes_e"].delete(0, "end")
        w["picked"] = None
        self._suggest_hide(w)
        self._refresh_totals(tab.name, flash_idx=merged_idx)
        grid_billing.focus_picker(w)

    def edit_line(self, tab, w):
        idx = w.get("card_sel")
        if idx is None or idx >= len(tab.items):
            return
        self.edit_line_idx(tab, w, idx)

    def edit_line_idx(self, tab, w, idx):
        it = tab.items[idx]
        win = ctk.CTkToplevel(self)
        win.title("Edit line")
        win.geometry("340x340")
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(win, text=it["name"],
                     font=ctk.CTkFont(weight="bold")).pack(pady=10)
        ents = {}
        for label, key in (("Quantity", "qty"), ("Rate (\u20b9)", "price"),
                           ("Line discount (\u20b9)", "line_discount"),
                           ("GST %", "gst_percent")):
            ctk.CTkLabel(win, text=label).pack(anchor="w", padx=14, pady=(6, 0))
            e = ctk.CTkEntry(win)
            e.insert(0, f"{it[key]:g}")
            e.pack(fill="x", padx=14)
            ents[key] = e

        def save():
            try:
                it["qty"] = float(ents["qty"].get())
                it["price"] = float(ents["price"].get())
                it["line_discount"] = float(ents["line_discount"].get() or 0)
                it["gst_percent"] = float(ents["gst_percent"].get() or 0)
                assert it["qty"] > 0 and it["price"] >= 0
            except (ValueError, AssertionError):
                messagebox.showerror("Billing", "Enter valid numbers.")
                return
            win.destroy()
            w["card_sel"] = idx
            self._refresh_totals(tab.name)

        ctk.CTkButton(win, text="Save", command=save).pack(pady=14)

    def remove_line(self, tab, w):
        idx = w.get("card_sel")
        if idx is None or idx >= len(tab.items):
            return
        self.remove_line_idx(tab, w, idx)

    def remove_line_idx(self, tab, w, idx):
        del tab.items[idx]
        w["card_sel"] = None
        self._refresh_totals(tab.name)

    def _line_amount(self, it):
        taxable = max(it["qty"] * it["price"] - it["line_discount"], 0)
        return taxable * (1 + it["gst_percent"] / 100)

    def _low_stock(self, it):
        if not it.get("product_id"):
            return False
        try:
            p = self.db.get_product(it["product_id"])
        except Exception:
            return False
        return bool(p) and (p["stock"] - it["qty"]) <= p["low_stock_threshold"]

    def _render_cards(self, tab, w, flash_idx=None):
        sf = w["cards_sf"]
        for ch in sf.winfo_children():
            ch.destroy()
        cards = []
        w["card_fields"] = {}
        if not tab.items:
            ctk.CTkLabel(
                sf,
                text="\U0001f9fe   Bill is empty\n\n"
                     "Add products above \u2014 press F3 to jump to search.",
                justify="center", text_color="gray",
                font=ctk.CTkFont(size=14)).pack(expand=True, pady=48)
            w["card_sel"] = None
        else:
            for idx, it in enumerate(tab.items):
                card = self._build_card(tab, w, idx, it)
                card.pack(fill="x", padx=8, pady=3)
                cards.append(card)
            sel = w.get("card_sel")
            if sel is not None and sel < len(cards):
                self._select_card(tab, w, sel)
            else:
                w["card_sel"] = None
        w["card_widgets"] = cards
        gp = w.get("grid_panel")
        if gp is not None:
            gp.set_lines(tab.items, w.get("card_sel"))
        if flash_idx is not None and 0 <= flash_idx < len(cards):
            self._flash_card(w, flash_idx)

    def _build_card(self, tab, w, idx, it):
        sf = w["cards_sf"]
        card = ctk.CTkFrame(sf, corner_radius=8, border_width=1,
                            fg_color=self.CARD_BG,
                            border_color=self.CARD_BORDER)

        r1 = ctk.CTkFrame(card, fg_color="transparent")
        r1.pack(fill="x", padx=8, pady=(6, 1))
        name = ctk.CTkLabel(r1, text=it["name"],
                            font=self.f_card_name_sm, anchor="w")
        name.pack(side="left")
        warn_badge = None
        if self._low_stock(it):
            warn_badge = ctk.CTkLabel(
                r1, text="\u26a0 low stock", text_color=self.DANGER,
                font=ctk.CTkFont(size=11, weight="bold"))
            warn_badge.pack(side="left", padx=6)
        rm = ctk.CTkButton(r1, text="\u2715", width=26, height=24,
                           fg_color="transparent",
                           text_color=(self.DANGER, "#e57373"),
                           hover_color=("gray80", "gray25"),
                           command=lambda: self.remove_line_idx(tab, w, idx))
        rm.pack(side="right")
        total_lbl = ctk.CTkLabel(r1, text=money(self._line_amount(it)),
                                 font=self.f_card_total_sm,
                                 text_color=self.ACCENT_TEXT)
        total_lbl.pack(side="right", padx=(0, 6))

        r2 = ctk.CTkFrame(card, fg_color="transparent")
        r2.pack(fill="x", padx=8, pady=(0, 6))
        ctk.CTkLabel(r2, text="Qty", text_color="gray",
                     font=self.f_muted).pack(side="left", padx=(0, 2))
        qty_e = ctk.CTkEntry(r2, width=64)
        qty_e.insert(0, f"{it['qty']:g}")
        qty_e.pack(side="left")
        ctk.CTkLabel(r2, text=it["unit"], text_color="gray",
                     font=self.f_muted).pack(side="left", padx=4)
        ctk.CTkLabel(r2, text="Rate \u20b9", text_color="gray",
                     font=self.f_muted).pack(side="left", padx=(8, 2))
        rate_e = ctk.CTkEntry(r2, width=80)
        rate_e.insert(0, f"{it['price']:g}")
        rate_e.pack(side="left")
        ctk.CTkLabel(r2, text="Disc \u20b9", text_color="gray",
                     font=self.f_muted).pack(side="left", padx=(8, 2))
        disc_e = ctk.CTkEntry(r2, width=64)
        if it["line_discount"]:
            disc_e.insert(0, f"{it['line_discount']:g}")
        disc_e.pack(side="left")
        ctk.CTkLabel(r2, text=f"GST {it['gst_percent']:g}%",
                     text_color="gray", font=self.f_muted).pack(
                         side="left", padx=8)

        w["card_fields"][idx] = {"qty": qty_e, "rate": rate_e,
                                 "disc": disc_e, "total": total_lbl,
                                 "top": r1, "warn": warn_badge}
        for e in (qty_e, rate_e, disc_e):
            e._orig_bw = e.cget("border_width")
            e._orig_bc = e.cget("border_color")
            e.bind("<FocusIn>", lambda ev, ee=e: ee.configure(
                border_width=2, border_color=self.ACCENT))
            e.bind("<FocusOut>", lambda ev, ee=e: self._card_focus_out(
                tab, w, idx, qty_e, rate_e, disc_e, ee))

        qty_e.bind("<Return>", lambda e: self._commit_and_focus(
            tab, w, idx, qty_e, rate_e, disc_e, "rate"))
        rate_e.bind("<Return>", lambda e: self._commit_and_focus(
            tab, w, idx, qty_e, rate_e, disc_e, "disc"))
        disc_e.bind("<Return>", lambda e: self._commit_and_focus(
            tab, w, idx, qty_e, rate_e, disc_e, "prod"))

        def on_click(_e=None):
            self._select_card(tab, w, idx)
            try:
                card.focus_set()
            except Exception:
                pass

        def on_dbl(_e=None):
            self.edit_line_idx(tab, w, idx)

        card.bind("<Button-1>", on_click)
        card.bind("<Double-1>", on_dbl)
        name.bind("<Button-1>", on_click)
        name.bind("<Double-1>", on_dbl)
        return card

    def _commit_card_field(self, tab, w, idx, qty_e, rate_e, disc_e):
        try:
            if idx >= len(tab.items):
                return
            it = tab.items[idx]
            qty = float((qty_e.get() or "").strip() or it["qty"])
            price = float((rate_e.get() or "").strip() or it["price"])
            disc = float((disc_e.get() or "").strip() or 0)
            assert qty > 0 and price >= 0 and disc >= 0
        except Exception:
            try:
                if idx >= len(tab.items):
                    return
                it = tab.items[idx]
                qty_e.delete(0, "end")
                qty_e.insert(0, f"{it['qty']:g}")
                rate_e.delete(0, "end")
                rate_e.insert(0, f"{it['price']:g}")
                disc_e.delete(0, "end")
                if it["line_discount"]:
                    disc_e.insert(0, f"{it['line_discount']:g}")
            except Exception:
                pass
            return
        if (qty != it["qty"] or price != it["price"]
                or disc != it["line_discount"]):
            it["qty"], it["price"], it["line_discount"] = qty, price, disc
            w["card_sel"] = idx
            self._refresh_card_line(tab, w, idx)
            self._update_totals_footer(tab, w)

    def _refresh_card_line(self, tab, w, idx):
        f = (w.get("card_fields") or {}).get(idx)
        if not f or idx >= len(tab.items):
            return
        it = tab.items[idx]
        try:
            f["total"].configure(text=money(self._line_amount(it)))
        except Exception:
            pass
        low = self._low_stock(it)
        try:
            if low and f.get("warn") is None:
                f["warn"] = ctk.CTkLabel(
                    f["top"], text="\u26a0 low stock",
                    text_color=self.DANGER,
                    font=ctk.CTkFont(size=12, weight="bold"))
                f["warn"].pack(side="left", padx=8)
            elif not low and f.get("warn") is not None:
                f["warn"].destroy()
                f["warn"] = None
        except Exception:
            pass

    def _card_focus_out(self, tab, w, idx, qty_e, rate_e, disc_e, entry):
        try:
            if not entry.winfo_exists():
                return
        except Exception:
            return
        self._commit_card_field(tab, w, idx, qty_e, rate_e, disc_e)
        try:
            if entry.winfo_exists():
                entry.configure(border_width=entry._orig_bw,
                                border_color=entry._orig_bc)
        except Exception:
            pass

    def _commit_and_focus(self, tab, w, idx, qty_e, rate_e, disc_e, nxt):
        self._commit_card_field(tab, w, idx, qty_e, rate_e, disc_e)
        self._focus_card_field(tab, w, idx, nxt)
        return "break"

    def _focus_card_field(self, tab, w, idx, which):
        if which == "prod":
            try:
                w["prod_e"].focus_set()
            except Exception:
                pass
            self._suggest_show(tab, w, show_all=True)
            return
        e = (w.get("card_fields") or {}).get(idx, {}).get(which)
        try:
            if e is not None and e.winfo_exists():
                e.focus_set()
                e.select_range(0, "end")
        except Exception:
            pass

    def _select_line(self, tab, w, idx):
        """Bill-lines table (grid view) row selected: sync card selection."""
        w["card_sel"] = idx
        self._select_card(tab, w, idx)

    def _select_card(self, tab, w, idx):
        w["card_sel"] = idx
        for i, c in enumerate(w.get("card_widgets", [])):
            try:
                if not c.winfo_exists():
                    continue
                if i == idx:
                    c.configure(border_width=2, border_color=self.ACCENT)
                else:
                    c.configure(border_width=1,
                                border_color=self.CARD_BORDER)
            except Exception:
                pass

    def _flash_card(self, w, idx):
        cards = w.get("card_widgets", [])
        if idx >= len(cards):
            return
        card = cards[idx]
        try:
            card.configure(fg_color=("#d9f2e3", "#1c4632"))
            self.after(500, lambda: card.configure(fg_color=self.CARD_BG)
                       if card.winfo_exists() else None)
        except Exception:
            pass

    def _refresh_totals(self, name, flash_idx=None):
        if name not in self.tabs:
            return
        tab, w = self.tabs[name]
        self._render_cards(tab, w, flash_idx)
        self._update_totals_footer(tab, w)
        grid_billing.refresh_last_bills(self, w)

    def _update_totals_footer(self, tab, w):
        try:
            t = tab.totals(self.db)
        except Exception:
            return
        try:
            w["tot_lbl"].configure(
                text=f"Subtotal  {money(t['subtotal'])}      "
                     f"Bill disc.  {money(t['discount'])}      "
                     f"Round-off  {money(t['round_off'])}\n"
                     f"GST  {money(t['gst_total'])}")
            w["grand_lbl"].configure(text=f"Total  {money(t['grand_total'])}")
            problems = []
            if not tab.customer:
                problems.append("choose a customer")
            if not tab.payment_type:
                problems.append("choose payment type")
            w["warn_lbl"].configure(
                text=("\u26a0 " + " \u00b7 ".join(problems)) if problems else "")
        except Exception:
            pass

    def _validate(self, tab):
        if not tab.items:
            messagebox.showerror("Billing", "Add at least one item.")
            return False
        if not tab.customer:
            messagebox.showerror("Billing",
                                 "Choose a customer first (required).")
            return False
        if not tab.payment_type:
            messagebox.showerror("Billing",
                                 "Choose a payment type (Cash / UPI / Credit).")
            return False
        return True

    def finalize_current(self):
        cur = self.current()
        if not cur:
            return
        tab, w = cur
        if not self._validate(tab):
            return
        if tab.edit_bill_id:
            totals = self.db.update_bill(tab.edit_bill_id, tab.items,
                                         tab.bill_discount)
            bill_id = tab.edit_bill_id
            bill = self.db.get_bill(bill_id)
            msg = (f"Bill {bill['bill_no']} updated \u2014 "
                   f"new total {money(totals['grand_total'])}.")
        else:
            cid = tab.customer["id"] if tab.customer else None
            bill_id = self.db.create_bill(cid, tab.payment_type, tab.items,
                                          tab.bill_discount)
            bill = self.db.get_bill(bill_id)
            msg = (f"Bill {bill['bill_no']} saved \u2014 "
                   f"{money(bill['grand_total'])}.")
        name = tab.name
        self.close_tab(name)
        self.offer_print_after_save(bill_id, msg)
        self.app.show("dashboard")

    def offer_print_after_save(self, bill_id, msg):
        mode = self.db.get_setting("print_on_save", "ask")
        if mode == "skip":
            return
        if mode == "print":
            self._do_saved_bill_print(bill_id, preview=False)
            return
        if mode == "preview":
            self._do_saved_bill_print(bill_id, preview=True)
            return
        PrintOfferDialog(self.app, self, self.db, bill_id, msg)

    def _do_saved_bill_print(self, bill_id, preview=False):
        printer = self.db.get_setting("print_printer") or None
        copies = int(self.db.get_setting("print_copies", "1") or 1)
        try:
            path, printed, pmsg = invoices.print_bill(
                bill_id, printer=printer, copies=copies, preview=preview)
        except Exception as e:
            messagebox.showerror("Print", f"Could not build the invoice: {e}")
            return
        if printed:
            messagebox.showinfo("Print", pmsg)
        elif not preview:
            messagebox.showinfo("Print", pmsg)

    def _tab_bill_preview(self, tab):
        t = tab.totals(self.db)
        if tab.edit_bill_id:
            bill = self.db.get_bill(tab.edit_bill_id)
        else:
            bill = {"bill_no": "DRAFT", "date": today_iso(),
                    "payment_type": tab.payment_type or "Cash",
                    "subtotal": t["subtotal"], "discount": t["discount"],
                    "gst_total": t["gst_total"], "round_off": t["round_off"],
                    "grand_total": t["grand_total"],
                    "customer_name": (tab.customer["name"]
                                      if tab.customer else "Walk-in"),
                    "customer_phone": (tab.customer["phone"]
                                       if tab.customer else ""),
                    "customer_address": (tab.customer["address"]
                                         if tab.customer else "")}
        return bill, tab.items

    def print_current(self):
        cur = self.current()
        if not cur:
            return
        tab, w = cur
        if tab.edit_bill_id:
            bill, items = self._tab_bill_preview(tab)
        else:
            if not self._validate(tab):
                return
            bill, items = self._tab_bill_preview(tab)
        PrintDialog(self, self.db, bill, items)

    def repeat_last_bill(self, tab, w):
        """Load the customer's most recent bill's items into this tab at
        current prices. Customer is picked first via the existing picker."""
        def on_pick(c):
            bills = self.db.customer_bills(c["id"], limit=50)
            if not bills:
                messagebox.showinfo(
                    "Repeat bill",
                    f"{c['name']} has no previous bills to repeat.")
                return
            last = bills[0]
            self._set_customer(tab, c, w)
            n = 0
            for it in self.db.bill_items(last["id"]):
                p = (self.db.get_product(it["product_id"])
                     if it.get("product_id") else None)
                if p:
                    price = (p["wholesale_price"]
                             if tab.price_mode == "wholesale"
                             else p["retail_price"])
                    gst, sku, unit = (p["gst_percent"], p["sku"], p["unit"])
                else:
                    price, gst, sku, unit = (it["price"], it["gst_percent"],
                                            "", it["unit"])
                tab.items.append({
                    "product_id": it["product_id"], "name": it["name"],
                    "unit": unit, "qty": it["qty"], "price": price,
                    "line_discount": 0, "gst_percent": gst, "sku": sku})
                n += 1
            self._refresh_totals(tab.name)
            try:
                w["repeat_note"].configure(
                    text=f"Loaded {n} item(s) from bill {last['bill_no']} "
                         f"dated {last['date']} (current prices).")
            except Exception:
                pass

        SearchPicker(
            self, "Repeat last bill \u2014 choose customer",
            lambda q: self.db.list_customers(q),
            lambda c: (f"{c['name']}  \u2014 {c['phone']}"
                       + ("  [wholesale]" if c["is_wholesale"] else "  [retail]")),
            on_pick)


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


class InvoiceDesignFrame(ctk.CTkFrame):

    def __init__(self, parent, db, app):
        super().__init__(parent, fg_color="transparent")
        self.db, self.app = db, app
        prefs = db.print_prefs()

        ctk.CTkLabel(self, text="Invoice Design",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                         anchor="w", pady=(4, 2))
        ctk.CTkLabel(self, text="Everything here is saved and used on every "
                                "invoice you print.",
                     text_color="gray").pack(anchor="w", pady=(0, 8))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        left = ctk.CTkScrollableFrame(body, width=340)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        def section(title):
            ctk.CTkLabel(left, text=title,
                         font=ctk.CTkFont(size=14, weight="bold")).pack(
                             anchor="w", pady=(10, 4), padx=4)

        self.toggles = {}

        def toggle(key, label, default=True):
            v = ctk.BooleanVar(value=prefs.get(key, default))
            ctk.CTkCheckBox(left, text=label, variable=v,
                            command=self.refresh_preview).pack(
                                anchor="w", padx=4, pady=2)
            self.toggles[key] = v

        section("Shop header")
        toggle("show_tagline", "Show tagline")
        toggle("show_address", "Show address")
        toggle("show_phone", "Show phone")
        toggle("show_gstin", "Show GSTIN")
        ctk.CTkLabel(left, text="Shop logo (PNG/JPG)").pack(anchor="w",
                                                             padx=4, pady=(6, 2))
        self.logo_row = ctk.CTkFrame(left, fg_color="transparent")
        self.logo_row.pack(fill="x", padx=4)
        ctk.CTkButton(self.logo_row, text="Choose logo\u2026", width=130,
                      command=self.choose_logo).pack(side="left", padx=(0, 6))
        ctk.CTkButton(self.logo_row, text="Remove", width=80,
                      fg_color="gray", command=self.remove_logo).pack(
                          side="left")
        self.logo_lbl = ctk.CTkLabel(left, text="", text_color="gray",
                                     font=ctk.CTkFont(size=11))
        self.logo_lbl.pack(anchor="w", padx=4)
        self._pending_logo = prefs.get("logo_path") or ""
        self._show_logo_name()

        section("Title & text")
        ctk.CTkLabel(left, text="Invoice title").pack(anchor="w", padx=4)
        self.title_e = ctk.CTkEntry(left)
        self.title_e.insert(0, prefs.get("invoice_title") or "TAX INVOICE")
        self.title_e.pack(fill="x", padx=4, pady=(0, 4))
        self.title_e.bind("<KeyRelease>", lambda e: self.refresh_preview())
        ctk.CTkLabel(left, text="Text size").pack(anchor="w", padx=4)
        self.font_var = ctk.StringVar(
            value={"compact": "Compact", "standard": "Standard",
                   "large": "Large"}.get(prefs.get("font_size"), "Standard"))
        ctk.CTkSegmentedButton(left, values=["Compact", "Standard", "Large"],
                               variable=self.font_var,
                               command=lambda v: self.refresh_preview()).pack(
                                   fill="x", padx=4, pady=(0, 4))
        ctk.CTkLabel(left, text="Accent color").pack(anchor="w", padx=4)
        inv = {v: k for k, v in ACCENTS.items()}
        self.accent_var = ctk.StringVar(value=inv.get(prefs["accent"],
                                                     "Green"))
        ctk.CTkOptionMenu(left, values=list(ACCENTS.keys()),
                          variable=self.accent_var,
                          command=lambda v: self.refresh_preview()).pack(
                              fill="x", padx=4, pady=(0, 4))

        section("Columns & tables")
        toggle("show_item_codes", "Show item codes / SKU")
        toggle("show_discounts", "Show discount column")
        toggle("show_hsn", "Show HSN column (A4 only)", default=False)
        toggle("show_gst_table", "Show GST slab breakup table")

        section("Bill details")
        toggle("show_roundoff", "Show round-off line")
        toggle("show_customer_address", "Show customer address")
        toggle("show_payment_badge", "Show CREDIT \u2014 due badge")
        toggle("show_signature", "Show signature lines (A4 only)")

        section("Footer")
        ctk.CTkLabel(left, text="Terms & conditions / notes").pack(
            anchor="w", padx=4)
        self.terms_t = ctk.CTkTextbox(left, height=70)
        self.terms_t.insert("1.0", prefs.get("footer_note") or "")
        self.terms_t.pack(fill="x", padx=4, pady=(0, 4))
        self.terms_t.bind("<KeyRelease>", lambda e: self.refresh_preview())
        toggle("show_thankyou", "Show thank-you message")
        ctk.CTkLabel(left, text="Thank-you text").pack(anchor="w", padx=4)
        self.thankyou_e = ctk.CTkEntry(left)
        self.thankyou_e.insert(0, prefs.get("thankyou_text")
                               or "Thank you for your business!")
        self.thankyou_e.pack(fill="x", padx=4, pady=(0, 4))
        self.thankyou_e.bind("<KeyRelease>", lambda e: self.refresh_preview())

        section("Paper & numbering")
        ctk.CTkLabel(left, text="Default paper").pack(anchor="w", padx=4)
        self.paper_var = ctk.StringVar(
            value="Thermal 80mm" if prefs.get("paper") == "thermal" else "A4")
        ctk.CTkSegmentedButton(left, values=["A4", "Thermal 80mm"],
                               variable=self.paper_var,
                               command=lambda v: self.refresh_preview()).pack(
                                   fill="x", padx=4, pady=(0, 4))
        ctk.CTkLabel(left, text="Default copies").pack(anchor="w", padx=4)
        self.copies_e = ctk.CTkEntry(left, width=80)
        self.copies_e.insert(0, db.get_setting("print_copies", "1") or "1")
        self.copies_e.pack(anchor="w", padx=4, pady=(0, 4))
        ctk.CTkLabel(left, text="Invoice number prefix").pack(anchor="w",
                                                              padx=4)
        self.prefix_e = ctk.CTkEntry(left, width=120)
        self.prefix_e.insert(0, prefs.get("number_prefix") or "BB-")
        self.prefix_e.pack(anchor="w", padx=4, pady=(0, 2))
        nxt = int(db.get_setting("bill_counter", "1") or 1)
        self.next_lbl = ctk.CTkLabel(
            left,
            text=f"Next bill number: {(prefs.get('number_prefix') or 'BB-')}"
                 f"{nxt:04d}  (updates when you type)",
            text_color="gray", font=ctk.CTkFont(size=11))
        self.next_lbl.pack(anchor="w", padx=4, pady=(0, 4))
        self.prefix_e.bind("<KeyRelease>", self._update_next_preview)

        self.err_lbl = ctk.CTkLabel(left, text="", text_color="#b3261e",
                                    font=ctk.CTkFont(size=12))
        self.err_lbl.pack(anchor="w", padx=4, pady=(4, 0))
        ctk.CTkButton(left, text="Save invoice design", fg_color="#1f6f43",
                      hover_color="#175733",
                      command=self.save).pack(fill="x", padx=4, pady=12)

        right = ctk.CTkFrame(body)
        right.grid(row=0, column=1, sticky="nsew")
        ctk.CTkLabel(right, text="Live preview",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(
                         anchor="w", padx=10, pady=(8, 2))
        ctk.CTkLabel(right, text="Real PDF render when possible \u2014 "
                                 "otherwise a close approximation.",
                     text_color="gray",
                     font=ctk.CTkFont(size=11)).pack(anchor="w", padx=10)
        self.preview = ctk.CTkScrollableFrame(right, fg_color="white")
        self.preview.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.refresh_preview()

    def _update_next_preview(self, _e=None):
        nxt = int(self.db.get_setting("bill_counter", "1") or 1)
        self.next_lbl.configure(
            text=f"Next bill number: {(self.prefix_e.get().strip() or 'BB-')}"
                 f"{nxt:04d}  (updates when you type)")

    def _show_logo_name(self):
        p = self._pending_logo
        self.logo_lbl.configure(
            text=f"Logo: {Path(p).name}" if p else "No logo set")

    def choose_logo(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Choose shop logo",
            filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All files", "*.*")])
        if not path:
            return
        try:
            dest_dir = data_dir() / "logos"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / ("logo" + Path(path).suffix.lower())
            shutil.copy2(path, dest)
            self._pending_logo = str(dest)
            self._show_logo_name()
            self.refresh_preview()
        except Exception as e:
            messagebox.showerror("Logo", f"Could not use that file:\n{e}")

    def remove_logo(self):
        self._pending_logo = ""
        self._show_logo_name()
        self.refresh_preview()

    def collect_prefs(self):
        font_map = {"Compact": "compact", "Standard": "standard",
                    "Large": "large"}
        return {
            "accent": ACCENTS[self.accent_var.get()],
            "paper": ("thermal" if self.paper_var.get() == "Thermal 80mm"
                      else "A4"),
            "show_gstin": self.toggles["show_gstin"].get(),
            "show_item_codes": self.toggles["show_item_codes"].get(),
            "show_discounts": self.toggles["show_discounts"].get(),
            "header_note": self.db.get_setting("print_header_note"),
            "footer_note": self.terms_t.get("1.0", "end").strip(),
            "invoice_title": self.title_e.get().strip() or "TAX INVOICE",
            "font_size": font_map[self.font_var.get()],
            "show_tagline": self.toggles["show_tagline"].get(),
            "show_address": self.toggles["show_address"].get(),
            "show_phone": self.toggles["show_phone"].get(),
            "show_gst_table": self.toggles["show_gst_table"].get(),
            "show_hsn": self.toggles["show_hsn"].get(),
            "show_roundoff": self.toggles["show_roundoff"].get(),
            "show_customer_address":
                self.toggles["show_customer_address"].get(),
            "show_payment_badge": self.toggles["show_payment_badge"].get(),
            "show_signature": self.toggles["show_signature"].get(),
            "show_thankyou": self.toggles["show_thankyou"].get(),
            "thankyou_text": (self.thankyou_e.get().strip()
                              or "Thank you for your business!"),
            "logo_path": self._pending_logo,
            "number_prefix": self.prefix_e.get().strip() or "BB-",
        }

    def _render_pdf_image(self, prefs, prof):
        try:
            import fitz  # PyMuPDF — optional
            from PIL import Image
        except ImportError:
            return None
        try:
            import tempfile
            from printing import generate_invoice_pdf
            tmp = Path(tempfile.gettempdir()) / "billbook_design_preview.pdf"
            generate_invoice_pdf(DESIGN_SAMPLE_BILL, DESIGN_SAMPLE_ITEMS,
                                 prof, prefs, tmp)
            doc = fitz.open(str(tmp))
            pix = doc[0].get_pixmap(dpi=110)
            doc.close()
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            max_h = 1000
            if img.height > max_h:
                img = img.resize((int(img.width * max_h / img.height), max_h))
            return ctk.CTkImage(light_image=img, dark_image=img,
                                size=img.size)
        except Exception:
            return None

    def refresh_preview(self):
        prefs = self.collect_prefs()
        prof = self.db.shop_profile()
        for ch in self.preview.winfo_children():
            ch.destroy()
        photo = self._render_pdf_image(prefs, prof)
        if photo is not None:
            lbl = ctk.CTkLabel(self.preview, image=photo, text="",
                               fg_color="white")
            lbl.pack(padx=8, pady=8)
            self.preview._pdf_img = photo  # keep a reference (no GC)
        else:
            render_invoice_preview(self.preview, prof, DESIGN_SAMPLE_BILL,
                                   DESIGN_SAMPLE_ITEMS, prefs)

    def save(self):
        self.err_lbl.configure(text="")
        title = self.title_e.get().strip()
        if not title:
            self.err_lbl.configure(text="Invoice title can't be empty.")
            return
        try:
            copies = int(self.copies_e.get() or 1)
            if copies < 1:
                raise ValueError
        except ValueError:
            self.err_lbl.configure(
                text="Default copies must be a whole number of 1 or more.")
            return
        prefix = self.prefix_e.get().strip()
        if not prefix or len(prefix) > 8 or not all(
                ch.isalnum() or ch in "-_/" for ch in prefix):
            self.err_lbl.configure(
                text="Prefix: 1\u20138 characters, letters/digits/- _ / only.")
            return
        p = self.collect_prefs()
        self.db.set_setting("print_accent", p["accent"])
        self.db.set_setting("print_paper", p["paper"])
        self.db.set_setting("print_copies", str(copies))
        self.db.set_setting("invoice_title", title)
        self.db.set_setting("invoice_font_size", p["font_size"])
        for key in ("show_tagline", "show_address", "show_phone",
                    "show_hsn", "show_gst_table", "show_roundoff",
                    "show_customer_address", "show_payment_badge",
                    "show_signature", "show_thankyou"):
            self.db.set_setting(f"invoice_{key}", "1" if p[key] else "0")
        self.db.set_setting("print_show_gstin",
                            "1" if p["show_gstin"] else "0")
        self.db.set_setting("print_show_item_codes",
                            "1" if p["show_item_codes"] else "0")
        self.db.set_setting("print_show_discounts",
                            "1" if p["show_discounts"] else "0")
        self.db.set_setting("print_footer_note", p["footer_note"])
        self.db.set_setting("invoice_thankyou_text", p["thankyou_text"])
        self.db.set_setting("invoice_logo_path", p["logo_path"])
        self.db.set_setting("invoice_number_prefix", prefix)
        messagebox.showinfo("Invoice Design", "Invoice design saved.\n"
                            "It applies to every invoice from now on.")
        self.refresh_preview()


class CustomersFrame(ctk.CTkFrame):
    def __init__(self, parent, db, app):
        super().__init__(parent, fg_color="transparent")
        self.db, self.app = db, app
        ctk.CTkLabel(self, text="Customer ledger (khata)",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                         anchor="w", pady=(4, 8))

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", pady=4)
        self.search = ctk.CTkEntry(top, placeholder_text="Search customers...",
                                   width=260)
        self.search.pack(side="left", padx=4)
        self.search.bind("<KeyRelease>", lambda e: self.refresh())
        ctk.CTkButton(top, text="Add customer",
                      command=self.add_dialog).pack(side="left", padx=4)
        ctk.CTkButton(top, text="Outstanding reminders",
                      command=self.outstanding_reminders).pack(side="left", padx=4)
        ctk.CTkButton(top, text="Export outstanding CSV",
                      command=self.export_outstanding_csv).pack(side="left", padx=4)
        ctk.CTkButton(top, text="Record payment received", fg_color="#1f6f43",
                      hover_color="#175733",
                      command=self.payment_dialog).pack(side="left", padx=4)
        ctk.CTkButton(top, text="Statement",
                      command=self.statement_dialog).pack(side="left", padx=4)
        ctk.CTkButton(top, text="Delete",
                      fg_color="#b3261e", hover_color="#8f1d17",
                      command=self.delete_selected).pack(side="right", padx=4)
        self.outstanding_lbl = ctk.CTkLabel(top, text="",
                                     font=ctk.CTkFont(weight="bold"))
        self.outstanding_lbl.pack(side="right", padx=12)

        fr, self.tv = tree(self, ("Name", "Phone", "Type", "Outstanding \u20b9"),
                           widths=(220, 130, 90, 110), height=18)
        fr.pack(fill="both", expand=True, pady=6)
        self.tv.bind("<Double-1>", lambda e: self.statement_dialog())
        self.refresh()

    def refresh(self):
        for r in self.tv.get_children():
            self.tv.delete(r)
        for c in self.db.list_customers(self.search.get().strip()):
            bal = float(c["balance"])
            bal_txt = (f"Advance {-bal:.2f}" if bal < -0.004
                        else f"{bal:.2f}")
            self.tv.insert("", "end", iid=c["id"], values=(
                c["name"], c["phone"],
                "Wholesale" if c["is_wholesale"] else "Retail",
                bal_txt))
        self.outstanding_lbl.configure(
            text=f"Total outstanding: {money(self.db.total_outstanding())}")

    def outstanding_reminders(self):
        from new_features import open_outstanding_reminders_dialog
        shop = self.db.shop_profile().get("shop_name") or ""
        open_outstanding_reminders_dialog(self, self.db, shop)

    def export_outstanding_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV files", "*.csv")],
            title="Export outstanding to CSV",
            initialfile="billbook_outstanding.csv")
        if not path:
            return
        try:
            from new_features import export_outstanding_csv
            export_outstanding_csv(self.db, path)
            messagebox.showinfo("Export", f"Outstanding list exported to {path}")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Export", f"Could not export: {e}")

    def selected_id(self):
        sel = self.tv.selection()
        if not sel:
            messagebox.showinfo("Customers", "Select a customer first.")
            return None
        return int(sel[0])

    def add_dialog(self):
        win = ctk.CTkToplevel(self)
        win.title("Add customer")
        win.geometry("380x340")
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(win, text="Name *").pack(anchor="w", padx=14, pady=(10, 0))
        n_e = ctk.CTkEntry(win)
        n_e.pack(fill="x", padx=14)
        ctk.CTkLabel(win, text="Phone").pack(anchor="w", padx=14, pady=(6, 0))
        p_e = ctk.CTkEntry(win)
        p_e.pack(fill="x", padx=14)
        ctk.CTkLabel(win, text="Address").pack(anchor="w", padx=14, pady=(6, 0))
        a_e = ctk.CTkEntry(win)
        a_e.pack(fill="x", padx=14)
        ws = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(win, text="Wholesale customer", variable=ws).pack(
            anchor="w", padx=14, pady=10)

        def save():
            if not n_e.get().strip():
                messagebox.showerror("Customers", "Name is required.")
                return
            self.db.add_customer(n_e.get().strip(), p_e.get().strip(),
                                 a_e.get().strip(), ws.get())
            win.destroy()
            self.refresh()

        ctk.CTkButton(win, text="Save", command=save).pack(pady=12)

    def payment_dialog(self):
        cid = self.selected_id()
        if cid is None:
            return
        c = self.db.get_customer(cid)
        outstanding = float(c["balance"])
        if outstanding <= 0.004:
            messagebox.showinfo("Payment",
                                f"{c['name']} has no outstanding balance.")
            return
        win = ctk.CTkToplevel(self)
        win.title("Collect payment")
        win.geometry("380x420")
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(
            win, text=f"{c['name']} \u2014 outstanding {money(outstanding)}",
            font=ctk.CTkFont(weight="bold")).pack(pady=10)
        ctk.CTkLabel(win, text="Amount received (\u20b9) *").pack(
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
        note_e = ctk.CTkEntry(win, placeholder_text="e.g. partial payment")
        note_e.pack(fill="x", padx=14)

        def save():
            try:
                amt = float(amt_e.get())
                assert amt > 0
            except (ValueError, AssertionError):
                messagebox.showerror("Payment", "Enter a valid amount.")
                return
            if amt - outstanding > 0.004:
                messagebox.showerror(
                    "Payment",
                    f"Amount exceeds the outstanding balance ({money(outstanding)}).")
                return
            pay_date = date_e.get().strip() or today_iso()
            pay_id = self.db.record_payment(
                cid, amt, note_e.get().strip(), mode_var.get(), pay_date)
            win.destroy()
            self.refresh()
            try:
                from printing import (generate_payment_receipt_pdf,
                                      print_pdf)
                pay = self.db._one("SELECT * FROM payments WHERE id=?",
                                   (pay_id,))
                cust = self.db.get_customer(cid)
                pdf = generate_payment_receipt_pdf(
                    pay, cust, self.db.shop_profile(), self.db.print_prefs())
                ok, pmsg = print_pdf(pdf)
                if ok:
                    messagebox.showinfo(
                        "Payment",
                        f"Recorded {money(amt)} from {c['name']}.\n"
                        f"Receipt sent to printer.")
                else:
                    messagebox.showinfo(
                        "Payment",
                        f"Recorded {money(amt)} from {c['name']}.\n\n{pmsg}")
            except Exception as e:  # noqa: BLE001
                messagebox.showinfo(
                    "Payment",
                    f"Recorded {money(amt)} from {c['name']}.\n"
                    f"(Receipt PDF failed: {e})")

        amt_e.bind("<Return>", lambda e: save())
        ctk.CTkButton(win, text="Record & print receipt",
                      command=save).pack(pady=14)

    def statement_dialog(self):
        cid = self.selected_id()
        if cid is None:
            return
        c = self.db.get_customer(cid)
        win = ctk.CTkToplevel(self)
        win.title(f"Statement \u2014 {c['name']}")
        win.geometry("640x520")
        win.transient(self)

        ctk.CTkLabel(win, text=f"{c['name']}  \u00b7  {c['phone']}",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(
                         anchor="w", padx=12, pady=(8, 2))
        ctk.CTkLabel(win, text=f"Outstanding balance: {money(c['balance'])}",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color="#b3261e").pack(anchor="w", padx=12, pady=4)

        tabs = ctk.CTkTabview(win)
        tabs.pack(fill="both", expand=True, padx=10, pady=8)
        tabs.add("Bills")
        tabs.add("Payments")
        fr, tv = tree(tabs.tab("Bills"),
                      ("Bill No", "Date", "Payment", "Total"),
                      widths=(90, 100, 90, 110), height=10)
        fr.pack(fill="both", expand=True, padx=8, pady=8)
        for b in self.db.customer_bills(cid):
            tv.insert("", "end", values=(b["bill_no"], b["date"],
                                         b["payment_type"],
                                         money(b["grand_total"])))
        fr2, tv2 = tree(tabs.tab("Payments"),
                        ("Date", "Amount", "Mode", "Note"),
                        widths=(110, 100, 70, 220), height=10)
        fr2.pack(fill="both", expand=True, padx=8, pady=8)
        for p in self.db.customer_payments(cid):
            tv2.insert("", "end", values=(p["date"], money(p["amount"]),
                                          p.get("mode") or "Cash",
                                          p["note"]))

    def delete_selected(self):
        cid = self.selected_id()
        if cid is None:
            return
        c = self.db.get_customer(cid)
        if not messagebox.askyesno("Delete", f"Delete '{c['name']}'?"):
            return
        if not self.db.delete_customer(cid):
            messagebox.showerror("Delete",
                                 "This customer has bills on record and "
                                 "cannot be deleted.")
        self.refresh()


class InvoicesFrame(ctk.CTkFrame):
    def __init__(self, parent, db, app):
        super().__init__(parent, fg_color="transparent")
        self.db, self.app = db, app
        ctk.CTkLabel(self, text="Invoices \u2014 past bills",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                         anchor="w", pady=(4, 8))

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", pady=4)
        self.search = ctk.CTkEntry(top, placeholder_text="Search bill no / customer...",
                                   width=280)
        self.search.pack(side="left", padx=4)
        self.search.bind("<KeyRelease>", lambda e: self.refresh())
        ctk.CTkLabel(top, text="From").pack(side="left", padx=(10, 2))
        self.date_e = ctk.CTkEntry(top, width=110,
                                   placeholder_text="YYYY-MM-DD")
        self.date_e.pack(side="left", padx=4)
        ctk.CTkLabel(top, text="To").pack(side="left", padx=(6, 2))
        self.to_e = ctk.CTkEntry(top, width=110,
                                 placeholder_text="YYYY-MM-DD")
        self.to_e.pack(side="left", padx=4)
        self.date_e.bind("<KeyRelease>", lambda e: self.refresh())
        self.to_e.bind("<KeyRelease>", lambda e: self.refresh())
        ctk.CTkButton(top, text="Today",
                      command=lambda: (self.date_e.delete(0, "end"),
                                       self.date_e.insert(0, today_iso()),
                                       self.to_e.delete(0, "end"),
                                       self.to_e.insert(0, today_iso()),
                                       self.refresh())).pack(side="left",
                                                              padx=2)
        ctk.CTkButton(top, text="Clear",
                      command=lambda: (self.date_e.delete(0, "end"),
                                       self.to_e.delete(0, "end"),
                                       self.search.delete(0, "end"),
                                       self.refresh())).pack(side="left",
                                                              padx=2)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", pady=4)
        ctk.CTkButton(btns, text="Reprint", command=self.reprint).pack(
            side="left", padx=4)
        ctk.CTkButton(btns, text="View items / history",
                      command=self.view_detail).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Edit bill (reopen)",
                      command=self.edit_bill).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Return items", fg_color="#0b5fa5",
                      hover_color="#084a82",
                      command=self.return_items).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="WhatsApp", fg_color="#1f6f43",
                      hover_color="#175733",
                      command=self.whatsapp_share).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="New challan",
                      command=self.new_challan).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Delete bill", fg_color="#b3261e",
                      hover_color="#8f1d17",
                      command=self.delete_bill).pack(side="right", padx=4)

        fr, self.tv = tree(self, ("Bill No", "Date", "Customer", "Payment",
                                  "Items", "Total"),
                           widths=(90, 100, 220, 90, 60, 120), height=20)
        fr.pack(fill="both", expand=True, pady=6)
        self.tv.bind("<Double-1>", lambda e: self.view_detail())
        self.refresh()

    def refresh(self):
        for r in self.tv.get_children():
            self.tv.delete(r)
        start = self.date_e.get().strip() or None
        end = self.to_e.get().strip() or None
        if start or end:
            from new_features import sale_register
            bills = sale_register(self.db, start or "2000-01-01",
                                 end or today_iso(),
                                 self.search.get().strip())
        else:
            bills = self.db.list_bills(self.search.get().strip())
        for b in bills:
            n_items = len(self.db.bill_items(b["id"]))
            self.tv.insert("", "end", iid=b["id"], values=(
                b["bill_no"], b["date"], b["customer_name"] or "Walk-in",
                b["payment_type"], n_items, money(b["grand_total"])))

    def selected_id(self):
        sel = self.tv.selection()
        if not sel:
            messagebox.showinfo("Invoices", "Select a bill first.")
            return None
        return int(sel[0])

    def new_challan(self):
        from shop_ui import ChallanDialog
        ChallanDialog(self, self.db, on_done=lambda cid: None)

    def reprint(self):
        bid = self.selected_id()
        if bid is None:
            return
        bill = self.db.get_bill(bid)
        items = self.db.bill_items(bid)
        for it in items:
            p = self.db.get_product(it["product_id"]) if it.get("product_id") else None
            it["sku"] = (p or {}).get("sku", "")
        PrintDialog(self, self.db, bill, items)

    def view_detail(self):
        bid = self.selected_id()
        if bid is None:
            return
        b = self.db.get_bill(bid)
        items = self.db.bill_items(bid)
        hist = self.db.bill_history(bid)
        win = ctk.CTkToplevel(self)
        win.title(f"Bill {b['bill_no']}")
        win.geometry("620x560")
        win.transient(self)
        ctk.CTkLabel(win,
                     text=f"{b['bill_no']}  \u00b7  {b['date']}  \u00b7  "
                          f"{b.get('customer_name') or 'Walk-in'}  \u00b7  "
                          f"{b['payment_type']}",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
                         anchor="w", padx=12, pady=8)
        fr, tv = tree(win, ("Item", "Qty", "Rate", "Disc.", "GST%", "Amount"),
                      widths=(220, 70, 80, 70, 55, 100), height=10)
        fr.pack(fill="both", expand=True, padx=12, pady=4)
        for it in items:
            tv.insert("", "end", values=(
                it["name"], f"{it['qty']:g} {it['unit']}", money(it["price"]),
                money(it["line_discount"]) if it["line_discount"] else "\u2014",
                f"{it['gst_percent']:g}%", money(it["line_total"])))
        ctk.CTkLabel(win,
                     text=f"Subtotal {money(b['subtotal'])}  \u00b7  "
                          f"GST {money(b['gst_total'])}  \u00b7  "
                          f"Disc. {money(b['discount'])}  \u00b7  "
                          f"Round-off {money(b['round_off'])}",
                     ).pack(anchor="w", padx=12, pady=4)
        ctk.CTkLabel(win, text=f"Grand total: {money(b['grand_total'])}",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(
                         anchor="w", padx=12, pady=2)
        ctk.CTkLabel(win, text="Bill history",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w",
                                                           padx=12, pady=(8, 2))
        box = ctk.CTkTextbox(win, height=110)
        box.pack(fill="x", padx=12, pady=(0, 12))
        for h in hist:
            box.insert("end", f"{h['date']} \u2014 {h['action']}: {h['details']}\n")
        box.configure(state="disabled")

    def edit_bill(self):
        bid = self.selected_id()
        if bid is None:
            return
        b = self.db.get_bill(bid)
        if not messagebox.askyesno(
                "Edit bill",
                f"Reopen {b['bill_no']} for editing?\n\n"
                "Stock will be reversed and re-applied, and the edit is "
                "recorded in the bill history."):
            return
        self.app.open_billing_tab(edit_bill_id=bid)

    def delete_bill(self):
        bid = self.selected_id()
        if bid is None:
            return
        b = self.db.get_bill(bid)
        if not messagebox.askyesno(
                "Delete bill",
                f"Delete {b['bill_no']} ({money(b['grand_total'])})?\n\n"
                "Stock and the customer's outstanding balance will be reversed. This cannot be undone."):
            return
        self.db.delete_bill(bid)
        self.refresh()
        messagebox.showinfo("Invoices", f"Bill {b['bill_no']} deleted.")

    def return_items(self):
        bid = self.selected_id()
        if bid is None:
            return
        from returns_ui import ReturnDialog

        def done(rid):
            self.refresh()
            try:
                cn = self.db.get_return(rid)
                items = self.db.return_items(rid)
                pdf = printing.generate_credit_note_pdf(
                    cn, items, self.db.shop_profile(), self.db.print_prefs())
                printing.open_pdf(pdf)
                messagebox.showinfo(
                    "Credit note",
                    f"Credit note PDF saved at:\n{pdf}")
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("Credit note",
                                     f"Could not build the PDF: {e}")

        ReturnDialog(self, self.db, bid, on_done=done)

    def whatsapp_share(self):
        bid = self.selected_id()
        if bid is None:
            return
        from returns_ui import share_bill_whatsapp
        share_bill_whatsapp(self, self.db, bid)


class ReportsFrame(ctk.CTkFrame):
    def __init__(self, parent, db, app):
        super().__init__(parent, fg_color="transparent")
        self.db, self.app = db, app
        ctk.CTkLabel(self, text="Reports",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                         anchor="w", pady=(4, 8))

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", pady=4)
        ctk.CTkLabel(top, text="From").pack(side="left", padx=(4, 2))
        self.from_e = ctk.CTkEntry(top, width=110)
        self.from_e.pack(side="left", padx=4)
        ctk.CTkLabel(top, text="To").pack(side="left", padx=(4, 2))
        self.to_e = ctk.CTkEntry(top, width=110)
        self.to_e.pack(side="left", padx=4)

        def set_range(days):
            end = date.today()
            start = end - timedelta(days=days - 1)
            self.from_e.delete(0, "end")
            self.from_e.insert(0, start.isoformat())
            self.to_e.delete(0, "end")
            self.to_e.insert(0, end.isoformat())
            self.refresh()

        ctk.CTkButton(top, text="Today", width=70,
                      command=lambda: set_range(1)).pack(side="left", padx=2)
        ctk.CTkButton(top, text="7 days", width=70,
                      command=lambda: set_range(7)).pack(side="left", padx=2)
        ctk.CTkButton(top, text="30 days", width=70,
                      command=lambda: set_range(30)).pack(side="left", padx=2)
        ctk.CTkButton(top, text="Refresh", command=self.refresh).pack(
            side="left", padx=8)
        ctk.CTkButton(top, text="Export CSV",
                      command=self.export_csv).pack(side="left", padx=4)

        self.cards = ctk.CTkFrame(self, fg_color="transparent")
        self.cards.pack(fill="x", pady=6)

        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True, pady=6)
        tabs.add("Day-wise sales")
        tabs.add("Month-wise sales")
        tabs.add("GST summary")
        tabs.add("Top products")
        tabs.add("Item-wise profit")
        tabs.add("Party-wise sales")

        fr, self.tv_day = tree(tabs.tab("Day-wise sales"),
                               ("Date", "Bills", "Sales", "GST collected"),
                               widths=(120, 70, 130, 130), height=12)
        fr.pack(fill="both", expand=True, padx=8, pady=8)
        frm, self.tv_month = tree(tabs.tab("Month-wise sales"),
                                  ("Month", "Bills", "Sales", "Discount",
                                   "GST collected"),
                                  widths=(120, 70, 130, 130, 130), height=12)
        frm.pack(fill="both", expand=True, padx=8, pady=8)
        fr2, self.tv_gst = tree(tabs.tab("GST summary"),
                                ("GST slab", "Taxable value", "CGST", "SGST",
                                 "Total GST"),
                                widths=(90, 130, 110, 110, 130), height=12)
        fr2.pack(fill="both", expand=True, padx=8, pady=8)
        fr3, self.tv_top = tree(tabs.tab("Top products"),
                                ("Product", "Qty sold", "Amount"),
                                widths=(260, 100, 140), height=12)
        fr3.pack(fill="both", expand=True, padx=8, pady=8)
        fr4, self.tv_profit = tree(tabs.tab("Item-wise profit"),
                                   ("Product", "Qty", "Sales", "Cost",
                                    "Profit"),
                                   widths=(260, 100, 130, 130, 130),
                                   height=12)
        fr4.pack(fill="both", expand=True, padx=8, pady=8)
        fr5, self.tv_cust = tree(tabs.tab("Party-wise sales"),
                                 ("#", "Customer", "Phone", "Bills",
                                  "Total purchases", "Last purchase"),
                                 widths=(50, 260, 130, 70, 140, 120),
                                 height=12)
        fr5.pack(fill="both", expand=True, padx=8, pady=8)
        set_range(30)  # fills the date boxes and renders everything

    def export_csv(self):
        start = self.from_e.get().strip() or "2000-01-01"
        end = self.to_e.get().strip() or today_iso()
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV files", "*.csv")],
            title="Export report to CSV",
            initialfile=f"billbook_report_{start}_to_{end}.csv")
        if not path:
            return
        try:
            from new_features import export_reports_csv
            export_reports_csv(self.db, start, end, path)
            messagebox.showinfo("Export", f"Report exported to {path}")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Export", f"Could not export: {e}")

    def refresh(self):
        start = self.from_e.get().strip() or "2000-01-01"
        end = self.to_e.get().strip() or today_iso()
        s = self.db.sales_between(start, end)
        profit = self.db.profit_estimate(start, end)

        for ch in self.cards.winfo_children():
            ch.destroy()
        for title, value, color in [
                ("Bills", str(s["n"]), "#0b5fa5"),
                ("Total sales", money(s["t"]), "#1f6f43"),
                ("Discount given", money(s["d"]), "#b26a00"),
                ("GST collected", money(s["g"]), "#5b2d8e"),
                ("Profit estimate*", money(profit), "#1f6f43")]:
            card = ctk.CTkFrame(self.cards, border_width=2, border_color=color)
            card.pack(side="left", fill="x", expand=True, padx=6)
            ctk.CTkLabel(card, text=title, text_color="gray").pack(
                anchor="w", padx=10, pady=(6, 0))
            ctk.CTkLabel(card, text=value,
                         font=ctk.CTkFont(size=16, weight="bold")).pack(
                             anchor="w", padx=10, pady=(0, 8))
        ctk.CTkLabel(self.cards,
                     text="* Profit = sale price \u2212 purchase price per line; "
                          "approx, ignores overheads.",
                     text_color="gray", font=ctk.CTkFont(size=11)).pack(
                         side="left", padx=8)

        for tv in (self.tv_day, self.tv_month, self.tv_gst, self.tv_top,
                  self.tv_profit, self.tv_cust):
            for r in tv.get_children():
                tv.delete(r)
        for d in self.db.daywise_sales(start, end):
            self.tv_day.insert("", "end", values=(d["date"], d["n"],
                                                  money(d["t"]), money(d["g"])))
        from new_features import month_wise_sales
        months = month_wise_sales(self.db, start, end)
        for m in months:
            self.tv_month.insert("", "end", values=(
                m["month"], m["bills"], money(m["sales"]),
                money(m["discount"]), money(m["gst"])))
        if months:
            self.tv_month.insert("", "end", values=(
                "Total", sum(m["bills"] for m in months),
                money(sum(m["sales"] for m in months)),
                money(sum(m["discount"] for m in months)),
                money(sum(m["gst"] for m in months))))
        for g in self.db.gst_summary(start, end):
            taxable, gst = g["taxable"], g["gst"]
            self.tv_gst.insert("", "end", values=(
                f"{g['gst_percent']:g}%", money(taxable), money(gst / 2),
                money(gst / 2), money(gst)))
        for t in self.db.top_products(start, end, limit=50):
            self.tv_top.insert("", "end", values=(
                t["name"], f"{t['qty']:g} {t['unit']}", money(t["total"])))
        from new_features import item_wise_profit
        for p in item_wise_profit(self.db, start, end):
            self.tv_profit.insert("", "end", values=(
                p["name"], f"{p['qty']:g} {p['unit']}", money(p["sales"]),
                money(p["cost"]), money(p["profit"])))
        from new_features import party_wise_sales
        cust = party_wise_sales(self.db, start, end)
        for c in cust:
            self.tv_cust.insert("", "end", values=(
                c["rank"], c["name"], c["phone"], c["bills"],
                money(c["total"]), c["last"]))
        if cust:
            self.tv_cust.insert("", "end", values=(
                "", "Total", "", sum(c["bills"] for c in cust),
                money(sum(c["total"] for c in cust)), ""))




class SettingsFrame(ctk.CTkFrame):
    def __init__(self, parent, db, app):
        super().__init__(parent, fg_color="transparent")
        self.db, self.app = db, app
        ctk.CTkLabel(self, text="Settings",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(
                         anchor="w", pady=(4, 8))

        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, pady=6)

        ctk.CTkLabel(scroll, text="Shop profile \u2014 printed on every bill",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(
                         anchor="w", pady=(4, 6))
        self.entries = {}
        for key, label in (("shop_name", "Shop / company name *"),
                           ("shop_tagline", "Tagline"),
                           ("shop_address", "Address"),
                           ("shop_phone", "Phone"),
                           ("shop_gstin", "GSTIN")):
            ctk.CTkLabel(scroll, text=label).pack(anchor="w", padx=4)
            e = ctk.CTkEntry(scroll, width=420)
            e.insert(0, db.get_setting(key))
            e.pack(anchor="w", padx=4, pady=(0, 6), fill="x")
            self.entries[key] = e

        ctk.CTkLabel(scroll, text="Bill print defaults",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(
                         anchor="w", pady=(12, 6))
        ctk.CTkLabel(scroll, text="Accent color").pack(anchor="w", padx=4)
        cur = db.get_setting("print_accent")
        cur_name = next((n for n, c in ACCENTS.items()
                         if c.lower() == cur.lower()), "Green")
        self.accent_var = ctk.StringVar(value=cur_name)
        ctk.CTkOptionMenu(scroll, values=list(ACCENTS.keys()),
                          variable=self.accent_var).pack(anchor="w", padx=4,
                                                         pady=(0, 6))

        ctk.CTkLabel(scroll, text="Paper size").pack(anchor="w", padx=4)
        self.paper_var = ctk.StringVar(
            value="Thermal 80mm"
            if db.get_setting("print_paper") == "thermal" else "A4")
        ctk.CTkSegmentedButton(scroll, values=["A4", "Thermal 80mm"],
                               variable=self.paper_var).pack(anchor="w",
                                                             padx=4,
                                                             pady=(0, 6))

        self.toggles = {}
        for key, label in (("print_show_gstin", "Show shop GSTIN on bills"),
                           ("print_show_item_codes", "Show item codes / SKU"),
                           ("print_show_discounts", "Show discount column")):
            v = ctk.BooleanVar(value=db.get_setting(key) == "1")
            ctk.CTkCheckBox(scroll, text=label, variable=v).pack(
                anchor="w", padx=4, pady=2)
            self.toggles[key] = v

        for key, label in (("print_header_note", "Header note"),
                           ("print_footer_note", "Footer note")):
            ctk.CTkLabel(scroll, text=label).pack(anchor="w", padx=4)
            e = ctk.CTkEntry(scroll, width=420)
            e.insert(0, db.get_setting(key))
            e.pack(anchor="w", padx=4, pady=(0, 6), fill="x")
            self.entries[key] = e

        ctk.CTkLabel(scroll, text="App updates",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(
                         anchor="w", pady=(12, 6))
        ctk.CTkLabel(scroll,
                     text="BillBook checks GitHub for updates when it starts. "
                          "You can also check right now:",
                     text_color="gray", wraplength=560,
                     justify="left").pack(anchor="w", padx=4)
        ctk.CTkButton(scroll, text="Check for updates",
                      command=self.check_updates).pack(anchor="w", padx=4,
                                                      pady=(6, 0))

        ctk.CTkButton(scroll, text="Save settings", fg_color="#1f6f43",
                      hover_color="#175733",
                      command=self.save).pack(anchor="w", padx=4, pady=14)

    def check_updates(self):
        def work():
            try:
                import updater
                status, sha = updater.check_update()
            except Exception:
                status, sha = "offline", None
            self.after(0, lambda: self._update_result(status, sha))
        threading.Thread(target=work, daemon=True).start()

    def _update_result(self, status, sha):
        if status == "available" and sha:
            self.app._update_sha = sha
            self.app._on_update_checked("available", sha)
            if messagebox.askyesno(
                    "Update available",
                    "A new version of BillBook is available.\n\n"
                    "Update now? (Takes a few minutes; your data is safe.)"):
                self.app._on_update_clicked()
        elif status == "offline":
            messagebox.showinfo("Updates",
                                "Could not reach GitHub.\n"
                                "Check your internet connection.")
        else:
            messagebox.showinfo("Updates",
                                "You already have the latest version.")

    def save(self):
        for key, e in self.entries.items():
            self.db.set_setting(key, e.get().strip())
        self.db.set_setting("print_accent", ACCENTS[self.accent_var.get()])
        self.db.set_setting("print_paper", "thermal"
                            if self.paper_var.get() == "Thermal 80mm"
                            else "A4")
        for key, v in self.toggles.items():
            self.db.set_setting(key, "1" if v.get() else "0")
        messagebox.showinfo("Settings", "Settings saved.")
        self.app.show("settings")
