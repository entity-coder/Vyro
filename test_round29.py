"""Headless tests for Round 29 — shop expense tracker.

Real temp SQLite DB (no GUI). Run: python3 test_round29.py
Covers: add/list/delete, newest-first order, invalid date/category/mode/
amount/description rejected, monthly totals by category (incl. empty
month), month isolation, the shop_expenses table appearing on an old
database, and the Cash Book still recording entries exactly as before.
"""

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from db import DB  # noqa: E402
from shop_expenses import expense_month_rows, expense_summary  # noqa: E402

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


# --- add / list ------------------------------------------------------------
def t_add_and_list_newest_first():
    db, tmp = make_db()
    first = db.add_shop_expense("2026-11-10", "Rent", "Shop rent Nov",
                                15000, "Bank", "Paid to landlord")
    second = db.add_shop_expense("2026-11-17", "Electricity",
                                 "Nov bill", 2350, "UPI")
    assert first > 0 and second > first
    rows = expense_month_rows(db, "2026-11")
    assert len(rows) == 2
    assert rows[0]["description"] == "Nov bill"  # newest first
    assert (rows[0]["category"], rows[0]["amount"],
            rows[0]["mode"]) == ("Electricity", 2350, "UPI")
    assert (rows[1]["category"], rows[1]["amount"],
            rows[1]["mode"]) == ("Rent", 15000, "Bank")
    assert rows[1]["note"] == "Paid to landlord"
    tmp.cleanup()


def t_default_mode_is_cash():
    db, tmp = make_db()
    db.add_shop_expense("2026-11-17", "Transport", "Tempo hire", 800)
    assert expense_month_rows(db, "2026-11")[0]["mode"] == "Cash"
    tmp.cleanup()


def t_list_without_month_returns_all():
    db, tmp = make_db()
    db.add_shop_expense("2026-11-17", "Rent", "Nov rent", 15000)
    db.add_shop_expense("2026-10-17", "Rent", "Oct rent", 15000)
    assert len(db.list_shop_expenses()) == 2
    tmp.cleanup()


def t_delete_removes_row():
    db, tmp = make_db()
    rid = db.add_shop_expense("2026-11-17", "Repairs", "Shutter fix", 1200)
    db.add_shop_expense("2026-11-18", "Packing", "Bags", 450)
    db.delete_shop_expense(rid)
    rows = expense_month_rows(db, "2026-11")
    assert len(rows) == 1
    assert rows[0]["description"] == "Bags"
    tmp.cleanup()


# --- validation ------------------------------------------------------------
def t_invalid_date_rejected():
    db, tmp = make_db()
    for bad in ("17-11-2026", "2026-13-01", "2026-11-32", "", "2026/11/17"):
        try:
            db.add_shop_expense(bad, "Rent", "Rent", 1000)
        except ValueError:
            pass
        else:
            raise AssertionError(f"date {bad!r} did not raise ValueError")
    assert expense_month_rows(db, "2026-11") == []
    tmp.cleanup()


def t_invalid_category_rejected():
    db, tmp = make_db()
    for bad in ("Salary", "Food", "salary", "rent", "", "General"):
        try:
            db.add_shop_expense("2026-11-17", bad, "Something", 1000)
        except ValueError:
            pass
        else:
            raise AssertionError(
                f"category {bad!r} did not raise ValueError")
    assert expense_month_rows(db, "2026-11") == []
    tmp.cleanup()


def t_invalid_mode_rejected():
    db, tmp = make_db()
    for bad in ("Card", "cash", "upi", "Cheque"):
        try:
            db.add_shop_expense("2026-11-17", "Rent", "Rent", 1000, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"mode {bad!r} did not raise ValueError")
    # Empty mode falls back to Cash, like supplier payments do.
    db.add_shop_expense("2026-11-17", "Rent", "Rent", 1000, "")
    assert expense_month_rows(db, "2026-11")[0]["mode"] == "Cash"
    tmp.cleanup()


def t_invalid_amount_rejected():
    db, tmp = make_db()
    for bad in (0, -500, "abc", None):
        try:
            db.add_shop_expense("2026-11-17", "Rent", "Rent", bad)
        except (ValueError, TypeError):
            pass
        else:
            raise AssertionError(f"amount {bad!r} did not raise")
    assert expense_month_rows(db, "2026-11") == []
    tmp.cleanup()


def t_missing_description_rejected():
    db, tmp = make_db()
    for bad in ("", "   "):
        try:
            db.add_shop_expense("2026-11-17", "Rent", bad, 1000)
        except ValueError:
            pass
        else:
            raise AssertionError("empty description did not raise")
    tmp.cleanup()


def t_invalid_month_rejected():
    db, tmp = make_db()
    db.add_shop_expense("2026-11-17", "Rent", "Rent", 1000)
    for bad in ("2026-13", "Nov 2026", "2026-1"):
        try:
            db.list_shop_expenses(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"month {bad!r} did not raise ValueError")
        try:
            db.monthly_expense_summary(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"month {bad!r} did not raise ValueError")
    # Empty month means "all months" for the list, like no filter.
    assert len(db.list_shop_expenses("")) == 1
    tmp.cleanup()


# --- monthly summary ---------------------------------------------------------
def t_monthly_totals_by_category():
    db, tmp = make_db()
    db.add_shop_expense("2026-11-05", "Rent", "Nov rent", 15000, "Bank")
    db.add_shop_expense("2026-11-10", "Electricity", "Bill", 2350, "UPI")
    db.add_shop_expense("2026-11-17", "Electricity", "Extra units", 650)
    db.add_shop_expense("2026-11-20", "Transport", "Tempo", 800, "Cash")
    total, count, totals = expense_summary(db, "2026-11")
    assert total == 18800, total
    assert count == 4
    assert totals == {"Rent": 15000, "Electricity": 3000,
                      "Transport": 800}, totals
    tmp.cleanup()


def t_month_isolation():
    db, tmp = make_db()
    db.add_shop_expense("2026-11-17", "Rent", "Nov rent", 15000)
    db.add_shop_expense("2026-12-01", "Rent", "Dec rent", 15000)
    assert expense_summary(db, "2026-11") == (15000, 1, {"Rent": 15000})
    assert expense_summary(db, "2026-12") == (15000, 1, {"Rent": 15000})
    assert len(expense_month_rows(db, "2026-11")) == 1
    tmp.cleanup()


def t_empty_month_zeros():
    db, tmp = make_db()
    assert expense_summary(db, "2026-11") == (0, 0, {})
    assert expense_month_rows(db, "2026-11") == []
    tmp.cleanup()


# --- migration ---------------------------------------------------------------
def t_migration_creates_expenses_table():
    """A DB built by an older build (no shop_expenses table) gains it
    when opened — CREATE TABLE IF NOT EXISTS runs on every open."""
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "old.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()
    db = DB(path)
    cols = [r["name"] for r in
            db.conn.execute("PRAGMA table_info(shop_expenses)").fetchall()]
    assert "category" in cols and "mode" in cols, cols
    rid = db.add_shop_expense("2026-11-17", "Miscellaneous", "Tape", 120)
    assert rid > 0
    assert expense_summary(db, "2026-11") == (120, 1,
                                              {"Miscellaneous": 120})
    tmp.cleanup()


# --- cash book untouched -------------------------------------------------------
def t_cash_book_still_works():
    db, tmp = make_db()
    db.add_cash_entry("2026-11-17", "out", "Shop rent Nov", "Rent", 15000)
    assert db.cash_balance() == -15000  # opening balance defaults to 0
    assert len(db.list_cash_entries()) == 1
    tmp.cleanup()


if __name__ == "__main__":
    print("Round 29 tests (shop expense tracker):")
    for name, fn in [
            ("add and list newest first", t_add_and_list_newest_first),
            ("default mode is Cash", t_default_mode_is_cash),
            ("list without month returns all",
             t_list_without_month_returns_all),
            ("delete removes row", t_delete_removes_row),
            ("invalid date rejected", t_invalid_date_rejected),
            ("invalid category rejected", t_invalid_category_rejected),
            ("invalid mode rejected", t_invalid_mode_rejected),
            ("invalid amount rejected", t_invalid_amount_rejected),
            ("missing description rejected", t_missing_description_rejected),
            ("invalid month rejected", t_invalid_month_rejected),
            ("monthly totals by category", t_monthly_totals_by_category),
            ("month isolation", t_month_isolation),
            ("empty month zeros", t_empty_month_zeros),
            ("migration creates expenses table",
             t_migration_creates_expenses_table),
            ("cash book still works (no regression)",
             t_cash_book_still_works),
    ]:
        check(name, fn)
    print(f"\n{PASSED} passed, {len(FAILED)} failed")
    sys.exit(1 if FAILED else 0)
