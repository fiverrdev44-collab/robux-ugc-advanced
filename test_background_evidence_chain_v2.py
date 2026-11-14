"""Regression tests for background evidence provenance and optional CHAIN handoff.

Offline only: no Roblox requests, AI provider calls, or production DB writes.
"""
import asyncio
from types import SimpleNamespace
from unittest import mock

from background_intelligence import (
    verified_background_competitors, combine_background_live_checks,
)
from background_review import format_multi_pass_review
import commands_ai


def test_verified_competitor_provenance():
    rows = verified_background_competitors({
        "ok": True, "top_competitors": [
            {"name": "Sunny House Background", "asset_type_id": 92,
             "asset_id": 12345, "creator_type": "Group", "creator_id": 789,
             "creator": "Garden Studio", "favorites": 14,
             "favorites_known": True, "price": 80},
            {"name": "Not A Background", "asset_type_id": 8,
             "asset_id": 99999},
            {"name": "Unnamed IDs Background", "asset_type_id": 92,
             "asset_id": "invalid", "creator_id": "invalid",
             "favorites": None, "favorites_known": False},
        ]}, limit=5)
    assert len(rows) == 2
    assert rows[0]["asset_id"] == 12345
    assert rows[0]["creator_id"] == 789
    assert rows[1]["asset_id"] is None
    assert rows[1]["creator_id"] is None


def test_live_check_reports_metadata_and_rejects_wrong_category():
    output = combine_background_live_checks([
        {"ok": True, "keyword": "house", "sampled_results": 3,
         "category_correct": 1, "pages": 1,
         "observed_at": "2026-11-14T08:00:00+00:00",
         "top_competitors": [
             {"name": "Sunny House Background", "asset_type_id": 92,
              "asset_id": 12345, "creator_type": "Group", "creator_id": 789,
              "favorites": 14, "favorites_known": True},
             {"name": "Hat", "asset_type_id": 8, "asset_id": 555},
         ]},
        {"ok": False, "keyword": "oggy", "error": "HTTP 429"},
    ])
    assert len(output["search_checks"]) == 2
    assert output["search_checks"][0]["observed_at"].startswith("2026")
    assert output["search_checks"][1]["status"] == "unavailable"
    assert len(output["top_competitors"]) == 1

    report = format_multi_pass_review({
        "status": "ok", "winner": "Sunny House Background",
        "alternatives": ["Cartoon House Background"],
        "description": "A sunny cartoon house with a garden.",
        "passes": {"initial_vision": "ok"},
        "competitors": verified_background_competitors(output),
        "live_checks": output["search_checks"],
    })
    assert "https://www.roblox.com/catalog/12345" in report
    assert "Group 789" in report
    assert "14 favorites" in report
    assert "observed 2026" in report
    assert "oggy: unavailable (HTTP 429)" in report


class FakeBot:
    def __init__(self):
        self.callbacks = {}
    def command(self, name=None, **kwargs):
        def decorate(callback):
            self.callbacks[name] = callback
            return callback
        return decorate


class FakeChannel:
    def __init__(self):
        self.messages = []
    async def send(self, msg=None, **kwargs):
        self.messages.append(msg)


class FakeAttachment:
    content_type = "image/png"
    size = 6
    async def read(self):
        return b"sample"


def test_background_handoff_requires_conversation_and_review():
    bot = FakeBot()
    commands_ai.register_ai_commands(bot)
    vision = {
        "visual_summary": "Sunny cartoon house with a purple roof",
        "search_description": "Sunny cartoon house",
        "distinctive_features": ["purple roof", "green mailbox"],
        "visual_colors": ["purple", "green"],
        "visual_style": ["cartoon"],
    }
    for allowed in (True, False):
        channel = FakeChannel()
        state = SimpleNamespace(pending_chain=None) if allowed else None
        ctx = SimpleNamespace(
            message=SimpleNamespace(attachments=[FakeAttachment()]),
            channel=channel, send=channel.send, vanta_state=state,
        )
        with mock.patch.object(commands_ai, "is_available", return_value=True), \
             mock.patch.object(commands_ai, "analyze_image_for_ugc", return_value=vision), \
             mock.patch("convergence_live.verify_niche", return_value={"ok": False, "error": "HTTP 429"}), \
             mock.patch("background_opportunities.lookup_background_opportunities", return_value={"status": "unavailable"}), \
             mock.patch("category_creator_learning.lookup_creator_learning", return_value={"status": "insufficient"}), \
             mock.patch("background_review.build_multi_pass_review", return_value={"status": "ok", "winner": "Sunny Cartoon House Background"}), \
             mock.patch("background_review.format_multi_pass_review", return_value="Background review"):
            asyncio.run(bot.callbacks["background_analyze"](
                ctx, notes="sunny cartoon house with purple roof"))
        if allowed:
            assert state.pending_chain["family"] == "backgrounds"
            assert "cartoon house" in state.pending_chain["concept"].lower()
            assert any("Reply" in (msg or "") and "yes" in msg for msg in channel.messages)
        else:
            assert not any("Reply" in (msg or "") for msg in channel.messages)


if __name__ == "__main__":
    test_verified_competitor_provenance()
    test_live_check_reports_metadata_and_rejects_wrong_category()
    test_background_handoff_requires_conversation_and_review()
    print("PASS background evidence and CHAIN handoff")
