"""F-05 unified Roblox API safety contracts (offline, deterministic)."""
import asyncio
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ROBLOSECURITY_COOKIE", "test-cookie")

import execution_policy as ep  # noqa: E402
import safe_roblox  # noqa: E402
import scanner  # noqa: E402
import search_visibility  # noqa: E402


class Response:
    def __init__(self, status=200, payload=None, headers=None,
                 json_error=False):
        self.status_code = status
        self.headers = headers or {}
        self.payload = payload if payload is not None else {}
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise ValueError("invalid json")
        return self.payload


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


def _reset():
    safe_roblox.reset_for_tests()
    ep.default_scheduler().reset()


def _install(request_fn, clock=None, sleep=None, endpoint="catalog_search",
             **overrides):
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    sched = ep.RobloxScheduler(request_fn=request_fn, clock=clock, sleep=sleep)
    config = {
        "rate_per_min": 100000,
        "max_concurrency": 4,
        "cache_ttl": 0,
        "max_retries": 0,
        "circuit_threshold": 1,
        "circuit_cooldown": 30.0,
        "retry_after_budget": 60.0,
        "honor_retry_after": True,
    }
    config.update(overrides)
    sched.configure(endpoint, **config)
    safe_roblox.set_scheduler_for_tests(sched)
    return sched


def test_http_200_success():
    _reset()
    _install(lambda *a, **k: Response(200, {"data": [1]}))
    try:
        r = safe_roblox.get("catalog_search", "https://example.test")
        assert r.status_code == 200 and r.ok
        assert r.json() == {"data": [1]}
    finally:
        _reset()


def test_http_400_and_403_are_explicit():
    _reset()
    _install(lambda *a, **k: Response(400, {}, {"X-Test": "1"}))
    try:
        r = safe_roblox.get("catalog_search", "https://example.test")
        assert r.status_code == 400 and not r.ok
        assert r.error == "HTTP 400"
    finally:
        _reset()
    _reset()
    _install(lambda *a, **k: Response(403, {}, {"X-CSRF-Token": "token"}))
    try:
        with mock.patch.object(
                safe_roblox.requests, "post",
                return_value=Response(403, {}, {"X-CSRF-Token": "token"})):
            r = safe_roblox.post("https://example.test", json={})
        assert r.status_code == 403
        assert r.headers.get("X-CSRF-Token") == "token"
        assert r.error == "HTTP 403"
    finally:
        _reset()


def test_429_numeric_retry_after_is_honored():
    _reset()
    clock = FakeClock()
    seq = [Response(429, {}, {"Retry-After": "5"}),
           Response(200, {"ok": 1})]
    _install(lambda *a, **k: seq.pop(0), clock=clock.now,
             sleep=clock.sleep, max_retries=1)
    try:
        r = safe_roblox.get("catalog_search", "https://example.test")
        assert r.ok and r.status_code == 200
        assert 5.0 in clock.sleeps
    finally:
        _reset()


def test_429_http_date_retry_after_is_honored_and_long_date_defers():
    _reset()
    clock = FakeClock()
    header = format_datetime(
        datetime.now(timezone.utc) + timedelta(seconds=10), usegmt=True)
    seq = [Response(429, {}, {"Retry-After": header}),
           Response(200, {"ok": 1})]
    _install(lambda *a, **k: seq.pop(0), clock=clock.now,
             sleep=clock.sleep, max_retries=1)
    try:
        r = safe_roblox.get("catalog_search", "https://example.test")
        assert r.ok
        assert any(seconds > 0 for seconds in clock.sleeps)
    finally:
        _reset()

    _reset()
    clock = FakeClock()
    long_header = format_datetime(
        datetime.now(timezone.utc) + timedelta(seconds=120), usegmt=True)
    calls = {"n": 0}

    def request(*a, **k):
        calls["n"] += 1
        return Response(429, {}, {"Retry-After": long_header})

    _install(request, clock=clock.now, sleep=clock.sleep,
             max_retries=1, retry_after_budget=30)
    try:
        r = safe_roblox.get("catalog_search", "https://example.test")
        assert r.status_code == 429 and r.deferred
        assert calls["n"] == 1
        assert safe_roblox.shared_circuit_open()
    finally:
        _reset()


def test_http_500_and_503_are_bounded():
    _reset()
    clock = FakeClock()
    seq = [Response(503), Response(200, {"ok": 1})]
    _install(lambda *a, **k: seq.pop(0), clock=clock.now,
             sleep=clock.sleep, max_retries=1)
    try:
        r = safe_roblox.get("catalog_search", "https://example.test")
        assert r.ok
    finally:
        _reset()

    _reset()
    clock = FakeClock()
    calls = {"n": 0}

    def failing(*a, **k):
        calls["n"] += 1
        return Response(500)

    _install(failing, clock=clock.now, sleep=clock.sleep, max_retries=1)
    try:
        r = safe_roblox.get("catalog_search", "https://example.test")
        assert not r.ok and r.status_code == 500
        assert calls["n"] == 2
        assert safe_roblox.shared_circuit_open()
    finally:
        _reset()


def test_connection_timeout_and_invalid_json():
    _reset()
    calls = {"n": 0}

    def timeout(*a, **k):
        calls["n"] += 1
        raise TimeoutError("upstream timeout")

    _install(timeout, max_retries=0)
    try:
        r = safe_roblox.get("catalog_search", "https://example.test")
        assert r.status_code == 0 and r.error == "TimeoutError"
        assert calls["n"] == 1
    finally:
        _reset()

    _reset()
    _install(lambda *a, **k: Response(200, json_error=True))
    try:
        r = safe_roblox.get("catalog_search", "https://example.test")
        assert r.ok and r.status_code == 200
        assert r.json() is None
    finally:
        _reset()


def test_shared_circuit_opens_and_defers_requests():
    _reset()
    calls = {"n": 0}

    def limited(*a, **k):
        calls["n"] += 1
        return Response(429, {}, {"Retry-After": "120"})

    _install(limited, max_retries=0)
    try:
        first = safe_roblox.get("catalog_search", "https://example.test")
        second = safe_roblox.get("catalog_details", "https://example.test")
        assert first.status_code == 429 and first.deferred
        assert second.error == "circuit open"
        assert calls["n"] == 1
        assert safe_roblox.shared_circuit_open("catalog_details")
    finally:
        _reset()


def test_circuit_breaker_recovers_after_cooldown():
    _reset()
    clock = FakeClock()
    seq = [Response(429, {}, {"Retry-After": "1"}),
           Response(200, {"ok": 1})]
    sched = _install(lambda *a, **k: seq.pop(0), clock=clock.now,
                     sleep=clock.sleep, max_retries=0,
                     circuit_cooldown=1.0)
    try:
        first = sched.request("catalog_search", "https://example.test")
        assert not first.ok and sched.is_circuit_open("catalog_search")
        clock.t += 2.0
        second = sched.request("catalog_search", "https://example.test")
        assert second.ok
    finally:
        _reset()


def test_concurrent_requests_share_concurrency_protection():
    _reset()
    active = {"now": 0, "max": 0}
    lock = threading.Lock()

    def request(*a, **k):
        with lock:
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
        time.sleep(0.05)
        with lock:
            active["now"] -= 1
        return Response(200, {"ok": 1})

    _install(request, max_concurrency=1)
    try:
        results = []
        threads = [
            threading.Thread(target=lambda: results.append(
                safe_roblox.get("catalog_search",
                                f"https://example.test/{i}")))
            for i in range(3)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
        assert all(r.ok for r in results)
        assert active["max"] == 1
    finally:
        _reset()


def test_retry_budget_exhaustion_stops_requests():
    _reset()
    clock = FakeClock()
    calls = {"n": 0}

    def limited(*a, **k):
        calls["n"] += 1
        return Response(429, {}, {"Retry-After": "1"})

    sched = _install(limited, clock=clock.now, sleep=clock.sleep,
                     max_retries=2)
    try:
        first = sched.request("catalog_search", "https://example.test")
        assert not first.ok
        assert first.attempts == 3
        assert calls["n"] == 3
        assert sched.is_circuit_open("catalog_search")
        second = sched.request("catalog_search", "https://example.test")
        assert second.error == "circuit open"
        assert calls["n"] == 3
    finally:
        _reset()


def test_authenticated_session_is_preserved():
    _reset()

    class Session:
        def __init__(self):
            self.cookies = {".ROBLOSECURITY": "secret-cookie"}
            self.headers = {"Cookie": ".ROBLOSECURITY=secret-cookie"}
            self.calls = []

        def get(self, url, params=None, headers=None, timeout=None):
            self.calls.append((url, params, headers, timeout))
            return Response(200, {"ok": 1})

        def post(self, url, json=None, headers=None, timeout=None):
            self.calls.append((url, json, headers, timeout))
            return Response(403, {}, {"X-CSRF-Token": "csrf"})

    session = Session()
    clock = FakeClock()
    _install(lambda *a, **k: Response(200, {"ok": 1}),
             clock=clock.now, sleep=clock.sleep)
    try:
        with mock.patch.object(
                safe_roblox.requests, "get",
                side_effect=AssertionError("anonymous GET attempted")):
            r = safe_roblox.get(
                "catalog_search", "https://example.test",
                params={"keyword": "x"}, session=session,
                headers={"A": "B"})
        assert r.ok
        assert session.calls and session.calls[0][1] == {"keyword": "x"}
        assert session.cookies[".ROBLOSECURITY"] == "secret-cookie"
        post = safe_roblox.post(
            "https://example.test", json={"x": 1}, session=session)
        assert post.headers.get("X-CSRF-Token") == "csrf"
        assert session.calls[-1][1] == {"x": 1}
    finally:
        _reset()


def test_batch_client_csrf_token_is_preserved_without_secret_logging():
    from roblox_batch_client import RobloxBatchClient

    _reset()
    client = RobloxBatchClient()
    calls = []

    class FakeResponse:
        def __init__(self, status, payload=None, headers=None):
            self.status = status
            self.payload = payload or {}
            self.headers = headers or {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def json(self, content_type=None):
            return self.payload

    class FakeSession:
        def __init__(self):
            self.n = 0

        def post(self, url, json=None, headers=None):
            calls.append(dict(headers or {}))
            self.n += 1
            if self.n == 1:
                return FakeResponse(403, {}, {"X-CSRF-TOKEN": "csrf-token"})
            return FakeResponse(200, {"data": [{"id": 1, "name": "ok"}]})

    client._session = FakeSession()
    try:
        data, failed = asyncio.run(client._post([1]))
        assert data and data[0]["id"] == 1
        assert not failed
        assert calls[1].get("X-CSRF-TOKEN") == "csrf-token"
        assert "secret" not in str(calls[1]).lower()
    finally:
        _reset()


def test_secret_redaction_in_errors():
    _reset()

    def boom(*a, **k):
        raise RuntimeError("cookie=SECRET; token=SECRET")

    _install(boom, max_retries=0)
    try:
        r = safe_roblox.get("catalog_search", "https://example.test")
        assert r.error == "RuntimeError"
        assert "SECRET" not in str(r.error)
    finally:
        _reset()


def test_partial_result_reporting():
    _reset()
    good = SimpleNamespace(
        status_code=200,
        headers={},
        error=None,
        json=lambda: {"data": [{"id": 1}, {"id": 2}],
                      "nextPageCursor": "next"},
    )
    limited = SimpleNamespace(
        status_code=429, headers={"Retry-After": "5"},
        error="rate limited (429)", json=lambda: {})

    class Session:
        pass

    with mock.patch.object(
            search_visibility, "safe_get", side_effect=[good, limited]):
        rows, pages, status, error = search_visibility._fetch_query(
            Session(), "query", max_pages=2)
    assert pages == 1
    assert len(rows) == 2
    assert status == "partial"
    assert error == "HTTP 429 rate limited"


def test_request_budgets_are_not_increased():
    assert safe_roblox._ENDPOINTS["catalog_search"]["rate_per_min"] == 30
    assert safe_roblox._ENDPOINTS["catalog_details"]["rate_per_min"] == 30
    assert safe_roblox._POST_RATE_PER_MIN == 20
    assert scanner.MAX_PAGES_PER_QUERY == 6
    assert scanner.WORKERS == scanner.WORKERS_PER_COOKIE == 3
    from roblox_batch_client import MAX_BATCH
    assert MAX_BATCH == 30


def test_no_session_or_cookie_rotation():
    _reset()
    assert scanner.get_session() is scanner.get_session()
    assert scanner.get_session() is scanner.SESSIONS[0]

    source = Path("creator_tracker.py").read_text(encoding="utf-8")
    assert "rotating to cookie" not in source
    assert "session_idx" not in source
    source = Path("scanner.py").read_text(encoding="utf-8")
    assert "_session_idx" not in source
    assert "Rotate to a different cookie on 429" not in source

    import live_enrich
    calls = []

    class Session:
        def __init__(self, name):
            self.name = name

        def get(self, *args, **kwargs):
            return Response(200, {"data": [{"id": 1}],
                                  "nextPageCursor": None})

    first, second = Session("first"), Session("second")
    saved = live_enrich.SESSIONS
    live_enrich.SESSIONS = [first, second]
    try:
        with mock.patch.object(
                live_enrich, "safe_get",
                side_effect=lambda *a, **k: (
                    calls.append(k.get("session")) or
                    Response(200, {"data": [{"id": 1}],
                                   "nextPageCursor": None}))):
            live_enrich._search_keyword("test", limit=1)
    finally:
        live_enrich.SESSIONS = saved
    assert calls and all(session is first for session in calls)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL {len(tests)} F-05 API SAFETY TESTS PASSED")
