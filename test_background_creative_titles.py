"""Creator-specific background title creativity and IP caveat regressions.

No network, model, or database. Verify named game inspiration is not
automatically reproduced as marketing copy; no claim of legal clearance.
"""
from background_creative_titles import (
    creative_title_issues, creative_lane_candidates, brand_sensitive_title,
)
from background_review import _valid_titles, build_multi_pass_review, format_multi_pass_review

GRASS = ("Garry's Mod (GMod) gm_flatgrass-inspired sandbox map. "
         "Large curved brick structure, huge open flat grassy field, "
         "green hills, and a clear blue sky. Distant FLATTYWOOD sign.")
OCEAN = ("BioShock Rapture-inspired underwater city observation room. "
         "Massive panoramic window looking out over a blue underwater city skyline, "
         "Art Deco structure, tiled floor and amber lights.")
HOUSE = ("Oggy and the Cockroaches-inspired sunny cartoon house. "
         "Purple roof, rainbow awnings, lush garden, green mailbox and walkway.")


def vision(summary, details):
    return {"visual_summary": summary,
            "search_description": summary,
            "distinctive_features": details}


def test_gmod_unbranded_ideas_are_creative_but_relevant():
    v = vision("Open flat grassy field with green hills, blue sky and brick structure",
               ["green hills", "curved brick building", "large grassy field"])
    options = creative_lane_candidates(v, GRASS)
    assert "Open Grassland Background" in options, options
    assert "Endless Green Fields Background" in options, options
    assert "GMod Flatgrass Background" not in options
    assert _valid_titles(options, v, GRASS, None) == options
    assert creative_title_issues("Open Grassland Background",
                                GRASS, GRASS) is None
    assert creative_title_issues("GMod Flatgrass Background",
                                GRASS, GRASS) == "unlicensed_identity_or_affiliation"


def test_rapture_allows_sunken_skyline_not_fantasy_props():
    v = vision("Art Deco observation room overlooking an underwater city skyline",
               ["panoramic window", "blue skyline", "tiled floor"])
    options = creative_lane_candidates(v, OCEAN)
    assert "Sunken Skyline Background" in options, options
    assert "Beyond The Glass Underwater City Background" in options, options
    assert _valid_titles(options, v, OCEAN, None) == options
    for bad in ("BioShock Rapture Window Background",
                "Rapture Underwater City Background",
                "Official Rapture Background",
                "Underwater Dragon Castle Background",
                "Animated Underwater City Background"):
        assert creative_title_issues(bad, OCEAN, OCEAN) is not None, bad


def test_oggy_does_not_transfer_brand_by_default():
    v = vision("Sunny cartoon house with purple roof and lush garden",
               ["rainbow awnings", "green mailbox"])
    options = creative_lane_candidates(v, HOUSE)
    assert "Sunlit Cartoon House Background" in options, options
    assert _valid_titles(options, v, HOUSE, None) == options
    assert not any("Oggy" in title for title in options)


def test_generic_style_without_scene_is_not_accepted():
    assert creative_title_issues("Mystic Dreamy Background",
                                 "a large field and blue sky") is not None
    assert creative_title_issues("Neon Dragon Garden Background",
                                 "lush garden with flowers") is not None
    assert brand_sensitive_title("Rapture Underwater City Background", OCEAN)
    # The word rapture can be ordinary prose outside the known franchise
    # context; the validator is a limited warning, not a trademark oracle.
    assert brand_sensitive_title("Rapture Garden Background", "beautiful garden") is None


def test_model_picks_distinct_memorable_unbranded_titles_without_copying_brand():
    v = vision("Flat green field and distant hills under blue open sky",
               ["curved brick wall", "green hills", "flat grassy field"])
    def model(prompt, **kwargs):
        if "JSON" in prompt and "titles" in prompt[:500]:
            return ('{"titles":["Endless Green Fields Background",'
                    '"Open Grassland Background",'
                    '"GMod Flatgrass Background",'
                    '"Banana Dragon Sandbox Background"]}')
        return ('{"winner":"Endless Green Fields Background",'
                '"alternatives":["Open Grassland Background"],'
                '"description":"An open grassy landscape under a bright blue sky."}')
    result = build_multi_pass_review(v, [], GRASS, None, None, model)
    assert result["status"] == "ok", result
    names = [result["winner"]] + result["alternatives"]
    assert any("Grass" in name or "Fields" in name for name in names)
    assert not any("GMod" in name or "Flatgrass" in name for name in names)
    report = format_multi_pass_review(result)
    assert "Unknown" in report
    assert "clear IP rights" not in report


def test_explicit_franchise_prefix_keeps_scene_hook_and_unbranded_alternatives():
    v = vision("An Art Deco observation room looking out at an underwater city",
               ["panoramic window", "underwater city skyline"])
    unavailable = lambda *args, **kwargs: None
    default = build_multi_pass_review(v, [], OCEAN, None, None, unavailable)
    assert not default["winner"].startswith("BioShock ")
    for request in ('Use "BioShock" in the title.',
                    "Please include BioShock at the start of my title."):
        result = build_multi_pass_review(v, [], OCEAN + " " + request, None, None, unavailable)
        assert result["winner"] == "BioShock " + default["winner"]
        assert "Underwater City" in result["winner"]
        assert default["winner"] in result["alternatives"]
        assert "Confirm permission" in format_multi_pass_review(result)

    for suffix in ("Do not use BioShock in the title.", "Use Official BioShock in the title."):
        result = build_multi_pass_review(v, [], OCEAN + " " + suffix, None, None, unavailable)
        assert result["winner"] == default["winner"]


def test_explicit_franchise_prefix_skips_an_exact_catalog_duplicate():
    v = vision("Haunted security office with a glowing computer",
               ["green lockers", "glowing computer"])
    notes = "Haunted security office."
    unavailable = lambda *args, **kwargs: None
    original = build_multi_pass_review(v, [], notes, None, None, unavailable)
    exact = "FNAF " + original["winner"]
    live = {"ok": True, "top_competitors": [{"name": exact, "asset_type_id": 92}]}
    result = build_multi_pass_review(v, [], notes + " Use FNAF in the title.", live, None, unavailable)
    assert result["winner"] != exact
    assert result["winner"].startswith("FNAF ")
    assert "Security Office" in result["winner"]


if __name__ == "__main__":
    test_gmod_unbranded_ideas_are_creative_but_relevant()
    test_rapture_allows_sunken_skyline_not_fantasy_props()
    test_oggy_does_not_transfer_brand_by_default()
    test_generic_style_without_scene_is_not_accepted()
    test_model_picks_distinct_memorable_unbranded_titles_without_copying_brand()
    test_explicit_franchise_prefix_keeps_scene_hook_and_unbranded_alternatives()
    test_explicit_franchise_prefix_skips_an_exact_catalog_duplicate()
    print("PASS creative unbranded Avatar Background title routes")
