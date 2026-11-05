"""Phase 2 — Milestone 1: reporting-integrity tests (offline).

Covers snapshot-based velocity labeling, failure-pattern ratios without the
999 placeholder, and corrected whale-radar scope labels. No DB writes/network.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pattern_forge
from commands_supercomputer import (
    golden_hour_metrics, WHALE_RADAR_TITLE, WHALE_RADAR_DESCRIPTION,
    WHALE_RADAR_FOOTER,
)

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


class StubCursor:
    def __init__(self, results=None):
        self._results = list(results or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        if not self._results:
            return []
        result = self._results.pop(0)
        return result if isinstance(result, list) else [result]


def sql_row(item_id, name, favs, velocity, span_hours, snapshot_count=2,
            price=50, creator="c1"):
    """Shape returned by the SQL aggregation/ranking query."""
    return (item_id, name, creator, price, favs, NOW - timedelta(hours=30),
            snapshot_count, span_hours, velocity, velocity is not None)


class GoldenHourTests(unittest.TestCase):
    def test_maps_measured_zero_negative_and_unmeasured(self):
        rows = [
            sql_row(1, "Aura Emote", 150, 20.0, 24.0, 2),
            sql_row(4, "Cape", 80, 0.0, 24.0, 2),
            sql_row(6, "Decline", 40, -5.0, 12.0, 2),
            sql_row(2, "Plain Hat", 500, None, None, 1),
            sql_row(3, "Boots", 100, None, None, 2),
            sql_row(5, "Null", None, None, None, 0),
        ]
        cur = StubCursor([rows])
        metrics = golden_hour_metrics(cur, limit=10)

        self.assertEqual(metrics["measured_count"], 3)
        self.assertEqual(metrics["unmeasured_count"], 3)
        self.assertEqual([r["item_id"] for r in metrics["items"]],
                         [1, 4, 6, 2, 3, 5])

        by_id = {r["item_id"]: r for r in metrics["items"]}
        self.assertTrue(by_id[1]["velocity_measured"])
        self.assertEqual(by_id[1]["velocity"], 20.0)
        self.assertEqual(by_id[1]["snapshot_span_hours"], 24.0)
        self.assertTrue(by_id[4]["velocity_measured"])
        self.assertEqual(by_id[4]["velocity"], 0.0)
        self.assertTrue(by_id[6]["velocity_measured"])
        self.assertEqual(by_id[6]["velocity"], -5.0)

        self.assertFalse(by_id[2]["velocity_measured"])
        self.assertIsNone(by_id[2]["velocity"])
        self.assertIsNone(by_id[2]["snapshot_span_hours"])
        self.assertEqual(by_id[2]["snapshot_count"], 1)
        self.assertFalse(by_id[3]["velocity_measured"])
        self.assertFalse(by_id[5]["velocity_measured"])
        self.assertIsNone(by_id[5]["favorites"])

    def test_sql_aggregates_ranks_and_limits(self):
        cur = StubCursor([[]])
        golden_hour_metrics(cur, limit=7)
        sql, params = cur.executed[0]
        self.assertIn("WITH recent", sql)
        self.assertIn("GROUP BY r.id", sql)
        self.assertIn("array_agg", sql)
        self.assertIn("snapshot_count >= 2", sql)
        self.assertIn(">= %s", sql)
        self.assertIn("ORDER BY (velocity IS NOT NULL) DESC", sql)
        self.assertIn("favorite_count DESC NULLS LAST", sql)
        self.assertIn("LIMIT %s", sql)
        self.assertIn("h.snapshot_at >= NOW() - INTERVAL '48 hours'", sql)
        self.assertEqual(params, (3600, 7))

    def test_large_result_is_bounded_to_limit(self):
        rows = [sql_row(i, f"Item {i}", 10000 - i, float(i), 24.0)
                for i in range(10000)]
        cur = StubCursor([rows])
        metrics = golden_hour_metrics(cur, limit=5)
        self.assertEqual(len(metrics["items"]), 5)
        self.assertEqual([r["item_id"] for r in metrics["items"]],
                         [0, 1, 2, 3, 4])

    def test_database_error_and_timeout_propagate(self):
        class ErrorCursor:
            def __init__(self, error):
                self.error = error

            def execute(self, *args, **kwargs):
                raise self.error

        with self.assertRaises(TimeoutError):
            golden_hour_metrics(ErrorCursor(TimeoutError("timeout")),
                                limit=5)
        with self.assertRaises(psycopg2.errors.QueryCanceled):
            golden_hour_metrics(
                ErrorCursor(psycopg2.errors.QueryCanceled("canceled")),
                limit=5)

    def test_old_velocity_claims_removed_from_source(self):
        source = Path(__file__).with_name(
            "commands_supercomputer.py").read_text(encoding="utf-8")
        self.assertNotIn("48-Hour Golden Window Velocity Radar", source)
        self.assertNotIn("Algorithmic Testing Window Tracker", source)
        self.assertNotIn("New items gaining algorithmic momentum", source)


class FailurePatternTests(unittest.TestCase):
    def test_zero_comparison_frequency_is_not_999(self):
        rows = [
            # Underperformers: "cursed" and "hat" appear 3 times.
            (1, "Cursed Hat", 0, 50, 61, NOW, "c1"),
            (2, "Cursed Hat Two", 0, 50, 61, NOW, "c2"),
            (3, "Cursed Hat Three", 1, 50, 61, NOW, "c3"),
            # High-favorite comparison group: "hat" appears once.
            (4, "Winner Hat", 300, 50, 61, NOW, "c4"),
            (5, "Winner Cap", 400, 50, 61, NOW, "c5"),
        ]
        cur = StubCursor([rows])
        results = pattern_forge.mine_failure_patterns(cur, min_sample=2)
        by_word = {r["word"]: r for r in results}

        cursed = by_word["cursed"]
        self.assertIsNone(cursed["ratio"])
        self.assertEqual(cursed["perf_count"], 0)
        self.assertEqual(cursed["perf_total"], 2)
        self.assertEqual(cursed["under_total"], 3)
        self.assertIn("no high-favorite comparison occurrences",
                      cursed["evidence"])

        hat = by_word["hat"]
        self.assertEqual(hat["ratio"], 2.0)
        self.assertEqual(hat["under_count"], 3)
        self.assertEqual(hat["perf_count"], 1)
        self.assertEqual(hat["perf_total"], 2)

        text = pattern_forge.format_failure_patterns(results)
        self.assertNotIn("999", text)
        self.assertIn("n/a", text)
        self.assertIn("3/3", text)
        self.assertIn("1/2", text)


class WhaleLabelTests(unittest.TestCase):
    def test_labels_do_not_claim_live_50_studio_surveillance(self):
        self.assertIn("not live", WHALE_RADAR_DESCRIPTION.lower())
        self.assertIn("not 50-studio", WHALE_RADAR_DESCRIPTION.lower())
        self.assertIn("not live", WHALE_RADAR_FOOTER.lower())
        self.assertNotIn("surveillance of top 50",
                         WHALE_RADAR_DESCRIPTION.lower())
        self.assertIn("Catalog Sample", WHALE_RADAR_TITLE)
        source = Path(__file__).with_name(
            "commands_supercomputer.py").read_text(encoding="utf-8")
        self.assertNotIn("Live surveillance of top 50 studios", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
