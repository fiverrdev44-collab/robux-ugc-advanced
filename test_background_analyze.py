"""Background analyzer regression tests using synthetic images and mocks."""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import background_analyze as ba
import command_security as cs


def _vision():
    return {
        "visual_summary": "A rounded cartoon house on a quiet street with an orange roof.",
        "background_setting": "suburban street",
        "background_landmarks": ["rounded house", "orange roof"],
        "background_lighting": "warm afternoon light",
        "background_palette": ["orange", "blue", "cream"],
        "background_atmosphere": "playful cartoon",
        "background_composition": "house centered, clear ground and avatar space",
        "visual_colors": ["orange", "blue"],
        "visual_style": ["cartoon"],
        "visual_mood": ["playful"],
        "distinctive_features": ["rounded windows"],
        "search_description": "cartoon house background",
        "visual_title_seed": "Toon House",
        "composition_notes": "readable on mobile and desktop",
    }


def _verification(status="verified"):
    return {
        "verification_status": status,
        "verified_setting": "suburban street",
        "verified_landmarks": ["rounded house"],
        "verified_colors": ["orange", "blue"],
        "verified_lighting": "warm afternoon",
        "verified_avatar_space": "centre",
        "discrepancies": [],
        "visual_summary": "Independent pass confirms the cartoon house.",
    }


def _live(ok=True, competitors=None, error="", retry_after=None):
    if not ok:
        return {"ok": False, "error": error or "rate limited",
                "retry_after": retry_after, "status": "rate_limited"}
    comps = competitors if competitors is not None else [{
        "id": 111222333,
        "name": "Toon House Background",
        "creator": "toon_creator",
        "favorites": 42,
        "price": 100,
        "created_at": "2026-11-01",
        "asset_type_id": 92,
        "related": True,
    }]
    return {"ok": True, "sampled_results": 12, "pages": 1,
            "category_correct": 12, "exact_title_matches": 1,
            "competitors": comps, "top_competitors": comps,
            "verification_timestamp": "2026-11-14T09:00:00+00:00",
            "status": "ok"}


def _analyze(notes, vision_side_effect=None, live_side_effect=None):
    with mock.patch.object(ba.ab, "validate_image",
                           return_value={"ok": True, "format": "PNG",
                                         "width": 2560, "height": 1440,
                                         "alpha": False, "srgb": True}), \
            mock.patch.object(ba, "analyze_image_for_ugc",
                              side_effect=vision_side_effect
                              or [_vision(), _verification()]), \
            mock.patch.object(ba.cl, "verify_niche",
                              side_effect=live_side_effect
                              or [_live(), _live()]):
        return ba.analyze(
            [{"bytes": b"fake-png", "mime": "image/png"}], notes, True)


def test_oggy_inspired_house_keeps_original_preferred_and_ip_warning():
    data = _analyze("Oggy-inspired cartoon house")
    assert data["ok"]
    titles = data["titles"]
    assert len(titles["all"]) == 3
    assert "Oggy" not in titles["preferred"]["title"]
    assert any("Oggy" in x["title"] for x in titles["alternatives"])
    assert "authorization" in data["ip_warning"].lower()
    assert "legally safe" not in data["ip_warning"].lower()
    report = ba.format_report(data)
    assert report.count("**Preferred:**") == 1
    assert report.count("**Alternative") == 2
    assert "Oggy" in report
    print("PASS Oggy-inspired house keeps original preferred + IP warning")


def test_generic_house_has_three_titles_and_no_franchise_claim():
    data = _analyze("original cartoon house")
    assert len(data["titles"]["all"]) == 3
    assert not data["ip_warning"]
    assert all(not x["franchise_reference"]
               for x in data["titles"]["all"])
    print("PASS generic cartoon house has three original titles")


def test_missing_image_and_vision_failure_are_explicit():
    missing = ba.analyze([], "a house", True)
    assert missing["status"] == "missing_image"
    failed = _analyze("a house", vision_side_effect=[{}])
    assert failed["status"] == "vision_failed"
    assert "notes only" in failed["evidence_label"].lower()
    print("PASS missing image and vision failure are explicit")


def test_verification_failure_retains_first_pass_label():
    data = _analyze("cartoon house",
                    vision_side_effect=[_vision(), {}])
    assert data["verification_status"] == "failed"
    report = ba.format_report(data)
    assert "first-pass only" in report
    assert "not treated as verification" in report
    print("PASS verification failure retains first-pass observations")


def test_live_success_includes_actual_ids_and_fields():
    data = _analyze("cartoon house")
    report = ba.format_report(data)
    assert "LIVE marketplace evidence" in report
    assert "https://www.roblox.com/catalog/111222333" in report
    assert "Toon House Background" in report
    assert "toon_creator" in report
    assert "2026-11-01" in report
    assert "not stored snapshots" in report
    print("PASS live success returns actual competitor IDs and fields")


def test_rate_limit_and_empty_results_do_not_substitute_stored_data():
    limited = _analyze("cartoon house",
                       live_side_effect=[_live(False, retry_after=30)])
    report = ba.format_report(limited)
    assert "rate_limited" in report
    assert "no stored match was substituted" in report

    empty = _analyze("cartoon house",
                     live_side_effect=[_live(True, competitors=[])])
    assert empty["live"][0]["status"] == "empty"
    assert "No type-92 competitors returned" in ba.format_report(empty)
    print("PASS 429/empty live results are explicit and do not fall back")


def test_sparse_creator_history_is_labeled():
    comp = {"id": 1, "name": "Lonely House Background", "creator": "",
            "favorites": None, "price": 0, "created_at": None,
            "asset_type_id": 92}
    data = _analyze("cartoon house",
                    live_side_effect=[_live(True, competitors=[comp])])
    report = ba.format_report(data)
    assert "creator unavailable" in report
    assert "publication date unavailable" in report
    print("PASS sparse creator/publication data is labeled")


def test_category_propagation_and_chain_context():
    import commands_advanced as ca
    family, concept = ca._resolve_family_prefix("backgrounds:cozy house")
    assert family == "backgrounds" and concept == "cozy house"
    data = _analyze("cartoon house")
    ba.store_last(1, 2, data)
    assert ba.last_visual_context(1, 2) == data["chain_context"]
    import inspect
    from chain import run_chain
    assert "visual_context" in inspect.signature(run_chain).parameters
    print("PASS background family and visual context propagate to chain")


def test_command_alias_keeps_owner_ai_authorization():
    policy = cs.policy_for("background_analyze")
    assert policy["command"] == "analyze_image"
    assert policy["level"] == "owner"
    assert policy["ai_cost"] is True
    assert cs.canonical_command_name("background_analyze") == "analyze_image"
    print("PASS background_analyze alias preserves owner/AI policy")


def test_command_alias_executes_background_path():
    import asyncio
    import discord_ugc_bot as botmod

    class Attachment:
        content_type = "image/png"
        filename = "scene.png"

        async def read(self):
            return b"scene-bytes"

    class Ctx:
        invoked_with = "background_analyze"
        author = type("Author", (), {"id": 3})()
        channel = type("Channel", (), {"id": 4})()

        def __init__(self):
            self.message = type("Message", (), {
                "attachments": [Attachment()]})()
            self.sent = []

        async def send(self, content=None, **kwargs):
            self.sent.append(content or "")
            return self

        async def edit(self, **kwargs):
            return self

        async def delete(self):
            return None

    command = botmod.bot.get_command("background_analyze")
    assert command is not None
    ctx = Ctx()
    with mock.patch.object(ba, "analyze",
                           return_value={"ok": True, "checked_at": "now"}), \
            mock.patch.object(ba, "format_report",
                              return_value="BG REPORT"), \
            mock.patch.object(ba, "store_last") as store:
        asyncio.run(command.callback(ctx, description="cartoon house"))
    assert "BG REPORT" in " ".join(ctx.sent)
    store.assert_called_once()
    print("PASS command alias executes the background-specific callback path")


def test_chain_backgrounds_receives_visual_context_and_filtered_live():
    import asyncio
    import discord_ugc_bot as botmod
    import chain

    class Ctx:
        invoked_with = "chain"
        author = type("Author", (), {"id": 5})()
        channel = type("Channel", (), {"id": 6})()
        vanta_state = None

        def __init__(self):
            self.sent = []

        async def send(self, content=None, **kwargs):
            self.sent.append(content or "")
            return type("Msg", (), {"delete": lambda self: asyncio.sleep(0)})()
        async def edit(self, **kwargs):
            return self

    ba.store_last(5, 6, {"chain_context": "orange cartoon house, blue sky"})
    ctx = Ctx()
    command = botmod.bot.get_command("chain")
    result = {"family": "backgrounds", "concept": "cozy house",
              "scored_titles": [{"title": "Toon House Background"}],
              "stats": {}, "error": None}
    live_calls = []
    with mock.patch.object(chain, "run_chain", return_value=result) as run, \
            mock.patch.object(ba.cl, "verify_niche",
                              side_effect=lambda *a, **k: (
                                  live_calls.append((a, k)) or
                                  _live())) as verify, \
            mock.patch("astra_report.build_analyst_report",
                       return_value=["CHAIN REPORT"]):
        asyncio.run(command.callback(ctx, args="backgrounds:cozy house"))
    assert run.call_args.kwargs["visual_context"] == (
        "orange cartoon house, blue sky")
    assert live_calls and live_calls[0][0][1] == "backgrounds"
    assert "CHAIN REPORT" in " ".join(ctx.sent)
    print("PASS chain backgrounds receives visual context and 92-only live check")


def test_report_has_no_unsupported_sales_or_ctr_claim():
    data = _analyze("cartoon house")
    report = ba.format_report(data)
    assert "No sales, revenue, CTR" in report
    assert "verified marketplace demand" in report
    assert "CTR:" not in report
    print("PASS report makes no unsupported sales/CTR claim")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL {len(tests)} BACKGROUND ANALYZE TESTS PASSED")
