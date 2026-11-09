"""Phase 1 Creator Intelligence tests (offline, synthetic fixtures).

Covers the confirmed statistical-integrity defects and the learning/creator
readiness guards. No database writes, no network, no production data.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import creator_brain
import learning
import pattern_forge
import convergence_live

NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)


class StubCursor:
    def __init__(self, results=None):
        self._results = list(results or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        if not self._results:
            return []
        r = self._results.pop(0)
        return r if isinstance(r, list) else [r]

    def fetchone(self):
        if not self._results:
            return None
        r = self._results.pop(0)
        return r[0] if isinstance(r, list) and r else r


def row(item_id, name, favs, price=50, asset_type=61, age_days=10,
        creator="c1"):
    created = NOW - timedelta(days=age_days)
    return (item_id, name, favs, price, asset_type, created, creator)


class PatternForgeTests(unittest.TestCase):
    def test_comparison_uses_item_membership_not_favorite_values(self):
        rows = [
            row(1, "Glow Hat", 100, creator="c1"),
            row(6, "Glow Boots", 50, creator="c2"),
            row(2, "Shiny Hat", 100, creator="c3"),
            row(3, "Plain Hat", 50, creator="c4"),
            row(4, "Plain Cap", 10, creator="c5"),
            row(5, "Other", 10, creator="c6"),
        ]
        cur = StubCursor([rows])
        results = pattern_forge.mine_patterns(
            cur, min_sample=2, min_favs=0, now=NOW)
        glow = next(r for r in results
                    if r["kind"] == "word" and r["feature"] == "glow")
        # All four non-featured items are the comparison group, even though
        # two share favorite values with featured items.
        self.assertEqual(glow["without_count"], 4)
        self.assertEqual(glow["with_median"], 75.0)
        self.assertEqual(glow["without_median"], 30.0)
        self.assertEqual(glow["lift"], 2.5)
        self.assertEqual(glow["comparison_scope"],
                         "same_category_price_age")
        self.assertFalse(glow["causal"])
        self.assertEqual(glow["metric"], "favorites")

    def test_missing_favorites_are_skipped(self):
        rows = [
            row(1, "Glow Hat", 100),
            row(2, "Glow Boots", 50),
            row(3, "Plain Hat", 10),
            row(4, "Plain Cap", 10),
            row(5, "Glow Null", None),
        ]
        cur = StubCursor([rows])
        results = pattern_forge.mine_patterns(
            cur, min_sample=2, min_favs=0, now=NOW)
        glow = next(r for r in results
                    if r["kind"] == "word" and r["feature"] == "glow")
        self.assertEqual(glow["with_count"], 2)

    def test_age_confounder_restricts_comparison(self):
        rows = [
            row(1, "Glow Hat", 100, age_days=10, creator="c1"),
            row(2, "Glow Boots", 50, age_days=10, creator="c2"),
            row(3, "Plain Hat", 10, age_days=10, creator="c3"),
            row(4, "Plain Cap", 10, age_days=10, creator="c4"),
            row(5, "Vintage Crown", 1000, age_days=400, creator="c5"),
        ]
        cur = StubCursor([rows])
        results = pattern_forge.mine_patterns(
            cur, min_sample=2, min_favs=0, now=NOW)
        glow = next(r for r in results
                    if r["kind"] == "word" and r["feature"] == "glow")
        self.assertEqual(glow["comparison_scope"],
                         "same_category_price_age")
        self.assertEqual(glow["without_count"], 2)
        self.assertEqual(glow["without_median"], 10.0)

    def test_insufficient_sample_excluded(self):
        rows = [
            row(1, "Glow Hat", 100),
            row(2, "Plain Hat", 10),
            row(3, "Plain Cap", 10),
            row(4, "Other", 10),
        ]
        cur = StubCursor([rows])
        results = pattern_forge.mine_patterns(
            cur, min_sample=2, min_favs=0, now=NOW)
        self.assertFalse(any(r["kind"] == "word" and r["feature"] == "glow"
                             for r in results))

    def test_creator_concentration_reported(self):
        rows = [
            row(1, "Glow Hat", 100, creator="same"),
            row(2, "Glow Boots", 50, creator="same"),
            row(3, "Plain Hat", 10, creator="c3"),
            row(4, "Plain Cap", 10, creator="c4"),
        ]
        cur = StubCursor([rows])
        results = pattern_forge.mine_patterns(
            cur, min_sample=2, min_favs=0, now=NOW)
        glow = next(r for r in results
                    if r["kind"] == "word" and r["feature"] == "glow")
        self.assertEqual(glow["creator_concentration"], 1.0)
        self.assertTrue(glow["single_creator_dominated"])

    def test_duplicate_token_membership_counts_once(self):
        rows = [
            row(1, "Glow Glow Hat", 100),
            row(2, "Glow Boots", 50),
            row(3, "Plain Hat", 10),
            row(4, "Plain Cap", 10),
        ]
        cur = StubCursor([rows])
        results = pattern_forge.mine_patterns(
            cur, min_sample=2, min_favs=0, now=NOW)
        glow = next(r for r in results
                    if r["kind"] == "word" and r["feature"] == "glow")
        self.assertEqual(glow["with_count"], 2)

    def test_empty_cohort(self):
        cur = StubCursor([[]])
        self.assertEqual(
            pattern_forge.mine_patterns(cur, now=NOW), [])

    def test_zero_favorites_included_in_failure_patterns(self):
        rows = [
            row(1, "Cursed Hat", 0),
            row(2, "Cursed Cap", 0),
            row(3, "Cursed Boots", 1),
            row(4, "Winner Hat", 300),
            row(5, "Winner Cap", 400),
        ]
        cur = StubCursor([rows])
        results = pattern_forge.mine_failure_patterns(
            cur, min_sample=2)
        self.assertTrue(any(r["word"] == "cursed" for r in results))
        self.assertIn("favorite_count >= %s", cur.executed[0][0])
        self.assertFalse(any(r.get("causal") for r in results))

    def test_true_median(self):
        self.assertEqual(pattern_forge._median([1, 2, 3, 4]), 2.5)
        self.assertEqual(pattern_forge._median([1, 2, 3]), 2)


class FabricatedMetricsTests(unittest.TestCase):
    def test_format_favorite_keeps_missing_unknown(self):
        from commands_supercomputer import format_favorite
        self.assertEqual(format_favorite(None), "unknown")
        self.assertEqual(format_favorite(0), "0")
        self.assertEqual(format_favorite(1234), "1,234")

    def test_no_synthetic_favorite_formula(self):
        source = Path(__file__).with_name(
            "commands_supercomputer.py").read_text(encoding="utf-8")
        self.assertNotIn("% 7500", source)
        self.assertNotIn("actual_favs", source)


class LearningReadinessTests(unittest.TestCase):
    def test_eligible_population_thresholds_and_flag(self):
        # total, eligible, mature, eligible_sales, verified_sales,
        # unverified_sales, eligible_controls, leakage, explicitly_unverified
        ready = learning.learning_readiness(
            StubCursor([(100, 30, 20, 15, 15, 0, 10, 0, 0)]))
        self.assertTrue(ready["ready"])
        self.assertFalse(ready["recommended_flag"])
        self.assertTrue(all(ready["checks"].values()))

        leaking = learning.learning_readiness(
            StubCursor([(100, 30, 20, 15, 15, 0, 10, 2, 0)]))
        self.assertFalse(leaking["ready"])
        self.assertFalse(leaking["checks"]["no_temporal_leakage"])

    def test_disjoint_thresholds_cannot_produce_ready(self):
        # Old aggregate counts would individually look sufficient, but they
        # are not one eligible population.
        result = learning.learning_readiness(
            StubCursor([(100, 5, 3, 2, 2, 0, 1, 0, 0)]))
        self.assertFalse(result["ready"])
        self.assertFalse(result["checks"]["eligible_outcomes"])
        self.assertFalse(result["checks"]["mature_outcomes"])
        self.assertFalse(result["checks"]["verified_sales_evidence"])
        self.assertFalse(result["checks"]["eligible_controls"])

    def test_missing_sales_verification_does_not_count(self):
        result = learning.learning_readiness(
            StubCursor([(100, 30, 20, 15, 0, 15, 10, 0, 0)]))
        self.assertFalse(result["ready"])
        self.assertFalse(result["checks"]["verified_sales_evidence"])
        self.assertFalse(result["checks"]["no_unverified_sales"])

    def test_thin_population_not_ready(self):
        result = learning.learning_readiness(
            StubCursor([(10, 5, 2, 1, 1, 0, 0, 0, 0)]))
        self.assertFalse(result["ready"])

    def test_load_requires_verified_sales_and_attribution(self):
        rows = [
            (1, 10, "rename", "applied", "mature",
             '{"post_units": 5, "verified": true}', '{}', 10, None, None),
            (2, 11, "rename", "applied", "mature",
             '{"post_units": 5}', '{}', 10, None, None),
            (3, None, "rename", "applied", "mature",
             '{"post_units": 5, "verified": true}', '{}', 10, None, None),
            (4, 12, "rename", "applied", "mature",
             '{"post_units": 5, "verified": true}',
             '{"insufficient": true}', 10, None, None),
            (5, 13, "rename", "applied", "mature",
             '{"post_units": 5, "verified": false}', '{}', 10, None, None),
        ]
        cur = StubCursor([rows])
        out = learning.load_measured_outcomes(cur, limit=10)
        self.assertEqual([r["rec_id"] for r in out], [1])
        self.assertIn("measured_at >= applied_at", cur.executed[0][0])


class CreatorComparisonTests(unittest.TestCase):
    def test_representative_segments_include_nonverified(self):
        rows = [
            ("User", 100, "alice", 10, 500, True),
            ("User", 200, "bob", 3, 40, False),
            ("User", 300, "carol", 8, 100, False),
            ("Group", 400, "dave", 2, 5, False),
            ("User", 500, "erin", 6, 250, True),
            ("Group", 600, "frank", 4, 20, False),
        ]
        result = creator_brain.build_comparison_cohorts(
            StubCursor([rows]), has_type=True)
        segments = result["segments"]
        self.assertEqual(result["creators"], 6)
        self.assertEqual(segments["established"]["creators"], 3)
        self.assertEqual(segments["emerging"]["creators"], 3)
        self.assertEqual(segments["verified"]["creators"], 2)
        self.assertEqual(segments["nonverified"]["creators"], 4)
        self.assertEqual(segments["top_performers"]["creators"], 2)
        self.assertEqual(segments["average_performers"]["creators"], 2)
        self.assertEqual(segments["underperformers"]["creators"], 2)
        self.assertEqual(result["selection"]["identity_key"],
                         "(creator_type, creator_id)")

    def test_true_median(self):
        self.assertEqual(creator_brain._median([1, 2, 3, 4]), 2.5)

    def _sample_findings(self):
        cohort = [("User", 100, "alice", 10, 500, 900),
                  ("User", 200, "bob", 3, 40, 50)]
        items = [
            ("glow hat", 100, 50, 10.0),
            ("glow boots", 80, 40, 20.0),
            ("plain hat", 5, 0, 30.0),
        ]
        comparison_rows = [
            ("User", 100, "alice", 10, 500, True),
            ("User", 200, "bob", 3, 40, False),
            ("User", 300, "carol", 8, 100, False),
            ("Group", 400, "dave", 2, 5, False),
            ("User", 500, "erin", 6, 250, True),
            ("Group", 600, "frank", 4, 20, False),
        ]
        coverage = [(1, 6, 1, 8)]
        return creator_brain.learn(
            StubCursor([cohort, items, comparison_rows, coverage]),
            min_items=2, top_n=10, has_type=True)

    def test_learn_labels_success_and_comparison(self):
        findings = self._sample_findings()
        self.assertEqual(findings["cohort_label"],
                         "success_top_median_favorites")
        self.assertFalse(findings["cohort_is_representative"])
        self.assertIn("not representative", findings["cohort_selection"])
        self.assertIsNotNone(findings["comparison"])
        seg = findings["comparison"]["segments"]
        self.assertEqual(seg["nonverified"]["creators"], 4)
        self.assertGreater(seg["underperformers"]["creators"], 0)
        self.assertFalse(findings["comparison_selection"]["representative"])
        self.assertEqual(
            findings["comparison"]["selection"]["population"],
            "typed creators with >= 3 items and non-null favorites")
        self.assertEqual(
            findings["comparison"]["selection"]["identity_key"],
            "(creator_type, creator_id)")
        self.assertIsNotNone(findings["identity_coverage"])
        self.assertEqual(findings["identity_coverage"]["typed_items"], 6)

    def test_save_load_preserves_comparison(self):
        import json
        findings = self._sample_findings()
        saver = StubCursor([])
        creator_brain.save(saver, findings)
        store = {}
        for sql, params in saver.executed:
            if "insert into creator_patterns" in sql.lower():
                store[params[0]] = params[1]
        self.assertIn("comparison", store)
        self.assertEqual(
            json.loads(store["comparison"])["segments"]
            ["nonverified"]["creators"], 4)

        stored_rows = [(k, v, None) for k, v in store.items()]
        loaded = creator_brain.load_findings(StubCursor([stored_rows]))
        self.assertIsNotNone(loaded["comparison"])
        self.assertEqual(
            loaded["comparison"]["segments"]["nonverified"]["creators"], 4)
        self.assertFalse(loaded["cohort_is_representative"])
        report = creator_brain.format_report(loaded)
        self.assertIn("Comparison segments", report)
        self.assertIn("not probability-representative", report.lower())

    def test_cached_report_without_comparison_warns(self):
        stored = [
            ("cohort_size", "2", None), ("items", "3", None),
            ("median_title_words", "2.0", None), ("emoji_rate", "0.0", None),
            ("median_price", "45.0", None), ("median_favs", "80.0", None),
            ("cadence_per_week", "0.5", None),
            ("top_words", "", None), ("top_bigrams", "", None),
            ("cohort_label", "success_top_median_favorites", None),
            ("cohort_is_representative", "false", None),
            ("cohort_selection", "all creators; not representative", None),
        ]
        loaded = creator_brain.load_findings(StubCursor([stored]))
        report = creator_brain.format_report(loaded)
        self.assertIn("Comparison summary unavailable", report)
        self.assertIn("do not read the success cohort as representative",
                      report.lower())


class ConvergenceFailureTests(unittest.TestCase):
    def test_api_failure_is_incomplete_not_fabricated(self):
        with mock.patch.object(
                convergence_live, "_get_scheduler",
                side_effect=RuntimeError("down")):
            result = convergence_live.verify_niche(
                "street dance", family="emotes", use_cache=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "RuntimeError")


if __name__ == "__main__":
    unittest.main(verbosity=2)
