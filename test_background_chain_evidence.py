"""Regression checks for real November background !chain output defects.

All tests are offline and do not claim fresh Roblox API availability.
"""
from unittest import mock
import astra_report
import commands_ai
import winner_analysis
import product_understanding
import convergence_live


def test_background_report_scene_preview_and_failed_live_evidence():
    result = {
        "family": "backgrounds",
        "concept": "moonlit shrine with glowing portal",
        "stats": {"count": 10, "avg_favs": 100, "median_favs": 20,
                  "winner_favs": 250, "price_avg": 200},
        "merged_description": "Moonlit shrine scene for avatars.",
        "scored_titles": [
            {"title": "Moonlit Shrine Background", "exact_matches": 0,
             "opportunity": {"verdict": "CONTESTED", "demand_volume": 8093,
                             "supply": 4, "exact": 0},
             "breakdown": [{"word": "shrine"}]},
        ],
    }
    understanding = product_understanding.merge(
        result["concept"], api_family="backgrounds")
    assert understanding["family"] == "backgrounds"
    assert "product family not stated" not in understanding["unknowns"]
    text = "\n".join(astra_report.build_analyst_report(
        result, live={"ok": False, "error": "HTTP 0"}, understanding=understanding))
    for expected in (
        "2560×1440", "centered Roblox avatar", "Live search failed",
        "live overlap unverified", "database supply proxy",
        "not verified sales or CTR", "AssetType 92-filtered",
    ):
        assert expected in text, expected
    for invalid in (
        "Static accessory: show front, 3/4, and back",
        "exact None", "None page(s)", "Uncertainty: 0 exact matches",
        "Motion: none (static accessory)", "avg price R$",
        "Live check: unavailable · None",
    ):
        assert invalid not in text, invalid
    assert all(len(c) <= 1900 for c in astra_report.build_analyst_report(
        result, live={"ok": False}, understanding=understanding))


def test_other_category_preview_unchanged():
    result = {"family": "headwear", "concept": "blue hat", "scored_titles": [],
              "stats": {}, "merged_description": ""}
    text = "\n".join(astra_report.build_analyst_report(result))
    assert "Static accessory: show front, 3/4, and back" in text


def test_background_keyword_expansion_stays_scoped():
    background = (1, "Moonlit Shrine Background", 100, 200, 0, "")
    alien = (2, "Moonlit Shrine Hat", 99999, 50, 0, "")
    queries = []

    def category_search(patterns, asset_ids):
        queries.append(("scoped", tuple(asset_ids)))
        assert list(asset_ids) == [92]
        return [background]

    def global_search(patterns):
        queries.append(("global", None))
        return [alien]

    intent = {"primary": ["moonlit", "shrine"], "specific_moves": []}
    with mock.patch.object(commands_ai, "all_terms", return_value=["moonlit", "shrine"]), \
         mock.patch.object(commands_ai, "_db_search_by_category",
                           side_effect=category_search), \
         mock.patch.object(commands_ai, "_db_search", side_effect=global_search), \
         mock.patch.object(commands_ai, "_term_match_count", return_value=0), \
         mock.patch.object(commands_ai, "_get_db_vocab_sample", return_value=["moonlit", "shrine"]), \
         mock.patch.object(commands_ai, "expand_search_terms",
                           return_value={"expanded_terms": ["shrine"], "reasoning": "theme"}):
        _, top, stats = commands_ai._build_allow_list(
            intent, 60, None, family="backgrounds")
    assert stats["count"] == 1, stats
    assert stats["family"] == "backgrounds"
    assert stats["avg_favs"] == 100
    assert all(it["name"] == background[1] for it in top)
    assert len(queries) == 2 and all(q[0] == "scoped" for q in queries), queries


class FakeWinnerCursor:
    def __init__(self):
        self.sql = None
        self.params = None
    def execute(self, sql, params):
        self.sql, self.params = sql, params
    def fetchall(self):
        return []


def test_background_winner_comparison_filters_type():
    cur = FakeWinnerCursor()
    winner_analysis.analyze_winners(
        cur, ["shrine"], asset_type_ids=[92])
    assert "asset_type_id = ANY(%s)" in cur.sql
    assert cur.params[-1] == [92]
    cur = FakeWinnerCursor()
    winner_analysis.analyze_winners(cur, ["shrine"])
    assert "asset_type_id = ANY(%s)" not in cur.sql


def test_empty_background_convergence_explains_mismatch():
    report = convergence_live.format_report(
        {"shortlist": [], "candidates": [], "gated": []},
        {}, family="backgrounds")
    assert "!early 7 backgrounds" in report
    assert "Individual early winners" in report
    assert "No qualifying opportunities" in report


if __name__ == "__main__":
    test_background_report_scene_preview_and_failed_live_evidence()
    test_other_category_preview_unchanged()
    test_background_keyword_expansion_stays_scoped()
    test_background_winner_comparison_filters_type()
    test_empty_background_convergence_explains_mismatch()
    print("PASS background chain evidence and report regression tests")
