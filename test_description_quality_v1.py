"""No-network checks for human-sounding, grounded catalog description quality."""
import description_quality as dq
import chain
import background_review


def test_casual_grounded_background_copy():
    concept = ("Oggy-inspired sunny cartoon house with purple roof, "
               "rainbow striped awnings, green mailbox, butterflies and a central walkway. "
               "Create a premium launch assessment and predict high CTR.")
    assert "Create a premium" not in dq.fact_source(concept)
    draft = ("A sunny cartoon house with a purple roof.\n"
             "Rainbow awnings, green mailbox and butterflies in the garden.")
    assert dq.rejection_reason(draft, concept, "backgrounds") is None
    assert dq.polish_description(draft, concept, "backgrounds") == draft


def test_generic_template_replaced_without_invented_claims():
    concept = "sunny cartoon house with a purple roof, striped awnings and green mailbox"
    bad = ("Enhance your Roblox avatar experience with this ultimate home! "
           "Perfect for your next avatar look.")
    assert dq.rejection_reason(bad, concept, "backgrounds") == "generic_template"
    result = dq.polish_description(bad, concept, "backgrounds",
                                   title="Sunny Cartoon House Background")
    assert "purple roof" in result.lower()
    assert "striped awnings" in result.lower()
    assert "Enhance" not in result
    assert "Perfect for your" not in result


def test_no_unsupported_effects_or_seller_performance():
    concept = "sunny cartoon house with a purple roof and a mailbox"
    assert dq.rejection_reason(
        "An interactive 3D cartoon house with a purple roof.",
        concept, "backgrounds"
    ).startswith("unverified_feature:")
    assert dq.rejection_reason(
        "Cartoon house where the mailbox moves and dances.",
        concept, "backgrounds"
    ) == "unsupported_motion"
    assert dq.rejection_reason(
        "Guaranteed high CTR for this purple cartoon house.",
        concept, "backgrounds"
    ) == "unverified_performance"


def test_emote_and_accessory_facts_are_distinct():
    emote = "smooth spinning flip dance with a confident landing"
    good = "Smooth spinning flip dance with a confident landing."
    assert dq.rejection_reason(good, emote, "emotes") is None
    hat = "cute fluffy cat beanie with small paws"
    assert dq.rejection_reason(
        "Cute fluffy cat beanie that spins when you dance.",
        hat, "headwear"
    ) == "unsupported_motion"
    result = dq.polish_description(
        "Perfect for any Roblox avatar.", hat, "headwear",
        title="Cute Fluffy Cat Beanie")
    assert "fluffy" in result.lower() or "paws" in result.lower()


def test_chain_and_background_share_gate():
    concept = "moonlit shrine with a glowing portal and stone path"
    assert "perfect for your" not in chain._fallback_description(
        concept, "backgrounds").lower() or dq.rejection_reason(
            chain._fallback_description(concept, "backgrounds"),
            concept, "backgrounds"
        ) == "generic_template"
    polished = background_review._polish_background_copy(
        "Elevate your avatar experience with this ultimate shrine!",
        {"visual_summary": "Moonlit shrine with a glowing portal",
         "search_description": "Moonlit Shrine Background",
         "distinctive_features": ["glowing portal", "stone path"]},
        "moonlit shrine with a glowing portal and stone path",
        "Moonlit Shrine Background",
    )
    assert "elevate" not in polished.lower()
    assert "Moonlit Shrine Background" in polished


def test_consistent_category_prompt_guidance():
    assert "movements" in dq.style_guidance("emotes")
    assert "scene" in dq.style_guidance("backgrounds")
    assert "materials" in dq.style_guidance("hair")


if __name__ == "__main__":
    test_casual_grounded_background_copy()
    test_generic_template_replaced_without_invented_claims()
    test_no_unsupported_effects_or_seller_performance()
    test_emote_and_accessory_facts_are_distinct()
    test_chain_and_background_share_gate()
    test_consistent_category_prompt_guidance()
    print("PASS human description quality regressions")
