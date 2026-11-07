"""Mocked-message tests for the prepared sales-source allowlist design."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sales_source_validation import validate_sales_message  # noqa: E402


class Channel:
    def __init__(self, channel_id):
        self.id = channel_id


class Author:
    def __init__(self, author_id, bot=False):
        self.id = author_id
        self.bot = bot


class Message:
    def __init__(self, channel_id=10, webhook_id=None, author_id=20,
                 bot=False):
        self.channel = Channel(channel_id)
        self.webhook_id = webhook_id
        self.author = Author(author_id, bot)


def test_off_mode_preserves_current_behavior():
    decision = validate_sales_message(Message(), mode="off",
                                      channel_id=10,
                                      webhook_ids={"999"},
                                      sender_ids={"888"})
    assert decision.allowed
    assert not decision.would_reject
    print("PASS off mode preserves ingestion behavior")


def test_dry_run_flags_untrusted_without_blocking():
    decision = validate_sales_message(Message(), mode="dry-run",
                                      channel_id=10,
                                      webhook_ids={"999"},
                                      sender_ids={"888"})
    assert decision.allowed
    assert decision.would_reject
    assert "not an approved" in decision.reason
    print("PASS dry-run flags untrusted without blocking")


def test_enforce_accepts_trusted_webhook_and_bot_sender():
    webhook = validate_sales_message(
        Message(webhook_id=999), mode="enforce", channel_id=10,
        webhook_ids={"999"}, sender_ids={"888"})
    assert webhook.allowed and webhook.source_kind == "webhook"

    bot = validate_sales_message(
        Message(author_id=888, bot=True), mode="enforce", channel_id=10,
        webhook_ids={"999"}, sender_ids={"888"})
    assert bot.allowed and bot.source_kind == "bot_user"
    print("PASS enforce accepts trusted webhook and bot sender")


def test_enforce_rejects_untrusted_user_and_wrong_channel():
    user = validate_sales_message(
        Message(author_id=777), mode="enforce", channel_id=10,
        webhook_ids={"999"}, sender_ids={"888"})
    assert not user.allowed and user.would_reject

    wrong = validate_sales_message(
        Message(channel_id=11, webhook_id=999), mode="enforce",
        channel_id=10, webhook_ids={"999"})
    assert not wrong.allowed
    assert "approved sales channel" in wrong.reason
    print("PASS enforce rejects untrusted user and wrong channel")


def test_invalid_mode_falls_back_to_off():
    decision = validate_sales_message(Message(), mode="bogus",
                                      channel_id=10)
    assert decision.allowed
    assert not decision.would_reject
    print("PASS invalid mode fails safe to off")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL {len(tests)} SALES SOURCE TESTS PASSED")
