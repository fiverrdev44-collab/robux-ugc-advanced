"""Offline natural-language title feedback regressions; no network."""
import asyncio
from types import SimpleNamespace
from unittest import mock

import vanta_conversation as vc
import title_feedback as tf


def test_literal_proposals_and_no_false_rename():
    phrases = {
        'what if i name this item as "Animatronic Bear Security Office Background"?':
            "Animatronic Bear Security Office Background",
        "should i call my emote Smooth 360 Flip?": "Smooth 360 Flip",
        "what do you think of the title Cute Kitty Fluffy Beanie?":
            "Cute Kitty Fluffy Beanie",
        "rate the title Sorcerer Hat": "Sorcerer Hat",
        "is Glowing Blue Office Background a good title?":
            "Glowing Blue Office Background",
        "what about 'Moonlit Shrine Background'?": "Moonlit Shrine Background",
    }
    for phrase, expected in phrases.items():
        assert tf.proposed_title(phrase) == expected, (phrase, tf.proposed_title(phrase))
    for phrase in ("rename viral russian", "change title of my old item",
                   "make a better name", "what if i call it?", "check item 123456789"):
        assert tf.proposed_title(phrase) is None, phrase


def test_user_context_router_prevents_wrong_command():
    state = vc.ConversationState(user_id=1)
    state.last_item_id = 121930221694467
    state.last_family = "backgrounds"
    name = "Animatronic Bear Security Office Background"
    phrase = "what if i name this item as " + name
    r = vc.classify_intent(phrase, state=state, use_ai=False)
    assert r["intent"] == "review_title" and r["item_id"] == state.last_item_id
    assert r["concept"] == name and r["family"] == "backgrounds"
    with mock.patch.object(vc, "_planner_ai", side_effect=AssertionError("no planner")):
        parsed = asyncio.run(vc.plan_message(phrase, False, state))
    assert parsed == r
    explicit = vc.classify_intent("should i call my emote Smooth 360 Flip",
                                  state=state, use_ai=False)
    assert explicit["family"] == "emote"
    # Switching from a remembered emote to a new background MUST NOT
    # inherit the old asset ID or compare against emote listings.
    state.last_family = "emote"
    state.last_item_id = 92364796546749
    incoming = ("What if I name this background "
                "FNAF Freddy Fazebear Haunted Security Office Background")
    next_route = vc.classify_intent(incoming, state=state, use_ai=False)
    assert next_route["intent"] == "review_title"
    assert next_route["family"] == "backgrounds"
    assert next_route["item_id"] is None
    planned = asyncio.run(vc.plan_message(incoming, False, state))
    assert planned["item_id"] is None and planned["family"] == "backgrounds"
    assert vc.classify_intent("rename viral russian", state=state,
                              use_ai=False)["intent"] != "review_title"


class FakeCursor:
    def __init__(self):
        self.calls = []
    def execute(self, sql, values):
        self.calls.append((sql, values))
        assert not any(w in sql.upper() for w in ("INSERT ", "UPDATE ", "DELETE "))
    def close(self):
        pass
    def fetchone(self):
        return (44, "Old Background", 92)
    def fetchall(self):
        return [(1, "Office Security Background", 45),
                (2, "Animatronic Bear Office Background", 20),
                (3, "Other Background", 200)]


class FakeConn:
    def __init__(self):
        self.cursor_instance = FakeCursor()
        self.closed = False
    def cursor(self):
        return self.cursor_instance
    def close(self):
        self.closed = True


def test_background_evidence_is_asset_type_scoped():
    conn = FakeConn()
    data = tf._evidence("Animatronic Bear Office Background", "backgrounds",
                        item_id=44, db_factory=lambda: conn)
    assert conn.closed
    assert data["family"] == "backgrounds", data
    assert len(conn.cursor_instance.calls) == 2
    sql, values = conn.cursor_instance.calls[1]
    assert "asset_type_id = ANY(%s)" in sql
    assert values[0] == [92], values
    assert len(data["peers"]) >= 1


def test_stale_emote_context_never_changes_background_category():
    class WrongItemCursor(FakeCursor):
        def fetchone(self):
            return (92364796546749, "Smooth Flip Emote", 61)
        def fetchall(self):
            return [(1, "FNAF Bonnie Security Office Background", 12),
                    (2, "Freddy Office Background", 8)]
    class WrongItemConn(FakeConn):
        def __init__(self):
            self.cursor_instance = WrongItemCursor()
            self.closed = False
    conn = WrongItemConn()
    title = "FNAF Freddy Fazebear Haunted Security Office Background"
    data = tf._evidence(title, "backgrounds", item_id=92364796546749,
                        db_factory=lambda: conn)
    assert data["family"] == "backgrounds", data
    assert data["item"] is None
    assert data["mismatched_item"] is True
    assert conn.cursor_instance.calls[1][1][0] == [92]
    report = tf.review_proposal(
        title, family="backgrounds", item_id=92364796546749,
        db_factory=lambda: WrongItemConn(),
        model_fn=lambda *args, **kwargs: None,
        live_fn=lambda *args: {"ok": False, "error": "test offline"})
    assert "Category: backgrounds" in report
    assert "Context correction" in report
    assert "Fazbear" in report
    assert "Smooth Flip Emote" not in report
    assert "FNAF Bonnie Security Office Background" in report


def test_model_feedback_no_mutation_and_no_scores():
    conn = FakeConn()
    def model(prompt, **kwargs):
        assert '"family": "backgrounds"' in prompt
        return ('{"verdict":"Good recognizable scene hook",'
                '"strength":"Office tells buyers the setting",'
                '"weakness":"Bear-specific terms may narrow reach",'
                '"alternative":"Creepy Bear Security Office Background"}')
    report = tf.review_proposal("Animatronic Bear Office Background",
                                family="backgrounds", item_id=44,
                                db_factory=lambda: conn, model_fn=model,
                                live_fn=lambda *args: {"ok": False, "error": "test offline"})
    assert "Good recognizable scene hook" in report
    assert "Creepy Bear Security Office Background" in report
    assert "Read-only" in report
    assert "/100" not in report
    assert all("asset_type_id" in q if i == 1 else "WHERE id = %s" in q
               for i, (q, _) in enumerate(conn.cursor_instance.calls))


def test_optional_item_and_unavailable_data_fail_safely():
    def bad_db():
        raise RuntimeError("db offline")
    report = tf.review_proposal("Moonlit Shrine Background",
                                db_factory=bad_db, model_fn=lambda *a, **kw: None,
                                live_fn=lambda *args: {"ok": False, "error": "test offline"})
    assert "evidence unavailable" in report
    assert "ranking" in report
    assert "No item changed" in report
    assert not tf.proposed_title("what if i call it?")


def test_one_live_background_query_with_category_isolation():
    calls = []
    def fake_live(keyword, family, limit, pages, timeout, cache):
        calls.append((keyword, family, limit, pages, timeout, cache))
        return {
            "ok": True, "search_keyword": "security office background",
            "sampled_results": 30, "category_correct": 2,
            "observed_at": "2026-11-13T10:00:00+00:00",
            "top_competitors": [
                {"name": "FNAF Bonnie Security Office Background",
                 "asset_type_id": 92, "favorites": 5, "price": 200},
                {"name": "Security Stance Emote", "asset_type_id": 61,
                 "favorites": 12000, "price": 100},
            ],
        }
    conn = FakeConn()
    title = "Haunted Security Office Background"
    report = tf.review_proposal(
        title, family="backgrounds", db_factory=lambda: conn,
        model_fn=lambda *args, **kwargs: None, live_fn=fake_live)
    assert calls == [("security office", "backgrounds", 30, 1, 12, True)], calls
    assert "Live Roblox Marketplace" in report
    assert "FNAF Bonnie Security Office Background" in report
    assert "Security Stance Emote" not in report
    assert "2 background(s) in 30 sampled results" in report
    assert "/100" not in report


def test_live_unavailable_still_reports_db_without_inventing_market():
    calls = []
    def failed(*args):
        calls.append(args)
        return {"ok": False, "error": "rate limited", "deferred": True}
    report = tf.review_proposal(
        "Blue Security Office Background", family="backgrounds",
        db_factory=lambda: FakeConn(), model_fn=lambda *args, **kwargs: None,
        live_fn=failed)
    assert len(calls) == 1
    assert "Live Marketplace check unavailable:** rate limited" in report
    assert "No exact name in sampled results" in report
    assert "ranking" in report


def test_other_categories_do_not_call_background_live_search():
    def forbidden(*args):
        raise AssertionError("Non-background should not call live")
    report = tf.review_proposal(
        "Smooth Flip Emote", family="emote", item_id=None,
        db_factory=lambda: FakeConn(), model_fn=lambda *args, **kwargs: None,
        live_fn=forbidden)
    assert "Live Roblox Marketplace" not in report
    assert "Category: emote" in report


def test_dispatch_readonly_authorized_and_context():
    state = vc.ConversationState(user_id=1)
    state.last_family = "backgrounds"
    delivered = []
    class Channel:
        async def send(self, text, **kwargs):
            delivered.append(text)
    message = SimpleNamespace(
        author=SimpleNamespace(id=1),
        channel=Channel(),
        content="what if i name this item as Moonlit Shrine Background")
    route = vc._intent("review_title", concept="Moonlit Shrine Background",
                       family="backgrounds")
    with mock.patch("command_security.require_authorized") as auth, \
         mock.patch("title_feedback.review_proposal", return_value="READ ONLY TEST") as reviewer:
        asyncio.run(vc._run_registry(None, message, route, state))
    auth.assert_called_once_with("autopsy", 1)
    reviewer.assert_called_once()
    assert delivered == ["READ ONLY TEST"]
    assert state.last_concept == "Moonlit Shrine Background"
    assert state.last_intent == "review_title"


if __name__ == "__main__":
    test_literal_proposals_and_no_false_rename()
    test_user_context_router_prevents_wrong_command()
    test_background_evidence_is_asset_type_scoped()
    test_stale_emote_context_never_changes_background_category()
    test_model_feedback_no_mutation_and_no_scores()
    test_optional_item_and_unavailable_data_fail_safely()
    test_one_live_background_query_with_category_isolation()
    test_live_unavailable_still_reports_db_without_inventing_market()
    test_other_categories_do_not_call_background_live_search()
    test_dispatch_readonly_authorized_and_context()
    print("PASS VANTA natural-language proposed title reviews")
