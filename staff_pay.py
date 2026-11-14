"""
Vyro — staff pay (Round 26).

Employee payment reminders: one staff row per employee (name, role, monthly
salary, pay day 1-28), one payment row per (part-)payment of a month's
salary. The dialog shows, for a chosen month, who is paid / partly paid /
still due — with an "overdue" flag once the pay day has passed — and records
payments capped at the month's remaining salary (db.record_staff_payment).

Staff payments are a salary ledger, like supplier payments are a creditor
ledger: they do NOT post to Cash Book automatically. If a salary was paid
in cash, add it in Cash Book too (OUT / Salary) so cash-in-hand stays
correct; the dialog says so.

Pure functions first (no GUI imports, so they can be tested headless);
the CustomTkinter dialog is at the bottom, imported lazily by shop_ui.
"""

from datetime import date


PAY_MODES = ["Cash", "UPI", "Bank"]


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


def staff_due_for_month(db, month, today=None):
    """One row per active staff member for `month` (YYYY-MM).

    Each row: id, name, role, phone, monthly_salary, pay_day, paid,
    remaining, status ('Paid' / 'Partial' / 'Due'), overdue (True when the
    pay day has passed and something is still due). Sorted most-due first.
    Staff with a zero salary have nothing due and are listed as Paid.
    """
    today = today or date.today()
    rows = []
    for s in db.list_staff(active_only=True):
        salary = float(s["monthly_salary"])
        paid = db.staff_paid_for_month(s["id"], month)
        remaining = round(salary - paid, 2)
        if remaining < 0.004:
            remaining = 0.0
        if remaining <= 0:
            status = "Paid"
        elif paid > 0.004:
            status = "Partial"
        else:
            status = "Due"
        overdue = bool(
            remaining > 0 and month == today.strftime("%Y-%m")
            and today.day > int(s["pay_day"]))
        rows.append({
            "id": s["id"], "name": s["name"], "role": s["role"] or "",
            "phone": s["phone"] or "", "monthly_salary": salary,
            "pay_day": int(s["pay_day"]), "paid": paid,
            "remaining": remaining, "status": status, "overdue": overdue,
        })
    rows.sort(key=lambda r: (-r["remaining"], r["name"]))
    return rows


def staff_due_summary(db, month, today=None):
    """(total salary due, total paid, total remaining, staff still unpaid)."""
    rows = staff_due_for_month(db, month, today)
    total = sum(r["monthly_salary"] for r in rows)
    paid = sum(r["paid"] for r in rows)
    remaining = sum(r["remaining"] for r in rows)
    unpaid = sum(1 for r in rows if r["remaining"] > 0)
    return total, paid, remaining, unpaid


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------
def open_staff_pay_dialog(parent, db):
    """Staff pay window: monthly salary status + record payments."""
    from tkinter import messagebox
    import customtkinter as ctk
    from tkinter import ttk

    win = ctk.CTkToplevel(parent)
    win.title("Staff pay — employee payment reminders")
    win.geometry("820x560")
    win.transient(parent)

    RUPEE = "\u20b9"

    def money(n):
        return f"{RUPEE}{float(n):,.2f}"

    month_var = ctk.StringVar(value=current_month())

    top = ctk.CTkFrame(win, fg_color="transparent")
    top.pack(fill="x", padx=12, pady=(10, 2))
    ctk.CTkLabel(top, text="Staff pay",
                 font=ctk.CTkFont(size=22, weight="bold")).pack(
                     side="left", padx=(0, 12))
    ctk.CTkLabel(top, text="Month (YYYY-MM)").pack(side="left", padx=(4, 2))
    month_e = ctk.CTkEntry(top, textvariable=month_var, width=90)
    month_e.pack(side="left", padx=4)

    def shift_month(delta):
        try:
            y, m = int(month_var.get()[:4]), int(month_var.get()[5:7])
        except ValueError:
            messagebox.showerror("Staff pay",
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
    ctk.CTkButton(top, text="Add staff",
                  command=lambda: staff_dialog()).pack(side="right", padx=4)
    ctk.CTkButton(top, text="Show all / inactive",
                  command=lambda: staff_dialog(show_inactive=True)).pack(
                      side="right", padx=4)

    summary_lbl = ctk.CTkLabel(win, text="",
                               font=ctk.CTkFont(size=14, weight="bold"))
    summary_lbl.pack(anchor="w", padx=14, pady=(2, 4))
    ctk.CTkLabel(
        win,
        text="Salaries recorded here don't post to Cash Book — if a salary "
             "was paid in cash, add it in Cash Book too (OUT / Salary) so "
             "cash-in-hand stays correct.",
        text_color="gray", wraplength=780, justify="left").pack(
            anchor="w", padx=14, pady=(0, 4))

    frame = ctk.CTkFrame(win)
    frame.pack(fill="both", expand=True, padx=12, pady=6)
    cols = ("Name", "Role", "Salary", "Paid", "Remaining", "Status")
    tv = ttk.Treeview(frame, columns=cols, show="headings", height=16)
    widths = (170, 120, 110, 110, 110, 110)
    for c, w in zip(cols, widths):
        tv.heading(c, text=c)
        tv.column(c, width=w, anchor="w")
    vsb = ttk.Scrollbar(frame, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=vsb.set)
    tv.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")

    btns = ctk.CTkFrame(win, fg_color="transparent")
    btns.pack(fill="x", padx=12, pady=(2, 10))
    ctk.CTkButton(btns, text="Record payment", fg_color="#1f6f43",
                  hover_color="#175733",
                  command=lambda: pay_dialog()).pack(side="left", padx=4)
    ctk.CTkButton(btns, text="Payment history",
                  command=lambda: history_dialog()).pack(side="left", padx=4)
    ctk.CTkButton(btns, text="Edit staff",
                  command=lambda: staff_dialog(edit=True)).pack(
                      side="left", padx=4)
    ctk.CTkButton(btns, text="Deactivate / reactivate",
                  command=lambda: toggle_active()).pack(side="left", padx=4)

    def selected_row():
        sel = tv.selection()
        if not sel:
            messagebox.showinfo("Staff pay", "Select a staff member first.")
            return None
        return sel[0]

    def refresh():
        for r in tv.get_children():
            tv.delete(r)
        try:
            month = db._check_month(month_var.get())
        except ValueError as e:
            messagebox.showerror("Staff pay", str(e))
            return
        rows = staff_due_for_month(db, month)
        for r in rows:
            status = r["status"] + (" — OVERDUE" if r["overdue"] else "")
            tv.insert("", "end", iid=r["id"], values=(
                r["name"], r["role"], money(r["monthly_salary"]),
                money(r["paid"]), money(r["remaining"]), status))
        total, paid, remaining, unpaid = staff_due_summary(db, month)
        summary_lbl.configure(
            text=f"{month_name(month)}: {money(total)} due  |  "
                 f"{money(paid)} paid  |  {money(remaining)} remaining"
                 f"  ({unpaid} staff unpaid)")

    def staff_dialog(edit=False, show_inactive=False):
        sid = None
        existing = None
        if edit:
            sid = selected_row()
            if sid is None:
                return
            existing = db.get_staff(int(sid))
        d = ctk.CTkToplevel(win)
        d.title("Edit staff" if edit else "Add staff")
        d.geometry("420x380")
        d.transient(win)
        if show_inactive and not edit:
            staff = db.list_staff(active_only=False)
            names = [f"{s['name']}  ({'active' if s['active'] else 'inactive'})"
                     for s in staff]
            ctk.CTkLabel(d, text="All staff (including inactive):",
                         font=ctk.CTkFont(weight="bold")).pack(
                             anchor="w", padx=14, pady=(10, 2))
            box = ctk.CTkTextbox(d, height=120)
            box.pack(fill="x", padx=14, pady=4)
            box.insert("0.0", "\n".join(names) or "No staff added yet.")
            box.configure(state="disabled")
            ctk.CTkButton(d, text="Close",
                          command=d.destroy).pack(pady=10)
            return
        fields = {}
        for label, key, default in (
                ("Name *", "name", existing["name"] if existing else ""),
                ("Role", "role", existing["role"] if existing else ""),
                ("Monthly salary \u20b9 *", "salary",
                 f"{existing['monthly_salary']:g}" if existing else ""),
                ("Pay day (1-28)", "pay_day",
                 str(existing["pay_day"]) if existing else "1"),
                ("Phone", "phone", existing["phone"] if existing else "")):
            ctk.CTkLabel(d, text=label).pack(anchor="w", padx=14, pady=(6, 0))
            e = ctk.CTkEntry(d, width=320)
            e.insert(0, default)
            e.pack(anchor="w", padx=14)
            fields[key] = e

        def save():
            try:
                if edit:
                    db.update_staff(
                        int(sid), fields["name"].get(),
                        fields["role"].get(), fields["salary"].get(),
                        fields["pay_day"].get(), fields["phone"].get())
                else:
                    db.add_staff(fields["name"].get(),
                                 fields["role"].get(),
                                 fields["salary"].get(),
                                 fields["pay_day"].get(),
                                 fields["phone"].get())
            except (ValueError, TypeError) as e:
                messagebox.showerror("Staff pay", str(e))
                return
            d.destroy()
            refresh()

        ctk.CTkButton(d, text="Save", fg_color="#1f6f43",
                      hover_color="#175733", command=save).pack(pady=14)

    def toggle_active():
        sid = selected_row()
        if sid is None:
            return
        s = db.get_staff(int(sid))
        action = "Reactivate" if not s["active"] else "Deactivate"
        if messagebox.askyesno("Staff pay",
                               f"{action} {s['name']}?"):
            db.set_staff_active(int(sid), not s["active"])
            refresh()

    def pay_dialog():
        sid = selected_row()
        if sid is None:
            return
        s = db.get_staff(int(sid))
        month = month_var.get().strip()
        remaining = (float(s["monthly_salary"])
                     - db.staff_paid_for_month(int(sid), month))
        if remaining <= 0.004:
            messagebox.showinfo(
                "Staff pay",
                f"{s['name']} is fully paid for {month_name(month)}.")
            return
        d = ctk.CTkToplevel(win)
        d.title(f"Record payment — {s['name']}")
        d.geometry("420x360")
        d.transient(win)
        ctk.CTkLabel(
            d,
            text=f"{month_name(month)} salary: {money(s['monthly_salary'])}"
                 f"  |  Remaining: {money(remaining)}",
            font=ctk.CTkFont(weight="bold"), wraplength=380).pack(
                padx=14, pady=(12, 4))
        ctk.CTkLabel(d, text="Amount \u20b9 *").pack(anchor="w", padx=14)
        amt_e = ctk.CTkEntry(d, width=200)
        amt_e.insert(0, f"{remaining:g}")
        amt_e.pack(anchor="w", padx=14)
        ctk.CTkLabel(d, text="Date (YYYY-MM-DD)").pack(anchor="w", padx=14)
        date_e = ctk.CTkEntry(d, width=200)
        date_e.insert(0, date.today().isoformat())
        date_e.pack(anchor="w", padx=14)
        ctk.CTkLabel(d, text="Mode").pack(anchor="w", padx=14)
        mode_var = ctk.StringVar(value="Cash")
        ctk.CTkOptionMenu(d, values=PAY_MODES, variable=mode_var,
                          width=200).pack(anchor="w", padx=14)
        ctk.CTkLabel(d, text="Note").pack(anchor="w", padx=14)
        note_e = ctk.CTkEntry(d, width=320)
        note_e.pack(anchor="w", padx=14)

        def save():
            try:
                db.record_staff_payment(
                    int(sid), month, amt_e.get(), date_e.get(),
                    mode_var.get(), note_e.get())
            except (ValueError, TypeError) as e:
                messagebox.showerror("Staff pay", str(e))
                return
            d.destroy()
            refresh()

        ctk.CTkButton(d, text="Save payment", fg_color="#1f6f43",
                      hover_color="#175733", command=save).pack(pady=14)

    def history_dialog():
        sid = selected_row()
        if sid is None:
            return
        s = db.get_staff(int(sid))
        d = ctk.CTkToplevel(win)
        d.title(f"Payment history — {s['name']}")
        d.geometry("560x380")
        d.transient(win)
        pays = db.staff_payments(int(sid))
        if not pays:
            ctk.CTkLabel(d, text="No payments recorded yet.",
                         font=ctk.CTkFont(size=14)).pack(pady=30)
            return
        frame2 = ctk.CTkFrame(d)
        frame2.pack(fill="both", expand=True, padx=12, pady=10)
        tv2 = ttk.Treeview(frame2, columns=("Month", "Date", "Amount",
                                            "Mode", "Note"),
                           show="headings", height=12)
        for c, w in (("Month", 80), ("Date", 100), ("Amount", 100),
                     ("Mode", 70), ("Note", 170)):
            tv2.heading(c, text=c)
            tv2.column(c, width=w, anchor="w")
        vsb2 = ttk.Scrollbar(frame2, orient="vertical", command=tv2.yview)
        tv2.configure(yscrollcommand=vsb2.set)
        tv2.pack(side="left", fill="both", expand=True)
        vsb2.pack(side="right", fill="y")
        for p in pays:
            tv2.insert("", "end", iid=p["id"], values=(
                p["month"], p["date"], money(p["amount"]), p["mode"],
                p["note"] or ""))

        def delete_pay():
            sel = tv2.selection()
            if not sel:
                messagebox.showinfo("Staff pay", "Select a payment first.")
                return
            if messagebox.askyesno("Staff pay",
                                   "Delete this payment record?"):
                db.delete_staff_payment(int(sel[0]))
                d.destroy()
                refresh()

        ctk.CTkButton(d, text="Delete selected payment",
                      fg_color="#b3261e", hover_color="#8f1d17",
                      command=delete_pay).pack(pady=(0, 10))

    refresh()
