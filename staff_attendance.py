"""
Vyro — staff attendance / shift log (Round 28).

Per-staff daily clock-in/out + shift log, next to Staff pay (Round 26).
Each staff member has a usual shift (morning / evening / full day); each
day is marked present / absent / leave with optional clock-in/out times.
The monthly view shows, per staff member, how many days they were
present, absent or on leave — the attendance picture for the same month
Staff pay shows the salary picture for.

Attendance is a log only: it never changes pay. A salary is never
auto-deducted for an absence; the owner reads the two windows together
and decides.

Pure functions first (no GUI imports, so they can be tested headless);
the CustomTkinter dialog is at the bottom, imported lazily by shop_ui.
"""

from datetime import date

from db import ATTENDANCE_STATUSES, STAFF_SHIFTS

SHIFTS = STAFF_SHIFTS
STATUSES = ATTENDANCE_STATUSES


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


def attendance_month_rows(db, month):
    """Monthly attendance per active staff member, most-present first.

    Each row: id, name, role, shift, present, absent, leave.
    """
    rows = db.attendance_for_month(month)
    rows.sort(key=lambda r: (-r["present"], r["name"]))
    return rows


def attendance_summary(db, month):
    """(total present days, total absent days, total leave days,
    active staff count) for `month`."""
    return db.monthly_attendance_summary(month)


def attendance_day_rows(db, date_str):
    """One row per active staff member for a day: status ('' when nothing
    was recorded yet), clock-in/out, shift, note."""
    return db.attendance_for_day(date_str)


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------
def open_staff_attendance_dialog(parent, db):
    """Staff attendance window: monthly present/absent/leave per staff,
    plus marking one day's attendance (status + clock-in/out)."""
    from tkinter import messagebox
    import customtkinter as ctk
    from tkinter import ttk

    win = ctk.CTkToplevel(parent)
    win.title("Staff attendance — shift log")
    win.geometry("820x620")
    win.transient(parent)

    month_var = ctk.StringVar(value=current_month())

    top = ctk.CTkFrame(win, fg_color="transparent")
    top.pack(fill="x", padx=12, pady=(10, 2))
    ctk.CTkLabel(top, text="Staff attendance",
                 font=ctk.CTkFont(size=22, weight="bold")).pack(
                     side="left", padx=(0, 12))
    ctk.CTkLabel(top, text="Month (YYYY-MM)").pack(side="left", padx=(4, 2))
    month_e = ctk.CTkEntry(top, textvariable=month_var, width=90)
    month_e.pack(side="left", padx=4)

    def shift_month(delta):
        try:
            y, m = int(month_var.get()[:4]), int(month_var.get()[5:7])
        except ValueError:
            messagebox.showerror("Staff attendance",
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
    summary_lbl.pack(anchor="w", padx=14, pady=(2, 4))
    ctk.CTkLabel(
        win,
        text="Attendance is a log only — it never deducts salary. "
             "Read it next to Staff pay to see who turned up in the "
             "month they were paid for.",
        text_color="gray", wraplength=780, justify="left").pack(
            anchor="w", padx=14, pady=(0, 4))

    frame = ctk.CTkFrame(win)
    frame.pack(fill="both", expand=True, padx=12, pady=6)
    cols = ("Name", "Role", "Shift", "Present", "Absent", "Leave")
    tv = ttk.Treeview(frame, columns=cols, show="headings", height=10)
    widths = (180, 130, 110, 90, 90, 90)
    for c, w in zip(cols, widths):
        tv.heading(c, text=c)
        tv.column(c, width=w, anchor="w")
    vsb = ttk.Scrollbar(frame, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=vsb.set)
    tv.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")

    # -- mark one day's attendance for the selected staff member ---------
    mark = ctk.CTkFrame(win)
    mark.pack(fill="x", padx=12, pady=(2, 10))
    ctk.CTkLabel(mark, text="Mark attendance",
                 font=ctk.CTkFont(size=15, weight="bold")).pack(
                     anchor="w", padx=10, pady=(8, 2))
    row1 = ctk.CTkFrame(mark, fg_color="transparent")
    row1.pack(fill="x", padx=10, pady=2)
    ctk.CTkLabel(row1, text="Date (YYYY-MM-DD)").pack(side="left", padx=(0, 2))
    date_e = ctk.CTkEntry(row1, width=120)
    date_e.insert(0, date.today().isoformat())
    date_e.pack(side="left", padx=4)
    ctk.CTkLabel(row1, text="Status").pack(side="left", padx=(8, 2))
    status_var = ctk.StringVar(value="present")
    ctk.CTkOptionMenu(row1, values=list(STATUSES),
                      variable=status_var, width=110).pack(side="left", padx=4)
    ctk.CTkLabel(row1, text="Clock-in (HH:MM)").pack(side="left", padx=(8, 2))
    in_e = ctk.CTkEntry(row1, width=70)
    in_e.pack(side="left", padx=4)
    ctk.CTkLabel(row1, text="Clock-out").pack(side="left", padx=(8, 2))
    out_e = ctk.CTkEntry(row1, width=70)
    out_e.pack(side="left", padx=4)
    row2 = ctk.CTkFrame(mark, fg_color="transparent")
    row2.pack(fill="x", padx=10, pady=(2, 8))
    ctk.CTkLabel(row2, text="Note").pack(side="left", padx=(0, 2))
    note_e = ctk.CTkEntry(row2, width=300)
    note_e.pack(side="left", padx=4)
    ctk.CTkButton(row2, text="Save attendance", fg_color="#1f6f43",
                  hover_color="#175733",
                  command=lambda: save_day()).pack(side="left", padx=8)
    ctk.CTkLabel(row2, text="Shift:").pack(side="left", padx=(8, 2))
    shift_var = ctk.StringVar(value="full day")
    ctk.CTkOptionMenu(row2, values=list(SHIFTS),
                      variable=shift_var, width=110).pack(side="left", padx=4)
    ctk.CTkButton(row2, text="Set shift",
                  command=lambda: save_shift()).pack(side="left", padx=4)

    def selected_row():
        sel = tv.selection()
        if not sel:
            messagebox.showinfo("Staff attendance",
                                "Select a staff member first.")
            return None
        return sel[0]

    def refresh():
        for r in tv.get_children():
            tv.delete(r)
        try:
            month = db._check_month(month_var.get())
        except ValueError as e:
            messagebox.showerror("Staff attendance", str(e))
            return
        rows = attendance_month_rows(db, month)
        for r in rows:
            tv.insert("", "end", iid=r["id"], values=(
                r["name"], r["role"], r["shift"], r["present"],
                r["absent"], r["leave"]))
        present, absent, leave, count = attendance_summary(db, month)
        summary_lbl.configure(
            text=f"{month_name(month)}: {present} present  |  "
                 f"{absent} absent  |  {leave} leave days"
                 f"  ({count} staff)")

    def save_day():
        sid = selected_row()
        if sid is None:
            return
        try:
            db.record_attendance(int(sid), date_e.get().strip(),
                                 status_var.get(), in_e.get().strip(),
                                 out_e.get().strip(),
                                 note=note_e.get().strip())
        except (ValueError, TypeError) as e:
            messagebox.showerror("Staff attendance", str(e))
            return
        in_e.delete(0, "end")
        out_e.delete(0, "end")
        note_e.delete(0, "end")
        refresh()

    def save_shift():
        sid = selected_row()
        if sid is None:
            return
        s = db.get_staff(int(sid))
        if messagebox.askyesno(
                "Staff attendance",
                f"Set {s['name']}'s usual shift to "
                f"{shift_var.get()}?"):
            try:
                db.set_staff_shift(int(sid), shift_var.get())
            except (ValueError, TypeError) as e:
                messagebox.showerror("Staff attendance", str(e))
                return
            refresh()

    refresh()
