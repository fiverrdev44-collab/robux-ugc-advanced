"""Callback-level behavioral tests for the 54 restricted commands.

All callbacks are the real registered callbacks. External providers, DB, files,
process restarts, and deployment actions are mocked; production is never used.
"""
import os
import subprocess
import sys
from contextlib import ExitStack
from unittest import mock

os.environ.setdefault("ROBLOSECURITY_COOKIE", "test-cookie")
os.environ.setdefault("ROBLOSECURITY_COOKIE_1", "test-cookie")

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_public_command_callbacks as pub  # noqa: E402
import command_security as cs  # noqa: E402
import commands_supercomputer as csc  # noqa: E402
import commands_sales as csales  # noqa: E402
import commands_intel as cintel  # noqa: E402
import commands_experiments as cexp  # noqa: E402
import gemini_brain  # noqa: E402

OWNER = 900000000000000001


class Resp:
    status_code = 200
    headers = {}
    text = "{}"

    def json(self):
        return {}


def _fake_get(*args, **kwargs):
    return Resp()


def _fake_post(*args, **kwargs):
    return Resp()


def _fake_subprocess(*args, **kwargs):
    return type("R", (), {"returncode": 0, "stdout": "abc123",
                          "stderr": ""})()


def _run(name, extra=(), **kwargs):
    ctx = pub.FakeCtx(name)
    ctx.author.id = OWNER
    with ExitStack() as stack:
        stack.enter_context(pub._db(pub._callback(name), pub._rows_handler))
        stack.enter_context(mock.patch.object(
            cs, "_owner_ids", return_value={OWNER}))
        stack.enter_context(mock.patch.object(csc, "BOT_OWNERS", {OWNER}))
        stack.enter_context(mock.patch.object(requests, "get", _fake_get))
        stack.enter_context(mock.patch.object(requests, "post", _fake_post))
        stack.enter_context(mock.patch.object(
            subprocess, "run", _fake_subprocess))
        stack.enter_context(mock.patch.object(
            csc.os, "_exit", lambda *args: None))
        stack.enter_context(mock.patch(
            "bot_core.get_db", lambda: pub.FakeConn(pub._rows_handler)))
        stack.enter_context(mock.patch(
            "bot_core.get_research_db",
            lambda: pub.FakeConn(pub._rows_handler)))
        stack.enter_context(mock.patch(
            "snapshot.snapshot_top_items", return_value=True))
        stack.enter_context(mock.patch(
            "scanner.run_scanner", return_value=True))
        stack.enter_context(mock.patch(
            "enricher.enrich_items", return_value=True))
        stack.enter_context(mock.patch(
            "title_predictor.train_model",
            return_value={"n_samples": 1, "accuracy": 1.0}))
        stack.enter_context(mock.patch(
            "creator_tracker.run_batch", return_value=(0, 0, 0, "")))
        stack.enter_context(mock.patch(
            "suggest.run_suggest", return_value=None))
        stack.enter_context(mock.patch.object(
            csc, "safe_get", _fake_get))
        stack.enter_context(mock.patch.object(
            csales, "safe_get", _fake_get))
        stack.enter_context(mock.patch.object(
            csales, "safe_post", _fake_post))
        stack.enter_context(mock.patch.object(
            gemini_brain, "_generate", return_value=None))
        for context in extra:
            stack.enter_context(context)
        pub._run(name, ctx, **kwargs)
    assert ctx.text(), name
    return ctx


def test_ai_and_creative_restricted_callbacks():
    for name, kwargs in (
            ("analyze_image", {"description": "a test image"}),
            ("brainstorm", {"description": "dance emote"}),
            ("rescue", {"description": "dance emote launched"}),
            ("creative", {"seed": "dance"}),
            ("creative_raw", {"seed": "dance"}),
            ("concept", {"text": "emotes | levitation"}),
            ("chain", {}),
            ("desc_forge", {"args": "emotes:dance"}),
            ("tags", {"args": "Cute Hat"}),
            ("meta_sniper", {"niche": "dance"}),
            ("stealth", {"args": "Cute Hat"}),
            ("playbook", {"topic": ""}),
            ("path", {}),
            ("revsim", {"price": 10}),
            ("sales_keywords", {"family": "emote"}),
    ):
        _run(name, **kwargs)
    print("PASS restricted AI/creative callbacks execute")


def test_data_and_ledger_restricted_callbacks():
    def mark(*args, **kwargs):
        return ({"id": 1, "measure_at": pub.NOW}, None)

    def mark_ignored(*args, **kwargs):
        return (1, None)

    extras = [
        mock.patch("experiments.mark_latest", side_effect=mark),
        mock.patch("experiments.mark_applied", side_effect=mark),
        mock.patch("experiments.mark_latest_ignored",
                   side_effect=mark_ignored),
        mock.patch("experiments.mark_ignored",
                   side_effect=mark_ignored),
        mock.patch("data_audit.build_report", return_value={}),
        mock.patch("data_audit.format_report", return_value="DATA AUDIT"),
        mock.patch("creator_brain.learn", return_value=[]),
        mock.patch("creator_brain.save", return_value=None),
        mock.patch("creator_brain.load_findings", return_value=[]),
        mock.patch("creator_brain.format_report", return_value="BRAIN"),
        mock.patch("launch_ledger.configured_groups", return_value=[]),
        mock.patch("launch_ledger.sync_group_items",
                   return_value=(0, 0)),
        mock.patch.object(csc, "configured_groups", return_value=[]),
        mock.patch.object(csc, "sync_group_items", return_value=(0, 0)),
        mock.patch.object(cintel, "fetch_item_from_roblox",
                          return_value=None),
        mock.patch.object(cintel, "save_item_to_db", return_value=None),
    ]
    for name, kwargs in (
            ("applied", {}), ("ignored", {}), ("dbtest", {}),
            ("data_audit", {}), ("desc_analyze", {"keyword": "dance"}),
            ("hitrate", {}), ("link", {"run_id": 1,
                                                           "item_id": 1}),
            ("rename", {"run_id": 1, "item_id": 1}),
            ("outcome", {"run_id": 1}),
            ("launch", {"item_id": 1}), ("launch_sync", {"groups": "G"}),
            ("ledger_sync", {}), ("creator_brain", {}),
            ("momentum_debug", {}), ("verdict", {"item_id": 1}),
            ("autopsy", {"item_id": 1}), ("revive", {"item_id": 1}),
            ("verified_scan", {"limit": 1}),
            ("group_metrics", {"group_id": 1}),
            ("sales_debug", {}), ("sales_backfill", {"limit": 1}),
            ("sales_post_now", {}), ("sales_probe", {"item": "dance"}),
            ("sales_scan", {"limit": 1}),
    ):
        _run(name, extras, **kwargs)
    print("PASS restricted data/ledger callbacks execute")


def test_operational_restricted_callbacks():
    extras = [
        mock.patch("snapshot.snapshot_top_items", return_value=True),
        mock.patch("scanner.run_scanner", return_value=True),
        mock.patch("enricher.enrich_items", return_value=True),
        mock.patch("title_predictor.train_model",
                   return_value={"n_samples": 1, "accuracy": 1.0}),
        mock.patch("sales_listener.backfill_channel",
                   return_value=(0, 0, 0)),
        mock.patch("sales_listener.sales_summary",
                   return_value={"total_units": 0, "total_robux": 0,
                                 "top_items": [], "daily": [],
                                 "unresolved": [], "coverage": {},
                                 "window": {}}),
        mock.patch("sales_listener.item_sales_summary", return_value=None),
    ]
    for name, kwargs in (
            ("snapshot_now", {}), ("scan_run", {}), ("enrich_run", {}),
            ("train", {}), ("selftest_db", {}),
            ("logs", {"lines": 1}), ("bot_update", {}),
            ("suggest_probe", {"query": "dance"}),
            ("suggest_run", {}), ("vacuum", {"limit": 1}),
            ("visibility_run", {"limit": 1}),
            ("visibility_seed", {"limit": 1}),
            ("converge_debug", {"keyword": "dance"}),
            ("cookie_check", {}),
    ):
        _run(name, extras, **kwargs)
    print("PASS restricted operational callbacks execute")


def test_restricted_coverage_count():
    names = {
        "analyze_image", "applied", "autopsy", "bot_update", "brainstorm",
        "chain", "concept", "converge_debug", "cookie_check", "creative",
        "creative_raw", "creator_brain", "data_audit", "dbtest",
        "desc_analyze", "desc_forge", "enrich_run", "group_metrics",
        "hitrate", "ignored", "launch", "launch_sync", "ledger_sync", "link",
        "logs", "meta_sniper", "momentum_debug", "outcome", "path",
        "playbook", "rename", "rescue", "revive", "revsim",
        "sales_backfill", "sales_debug", "sales_keywords", "sales_post_now",
        "sales_probe", "sales_scan", "scan_run", "selftest", "selftest_db",
        "snapshot_now", "stealth", "suggest_probe", "suggest_run", "tags",
        "train", "vacuum", "verdict", "verified_scan", "visibility_run",
        "visibility_seed",
    }
    assert len(names) == 54
    print("PASS restricted callback list covers all 54 commands")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL {len(tests)} RESTRICTED COMMAND CALLBACK TESTS PASSED")
