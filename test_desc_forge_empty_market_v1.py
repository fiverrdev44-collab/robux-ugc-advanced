"""Regression: creator supplied Oggy concept must not fail with zero market peers."""
from unittest.mock import patch
import desc_forge

OGGY = ("Oggy-inspired sunny cartoon house with purple roof, rainbow-striped "
        "awnings, lush green garden, butterflies, green mailbox and central walkway")


def test_long_concept_prioritizes_actual_scene():
    keywords = desc_forge._candidate_keywords(OGGY)
    assert "cartoon house" in keywords[:3], keywords
    assert keywords[0] != "walkway"
    assert len(keywords) <= 8
    assert len(keywords[0]) < len(OGGY)


def test_no_db_or_live_match_still_returns_description():
    with (patch.object(desc_forge, "_fetch_description_cohorts", return_value=(
            [], {"established_candidates": 0,
                 "measured_rising_candidates": 0,
                 "rising_status": "insufficient_history"})),
          patch.object(desc_forge, "_generate_description", return_value=(
              "A little cartoon house with a purple roof and rainbow awnings.\n"
              "A sunny garden, butterflies and green mailbox line the walkway."))):
        result = desc_forge.forge_description(OGGY, family="backgrounds")
    assert "error" not in result, result
    assert result["description"].startswith("A little cartoon")
    assert result["evidence_status"] == "creator_details_only"
    assert result["examples"] == []
    rendered = "\n".join(desc_forge.format_forge(result))
    assert "No verified matching seller descriptions" in rendered
    assert "None" not in rendered
    assert "Top examples it studied" not in rendered


def test_no_model_returns_factual_copy_not_empty_market_error():
    with (patch.object(desc_forge, "_fetch_description_cohorts", return_value=(
            [], {"established_candidates": 0, "measured_rising_candidates": 0,
                 "rising_status": "unavailable"})),
          patch.object(desc_forge, "_generate_description", side_effect=RuntimeError("API down"))):
        result = desc_forge.forge_description(OGGY, family="backgrounds")
    assert "error" not in result, result
    assert result["description"]
    assert "purple roof" in result["description"].lower()
    assert result["evidence_status"] == "creator_details_only"


def test_available_market_keeps_evidence_label():
    sample = ("Cartoon Garden House Background",
              "Sunny house with striped awnings and a garden gate.", 420, 200)
    with (patch.object(desc_forge, "_fetch_description_cohorts", return_value=(
            [sample], {"established_candidates": 1,
                       "measured_rising_candidates": 0,
                       "rising_status": "insufficient_history"})),
          patch.object(desc_forge, "_generate_description", return_value=(
              "Sunny cartoon house with a purple roof and rainbow awnings."))):
        result = desc_forge.forge_description(OGGY, family="backgrounds")
    assert result["evidence_status"] == "observed"
    assert len(result["examples"]) == 1


if __name__ == "__main__":
    test_long_concept_prioritizes_actual_scene()
    test_no_db_or_live_match_still_returns_description()
    test_no_model_returns_factual_copy_not_empty_market_error()
    test_available_market_keeps_evidence_label()
    print("PASS desc forge sparse-market creator-only regressions")
