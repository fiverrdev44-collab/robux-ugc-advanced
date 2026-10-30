"""Identity, alias and reporting-window tests.

Pure tests run everywhere. Database fixture tests run only when DATABASE_URL
is set (they open a read-only transaction and never write).
"""
import os
import sys
from datetime import date

from item_resolver import normalize_name
from reporting import window_bounds, describe_window


def test_normalize():
    assert normalize_name("NAME : ⭐Smooth 360 flip Rizz ") == "smooth 360 flip rizz"
    assert normalize_name("Cute Kitty Fluffy Beanie🎀") == "cute kitty fluffy beanie"
    assert normalize_name("cute  beanie   w paws") == "cute beanie w paws"
    print("PASS normalization")


class _FakeCur:
    def __init__(self, anchor):
        self.anchor = anchor

    def execute(self, *_a, **_k):
        pass

    def fetchone(self):
        return (self.anchor,)


def test_windows():
    anchor = date(2026, 10, 30)
    start, end, a = window_bounds(_FakeCur(anchor), 7)
    assert (start, end) == (date(2026, 10, 24), date(2026, 10, 31))
    start, end, a = window_bounds(_FakeCur(anchor), 30)
    assert (start, end) == (date(2026, 10, 1), date(2026, 10, 31))
    start, end, a = window_bounds(_FakeCur(anchor), 90)
    assert (start, end) == (date(2026, 8, 2), date(2026, 10, 31))
    meta = describe_window(start, end, a)
    assert meta["today_partial"] is True and meta["days"] == 90
    print("PASS window bounds")


def test_db_fixtures():
    if not os.getenv("DATABASE_URL"):
        print("SKIP db fixtures (no DATABASE_URL)")
        return
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from bot_core import get_db
    from item_resolver import resolve_name, sales_breakdown

    con = get_db()
    con.set_session(readonly=True)
    cur = con.cursor()
    try:
        cur.execute("SET statement_timeout='20s'")
        expected = {"7": (27, 422), "30": (149, 2465), "90": (495, 8828)}
        for days, (records, robux) in expected.items():
            s, e, _ = window_bounds(cur, int(days), anchor=date(2026, 10, 30))
            data = sales_breakdown(cur, s, e)
            t = data["totals"]
            assert (t["records"], t["robux"]) == (records, robux), (days, t)
            assert (t["mapped_records"] + t["unresolved_records"]
                    + t["ambiguous_records"]) == t["records"]
        print("PASS frozen window fixtures")

        a = resolve_name(cur, "Cute Beanie w paws")
        b = resolve_name(cur, "Cute Kitty Fluffy Beanie")
        assert a["item_id"] == b["item_id"] == 130928797494687, (a, b)
        assert a["status"] == b["status"] == "confirmed"

        data = sales_breakdown(cur, date(2026, 1, 1), date(2026, 10, 31))
        beanie = next(g for g in data["items"]
                      if g["item_id"] == 130928797494687)
        assert (beanie["records"], beanie["robux"]) == (139, 4045), beanie
        print("PASS creator-confirmed beanie fixture (139 / 4045)")

        flip = resolve_name(cur, "Smooth 360 flip Rizz")
        assert flip["item_id"] == 92364796546749 and flip["status"] == "candidate"
        print("PASS flip candidate identity")
    finally:
        try:
            con.rollback()
        finally:
            con.close()


if __name__ == "__main__":
    test_normalize()
    test_windows()
    test_db_fixtures()
    print("ALL IDENTITY TESTS PASSED")
