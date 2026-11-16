"""Headless tests for Round 27 — supplier payment reminders.

Real temp SQLite DB (no GUI). Run: python3 test_round27.py
Covers: per-supplier owed amounts, due-date set/get, overdue flag,
all three language drafts, WhatsApp link shape, empty cases, and the
pay_due_date migration on a pre-existing (old-schema) database.
"""

import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from db import DB  # noqa: E402
from new_features import whatsapp_link  # noqa: E402
from supplier_pay import (  # noqa: E402
    supplier_pay_reminders,
    supplier_pay_summary,
    supplier_reminder_message,
)

TODAY = date(2026, 11, 16)
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


def make_db():
    tmp = tempfile.TemporaryDirectory()
    return DB(Path(tmp.name) / "test.db"), tmp


def add_owed(db, name, amount, phone="9876543210"):
    """Supplier with one purchase of `amount` (so that much is owed)."""
    sid = db.add_supplier(name, phone)
    db.create_purchase(sid, "2026-11-10", "INV-1",
                       [{"name": "Sugar", "qty": 1, "cost": amount}])
    return sid


# --- per-supplier owed amounts -------------------------------------------
def t_owed_amounts():
    db, tmp = make_db()
    a = add_owed(db, "Sharma Traders", 5000)
    b = add_owed(db, "Patel Stores", 3000)
    db.record_supplier_payment(b, 1000)  # part-payment
    rows = supplier_pay_reminders(db, TODAY)
    by_name = {r["name"]: r for r in rows}
    assert by_name["Sharma Traders"]["owed"] == 5000, by_name
    assert by_name["Patel Stores"]["owed"] == 2000, by_name
    assert rows[0]["name"] == "Sharma Traders"  # most owed first
    total, count, overdue = supplier_pay_summary(db, TODAY)
    assert (total, count, overdue) == (7000, 2, 0), (total, count, overdue)
    tmp.cleanup()


def t_fully_paid_supplier_absent():
    db, tmp = make_db()
    sid = add_owed(db, "Paid Supplier", 1000)
    db.record_supplier_payment(sid, 1000)
    assert db.supplier_outstanding(sid) == 0
    assert supplier_pay_reminders(db, TODAY) == []
    tmp.cleanup()


# --- due-date set/get ------------------------------------------------------
def t_due_date_set_get():
    db, tmp = make_db()
    sid = add_owed(db, "Dated Supplier", 1000)
    assert db.get_supplier_due_date(sid) == ""
    db.set_supplier_due_date(sid, "2026-11-20")
    assert db.get_supplier_due_date(sid) == "2026-11-20"
    db.set_supplier_due_date(sid, "")  # clears it
    assert db.get_supplier_due_date(sid) == ""
    tmp.cleanup()


def t_due_date_bad_value():
    db, tmp = make_db()
    sid = add_owed(db, "Bad Date Supplier", 1000)
    try:
        db.set_supplier_due_date(sid, "20-11-2026")
    except ValueError:
        pass
    else:
        raise AssertionError("bad date did not raise ValueError")
    tmp.cleanup()


def t_migration_adds_column():
    """A DB built by an older build (suppliers without pay_due_date)
    gains the column when opened."""
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "old.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE suppliers (id INTEGER PRIMARY KEY "
                 "AUTOINCREMENT, name TEXT NOT NULL, phone TEXT DEFAULT '',"
                 " address TEXT DEFAULT '')")
    conn.commit()
    conn.close()
    db = DB(path)
    cols = [r["name"] for r in
            db.conn.execute("PRAGMA table_info(suppliers)").fetchall()]
    assert "pay_due_date" in cols, cols
    tmp.cleanup()


# --- overdue flag ----------------------------------------------------------
def t_overdue_past_due_and_owed():
    db, tmp = make_db()
    sid = add_owed(db, "Late Supplier", 1000)
    db.set_supplier_due_date(sid, "2026-11-15")  # yesterday
    rows = supplier_pay_reminders(db, TODAY)
    assert len(rows) == 1 and rows[0]["overdue"] is True, rows
    assert supplier_pay_summary(db, TODAY) == (1000, 1, 1)
    tmp.cleanup()


def t_not_overdue_future_due():
    db, tmp = make_db()
    sid = add_owed(db, "Future Supplier", 1000)
    db.set_supplier_due_date(sid, "2026-11-20")  # in 4 days
    rows = supplier_pay_reminders(db, TODAY)
    assert rows[0]["overdue"] is False, rows
    tmp.cleanup()


def t_not_overdue_no_due_date():
    db, tmp = make_db()
    add_owed(db, "No Date Supplier", 1000)
    rows = supplier_pay_reminders(db, TODAY)
    assert rows[0]["overdue"] is False, rows
    tmp.cleanup()


def t_not_overdue_when_paid():
    """Past due date but fully paid: not in the reminders at all."""
    db, tmp = make_db()
    sid = add_owed(db, "Paid Late Supplier", 1000)
    db.set_supplier_due_date(sid, "2026-11-01")
    db.record_supplier_payment(sid, 1000)
    assert supplier_pay_reminders(db, TODAY) == []
    tmp.cleanup()


def t_overdue_sorts_first():
    db, tmp = make_db()
    big = add_owed(db, "Big Current", 9000)
    db.set_supplier_due_date(big, "2026-12-01")
    small = add_owed(db, "Small Overdue", 500)
    db.set_supplier_due_date(small, "2026-11-01")
    rows = supplier_pay_reminders(db, TODAY)
    assert rows[0]["name"] == "Small Overdue", rows  # overdue first
    tmp.cleanup()


# --- reminder drafts -------------------------------------------------------
def t_drafts_all_languages():
    for lang in ("English", "Hindi", "Marathi"):
        msg = supplier_reminder_message("Vyro Store", "Sharma Traders",
                                        5000, "2026-11-20", lang)
        assert "Sharma Traders" in msg, (lang, msg)
        assert "5000.00" in msg, (lang, msg)
        assert "20 Nov 2026" in msg, (lang, msg)
        assert "Vyro Store" in msg, (lang, msg)


def t_drafts_no_due_date():
    msg = supplier_reminder_message("Vyro Store", "Sharma Traders",
                                    5000, "", "English")
    assert "Sharma Traders" in msg and "5000.00" in msg, msg
    assert "20 Nov 2026" not in msg, msg


def t_draft_unknown_lang_falls_back_to_english():
    msg = supplier_reminder_message("Vyro Store", "Sharma Traders",
                                    5000, "2026-11-20", "French")
    assert msg.startswith("Hello Sharma Traders"), msg


# --- WhatsApp link ---------------------------------------------------------
def t_whatsapp_link_shape():
    link = whatsapp_link("9876543210", "Hello, we will pay soon.")
    assert link.startswith("https://wa.me/919876543210?text="), link
    assert "Hello" in link, link


def t_whatsapp_link_no_phone():
    assert whatsapp_link("", "Hello") == ""
    assert whatsapp_link(None, "Hello") == ""


# --- empty cases -----------------------------------------------------------
def t_empty_db():
    db, tmp = make_db()
    assert supplier_pay_reminders(db, TODAY) == []
    assert supplier_pay_summary(db, TODAY) == (0, 0, 0)
    tmp.cleanup()


def t_supplier_with_no_purchases():
    db, tmp = make_db()
    db.add_supplier("No Purchases Yet", "9876543210")
    assert supplier_pay_reminders(db, TODAY) == []
    tmp.cleanup()


if __name__ == "__main__":
    print("Round 27 tests (supplier payment reminders):")
    for name, fn in [
            ("owed amounts per supplier", t_owed_amounts),
            ("fully paid supplier absent", t_fully_paid_supplier_absent),
            ("due-date set/get/clear", t_due_date_set_get),
            ("due-date bad value rejected", t_due_date_bad_value),
            ("migration adds pay_due_date", t_migration_adds_column),
            ("overdue: past due + owed", t_overdue_past_due_and_owed),
            ("not overdue: future due", t_not_overdue_future_due),
            ("not overdue: no due date", t_not_overdue_no_due_date),
            ("not overdue: paid despite past due",
             t_not_overdue_when_paid),
            ("overdue sorts first", t_overdue_sorts_first),
            ("drafts in all 3 languages", t_drafts_all_languages),
            ("draft without due date", t_drafts_no_due_date),
            ("draft unknown language falls back",
             t_draft_unknown_lang_falls_back_to_english),
            ("WhatsApp link shape", t_whatsapp_link_shape),
            ("WhatsApp link without phone", t_whatsapp_link_no_phone),
            ("empty DB", t_empty_db),
            ("supplier with no purchases", t_supplier_with_no_purchases),
    ]:
        check(name, fn)
    print(f"\n{PASSED} passed, {len(FAILED)} failed")
    sys.exit(1 if FAILED else 0)
