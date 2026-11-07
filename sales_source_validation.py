"""Prepared sales-source allowlist validation (not wired into ingestion).

Modes:
- off: preserve current ingestion behavior.
- dry-run: accept for now, but flag would-reject messages for observation.
- enforce: reject before parsing/writing.

Enforcement is intentionally not enabled by this module or the listener. A
separate reviewed rollout must provide approved webhook/sender IDs.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceDecision:
    allowed: bool
    would_reject: bool
    reason: str
    source_kind: str = "unknown"
    source_id: str = ""


def _id(value):
    return "" if value is None else str(value)


def validate_sales_message(message, mode="off", channel_id=None,
                           webhook_ids=(), sender_ids=()):
    mode = str(mode or "off").lower()
    if mode not in {"off", "dry-run", "enforce"}:
        raise ValueError(
            "invalid sales source mode; expected off, dry-run, or enforce")

    channel = getattr(message, "channel", None)
    actual_channel = _id(getattr(channel, "id", None))
    expected_channel = _id(channel_id)
    channel_ok = not expected_channel or actual_channel == expected_channel

    webhook_id = _id(getattr(message, "webhook_id", None))
    author = getattr(message, "author", None)
    author_id = _id(getattr(author, "id", None))
    author_is_bot = bool(getattr(author, "bot", False))
    trusted_webhooks = {_id(x) for x in (webhook_ids or ()) if _id(x)}
    trusted_senders = {_id(x) for x in (sender_ids or ()) if _id(x)}

    if webhook_id and webhook_id in trusted_webhooks:
        source_kind, source_id, trusted = "webhook", webhook_id, True
    elif author_is_bot and author_id in trusted_senders:
        source_kind, source_id, trusted = "bot_user", author_id, True
    else:
        source_kind, source_id, trusted = (
            "webhook" if webhook_id else "user", webhook_id or author_id, False)

    if mode == "off":
        return SourceDecision(True, False, "source validation disabled",
                              source_kind, source_id)
    if not channel_ok:
        return SourceDecision(
            mode != "enforce", True,
            "message is not in the approved sales channel",
            source_kind, source_id)
    if not trusted:
        return SourceDecision(
            mode != "enforce", True,
            "message source is not an approved webhook or sender",
            source_kind, source_id)
    return SourceDecision(True, False, "approved source",
                          source_kind, source_id)
