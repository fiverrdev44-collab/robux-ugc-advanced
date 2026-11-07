"""Shared read-only Roblox HTTP wrapper for command/helper paths.

All GETs routed here use the process-wide execution_policy scheduler, which
provides pacing, in-flight dedupe, Retry-After handling, and circuit breaking.
Retries are disabled by default for these diagnostic/helper paths so the number
of physical requests is not increased; 429s are surfaced or deferred.
"""
import json
import threading
import time
from collections import deque

import requests

from execution_policy import (
    RobloxScheduler,
    SchedulerResult,
    _parse_retry_after,
    default_scheduler,
)

_SCHEDULER = None
_CONFIGURED = set()
_POST_TIMES = deque()
_POST_LOCK = threading.Lock()
_POST_CIRCUIT_UNTIL = 0.0
_POST_RATE_PER_MIN = 20

_ENDPOINTS = {
    "catalog_search": {"rate_per_min": 30, "max_concurrency": 2},
    "desc_search": {"rate_per_min": 30, "max_concurrency": 2},
    "games_search": {"rate_per_min": 20, "max_concurrency": 2},
    "groups": {"rate_per_min": 20, "max_concurrency": 2},
    "recovery_live": {"rate_per_min": 30, "max_concurrency": 2},
    "sales_probe": {"rate_per_min": 20, "max_concurrency": 2},
    "suggest": {"rate_per_min": 30, "max_concurrency": 2},
    "users": {"rate_per_min": 20, "max_concurrency": 2},
}


class SafeResponse:
    def __init__(self, result, body=None):
        self.result = result
        self.status_code = int(
            result.status if result.status is not None else 200 if result.ok
            else 0)
        self.headers = dict(result.headers or {})
        self.retry_after = result.retry_after
        self.deferred = bool(result.deferred)
        self.error = result.error
        self._data = result.data
        self._body = body

    @property
    def ok(self):
        return self.result.ok

    @property
    def text(self):
        if self._body is not None:
            return str(self._body)
        if self._data is not None:
            try:
                return json.dumps(self._data)
            except Exception:
                return str(self._data)
        return str(self.error or "")

    def json(self):
        return self._data


def _scheduler():
    global _SCHEDULER
    if _SCHEDULER is not None:
        return _SCHEDULER
    scheduler = default_scheduler()
    for endpoint, config in _ENDPOINTS.items():
        if endpoint not in _CONFIGURED:
            scheduler.configure(
                endpoint,
                rate_per_min=config["rate_per_min"],
                max_concurrency=config["max_concurrency"],
                cache_ttl=0,
                max_retries=0,
                circuit_threshold=1,
                circuit_cooldown=30.0,
                retry_after_budget=60.0,
                honor_retry_after=True,
            )
            _CONFIGURED.add(endpoint)
    return scheduler


def get(endpoint, url, params=None, headers=None, timeout=12, cache_key=None):
    scheduler = _scheduler()
    result = scheduler.request(
        endpoint, url, params=params, headers=headers, timeout=timeout,
        cache_key=cache_key, use_cache=False)
    return SafeResponse(result)


def shared_circuit_open(endpoint="catalog_search"):
    if time.monotonic() < _POST_CIRCUIT_UNTIL:
        return True
    try:
        return default_scheduler().is_circuit_open(endpoint)
    except Exception:
        return False


def trip_shared_circuit(retry_after=None, endpoint="catalog_search"):
    global _POST_CIRCUIT_UNTIL
    wait = _parse_retry_after(retry_after)
    if wait is None:
        wait = 30.0
    wait = max(1.0, min(float(wait), 3600.0))
    with _POST_LOCK:
        _POST_CIRCUIT_UNTIL = max(_POST_CIRCUIT_UNTIL,
                                  time.monotonic() + wait)
    try:
        default_scheduler().trip(endpoint, retry_after)
    except Exception:
        pass


def _post_budget_available(now=None):
    now = time.monotonic() if now is None else float(now)
    cutoff = now - 60.0
    with _POST_LOCK:
        while _POST_TIMES and _POST_TIMES[0] < cutoff:
            _POST_TIMES.popleft()
        if len(_POST_TIMES) >= _POST_RATE_PER_MIN:
            return False
        _POST_TIMES.append(now)
        return True


def post(url, json=None, headers=None, timeout=15,
         endpoint="roblox_post"):
    """One bounded POST attempt sharing the global Roblox circuit/budget.

    No retry loop is added here; command-specific CSRF handling remains in the
    caller. A 429 or an already-open circuit defers without a request.
    """
    if shared_circuit_open():
        return SafeResponse(SchedulerResult(
            ok=False, endpoint=endpoint, status=0,
            error="circuit open", deferred=True))
    if not _post_budget_available():
        return SafeResponse(SchedulerResult(
            ok=False, endpoint=endpoint, status=0,
            error="POST budget exhausted", deferred=True))
    try:
        resp = requests.post(url, json=json, headers=headers,
                             timeout=timeout)
    except Exception as exc:
        return SafeResponse(SchedulerResult(
            ok=False, endpoint=endpoint, status=0,
            error=type(exc).__name__))
    status = int(getattr(resp, "status_code", 0) or 0)
    body = getattr(resp, "text", "")
    headers_dict = dict(getattr(resp, "headers", {}) or {})
    result = SchedulerResult(ok=status == 200, endpoint=endpoint,
                             status=status, headers=headers_dict,
                             attempts=1)
    if status == 429:
        ra = headers_dict.get("Retry-After")
        result.retry_after = _parse_retry_after(ra)
        result.error = "rate limited (429)"
        result.deferred = True
        trip_shared_circuit(ra)
    elif status >= 400:
        result.error = f"HTTP {status}"
    else:
        try:
            result.data = resp.json()
        except Exception:
            result.data = None
    return SafeResponse(result, body=body)


def set_scheduler_for_tests(scheduler=None):
    """Inject a deterministic scheduler for tests; None restores the default."""
    global _SCHEDULER
    _SCHEDULER = scheduler


def reset_for_tests():
    global _SCHEDULER, _POST_CIRCUIT_UNTIL
    _SCHEDULER = None
    _CONFIGURED.clear()
    with _POST_LOCK:
        _POST_TIMES.clear()
        _POST_CIRCUIT_UNTIL = 0.0
