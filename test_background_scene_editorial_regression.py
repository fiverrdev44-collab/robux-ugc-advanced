"""Real Discord Rapture scene report regressions, offline and deterministic.

Reproduces November 19 failure: room-versus-underwater-view false conflict,
irrelevant gaming room category competitors, generic Art Deco title and
fabricated first-person motivation. No real Roblox requests, AI or DB.
"""
import background_review as review
from background_grounding import reconcile_background_vision
from background_intelligence import relevant_background_competitors

NOTES = (
    "BioShock Rapture-inspired underwater city observation room. "
    "Massive panoramic window overlooking mysterious underwater skyscrapers, "
    "dark teal Art Deco architecture, tiled floor, glowing amber lights."
)
FIRST = {
    "visual_summary": (
        "Art Deco observation room with panoramic window overlooking "
        "an underwater city skyline."
    ),
    "search_description": "Art Deco observation room",
    "distinctive_features": [
        "large central panoramic window", "underwater cityscape",
        "tiled reflective floor", "Art Deco columns",
    ],
    "primary_subject": "observation room",
    "subject_relation": "window",
}
SECOND = {
    "visual_summary": (
        "Observation room with tiled floor and window looking "
        "over a blue underwater city."
    ),
    "search_description": "large central observation room",
    "distinctive_features": ["tiled reflective floor", "underwater city view"],
    "primary_subject": "observation room",
    "subject_relation": "window",
    "uncertain_elements": ["whether fish are in an aquarium or beyond the glass"],
}
LIVE = {
    "ok": True, "top_competitors": [
        {"name": "Death Note L Dark City Room Anime Game Background",
         "asset_type_id": 92, "asset_id": 81589366413493,
         "favorites": 120},
        {"name": "Purple Night Gaming Room Background",
         "asset_type_id": 92, "asset_id": 128294345993625,
         "favorites": 52},
        {"name": "Pink Gaming Room Kawaii Background",
         "asset_type_id": 92, "asset_id": 96786986475982,
         "favorites": 32},
    ],
    "search_checks": [{"query": "observation room background", "status": "ok",
                       "asset_type_92_matches": 19, "sampled_results": 30,
                       "pages": 1, "cached": False}],
}


def test_window_view_not_a_global_scene_conflict():
    out = reconcile_background_vision(FIRST, SECOND, NOTES)
    assert out["independent_checked"]
    assert not out["scene_conflict"], out
    assert out["status"] == "cross_checked", out
    assert "underwater cityscape" in out["vision"]["distinctive_features"]


def test_real_forest_versus_office_contradiction_remains_conflict():
    first = {"visual_summary": "Misty pine forest",
             "search_description": "Misty forest", "primary_subject": "forest"}
    second = {"visual_summary": "A pine forest",
              "primary_subject": "forest"}
    out = reconcile_background_vision(first, second, "haunted security office")
    assert out["scene_conflict"]


def test_generic_gaming_rooms_are_not_competitor_examples():
    out = relevant_background_competitors(LIVE, FIRST, NOTES)
    assert out == [], out
    valid_live = dict(LIVE, top_competitors=LIVE["top_competitors"] + [
        {"name": "Underwater City Window Background",
         "asset_type_id": 92, "asset_id": 112233, "favorites": 7},
        {"name": "Underwater City Window Hat",
         "asset_type_id": 8, "asset_id": 112234, "favorites": 9999},
    ])
    out = relevant_background_competitors(valid_live, FIRST, NOTES)
    assert len(out) == 1 and out[0]["asset_id"] == 112233


def test_specific_title_beats_generic_observation_room():
    vision = reconcile_background_vision(FIRST, SECOND, NOTES)["vision"]
    titles = review._valid_titles(
        review._editorial_candidates(vision, NOTES) +
        ["Art Deco Observation Room Background"], vision, NOTES, LIVE)
    assert "Underwater City Observation Room Background" in titles, titles
    winner_priority = review._fit(
        "Underwater City Observation Room Background", vision, NOTES, LIVE)
    generic = review._fit(
        "Art Deco Observation Room Background", vision, NOTES, LIVE)
    assert winner_priority["view_landmark"] is True
    assert generic["view_landmark"] is False

    prompts = []
    def model(prompt, **kwargs):
        prompts.append(prompt)
        if len(prompts) == 1:
            return ('{"titles":["Art Deco Observation Room Background",'
                    '"Underwater City Observation Room Background",'
                    '"Underwater City Background"]}')
        return ('{"winner":"Art Deco Observation Room Background",'
                '"alternatives":["Underwater City Background"],'
                '"why_winner":"Artwork framing",'
                '"description":"I put this digital background together because '
                'I wanted an underwater city backdrop with amber lights."}')
    data = review.build_multi_pass_review(
        vision, [], NOTES, LIVE, None, model,
        {"status": "unavailable", "angles": []},
        {"status": "insufficient", "patterns": []})
    assert data["status"] == "ok", data
    assert "Underwater City" in data["winner"], data
    assert not data["competitors"], data["competitors"]
    assert "I put this" not in data["description"], data["description"]
    assert "underwater city" in data["description"].lower()
    assert "window" in data["description"].lower()
    report = review.format_multi_pass_review(data)
    assert "Scene-relevant AssetType 92 comparables" in report
    assert "No scene-relevant comparable titles" in report
    assert "19 correct-category" in report
    assert "Death Note" not in report
    assert "Pink Gaming" not in report
    assert len(prompts) == 2


def test_real_vision_conflict_still_avoids_unsupported_scene_claim():
    first = {"visual_summary": "Security office",
             "search_description": "Security office",
             "distinctive_features": ["desk", "locker"]}
    second = {"visual_summary": "Dark security office",
              "distinctive_features": ["desk"]}
    # No conflict with consistent scene.
    assert not reconcile_background_vision(
        first, second, "security office")["scene_conflict"]


if __name__ == "__main__":
    test_window_view_not_a_global_scene_conflict()
    test_real_forest_versus_office_contradiction_remains_conflict()
    test_generic_gaming_rooms_are_not_competitor_examples()
    test_specific_title_beats_generic_observation_room()
    test_real_vision_conflict_still_avoids_unsupported_scene_claim()
    print("PASS scene compatibility, relevant competitors, natural title and copy")
