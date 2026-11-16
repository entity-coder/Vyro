"""
Vyro — supplier payment reminders (Round 27).

"Vyro reminds you who you owe, before they chase you."

One planned pay-by date per supplier (db.set_supplier_due_date /
db.get_supplier_due_date, stored on the suppliers row). The amount owed
is never stored — it is always purchases minus payments made
(db.supplier_outstanding). A supplier is OVERDUE when today is past the
due date and something is still owed; a fully paid supplier (or one with
no due date set) is never overdue.

Reminder drafts are ready-to-send WhatsApp texts in English, Hindi and
Marathi, sent with one tap via the same wa.me link helper as the Round 21
customer reminders (new_features.whatsapp_link). Like those, this is a
draft, not auto-send — WhatsApp offers no official auto-send API.

Pure functions first (no GUI imports, so they can be tested headless);
the CustomTkinter dialog is at the bottom, imported lazily by shop_ui.
"""

from datetime import date


LANGUAGES = ["English", "Hindi", "Marathi"]


def _fmt_date(due):
    """'2026-11-20' -> '20 Nov 2026' (falls back to the raw string)."""
    try:
        d = date.fromisoformat(due)
        names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        return f"{d.day} {names[d.month - 1]} {d.year}"
    except ValueError:
        return due


def supplier_pay_reminders(db, today=None):
    """One row per supplier we still owe, overdue first, then most owed.

    Each row: id, name, phone, owed, due_date ('' when not set),
    overdue (True when today is past the due date and something is
    still owed). Suppliers with nothing outstanding never appear —
    a paid supplier is never overdue.
    """
    today = today or date.today()
    rows = []
    for s in db.suppliers_with_payables():
        due = (s.get("pay_due_date") or "").strip()
        overdue = False
        if due:
            try:
                overdue = date.fromisoformat(due) < today
            except ValueError:
                overdue = False
        rows.append({
            "id": s["id"], "name": s["name"],
            "phone": s.get("phone") or "",
            "owed": float(s["outstanding"]), "due_date": due,
            "overdue": overdue,
        })
    rows.sort(key=lambda r: (not r["overdue"], -r["owed"], r["name"]))
    return rows


def supplier_pay_summary(db, today=None):
    """(total owed, suppliers still owed, suppliers overdue)."""
    rows = supplier_pay_reminders(db, today)
    total = sum(r["owed"] for r in rows)
    overdue = sum(1 for r in rows if r["overdue"])
    return total, len(rows), overdue


def supplier_reminder_message(shop_name, supplier_name, amount,
                              due_date="", lang="English"):
    """Ready-to-send text telling the supplier when we will pay them.

    The shop owes the supplier, so the message promises payment by the
    due date — or "shortly" when no due date is set. `lang` is one of
    'English', 'Hindi', 'Marathi' (anything else falls back to English).
    """
    shop = shop_name or "Vyro"
    amt = f"Rs. {float(amount):.2f}"
    due = (due_date or "").strip()
    if lang == "Hindi":
        if due:
            return (f"नमस्ते {supplier_name}, मैं {shop} से बोल रहा हूँ। "
                    f"हम {amt} का भुगतान {_fmt_date(due)} तक कर देंगे। "
                    f"धन्यवाद!")
        return (f"नमस्ते {supplier_name}, मैं {shop} से बोल रहा हूँ। "
                f"हम {amt} का भुगतान जल्द ही कर देंगे। धन्यवाद!")
    if lang == "Marathi":
        if due:
            return (f"नमस्कार {supplier_name}, मी {shop} मधून बोलत आहे। "
                    f"आम्ही {amt} चे पेमेंट {_fmt_date(due)} पर्यंत करू। "
                    f"धन्यवाद!")
        return (f"नमस्कार {supplier_name}, मी {shop} मधून बोलत आहे। "
                f"आम्ही {amt} चे पेमेंट लवकरच करू। धन्यवाद!")
    if due:
        return (f"Hello {supplier_name}, this is {shop}. We will pay "
                f"{amt} by {_fmt_date(due)}. Thank you!")
    return (f"Hello {supplier_name}, this is {shop}. We will pay {amt} "
            f"shortly. Thank you!")


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------
def open_supplier_pay_dialog(parent, db, shop_name=""):
    """Window listing every supplier we owe + reminder drafts to send."""
    import webbrowser
    from tkinter import messagebox
    import customtkinter as ctk
    from new_features import whatsapp_link

    win = ctk.CTkToplevel(parent)
    win.title("Supplier payment reminders")
    win.geometry("760x520")
    win.transient(parent)

    RUPEE = "\u20b9"

    def money(n):
        return f"{RUPEE}{float(n):,.2f}"

    lang_var = ctk.StringVar(value="English")

    top = ctk.CTkFrame(win, fg_color="transparent")
    top.pack(fill="x", padx=12, pady=(10, 2))
    ctk.CTkLabel(top, text="Supplier payment reminders",
                 font=ctk.CTkFont(size=22, weight="bold")).pack(
                     side="left", padx=(0, 12))
    ctk.CTkLabel(top, text="Language").pack(side="left", padx=(4, 2))
    ctk.CTkOptionMenu(top, values=LANGUAGES, variable=lang_var,
                      width=110, command=lambda _: refresh()).pack(
                          side="left", padx=4)

    summary_lbl = ctk.CTkLabel(win, text="",
                               font=ctk.CTkFont(size=14, weight="bold"))
    summary_lbl.pack(anchor="w", padx=14, pady=(2, 4))
    ctk.CTkLabel(
        win,
        text="Vyro reminds you who you owe, before they chase you. "
             "Set a pay-by date per supplier; a supplier turns OVERDUE "
             "once that date passes with money still owed. Reminders are "
             "drafts you send with one tap — nothing is sent automatically.",
        text_color="gray", wraplength=730, justify="left").pack(
            anchor="w", padx=14, pady=(0, 4))

    scroll = ctk.CTkScrollableFrame(win)
    scroll.pack(fill="both", expand=True, padx=10, pady=6)

    def refresh():
        for w in scroll.winfo_children():
            w.destroy()
        rows = supplier_pay_reminders(db)
        if not rows:
            ctk.CTkLabel(scroll, text="No suppliers are owed anything.",
                         font=ctk.CTkFont(size=14)).pack(pady=30)
            summary_lbl.configure(text="Nothing owed to any supplier.")
            return
        total, count, overdue = supplier_pay_summary(db)
        summary_lbl.configure(
            text=f"{count} supplier{'s' if count != 1 else ''} owed  |  "
                 f"Total payable: {money(total)}  |  "
                 f"{overdue} overdue")
        for r in rows:
            fr = ctk.CTkFrame(scroll)
            fr.pack(fill="x", pady=4, padx=4)
            status = "  —  OVERDUE" if r["overdue"] else ""
            ctk.CTkLabel(
                fr,
                text=f"{r['name']}  —  {money(r['owed'])} owed{status}",
                font=ctk.CTkFont(weight="bold"),
                text_color="#b3261e" if r["overdue"] else None).pack(
                    anchor="w", padx=8, pady=(6, 0))
            due_txt = (f"Pay by: {_fmt_date(r['due_date'])}"
                       if r["due_date"] else "No pay-by date set")
            ctk.CTkLabel(fr, text=due_txt, text_color="gray").pack(
                anchor="w", padx=8)
            msg = supplier_reminder_message(
                shop_name, r["name"], r["owed"], r["due_date"],
                lang_var.get())
            ctk.CTkLabel(fr, text=msg, wraplength=700).pack(
                anchor="w", padx=8)

            due_row = ctk.CTkFrame(fr, fg_color="transparent")
            due_row.pack(fill="x", padx=8, pady=4)
            ctk.CTkLabel(due_row, text="Pay-by date (YYYY-MM-DD)").pack(
                side="left", padx=(0, 2))
            due_e = ctk.CTkEntry(due_row, width=120)
            due_e.insert(0, r["due_date"])
            due_e.pack(side="left", padx=4)

            def save_due(sid=r["id"], entry=due_e):
                try:
                    db.set_supplier_due_date(sid, entry.get())
                except ValueError as e:
                    messagebox.showerror("Supplier reminders", str(e))
                    return
                refresh()

            ctk.CTkButton(due_row, text="Set due date", width=110,
                          command=save_due).pack(side="left", padx=4)

            btns = ctk.CTkFrame(fr, fg_color="transparent")
            btns.pack(fill="x", padx=8, pady=(0, 6))

            def copy_msg(m=msg):
                win.clipboard_clear()
                win.clipboard_append(m)
                messagebox.showinfo("Copied", "Reminder text copied.")

            def wa(m=msg, ph=r["phone"]):
                link = whatsapp_link(ph, m)
                if link:
                    webbrowser.open(link)
                else:
                    messagebox.showinfo(
                        "WhatsApp",
                        "No phone number saved for this supplier.")

            ctk.CTkButton(btns, text="Copy", width=70,
                          command=copy_msg).pack(side="left", padx=(0, 4))
            ctk.CTkButton(btns, text="WhatsApp", width=90,
                          fg_color="#1f6f43", hover_color="#175733",
                          command=wa).pack(side="left", padx=4)

    refresh()
