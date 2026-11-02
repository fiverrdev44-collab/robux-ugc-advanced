"""Phase 1 product-understanding tests (offline)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import product_understanding as pu


def test_blue_hat_no_motion():
    u = pu.from_text("I made a new hat and it's blue")
    assert u["family"] == "headwear", u
    assert [c["value"] for c in u["colors"]] == ["blue"]
    assert u["motion"] == [] and u["motion_required"] is False
    details = [d["value"] for d in u["details"]]
    for invented in ("beanie", "stars", "glow", "wings"):
        assert invented not in details
    ok, why = pu.validate_title("blue hat", "Dancing Blue Hat", "headwear")
    assert not ok and why == "static accessory must not claim motion"
    ok, _ = pu.validate_title("blue hat", "Blue Hat", "headwear")
    assert ok
    print("PASS blue hat: no motion, no invented features")


def test_emote_thumbnail_rule():
    vision = {
        "item_type_visual": "emote",
        "visual_summary": "dancing pose with arms up",
        "visual_colors": ["red"],
        "distinctive_features": ["jumping"],
        "motion": ["dance", "jump"],
    }
    u = pu.from_image(vision, "super saiyan battle pose", image_kind="thumbnail")
    assert u["family"] == "emotes"
    assert u["motion"] == [] and u["motion_required"] is False
    assert u["thumbnail_blocked"] is True
    assert any("static image" in x for x in u["unknowns"])
    print("PASS emote thumbnail: motion is not inferred from a static image")

    preview = pu.from_image(vision, "super saiyan battle pose",
                            image_kind="preview")
    assert preview["motion"], "creator preview may describe motion"
    print("PASS creator preview may supply motion")


def test_static_text_motion_stripped():
    u = pu.from_text("blue dancing hat with swaying tassels")
    assert u["family"] == "headwear"
    assert u["motion"] == [] and u["motion_required"] is False
    print("PASS static accessory motion stripped")


def test_user_overrides_api():
    u = pu.merge("blue hat", api_family="emotes")
    assert u["family"] == "headwear"
    assert u["family_source"] == "user"
    print("PASS user text overrides API family")


def test_identity_lock_override():
    ok, why = pu.validate_title("super saiyan battle pose",
                                "Super Saiyan Death Pose", "emotes")
    assert not ok and why == "motion swapped"
    ok, _ = pu.validate_title("super saiyan battle pose",
                              "Super Saiyan Battle Pose", "emotes")
    assert ok
    ok, _ = pu.validate_title("super saiyan battle stance",
                              "Super Saiyan Battle Stance", "emotes")
    assert ok  # explicit user wording is the override
    print("PASS identity lock with explicit wording override")


def test_prompt_block_sources():
    u = pu.from_text("blue hat")
    block = pu.to_prompt_block(u)
    assert "family: headwear (user)" in block
    assert "motion: none (static)" in block
    print("PASS prompt block records sources")


if __name__ == "__main__":
    test_blue_hat_no_motion()
    test_emote_thumbnail_rule()
    test_static_text_motion_stripped()
    test_user_overrides_api()
    test_identity_lock_override()
    test_prompt_block_sources()
    print("ALL PRODUCT UNDERSTANDING TESTS PASSED")
