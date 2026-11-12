"""Background Convergence: scarce-data recovery without invented demand.

These tests cover the user-reported empty niche scan despite measurable
background favorite growth. No Roblox API, Discord or production DB calls.
"""
import unittest
from unittest import mock
import convergence_engine as ce
import convergence_live as cl
import avatar_backgrounds as ab


class FakeCursor:
    def close(self):
        pass

class FakeConn:
    def cursor(self):
        return FakeCursor()
    def close(self):
        pass


def candidate(keyword, measured=False, recent=0, score=50):
    return {
        "keyword": keyword, "score": score, "family": "backgrounds",
        "velocity_measured": measured, "velocity": 1.0 if measured else None,
        "recent": recent, "median_favs": 35.0, "supply": 6,
        "concentration": 0.2, "freshness": "recent",
    }


def early_rows():
    return {
        "status": "ok",
        "candidate_window": 150,
        "usable_history": 71,
        "coverage_pct": 47.3,
        "ranked": [
            {
                "id": 1234, "name": "Lion Dog Meme Background",
                "asset_type_id": 92, "measured_favorites_gained": 262,
                "measured_favs_per_day": 174.71, "observations": 3,
                "confidence": "medium",
            },
            {
                "id": 5678, "name": "Cyberpunk Street Alleyway",
                "asset_type_id": 92, "measured_favorites_gained": 4,
                "measured_favs_per_day": 2.67, "observations": 3,
                "confidence": "medium",
            }
        ],
    }


class BackgroundConvergenceRecoveryTests(unittest.TestCase):
    def _run(self, keywords, side_effect, family="backgrounds", early=None):
        with mock.patch.object(ce, "get_research_db", return_value=FakeConn()), \
             mock.patch.object(ce, "_gather_keywords", return_value=keywords), \
             mock.patch.object(ce, "_score_keyword", side_effect=side_effect), \
             mock.patch.object(ab, "find_background_early_winners",
                               return_value=early or early_rows()) as fallback:
            result = ce.scan_convergence_detailed(family, limit=8, shortlist=8)
        return result, fallback

    def test_empty_mined_phrases_still_shows_measured_early_activity(self):
        result, fallback = self._run([], lambda *args, **kw: None)
        self.assertEqual(result["scanned"], 0)
        self.assertEqual(result["scored"], 0)
        fallback.assert_called_once()
        self.assertEqual(result["background_early_activity"]["ranked"][0]
                         ["measured_favorites_gained"], 262)
        report = cl.format_report(result, {}, family="backgrounds")
        self.assertIn("No qualifying opportunities", report)
        self.assertIn("Measured early activity", report)
        self.assertIn("Lion Dog Meme Background", report)
        self.assertIn("174.71/day", report)
        self.assertIn("47.3%", report)
        self.assertIn("NOT verified niches", report)
        self.assertIn("No suitable repeated scene phrases", report)
        self.assertNotIn("## Shortlist", report)

    def test_scored_but_gated_continues_all_three_tiers(self):
        calls = []
        def scorer(cur, kw, family, **kwargs):
            calls.append(kwargs["min_median"])
            return candidate(kw, measured=False, recent=0)
        result, fallback = self._run(["moonlit shrine"], scorer)
        self.assertEqual(calls, [25, 20, 15])
        self.assertEqual(result["scanned"], 1)
        self.assertEqual(result["scored"], 1)
        self.assertEqual(result["qualified_count"], 0)
        self.assertEqual(result["gated"][0]["reason"],
                         "velocity unmeasured and no fresh supply")
        fallback.assert_called_once()
        self.assertIn("1 candidate phrases mined", cl.format_report(result, {},
                                                                   family="backgrounds"))

    def test_genuine_qualifying_niche_keeps_original_live_verification(self):
        result, fallback = self._run(
            ["moonlit shrine"],
            lambda cur, kw, fam, **kwarg: candidate(kw, recent=2))
        self.assertEqual(len(result["shortlist"]), 1)
        self.assertEqual(result["qualified_count"], 1)
        self.assertIsNone(result["background_early_activity"])
        fallback.assert_not_called()
        report = cl.format_report(result, {}, family="backgrounds")
        self.assertIn("Shortlist (1 candidates)", report)
        self.assertNotIn("Measured early activity", report)

    def test_other_families_do_not_run_background_fallback(self):
        result, fallback = self._run([], lambda *args, **kwargs: None,
                                     family="emotes")
        fallback.assert_not_called()
        self.assertIsNone(result["background_early_activity"])

    def test_no_measured_early_items_not_fabricated(self):
        result, fallback = self._run(
            [], lambda *args, **kwargs: None, early={
                "status": "insufficient_history", "ranked": [],
                "candidate_window": 150, "usable_history": 0,
                "coverage_pct": 0.0})
        report = cl.format_report(result, {}, family="backgrounds")
        self.assertNotIn("## Measured early activity", report)
        self.assertIn("No qualifying opportunities", report)

    def test_failed_background_snapshot_is_not_claimed(self):
        with mock.patch.object(ce, "get_research_db", return_value=FakeConn()), \
             mock.patch.object(ce, "_gather_keywords", return_value=[]), \
             mock.patch.object(ab, "find_background_early_winners",
                               side_effect=RuntimeError("DB disconnected")):
            result = ce.scan_convergence_detailed("backgrounds", 8, 8)
        report = cl.format_report(result, {}, family="backgrounds")
        self.assertIn("Early-item history is unavailable", report)
        self.assertNotIn("## Measured early activity", report)


if __name__ == "__main__":
    unittest.main()
