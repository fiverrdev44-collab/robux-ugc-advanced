"""Regression: exact reported generic output must never be accepted as good copy."""
from description_quality import (
    rejection_reason, finalize_description, rewrite_prompt, style_guidance,
)
from background_review import _polish_background_copy

CONCEPT = (
    "Oggy and the Cockroaches-inspired colorful cartoon house with purple roof, "
    "rainbow-striped awnings, lush sunny garden, green mailbox, butterflies "
    "and central walkway. Create a premium Roblox Avatar Background launch "
    "assessment. Prioritize a natural title."
)
BAD_LIVE = (
    "colorful house background with a purple roof and rainbow-striped awnings. "
    "features a sunny garden, green mailbox, and central walkway.\n"
    "vibrant cartoon scene for your avatar."
)
GOOD = (
    "A little cartoon house with a purple roof and colorful awnings.\n"
    "There's a green mailbox beside the sunny garden and central walkway."
)

def test_exact_live_generic_output_rejected():
    assert rejection_reason(BAD_LIVE, CONCEPT, "backgrounds") is not None
    assert rejection_reason("Vibrant cartoon scene for your avatar.", CONCEPT,
                            "backgrounds") == "generic_template"
    assert rejection_reason("Features a garden and mailbox.", CONCEPT,
                            "backgrounds") == "feature_inventory"

def test_rewrite_is_conditional_and_bounded():
    calls = []
    def writer(prompt):
        calls.append(prompt)
        return GOOD
    result = finalize_description(BAD_LIVE, CONCEPT, "backgrounds",
                                  "Sunny Cartoon House Background", writer)
    assert result["quality_status"] == "rewritten", result
    assert result["text"] == GOOD
    assert result["rewrite_attempted"] is True
    assert len(calls) == 1
    assert "Create a premium Roblox" not in calls[0]

    untouched = finalize_description(GOOD, CONCEPT, "backgrounds",
                                     "Sunny Cartoon House Background", writer)
    assert untouched["quality_status"] == "accepted", untouched
    assert len(calls) == 1

def test_bad_or_unavailable_rewrite_fails_safely():
    calls = []
    def bad(prompt):
        calls.append(prompt)
        return "Enhance your avatar experience with this ultimate background."
    result = finalize_description(BAD_LIVE, CONCEPT, "backgrounds",
                                  "Sunny Cartoon House Background", bad)
    assert result["quality_status"] == "factual_fallback"
    assert len(calls) == 1
    assert "Enhance your avatar" not in result["text"]
    assert "vibrant cartoon scene" not in result["text"].lower()

    no_model = finalize_description(BAD_LIVE, CONCEPT, "backgrounds")
    assert no_model["quality_status"] == "factual_fallback"
    assert no_model["rewrite_attempted"] is False

def test_background_analyzer_passes_visual_context_once():
    visual = {
        "visual_summary": "Sunny cartoon house with purple roof and colorful awnings",
        "search_description": "Sunny Cartoon House Background",
        "distinctive_features": ["purple roof", "green mailbox", "rainbow awnings"],
    }
    calls = []
    def text_fn(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return GOOD
    polished = _polish_background_copy(
        BAD_LIVE, visual, CONCEPT,
        "Sunny Cartoon House Background", text_fn=text_fn
    )
    # Background review already uses its two permitted model passes. It
    # rejects the weak copy and falls back without invoking a third.
    assert "vibrant cartoon scene" not in polished.lower()
    assert "Sunny Cartoon House Background" in polished
    assert calls == []

def test_family_specific_claims():
    assert rejection_reason(
        "The fluffy cat beanie spins as you walk.",
        "fluffy cat beanie with paws", "headwear") == "unsupported_motion"
    assert rejection_reason(
        "A smooth hip-hop dance with a left-foot kick.",
        "smooth hip-hop dance with a left-foot kick", "emotes") is None
    assert "movement" in style_guidance("emotes") or "movements" in style_guidance("emotes")

if __name__ == "__main__":
    test_exact_live_generic_output_rejected()
    test_rewrite_is_conditional_and_bounded()
    test_bad_or_unavailable_rewrite_fails_safely()
    test_background_analyzer_passes_visual_context_once()
    test_family_specific_claims()
    print("PASS description quality v2 exact report regressions")
