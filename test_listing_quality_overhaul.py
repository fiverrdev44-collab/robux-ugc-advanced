"""Command-path fixture checks with fake providers, catalog transport and sales DB."""
import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import commands_ai
import commands_advanced
import commands_sales
import convergence_live
import desc_forge
import vanta_conversation as vc
from background_intelligence import title_sample_overlap
from background_review import build_multi_pass_review
from description_quality import finalize_description
from test_background_market_quality import FakeScheduler
from test_background_visual_intelligence import Attachment, Channel, FakeBot
from test_background_grounding import horror_first
from background_grounding import reconcile_background_vision

SCENES = (
    (
        "GMod Flatgrass-inspired map. Blue sky over a huge open grassy field with distant hills and a curved brick structure.",
        "Open grassy field with distant hills under a blue sky.",
        ["curved brick structure", "distant hills"],
        "open grassland",
        "Grassland",
    ),
    (
        "BioShock-inspired Art Deco observation room with a panoramic window looking out over an underwater city.",
        "An Art Deco observation room overlooking an underwater city through a panoramic window.",
        ["panoramic window", "tiled floor", "amber lights"],
        "underwater city",
        "Underwater City",
    ),
    (
        "Oggy-inspired scene. Garden with a green mailbox in front of a sunny cartoon house with a purple roof and striped awnings.",
        "A sunny cartoon house with a purple roof, striped awnings and a garden mailbox.",
        ["green mailbox", "purple roof", "striped awnings"],
        "cartoon house",
        "House",
    ),
    (
        "Red carpet on the runway next to a presidential-style aircraft at a ceremonial arrival with a vehicle and guards.",
        "A presidential-style aircraft at a ceremonial arrival with a red carpet.",
        ["red carpet", "guards", "vehicle"],
        "aircraft arrival",
        "Jet Arrival",
    ),
)

UNDERWATER_LISTINGS = [
    ("Chill Gaming Room Background", 92, 150),
    ("Art Deco Bedroom Background", 92, 140),
    ("Panoramic Mountain Window Background", 92, 130),
    ("Blue Undersea Skyline Background", 92, 0),
    ("Underwater City Emote", 61, 300),
]


def test_background_callback_uses_scene_anchor_and_complete_bounded_sample():
    for notes, summary, features, anchor, wanted in SCENES:
        bot = FakeBot()
        commands_ai.register_ai_commands(bot)
        channel = Channel()
        ctx = SimpleNamespace(message=SimpleNamespace(attachments=[Attachment()]),
                              send=channel.send)
        vision = {"visual_summary": summary, "search_description": summary,
                  "distinctive_features": features}
        rows = UNDERWATER_LISTINGS if anchor == "underwater city" else []
        scheduler = FakeScheduler({"data": [
            {"name": name, "assetType": category, "favoriteCount": favorites, "id": index}
            for index, (name, category, favorites) in enumerate(rows, 1)
        ]})
        convergence_live.clear_cache()
        with patch.object(commands_ai, "is_available", return_value=True), \
             patch.object(commands_ai, "analyze_image_for_ugc", return_value=vision) as visual, \
             patch.object(convergence_live, "_get_scheduler", return_value=scheduler), \
             patch("background_opportunities.lookup_background_opportunities", return_value={}), \
             patch("category_creator_learning.lookup_creator_learning", return_value={}), \
             patch("gemini_brain._generate", return_value=None) as text:
            asyncio.run(bot.callbacks["background_analyze"](ctx, notes=notes))
        body = "\n".join(channel.messages)
        winner = body.split("**Search-focused title recommendation**\n• **")[1].split("**")[0]
        assert wanted in winner, (anchor, winner)
        assert summary in body
        assert "Perfect for your" not in body
        assert all(name not in winner for name in ("GMod", "BioShock", "Oggy", "Guards", "Mailbox"))
        assert scheduler.calls[0][2]["Keyword"] == anchor + " background"
        assert len(scheduler.calls) <= 2
        assert visual.call_count == 2 and text.call_count == 1
        if rows:
            assert "Blue Undersea Skyline Background" in body
            assert "0 favorites" in body
            assert all(name not in body for name, _, _ in rows if "Undersea" not in name)
        else:
            assert "No scene-relevant comparable titles" in body
            assert "Unknown:" in body
        alternatives = [line.split(": ", 1)[1] for line in body.splitlines()
                        if line.startswith("• Alternate ")]
        assert len(alternatives) == 2, (anchor, alternatives)
        for first, second in ((winner, alternatives[0]), (winner, alternatives[1]), alternatives):
            assert title_sample_overlap(first, [{"name": second}])["ratio"] < .70


def test_vision_outage_uses_scene_notes_without_importing_instructions():
    notes = ("Please write a title. A sunny cartoon house with a purple roof and striped awnings. "
             "Generate names about a castle.")
    bot = FakeBot()
    commands_ai.register_ai_commands(bot)
    channel = Channel()
    ctx = SimpleNamespace(message=SimpleNamespace(attachments=[Attachment()]),
                          send=channel.send)
    with patch.object(commands_ai, "is_available", return_value=False), \
         patch.object(commands_ai, "analyze_image_for_ugc") as image, \
         patch("convergence_live.verify_niche", return_value={"ok": True}) as search, \
         patch("background_opportunities.lookup_background_opportunities", return_value={}), \
         patch("category_creator_learning.lookup_creator_learning", return_value={}), \
         patch("gemini_brain._generate", return_value=None):
        asyncio.run(bot.callbacks["background_analyze"](ctx, notes=notes))
    image.assert_not_called()
    search.assert_called_once_with("cartoon house", "backgrounds", 30, 1, 12, True)
    body = "\n".join(channel.messages)
    assert "A sunny cartoon house with a purple roof and striped awnings." in body
    assert "without image-based" in body or "Continuing with your written scene description" in body
    assert "Castle Background" not in body and "Please write a title." not in body


def test_ambiguous_horror_subject_and_generated_placement_do_not_leak_into_copy():
    first = horror_first()
    independent = {"visual_summary": "A bear at a window in a dark security office.",
                   "primary_subject": "bear", "subject_relation": "window"}
    notes = "FNAF dark security office with a bear peeking through a window."
    verification = reconcile_background_vision(first, independent, notes)
    assert verification["relation_conflict"]
    critic = Mock(side_effect=[
        {"titles": ["Haunted Security Office Background", "Bear Window Security Office Background"]},
        {"winner": "Haunted Security Office Background",
         "description": "A bear peers through the window of a haunted security office.",
         "why_winner": "Guaranteed 99% CTR"},
    ])
    result = build_multi_pass_review(verification["vision"], [], notes, None, None, critic)
    assert "Security Office" in result["winner"]
    assert "window" not in result["description"].lower()
    assert "poster" not in result["description"].lower()
    assert "CTR" not in result["why_winner"]
    assert len(result["alternatives"]) == 2


def test_provider_outage_preserves_full_emote_and_accessory_facts():
    emote = "A quick shoulder shimmy followed by a left-foot kick and a small hop."
    clip = "A black crescent hair clip with tiny silver stars and scalloped edges."
    model = Mock(side_effect=RuntimeError("provider unavailable"))
    with patch("gemini_brain._generate", model):
        copy = desc_forge._generate_description(clip, "hair", [], {})
    assert copy == clip
    model.assert_called_once()
    outcome = finalize_description("Perfect for your avatar.", emote, "emotes", "Shoulder Shimmy")
    assert outcome["text"] == emote
    with patch.object(desc_forge, "_fetch_description_cohorts", return_value=([], {})), \
         patch("gemini_brain._generate") as writer:
        report = desc_forge.format_forge(desc_forge.forge_description(clip, "hair"))
    assert "No usable competitor descriptions" in report[0]
    assert clip in "\n".join(report)
    writer.assert_not_called()


def test_registered_converge_reports_an_empty_scan():
    bot = FakeBot()
    commands_advanced.register_advanced_commands(bot, Mock())
    channel = Channel()
    ctx = SimpleNamespace(send=channel.send)
    with patch("convergence_engine.scan_all_families", return_value={"backgrounds": []}):
        asyncio.run(bot.callbacks["converge"](ctx, family="all_families"))
    assert channel.messages[-1] == "No qualified leads in the available category evidence."


def test_malformed_catalog_response_is_distinct_from_an_empty_catalog_sample():
    for payload, expected_ok in (({"data": []}, True), ({"errors": []}, False)):
        scheduler = FakeScheduler(payload)
        with patch.object(convergence_live, "_get_scheduler", return_value=scheduler):
            result = convergence_live.verify_niche("aircraft arrival", "backgrounds", use_cache=False)
        assert result["ok"] is expected_ok
        if not expected_ok:
            assert result["error"] == "invalid catalog response"


def test_registered_sales_callback_discloses_partial_history_and_exact_period():
    for utterance, days, offset in (
        ("Sales 365 days", 365, 0),
        ("show my sales for the past 12 months", 365, 0),
        ("last year", 365, 0),
        ("show my sales last 30 days", 30, 0),
        ("sales yesterday", 1, 1),
        ("and yesterday", 1, 1),
    ):
        registrations = FakeBot()
        commands_sales.register_sales_commands(registrations, Mock())
        command = SimpleNamespace(callback=registrations.callbacks["sales_report"])
        bot = Mock()
        bot.get_command.return_value = command
        progress = SimpleNamespace(edit=AsyncMock())
        channel = SimpleNamespace(send=AsyncMock(return_value=progress), id=9)
        message = SimpleNamespace(channel=channel, content=utterance, author=SimpleNamespace(id=1))
        state = vc.ConversationState(user_id=1)
        state.last_intent = "check_sales"
        data = {"total_units": int(not offset), "total_robux": int(not offset) * 5,
                "top_items": [], "daily": [], "coverage": {"note": "missing source events"},
                "window": {"start": date(2025, 11, 23), "end_exclusive": date(2026, 11, 23)}}
        with patch.object(vc, "_v2_enabled", return_value=True), \
             patch.object(vc, "is_owner", return_value=True), \
             patch("sales_listener.sales_summary", return_value=data) as sales:
            route = asyncio.run(vc.plan_message(utterance, False, state))
            assert route["intent"] == "check_sales", (utterance, route)
            if utterance == "Sales 365 days":
                route["days"] = 30  # Simulate a planner-supplied default.
            asyncio.run(vc._run_registry(bot, message, route, state))
        sales.assert_called_once_with(days, offset)
        report = progress.edit.call_args.kwargs["content"]
        assert "Historical Discord sales may be missing" in report
        if offset:
            assert "No imported sales records for yesterday (UTC)" in report
        else:
            assert f"last {days} days" in report and "missing source events" in report


if __name__ == "__main__":
    test_background_callback_uses_scene_anchor_and_complete_bounded_sample()
    test_vision_outage_uses_scene_notes_without_importing_instructions()
    test_ambiguous_horror_subject_and_generated_placement_do_not_leak_into_copy()
    test_provider_outage_preserves_full_emote_and_accessory_facts()
    test_registered_converge_reports_an_empty_scan()
    test_malformed_catalog_response_is_distinct_from_an_empty_catalog_sample()
    test_registered_sales_callback_discloses_partial_history_and_exact_period()
    print("PASS grounded listing quality and imported sales command paths")
