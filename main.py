"""
Vyro — AI-powered billing and shop management app for a small Indian wholesale shop.

Run:  python main.py
"""

import customtkinter as ctk

from db import DB
from ui import App


def main():
    db = DB()
    # Theme follows the saved setting (dark default), toggle lives in sidebar.
    ctk.set_appearance_mode(db.get_setting("theme", "dark"))
    ctk.set_default_color_theme("green")
    app = App(db)
    app.mainloop()


if __name__ == "__main__":
    main()
