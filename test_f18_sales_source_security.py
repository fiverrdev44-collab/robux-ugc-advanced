"""F-18 sales-source authentication tests, including real listener paths."""
import asyncio
import contextlib
import io
import os
import sys
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sales_listener as sl
import sales_source_validation as ssv

CHANNEL = "333333333333333333"
GUILD = "444444444444444444"
WEBHOOK = "111111111111111111"
BOT = "222222222222222222"
HUMAN = "555555555555555555"


class Author:
    def __init__(self, author_id, bot=False):
        self.id = author_id
        self.bot = bot


class Channel:
    def __init__(self, channel_id):
        self.id = channel_id
        self.name = "sales"


class Guild:
    def __init__(self, guild_id):
        self.id = guild_id


class Field:
    def __init__(self, name, value):
        self.name = name
        self.value = value


class Embed:
    def __init__(self, title="New Sale", fields=None, timestamp=None,
                 description="purchase"):
        self.title = title
        self.description = description
        self.fields = fields or [
            Field("Item", "Glow Hat"),
            Field("Amount", "R$ 10"),
            Field("Buyer", "Buyer One"),
        ]
        self.timestamp = timestamp
        self.footer = None


class Message:
    def __init__(self, message_id=1, channel_id=CHANNEL, guild_id=GUILD,
                 webhook_id=None, author_id=HUMAN, bot=False, embeds=None,
                 content=""):
        self.id = message_id
        self.channel = Channel(channel_id)
        self.guild = Guild(guild_id) if guild_id else None
        self.webhook_id = webhook_id
        self.author = Author(author_id, bot) if author_id else None
        self.embeds = embeds if embeds is not None else [Embed()]
        self.created_at = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
        self.content = content


def _env(mode, include_allowlist=True):
    env = {
        "SALES_SOURCE_MODE": mode,
        "SALES_CHANNEL_ID": CHANNEL,
        "SALES_GUILD_ID": GUILD,
    }
    if include_allowlist:
        env["SALES_WEBHOOK_IDS"] = WEBHOOK
        env["SALES_SOURCE_USER_IDS"] = BOT
    return env


def _set_env(env):
    return mock.patch.dict(os.environ, env, clear=False)


def _decision(message, env):
    with _set_env(env):
        return ssv.validate_message(message)


def test_approved_webhook_and_bot_in_channel():
    webhook = _decision(Message(webhook_id=WEBHOOK), _env("enforce"))
    assert webhook.allowed and webhook.source_kind == "webhook"
    bot = _decision(Message(author_id=BOT, bot=True), _env("enforce"))
    assert bot.allowed and bot.source_kind == "bot_user"
    print("PASS approved webhook and bot sender accepted")


def test_unapproved_webhook_cannot_borrow_bot_id():
    msg = Message(webhook_id="999999999999999999", author_id=BOT, bot=True)
    decision = _decision(msg, _env("enforce"))
    assert not decision.allowed and decision.source_kind == "webhook"
    assert "webhook" in decision.reason
    print("PASS unapproved webhook cannot borrow trusted bot identity")


def test_human_and_unapproved_bot_are_rejected():
    human = _decision(Message(author_id=HUMAN), _env("enforce"))
    assert not human.allowed and human.source_kind == "user"
    bot = _decision(Message(author_id="888888888888888888", bot=True),
                    _env("enforce"))
    assert not bot.allowed and bot.source_kind == "bot_user"
    print("PASS human/unapproved bot rejected")


def test_wrong_channel_guild_and_missing_metadata():
    wrong_channel = _decision(
        Message(channel_id="999999999999999999", webhook_id=WEBHOOK),
        _env("enforce"))
    assert not wrong_channel.allowed and "channel" in wrong_channel.reason
    wrong_guild = _decision(
        Message(guild_id="999999999999999999", webhook_id=WEBHOOK),
        _env("enforce"))
    assert not wrong_guild.allowed and "guild" in wrong_guild.reason
    missing = _decision(Message(author_id=None, webhook_id=None),
                        _env("enforce"))
    assert not missing.allowed and missing.source_kind == "unknown"
    print("PASS wrong channel/guild and missing metadata rejected")


def test_empty_and_invalid_configuration_fail_closed():
    empty = _decision(Message(webhook_id=WEBHOOK),
                      {"SALES_SOURCE_MODE": "enforce",
                       "SALES_CHANNEL_ID": CHANNEL})
    assert not empty.allowed and "configuration" in empty.reason

    invalid_ids = _decision(
        Message(webhook_id=WEBHOOK),
        {"SALES_SOURCE_MODE": "enforce", "SALES_CHANNEL_ID": CHANNEL,
         "SALES_WEBHOOK_IDS": "not-an-id"})
    assert not invalid_ids.allowed

    invalid_mode = _decision(
        Message(webhook_id=WEBHOOK),
        {"SALES_SOURCE_MODE": "enforced", "SALES_CHANNEL_ID": CHANNEL,
         "SALES_WEBHOOK_IDS": WEBHOOK})
    assert not invalid_mode.allowed
    print("PASS empty/invalid configuration fails closed in enforce")


def test_dry_run_ingests_and_reports_would_reject():
    ssv.reset_diagnostics()
    msg = Message(author_id=HUMAN)
    with _set_env(_env("dry-run")):
        decision = ssv.check_message(msg)
    assert decision.allowed and decision.would_reject
    snap = ssv.diagnostics_snapshot()
    assert snap["allowed"] == 1 and snap["would_reject"] == 1
    assert snap["rejected"] == 0
    assert snap["by_reason"]
    print("PASS dry-run preserves ingestion and reports would-reject")


def test_off_mode_is_visible_and_permissive():
    ssv.reset_diagnostics()
    with _set_env({"SALES_SOURCE_MODE": "off"}):
        decision = ssv.check_message(Message(author_id=HUMAN))
    assert decision.allowed and not decision.would_reject
    assert ssv.diagnostics_snapshot()["disabled"] == 1
    print("PASS off mode remains permissive and visible in diagnostics")


def test_enforce_rejects_before_parsing_or_database():
    msg = Message(author_id=HUMAN)
    with _set_env(_env("enforce")), \
            mock.patch.object(sl, "extract_sales_from_message",
                              side_effect=AssertionError("parsed")), \
            mock.patch.object(sl, "_save_sale_single",
                              side_effect=AssertionError("db")):
        result = asyncio.run(sl.handle_sale_message(msg))
    assert result is False
    print("PASS enforce rejects before parsing and DB access")


def test_approved_listener_marks_and_persists():
    calls = []

    def fake_save(sale):
        calls.append(sale)
        return True

    msg = Message(webhook_id=WEBHOOK, embeds=[Embed(), Embed()])
    with _set_env(_env("enforce")), \
            mock.patch.object(sl, "_save_sale_single", side_effect=fake_save):
        result = asyncio.run(sl.handle_sale_message(msg))
    assert result is True
    assert [sale["embed_index"] for sale in calls] == [0, 1]
    assert all(sale["_source_validated"] is True for sale in calls)
    assert all(sale["_source_kind"] == "webhook" for sale in calls)
    print("PASS approved listener persists all embeds with original indexes")


class FakeHistoryChannel(Channel):
    def __init__(self, messages):
        super().__init__(CHANNEL)
        self.messages = messages

    async def history(self, limit=100):
        for message in self.messages[:limit]:
            yield message


class FakeBot:
    def __init__(self, channel):
        self.channel = channel

    def get_channel(self, channel_id):
        return self.channel if str(channel_id) == str(self.channel.id) else None


def test_backfill_and_auto_backfill_apply_validation():
    approved = Message(message_id=1, webhook_id=WEBHOOK)
    rejected = Message(message_id=2, author_id=HUMAN)
    channel = FakeHistoryChannel([approved, rejected])
    bot = FakeBot(channel)
    calls = []

    def fake_batch(sales):
        calls.extend(sales)
        return len(sales), 0

    with _set_env(_env("enforce")), \
            mock.patch.object(sl, "_save_sales_batch", side_effect=fake_batch):
        scanned, inserted = asyncio.run(
            sl.backfill_channel(bot, CHANNEL, limit=10))
    assert scanned == 2 and inserted == 1
    assert len(calls) == 1 and calls[0]["_source_validated"] is True

    calls.clear()
    with _set_env(_env("enforce")), \
            mock.patch.object(sl, "_save_sales_batch", side_effect=fake_batch):
        scanned, inserted = asyncio.run(sl.auto_backfill(bot, limit=10))
    assert scanned == 2 and inserted == 1 and len(calls) == 1
    print("PASS startup/manual backfill paths apply the same validation")


def test_ingestion_helpers_refuse_unvalidated_sales():
    sale = {"item_name": "x", "source_event_id": "txn:x:1"}
    with mock.patch.object(sl, "get_db",
                           side_effect=AssertionError("DB touched")):
        assert sl._save_sale_single(dict(sale)) is False
        assert sl._save_sales_batch([dict(sale)]) == (0, 1)
        assert sl._insert_sale(object(), dict(sale)) is False
    print("PASS direct persistence helpers refuse unvalidated sales")


def test_logging_contains_no_message_content_or_secrets():
    buf = io.StringIO()
    msg = Message(author_id=HUMAN,
                  content="SECRET_TOKEN buyer@example.com")
    with _set_env(_env("enforce")), contextlib.redirect_stdout(buf):
        ssv.check_message(msg)
    output = buf.getvalue()
    assert "SECRET_TOKEN" not in output
    assert "buyer@example.com" not in output
    assert "mode=enforce" in output and "decision=reject" in output
    print("PASS source logging omits content, buyer data and secrets")


def test_validation_does_not_mutate_sale_identity():
    before = sl.extract_sales_from_message(
        Message(message_id=42, webhook_id=WEBHOOK))[0]
    snapshot = dict(before)
    with _set_env(_env("enforce")):
        decision = ssv.check_message(Message(message_id=42,
                                             webhook_id=WEBHOOK))
    assert decision.allowed
    assert before == snapshot
    assert before["source_event_id"] == "discord:42:0"
    print("PASS source validation leaves sale identity untouched")


def test_command_paths_delegate_to_central_listener():
    source = open("commands_sales.py", encoding="utf-8").read()
    assert "backfill_channel" in source
    assert "auto_backfill" in source
    assert "extract_sales_from_message" not in source
    print("PASS manual sales commands delegate to validated listener paths")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and k != "test_collector"]
    for test in tests:
        test()
    print(f"ALL {len(tests)} F-18 SALES SOURCE TESTS PASSED")
