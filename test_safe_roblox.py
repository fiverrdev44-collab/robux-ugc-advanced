"""Failure-injection tests for the shared read-only Roblox wrapper."""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from execution_policy import RobloxScheduler  # noqa: E402
import safe_roblox  # noqa: E402


class Response:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


def _scheduler(request_fn):
    s = RobloxScheduler(request_fn=request_fn, sleep=lambda seconds: None)
    s.configure("catalog_search", rate_per_min=100000, max_concurrency=4,
                cache_ttl=0, max_retries=0, circuit_threshold=1,
                circuit_cooldown=30.0, retry_after_budget=60.0)
    return s


def test_success_json_and_text():
    s = _scheduler(lambda *a, **k: Response(200, {"data": [1]}))
    safe_roblox.set_scheduler_for_tests(s)
    try:
        r = safe_roblox.get("catalog_search", "https://example.test")
        assert r.status_code == 200 and r.ok
        assert r.json() == {"data": [1]}
        assert '"data"' in r.text
    finally:
        safe_roblox.set_scheduler_for_tests(None)
    print("PASS safe_roblox success response adapter")


def test_429_retry_after_defers_and_opens_circuit():
    calls = {"n": 0}

    def request(*args, **kwargs):
        calls["n"] += 1
        return Response(429, {}, {"Retry-After": "120"})

    s = _scheduler(request)
    safe_roblox.set_scheduler_for_tests(s)
    try:
        first = safe_roblox.get("catalog_search", "https://example.test")
        second = safe_roblox.get("catalog_search", "https://example.test")
        assert first.status_code == 429
        assert first.deferred is True
        assert first.retry_after == 120
        assert not first.ok
        assert calls["n"] == 1
        assert second.status_code == 0
        assert "circuit" in (second.error or "").lower()
        assert calls["n"] == 1
    finally:
        safe_roblox.set_scheduler_for_tests(None)
    print("PASS 429 Retry-After deferral and circuit stop")


def test_timeout_is_visible_and_not_retried():
    calls = {"n": 0}

    def request(*args, **kwargs):
        calls["n"] += 1
        raise TimeoutError("upstream timeout")

    s = _scheduler(request)
    safe_roblox.set_scheduler_for_tests(s)
    try:
        r = safe_roblox.get("catalog_search", "https://example.test", timeout=1)
        assert r.status_code == 0
        assert not r.ok
        assert "timeout" in (r.error or "").lower()
        assert calls["n"] == 1
    finally:
        safe_roblox.set_scheduler_for_tests(None)
    print("PASS timeout is visible and not retried")


def test_concurrent_commands_share_scheduler():
    calls = {"n": 0}

    def request(url, **kwargs):
        calls["n"] += 1
        return Response(200, {"url": url})

    s = _scheduler(request)
    safe_roblox.set_scheduler_for_tests(s)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda i: safe_roblox.get("catalog_search",
                                          f"https://example.test/{i}"),
                range(2)))
        assert all(r.status_code == 200 for r in results)
        assert calls["n"] == 2
    finally:
        safe_roblox.set_scheduler_for_tests(None)
    print("PASS concurrent commands share the safe scheduler")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL {len(tests)} SAFE ROBLOX TESTS PASSED")
