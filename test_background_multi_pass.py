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
SECOND = {"visual_summary": "Moonlit shrine scene with portal",
          "primary_subject": "portal", "subject_relation": "unknown",
          "mobile_readability_notes": "Portal may vanish in thumbnail",
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
    assert len(vision_calls) == 0  # No second artwork/aesthetic critique
    assert len(text_calls) == 2
    assert result["passes"]["independent_vision"] == "skipped"
    assert result["passes"]["creative"] == "ok"
    assert result["passes"]["skeptical_critic"] == "ok"
    assert result["winner"] == "Stone Path Shrine Background"
    titles = [row["title"] for row in result["scored"]]
    assert "Moonlit Shrine Background" not in titles
    assert "Animated Moonlit Shrine Background" not in titles
    assert "Banana Rocket Shrine Background" not in titles
    assert len(result["alternatives"]) == 2
    report = br.format_multi_pass_review(result)
    assert "Search-focused title recommendation" in report
    assert "Same-category competitor titles" in report
    assert "Photopea" not in report
    assert "/100" not in report
    assert "CTR" in report


def test_horror_office_titles_reject_awkward_detail_stacking():
    horror_vision = {
        "visual_summary": "Haunted security office with animatronic bear peeking through a window",
        "search_description": "Security Office Background",
        "distinctive_features": [
            "animatronic bear peeking at the office window",
            "glowing computer on metal desk",
            "yellow lockers against metal walls",
        ],
    }
    notes = "FNAF Freddy Fazbear haunted security office background"
    live = {"ok": True, "category_correct": 1,
            "top_competitors": [
                {"name": "FNAF Sister Location Office Background",
                 "asset_type_id": 92, "favorites": 15, "price": 200}]}
    rejected = [
        "Animatronic Face Frame Security Office Background",
        "Animatronic Face Security Office Background",
        "Haunted Metal Panel Security Office Background",
    ]
    assert br._valid_titles(rejected, horror_vision, notes, live) == []
    approved = br._valid_titles([
        "Animatronic Bear Security Office Background",
        "Haunted Security Office Background",
    ], horror_vision, notes, live)
    assert "Animatronic Bear Security Office Background" in approved
    prompts = []
    def model(prompt, **kwargs):
        prompts.append(prompt)
        if len(prompts) == 1:
            return '{"titles":["Animatronic Face Frame Security Office Background", "Haunted Metal Panel Security Office Background", "Animatronic Bear Security Office Background"]}'
        return ('{"winner":"Animatronic Face Frame Security Office Background",'
                '"alternatives":["Animatronic Bear Security Office Background"],'
                '"challenge":"Some competitor titles overlap on security office.",'
                '"why_winner":"Readable recognizable setting and scary character.",'
                '"description":"A haunted office where an animatronic bear peeks through the window."}')
    result = br.build_multi_pass_review(
        horror_vision, [], notes, live, lambda *a: {}, model)
    assert result["status"] == "ok", result
    assert result["winner"] not in rejected
    assert all(row["title"] not in rejected for row in result["scored"])
    assert "Animatronic Bear Security Office Background" in [
        row["title"] for row in result["scored"]]
    assert len(prompts) == 2
    assert "NATURAL Roblox product names" in prompts[0]
    assert "Reject unnatural" in prompts[1]


def test_unavailable_providers_fail_soft_without_false_evidence():
    def no_vision(*args):
        raise RuntimeError("rate limited")
    def no_text(*args, **kw):
        raise RuntimeError("provider unavailable")
    out = br.build_multi_pass_review(
        VISION, [], "", {"ok": False, "error": "HTTP 429"}, no_vision, no_text)
    assert out["passes"]["independent_vision"] == "skipped"
    assert out["passes"]["creative"] == "fallback_only"
    assert out["passes"]["skeptical_critic"] == "unavailable"
    assert not out["competitors"]
    report = br.format_multi_pass_review(out)
    assert "Same-category competitor titles" in report
    assert "Favorites ≠ sales" in report


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
    report = br.format_multi_pass_review(result)
    assert report.count("verify rights") == 1
    assert "Third-party IP caution" not in report
    assert "authorize protected" not in report


def test_explicit_oggy_name_is_a_real_candidate_not_blocked():
    vision = {
        "visual_summary": "Colorful sunny cartoon house with purple roof and garden",
        "search_description": "Cartoon house beside a green garden",
        "distinctive_features": [
            "bright purple roof", "green mailbox", "colorful striped awnings",
        ],
    }
    notes = ("Oggy and the Cockroaches-inspired sunny cartoon house. "
             "Purple roof, colorful awnings, green mailbox and bright garden.")
    from background_intelligence import (
        creator_named_subject, combine_background_live_checks,
    )
    assert creator_named_subject(notes) == "oggy"
    assert creator_named_subject("A sunny cartoon house") is None
    titles = br._valid_titles(
        br._editorial_candidates(vision, notes), vision, notes, None)
    assert "Oggy's Sunny Cartoon House Background" in titles, titles
    assert "Oggy Cartoon House Background" in titles, titles
    prompts = []
    def model(prompt, **kwargs):
        prompts.append(prompt)
        if len(prompts) == 1:
            return ('{"titles":["Oggys Sunny Cartoon House Background",'
                    '"Sunny Cartoon House Background",'
                    '"Colorful Cartoon House Background"]}')
        return ('{"winner":"Oggy Cartoon House Background",'
                '"alternatives":["Oggys Sunny Cartoon House Background",'
                '"Sunny Cartoon House Background"],'
                '"challenge":"A named identity is creator-supplied, not visually proven.",'
                '"why_winner":"Recognizable named scene and concise words.",'
                '"description":"A cheerful cartoon house surrounded by a bright garden."}')
    live = combine_background_live_checks([
        {"ok": True, "keyword": "cartoon house",
         "search_keyword": "cartoon house background",
         "category_correct": 2, "sampled_results": 30, "pages": 1,
         "top_competitors": [
             {"name": "Cartoon City Background", "asset_type_id": 92,
              "favorites": 40}]},
        {"ok": True, "keyword": "oggy", "search_keyword": "oggy background",
         "category_correct": 1, "sampled_results": 30, "pages": 1,
         "top_competitors": [
             {"name": "Oggy Cartoon Garden Background", "asset_type_id": 92,
              "favorites": 12},
             {"name": "Oggy Hat", "asset_type_id": 8, "favorites": 9999}]}
    ])
    review = br.build_multi_pass_review(
        vision, [], notes, live, lambda *_: {}, model)
    assert review["status"] == "ok", review
    assert "Oggy" in review["winner"], review
    assert "Oggy's Sunny Cartoon House Background" in [
        row["title"] for row in review["scored"]], review
    assert "Oggy Hat" not in [x["name"] for x in review["competitors"]]
    assert len(prompts) == 2
    assert "creator_named_subject" in prompts[0]
    report = br.format_multi_pass_review(review)
    assert "cartoon house background" in report
    assert "oggy background" in report
    assert "correct-category" in report
    assert "verify rights" in report
    assert "Oggy's Sunny Cartoon House Background" in report


def test_failing_named_live_search_never_claims_zero_competitors():
    from background_intelligence import combine_background_live_checks
    merged = combine_background_live_checks([
        {"ok": False, "keyword": "oggy",
         "error": "rate limited (429)"},
        {"ok": True, "keyword": "cartoon house",
         "category_correct": 0, "sampled_results": 7, "pages": 1,
         "top_competitors": []},
    ])
    assert merged["ok"] is True
    assert merged["search_checks"][0]["status"] == "unavailable"
    assert merged["search_checks"][0]["asset_type_92_matches"] is None
    assert merged["search_checks"][1]["asset_type_92_matches"] == 0
    assert merged["top_competitors"] == []


def test_discord_command_checks_scene_and_explicit_oggy_search():
    bot = FakeBot()
    commands_ai.register_ai_commands(bot)
    channel = Channel()
    ctx = SimpleNamespace(
        message=SimpleNamespace(attachments=[Attachment()]),
        channel=channel, send=channel.send,
        vanta_state=SimpleNamespace(pending_chain=None))
    requested = []
    def vision(*args, **kwargs):
        return {
            "visual_summary": "Sunny cartoon house with purple roof",
            "search_description": "Cartoon house with bright garden",
            "distinctive_features": ["purple roof", "colorful awnings"],
            "primary_subject": "house", "subject_relation": "unknown",
        }
    def market(keyword, family, limit, max_pages, timeout, cache):
        requested.append((keyword, family, limit, max_pages, cache))
        return {
            "ok": True, "keyword": keyword,
            "search_keyword": keyword + " background",
            "pages": 1, "category_correct": 1, "sampled_results": 8,
            "top_competitors": [
                {"name": keyword.title() + " Background",
                 "asset_type_id": 92, "favorites": 5}]
        }
    with mock.patch.object(commands_ai, "is_available", return_value=True), \
         mock.patch.object(commands_ai, "analyze_image_for_ugc",
                           side_effect=vision), \
         mock.patch("convergence_live.verify_niche", side_effect=market), \
         mock.patch("gemini_brain._generate", return_value=None):
        asyncio.run(bot.callbacks["background_analyze"](
            ctx, notes="Oggy sunny cartoon house and purple roof"))
    assert len(requested) == 2, requested
    assert requested[0][0] != requested[1][0]
    assert requested[1] == ("oggy", "backgrounds", 30, 1, True)
    assert all(call[1:] == ("backgrounds", 30, 1, True)
               for call in requested)
    body = "\n".join(channel.messages)
    assert "Live AssetType 92 marketplace checks" in body
    assert "oggy background" in body
    assert "correct-category" in body
    assert "Oggy" in body


def test_discord_command_keeps_one_market_search_and_two_visual_calls():
    bot = FakeBot()
    commands_ai.register_ai_commands(bot)
    channel = Channel()
    ctx = SimpleNamespace(
        message=SimpleNamespace(attachments=[Attachment()]),
        channel=channel, send=channel.send,
        vanta_state=SimpleNamespace(pending_chain=None))
    seen = {"market": 0, "vision": 0, "text": 0}
    def vision(*args, **kwargs):
        seen["vision"] += 1
        if seen["vision"] == 2:
            assert kwargs.get("subject_check") is True
            assert args[1] == ""
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
    assert any("Image evidence check" in (m or "")
               for m in channel.messages)
    assert any("ROBLOX BACKGROUND SEARCH INTELLIGENCE" in (m or "")
               for m in channel.messages)
    assert not any("Photopea" in (m or "") or
                   "Avatar clearance" in (m or "") for m in channel.messages)
    assert not any("/100" in (m or "") for m in channel.messages)


if __name__ == "__main__":
    test_four_passes_and_human_readable_output()
    test_horror_office_titles_reject_awkward_detail_stacking()
    test_unavailable_providers_fail_soft_without_false_evidence()
    test_prompt_injection_and_ip_claim_guards()
    test_explicit_oggy_name_is_a_real_candidate_not_blocked()
    test_failing_named_live_search_never_claims_zero_competitors()
    test_discord_command_checks_scene_and_explicit_oggy_search()
    test_discord_command_keeps_one_market_search_and_two_visual_calls()
    print("PASS background multi-pass creative director")
