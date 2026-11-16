"""
Vyro — AI-powered billing and shop management app for a small Indian wholesale shop.

Run:  python main.py
"""

import os
import sys
import tkinter as tk

import customtkinter as ctk

from db import DB
from ui import App


def _resource_path(name):
    # When frozen by PyInstaller, bundled files live under sys._MEIPASS;
    # otherwise they sit next to this script.
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def main():
    db = DB()
    # Theme follows the saved setting (dark default), toggle lives in sidebar.
    ctk.set_appearance_mode(db.get_setting("theme", "dark"))
    ctk.set_default_color_theme("green")
    app = App(db)
    try:
        _logo = tk.PhotoImage(file=_resource_path("vyro-logo.png"))
        app.iconphoto(True, _logo)
        app._vyro_logo = _logo  # keep a reference so it is not garbage-collected
    except Exception:
        pass  # a missing logo must never stop the app from starting
    app.mainloop()


if __name__ == "__main__":
    main()
