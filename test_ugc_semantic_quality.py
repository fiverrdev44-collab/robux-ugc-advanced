"""Regression: observed Roblox UGC failure must not turn hip-hop dances into streetwear.

Read-only, offline. Covers family scope, identity retention, pre-live keyword
filtering, suggestion sanitization and semantic ranking.
"""
from unittest import mock
import chain
import smart_pipeline
from ugc_semantics import (
    filter_intent_for_family, grounded_keyword, is_foreign_platform_description,
    sanitize_generated_strategy, title_is_grounded,
)

EMOTE = "Jabba No Chill Hip Hop Street Dance"
BACKGROUND = "Haunted Security Office Background"


def test_streetwear_cannot_replace_emote_identity():
    bad = (
        "Streetwear Jabba Hip Hop Dance",
        "Streetwear Urban Hip Hop Emote",
        "Streetwear Jabba Groove Emote",
        "Streetwear Freestyle Hip Hop Dance",
        "Viral Jabba Urban Street Dance",
        "Jabba Freestyle Streetwear Dance",
        "Jabba Moonlit Night Background",
    )
    for title in bad:
        passed, reason = title_is_grounded(EMOTE, title, "emote")
        assert not passed, (title, reason)
        assert title not in chain._astra_filter([title], EMOTE, "emote")
    good = (
        "Jabba Urban Street Dance",
        "Jabba Hip Hop Street Dance",
        "Jabba Freestyle Dance",
    )
    for title in good:
        passed, reason = title_is_grounded(EMOTE, title, "emote")
        assert passed, (title, reason)
        assert title in chain._astra_filter([title], EMOTE, "emote")


def test_motion_nouns_cannot_be_swapped_for_keyword_score():
    assert not title_is_grounded("Hero Battle Pose",
                                 "Hero Battle Dance", "emote")[0]
    assert not title_is_grounded("Standing Hero Stance",
                                 "Standing Hero Dance", "emote")[0]
    assert not title_is_grounded("Jabba Street Dance",
                                 "Jabba Street Emote", "emote")[0]
    assert title_is_grounded("Jabba Street Dance",
                             "Jabba Street Dance", "emote")[0]


def test_multi_family_relevance_and_creator_override():
    assert not grounded_keyword("streetwear", "emotes", EMOTE,
                                for_alternative=True)
    assert not grounded_keyword("streetwear", "emote", EMOTE)
    assert grounded_keyword("streetwear", "clothing",
                            "Oversized Streetwear Hoodie",
                            for_alternative=True)
    assert not grounded_keyword("dance", "backgrounds", BACKGROUND,
                                for_alternative=True)
    assert not title_is_grounded(BACKGROUND,
                                 "Streetwear Security Office Background",
                                 "backgrounds")[0]
    assert title_is_grounded(BACKGROUND,
                             "Haunted Security Office Background",
                             "backgrounds")[0]


def test_ai_expansion_must_not_pollute_intent_or_niche():
    intent = {
        "primary": ["jabba", "streetwear"],
        "specific_moves": ["hip hop", "dance"],
        "style": ["streetwear", "urban"],
        "search_terms": ["streetwear", "dance", "freestyle"],
        "item_type": "emote",
    }
    filtered = filter_intent_for_family(intent, "emote", EMOTE)
    assert "streetwear" not in filtered["primary"]
    assert "streetwear" not in filtered["style"]
    assert "streetwear" not in filtered["search_terms"]
    assert "dance" in filtered["search_terms"]
    assert "jabba" in filtered["primary"]
    assert intent["primary"] == ["jabba", "streetwear"]


def test_final_strategy_hides_wrong_family_titles_and_marketing():
    sample = {
        "titles_safe": ["Jabba Urban Street Dance",
                        "Streetwear Jabba Hip Hop Dance"],
        "titles_differentiated": ["Streetwear Jabba Groove Emote"],
        "titles_longtail": ["Jabba Freestyle Street Dance"],
        "titles_viral": ["Viral Streetwear Jabba Dance"],
        "killer_keywords": ["streetwear", "hip hop", "dance", "freestyle"],
        "best_pivot": {"keyword": "streetwear", "reason": "VIRGIN"},
        "cross_promotion_play": "Bundle this emote with streetwear clothing items.",
        "social_playbook": "Post two TikTok clips with trending audio.",
        "market_diagnosis": "Hip hop street dance is a movement item.",
        "bonus_plays": ["Jabba Streetwear Idle Pose", "Jabba Freestyle Dance"],
    }
    clean = sanitize_generated_strategy(sample, "emote", EMOTE)
    assert clean["titles_safe"] == ["Jabba Urban Street Dance"]
    assert not clean["titles_differentiated"]
    assert clean["titles_longtail"] == ["Jabba Freestyle Street Dance"]
    assert not clean["titles_viral"]
    assert clean["killer_keywords"] == ["hip hop", "dance", "freestyle"]
    assert clean["best_pivot"] == {}
    assert clean["cross_promotion_play"] == ""
    assert clean["social_playbook"] == ""
    assert clean["bonus_plays"] == ["Jabba Freestyle Dance"]
    assert clean["market_diagnosis"]


def test_reject_foreign_game_description_without_discarding_valid_roblox():
    assert is_foreign_platform_description(
        "Jabba Switchway",
        "Jabba Switchway is an Icon Series Emote in Fortnite, purchasable "
        "from the Item Shop.")
    assert not is_foreign_platform_description(
        "Jabba Urban Street Dance",
        "Jabba Urban Street Dance for your Roblox avatar.")


class _StubCursor:
    def close(self):
        pass


class _StubConn:
    def __init__(self):
        self.cur = _StubCursor()
    def cursor(self):
        return self.cur
    def close(self):
        pass


def test_smart_pipeline_filters_bad_alternatives_before_worker():
    attempted = []
    def worker(word, count, category_asset_ids, db_factory, live_enrich):
        attempted.append(word)
        return {"word": word, "gap_score": 1, "comp": 2,
                "median_favs": 110, "median_price": 55, "co_occurs": count}
    with mock.patch.object(smart_pipeline, "_find_alt_candidates",
                           return_value=[("streetwear", 8),
                                         ("freestyle", 7),
                                         ("duck", 3)]), \
         mock.patch.object(smart_pipeline, "_alt_worker", side_effect=worker):
        rows = smart_pipeline.find_alternatives_parallel(
            ["dance"], [61], lambda: _StubConn(), limit=10,
            live_enrich=True, family="emote", description=EMOTE)
    assert attempted == ["freestyle"], attempted
    assert [r["word"] for r in rows] == ["freestyle"]


def test_smart_report_does_not_claim_dance_was_replaced():
    output = smart_pipeline._format_report({
        "parallel": False, "live_enriched": False,
        "seeds": ["dance"], "seed_analysis": [],
        "saturated_seeds": ["dance"], "alternatives": [],
    })
    assert "NOT AUTO-REPLACED" in output
    assert "AUTO-REPLACED:" not in output


if __name__ == "__main__":
    test_streetwear_cannot_replace_emote_identity()
    test_motion_nouns_cannot_be_swapped_for_keyword_score()
    test_multi_family_relevance_and_creator_override()
    test_ai_expansion_must_not_pollute_intent_or_niche()
    test_final_strategy_hides_wrong_family_titles_and_marketing()
    test_reject_foreign_game_description_without_discarding_valid_roblox()
    test_smart_pipeline_filters_bad_alternatives_before_worker()
    test_smart_report_does_not_claim_dance_was_replaced()
    print("PASS identity-grounded UGC keyword and chain strategy quality")
