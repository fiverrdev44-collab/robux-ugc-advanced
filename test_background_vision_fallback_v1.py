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
        return b"\xff\xd8\xff\xe0offline-jpeg-stub"


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


NUKE = (
    "Counter-Strike 2 (CS2) Nuke Bombsite B. The attached image shows the iconic "
    "underground nuclear reactor facility, blue industrial walls, yellow machinery, "
    "illuminated glass flooring, central ramp and red B-site sign. Analyze the actual "
    "image and research Roblox Avatar Backgrounds (AssetType 92) using stored "
    "marketplace data and live marketplace verification. Investigate CS2, CSGO, "
    "Counter-Strike, Nuke, gaming map backgrounds, industrial environments and "
    "comparable successful gaming backgrounds including TF2 and GMod. Identify "
    "relevant top creators, measured favorite growth, early traction, competition, "
    "search visibility and naming patterns. Compare CS2 Nuke B Site Background, "
    "CS2 Nuke Background and CS2 Nuke Bombsite B Background against stronger alternatives."
)


def test_nuke_notes_survive_vision_failure():
    from background_intelligence import creator_named_subject, named_ip_caution
    from background_creative_titles import creative_lane_candidates, brand_sensitive_title
    assert scene_phrase({}, NUKE) == "nuclear reactor"
    assert creator_named_subject(NUKE) == "cs2 nuke"
    assert named_ip_caution({}, NUKE)
    assert brand_sensitive_title("CS2 Nuke Background", NUKE) == "cs2"
    assert "Nuclear Reactor Background" in creative_lane_candidates({}, NUKE)
    for provider in (True, False):
        messages, searches, calls = _run(notes=NUKE, provider=provider)
        rendered = "\n".join(str(m) for m in messages)
        assert searches == [("nuclear reactor", "backgrounds"), ("cs2 nuke", "backgrounds")], searches
        assert "ROBLOX BACKGROUND SEARCH INTELLIGENCE" in rendered, rendered
        assert "lacked a grounded scene term" not in rendered
        assert "creator-provided scene details only" in rendered
        assert "creator_notes_only" in rendered
        assert calls == int(provider)


if __name__ == "__main__":
    test_nuke_notes_survive_vision_failure()
    test_exact_rapture_image_failure_still_produces_research()
    test_provider_offline_can_still_use_creator_notes()
    test_no_scene_does_not_claim_titles_or_search_market()
    test_notes_only_review_discloses_visual_uncertainty()
    print("PASS Rapture background image vision outage and creator-text fallback")
