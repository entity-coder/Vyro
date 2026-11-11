"""
Vyro — shared search picker dialog.

Split out of ui.py (Round 25) to keep ui.py under the push size
limit; behaviour is unchanged. ui.py re-exports SearchPicker, so
existing `from ui import SearchPicker` imports keep working.
"""

import customtkinter as ctk


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
