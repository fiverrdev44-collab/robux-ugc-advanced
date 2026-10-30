"""Recommendation lifecycle tests: application evidence and existing payloads."""
import os
import sys

from experiments import application_matches


def test_application_matches():
    r = application_matches("Cute Kitty Fluffy Beanie", 55,
                            "Cute Kitty Fluffy Beanie", 55)
    assert r["name_match"] and r["price_match"] and r["verified"]

    r = application_matches("Cute Kitty Fluffy Beanie", 55,
                            "Cute Kitty Fluffy Beanie", 60)
    assert r["verified"] and r["name_match"] and not r["price_match"]

    r = application_matches("Different Title", 55,
                            "Cute Kitty Fluffy Beanie", 60)
    assert not r["verified"]

    r = application_matches("Different Title", 60, None, 60)
    assert r["verified"] and r["price_match"]
    print("PASS application verification")


def test_db_payloads():
    if not os.getenv("DATABASE_URL"):
        print("SKIP db recommendation fixtures (no DATABASE_URL)")
        return
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from bot_core import get_db

    con = get_db()
    con.set_session(readonly=True)
    cur = con.cursor()
    try:
        cur.execute("SET statement_timeout='20s'")
        cols = {}
        cur.execute("""
            select column_name from information_schema.columns
            where table_name = 'recommendation_ledger'
        """)
        cols = {r[0] for r in cur.fetchall()}
        for required in ("hypothesis", "proposed_change", "success_condition",
                         "application_status", "application_evidence",
                         "maturity", "contaminated", "superseded_by"):
            assert required in cols, required

        cur.execute("""
            select did_estimate, outcome, control_n
            from recommendation_ledger where id = 10
        """)
        row = cur.fetchone()
        if row:
            did, outcome, control_n = row
            if did is not None:
                assert did.get("insufficient") is True, did
            assert control_n in (0, None) or control_n >= 0
        print("PASS recommendation schema and rec-10 insufficiency marker")
    finally:
        try:
            con.rollback()
        finally:
            con.close()


if __name__ == "__main__":
    test_application_matches()
    test_db_payloads()
    print("ALL RECOMMENDATION TESTS PASSED")
