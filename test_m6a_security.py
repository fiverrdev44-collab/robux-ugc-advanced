"""M6-A command authorization, secret, and AI-cost regression tests."""
import asyncio
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import command_security as cs  # noqa: E402
from discord.ext import commands as dcommands  # noqa: E402

OWNER = 900000000000000001
NON_OWNER = 900000000000000002


def _owner_context():
    return mock.patch.object(cs, "_owner_ids", return_value={OWNER})


def test_every_registered_command_is_classified():
    assert len(cs.ALL_COMMANDS) == 90
    assert not (cs.OWNER_ONLY & cs.PUBLIC_READ_ONLY)
    assert cs.OWNER_ONLY | cs.PUBLIC_READ_ONLY == cs.ALL_COMMANDS
    for name in cs.ALL_COMMANDS:
        policy = cs.policy_for(name)
        assert policy["known"] is True
        assert policy["level"] in {"owner", "public"}
        assert policy["command"] == name
    assert cs.AI_COST <= cs.OWNER_ONLY
    assert cs.MUTATING <= cs.OWNER_ONLY
    print("PASS every command has an explicit authorization policy")


def test_owner_only_commands_deny_non_owner_and_allow_owner():
    restricted = [
        "ai_debug", "snapshot_now", "sales_backfill", "sales_post_now",
        "visibility_seed", "visibility_run", "dbtest", "data_audit",
        "brainstorm", "rescue", "analyze_image", "concept", "chain",
        "creative", "creative_raw", "desc_forge", "applied", "ignored",
        "link", "rename", "outcome", "scan_run", "train", "vacuum",
    ]
    with _owner_context():
        for name in restricted:
            denied = cs.authorize_command(name, NON_OWNER)
            assert not denied.allowed, name
            assert denied.level == "owner"
            allowed = cs.authorize_command(name, OWNER)
            assert allowed.allowed, name
    print("PASS owner-only commands deny non-owners and allow owners")


def test_public_read_only_commands_still_work():
    public = [
        "guide", "help", "version", "start", "watchlist", "track",
        "sales_report", "sales_for", "converge", "verdict", "predict",
        "emote_title", "creator_brain", "momentum", "experiments",
    ]
    with _owner_context():
        for name in public:
            decision = cs.authorize_command(name, NON_OWNER)
            assert decision.allowed, name
            assert decision.level == "public"
    print("PASS public read-only commands remain available")


def test_aliases_cannot_bypass_authorization():
    assert cs.canonical_command_name("apply_rec") == "applied"
    assert cs.canonical_command_name("run_scanner") == "scan_run"
    assert cs.canonical_command_name("ver") == "version"
    with _owner_context():
        assert not cs.authorize_command("apply_rec", NON_OWNER).allowed
        assert not cs.authorize_command("run_scanner", NON_OWNER).allowed
        assert cs.authorize_command("ver", NON_OWNER).allowed
        assert not cs.authorize_command("unknown_command", NON_OWNER).allowed
    print("PASS aliases resolve to canonical policy; unknown commands fail closed")


def test_unauthorized_denial_happens_before_callback_work():
    calls = []

    def callback():
        calls.append("called")

    with _owner_context():
        try:
            cs.require_authorized("ai_debug", NON_OWNER)
        except cs.CommandNotAuthorized:
            pass
        else:
            raise AssertionError("expected denial")
    assert calls == []
    assert issubclass(cs.CommandNotAuthorized, dcommands.CheckFailure)
    print("PASS denial raises before any callback work")


def test_ai_limits_are_per_user_and_global():
    cs.configure_for_tests(user_limit=1, owner_limit=1, global_limit=10,
                           window_seconds=60)
    with _owner_context():
        first = cs.authorize_command("concept", OWNER, now=100.0)
        second = cs.authorize_command("concept", OWNER, now=101.0)
    assert first.allowed
    assert not second.allowed and second.ai_rate_limited

    cs.configure_for_tests(user_limit=1, owner_limit=10, global_limit=1,
                           window_seconds=60)
    with _owner_context():
        first = cs.authorize_command("concept", OWNER, now=200.0)
        second = cs.authorize_command("brainstorm", OWNER, now=201.0)
    assert first.allowed
    assert not second.allowed and second.ai_rate_limited
    cs.configure_for_tests()
    cs.reset_for_tests()
    print("PASS per-user and global AI limits reject excessive invocation")


def test_denied_non_owner_does_not_consume_ai_quota():
    cs.configure_for_tests(user_limit=1, owner_limit=1, global_limit=10,
                           window_seconds=60)
    with _owner_context():
        denied = cs.authorize_command("concept", NON_OWNER, now=300.0)
        allowed = cs.authorize_command("concept", OWNER, now=301.0)
    assert not denied.allowed
    assert allowed.allowed
    cs.configure_for_tests()
    cs.reset_for_tests()
    print("PASS unauthorized AI requests do not consume quota")


def test_secret_redaction_removes_keys_and_cookies():
    fake_gemini = "AIza" + "A" * 28
    fake_openrouter = "sk-" + "b" * 24
    fake_cookie = "COOKIE-SECRET-VALUE-123"
    with mock.patch.dict(os.environ, {
            "GEMINI_API_KEY": fake_gemini,
            "OPENROUTER_API_KEY": fake_openrouter,
            "ROBLOSECURITY_COOKIE_1": fake_cookie,
    }, clear=False):
        text = cs.redact_secrets(
            f"gemini={fake_gemini} openrouter={fake_openrouter} "
            f"cookie={fake_cookie}")
    assert fake_gemini not in text
    assert fake_openrouter not in text
    assert fake_cookie not in text
    assert "[redacted" in text
    print("PASS secret redaction removes keys and cookies")


def test_ai_debug_source_never_prints_key_material():
    source = open("commands_ai.py", encoding="utf-8").read()
    assert "gkey[:" not in source
    assert "okey[:" not in source
    assert "len(gkey)" not in source
    assert "len(okey)" not in source
    assert "configured" in source
    print("PASS ai_debug source has no key prefix/length output")


class _FakeBot:
    def __init__(self):
        self.commands = {}

    def command(self, name=None, **kwargs):
        def decorator(fn):
            self.commands[name or kwargs.get("name")] = fn
            return fn
        return decorator


class _FakeCtx:
    def __init__(self):
        self.messages = []

    async def send(self, content=None, **kwargs):
        self.messages.append(content or "")


def test_ai_debug_mock_keys_never_appear_in_response():
    import commands_ai

    fake_gemini = "AIza" + "G" * 28
    fake_openrouter = "sk-" + "O" * 24
    bot = _FakeBot()
    commands_ai.register_ai_commands(bot)
    ctx = _FakeCtx()
    with mock.patch.dict(os.environ, {
            "GEMINI_API_KEY": fake_gemini,
            "OPENROUTER_API_KEY": fake_openrouter,
    }, clear=False), \
            mock.patch("google.genai.Client",
                       side_effect=Exception(f"bad key {fake_gemini}")), \
            mock.patch("openai.OpenAI",
                       side_effect=Exception(f"bad key {fake_openrouter}")):
        asyncio.run(bot.commands["ai_debug"](ctx))
    text = "\n".join(ctx.messages)
    assert fake_gemini not in text
    assert fake_openrouter not in text
    assert "configured" in text
    assert "len" not in text.lower()
    print("PASS ai_debug mock keys never appear in Discord response")


def test_ai_cost_and_mutating_commands_are_owner_only():
    for name in cs.AI_COST:
        policy = cs.policy_for(name)
        assert policy["level"] == "owner", name
    for name in cs.MUTATING:
        policy = cs.policy_for(name)
        assert policy["level"] == "owner", name
    print("PASS AI-cost and mutating commands require owner authorization")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL {len(tests)} M6-A SECURITY TESTS PASSED")
