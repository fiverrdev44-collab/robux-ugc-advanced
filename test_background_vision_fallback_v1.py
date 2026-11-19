"""Regressions for a real Rapture underwater scene when image vision fails.

No live model, Roblox endpoint, production database, or asset changes.
"""
import asyncio
from types import SimpleNamespace
from unittest import mock
import commands_ai
from background_intelligence import scene_phrase
from background_review import build_multi_pass_review, format_multi_pass_review

RAPTURE = (
    "BioShock Rapture-inspired underwater city observation room. "
    "Massive panoramic window overlooking mysterious blue underwater skyscrapers, "
    "dark teal Art Deco-style architecture, tiled floor, glowing amber lights, "
    "floating particles, and deep ocean atmosphere. "
    "Static Roblox Avatar Background (AssetType 92), with open foreground "
    "space for the avatar. Research same-category marketplace titles."
)


class FakeBot:
    def __init__(self):
        self.callbacks = {}
    def command(self, name=None, **kwargs):
        def decorate(cb):
            self.callbacks[name] = cb
            return cb
        return decorate


class FakeChannel:
    def __init__(self):
        self.messages = []
    async def send(self, msg=None, **kwargs):
        self.messages.append(msg)


class FakeAttachment:
    content_type = "image/jpeg"
    size = 6
    async def read(self):
        return b"offline"


def _context():
    ch = FakeChannel()
    return SimpleNamespace(
        message=SimpleNamespace(attachments=[FakeAttachment()]),
        send=ch.send, channel=ch, vanta_state=None,
    ), ch


def _run(notes=RAPTURE, provider=True):
    bot = FakeBot()
    commands_ai.register_ai_commands(bot)
    ctx, channel = _context()
    searches = []
    def search(query, family, *args):
        searches.append((query, family))
        return {"ok": False, "keyword": query, "error": "HTTP 429"}
    with (mock.patch.object(commands_ai, "is_available", return_value=provider),
          mock.patch.object(commands_ai, "analyze_image_for_ugc", return_value={}) as vis,
          mock.patch("convergence_live.verify_niche", side_effect=search),
          mock.patch("background_opportunities.lookup_background_opportunities",
                     return_value={"status": "unavailable", "angles": []}),
          mock.patch("category_creator_learning.lookup_creator_learning",
                     return_value={"status": "insufficient", "patterns": []}),
          mock.patch("gemini_brain._generate", return_value=None)):
        asyncio.run(bot.callbacks["background_analyze"](ctx, notes=notes))
    return channel.messages, searches, vis.call_count


def test_exact_rapture_image_failure_still_produces_research():
    assert scene_phrase({}, RAPTURE) == "underwater city"
    messages, searches, calls = _run()
    rendered = "\n".join(str(m) for m in messages)
    assert calls == 1, calls
    assert searches and searches[0] == ("underwater city", "backgrounds"), searches
    assert all(family == "backgrounds" for _, family in searches)
    assert len(searches) <= 2
    assert "creator-provided scene details only" in rendered
    assert "ROBLOX BACKGROUND SEARCH INTELLIGENCE" in rendered, rendered
    assert "creator_notes_only" in rendered
    assert "Could not identify grounded search terms" not in rendered
    assert "No verified live search evidence" not in rendered  # failed checks disclosed


def test_provider_offline_can_still_use_creator_notes():
    messages, searches, calls = _run(provider=False)
    assert calls == 0
    assert searches and searches[0][0] == "underwater city"
    assert "image-verified" in "\n".join(str(m) for m in messages)


def test_no_scene_does_not_claim_titles_or_search_market():
    messages, searches, calls = _run(notes="make it very viral and high CTR")
    assert calls == 1
    assert not searches
    joined = "\n".join(str(m) for m in messages)
    assert "lacked a grounded scene term" in joined
    assert "ROBLOX BACKGROUND SEARCH INTELLIGENCE" not in joined


def test_notes_only_review_discloses_visual_uncertainty():
    result = build_multi_pass_review(
        {"creator_notes_only": True, "visual_verification": "unavailable"},
        [{"bytes": b"offline", "mime": "image/jpeg"}], RAPTURE,
        {"ok": False, "search_checks": [], "top_competitors": []},
        None, lambda *args, **kwargs: None,
        {"status": "unavailable", "angles": []},
        {"status": "insufficient", "patterns": []},
    )
    assert result.get("passes", {}).get("initial_vision") == "creator_notes_only"
    assert result.get("passes", {}).get("independent_vision") == "unavailable"
    if result.get("status") == "ok":
        rendered = format_multi_pass_review(result)
        assert "creator_notes_only" in rendered
        assert result.get("winner", "").endswith("Background")


if __name__ == "__main__":
    test_exact_rapture_image_failure_still_produces_research()
    test_provider_offline_can_still_use_creator_notes()
    test_no_scene_does_not_claim_titles_or_search_market()
    test_notes_only_review_discloses_visual_uncertainty()
    print("PASS Rapture background image vision outage and creator-text fallback")
