"""Conversation routing contract: explicit item IDs, action verbs and follow-ups.

Runs fully offline. The router must not quietly turn a rename request into
chain, competitor lookup, autopsy of an old item, or a listing mutation.
"""
import asyncio
from unittest import mock
import vanta_conversation as vc

BACKGROUND = 125628794109589
OLD_EMOTE = 92364796546749
NEW_EMOTE = 11444555666777


def seeded():
    state = vc.ConversationState(user_id=1)
    state.last_item_id = OLD_EMOTE
    state.last_family = "emote"
    state.last_concept = "smooth 360 flip"
    state.pending_chain = {"family": "emote", "concept": "dance"}
    state.pending_intent = "tags"
    state.pending_action = {"intent": "tags"}
    state.results = [OLD_EMOTE]
    state.item_titles = {OLD_EMOTE: "Smooth 360 flip Rizz"}
    return state


def route(text, state):
    with mock.patch.object(
        vc, "_planner_ai", side_effect=AssertionError("planner must not run")
    ):
        return asyncio.run(vc.plan_message(text, False, state))


def test_explicit_id_with_and_without_family():
    cases = (
        "I want to rename 125628794109589",
        "I want to rename 125628794109589 Background",
        "rename 125628794109589 background",
        "I wanna rename item 125628794109589",
        "Can I rename 125628794109589?",
        "could I retitle the background 125628794109589?",
        "I want to change the title of item 125628794109589",
    )
    for phrase in cases:
        state = seeded()
        result = route(phrase, state)
        assert result["intent"] == "clarify", (phrase, result)
        assert result["item_id"] == BACKGROUND, (phrase, result)
        assert "new title" in result["question"].lower()
        assert state.last_item_id == BACKGROUND
        assert state.last_concept is None
        assert state.results == []
        assert state.pending_chain is None
        assert state.pending_intent == "review_title"
        assert state.pending_action["item_id"] == BACKGROUND
        if "background" in phrase.lower():
            assert result["family"] == "backgrounds", (phrase, result)


def test_proposed_name_is_review_not_launch_or_autopsy():
    proposals = (
        "I want to rename 125628794109589 to Haunted Pizzeria Office Background",
        "Can I rename 125628794109589 as Creepy Security Office Background?",
        "What if I rename 125628794109589 to Haunted Security Office Background?",
        "change the title of item 125628794109589 to Animatronic Security Office Background",
    )
    for phrase in proposals:
        state = seeded()
        result = route(phrase, state)
        assert result["intent"] == "review_title", (phrase, result)
        assert result["item_id"] == BACKGROUND
        assert "Background" in result["concept"]
        assert state.last_item_id == BACKGROUND
        assert state.pending_action is None
        assert state.last_concept is None


def test_ordinary_commands_not_hijacked_by_rename_parser():
    # Verbs, not just presence of an ID, select the intended engine.
    expected = (
        ("revive 125628794109589 Background", "revive_item", BACKGROUND),
        ("autopsy 125628794109589", "diagnose_item", BACKGROUND),
        ("check item 125628794109589", "inspect_item", BACKGROUND),
        ("how much have i made recently", "check_sales", None),
        ("rename viral russian", "create_ideas", OLD_EMOTE),
        ("retitle it to cute hip sway", "create_ideas", OLD_EMOTE),
    )
    for phrase, intent, item in expected:
        state = seeded()
        result = route(phrase, state)
        assert result["intent"] == intent, (phrase, result)
        if item is not None:
            assert result.get("item_id") == item, (phrase, result)


def test_sticky_id_and_title_only_followup():
    state = seeded()
    first = route("I want to rename 125628794109589 Background", state)
    assert first["intent"] == "clarify"
    second = route("Haunted Pizzeria Security Office Background", state)
    assert second["intent"] == "review_title"
    assert second["item_id"] == BACKGROUND
    assert second["family"] == "backgrounds"
    assert second["concept"] == "Haunted Pizzeria Security Office Background"
    assert second["item_id"] != OLD_EMOTE


def test_new_explicit_item_overrides_pending_context():
    state = seeded()
    first = route("I want to rename 125628794109589 Background", state)
    assert first["intent"] == "clarify"
    second = route("I want to rename 11444555666777 Emote", state)
    assert second["intent"] == "clarify"
    assert state.pending_action["item_id"] == NEW_EMOTE
    assert state.pending_action["family"] == "emote"
    assert state.results == []
    third = route("Smooth Side Step Emote", state)
    assert third["intent"] == "review_title"
    assert third["item_id"] == NEW_EMOTE
    assert third["family"] == "emote"


def test_id_bearing_ambiguous_request_cannot_start_chain():
    state = seeded()
    for phrase in (
        "125628794109589 please do something",
        "make something 125628794109589",
    ):
        result = route(phrase, state)
        assert result["intent"] != "create_ideas", result
        assert result["item_id"] in (None, BACKGROUND)


def test_no_context_asks_for_item_not_old_creator():
    state = vc.ConversationState(user_id=1)
    result = route("I want to rename", state)
    assert result["intent"] == "clarify"
    assert "Which item" in result["question"]
    result = route("I want to rename 125628794109589", state)
    assert result["intent"] == "clarify"
    assert result["item_id"] == BACKGROUND


if __name__ == "__main__":
    test_explicit_id_with_and_without_family()
    test_proposed_name_is_review_not_launch_or_autopsy()
    test_ordinary_commands_not_hijacked_by_rename_parser()
    test_sticky_id_and_title_only_followup()
    test_new_explicit_item_overrides_pending_context()
    test_id_bearing_ambiguous_request_cannot_start_chain()
    test_no_context_asks_for_item_not_old_creator()
    print("PASS VANTA item-target and rename conversation contracts")
