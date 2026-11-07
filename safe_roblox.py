"""Shared read-only Roblox HTTP wrapper for command/helper paths.

All GETs routed here use the process-wide execution_policy scheduler, which
provides pacing, in-flight dedupe, Retry-After handling, and circuit breaking.
Retries are disabled by default for these diagnostic/helper paths so the number
of physical requests is not increased; 429s are surfaced or deferred.
"""
import json

from execution_policy import RobloxScheduler, default_scheduler

_SCHEDULER = None
_CONFIGURED = set()

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
    def __init__(self, result):
        self.result = result
        self.status_code = int(
            result.status if result.status is not None else 200 if result.ok
            else 0)
        self.headers = dict(result.headers or {})
        self.retry_after = result.retry_after
        self.deferred = bool(result.deferred)
        self.error = result.error
        self._data = result.data

    @property
    def ok(self):
        return self.result.ok

    @property
    def text(self):
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


def set_scheduler_for_tests(scheduler=None):
    """Inject a deterministic scheduler for tests; None restores the default."""
    global _SCHEDULER
    _SCHEDULER = scheduler


def reset_for_tests():
    global _SCHEDULER
    _SCHEDULER = None
    _CONFIGURED.clear()
