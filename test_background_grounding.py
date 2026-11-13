"""Offline cross-family visual claim verification tests. No real model/marketplace."""
from background_grounding import (
    reconcile_background_vision, format_visual_verification,
)
from background_intelligence import scene_phrase
from background_review import build_multi_pass_review, _valid_titles

def horror_first():
    return {
        "item_type_visual": "background",
        "visual_summary": "Haunted security office with a bear face on a wall poster.",
        "search_description": "Security Office Background",
        "distinctive_features": [
            "bear face on a wall poster", "green lockers", "glowing computer"
        ],
        "primary_subject": "bear face",
        "subject_relation": "wall poster",
    }


def test_fnaf_window_poster_disagreement_never_forces_either():
    image_only = {
        "visual_summary": "A bear at a window in a dark security office.",
        "primary_subject": "bear",
        "subject_relation": "window",
        "distinctive_features": ["bear at window", "security desk"],
        "uncertain_elements": ["unclear if bear is moving"],
    }
    combined = reconcile_background_vision(
        horror_first(), image_only, "FNAF haunted security office bear peeking through window")
    assert combined["status"] == "conflict"
    assert combined["independent_checked"]
    assert combined["relation_conflict"]
    vision = combined["vision"]
    assert set(vision["visual_conflicting_placements"]) == {"window", "poster"}
    assert "bear" in vision["distinctive_features"]
    assert not any("poster" in x or "window" in x for x in vision["distinctive_features"])
    assert "poster" not in vision["visual_summary"].lower()
    assert "subject's location" in format_visual_verification(combined)
    assert not _valid_titles(
        ["Bear Window Security Office Background",
         "Bear Poster Security Office Background"],
        vision, "haunted security office", None)
    assert _valid_titles(["Haunted Security Office Background"],
                         vision, "haunted security office", None)


def test_creator_window_claim_is_not_auto_verified():
    primary = horror_first()
    image_only = dict(primary)
    image_only["uncertain_elements"] = ["poster or glass reflection"]
    result = reconcile_background_vision(
        primary, image_only, "FNAF bear peeking through window in a security office")
    assert result["creator_conflict"], result
    assert result["status"] == "conflict"
    assert "window" in result["vision"]["visual_conflicting_placements"]
    assert "poster" in result["vision"]["visual_conflicting_placements"]


def test_shrine_without_conflict_stays_searchable():
    first = {
        "visual_summary": "Moonlit shrine with a glowing portal at night.",
        "search_description": "Moonlit Shrine Background",
        "distinctive_features": ["glowing portal", "stone path"],
        "primary_subject": "portal",
        "subject_relation": "unknown",
    }
    independent = {
        "visual_summary": "A moonlit shrine and glowing portal.",
        "primary_subject": "portal", "subject_relation": "unknown",
        "distinctive_features": ["glowing portal"],
    }
    result = reconcile_background_vision(first, independent, "moonlit shrine")
    assert result["status"] == "cross_checked", result
    assert not result["creator_conflict"]
    assert "glowing portal" in result["vision"]["distinctive_features"]
    assert _valid_titles(["Glowing Moonlit Shrine Background"],
                         result["vision"], "moonlit shrine", None)


def test_setting_conflict_prevents_creator_only_anchor():
    first = {
        "visual_summary": "Misty pine forest and a mountain.",
        "search_description": "Misty Forest Background",
        "distinctive_features": ["pine trees", "mountain ridge"],
    }
    independent = {
        "visual_summary": "Pine forest with high mist.",
        "distinctive_features": ["pine trees", "mist"],
    }
    result = reconcile_background_vision(first, independent, "Security office backdrop")
    assert result["scene_conflict"]
    assert scene_phrase(result["vision"], "Security office backdrop") != "security office"
    assert "different setting" in " ".join(result["notes"])


def test_failed_second_pass_cannot_be_called_confirmed():
    result = reconcile_background_vision(horror_first(), {}, "")
    assert result["status"] == "unverified"
    assert not result["independent_checked"]
    assert "unavailable" in format_visual_verification(result)


def test_conflicting_subjects_block_subject_titles():
    first = {
        "visual_summary": "Eerie castle courtyard with a ghost",
        "search_description": "Castle Courtyard Background",
        "distinctive_features": ["ghost floating by castle"],
        "primary_subject": "ghost", "subject_relation": "unknown",
    }
    other = {
        "visual_summary": "Eerie castle courtyard with a bear",
        "primary_subject": "bear", "subject_relation": "unknown",
    }
    result = reconcile_background_vision(first, other, "castle courtyard")
    # A subject unknown to the classifier cannot be falsely 'verified'; the
    # title generator still cannot invent new unsupported objects.
    assert result["status"] in ("cross_checked", "conflict")
    assert not _valid_titles(["Dragon Castle Courtyard Background"],
                             result["vision"], "castle courtyard", None)


def test_model_failure_reports_fallback_honestly():
    first = {
        "visual_summary": "Misty forest glowing at twilight.",
        "search_description": "Misty Forest Background",
        "distinctive_features": ["misty trees"],
    }
    result = build_multi_pass_review(
        first, [], "misty forest", None, lambda *_: {},
        lambda *args, **kwargs: None)
    assert result["status"] == "ok", result
    assert result["passes"]["creative"] == "fallback_only"
    assert result["winner"].endswith("Background")
    assert "forest" in result["winner"].lower()


if __name__ == "__main__":
    test_fnaf_window_poster_disagreement_never_forces_either()
    test_creator_window_claim_is_not_auto_verified()
    test_shrine_without_conflict_stays_searchable()
    test_setting_conflict_prevents_creator_only_anchor()
    test_failed_second_pass_cannot_be_called_confirmed()
    test_conflicting_subjects_block_subject_titles()
    test_model_failure_reports_fallback_honestly()
    print("PASS background visual claim reconciliation and safe title fallback")
