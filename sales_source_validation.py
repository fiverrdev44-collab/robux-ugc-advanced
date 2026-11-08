"""Central Discord sales-source authentication (F-18).

Modes:
- off: preserve ingestion; authentication absence is visible in diagnostics.
- dry-run: evaluate every message, record would-reject decisions, never block.
- enforce: reject before embed parsing/database access.

Trusted identities come only from approved configuration. A webhook_id always
takes precedence: an unapproved webhook cannot become trusted through an
apparent bot author ID.
"""
import os
import re
import threading
from dataclasses import dataclass, field

MODES = {"off", "dry-run", "enforce"}
_ID_RE = re.compile(r"^\d{5,25}$")


@dataclass(frozen=True)
class SourceConfig:
    mode: str = "off"
    channel_id: str = ""
    guild_id: str = ""
    webhook_ids: frozenset = field(default_factory=frozenset)
    sender_ids: frozenset = field(default_factory=frozenset)
    error: str = ""


@dataclass(frozen=True)
class SourceDecision:
    allowed: bool
    would_reject: bool
    reason: str
    source_kind: str = "unknown"
    source_id: str = ""
    mode: str = "off"
    message_id: str = ""
    channel_id: str = ""
    guild_id: str = ""


_DIAG_LOCK = threading.Lock()
_DIAG = {
    "evaluated": 0,
    "allowed": 0,
    "would_reject": 0,
    "rejected": 0,
    "accepted_webhook": 0,
    "accepted_bot": 0,
    "disabled": 0,
    "by_reason": {},
}


def _id(value):
    return "" if value is None else str(value)


def _split_ids(raw):
    parts = [p for p in re.split(r"[,\s]+", str(raw or "").strip()) if p]
    return frozenset(parts), [p for p in parts if not _ID_RE.match(p)]


def load_config(env=None):
    """Read the approved allowlist from environment; never invent IDs."""
    env = os.environ if env is None else env
    raw_mode = str(env.get("SALES_SOURCE_MODE", "off") or "off").strip().lower()
    channel = _id(env.get("SALES_CHANNEL_ID", "")).strip()
    guild = _id(env.get("SALES_GUILD_ID", "")).strip()
    webhooks, bad_webhooks = _split_ids(env.get("SALES_WEBHOOK_IDS", ""))
    senders, bad_senders = _split_ids(env.get("SALES_SOURCE_USER_IDS", ""))

    problems = []
    if raw_mode not in MODES:
        problems.append("invalid sales source mode")
    for label, value in (("SALES_CHANNEL_ID", channel),
                         ("SALES_GUILD_ID", guild)):
        if value and not _ID_RE.match(value):
            problems.append(f"invalid {label}")
    if bad_webhooks:
        problems.append("invalid SALES_WEBHOOK_IDS entry")
    if bad_senders:
        problems.append("invalid SALES_SOURCE_USER_IDS entry")
    if raw_mode == "enforce":
        if not channel:
            problems.append("missing SALES_CHANNEL_ID")
        if not webhooks and not senders:
            problems.append("missing trusted webhook/sender allowlist")

    return SourceConfig(
        mode=raw_mode,
        channel_id=channel,
        guild_id=guild,
        webhook_ids=webhooks,
        sender_ids=senders,
        error="; ".join(problems),
    )


def _evaluate(message, config):
    channel = getattr(message, "channel", None)
    actual_channel = _id(getattr(channel, "id", None))
    guild = getattr(message, "guild", None)
    actual_guild = _id(getattr(guild, "id", None))
    message_id = _id(getattr(message, "id", None))

    webhook_id = _id(getattr(message, "webhook_id", None))
    author = getattr(message, "author", None)
    author_id = _id(getattr(author, "id", None))
    author_is_bot = bool(getattr(author, "bot", False))

    if webhook_id:
        source_kind = "webhook"
        source_id = webhook_id
        trusted_source = webhook_id in config.webhook_ids
        source_reason = ("approved webhook" if trusted_source
                         else "unapproved webhook")
    elif author_is_bot and author_id in config.sender_ids:
        source_kind = "bot_user"
        source_id = author_id
        trusted_source = True
        source_reason = "approved bot sender"
    elif author_is_bot:
        source_kind = "bot_user"
        source_id = author_id
        trusted_source = False
        source_reason = "unapproved bot sender"
    elif author_id:
        source_kind = "user"
        source_id = author_id
        trusted_source = False
        source_reason = "human sender is not an approved webhook or bot source"
    else:
        source_kind = "unknown"
        source_id = ""
        trusted_source = False
        source_reason = "missing source metadata"

    channel_ok = bool(config.channel_id) and actual_channel == config.channel_id
    guild_ok = (not config.guild_id) or actual_guild == config.guild_id

    if config.mode == "invalid":
        return SourceDecision(
            False, True, "invalid sales source configuration",
            source_kind, source_id, "invalid", message_id, actual_channel,
            actual_guild)
    if config.mode == "off":
        return SourceDecision(
            True, False,
            ("source validation disabled"
             + (" (configuration incomplete)" if config.error else "")),
            source_kind, source_id, "off", message_id, actual_channel,
            actual_guild)

    reason = source_reason
    if config.error:
        reason = "invalid sales source configuration"
    elif not guild_ok:
        reason = "message is not in the approved sales guild"
    elif not channel_ok:
        reason = "message is not in the approved sales channel"

    trusted = bool(trusted_source and channel_ok and guild_ok
                   and not config.error)
    would_reject = not trusted
    allowed = (config.mode != "enforce") or trusted
    if trusted:
        reason = "approved source"
    return SourceDecision(
        allowed, would_reject, reason, source_kind, source_id, config.mode,
        message_id, actual_channel, actual_guild)


def validate_message(message, config=None):
    """Pure central validation. Does not parse embeds or touch the database."""
    config = config or load_config()
    if config.mode not in MODES:
        return SourceDecision(
            False, True, "invalid sales source configuration",
            "unknown", "", config.mode or "invalid",
            _id(getattr(message, "id", None)),
            _id(getattr(getattr(message, "channel", None), "id", None)),
            _id(getattr(getattr(message, "guild", None), "id", None)))
    return _evaluate(message, config)


def check_message(message, config=None):
    """Validate, record safe diagnostics, and log safe metadata."""
    decision = validate_message(message, config)
    record_decision(decision)
    log_decision(decision)
    return decision


def record_decision(decision):
    with _DIAG_LOCK:
        _DIAG["evaluated"] += 1
        if decision.allowed:
            _DIAG["allowed"] += 1
        if decision.would_reject:
            _DIAG["would_reject"] += 1
        if not decision.allowed:
            _DIAG["rejected"] += 1
        if decision.reason == "approved source":
            if decision.source_kind == "webhook":
                _DIAG["accepted_webhook"] += 1
            elif decision.source_kind == "bot_user":
                _DIAG["accepted_bot"] += 1
        if decision.mode == "off":
            _DIAG["disabled"] += 1
        reason = decision.reason or "unknown"
        _DIAG["by_reason"][reason] = _DIAG["by_reason"].get(reason, 0) + 1


def diagnostics_snapshot():
    with _DIAG_LOCK:
        return {
            "evaluated": _DIAG["evaluated"],
            "allowed": _DIAG["allowed"],
            "would_reject": _DIAG["would_reject"],
            "rejected": _DIAG["rejected"],
            "accepted_webhook": _DIAG["accepted_webhook"],
            "accepted_bot": _DIAG["accepted_bot"],
            "disabled": _DIAG["disabled"],
            "by_reason": dict(_DIAG["by_reason"]),
        }


def reset_diagnostics():
    with _DIAG_LOCK:
        for key in ("evaluated", "allowed", "would_reject", "rejected",
                    "accepted_webhook", "accepted_bot", "disabled"):
            _DIAG[key] = 0
        _DIAG["by_reason"].clear()


def log_decision(decision):
    """Safe operational log: never message content, names, tokens or URLs."""
    print(
        "[sales-source] "
        f"mode={decision.mode} decision={'allow' if decision.allowed else 'reject'} "
        f"would_reject={decision.would_reject} reason={decision.reason} "
        f"source={decision.source_kind} message_id={decision.message_id or '-'} "
        f"channel_id={decision.channel_id or '-'} "
        f"guild_id={decision.guild_id or '-'}",
        flush=True,
    )


def validate_sales_message(message, mode="off", channel_id=None,
                           webhook_ids=(), sender_ids=()):
    """Backward-compatible pure validator used by legacy tests."""
    mode = str(mode or "off").lower()
    if mode not in MODES:
        raise ValueError(
            "invalid sales source mode; expected off, dry-run, or enforce")
    config = SourceConfig(
        mode=mode,
        channel_id=_id(channel_id),
        webhook_ids=frozenset(_id(x) for x in (webhook_ids or ()) if _id(x)),
        sender_ids=frozenset(_id(x) for x in (sender_ids or ()) if _id(x)),
    )
    return _evaluate(message, config)
