"""
Vyro — shop expense tracker (Round 29).

The shop's own costs — rent, electricity, transport, packing, repairs,
stationery, miscellaneous — recorded by date with a payment mode
(Cash / UPI / Bank) and summed by month and category, so the owner can
see where the money goes besides stock purchases.

Separate from the Cash Book on purpose: the Cash Book tracks cash
movement, this tracks what it was spent on. Salaries are NOT here —
staff pay (Round 26) already tracks those, so they would double count.

Pure functions first (no GUI imports, so they can be tested headless);
the CustomTkinter dialog is at the bottom, imported lazily by shop_ui.
"""

from datetime import date

from db import EXPENSE_CATEGORIES, EXPENSE_MODES


def current_month():
    return date.today().strftime("%Y-%m")


def month_name(month):
    """'2026-11' -> 'November 2026' (falls back to the raw string)."""
    try:
        y, m = int(month[:4]), int(month[5:7])
        names = ["January", "February", "March", "April", "May", "June",
                 "July", "August", "September", "October", "November",
                 "December"]
        return f"{names[m - 1]} {y}"
    except (ValueError, IndexError):
        return month


def expense_month_rows(db, month):
    """This month's expenses, newest first."""
    return db.list_shop_expenses(month)


def expense_summary(db, month):
    """(total spent, expense count, {category: total}) for `month`."""
    return db.monthly_expense_summary(month)


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------
def open_shop_expenses_dialog(parent, db):
    """Shop expenses window: monthly costs by category, plus add/delete."""
    from tkinter import messagebox
    import customtkinter as ctk
    from tkinter import ttk

    win = ctk.CTkToplevel(parent)
    win.title("Shop expenses")
    win.geometry("820x620")
    win.transient(parent)

    RUPEE = "\u20b9"

    def money(n):
        return f"{RUPEE}{float(n):,.2f}"

    month_var = ctk.StringVar(value=current_month())

    top = ctk.CTkFrame(win, fg_color="transparent")
    top.pack(fill="x", padx=12, pady=(10, 2))
    ctk.CTkLabel(top, text="Shop expenses",
                 font=ctk.CTkFont(size=22, weight="bold")).pack(
                     side="left", padx=(0, 12))
    ctk.CTkLabel(top, text="Month (YYYY-MM)").pack(side="left", padx=(4, 2))
    month_e = ctk.CTkEntry(top, textvariable=month_var, width=90)
    month_e.pack(side="left", padx=4)

    def shift_month(delta):
        try:
            y, m = int(month_var.get()[:4]), int(month_var.get()[5:7])
        except ValueError:
            messagebox.showerror("Shop expenses",
                                 "Month must be YYYY-MM (e.g. 2026-11).")
            return
        m += delta
        while m < 1:
            m += 12
            y -= 1
        while m > 12:
            m -= 12
            y += 1
        month_var.set(f"{y:04d}-{m:02d}")
        refresh()

    ctk.CTkButton(top, text="\u2039", width=36,
                  command=lambda: shift_month(-1)).pack(side="left", padx=2)
    ctk.CTkButton(top, text="\u203a", width=36,
                  command=lambda: shift_month(1)).pack(side="left", padx=2)

    summary_lbl = ctk.CTkLabel(win, text="",
                               font=ctk.CTkFont(size=14, weight="bold"))
    summary_lbl.pack(anchor="w", padx=14, pady=(2, 2))
    breakdown_lbl = ctk.CTkLabel(win, text="", text_color="gray",
                                 wraplength=780, justify="left")
    breakdown_lbl.pack(anchor="w", padx=14, pady=(0, 4))
    ctk.CTkLabel(
        win,
        text="The shop's own costs — what the money was spent on, not "
             "stock purchases. This is separate from the Cash Book, which "
             "tracks cash movement; salaries live in Staff pay, not here.",
        text_color="gray", wraplength=780, justify="left").pack(
            anchor="w", padx=14, pady=(0, 4))

    frame = ctk.CTkFrame(win)
    frame.pack(fill="both", expand=True, padx=12, pady=6)
    cols = ("Date", "Category", "Description", "Amount", "Mode")
    tv = ttk.Treeview(frame, columns=cols, show="headings", height=10)
    widths = (110, 130, 300, 110, 80)
    for c, w in zip(cols, widths):
        tv.heading(c, text=c)
        tv.column(c, width=w, anchor="w")
    vsb = ttk.Scrollbar(frame, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=vsb.set)
    tv.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")

    # -- add one expense ---------------------------------------------------
    add = ctk.CTkFrame(win)
    add.pack(fill="x", padx=12, pady=(2, 10))
    ctk.CTkLabel(add, text="Add expense",
                 font=ctk.CTkFont(size=15, weight="bold")).pack(
                     anchor="w", padx=10, pady=(8, 2))
    row1 = ctk.CTkFrame(add, fg_color="transparent")
    row1.pack(fill="x", padx=10, pady=2)
    ctk.CTkLabel(row1, text="Date (YYYY-MM-DD)").pack(side="left", padx=(0, 2))
    date_e = ctk.CTkEntry(row1, width=120)
    date_e.insert(0, date.today().isoformat())
    date_e.pack(side="left", padx=4)
    ctk.CTkLabel(row1, text="Category").pack(side="left", padx=(8, 2))
    cat_var = ctk.StringVar(value=EXPENSE_CATEGORIES[0])
    ctk.CTkOptionMenu(row1, values=list(EXPENSE_CATEGORIES),
                      variable=cat_var, width=130).pack(side="left", padx=4)
    ctk.CTkLabel(row1, text="Amount").pack(side="left", padx=(8, 2))
    amt_e = ctk.CTkEntry(row1, width=110)
    amt_e.pack(side="left", padx=4)
    ctk.CTkLabel(row1, text="Mode").pack(side="left", padx=(8, 2))
    mode_var = ctk.StringVar(value="Cash")
    ctk.CTkOptionMenu(row1, values=list(EXPENSE_MODES),
                      variable=mode_var, width=90).pack(side="left", padx=4)
    row2 = ctk.CTkFrame(add, fg_color="transparent")
    row2.pack(fill="x", padx=10, pady=(2, 8))
    ctk.CTkLabel(row2, text="Description").pack(side="left", padx=(0, 2))
    desc_e = ctk.CTkEntry(row2, width=300)
    desc_e.pack(side="left", padx=4)
    ctk.CTkLabel(row2, text="Note").pack(side="left", padx=(8, 2))
    note_e = ctk.CTkEntry(row2, width=200)
    note_e.pack(side="left", padx=4)
    ctk.CTkButton(row2, text="Add expense", fg_color="#1f6f43",
                  hover_color="#175733",
                  command=lambda: save_expense()).pack(side="left", padx=8)

    del_row = ctk.CTkFrame(win, fg_color="transparent")
    del_row.pack(fill="x", padx=12, pady=(0, 10))
    ctk.CTkButton(del_row, text="Delete selected", fg_color="#b3261e",
                  hover_color="#8f1d17",
                  command=lambda: delete_selected()).pack(side="left")

    def refresh():
        for r in tv.get_children():
            tv.delete(r)
        try:
            month = db._check_month(month_var.get())
        except ValueError as e:
            messagebox.showerror("Shop expenses", str(e))
            return
        for r in expense_month_rows(db, month):
            tv.insert("", "end", iid=r["id"], values=(
                r["date"], r["category"], r["description"],
                money(r["amount"]), r["mode"]))
        total, count, totals = expense_summary(db, month)
        summary_lbl.configure(
            text=f"{month_name(month)}: {money(total)} across "
                 f"{count} expense{'s' if count != 1 else ''}")
        if totals:
            breakdown_lbl.configure(text="  ·  ".join(
                f"{c}: {money(v)}" for c, v in sorted(
                    totals.items(), key=lambda kv: -kv[1])))
        else:
            breakdown_lbl.configure(text="No expenses recorded this month.")

    def save_expense():
        try:
            amt = float(amt_e.get())
        except ValueError:
            messagebox.showerror("Shop expenses",
                                 "Amount must be a number greater than 0.")
            return
        try:
            db.add_shop_expense(date_e.get().strip(), cat_var.get(),
                                desc_e.get().strip(), amt, mode_var.get(),
                                note_e.get().strip())
        except ValueError as e:
            messagebox.showerror("Shop expenses", str(e))
            return
        amt_e.delete(0, "end")
        desc_e.delete(0, "end")
        note_e.delete(0, "end")
        refresh()

    def delete_selected():
        sel = tv.selection()
        if not sel:
            messagebox.showinfo("Shop expenses", "Select an expense first.")
            return
        if messagebox.askyesno("Shop expenses",
                               "Delete this expense?"):
            db.delete_shop_expense(int(sel[0]))
            refresh()

    refresh()
