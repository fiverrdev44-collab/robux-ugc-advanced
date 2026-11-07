"""M6-A command authorization, secret, and AI-cost regression tests."""
import asyncio
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import discord  # noqa: E402
import command_security as cs  # noqa: E402
from discord.ext import commands as dcommands  # noqa: E402

OWNER = 900000000000000001
NON_OWNER = 900000000000000002


def _owner_context():
    return mock.patch.object(cs, "_owner_ids", return_value={OWNER})


def test_every_registered_command_is_classified():
    assert len(cs.ALL_COMMANDS) == 90
    assert not (cs.OWNER_ONLY & cs.PUBLIC_READ_ONLY)
    assert not (cs.OWNER_ONLY & cs.PUBLIC_RATE_LIMITED)
    assert not (cs.PUBLIC_READ_ONLY & cs.PUBLIC_RATE_LIMITED)
    assert (cs.OWNER_ONLY | cs.PUBLIC_READ_ONLY
            | cs.PUBLIC_RATE_LIMITED) == cs.ALL_COMMANDS
    for name in cs.ALL_COMMANDS:
        policy = cs.policy_for(name)
        assert policy["known"] is True
        assert policy["level"] in {"owner", "public"}
        assert policy["command"] == name
    assert cs.AI_COST <= (cs.OWNER_ONLY | cs.PUBLIC_RATE_LIMITED)
    assert cs.PUBLIC_RATE_LIMITED <= cs.AI_COST
    assert cs.MUTATING <= cs.OWNER_ONLY
    print("PASS every command has an explicit authorization policy")


def test_owner_only_commands_deny_non_owner_and_allow_owner():
    restricted = [
        "ai_debug", "snapshot_now", "sales_backfill", "sales_post_now",
        "visibility_seed", "visibility_run", "dbtest", "data_audit",
        "brainstorm", "rescue", "analyze_image", "concept", "chain",
        "creative", "creative_raw", "desc_forge", "applied", "ignored",
        "link", "rename", "outcome", "scan_run", "train", "vacuum",
        "verdict", "hitrate", "creator_brain",
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
        "sales_report", "sales_for", "converge", "predict",
        "momentum", "experiments",
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
    for name in cs.AI_COST - cs.PUBLIC_RATE_LIMITED:
        policy = cs.policy_for(name)
        assert policy["level"] == "owner", name
    for name in cs.MUTATING:
        policy = cs.policy_for(name)
        assert policy["level"] == "owner", name
    print("PASS AI-cost and mutating commands require owner authorization")


def test_emote_title_public_exception_is_documented_and_rate_limited():
    policy = cs.policy_for("emote_title")
    assert policy["level"] == "public"
    assert policy["ai_cost"] is True
    assert policy["external_api"] is True
    assert policy["public_exception"] is True

    cs.configure_emote_title_for_tests(user_limit=1, owner_limit=1,
                                       global_limit=10, window_seconds=60)
    with _owner_context():
        first = cs.authorize_command("emote_title", NON_OWNER, now=400.0)
        second = cs.authorize_command("emote_title", NON_OWNER, now=401.0)
    assert first.allowed and first.level == "public"
    assert not second.allowed and second.ai_rate_limited

    cs.configure_emote_title_for_tests(user_limit=2, owner_limit=1,
                                       global_limit=10, window_seconds=60)
    with _owner_context():
        first = cs.authorize_command("emote_title", OWNER, now=500.0)
        second = cs.authorize_command("emote_title", OWNER, now=501.0)
    assert first.allowed
    assert not second.allowed and second.ai_rate_limited
    cs.configure_emote_title_for_tests()
    cs.reset_for_tests()
    print("PASS emote_title public exception is documented and rate-limited")


def test_emote_title_limiter_denies_before_callback():
    async def scenario():
        bot = dcommands.Bot(command_prefix="!",
                            intents=discord.Intents.default())
        bot.before_invoke(cs.authorize_before_invoke)
        calls = []

        class Cmd:
            name = "emote_title"

        class Author:
            id = NON_OWNER

        class Ctx:
            command = Cmd()
            author = Author()

        async def callback():
            calls.append(1)

        await bot._before_invoke(Ctx())
        await callback()
        try:
            await bot._before_invoke(Ctx())
        except cs.CommandNotAuthorized:
            return calls
        raise AssertionError("second emote_title should be denied")

    cs.configure_emote_title_for_tests(user_limit=1, owner_limit=1,
                                       global_limit=10, window_seconds=60)
    with mock.patch("bot_core.psycopg2.connect",
                    side_effect=AssertionError("DB call attempted")), \
            mock.patch("live_market._get_with_backoff",
                       side_effect=AssertionError("Roblox call attempted")), \
            mock.patch("gemini_brain._generate",
                       side_effect=AssertionError("AI call attempted")):
        with _owner_context():
            calls = asyncio.run(scenario())
    cs.configure_emote_title_for_tests()
    cs.reset_for_tests()
    assert calls == [1]
    print("PASS emote_title limiter denies before AI/API callback")


def test_real_before_invoke_hook_denies_before_callback():
    async def scenario():
        bot = dcommands.Bot(command_prefix="!", intents=discord.Intents.default())
        bot.before_invoke(cs.authorize_before_invoke)
        calls = []

        class Cmd:
            name = "snapshot_now"

        class Author:
            id = NON_OWNER

        class Ctx:
            command = Cmd()
            author = Author()

        denied = False
        try:
            await bot._before_invoke(Ctx())
        except cs.CommandNotAuthorized:
            denied = True
        assert denied
        assert calls == []

        Ctx.command.name = "guide"
        await bot._before_invoke(Ctx())

        Ctx.command.name = "unknown_command"
        try:
            await bot._before_invoke(Ctx())
        except cs.CommandNotAuthorized:
            pass
        else:
            raise AssertionError("unknown command should fail closed")

    with _owner_context():
        asyncio.run(scenario())
    print("PASS real Discord before_invoke hook denies before callback")


def test_real_before_invoke_hook_enforces_ai_limit():
    async def scenario():
        bot = dcommands.Bot(command_prefix="!", intents=discord.Intents.default())
        bot.before_invoke(cs.authorize_before_invoke)

        class Cmd:
            name = "concept"

        class Author:
            id = OWNER

        class Ctx:
            command = Cmd()
            author = Author()

        await bot._before_invoke(Ctx())
        try:
            await bot._before_invoke(Ctx())
        except cs.CommandNotAuthorized:
            return True
        return False

    cs.configure_for_tests(user_limit=1, owner_limit=1, global_limit=10,
                           window_seconds=60)
    with _owner_context():
        denied = asyncio.run(scenario())
    cs.configure_for_tests()
    cs.reset_for_tests()
    assert denied
    print("PASS real before_invoke hook enforces AI rate limit")


def test_conversation_router_denies_before_callback():
    import vanta_conversation as vc

    class Cmd:
        name = "desc_forge"
        def __init__(self):
            self.called = []

        async def callback(self, ctx, **kwargs):
            self.called.append(kwargs)

    class Bot:
        def __init__(self):
            self.cmd = Cmd()

        def get_command(self, name):
            return self.cmd if name == "desc_forge" else None

    class Channel:
        def __init__(self):
            self.messages = []

        async def send(self, content=None, **kwargs):
            self.messages.append(content or "")

    class Message:
        def __init__(self, channel):
            self.channel = channel
            self.author = type("A", (), {"id": NON_OWNER, "bot": False})()
            self.content = "tags"
            self.attachments = []
            self.id = 1

    route = {"intent": "tags", "concept": "Cute Hat", "item_id": None,
             "family": None}
    channel = Channel()
    message = Message(channel)
    bot = Bot()
    state = vc.ConversationState(user_id=NON_OWNER)
    with mock.patch("bot_core.psycopg2.connect",
                    side_effect=AssertionError("DB call attempted")), \
            mock.patch("live_market._get_with_backoff",
                       side_effect=AssertionError("Roblox call attempted")), \
            mock.patch("gemini_brain._generate",
                       side_effect=AssertionError("AI call attempted")):
        asyncio.run(vc._run_registry(bot, message, route, state))
    assert bot.cmd.called == []
    assert any("denied" in str(x).lower() for x in channel.messages)

    with _owner_context():
        channel2 = Channel()
        message2 = Message(channel2)
        message2.author.id = OWNER
        bot2 = Bot()
        state2 = vc.ConversationState(user_id=OWNER)
        asyncio.run(vc._run_registry(bot2, message2, route, state2))
    assert bot2.cmd.called, bot2.cmd.called
    print("PASS conversation router denies before callback and allows owner")


def test_planner_budget_is_global_per_user_and_counts_failures():
    import vanta_conversation as vc

    text = "maybe a floating lantern hat for cozy avatars"
    calls = []

    def fake_planner(*args, **kwargs):
        calls.append(1)
        return None

    cs.configure_planner_for_tests(user_limit=1, owner_limit=1,
                                   global_limit=10, window_seconds=60)
    with mock.patch.object(vc, "_planner_ai", side_effect=fake_planner), \
            mock.patch.object(cs, "_owner_ids", return_value=set()):
        first = vc.ConversationState(user_id=NON_OWNER)
        asyncio.run(vc.plan_message(text, False, first, bot=None))
        second = vc.ConversationState(user_id=NON_OWNER)
        asyncio.run(vc.plan_message(text, False, second, bot=None))
    assert len(calls) == 1
    assert len(first.ai_calls) == 1
    assert len(second.ai_calls) == 0

    calls.clear()
    def failing_planner(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("provider failed")

    cs.configure_planner_for_tests(user_limit=1, owner_limit=1,
                                   global_limit=10, window_seconds=60)
    with mock.patch.object(vc, "_planner_ai", side_effect=failing_planner), \
            mock.patch.object(cs, "_owner_ids", return_value=set()):
        first = vc.ConversationState(user_id=NON_OWNER)
        asyncio.run(vc.plan_message(text, False, first, bot=None))
        second = vc.ConversationState(user_id=NON_OWNER)
        asyncio.run(vc.plan_message(text, False, second, bot=None))
    assert len(calls) == 1

    calls.clear()
    cs.configure_planner_for_tests(user_limit=10, owner_limit=10,
                                   global_limit=1, window_seconds=60)
    with mock.patch.object(vc, "_planner_ai", side_effect=fake_planner), \
            mock.patch.object(cs, "_owner_ids", return_value=set()):
        first = vc.ConversationState(user_id=1)
        asyncio.run(vc.plan_message(text, False, first, bot=None))
        second = vc.ConversationState(user_id=2)
        asyncio.run(vc.plan_message(text, False, second, bot=None))
    assert len(calls) == 1
    assert len(first.ai_calls) == 1
    assert len(second.ai_calls) == 0
    cs.configure_planner_for_tests()
    cs.reset_for_tests()
    print("PASS planner budget is global per user and counts failed attempts")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL {len(tests)} M6-A SECURITY TESTS PASSED")
