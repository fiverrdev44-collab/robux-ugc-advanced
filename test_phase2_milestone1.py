"""Phase 2 — Milestone 1: reporting-integrity tests (offline).

Covers snapshot-based velocity labeling, failure-pattern ratios without the
999 placeholder, and corrected whale-radar scope labels. No DB writes/network.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def joined_row(item_id, name, favs, snap_favs, snap_at, price=50,
               creator="c1"):
    return (item_id, name, creator, price, favs,
            NOW - timedelta(hours=30), snap_favs, snap_at)


class GoldenHourTests(unittest.TestCase):
    def test_velocity_only_when_snapshots_support_it(self):
        rows = [
            # Measured: +20 favorites over 24h.
            joined_row(1, "Aura Emote", 150, 100, NOW - timedelta(hours=24)),
            joined_row(1, "Aura Emote", 150, 120, NOW),
            # One snapshot only.
            joined_row(2, "Plain Hat", 500, 480, NOW - timedelta(hours=5)),
            # Two snapshots 0.5h apart: insufficient span.
            joined_row(3, "Boots", 100, 95, NOW - timedelta(minutes=30)),
            joined_row(3, "Boots", 100, 100, NOW),
            # Measured flat: 0 growth over 24h.
            joined_row(4, "Cape", 80, 80, NOW - timedelta(hours=24)),
            joined_row(4, "Cape", 80, 80, NOW),
            # Missing favorites, no snapshots.
            joined_row(5, "Null", None, None, None),
        ]
        cur = StubCursor([rows])
        metrics = golden_hour_metrics(cur, limit=10)
        by_id = {r["item_id"]: r for r in metrics["items"]}

        self.assertEqual(metrics["measured_count"], 2)
        self.assertEqual(metrics["unmeasured_count"], 3)
        self.assertEqual([r["item_id"] for r in metrics["items"]],
                         [1, 4, 2, 3, 5])

        self.assertTrue(by_id[1]["velocity_measured"])
        self.assertEqual(by_id[1]["velocity"], 20.0)
        self.assertEqual(by_id[1]["snapshot_span_hours"], 24.0)
        self.assertTrue(by_id[4]["velocity_measured"])
        self.assertEqual(by_id[4]["velocity"], 0.0)

        self.assertFalse(by_id[2]["velocity_measured"])
        self.assertIsNone(by_id[2]["velocity"])
        self.assertFalse(by_id[3]["velocity_measured"])
        self.assertFalse(by_id[5]["velocity_measured"])
        self.assertIsNone(by_id[5]["favorites"])
        self.assertIn("item_history", cur.executed[0][0])

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
