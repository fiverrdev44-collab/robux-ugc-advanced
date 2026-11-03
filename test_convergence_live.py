"""Regression tests for the two-stage convergence pipeline (offline).

Stage A gate logic (generic rejection, evidence qualification, median/velocity
labeling) is tested as pure functions. Stage B live verification is tested with
mocked Roblox responses — no network, no database writes.
"""
import sys
import unittest
from unittest import mock

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))

import convergence_engine as ce
import convergence_live as cl


class _FakeResp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


def _candidate(**kw):
    base = {
        "keyword": "levitation pose", "family": "emotes", "score": 62.0,
        "demand": 4, "demand_live": 4, "demand_reliable": True,
        "demand_volume": 120, "velocity": 1.5, "velocity_measured": True,
        "observations": 3, "stale": False, "supply": 18, "recent": 2,
        "median_favs": 42.0, "avg_favs": 42.0, "p90_favs": 120.0,
        "concentration": 0.35,
    }
    base.update(kw)
    return base


class GenericRejectionTests(unittest.TestCase):
    def test_generic_single_word_rejected(self):
        for w in ("fairy", "waist", "emote", "float", "music", "matching",
                  "confess", "farming", "heart", "model"):
            self.assertTrue(ce._is_generic(w), w)

    def test_actionable_bigram_not_generic(self):
        self.assertFalse(ce._is_generic("fairy levitation"))
        self.assertFalse(ce._is_generic("floating battle stance"))
        self.assertFalse(ce._is_generic("levitation"))

    def test_generic_seed_kept_as_multiword_concept(self):
        # "float"/"fairy"/"heart" are gated standalone but survive as concepts.
        self.assertTrue(ce._is_generic("float"))
        self.assertFalse(ce._is_generic("floating pose"))
        self.assertTrue(ce._is_generic("fairy"))
        self.assertFalse(ce._is_generic("fairy levitation"))
        self.assertTrue(ce._is_generic("heart"))
        self.assertFalse(ce._is_generic("heart pose"))

    def test_qualifies_rejects_generic(self):
        ok, reason = ce.qualifies(_candidate(keyword="fairy"))
        self.assertFalse(ok)
        self.assertIn("generic", reason)

    def test_qualifies_rejects_unmeasured_and_stale(self):
        ok, reason = ce.qualifies(
            _candidate(velocity_measured=False, velocity=None, recent=0))
        self.assertFalse(ok)
        self.assertIn("velocity", reason)

    def test_qualifies_allows_measured(self):
        ok, _ = ce.qualifies(_candidate())
        self.assertTrue(ok)

    def test_qualifies_allows_fresh_supply_when_unmeasured(self):
        ok, reason = ce.qualifies(
            _candidate(velocity_measured=False, velocity=None, recent=3))
        self.assertTrue(ok)
        self.assertIn("fresh supply", reason)


class LabelingTests(unittest.TestCase):
    def test_velocity_unavailable(self):
        self.assertEqual(ce._fmt_velocity(_candidate(velocity_measured=False)),
                         "unavailable")
        self.assertEqual(ce._fmt_velocity(_candidate(velocity=1.5)), "1.5/d")

    def test_brief_labels_median_and_unverified_autocomplete(self):
        text = ce.format_brief(_candidate())
        self.assertIn("median", text)
        self.assertIn("unverified", text)
        self.assertIn("velocity 1.5/d", text)

    def test_brief_flags_unmeasured_velocity(self):
        text = ce.format_brief(
            _candidate(velocity_measured=False, velocity=None))
        self.assertIn("unavailable", text)


class ConvergeDebugTests(unittest.TestCase):
    class _Cursor:
        def __init__(self, rows):
            self._rows = list(rows)
        def execute(self, *a, **k):
            pass
        def fetchone(self):
            return self._rows.pop(0) if self._rows else None
        def close(self):
            pass

    def test_debug_accepts_kwarg_and_rejects_generic(self):
        # Generic keyword is rejected before any SQL; debug=True must not raise.
        cur = self._Cursor([])
        self.assertIsNone(
            ce._score_keyword(cur, "fairy", "emotes", debug=True))

    def test_debug_scores_a_viable_keyword(self):
        cur = self._Cursor([
            (18, 42, 120),            # supply, median, p90
            (4, 120, 4, 120),         # demand_all, volume_all, live, volume_live
            (2,),                     # recent
            (3, 1.5),                 # observations, avg velocity
            ("2026-11-01T00:00:00+00:00",),  # last obs
            (5000, 1000),             # total favs, top favs
        ])
        r = ce._score_keyword(cur, "levitation pose", "emotes", debug=True)
        self.assertIsNotNone(r)
        self.assertTrue(r.get("velocity_measured"))
        self.assertEqual(r.get("median_favs"), 42.0)


class LiveVerificationTests(unittest.TestCase):
    def setUp(self):
        cl.clear_cache()

    def _patch(self, responses):
        return mock.patch.object(cl, "_get_with_backoff", side_effect=responses)

    def _items(self, n=3, asset_type=61, name="levitation", favs=100, price=50):
        return [{"name": f"{name} {i}", "favoriteCount": favs + i,
                 "price": price, "assetType": asset_type,
                 "creatorName": f"creator{i}"} for i in range(n)]

    def test_emotes_category_verification(self):
        payload = {"data": self._items(), "nextPageCursor": None}
        with self._patch([_FakeResp(200, payload)]):
            r = cl.verify_niche("levitation", family="emotes")
        self.assertTrue(r["ok"])
        self.assertEqual(r["category_correct"], 3)
        self.assertEqual(r["category_mismatched"], 0)
        self.assertEqual(r["sampled_results"], 3)

    def test_unrelated_category_flagged(self):
        items = self._items(asset_type=8)  # hats, not emotes
        with self._patch([_FakeResp(200, {"data": items, "nextPageCursor": None})]):
            r = cl.verify_niche("levitation", family="emotes")
        self.assertEqual(r["category_correct"], 0)
        self.assertEqual(r["category_mismatched"], 3)

    def test_http_429(self):
        with self._patch([_FakeResp(429, {}, {"Retry-After": "1"})]):
            r = cl.verify_niche("levitation", family="emotes")
        self.assertFalse(r["ok"])
        self.assertIn("429", r["error"])

    def test_api_outage(self):
        def boom(*a, **k):
            raise RuntimeError("connection reset")
        with mock.patch.object(cl, "_get_with_backoff", side_effect=boom):
            r = cl.verify_niche("levitation", family="emotes")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "RuntimeError")

    def test_pagination_capped(self):
        page1 = {"data": self._items(), "nextPageCursor": "cursor1"}
        page2 = {"data": self._items(), "nextPageCursor": "cursor2"}
        with self._patch([_FakeResp(200, page1), _FakeResp(200, page2)]):
            r = cl.verify_niche("levitation", family="emotes", max_pages=2)
        self.assertTrue(r["capped"])
        self.assertEqual(r["pages"], 2)

    def test_cache_reuse(self):
        cl.clear_cache()
        payload = {"data": self._items(), "nextPageCursor": None}
        calls = {"n": 0}

        def fake(*a, **k):
            calls["n"] += 1
            return _FakeResp(200, payload)

        with mock.patch.object(cl, "_get_with_backoff", side_effect=fake):
            r1 = cl.verify_niche("levitation", family="emotes")
            r2 = cl.verify_niche("levitation", family="emotes")
        self.assertFalse(r1.get("cached"))
        self.assertTrue(r2.get("cached"))
        self.assertEqual(calls["n"], 1)
        cl.clear_cache()


class ReportTests(unittest.TestCase):
    def test_no_qualifying_opportunities(self):
        detailed = {"family": "emotes", "candidates": [], "shortlist": [],
                    "gated": [{"keyword": "fairy", "reason": "generic",
                               "score": 70.2}]}
        text = cl.format_report(detailed, {}, family="emotes")
        self.assertIn("No qualifying opportunities", text)
        self.assertIn("fairy", text)

    def test_recommendation_live_disagreement_lowers_confidence(self):
        c = _candidate()
        live = {"ok": True, "keyword": "levitation pose", "sampled_results": 30,
                "category_correct": 0, "category_mismatched": 30,
                "exact_title_matches": 0, "conceptual_matches": 2,
                "top_competitors": [], "verification_timestamp": "2026-11-03T00:00:00",
                "sample_note": "first 30", "capped": False}
        level, why = cl._confidence(c, live)
        self.assertEqual(level, "low")
        self.assertIn("correct-category", why)


if __name__ == "__main__":
    unittest.main(verbosity=2)
