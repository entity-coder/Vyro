"""Recent-history quick jump (Round 30) — Marg ERP item #3.

The video's billing screen keeps a history list on the side: every screen
the owner opened, most recent first, one click jumps straight back to it.
Vyro gets the same thing as a "Recent" section under the nav buttons in
the sidebar.

Design notes:
- In-session only: the list lives on the app object and resets when the
  app closes. Yesterday's screens are not the point — jumping between
  screens during a working session is.
- The current screen never appears in the list (clicking it would be a
  no-op); the list is capped at MAX_RECENT entries, most recent first.
- Pure functions (record_visit / jump_list) hold all the list logic so
  they are testable without a window; RecentHistory only builds widgets
  and wraps app.show. The wrap composes with nav_travel's own show()
  wrap because attach runs after App.__init__ and captures whatever
  app.show currently is.
- ui.py is never touched (it is ~130 KB, near the GitHub push limit);
  main.py only calls attach_recent_history(app) after App(db).
"""

import customtkinter as ctk

MAX_RECENT = 8


def record_visit(history, key, limit=MAX_RECENT):
    """Return a new history list with key moved to the front.

    Duplicates are removed, the list is capped at limit, and empty keys
    are ignored. The input list is never mutated.
    """
    if not key:
        return list(history)
    out = [k for k in history if k != key]
    out.insert(0, key)
    return out[:limit]


def jump_list(history, current, limit=MAX_RECENT):
    """Screens the panel should offer: history minus the current screen."""
    return [k for k in history if k != current][:limit]


def label_for(app, key):
    """Sidebar label for a screen key, falling back to the key itself."""
    btn = getattr(app, "nav_buttons", {}).get(key)
    if btn is not None:
        try:
            return btn.cget("text") or key
        except Exception:
            return key
    return key


class RecentHistory:
    """The 'Recent' panel in the sidebar + the show() wrapper behind it."""

    def __init__(self, app):
        self.app = app
        self.history = []
        frame = ctk.CTkFrame(app.sidebar, fg_color="transparent")
        theme_lbl = getattr(app, "_theme_lbl", None)
        if theme_lbl is not None:
            frame.pack(fill="x", padx=10, pady=(10, 2), before=theme_lbl)
        else:
            frame.pack(fill="x", padx=10, pady=(10, 2))
        self.frame = frame
        ctk.CTkLabel(frame, text="Recent",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color="gray").pack(anchor="w", padx=2)
        self.btns = ctk.CTkFrame(frame, fg_color="transparent")
        self.btns.pack(fill="x")
        self.empty_lbl = ctk.CTkLabel(
            frame, text="No recent screens yet",
            font=ctk.CTkFont(size=11), text_color="gray")
        self.refresh()

    def record(self, key):
        self.history = record_visit(self.history, key)

    def refresh(self):
        for w in self.btns.winfo_children():
            w.destroy()
        keys = jump_list(self.history, getattr(self.app, "current", None))
        if not keys:
            self.empty_lbl.pack(anchor="w", padx=2, pady=2)
            return
        self.empty_lbl.pack_forget()
        for key in keys:
            b = ctk.CTkButton(self.btns, text=label_for(self.app, key),
                              anchor="w", fg_color="transparent",
                              command=lambda k=key: self.app.show(k))
            b.pack(fill="x", padx=2, pady=1)


def attach_recent_history(app):
    """Install the Recent panel on an App; returns the RecentHistory.

    Safe to call twice — the second call returns the existing panel.
    """
    existing = getattr(app, "_recent_history", None)
    if existing is not None:
        return existing
    panel = RecentHistory(app)
    app._recent_history = panel
    panel.record(getattr(app, "current", None))
    panel.refresh()
    orig_show = app.show

    def show_and_record(key):
        panel.record(key)
        orig_show(key)
        panel.refresh()

    app.show = show_and_record
    return panel
