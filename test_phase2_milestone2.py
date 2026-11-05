"""Phase 2 — Milestone 2: creator discovery/registry tests (offline).

Synthetic fixtures only; no production writes, no network, no Roblox API calls.
"""
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import creator_registry as cr

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

    def fetchone(self):
        if not self._results:
            return None
        result = self._results.pop(0)
        return result[0] if isinstance(result, list) and result else result


def reg_row(item_id, ctype="User", cid=10, name="Creator", verified=False,
            asset=61, price=50, favs=100, age_days=20, snapshots=2,
            type_prov="tracked_creator", fetched_days=0):
    created = (NOW - timedelta(days=age_days)
               if age_days is not None else None)
    fetched = (NOW - timedelta(days=fetched_days)
               if fetched_days is not None else None)
    return (item_id, ctype, cid, name, verified, asset, price, favs,
            created, fetched, snapshots, type_prov)


def comp_row(item_id, ctype, cid, name, verified, asset=61, price=50,
             favs=100, age_days=20, snapshots=2, fetched_days=0):
    created = NOW - timedelta(days=age_days)
    fetched = NOW - timedelta(days=fetched_days)
    return (item_id, ctype, cid, name, verified, asset, price, favs,
            created, fetched, snapshots)


class RegistryBuildTests(unittest.TestCase):
    def test_identity_is_id_and_type_not_name(self):
        rows = [
            reg_row(1, "User", 10, "Same Name", True),
            reg_row(2, "User", 20, "Same Name", False),
            reg_row(3, "Group", 10, "Same Name", None),
        ]
        built = cr.build_registry_rows(rows, now=NOW)
        keys = {(r["creator_type"], r["creator_id"])
                for r in built["rows"]}
        self.assertEqual(keys, {("User", 10), ("User", 20), ("Group", 10)})
        self.assertEqual(built["diagnostics"]["creators"], 3)

    def test_name_change_preserved(self):
        rows = [
            reg_row(1, "User", 10, "Old Name", True, fetched_days=10),
            reg_row(2, "User", 10, "New Name", True, fetched_days=0),
        ]
        built = cr.build_registry_rows(rows, now=NOW)
        self.assertEqual(len(built["rows"]), 1)
        row = built["rows"][0]
        self.assertEqual(row["display_name"], "New Name")
        self.assertIn("Old Name", row["previous_names"])

    def test_missing_verification_is_unknown(self):
        built = cr.build_registry_rows(
            [reg_row(1, "User", 10, "A", None)], now=NOW)
        row = built["rows"][0]
        self.assertEqual(row["verification_status"], "unknown")
        self.assertEqual(row["verification_provenance"], "missing")

        nonverified = cr.build_registry_rows(
            [reg_row(2, "User", 20, "B", False)], now=NOW)["rows"][0]
        self.assertEqual(nonverified["verification_status"], "nonverified")

        verified = cr.build_registry_rows(
            [reg_row(3, "User", 30, "C", True)], now=NOW)["rows"][0]
        self.assertEqual(verified["verification_status"], "verified")

    def test_missing_creator_id_reported_not_registered(self):
        rows = [reg_row(1, "User", None, "No ID", True)]
        built = cr.build_registry_rows(rows, now=NOW)
        self.assertEqual(built["rows"], [])
        self.assertEqual(built["diagnostics"]["items_missing_creator_id"], 1)

    def test_duplicate_items_counted_once_latest_row_wins(self):
        rows = [
            reg_row(1, "User", 10, "A", True, favs=100, fetched_days=2),
            reg_row(1, "User", 10, "A", True, favs=120, fetched_days=0),
        ]
        built = cr.build_registry_rows(rows, now=NOW)
        row = built["rows"][0]
        self.assertEqual(row["item_count"], 1)
        self.assertEqual(row["median_favorites"], 120)
        self.assertEqual(built["diagnostics"]["duplicate_item_rows_removed"], 1)

    def test_category_price_age_snapshot_aggregation(self):
        rows = [
            reg_row(1, "User", 10, "A", True, asset=61, price=20,
                    favs=10, age_days=10, snapshots=1),
            reg_row(2, "User", 10, "A", True, asset=8, price=80,
                    favs=30, age_days=30, snapshots=3),
            reg_row(3, "User", 10, "A", True, asset=None, price=None,
                    favs=None, age_days=None, snapshots=None),
        ]
        row = cr.build_registry_rows(rows, now=NOW)["rows"][0]
        self.assertEqual(row["item_count"], 3)
        self.assertEqual(row["category_counts"], {"61": 1, "8": 1,
                                                  "unknown": 1})
        self.assertEqual(row["price_counts"], {"under_30": 1,
                                               "60_to_100": 1,
                                               "unknown": 1})
        self.assertEqual(row["median_favorites"], 20)
        self.assertEqual(row["median_price"], 50)
        self.assertEqual(row["snapshot_item_count"], 1)
        self.assertEqual(row["max_snapshots"], 3)
        self.assertEqual(row["missing_favorite_items"], 1)

    def test_partial_rows_do_not_crash(self):
        row = cr.build_registry_rows(
            [reg_row(1, None, 10, None, None, asset=None, price=None,
                     favs=None, age_days=None, snapshots=None,
                     type_prov="missing")], now=NOW)["rows"][0]
        self.assertEqual(row["creator_type"], "unknown")
        self.assertEqual(row["type_provenance"], "missing")
        self.assertEqual(row["verification_status"], "unknown")
        self.assertIsNone(row["median_favorites"])
        self.assertIsNone(row["median_age_days"])

    def test_build_is_idempotent(self):
        rows = [reg_row(1, "User", 10, "A", True),
                reg_row(2, "User", 10, "A", True)]
        first = cr.build_registry_rows(rows, now=NOW)
        second = cr.build_registry_rows(rows, now=NOW)
        self.assertEqual(first["rows"], second["rows"])
        self.assertEqual(first["diagnostics"], second["diagnostics"])


class RegistryPersistenceTests(unittest.TestCase):
    def test_upsert_is_keyed_and_preserves_history(self):
        built = cr.build_registry_rows(
            [reg_row(1, "User", 10, "A", True)], now=NOW)
        cur = StubCursor([])
        written = cr.upsert_registry(cur, built["rows"])
        self.assertEqual(written, 1)
        sql, params = cur.executed[0]
        self.assertIn("ON CONFLICT (creator_type, creator_id)", sql)
        self.assertIn("LEAST", sql)
        self.assertIn("GREATEST", sql)
        self.assertIn("previous_names", sql)
        self.assertEqual(params[0], "User")
        self.assertEqual(params[1], 10)
        self.assertEqual(json.loads(params[17]), [])

    def test_refresh_is_resumable_and_idempotent(self):
        batch = [reg_row(2, "Group", 20, "B", None),
                 reg_row(1, "User", 10, "A", True)]
        cur = StubCursor([batch, []])
        totals = cr.refresh_from_items(cur, batch_size=10, now=NOW)
        self.assertEqual(totals["batches"], 1)
        self.assertEqual(totals["creators"], 2)
        self.assertEqual(totals["items"], 2)
        self.assertTrue(totals["done"])
        self.assertEqual(totals["next_cursor"], ["User", 10])
        self.assertIn("WITH typed", cur.executed[0][0])
        self.assertEqual(cur.executed[0][1][0], None)
        self.assertEqual(cur.executed[0][1][3], 10)

    def test_refresh_cursor_resumes_across_invocations(self):
        first = cr.refresh_from_items(
            StubCursor([[reg_row(1, "Group", 10, "A", None)]]),
            batch_size=1, max_batches=1, now=NOW)
        self.assertFalse(first["done"])
        self.assertEqual(first["next_cursor"], ["Group", 10])
        self.assertEqual(first["started_after"], None)

        cur2 = StubCursor([[reg_row(2, "User", 20, "B", True)], []])
        second = cr.refresh_from_items(
            cur2, batch_size=1, cursor=first["next_cursor"], now=NOW)
        self.assertEqual(second["started_after"], ["Group", 10])
        self.assertEqual(second["next_cursor"], ["User", 20])
        self.assertTrue(second["done"])
        params = cur2.executed[0][1]
        self.assertEqual(params[0], "Group")
        self.assertEqual(params[2], 10)

    def test_composite_creator_type_resolution(self):
        self.assertEqual(
            cr.resolve_creator_type("User", "Group", "A", "A"),
            ("User", "item_catalog"))
        self.assertEqual(
            cr.resolve_creator_type(None, "Group", "Same", "Same"),
            ("Group", "tracked_name_match"))
        self.assertEqual(
            cr.resolve_creator_type(None, "Group", "Item Name", "Other"),
            ("unknown", "missing"))
        self.assertEqual(
            cr.resolve_creator_type(None, None, "Same", "Same"),
            ("unknown", "missing"))

    def test_refresh_sql_requires_composite_name_match(self):
        sql = cr._REFRESH_SQL
        self.assertIn("i.creator_type", sql)
        self.assertIn("lower(t2.creator_name) = lower(i.creator_name)", sql)
        self.assertIn("NULLIF(i.creator_type", sql)

    def test_upsert_previous_names_is_deduplicated(self):
        sql = cr._UPSERT_SQL
        self.assertIn("jsonb_agg(DISTINCT", sql)
        self.assertIn("jsonb_array_elements_text", sql)
        self.assertIn("n <> COALESCE(EXCLUDED.display_name", sql)

    def test_comparison_sql_is_deterministic_and_composite(self):
        sql = cr._COMPARISON_SQL
        self.assertIn("ORDER BY i.id", sql)
        self.assertIn("LIMIT %s", sql)
        self.assertIn("lower(t2.creator_name) = lower(i.creator_name)", sql)

    def test_comparison_pre_migration_type_fallback(self):
        cur = StubCursor([[]])
        cr.creator_comparison(cur, family=None, has_creator_type=False)
        sql = cur.executed[0][0]
        self.assertNotIn("i.creator_type", sql)
        self.assertIn("lower(t2.creator_name)", sql)
        self.assertIn("ORDER BY i.id", sql)

    def test_tracker_verification_tristate_and_type(self):
        from creator_tracker import _to_item
        missing = _to_item({"id": 1, "name": "A", "creatorTargetId": 10})
        self.assertIsNone(missing["creator_verified"])
        self.assertIsNone(missing["creator_type"])
        explicit_true = _to_item({
            "id": 2, "name": "B", "creatorTargetId": 20,
            "creatorType": "Group", "creatorHasVerifiedBadge": True})
        self.assertTrue(explicit_true["creator_verified"])
        self.assertEqual(explicit_true["creator_type"], "Group")
        explicit_false = _to_item({
            "id": 3, "name": "C", "creatorTargetId": 30,
            "creatorHasVerifiedBadge": False})
        self.assertFalse(explicit_false["creator_verified"])

    def test_tracker_upsert_preserves_unknown_and_composite(self):
        from creator_tracker import upsert_items
        cur = StubCursor([[(1,)]])  # information_schema: creator_type exists
        upsert_items(cur, [{
            "id": 1, "name": "A", "description": "",
            "favorite_count": 10, "price": 50, "creator_name": "Creator",
            "creator_id": 10, "creator_type": "Group",
            "creator_verified": None, "asset_type_id": 61,
            "created_at": NOW,
        }])
        sql, params = cur.executed[-1]
        self.assertIn("creator_type", sql)
        self.assertIn("COALESCE(EXCLUDED.creator_type", sql)
        self.assertIn("COALESCE(EXCLUDED.creator_verified", sql)
        self.assertEqual(params[7], "Group")
        self.assertIsNone(params[8])

    def test_discover_nonverified_reuses_stored_data(self):
        rows = [("User", 10, "A", "nonverified", "catalog_flag",
                 "tracked_creator", 3, {"61": 3}, 1, NOW)]
        out = cr.discover_nonverified(StubCursor([rows]), limit=10)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source"], "stored_catalog")
        self.assertEqual(out[0]["live_api_calls"], 0)
        self.assertEqual(out[0]["item_count"], 3)

    def test_registry_module_makes_no_live_api_calls(self):
        source = Path(__file__).with_name(
            "creator_registry.py").read_text(encoding="utf-8")
        self.assertNotIn("import requests", source)
        self.assertNotIn("aiohttp", source)
        self.assertNotIn("roblox.com", source)


class SnapshotCoverageTests(unittest.TestCase):
    def test_coverage_counts_and_missing_evidence(self):
        report = cr.snapshot_coverage(
            StubCursor([(10, 3, 2, 5, 4, 20)]), window_hours=48)
        self.assertEqual(report["recent_items"], 10)
        self.assertEqual(report["no_snapshots"], 3)
        self.assertEqual(report["one_snapshot"], 2)
        self.assertEqual(report["two_plus_snapshots"], 5)
        self.assertEqual(report["valid_growth_items"], 4)
        self.assertEqual(report["valid_growth_pct"], 40.0)
        self.assertFalse(report["missing_evidence"])

        empty = cr.snapshot_coverage(
            StubCursor([(0, 0, 0, 0, 0, 0)]))
        self.assertTrue(empty["missing_evidence"])
        self.assertIsNone(empty["valid_growth_pct"])


class ComparisonTests(unittest.TestCase):
    def _rows(self):
        rows = []
        # Established verified high performer.
        for i in range(1, 7):
            rows.append(comp_row(i, "User", 100, "A", True, favs=500,
                                 age_days=20, price=100, snapshots=2))
        # Emerging nonverified low performer, with one missing favorite.
        for i in range(7, 9):
            rows.append(comp_row(i, "User", 200, "B", False, favs=5,
                                 age_days=5, price=20, snapshots=0))
        rows.append(comp_row(17, "User", 200, "B", False, favs=None,
                             age_days=6, price=20, snapshots=0))
        # Unknown verification middle performer.
        for i in range(9, 12):
            rows.append(comp_row(i, "Group", 300, "C", None, favs=50,
                                 age_days=40, price=50, snapshots=1))
        # Established nonverified middle performer.
        for i in range(12, 17):
            rows.append(comp_row(i, "User", 400, "D", False, favs=100,
                                 age_days=60, price=70, snapshots=2))
        # Duplicate of item 1, newer observation.
        rows.append(comp_row(1, "User", 100, "A", True, favs=520,
                             age_days=20, price=100, snapshots=2,
                             fetched_days=0))
        return rows

    def test_segments_include_nonverified_and_underperformers(self):
        summary = cr.summarize_comparison(
            self._rows(), family="emotes", now=NOW)
        seg = summary["segments"]
        self.assertEqual(summary["creators"], 4)
        self.assertEqual(summary["items"], 17)
        self.assertEqual(seg["established"]["creators"], 2)
        self.assertEqual(seg["emerging"]["creators"], 2)
        self.assertEqual(seg["verified"]["creators"], 1)
        self.assertEqual(seg["nonverified"]["creators"], 2)
        self.assertEqual(seg["unknown_verification"]["creators"], 1)
        self.assertEqual(seg["top_performers"]["creators"], 1)
        self.assertGreaterEqual(seg["underperformers"]["creators"], 1)
        self.assertGreater(seg["established"]["median_age_days"],
                           seg["emerging"]["median_age_days"])
        self.assertEqual(summary["missing"]["items_without_favorites"], 1)
        self.assertEqual(summary["concentration"]["top_creator"], "A")
        self.assertFalse(summary["selection"]["representative"])
        self.assertTrue(summary["selection"]["favorites_not_sales"])

    def test_empty_comparison_is_honest(self):
        summary = cr.summarize_comparison([], family="emotes", now=NOW)
        self.assertEqual(summary["creators"], 0)
        self.assertEqual(summary["items"], 0)
        self.assertEqual(summary["segments"]["established"]["creators"], 0)
        self.assertFalse(summary["selection"]["representative"])
        self.assertTrue(summary["selection"]["growth_only_from_snapshots"])

    def test_creator_evidence_contract(self):
        counts = (20, 5, 10, 5, 2, 100, 40)
        comparison_rows = self._rows()
        coverage = (10, 3, 2, 5, 4, 20)
        cur = StubCursor([counts, (1,), comparison_rows, coverage])
        evidence = cr.creator_evidence(
            cur, family="emotes", days=180, limit=100)
        self.assertEqual(evidence["registry"]["creators"], 20)
        self.assertEqual(evidence["registry"]["verified"], 5)
        self.assertEqual(evidence["registry"]["nonverified"], 10)
        self.assertEqual(evidence["comparison"]["creators"], 4)
        self.assertEqual(evidence["comparison"]["sample"]["order"], "item_id")
        self.assertFalse(evidence["comparison"]["sample"]["representative"])
        self.assertEqual(evidence["snapshot_coverage"]["valid_growth_pct"],
                         40.0)
        self.assertTrue(evidence["contract"]["favorites_not_sales"])
        self.assertFalse(evidence["contract"]["representative"])
        self.assertTrue(evidence["contract"]["growth_requires_snapshots"])
        self.assertEqual(evidence["sample_sizes"]["comparison_creators"], 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
