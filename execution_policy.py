"""
execution_policy.py — accuracy-first execution policy for VANTA 73.

Goals
-----
* Lightweight commands stay fast; research/time-consuming commands get a
  generous, configurable time budget instead of arbitrary short deadlines.
* Blocking work runs off the Discord event loop; users get an immediate
  acknowledgement / typing indicator and a truthful timeout or error report.
* All Roblox HTTP access can share one endpoint-aware scheduler: controlled
  concurrency, request pacing, Retry-After handling, bounded exponential
  backoff, per-endpoint circuit breaking, TTL caching, and in-flight request
  deduplication. Read-only GETs are retried; writes are not.

Nothing here changes scoring, ORACLE learning, or sales ingestion.
"""
import asyncio
import functools
import inspect
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

# ── Command classes ─────────────────────────────────────────────────
LIGHTWEIGHT = "lightweight"
DB_ANALYSIS = "db_analysis"
LIVE_RESEARCH = "live_research"
AI_REASONING = "ai_reasoning"
MULTI_STAGE = "multi_stage"
ADMIN = "admin"

# Default budgets (seconds). Deliberately generous for research; still bounded.
CLASS_BUDGETS = {
    LIGHTWEIGHT: 15,
    DB_ANALYSIS: 120,
    LIVE_RESEARCH: 240,
    AI_REASONING: 180,
    MULTI_STAGE: 600,
    ADMIN: 900,
}

LIGHTWEIGHT_COMMANDS = {
    "help", "guide", "version", "ver", "about", "ai_status", "dbtest",
    "scan_status", "emote_status", "sales_debug", "converge_debug",
    "momentum_debug", "data_audit", "integrity", "experiments", "labs",
    "results", "applied", "ignored", "logs", "log", "watchlist", "track",
}

DB_ANALYSIS_COMMANDS = {
    "gap", "velocity", "history", "trends", "patterns", "failures", "early",
    "momentum", "predict", "oracle", "nextwave", "opportunities", "verdict",
    "autopsy", "revive", "revive_item", "sales_keywords", "sales_words",
    "whales", "whale", "stealth", "stealth_desc", "hitrate", "hit_rate",
    "creator_brain", "meta", "cohort", "sales_report", "sales_for",
    "group_metrics", "gmetrics", "visibility", "emote", "classic",
    "opportunity", "suggest_probe", "probe_suggest",
}

LIVE_RESEARCH_COMMANDS = {
    "converge", "xray", "verified_scan", "scan_verified", "creative",
    "desc_forge", "analyze_image", "rescue", "tags",
}

AI_REASONING_COMMANDS = {
    "chain", "brainstorm", "creative_raw", "predict",
}

MULTI_STAGE_COMMANDS = {
    "rising_gaps", "nextwave", "opportunities", "converge",
}

ADMIN_COMMANDS = {
    "scan_run", "run_scanner", "enrich_run", "run_enricher", "suggest_run",
    "scrape_suggest", "train", "retrain", "snapshot_now", "sales_backfill",
    "sales_scan", "sales_post_now", "visibility_seed", "visibility_run",
    "launch", "log_launch", "launch_sync", "sync_launches", "ledger_sync",
    "sync_ledger", "selftest", "certify", "selftest_db", "healthcheck_db",
    "bot_update", "update_bot", "selfupdate", "playbook", "tactics",
    "path", "roadmap", "vacuum", "snipe", "revsim", "simulator",
    "golden_hour", "golden", "meta_sniper", "sniper", "link", "rename",
    "outcome", "cookie_check", "sales_probe", "creative_raw",
}

# Specific commands that combine stages outrank their other tags.
_PRIORITY = (
    (MULTI_STAGE_COMMANDS, MULTI_STAGE),
    (ADMIN_COMMANDS, ADMIN),
    (LIVE_RESEARCH_COMMANDS, LIVE_RESEARCH),
    (AI_REASONING_COMMANDS, AI_REASONING),
    (DB_ANALYSIS_COMMANDS, DB_ANALYSIS),
    (LIGHTWEIGHT_COMMANDS, LIGHTWEIGHT),
)


def classify(command_name):
    """Classify a command into one of the execution classes."""
    name = (command_name or "").strip().lstrip("!").lower()
    for group, cls in _PRIORITY:
        if name in group:
            return cls
    return LIGHTWEIGHT


def budget_seconds(command_name):
    """Per-command budget; override with VANTA_TIMEOUT_<COMMAND>."""
    name = (command_name or "").strip().lstrip("!").lower()
    env = os.getenv(f"VANTA_TIMEOUT_{name.upper().replace('-', '_')}")
    if env:
        try:
            return max(5.0, float(env))
        except (TypeError, ValueError):
            pass
    cls = classify(name)
    env_cls = os.getenv(f"VANTA_BUDGET_{cls.upper()}")
    if env_cls:
        try:
            return max(5.0, float(env_cls))
        except (TypeError, ValueError):
            pass
    return float(CLASS_BUDGETS.get(cls, CLASS_BUDGETS[LIGHTWEIGHT]))


# ── Discord delivery helpers ────────────────────────────────────────

def _typing_ctx(ctx):
    """Best-effort typing indicator context manager for message or interaction."""
    factory = getattr(getattr(ctx, "channel", None), "typing", None)
    if factory is None and getattr(ctx, "interaction", None) is not None:
        factory = getattr(ctx.interaction, "channel", None)
        factory = getattr(factory, "typing", None)
    if factory is None:
        class _Null:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
        return _Null()
    return factory()


async def deliver(ctx, content, *, embed=None, view=None):
    """Deliver a message to the right channel, tolerating interaction lifetime."""
    kwargs = {}
    if embed is not None:
        kwargs["embed"] = embed
    if view is not None:
        kwargs["view"] = view
    try:
        return await ctx.send(content, **kwargs)
    except Exception:
        pass
    followup = getattr(ctx, "followup", None)
    if followup is not None:
        try:
            return await followup.send(content, **kwargs)
        except Exception:
            pass
    channel = getattr(ctx, "channel", None)
    if channel is not None:
        try:
            return await channel.send(content, **kwargs)
        except Exception:
            pass
    return None


async def run_research(ctx, command, work, *, stages=None, send_result=True):
    """Run blocking research off the event loop under a bounded budget.

    ``work`` is a zero-argument callable executed in a worker thread. Returns
    its value, or None on timeout/failure. Users always receive a truthful
    acknowledgement and a timeout/error message; requests are never silently
    abandoned.
    """
    budget = budget_seconds(command)
    if budget >= 30:
        await deliver(ctx, f"🔎 `!{command}` is running (budget {int(budget)}s)…")
    try:
        async with _typing_ctx(ctx):
            result = await asyncio.wait_for(asyncio.to_thread(work), timeout=budget)
    except asyncio.TimeoutError:
        await deliver(
            ctx,
            f"⏱️ `!{command}` reached its {int(budget)}s research budget. "
            "No result was fabricated; narrow the scope or raise the budget.",
        )
        return None
    except asyncio.CancelledError:
        raise
    except Exception as e:
        await deliver(ctx, f"❌ `!{command}` failed: {type(e).__name__}: {e}")
        return None
    if send_result and result is not None:
        if isinstance(result, str):
            for chunk in [result[i:i + 1900] for i in range(0, len(result), 1900)]:
                await deliver(ctx, chunk)
        else:
            await deliver(ctx, str(result))
    return result


def research_command(command):
    """Decorator: bound an async command with the accuracy-first budget."""
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(ctx, *args, **kwargs):
            budget = budget_seconds(command)
            try:
                async with _typing_ctx(ctx):
                    return await asyncio.wait_for(
                        fn(ctx, *args, **kwargs), timeout=budget)
            except asyncio.TimeoutError:
                await deliver(
                    ctx,
                    f"⏱️ `!{command}` reached its {int(budget)}s research budget. "
                    "No result was fabricated.",
                )
                return None
            except asyncio.CancelledError:
                raise
            except Exception as e:
                await deliver(ctx, f"❌ `!{command}` failed: "
                                   f"{type(e).__name__}: {e}")
                return None
        wrapper.__signature__ = inspect.signature(fn)
        return wrapper
    return deco


# ── Centralized Roblox request scheduler ────────────────────────────

def _parse_retry_after(value):
    """Parse numeric or HTTP-date Retry-After into seconds; never raises."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return max(0.0, float(s))
    except (TypeError, ValueError):
        pass
    try:
        dt = parsedate_to_datetime(s)
        if dt is not None:
            return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        pass
    return None


@dataclass
class EndpointPolicy:
    rate_per_min: int = 60
    max_concurrency: int = 3
    cache_ttl: float = 300.0
    max_retries: int = 2
    backoff_base: float = 1.0
    backoff_cap: float = 30.0
    circuit_threshold: int = 3
    circuit_cooldown: float = 30.0
    max_cache_entries: int = 512


@dataclass
class SchedulerResult:
    ok: bool
    endpoint: str
    status: int = None
    headers: dict = field(default_factory=dict)
    data: object = None
    error: str = None
    cached: bool = False
    deduplicated: bool = False
    attempts: int = 0


class _Bucket:
    def __init__(self, rate_per_min, clock):
        self.rate = max(1.0, float(rate_per_min)) / 60.0
        self.capacity = max(1.0, self.rate * 5)
        self.tokens = self.capacity
        self.updated = clock()

    def acquire(self, clock, sleep):
        while True:
            now = clock()
            self.tokens = min(self.capacity,
                              self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return
            sleep(max((1.0 - self.tokens) / self.rate, 0.01))


class RobloxScheduler:
    """Endpoint-aware, thread-safe request scheduler (synchronous)."""

    def __init__(self, request_fn=None, clock=time.monotonic, sleep=time.sleep):
        self._request_fn = request_fn or self._default_request
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._policies = {}
        self._buckets = {}
        self._sems = {}
        self._cache = OrderedDict()
        self._inflight = {}
        self._results = {}
        self._circuit_until = {}
        self._circuit_fails = {}

    @staticmethod
    def _default_request(url, params=None, headers=None, timeout=12):
        return requests.get(url, params=params, headers=headers, timeout=timeout)

    def configure(self, endpoint, **kwargs):
        with self._lock:
            pol = self._policies.get(endpoint) or EndpointPolicy()
            for k, v in kwargs.items():
                if hasattr(pol, k):
                    setattr(pol, k, v)
            self._policies[endpoint] = pol
            self._buckets[endpoint] = _Bucket(pol.rate_per_min, self._clock)
            self._sems[endpoint] = threading.Semaphore(pol.max_concurrency)
        return pol

    def _policy(self, endpoint):
        with self._lock:
            pol = self._policies.get(endpoint)
        if pol is None:
            pol = self.configure(endpoint)
        return pol

    def reset(self):
        """Clear cache, in-flight state, and circuit breakers (tests/ops)."""
        with self._lock:
            self._cache.clear()
            self._inflight.clear()
            self._results.clear()
            self._circuit_until.clear()
            self._circuit_fails.clear()
            for endpoint, pol in self._policies.items():
                self._buckets[endpoint] = _Bucket(pol.rate_per_min, self._clock)

    def _circuit_open(self, endpoint):
        with self._lock:
            until = self._circuit_until.get(endpoint, 0.0)
        return self._clock() < until

    def _trip(self, endpoint, pol, retry_after=None):
        wait = _parse_retry_after(retry_after)
        if wait is None:
            wait = pol.circuit_cooldown
        wait = max(1.0, min(wait, 300.0))
        with self._lock:
            self._circuit_until[endpoint] = max(
                self._circuit_until.get(endpoint, 0.0), self._clock() + wait)

    def _success(self, endpoint):
        with self._lock:
            self._circuit_fails[endpoint] = 0

    def _failure(self, endpoint, pol):
        with self._lock:
            self._circuit_fails[endpoint] = self._circuit_fails.get(endpoint, 0) + 1
            fails = self._circuit_fails[endpoint]
        if fails >= pol.circuit_threshold:
            self._trip(endpoint, pol)

    def _cache_get(self, key, pol):
        if pol.cache_ttl <= 0:
            return None
        with self._lock:
            item = self._cache.get(key)
            if not item:
                return None
            ts, res = item
            if (self._clock() - ts) > pol.cache_ttl:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return res

    def _cache_put(self, key, res, pol):
        if pol.cache_ttl <= 0:
            return
        with self._lock:
            self._cache[key] = (self._clock(), res)
            self._cache.move_to_end(key)
            while len(self._cache) > pol.max_cache_entries:
                self._cache.popitem(last=False)

    def _backoff(self, attempt, pol, retry_after=None):
        ra = _parse_retry_after(retry_after)
        if ra is not None:
            return max(0.0, min(ra, pol.backoff_cap))
        return min(pol.backoff_cap, pol.backoff_base * (2 ** attempt))

    def request(self, endpoint, url, params=None, headers=None, timeout=12,
                method="GET", cache_key=None, use_cache=True):
        """Perform one logical request with pacing, retries, and dedup."""
        pol = self._policy(endpoint)
        if self._circuit_open(endpoint):
            return SchedulerResult(ok=False, endpoint=endpoint,
                                   error="circuit open")
        key = (endpoint, cache_key if cache_key is not None else
               (url, tuple(sorted((params or {}).items()))))

        if use_cache:
            cached = self._cache_get(key, pol)
            if cached is not None:
                return SchedulerResult(ok=True, endpoint=endpoint,
                                       status=cached.status,
                                       headers=dict(cached.headers or {}),
                                       data=cached.data, cached=True,
                                       attempts=cached.attempts)

        # In-flight deduplication (singleflight).
        leader = False
        with self._lock:
            ev = self._inflight.get(key)
            if ev is None:
                ev = threading.Event()
                self._inflight[key] = ev
                leader = True
        if not leader:
            ev.wait(timeout=max(1.0, timeout * 2))
            with self._lock:
                res = self._results.get(key)
            if res is not None:
                return SchedulerResult(ok=res.ok, endpoint=endpoint,
                                       status=res.status,
                                       headers=dict(res.headers or {}),
                                       data=res.data, error=res.error,
                                       cached=False, deduplicated=True,
                                       attempts=res.attempts)
            return SchedulerResult(ok=False, endpoint=endpoint,
                                   error="deduplicated request failed")

        retries = pol.max_retries if str(method).upper() == "GET" else 0
        result = SchedulerResult(ok=False, endpoint=endpoint)
        try:
            for attempt in range(retries + 1):
                result.attempts = attempt + 1
                bucket = self._buckets.get(endpoint)
                if bucket is not None:
                    bucket.acquire(self._clock, self._sleep)
                sem = self._sems.get(endpoint)
                if sem is not None:
                    sem.acquire()
                try:
                    resp = self._request_fn(url, params=params,
                                            headers=headers, timeout=timeout)
                except Exception as e:
                    result = SchedulerResult(ok=False, endpoint=endpoint,
                                             error=type(e).__name__,
                                             attempts=attempt + 1)
                    if attempt < retries:
                        self._sleep(self._backoff(attempt, pol))
                        continue
                    self._failure(endpoint, pol)
                    break
                finally:
                    if sem is not None:
                        sem.release()

                status = int(getattr(resp, "status_code", 0) or 0)
                headers_dict = dict(getattr(resp, "headers", {}) or {})
                result = SchedulerResult(ok=(status == 200), endpoint=endpoint,
                                         status=status, headers=headers_dict,
                                         attempts=attempt + 1)
                if status == 200:
                    try:
                        result.data = resp.json()
                    except Exception:
                        result.data = None
                    self._success(endpoint)
                    break
                if status == 429:
                    ra = headers_dict.get("Retry-After")
                    if attempt < retries:
                        self._sleep(self._backoff(attempt, pol, ra))
                        continue
                    result.error = "rate limited (429)"
                    self._trip(endpoint, pol, ra)
                    break
                if 500 <= status < 600:
                    if attempt < retries:
                        self._sleep(self._backoff(attempt, pol))
                        continue
                    result.error = f"server error ({status})"
                    self._failure(endpoint, pol)
                    break
                result.error = f"HTTP {status}"
                break
        finally:
            with self._lock:
                self._results[key] = result
                if len(self._results) > pol.max_cache_entries:
                    self._results.pop(next(iter(self._results)), None)
                self._inflight.pop(key, None)
            ev.set()

        if result.ok and use_cache:
            self._cache_put(key, result, pol)
        return result


_DEFAULT_SCHEDULER = None
_DEFAULT_LOCK = threading.Lock()


def default_scheduler():
    global _DEFAULT_SCHEDULER
    with _DEFAULT_LOCK:
        if _DEFAULT_SCHEDULER is None:
            _DEFAULT_SCHEDULER = RobloxScheduler()
        return _DEFAULT_SCHEDULER


def reset_default_scheduler(scheduler=None):
    global _DEFAULT_SCHEDULER
    with _DEFAULT_LOCK:
        _DEFAULT_SCHEDULER = scheduler
