"""Offline regression checks for background creator essentials.

No Roblox API, Discord, model, or database activity.
"""
import background_intelligence as bi

VISION = {
    "visual_summary": "Moonlit shrine with a glowing portal",
    "search_description": "Moonlit Shrine Background",
    "distinctive_features": ["glowing portal", "stone path"],
    "avatar_clearance_notes": "avatar center crowded",
    "mobile_readability_notes": "cropped outer lanterns",
}

LIVE = {
    "ok": True, "sampled_results": 8, "category_correct": 3,
    "top_competitors": [
        {"name": "Moonlit Shrine Background", "asset_type_id": 92,
         "favorites": 41, "price": 200},
        {"name": "Mystical Shrine Background", "asset_type_id": 92,
         "favorites": 18, "price": 150},
        {"name": "Moonlit Shrine Hat", "asset_type_id": 8,
         "favorites": 9999, "price": 1},
    ],
}


def test_only_explicit_category_92_competitors_are_used():
    comp = bi.verified_background_competitors(LIVE)
    assert len(comp) == 2, comp
    assert all("Hat" not in x["name"] for x in comp)
    assert bi.verified_background_competitors({"ok": False}) == []
    assert bi.verified_background_competitors({
        "ok": True, "top_competitors": [{"name": "Unknown type"}]
    }) == []


def test_exact_sample_title_is_excluded_without_claiming_global_uniqueness():
    titles = bi.candidate_titles(VISION, live=LIVE)
    assert "Moonlit Shrine Background" not in titles, titles
    assert titles, "A defensible alternative should remain"
    assert all("Hat" not in title for title in titles)
    assert "Moonlit Shrine Background" in bi.candidate_titles(VISION)


def test_similarity_is_descriptive_not_visual_or_sales_based():
    comp = bi.verified_background_competitors(LIVE)
    result = bi.title_sample_overlap("Moonlit Shrine Background", comp)
    assert result["exact"] is True
    assert result["ratio"] == 1.0
    no_data = bi.title_sample_overlap("Moonlit Shrine Background", [])
    assert no_data["name"] is None


def test_market_price_and_launch_plan_are_grounded():
    report = bi.format_background_dossier(VISION, live=LIVE)
    assert "Naming decision" in report
    assert "R$150–R$200" in report
    assert "not an optimal price" in report.lower()
    assert "9999 favorites" not in report
    assert "Moonlit Shrine Hat" not in report
    assert "Pre-publish checklist" in report
    assert "!ledger_sync" in report
    assert "A PNG cannot become an animated GIF" in report
    assert all(len(part) <= 1800 for part in bi.discord_chunks(report))


def test_failed_market_and_unsupported_claims_are_not_fabricated():
    report = bi.format_background_dossier(
        VISION, live={"ok": False, "error": "HTTP 429"})
    assert "No usable sampled price reference" not in report
    assert "Unavailable (HTTP 429)" in report
    assert "Exact-title and similarity checks unavailable" in report
    assert "guarantee additional sales" in report
    bad_market = {
        "ok": True, "category_correct": 0, "sampled_results": 1,
        "top_competitors": [{"name": "Not a backdrop",
                             "asset_type_id": 7, "price": 9999}],
    }
    report = bi.format_background_dossier(VISION, live=bad_market)
    assert "No usable sampled price reference" in report
    assert "R$9999" not in report


if __name__ == "__main__":
    test_only_explicit_category_92_competitors_are_used()
    test_exact_sample_title_is_excluded_without_claiming_global_uniqueness()
    test_similarity_is_descriptive_not_visual_or_sales_based()
    test_market_price_and_launch_plan_are_grounded()
    test_failed_market_and_unsupported_claims_are_not_fabricated()
    print("PASS background creator essentials")


def test_title_dry_run_not_ctr_forecast():
    results = bi.title_dry_run(VISION, live=LIVE)
    assert results and len(results) >= 1
    assert results == sorted(results, key=lambda x: (-x["fit_score"], x["title"].casefold()))
    assert all(0 <= row["fit_score"] <= 100 for row in results)
    assert all("not predicted CTR" in row["score_type"] for row in results)
    assert all("Moonlit Shrine Background" != row["title"] for row in results)
    report = bi.format_background_dossier(VISION, live=LIVE)
    assert "Title dry run" in report
    assert "Favorites forecast: unavailable" in report


def test_named_ip_warning_not_mistaken_for_rights_clearance():
    assert bi.named_ip_caution(VISION, "Oggy and the Cockroaches background")
    assert not bi.named_ip_caution(VISION, "an original moonlit shrine")
    report = bi.format_background_dossier(VISION, notes="Oggy house", live=LIVE)
    assert "Third-party IP warning" in report
    assert "Renaming copied artwork" in report
