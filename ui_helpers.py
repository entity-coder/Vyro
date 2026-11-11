"""
Vyro — tiny shared UI helpers (money formatting, dates, entry parsing,
treeview builder).

Split out of ui.py (Round 25) to keep ui.py under the push size limit;
behaviour is unchanged.
"""

from datetime import date

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
