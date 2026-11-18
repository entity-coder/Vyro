"""Headless tests for Round 28 — staff attendance / shift log.

Real temp SQLite DB (no GUI). Run: python3 test_round28.py
Covers: shift set/get + invalid shift, record present/absent/leave +
upsert overwrite, one-row-per-day uniqueness, invalid date/status/time
rejected, unknown/inactive staff rejected, clock-in/out validation,
monthly counts per staff (incl. empty month zeros), monthly summary
totals, and the shift-column migration on a pre-existing (old-schema)
database. Staff pay logic is untouched — one check confirms a salary
payment still records and caps exactly as before.
"""

import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from db import DB  # noqa: E402
from staff_attendance import (  # noqa: E402
    attendance_day_rows,
    attendance_month_rows,
    attendance_summary,
)

TODAY = date(2026, 11, 17)
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


def add_staff(db, name, salary=12000, pay_day=5, shift=None):
    sid = db.add_staff(name, "Salesman", salary, pay_day, "9876543210")
    if shift:
        db.set_staff_shift(sid, shift)
    return sid


# --- shift set/get ---------------------------------------------------------
def t_shift_default_full_day():
    db, tmp = make_db()
    sid = add_staff(db, "Ramesh")
    assert db.get_staff_shift(sid) == "full day", db.get_staff(sid)
    tmp.cleanup()


def t_shift_set_get():
    db, tmp = make_db()
    sid = add_staff(db, "Ramesh")
    db.set_staff_shift(sid, "morning")
    assert db.get_staff_shift(sid) == "morning"
    db.set_staff_shift(sid, "evening")
    assert db.get_staff_shift(sid) == "evening"
    tmp.cleanup()


def t_shift_invalid_rejected():
    db, tmp = make_db()
    sid = add_staff(db, "Ramesh")
    for bad in ("night", "full-day", "", "Morning shift"):
        try:
            db.set_staff_shift(sid, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"shift {bad!r} did not raise ValueError")
    assert db.get_staff_shift(sid) == "full day"  # unchanged
    tmp.cleanup()


def t_shift_unknown_staff_rejected():
    db, tmp = make_db()
    try:
        db.set_staff_shift(999, "morning")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown staff did not raise ValueError")
    assert db.get_staff_shift(999) == ""
    tmp.cleanup()


def t_shift_case_insensitive():
    db, tmp = make_db()
    sid = add_staff(db, "Ramesh")
    db.set_staff_shift(sid, "Morning")
    assert db.get_staff_shift(sid) == "morning"
    tmp.cleanup()


# --- record attendance -----------------------------------------------------
def t_record_present_with_times():
    db, tmp = make_db()
    sid = add_staff(db, "Ramesh", shift="morning")
    rid = db.record_attendance(sid, "2026-11-17", "present",
                               "09:30", "18:00", note="On time")
    assert rid > 0
    rows = db.attendance_for_day("2026-11-17")
    assert len(rows) == 1
    r = rows[0]
    assert (r["status"], r["clock_in"], r["clock_out"], r["shift"],
            r["note"]) == ("present", "09:30", "18:00", "morning",
                           "On time"), r
    tmp.cleanup()


def t_record_uses_staff_shift_by_default():
    db, tmp = make_db()
    sid = add_staff(db, "Ramesh", shift="evening")
    db.record_attendance(sid, "2026-11-17", "present")
    rows = db.attendance_for_day("2026-11-17")
    assert rows[0]["shift"] == "evening", rows
    tmp.cleanup()


def t_record_absent_and_leave():
    db, tmp = make_db()
    sid = add_staff(db, "Sita")
    db.record_attendance(sid, "2026-11-16", "absent")
    db.record_attendance(sid, "2026-11-17", "leave", note="Sick")
    rows = db.attendance_for_month("2026-11")
    assert (rows[0]["present"], rows[0]["absent"], rows[0]["leave"]) == \
        (0, 1, 1), rows
    tmp.cleanup()


def t_upsert_overwrites_same_day():
    db, tmp = make_db()
    sid = add_staff(db, "Ramesh")
    first = db.record_attendance(sid, "2026-11-17", "present", "09:00",
                                 "18:00")
    second = db.record_attendance(sid, "2026-11-17", "leave", note="Left early")
    assert first == second  # same row, not a second one
    rows = db.attendance_for_day("2026-11-17")
    assert len(rows) == 1
    assert rows[0]["status"] == "leave", rows
    assert rows[0]["clock_in"] == ""  # overwritten, not kept
    assert rows[0]["note"] == "Left early", rows
    assert db.attendance_for_month("2026-11")[0]["leave"] == 1
    tmp.cleanup()


def t_one_row_per_day_enforced():
    db, tmp = make_db()
    sid = add_staff(db, "Ramesh")
    db.record_attendance(sid, "2026-11-17", "present")
    db.record_attendance(sid, "2026-11-17", "present")
    db.record_attendance(sid, "2026-11-17", "absent")
    count = db._one(
        "SELECT COUNT(*) c FROM staff_attendance WHERE staff_id=?",
        (sid,))["c"]
    assert count == 1, count
    tmp.cleanup()


# --- validation ------------------------------------------------------------
def t_invalid_date_rejected():
    db, tmp = make_db()
    sid = add_staff(db, "Ramesh")
    for bad in ("17-11-2026", "2026-13-01", "2026-11-32", "", "2026/11/17"):
        try:
            db.record_attendance(sid, bad, "present")
        except ValueError:
            pass
        else:
            raise AssertionError(f"date {bad!r} did not raise ValueError")
    tmp.cleanup()


def t_invalid_status_rejected():
    db, tmp = make_db()
    sid = add_staff(db, "Ramesh")
    for bad in ("late", "half day", "P", ""):
        try:
            db.record_attendance(sid, "2026-11-17", bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"status {bad!r} did not raise ValueError")
    tmp.cleanup()


def t_status_case_insensitive():
    db, tmp = make_db()
    sid = add_staff(db, "Ramesh")
    db.record_attendance(sid, "2026-11-17", "Present")
    assert db.attendance_for_day("2026-11-17")[0]["status"] == "present"
    tmp.cleanup()


def t_invalid_clock_times_rejected():
    db, tmp = make_db()
    sid = add_staff(db, "Ramesh")
    for bad_in, bad_out in (("9:30", ""), ("25:00", ""), ("09:60", ""),
                            ("", "18:99"), ("0930", "")):
        try:
            db.record_attendance(sid, "2026-11-17", "present",
                                 bad_in, bad_out)
        except ValueError:
            pass
        else:
            raise AssertionError(
                f"times {bad_in!r}/{bad_out!r} did not raise ValueError")
    tmp.cleanup()


def t_unknown_staff_rejected():
    db, tmp = make_db()
    try:
        db.record_attendance(999, "2026-11-17", "present")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown staff did not raise ValueError")
    tmp.cleanup()


def t_inactive_staff_rejected():
    db, tmp = make_db()
    sid = add_staff(db, "Imran")
    db.set_staff_active(sid, False)
    try:
        db.record_attendance(sid, "2026-11-17", "present")
    except ValueError:
        pass
    else:
        raise AssertionError("inactive staff did not raise ValueError")
    # Inactive staff also leave the monthly view.
    assert db.attendance_for_month("2026-11") == []
    tmp.cleanup()


# --- monthly counts / summary ----------------------------------------------
def t_monthly_counts_per_staff():
    db, tmp = make_db()
    r = add_staff(db, "Ramesh")
    s = add_staff(db, "Sita")
    for d in ("2026-11-16", "2026-11-17", "2026-11-18"):
        db.record_attendance(r, d, "present")
    db.record_attendance(r, "2026-11-19", "absent")
    db.record_attendance(r, "2026-11-20", "leave")
    db.record_attendance(s, "2026-11-16", "present")
    db.record_attendance(s, "2026-11-17", "absent")
    # A December record must not leak into November.
    db.record_attendance(r, "2026-12-01", "present")
    rows = {x["name"]: x for x in attendance_month_rows(db, "2026-11")}
    assert (rows["Ramesh"]["present"], rows["Ramesh"]["absent"],
            rows["Ramesh"]["leave"]) == (3, 1, 1), rows["Ramesh"]
    assert (rows["Sita"]["present"], rows["Sita"]["absent"],
            rows["Sita"]["leave"]) == (1, 1, 0), rows["Sita"]
    tmp.cleanup()


def t_empty_month_zeros():
    db, tmp = make_db()
    add_staff(db, "Ramesh")
    rows = attendance_month_rows(db, "2026-11")
    assert len(rows) == 1
    assert (rows[0]["present"], rows[0]["absent"], rows[0]["leave"]) == \
        (0, 0, 0), rows
    assert attendance_summary(db, "2026-11") == (0, 0, 0, 1)
    assert attendance_day_rows(db, "2026-11-17")[0]["status"] == ""
    tmp.cleanup()


def t_monthly_summary_totals():
    db, tmp = make_db()
    r = add_staff(db, "Ramesh")
    s = add_staff(db, "Sita")
    db.record_attendance(r, "2026-11-16", "present")
    db.record_attendance(r, "2026-11-17", "present")
    db.record_attendance(r, "2026-11-18", "leave")
    db.record_attendance(s, "2026-11-16", "absent")
    assert attendance_summary(db, "2026-11") == (2, 1, 1, 2)
    assert attendance_summary(db, "2026-12") == (0, 0, 0, 2)
    tmp.cleanup()


def t_monthly_view_shows_shift():
    db, tmp = make_db()
    add_staff(db, "Ramesh", shift="morning")
    add_staff(db, "Sita", shift="full day")
    rows = {x["name"]: x for x in attendance_month_rows(db, "2026-11")}
    assert rows["Ramesh"]["shift"] == "morning"
    assert rows["Sita"]["shift"] == "full day"
    tmp.cleanup()


# --- migration ---------------------------------------------------------------
def t_migration_adds_shift_column():
    """A DB built by an older build (staff without shift) gains the
    column with the 'full day' default when opened."""
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "old.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE staff (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                 " name TEXT NOT NULL, role TEXT DEFAULT '',"
                 " monthly_salary REAL NOT NULL DEFAULT 0,"
                 " pay_day INTEGER NOT NULL DEFAULT 1,"
                 " phone TEXT DEFAULT '',"
                 " active INTEGER NOT NULL DEFAULT 1,"
                 " created_at TEXT NOT NULL)")
    conn.execute("INSERT INTO staff (name, role, monthly_salary, pay_day,"
                 " phone, active, created_at) VALUES "
                 "('Old Staff', 'Loader', 9000, 5, '', 1, '2026-11-01')")
    conn.commit()
    conn.close()
    db = DB(path)
    cols = [r["name"] for r in
            db.conn.execute("PRAGMA table_info(staff)").fetchall()]
    assert "shift" in cols, cols
    assert db.get_staff_shift(1) == "full day"
    # The old staff row still works with the new attendance methods.
    db.record_attendance(1, "2026-11-17", "present", "09:00", "17:00")
    assert db.attendance_for_month("2026-11")[0]["present"] == 1
    tmp.cleanup()


# --- pay logic untouched -------------------------------------------------------
def t_staff_pay_still_works():
    db, tmp = make_db()
    sid = add_staff(db, "Ramesh", salary=12000, pay_day=5)
    db.record_staff_payment(sid, "2026-11", 5000, "2026-11-06", "Cash")
    assert db.staff_paid_for_month(sid, "2026-11") == 5000
    try:
        db.record_staff_payment(sid, "2026-11", 8000, "2026-11-07", "Cash")
    except ValueError:
        pass  # capped at the remaining 7000 — overpay still refused
    else:
        raise AssertionError("overpayment was not refused")
    assert db.staff_paid_for_month(sid, "2026-11") == 5000
    tmp.cleanup()


if __name__ == "__main__":
    print("Round 28 tests (staff attendance / shift log):")
    for name, fn in [
            ("shift default is full day", t_shift_default_full_day),
            ("shift set/get", t_shift_set_get),
            ("invalid shift rejected", t_shift_invalid_rejected),
            ("shift on unknown staff rejected",
             t_shift_unknown_staff_rejected),
            ("shift case-insensitive", t_shift_case_insensitive),
            ("record present with times", t_record_present_with_times),
            ("record uses staff shift by default",
             t_record_uses_staff_shift_by_default),
            ("record absent and leave", t_record_absent_and_leave),
            ("upsert overwrites same day", t_upsert_overwrites_same_day),
            ("one row per day enforced", t_one_row_per_day_enforced),
            ("invalid date rejected", t_invalid_date_rejected),
            ("invalid status rejected", t_invalid_status_rejected),
            ("status case-insensitive", t_status_case_insensitive),
            ("invalid clock times rejected",
             t_invalid_clock_times_rejected),
            ("unknown staff rejected", t_unknown_staff_rejected),
            ("inactive staff rejected", t_inactive_staff_rejected),
            ("monthly counts per staff", t_monthly_counts_per_staff),
            ("empty month zeros", t_empty_month_zeros),
            ("monthly summary totals", t_monthly_summary_totals),
            ("monthly view shows shift", t_monthly_view_shows_shift),
            ("migration adds shift column",
             t_migration_adds_shift_column),
            ("staff pay still works (no regression)",
             t_staff_pay_still_works),
    ]:
        check(name, fn)
    print(f"\n{PASSED} passed, {len(FAILED)} failed")
    sys.exit(1 if FAILED else 0)
