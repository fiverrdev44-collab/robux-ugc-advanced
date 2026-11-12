"""Central Discord command authorization and AI-cost controls.

The policy is fail-closed: an unclassified command is treated as owner-only,
and aliases are canonicalized before lookup. Authorization happens before any
command callback, database access, Roblox request, or AI provider call.
"""
import os
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from discord.ext import commands


ALL_COMMANDS = {
    "ai_debug", "ai_status", "analyze", "analyze_image", "background_analyze", "applied", "autopsy",
    "bot_update", "brainstorm", "chain", "classic", "concept", "converge",
    "converge_debug", "cookie_check", "creative", "creative_raw",
    "creator_brain", "data_audit", "dbtest", "desc_analyze", "desc_forge",
    "early", "emote", "emote_status", "emote_title", "enrich_run",
    "experiments", "failures", "gap", "golden_hour", "group_metrics", "guide",
    "help", "history", "hitrate", "ignored", "launch", "launch_sync",
    "ledger_sync", "link", "logs", "meta_sniper", "momentum",
    "momentum_debug", "nextwave", "opportunities", "opportunity", "oracle",
    "outcome", "path", "patterns", "playbook", "predict", "rename", "rescue",
    "revive", "revsim", "rising_gaps", "sales_backfill", "sales_debug",
    "sales_for", "sales_keywords", "sales_post_now", "sales_probe",
    "sales_report", "sales_scan", "scan_run", "scan_status", "selftest",
    "selftest_db", "snapshot_now", "start", "stealth", "suggest_probe",
    "suggest_run", "tags", "track", "train", "trends", "vacuum", "velocity",
    "verdict", "verified_scan", "version", "visibility", "visibility_run",
    "visibility_seed", "watchlist", "whales", "xray",
}

OWNER_ONLY = {
    "ai_debug", "analyze_image", "background_analyze", "applied", "autopsy", "bot_update",
    "brainstorm", "chain", "concept", "converge_debug", "cookie_check",
    "creative", "creative_raw", "data_audit", "dbtest", "desc_analyze",
    "desc_forge", "enrich_run", "group_metrics", "ignored", "launch",
    "creator_brain", "hitrate", "verdict",
    "launch_sync", "ledger_sync", "link", "logs", "meta_sniper",
    "momentum_debug", "outcome", "path", "playbook", "rename", "rescue",
    "revive", "revsim", "sales_backfill", "sales_debug",
    "sales_keywords", "sales_post_now", "sales_probe",
    "sales_scan", "scan_run", "selftest", "selftest_db", "snapshot_now",
    "stealth", "suggest_probe", "suggest_run", "tags", "train", "vacuum",
    "verified_scan", "visibility_run", "visibility_seed",
}

PUBLIC_RATE_LIMITED = {"emote_title"}
USER_SCOPED_WRITE = {"guide"}
OWNER_GATED_MUTATION = {"experiments"}

AI_COST = {
    "ai_debug", "analyze_image", "background_analyze", "autopsy", "brainstorm", "chain", "concept",
    "creative", "creative_raw", "desc_analyze", "desc_forge", "emote_title",
    "meta_sniper", "path", "playbook", "rescue", "revive", "revsim",
    "sales_keywords", "stealth", "tags",
}

MUTATING = {
    "applied", "creator_brain", "hitrate", "ignored", "link", "outcome",
    "rename", "snapshot_now", "sales_backfill", "sales_post_now",
    "visibility_seed", "visibility_run", "launch", "launch_sync",
    "ledger_sync", "scan_run", "enrich_run", "train", "sales_scan",
    "selftest", "suggest_run", "verdict",
}

EXTERNAL_API = {
    "autopsy", "converge", "converge_debug", "emote_title", "enrich_run",
    "hitrate", "meta_sniper", "revive", "sales_probe", "sales_scan",
    "scan_run", "selftest", "snapshot_now", "suggest_probe", "suggest_run",
    "vacuum", "verdict", "verified_scan", "visibility_run", "visibility_seed",
}

SENSITIVE = {
    "ai_debug", "converge_debug", "cookie_check", "data_audit", "dbtest",
    "group_metrics", "logs", "momentum_debug", "sales_debug", "sales_probe",
    "sales_scan", "selftest", "selftest_db",
}

PUBLIC_COMMANDS = ALL_COMMANDS - OWNER_ONLY
PUBLIC_MUTATING = USER_SCOPED_WRITE | OWNER_GATED_MUTATION
PUBLIC_READ_ONLY = PUBLIC_COMMANDS - PUBLIC_RATE_LIMITED - PUBLIC_MUTATING

COMMAND_ALIASES = {
    "about": "version", "apply_rec": "applied", "certify": "selftest",
    "cohort": "creator_brain", "gmetrics": "group_metrics",
    "golden": "golden_hour", "healthcheck_db": "selftest_db",
    "hit_rate": "hitrate", "integrity": "data_audit", "labs": "experiments",
    "log": "logs", "log_launch": "launch", "meta": "creator_brain",
    "probe_suggest": "suggest_probe", "results": "experiments",
    "retrain": "train", "revive_item": "revive", "roadmap": "path",
    "run_enricher": "enrich_run", "run_scanner": "scan_run",
    "sales_words": "sales_keywords", "scrape_suggest": "suggest_run",
    "selfupdate": "bot_update", "simulator": "revsim", "skip_rec": "ignored",
    "snipe": "vacuum", "sniper": "meta_sniper", "stealth_desc": "stealth",
    "sync_launches": "launch_sync", "sync_ledger": "ledger_sync",
    "tactics": "playbook", "update_bot": "bot_update", "ver": "version",
    "whale": "whales", "scan_verified": "verified_scan",
}


async def authorize_before_invoke(ctx):
    """Discord before_invoke hook shared by production and integration tests."""
    decision = authorize_command(ctx.command.name, ctx.author.id)
    if not decision.allowed:
        raise CommandNotAuthorized(decision.reason)


class CommandNotAuthorized(commands.CheckFailure):
    """Raised before a denied command callback is invoked."""


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    command: str
    level: str
    reason: str = ""
    ai_rate_limited: bool = False


def canonical_command_name(name):
    key = str(name or "").strip().lower().lstrip("!")
    return COMMAND_ALIASES.get(key, key)


def policy_for(name):
    canonical = canonical_command_name(name)
    if canonical not in ALL_COMMANDS:
        return {
            "command": canonical,
            "level": "owner",
            "mutating": False,
            "ai_cost": False,
            "external_api": False,
            "sensitive": True,
            "public_exception": False,
            "user_scoped_write": False,
            "owner_gated_mutation": False,
            "known": False,
        }
    return {
        "command": canonical,
        "level": "owner" if canonical in OWNER_ONLY else "public",
        "mutating": (canonical in MUTATING
                     or canonical in USER_SCOPED_WRITE
                     or canonical in OWNER_GATED_MUTATION),
        "ai_cost": canonical in AI_COST,
        "external_api": canonical in EXTERNAL_API,
        "sensitive": canonical in SENSITIVE,
        "public_exception": canonical in PUBLIC_RATE_LIMITED,
        "user_scoped_write": canonical in USER_SCOPED_WRITE,
        "owner_gated_mutation": canonical in OWNER_GATED_MUTATION,
        "known": True,
    }


def _owner_ids():
    ids = set()
    try:
        from commands_supercomputer import BOT_OWNERS
        ids.update(int(x) for x in BOT_OWNERS)
    except Exception:
        pass
    for key in ("BOT_OWNER_ID", "DISCORD_OWNER_ID"):
        for part in (os.getenv(key) or "").replace(",", " ").split():
            try:
                ids.add(int(part))
            except (TypeError, ValueError):
                continue
    return ids


def is_owner(user_id):
    try:
        return int(user_id) in _owner_ids()
    except (TypeError, ValueError):
        return False


class AIUsageLimiter:
    """Sliding-window per-user and global limits for AI-cost commands."""

    def __init__(self):
        self._lock = threading.Lock()
        self.configure()

    def configure(self, user_limit=None, owner_limit=None,
                  global_limit=None, window_seconds=None):
        def _env_int(name, default):
            try:
                return max(1, int(os.getenv(name, str(default))))
            except (TypeError, ValueError):
                return default

        self.user_limit = max(1, int(
            user_limit if user_limit is not None
            else _env_int("M6_AI_USER_LIMIT", 5)))
        self.owner_limit = max(1, int(
            owner_limit if owner_limit is not None
            else _env_int("M6_AI_OWNER_LIMIT", 20)))
        self.global_limit = max(1, int(
            global_limit if global_limit is not None
            else _env_int("M6_AI_GLOBAL_LIMIT", 30)))
        self.window_seconds = max(1, int(
            window_seconds if window_seconds is not None
            else _env_int("M6_AI_WINDOW_SECONDS", 600)))
        self._user = defaultdict(deque)
        self._global = deque()

    def reset(self):
        with self._lock:
            self._user.clear()
            self._global.clear()

    def allow(self, user_id, owner=False, now=None):
        now = time.monotonic() if now is None else float(now)
        cutoff = now - self.window_seconds
        with self._lock:
            while self._global and self._global[0] < cutoff:
                self._global.popleft()
            user = self._user[user_id]
            while user and user[0] < cutoff:
                user.popleft()
            if len(self._global) >= self.global_limit:
                return False, "global AI usage limit reached"
            limit = self.owner_limit if owner else self.user_limit
            if len(user) >= limit:
                return False, "per-user AI usage limit reached"
            self._global.append(now)
            user.append(now)
            return True, ""


def _env_int(name, default):
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


AI_LIMITER = AIUsageLimiter()
PLANNER_LIMITER = AIUsageLimiter()
PLANNER_LIMITER.configure(
    user_limit=_env_int("M6_PLANNER_USER_LIMIT", 20),
    owner_limit=_env_int("M6_PLANNER_OWNER_LIMIT", 100),
    global_limit=_env_int("M6_PLANNER_GLOBAL_LIMIT", 200),
    window_seconds=_env_int("M6_PLANNER_WINDOW_SECONDS", 3600),
)
PUBLIC_EMOTE_LIMITER = AIUsageLimiter()
PUBLIC_EMOTE_LIMITER.configure(
    user_limit=_env_int("M6_EMOTE_TITLE_USER_LIMIT", 10),
    owner_limit=_env_int("M6_EMOTE_TITLE_OWNER_LIMIT", 20),
    global_limit=_env_int("M6_EMOTE_TITLE_GLOBAL_LIMIT", 30),
    window_seconds=_env_int("M6_EMOTE_TITLE_WINDOW_SECONDS", 600),
)


def allow_planner_ai(user_id, owner=False, now=None):
    return PLANNER_LIMITER.allow(user_id, owner=owner, now=now)


def reset_for_tests():
    AI_LIMITER.reset()
    PLANNER_LIMITER.reset()
    PUBLIC_EMOTE_LIMITER.reset()


def configure_for_tests(user_limit=None, owner_limit=None,
                        global_limit=None, window_seconds=None):
    AI_LIMITER.configure(user_limit=user_limit, owner_limit=owner_limit,
                         global_limit=global_limit,
                         window_seconds=window_seconds)


def configure_planner_for_tests(user_limit=None, owner_limit=None,
                                global_limit=None, window_seconds=None):
    PLANNER_LIMITER.configure(user_limit=user_limit,
                              owner_limit=owner_limit,
                              global_limit=global_limit,
                              window_seconds=window_seconds)


def configure_emote_title_for_tests(user_limit=None, owner_limit=None,
                                    global_limit=None, window_seconds=None):
    PUBLIC_EMOTE_LIMITER.configure(user_limit=user_limit,
                                   owner_limit=owner_limit,
                                   global_limit=global_limit,
                                   window_seconds=window_seconds)


def authorize_command(name, user_id, now=None):
    policy = policy_for(name)
    canonical = policy["command"]
    if not policy["known"]:
        return AuthorizationDecision(
            False, canonical, "owner",
            "Unknown command policy; denied by default.")
    if policy["level"] == "owner" and not is_owner(user_id):
        return AuthorizationDecision(
            False, canonical, "owner", "This command is owner-only.")
    if policy["ai_cost"]:
        limiter = (PUBLIC_EMOTE_LIMITER
                   if policy["public_exception"] else AI_LIMITER)
        allowed, reason = limiter.allow(
            user_id, owner=is_owner(user_id), now=now)
        if not allowed:
            return AuthorizationDecision(
                False, canonical, policy["level"], reason,
                ai_rate_limited=True)
    return AuthorizationDecision(True, canonical, policy["level"])


def require_authorized(name, user_id, now=None):
    decision = authorize_command(name, user_id, now=now)
    if not decision.allowed:
        raise CommandNotAuthorized(decision.reason)
    return decision


def denial_message(reason):
    return f"🚫 Command denied: {reason}"


_SECRET_ENV_KEYS = (
    "GEMINI_API_KEY", "OPENROUTER_API_KEY", "TOKEN", "DISCORD_TOKEN",
    "ROBLOSECURITY_COOKIE", "ROBLOSECURITY_COOKIE_1",
    "ROBLOSECURITY_COOKIE_2", "ROBLOSECURITY_COOKIE_3", "DATABASE_URL",
)


def redact_secrets(text):
    """Remove configured secret values and common key formats from text."""
    result = str(text or "")
    for key in _SECRET_ENV_KEYS:
        value = (os.getenv(key) or "").strip()
        if len(value) >= 6:
            result = result.replace(value, "[redacted]")
    result = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[redacted-api-key]", result)
    result = re.sub(r"sk-[A-Za-z0-9_-]{10,}", "[redacted-api-key]", result)
    return result
