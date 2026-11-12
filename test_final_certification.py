"""Final certification regressions for the A–Z stabilization pass."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import command_security as cs  # noqa: E402


def test_runtime_inventory_matches_authorization_policy():
    import discord_ugc_bot as bot_module
    runtime = {c.name for c in bot_module.bot.commands}
    assert runtime == cs.ALL_COMMANDS
    assert len(runtime) == 91
    assert "background_analyze" in runtime
    assert "scheduler" not in sys.modules
    print("PASS runtime inventory matches authorization policy; no scheduler on import")


def test_fixed_public_read_only_misclassifications():
    for name in ("verdict", "hitrate", "creator_brain"):
        policy = cs.policy_for(name)
        assert policy["level"] == "owner", name
        assert policy["mutating"] is True, name
    assert cs.policy_for("verdict")["external_api"] is True
    assert cs.policy_for("hitrate")["external_api"] is True
    assert cs.policy_for("creator_brain")["external_api"] is False
    print("PASS verdict/hitrate/creator_brain are owner-only and marked mutating")


def test_selftest_is_not_classified_read_only():
    policy = cs.policy_for("selftest")
    assert policy["level"] == "owner"
    assert policy["mutating"] is True
    assert policy["external_api"] is True
    assert policy["sensitive"] is True
    print("PASS selftest is classified as owner-only, mutating, external, sensitive")


def test_public_read_only_excludes_scoped_mutations():
    for name in ("guide", "experiments"):
        assert name in cs.PUBLIC_COMMANDS, name
        assert name not in cs.PUBLIC_READ_ONLY, name
        assert cs.policy_for(name)["mutating"] is True, name
    print("PASS public read-only excludes guide and experiments")


def test_selftest_harness_does_not_count_denials_as_success():
    import selftest

    assert selftest._responses_ok([{"content": "normal output", "embed": None}])
    assert not selftest._responses_ok([])
    assert not selftest._responses_ok(
        [{"content": "🚫 Owner-only command.", "embed": None}])
    assert not selftest._responses_ok(
        [{"content": "Unknown command", "embed": None}])
    print("PASS selftest harness rejects empty and denied responses")


def test_predictor_language_is_heuristic():
    from predictor import format_prediction
    pred = {
        "heuristic_score": 72,
        "probability": 72,
        "score_label": "heuristic rank score; not a calibrated probability",
        "verdict": "STRONG",
        "factors": {
            "competition_density": {"score": 10, "max": 25, "raw": 10},
        },
    }
    text = format_prediction(pred, "levitation dance")
    lowered = text.lower()
    assert "heuristic score" in lowered
    assert "not a calibrated probability" in lowered
    assert "success probability" not in lowered
    assert "attack immediately" not in lowered
    assert "launch within" not in lowered
    print("PASS predictor output is heuristic, not a success probability")


def test_roi_does_not_fabricate_sales_or_revenue():
    from bot_core import _compute_roi
    roi = _compute_roi(
        {"best_price": 100},
        {"count": 5, "avg_favs": 1000},
        [{"avg_favs": 800}],
    )
    assert roi["expected_favs"] == 400
    assert roi["expected_sales"] is None
    assert roi["expected_revenue"] is None
    assert roi["sales_evidence"] == "unavailable"
    guide = open("commands_guide.py", encoding="utf-8").read()
    assert "Expected Sales" not in guide
    assert "Expected Revenue" not in guide
    print("PASS ROI output does not fabricate sales or revenue")


def test_sales_dedupe_preserves_distinct_event_ids():
    source = open("database.py", encoding="utf-8").read()
    assert "a.source_event_id IS NOT DISTINCT FROM b.source_event_id" in source
    print("PASS startup sales dedupe is event-ID aware")


def test_workflow_job_names_are_unique():
    seen = {}
    for path in sorted(os.listdir(".github/workflows")):
        if not path.endswith((".yml", ".yaml")):
            continue
        text = open(os.path.join(".github/workflows", path), encoding="utf-8").read()
        in_jobs = False
        for line in text.splitlines():
            if re.match(r"^jobs:\s*$", line):
                in_jobs = True
                continue
            if in_jobs and re.match(r"^  [A-Za-z0-9_-]+:\s*$", line):
                name = line.strip().rstrip(":")
                if name in seen:
                    raise AssertionError(f"duplicate job name {name}: {seen[name]} and {path}")
                seen[name] = path
            elif in_jobs and re.match(r"^[^ ]", line):
                in_jobs = False
    print("PASS workflow job names are unique")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL {len(tests)} FINAL CERTIFICATION TESTS PASSED")
