"""Background category quality regressions: no network or database writes.

Test AssetType 92 isolation, scene-focused keyword mining, strict live
verification, unrelated categories, and honest failed/limited evidence.
"""
import unittest
from unittest import mock
from types import SimpleNamespace

import background_niche
import convergence_engine as ce
import convergence_live as cl


class FakeMineCursor:
    def __init__(self, names):
        self.names = names
        self.calls = []
    def execute(self, sql, params=None):
        self.calls.append((sql, params))
    def fetchall(self):
        return [(n,) for n in self.names]


class TestBackgroundSceneCandidates(unittest.TestCase):
    def test_concepts_without_scene_context_are_not_recommendations(self):
        for word in ("white", "plaid", "white background",
                     "plaid background", "background", "generic background",
                     "avatar background", "dark", "cute"):
            self.assertFalse(background_niche.scene_phrase(word), word)
        for phrase in ("moonlit shrine", "neon city", "cozy library",
                       "floating portal", "starry sky", "snowy forest",
                       "rain city", "white city", "ancient temple"):
            self.assertTrue(background_niche.scene_phrase(phrase), phrase)

    def test_background_mining_is_scene_only(self):
        names = (["White Background"] * 6
                 + ["Plaid Background"] * 6
                 + ["Moonlit Shrine Avatar Background"] * 6
                 + ["Neon City Background"] * 5
                 + ["Cozy Library Background"] * 5
                 + ["Starry Sky Background"] * 4
                 + ["Blue Aura Emote"] * 10)
        cur = FakeMineCursor(names)
        keywords = ce._gather_keywords(cur, family="backgrounds")
        self.assertIn("moonlit shrine", keywords)
        self.assertIn("neon city", keywords)
        self.assertIn("cozy library", keywords)
        self.assertIn("starry sky", keywords)
        self.assertNotIn("white", keywords)
        self.assertNotIn("plaid", keywords)
        self.assertNotIn("white background", keywords)
        self.assertTrue(all(background_niche.scene_phrase(k) for k in keywords))
        self.assertIn("asset_type_id", cur.calls[0][0])
        self.assertEqual(cur.calls[0][1], [92])

    def test_other_families_keep_previous_mining_behavior(self):
        cur = FakeMineCursor(["Plaid Headwear"] * 4)
        # No background-specific restrictions should apply to hats.
        keywords = ce._gather_keywords(cur, family="headwear")
        self.assertIn("plaid", keywords)
        self.assertEqual(cur.calls[0][1], [8])

    def test_direct_score_rejects_empty_background_concepts_before_sql(self):
        cur = FakeMineCursor([])
        self.assertIsNone(ce._score_keyword(cur, "plaid", family="backgrounds"))
        self.assertIsNone(ce._score_keyword(cur, "white", family="backgrounds"))
        self.assertIsNone(ce._score_keyword(cur, "white background",
                                            family="backgrounds"))
        self.assertEqual(cur.calls, [])


class FakeScheduler:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.calls = []
    def request(self, endpoint, url, params=None, timeout=None):
        self.calls.append((endpoint, url, dict(params or {})))
        return SimpleNamespace(
            ok=self.status == 200,
            status=self.status,
            data=self.payload if self.status == 200 else None,
            error="rate limited" if self.status == 429 else None,
            deferred=self.status == 429,
            retry_after=15 if self.status == 429 else None,
            headers={},
        )


class TestBackgroundLiveMarketplace(unittest.TestCase):
    def setUp(self):
        cl.clear_cache()

    def test_backgrounds_are_searched_with_context_and_strict_type(self):
        payload = {"data": [
            {"name": "Moonlit Shrine Background", "assetType": 92,
             "favoriteCount": 150, "price": 60, "creatorName": "scenemaker"},
            {"name": "Moonlit Shrine Hat", "assetType": 8,
             "favoriteCount": 1000, "price": 90, "creatorName": "hatmaker"},
            {"name": "Moonlit Shrine Wings", "assetType": 47,
             "favoriteCount": 5000, "price": 80, "creatorName": "wingmaker"},
            {"name": "Moonlit Shrine Without Type", "favoriteCount": 2000},
            {"name": "Moonlit Shrine Sky", "assetTypeId": "92",
             "favoriteCount": 50, "price": 20},
        ], "nextPageCursor": None}
        scheduler = FakeScheduler(payload)
        with mock.patch.object(cl, "_get_scheduler", return_value=scheduler), \
                mock.patch.object(cl, "_circuit_open", return_value=False):
            result = cl.verify_niche("moonlit shrine", family="backgrounds",
                                     use_cache=False)
        self.assertTrue(result["ok"])
        self.assertEqual(scheduler.calls[0][2]["Keyword"],
                         "moonlit shrine background")
        self.assertEqual(result["sampled_results"], 5)
        self.assertEqual(result["category_correct"], 2)
        self.assertEqual(result["category_mismatched"], 3)
        self.assertEqual(result["search_keyword"], "moonlit shrine background")
        self.assertEqual({c["asset_type_id"] for c in result["top_competitors"]},
                         {92})
        self.assertEqual(len(result["top_competitors"]), 2)

    def test_other_categories_do_not_change_search_query(self):
        scheduler = FakeScheduler({"data": [
            {"name": "Moonlit Shrine Hat", "assetType": 8,
             "favoriteCount": 2, "price": 10},
        ], "nextPageCursor": None})
        with mock.patch.object(cl, "_get_scheduler", return_value=scheduler), \
                mock.patch.object(cl, "_circuit_open", return_value=False):
            result = cl.verify_niche("moonlit shrine", family="headwear",
                                     use_cache=False)
        self.assertEqual(scheduler.calls[0][2]["Keyword"], "moonlit shrine")
        self.assertEqual(result["category_correct"], 1)

    def test_wrong_category_results_are_not_recommendations(self):
        scheduler = FakeScheduler({"data": [
            {"name": "Neon City Hat", "assetType": 8},
        ], "nextPageCursor": None})
        with mock.patch.object(cl, "_get_scheduler", return_value=scheduler), \
                mock.patch.object(cl, "_circuit_open", return_value=False):
            result = cl.verify_niche("neon city", family="backgrounds",
                                     use_cache=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["category_correct"], 0)
        candidate = {"keyword": "neon city", "score": 90, "velocity_measured": True,
                     "recent": 6, "freshness": "recent", "median_favs": 40,
                     "supply": 5, "concentration": 0.2, "velocity": 2}
        report = cl.format_recommendation(candidate, result)
        self.assertIn("insufficient evidence", report)
        self.assertIn("does not prove", report)
        self.assertIn("Marketplace search", report)

    def test_rate_limited_live_market_is_not_presented_as_confirmed(self):
        scheduler = FakeScheduler({}, status=429)
        with mock.patch.object(cl, "_get_scheduler", return_value=scheduler), \
                mock.patch.object(cl, "_circuit_open", return_value=False):
            result = cl.verify_niche("neon city", family="backgrounds",
                                     use_cache=False)
        self.assertFalse(result["ok"])
        self.assertFalse(result.get("top_competitors"))
        self.assertEqual(result.get("retry_after"), 15)

    def test_report_has_clear_category_label(self):
        report = cl.format_report({"shortlist": [], "gated": []}, {},
                                  family="backgrounds")
        self.assertIn("CONVERGENCE — Avatar Backgrounds", report)
        self.assertIn("No qualifying opportunities", report)


if __name__ == "__main__":
    unittest.main()
