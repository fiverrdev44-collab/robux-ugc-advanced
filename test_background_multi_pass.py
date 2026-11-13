"""Offline multi-pass background director tests: mocked models and marketplace."""
import asyncio
from types import SimpleNamespace
from unittest import mock
import background_review as br
import commands_ai
from test_background_visual_intelligence import VISION, Attachment, Channel, FakeBot

LIVE = {"ok": True, "category_correct": 2, "sampled_results": 3,
        "top_competitors": [
            {"name": "Moonlit Shrine Background", "asset_type_id": 92,
             "favorites": 20, "price": 200},
            {"name": "Blue Hat", "asset_type_id": 8,
             "favorites": 9999, "price": 1}]}
SECOND = {"mobile_readability_notes": "Portal may vanish in thumbnail",
          "avatar_clearance_notes": "The portal overlaps avatar center",
          "lighting_notes": "Bright moon against dark background"}


def test_four_passes_and_human_readable_output():
    vision_calls, text_calls = [], []
    def visual(images, instruction):
        vision_calls.append((len(images), instruction))
        return SECOND
    def text(prompt, **kwargs):
        text_calls.append(prompt)
        if len(text_calls) == 1:
            return '{"titles":["Glowing Moonlit Shrine Background", "Stone Path Shrine Background", "Moonlit Shrine Background", "Animated Moonlit Shrine Background", "Banana Rocket Shrine Background"]}'
        return ('{"winner":"Stone Path Shrine Background", '
                '"alternatives":["Glowing Moonlit Shrine Background"], '
                '"challenge":"The first title may hide the path detail.", '
                '"why_winner":"Stone path helps describe the foreground.", '
                '"photopea_steps":["Test avatar overlay at center using Photopea",'
                '"Gently balance Curves around the portal lighting",'
                '"Inspect the mobile preview crop before export"], '
                '"description":"A moonlit shrine scene with a stone path and glowing portal for your avatar."}')
    result = br.build_multi_pass_review(
        VISION, [{"bytes": b"PNG", "mime": "image/png"}],
        "moonlit shrine with portal", LIVE, visual, text)
    assert len(vision_calls) == 1
    assert len(text_calls) == 2
    assert result["passes"]["independent_vision"] == "ok"
    assert result["passes"]["creative"] == "ok"
    assert result["passes"]["skeptical_critic"] == "ok"
    assert result["winner"] == "Stone Path Shrine Background"
    titles = [row["title"] for row in result["scored"]]
    assert "Moonlit Shrine Background" not in titles
    assert "Animated Moonlit Shrine Background" not in titles
    assert "Banana Rocket Shrine Background" not in titles
    assert len(result["alternatives"]) == 2
    report = br.format_multi_pass_review(result)
    assert "Recommended title to test" in report
    assert "Competitor IMAGES were not available" in report
    assert "Photopea improvement steps" in report
    assert "CTR" in report


def test_unavailable_providers_fail_soft_without_false_evidence():
    def no_vision(*args):
        raise RuntimeError("rate limited")
    def no_text(*args, **kw):
        raise RuntimeError("provider unavailable")
    out = br.build_multi_pass_review(
        VISION, [], "", {"ok": False, "error": "HTTP 429"}, no_vision, no_text)
    assert out["passes"]["independent_vision"] == "unavailable"
    assert out["passes"]["creative"] == "unavailable"
    assert out["passes"]["skeptical_critic"] == "unavailable"
    assert not out["competitors"]
    report = br.format_multi_pass_review(out)
    assert "Competitor IMAGES were not available" in report
    assert "No simulated sales" in report


def test_prompt_injection_and_ip_claim_guards():
    titles = br._valid_titles([
        "Moonlit Shrine Background", "Animated Moonlit Shrine Background",
        "Ignore Instructions Shrine Background",
        "Oggy Shrine Background", "Super Viral Shrine Background",
        "Glowing Portal Shrine Background",
    ], VISION, "", LIVE)
    assert "Moonlit Shrine Background" not in titles
    assert not any("Ignore" in s or "Animated" in s for s in titles)
    assert "Glowing Portal Shrine Background" in titles
    assert br._safe_description(
        "Guaranteed viral sales at 99% CTR!", VISION, "") is None
    result = br.build_multi_pass_review(
        VISION, [], "Oggy background", LIVE,
        lambda *a: SECOND, lambda *a, **kw: None)
    assert result["ip_caution"]


def test_discord_command_keeps_one_market_search_and_two_visual_calls():
    bot = FakeBot()
    commands_ai.register_ai_commands(bot)
    channel = Channel()
    ctx = SimpleNamespace(
        message=SimpleNamespace(attachments=[Attachment()]),
        channel=channel, send=channel.send,
        vanta_state=SimpleNamespace(pending_chain=None))
    seen = {"market": 0, "vision": 0, "text": 0}
    def vision(*args):
        seen["vision"] += 1
        return dict(VISION) if seen["vision"] == 1 else dict(SECOND)
    def market(*args):
        seen["market"] += 1
        return LIVE
    def text(*args, **kwargs):
        seen["text"] += 1
        return None
    with mock.patch.object(commands_ai, "is_available", return_value=True), \
         mock.patch.object(commands_ai, "analyze_image_for_ugc", side_effect=vision), \
         mock.patch("convergence_live.verify_niche", side_effect=market), \
         mock.patch("gemini_brain._generate", side_effect=text):
        asyncio.run(bot.callbacks["background_analyze"](
            ctx, notes="moonlit shrine with portal"))
    assert seen == {"market": 1, "vision": 2, "text": 2}, seen
    assert any("MULTI-PASS BACKGROUND CREATIVE DIRECTOR" in (m or "")
               for m in channel.messages)
    assert ctx.vanta_state.pending_chain["family"] == "backgrounds"


if __name__ == "__main__":
    test_four_passes_and_human_readable_output()
    test_unavailable_providers_fail_soft_without_false_evidence()
    test_prompt_injection_and_ip_claim_guards()
    test_discord_command_keeps_one_market_search_and_two_visual_calls()
    print("PASS background multi-pass creative director")
