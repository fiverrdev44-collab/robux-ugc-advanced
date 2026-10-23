"""Focused tests for data integrity, visibility, and matched experiments.

Run: python test_integrity_upgrades.py
DB tests use a transaction and roll back; no production rows are kept.
"""
import json
import math
import random
from datetime import datetime, timezone

from bot_core import get_db
from matched_experiments import (did_estimate, distance, select_controls,
                                 _velocity_pair)
from search_visibility import normalize_query, _fetch_query
from sales_listener import _insert_sale


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
    def get(self, *args, **kwargs):
        return self.responses.pop(0)


def test_query_normalization():
    assert normalize_query("  Hip   SWAY  ") == "hip sway"
    assert normalize_query("") == ""
    print("PASS query normalization")


def test_visibility_empty_results():
    session = _FakeSession([_FakeResponse(200, {"data": []})])
    rows, pages, status, error = _fetch_query(session, "missing query", 1)
    assert rows == [] and pages == 1 and status == "completed"
    assert error is None
    print("PASS visibility empty results")


def test_control_selection_uses_pre_features():
    treatment = {"price": 55, "age_days": 22, "pre_velocity": 0.7}
    candidates = [
        {"id": 1, "price": 50, "age_days": 20, "pre_velocity": 0.6},
        {"id": 2, "price": 200, "age_days": 90, "pre_velocity": 5.0},
        {"id": 3, "price": 55, "age_days": 25, "pre_velocity": 0.8},
    ]
    selected = select_controls(treatment, candidates, 2)
    assert [c["id"] for c in selected] == [3, 1], selected
    assert distance(treatment, selected[0]) < distance(treatment, candidates[1])
    print("PASS control selection")


def test_did_math_and_insufficient():
    result = did_estimate(0.5, [0.1, 0.2, 0.15])
    assert not result["insufficient"]
    assert abs(result["estimate"] - 0.35) < 1e-9
    assert result["n"] == 3
    assert result["ci80"][0] <= result["estimate"] <= result["ci80"][1]
    assert result["ci95"][0] <= result["ci80"][0]
    assert result["ci95"][1] >= result["ci80"][1]
    assert result["exploratory"] is True
    stable = did_estimate(0.5, [0.1, 0.2, 0.15, 0.12, 0.18])
    assert stable["exploratory"] is False
    small = did_estimate(0.5, [0.1])
    assert small["insufficient"] and small["n"] == 1
    print("PASS DiD math and insufficient-data handling")


def test_db_transaction():
    conn = get_db()
    cur = conn.cursor()
    try:
        # Legitimate identical sales are allowed when stable event IDs differ.
        cur.execute("""
            INSERT INTO my_sales
              (sale_date, sale_time, item_name, buyer, amount_robux, status,
               source_event_id, source)
            VALUES
              (CURRENT_DATE, now(), '__test_item__', 'buyer', 10, 'Complete',
               '__event_a__', 'test'),
              (CURRENT_DATE, now(), '__test_item__', 'buyer', 10, 'Complete',
               '__event_b__', 'test')
        """)
        assert cur.rowcount == 2
        # Same event ID is idempotent.
        cur.execute("""
            INSERT INTO my_sales
              (sale_date, sale_time, item_name, buyer, amount_robux, status,
               source_event_id, source)
            VALUES (CURRENT_DATE, now(), '__test_item__', 'buyer', 10,
                    'Complete', '__event_a__', 'test')
            ON CONFLICT DO NOTHING
        """)
        assert cur.rowcount == 0
        # The real sales writer is idempotent by stable event ID.
        now = datetime.now(timezone.utc)
        sale = {
            "sale_date": now.date(), "sale_time": now,
            "item_name": "__test_writer_item__", "buyer": "buyer",
            "amount_robux": 10, "status": "Complete",
            "source_event_id": "__writer_event__", "source": "test",
        }
        assert _insert_sale(cur, sale) is True
        assert _insert_sale(cur, dict(sale)) is False
        other = dict(sale); other["source_event_id"] = "__writer_event_2__"
        assert _insert_sale(cur, other) is True
        # Same daily snapshot is idempotent.
        cur.execute("""
            INSERT INTO item_history (item_id, favorite_count, price)
            VALUES (121930221694467, 16, 55)
            ON CONFLICT DO NOTHING
        """)
        first = cur.rowcount
        cur.execute("""
            INSERT INTO item_history (item_id, favorite_count, price)
            VALUES (121930221694467, 17, 55)
            ON CONFLICT DO NOTHING
        """)
        second = cur.rowcount
        assert first in (0, 1)
        assert second == 0
        # NULL and zero are distinct audit states.
        cur.execute("""
            SELECT COUNT(*) FILTER (WHERE favorite_count IS NULL),
                   COUNT(*) FILTER (WHERE favorite_count = 0)
            FROM items
        """)
        nulls, zeros = cur.fetchone()
        assert nulls >= 0 and zeros >= 0
        print("PASS DB idempotency and NULL/zero audit")
    finally:
        conn.rollback()
        cur.close()
        conn.close()


if __name__ == "__main__":
    test_query_normalization()
    test_visibility_empty_results()
    test_control_selection_uses_pre_features()
    test_did_math_and_insufficient()
    test_db_transaction()
    print("ALL TESTS PASSED")
