"""Headless tests for Round 30 — recent-history quick jump.

No GUI and no database: the list logic (record_visit / jump_list) is
pure, and the sidebar panel is exercised against stub widgets + a fake
app so the show() wrapping, button order and click-to-jump behaviour
are all verified without a window. Run: python3 test_round30.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import recent_history  # noqa: E402
from recent_history import attach_recent_history, jump_list, record_visit  # noqa: E402

PASSED = 0
FAILED = []


def check(name, fn):
    global PASSED
    try:
        fn()
        PASSED += 1
        print(f"  ok: {name}")
    except AssertionError as e:
        FAILED.append(name)
        print(f"  FAIL: {name} — {e}")
    except Exception as e:  # noqa: BLE001 - report unexpected errors too
        FAILED.append(name)
        print(f"  FAIL: {name} — {type(e).__name__}: {e}")


# --- pure list logic ---------------------------------------------------------
def t_first_visit_goes_first():
    assert record_visit([], "billing") == ["billing"]


def t_revisit_moves_to_front_no_duplicates():
    hist = record_visit(["billing", "purchases"], "billing")
    assert hist == ["billing", "purchases"]
    assert record_visit(hist, "purchases") == ["purchases", "billing"]


def t_input_list_not_mutated():
    hist = ["billing"]
    record_visit(hist, "purchases")
    assert hist == ["billing"]


def t_cap_at_eight():
    hist = []
    for i in range(10):
        hist = record_visit(hist, f"s{i}")
    assert hist == [f"s{i}" for i in range(9, 1, -1)], hist
    assert len(hist) == 8


def t_empty_key_ignored():
    assert record_visit(["billing"], "") == ["billing"]
    assert record_visit(["billing"], None) == ["billing"]


def t_jump_list_excludes_current():
    hist = ["purchases", "billing", "dashboard"]
    assert jump_list(hist, "purchases") == ["billing", "dashboard"]
    assert jump_list(hist, "billing") == ["purchases", "dashboard"]
    assert jump_list(hist, "other") == hist


def t_jump_list_caps():
    hist = [f"s{i}" for i in range(10)]
    assert jump_list(hist, "none", limit=3) == ["s0", "s1", "s2"]


# --- stub widgets + fake app -------------------------------------------------
class StubWidget:
    def __init__(self, parent=None, **kw):
        self.parent = parent
        self.kw = kw
        self.children = []
        self.packed = False
        self.pack_calls = []
        if parent is not None and hasattr(parent, "children"):
            parent.children.append(self)

    def pack(self, **kw):
        self.packed = True
        self.pack_calls.append(kw)

    def pack_forget(self):
        self.packed = False

    def winfo_children(self):
        return list(self.children)

    def destroy(self):
        self.packed = False
        if self.parent is not None and hasattr(self.parent, "children"):
            try:
                self.parent.children.remove(self)
            except ValueError:
                pass

    def cget(self, key):
        return self.kw.get(key)


class StubButton(StubWidget):
    def invoke(self):
        self.kw["command"]()


class FakeNavButton:
    def __init__(self, text):
        self._text = text

    def cget(self, key):
        return self._text if key == "text" else None


class FakeApp:
    """Minimal stand-in for ui.App: sidebar, nav buttons, show, current."""

    def __init__(self):
        self.sidebar = StubWidget()
        self._theme_lbl = StubWidget(self.sidebar)
        self.nav_buttons = {
            "dashboard": FakeNavButton("Dashboard"),
            "billing": FakeNavButton("Billing"),
            "purchases": FakeNavButton("Purchases"),
            "cashbook": FakeNavButton("Cash Book"),
        }
        self.current = "dashboard"
        self.shown = []

    def show(self, key):
        self.current = key
        self.shown.append(key)


def install_stubs():
    recent_history.ctk.CTkFrame = StubWidget
    recent_history.ctk.CTkLabel = StubWidget
    recent_history.ctk.CTkButton = StubButton
    recent_history.ctk.CTkFont = lambda **kw: kw


def panel_buttons(panel):
    return [w.kw.get("text") for w in panel.btns.winfo_children()]


def t_attach_seeds_dashboard_and_wraps_show():
    install_stubs()
    app = FakeApp()
    panel = attach_recent_history(app)
    assert panel.history == ["dashboard"]
    assert panel_buttons(panel) == []  # current screen is never offered
    assert app.show is not FakeApp.show
    app.show("billing")
    assert app.shown == ["billing"]
    assert panel.history == ["billing", "dashboard"]
    assert panel_buttons(panel) == ["Dashboard"]


def t_clicking_history_button_jumps_back():
    install_stubs()
    app = FakeApp()
    panel = attach_recent_history(app)
    app.show("billing")
    app.show("purchases")
    assert panel_buttons(panel) == ["Billing", "Dashboard"]
    btns = panel.btns.winfo_children()
    btns[0].invoke()  # click "Billing"
    assert app.current == "billing"
    assert app.shown[-1] == "billing"
    assert panel.history == ["billing", "purchases", "dashboard"]
    assert panel_buttons(panel) == ["Purchases", "Dashboard"]


def t_repeated_show_of_same_screen_stays_single():
    install_stubs()
    app = FakeApp()
    panel = attach_recent_history(app)
    app.show("billing")
    app.show("billing")
    assert panel.history == ["billing", "dashboard"]
    assert panel_buttons(panel) == ["Dashboard"]


def t_attach_twice_returns_same_panel():
    install_stubs()
    app = FakeApp()
    first = attach_recent_history(app)
    second = attach_recent_history(app)
    assert first is second
    app.show("billing")
    assert first.history == ["billing", "dashboard"]


def t_unknown_key_falls_back_to_key():
    install_stubs()
    app = FakeApp()
    panel = attach_recent_history(app)
    app.show("mystery")
    app.show("billing")  # mystery is now in the jump list, with no nav label
    assert panel_buttons(panel) == ["mystery", "Dashboard"]


def t_empty_label_shown_only_when_nothing_to_jump_to():
    install_stubs()
    app = FakeApp()
    panel = attach_recent_history(app)
    assert panel.empty_lbl.packed is True
    app.show("billing")
    assert panel.empty_lbl.packed is False
    app.show("dashboard")
    assert panel.empty_lbl.packed is False  # billing is on offer now
    assert panel_buttons(panel) == ["Billing"]


if __name__ == "__main__":
    print("Round 30 tests (recent-history quick jump):")
    for name, fn in [
            ("first visit goes first", t_first_visit_goes_first),
            ("revisit moves to front, no duplicates",
             t_revisit_moves_to_front_no_duplicates),
            ("input list not mutated", t_input_list_not_mutated),
            ("cap at eight", t_cap_at_eight),
            ("empty key ignored", t_empty_key_ignored),
            ("jump list excludes current", t_jump_list_excludes_current),
            ("jump list caps", t_jump_list_caps),
            ("attach seeds dashboard and wraps show",
             t_attach_seeds_dashboard_and_wraps_show),
            ("clicking history button jumps back",
             t_clicking_history_button_jumps_back),
            ("repeated show of same screen stays single",
             t_repeated_show_of_same_screen_stays_single),
            ("attach twice returns same panel",
             t_attach_twice_returns_same_panel),
            ("unknown key falls back to key",
             t_unknown_key_falls_back_to_key),
            ("empty label shown only when nothing to jump to",
             t_empty_label_shown_only_when_nothing_to_jump_to),
    ]:
        check(name, fn)
    print(f"\n{PASSED} passed, {len(FAILED)} failed")
    sys.exit(1 if FAILED else 0)
