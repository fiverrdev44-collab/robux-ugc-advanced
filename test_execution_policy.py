"""Tests for the accuracy-first execution policy and Roblox scheduler."""
import asyncio
import os
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import execution_policy as ep


class _Resp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
    def json(self):
        return self._payload


class _FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []
    def now(self):
        return self.t
    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


class ClassificationTests(unittest.TestCase):
    def test_classes(self):
        self.assertEqual(ep.classify("converge"), ep.MULTI_STAGE)
        self.assertEqual(ep.classify("gap"), ep.DB_ANALYSIS)
        self.assertEqual(ep.classify("xray"), ep.LIVE_RESEARCH)
        self.assertEqual(ep.classify("chain"), ep.AI_REASONING)
        self.assertEqual(ep.classify("help"), ep.LIGHTWEIGHT)
        self.assertEqual(ep.classify("scan_run"), ep.ADMIN)

    def test_budgets_are_generous_and_bounded(self):
        self.assertLess(ep.budget_seconds("help"), ep.budget_seconds("gap"))
        self.assertLess(ep.budget_seconds("gap"), ep.budget_seconds("converge"))
        for name in ("help", "gap", "converge", "chain", "scan_run"):
            self.assertGreaterEqual(ep.budget_seconds(name), 5)
            self.assertLessEqual(ep.budget_seconds(name), 3600)

    def test_env_override(self):
        with mock.patch.dict(os.environ, {"VANTA_TIMEOUT_GAP": "77"}):
            self.assertEqual(ep.budget_seconds("gap"), 77.0)


class _Ctx:
    class _Typing:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
    class _Channel:
        def __init__(self):
            self.sent = []
        async def send(self, content=None, **kw):
            self.sent.append(content)
            return content
        def typing(self):
            return _Ctx._Typing()
    def __init__(self):
        self.channel = _Ctx._Channel()
    async def send(self, content=None, **kw):
        self.channel.sent.append(content)
        return content


class RunResearchTests(unittest.TestCase):
    def test_runs_work_off_loop_and_returns_result(self):
        ctx = _Ctx()
        main_tid = threading.get_ident()
        seen = {}
        def work():
            seen["tid"] = threading.get_ident()
            return "RESULT"
        with mock.patch.object(ep, "budget_seconds", return_value=0.2):
            out = asyncio.run(ep.run_research(ctx, "gap", work))
        self.assertEqual(out, "RESULT")
        self.assertNotEqual(seen["tid"], main_tid)
        self.assertTrue(any("RESULT" in (m or "") for m in ctx.channel.sent))

    def test_timeout_is_reported_not_fabricated(self):
        ctx = _Ctx()
        def slow():
            time.sleep(0.4)
            return "SHOULD NOT APPEAR"
        with mock.patch.object(ep, "budget_seconds", return_value=0.05):
            out = asyncio.run(ep.run_research(ctx, "converge", slow))
        self.assertIsNone(out)
        self.assertTrue(any("budget" in (m or "").lower()
                            for m in ctx.channel.sent))

    def test_error_is_reported(self):
        ctx = _Ctx()
        def boom():
            raise ValueError("nope")
        with mock.patch.object(ep, "budget_seconds", return_value=1):
            out = asyncio.run(ep.run_research(ctx, "gap", boom))
        self.assertIsNone(out)
        self.assertTrue(any("ValueError" in (m or "") for m in ctx.channel.sent))


class DecoratorTests(unittest.TestCase):
    def test_decorator_bounds_and_reports(self):
        ctx = _Ctx()
        @ep.research_command("deco")
        async def cmd(ctx):
            await asyncio.sleep(0.4)
            return "late"
        with mock.patch.object(ep, "budget_seconds", return_value=0.05):
            out = asyncio.run(cmd(ctx))
        self.assertIsNone(out)
        self.assertTrue(any("budget" in (m or "").lower()
                            for m in ctx.channel.sent))


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.clock = _FakeClock()
        self.sched = ep.RobloxScheduler(
            request_fn=lambda *a, **k: _Resp(200, {"ok": 1}),
            clock=self.clock.now, sleep=self.clock.sleep)

    def test_cache_reuse(self):
        calls = {"n": 0}
        def rf(*a, **k):
            calls["n"] += 1
            return _Resp(200, {"v": 1})
        self.sched = ep.RobloxScheduler(request_fn=rf,
                                        clock=self.clock.now,
                                        sleep=self.clock.sleep)
        r1 = self.sched.request("e", "u", params={"a": 1})
        r2 = self.sched.request("e", "u", params={"a": 1})
        self.assertTrue(r1.ok)
        self.assertFalse(r1.cached)
        self.assertTrue(r2.cached)
        self.assertEqual(calls["n"], 1)

    def test_retry_after_numeric_and_http_date(self):
        for header in ("5", format_datetime(
                datetime.now(timezone.utc) + timedelta(seconds=3), usegmt=True)):
            self.clock = _FakeClock()
            seq = [_Resp(429, {}, {"Retry-After": header}), _Resp(200, {"v": 1})]
            def rf(*a, **k):
                return seq.pop(0)
            s = ep.RobloxScheduler(request_fn=rf, clock=self.clock.now,
                                   sleep=self.clock.sleep)
            s.configure("e", cache_ttl=0, max_retries=1)
            r = s.request("e", "u")
            self.assertTrue(r.ok, header)
            self.assertEqual(r.attempts, 2)
            self.assertTrue(self.clock.sleeps, header)

    def test_bounded_retries_and_circuit(self):
        calls = {"n": 0}
        def rf(*a, **k):
            calls["n"] += 1
            return _Resp(429, {}, {"Retry-After": "1"})
        s = ep.RobloxScheduler(request_fn=rf, clock=self.clock.now,
                               sleep=self.clock.sleep)
        s.configure("e", cache_ttl=0, max_retries=2, circuit_threshold=1,
                    circuit_cooldown=30)
        r = s.request("e", "u")
        self.assertFalse(r.ok)
        self.assertIn("429", r.error)
        self.assertEqual(r.attempts, 3)
        calls_before = calls["n"]
        r2 = s.request("e", "u")
        self.assertFalse(r2.ok)
        self.assertEqual(r2.error, "circuit open")
        self.assertEqual(calls["n"], calls_before)

    def test_unsupported_method_rejected(self):
        calls = {"n": 0}
        def rf(*a, **k):
            calls["n"] += 1
            return _Resp(200, {})
        s = ep.RobloxScheduler(request_fn=rf, clock=self.clock.now,
                               sleep=self.clock.sleep)
        s.configure("e", cache_ttl=0)
        r = s.request("e", "u", method="POST")
        self.assertFalse(r.ok)
        self.assertIn("unsupported HTTP method", r.error)
        self.assertEqual(calls["n"], 0)

    def test_exception_reported(self):
        def rf(*a, **k):
            raise RuntimeError("boom")
        s = ep.RobloxScheduler(request_fn=rf, clock=self.clock.now,
                               sleep=self.clock.sleep)
        s.configure("e", cache_ttl=0, max_retries=1)
        r = s.request("e", "u")
        self.assertFalse(r.ok)
        self.assertEqual(r.error, "RuntimeError")

    def test_concurrency_limit(self):
        active = {"now": 0, "max": 0}
        lock = threading.Lock()
        def rf(*a, **k):
            with lock:
                active["now"] += 1
                active["max"] = max(active["max"], active["now"])
            time.sleep(0.08)
            with lock:
                active["now"] -= 1
            return _Resp(200, {"v": 1})
        s = ep.RobloxScheduler(request_fn=rf, clock=time.monotonic,
                               sleep=time.sleep)
        s.configure("e", cache_ttl=0, max_concurrency=1)
        threads = [threading.Thread(target=lambda i=i: s.request(
            "e", "u", params={"i": i}, use_cache=False)) for i in range(3)]
        for t in threads: t.start()
        for t in threads: t.join(3)
        self.assertEqual(active["max"], 1)

    def test_inflight_dedup_singleflight(self):
        started = threading.Event()
        release = threading.Event()
        calls = {"n": 0}
        def rf(*a, **k):
            calls["n"] += 1
            started.set()
            release.wait(2)
            return _Resp(200, {"v": 1})
        s = ep.RobloxScheduler(request_fn=rf, clock=time.monotonic,
                               sleep=time.sleep)
        s.configure("e", cache_ttl=0)
        results = []
        t1 = threading.Thread(target=lambda: results.append(
            s.request("e", "u", params={"k": 1}, use_cache=False)))
        t1.start()
        self.assertTrue(started.wait(1))
        t2 = threading.Thread(target=lambda: results.append(
            s.request("e", "u", params={"k": 1}, use_cache=False)))
        t2.start()
        time.sleep(0.1)
        release.set()
        t1.join(3); t2.join(3)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(len(results), 2)
        self.assertTrue(any(r.deduplicated for r in results))

    def test_pacing_sleeps_between_requests(self):
        s = ep.RobloxScheduler(request_fn=lambda *a, **k: _Resp(200, {}),
                               clock=self.clock.now, sleep=self.clock.sleep)
        s.configure("e", rate_per_min=1, cache_ttl=0)
        s.request("e", "u", params={"a": 1})
        s.request("e", "u", params={"a": 2})
        self.assertTrue(self.clock.sleeps)

    def test_concurrent_requests_respect_pacing(self):
        # 60 concurrent acquisitions at 10/s with capacity 50 must take ~1s.
        s = ep.RobloxScheduler(request_fn=lambda *a, **k: _Resp(200, {}),
                               clock=time.monotonic, sleep=time.sleep)
        s.configure("e", rate_per_min=600, max_concurrency=20, cache_ttl=0)
        start = time.monotonic()
        threads = [threading.Thread(
            target=lambda i=i: s.request("e", "u", params={"i": i},
                                         use_cache=False))
            for i in range(60)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        elapsed = time.monotonic() - start
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertGreaterEqual(elapsed, 0.7)


class CancellationTests(unittest.TestCase):
    def test_timeout_cancels_worker_cooperatively(self):
        ctx = _Ctx()
        counter = {"n": 0}
        done = threading.Event()

        def work():
            try:
                while counter["n"] < 2000:
                    ep.check_cancelled()
                    counter["n"] += 1
                    time.sleep(0.002)
            finally:
                done.set()

        with mock.patch.object(ep, "budget_seconds", return_value=0.05):
            out = asyncio.run(ep.run_research(ctx, "converge", work))
        self.assertIsNone(out)
        self.assertTrue(done.wait(2.0))
        snapshot = counter["n"]
        time.sleep(0.1)
        self.assertEqual(counter["n"], snapshot)  # stopped consuming
        self.assertLess(snapshot, 2000)          # did not run to completion

    def test_cancel_token_cancels_registered_connection(self):
        token = ep.CancellationToken()

        class FakeConn:
            def __init__(self):
                self.cancelled = 0
            def cancel(self):
                self.cancelled += 1

        conn = FakeConn()
        token.register(conn)
        token.cancel()
        self.assertEqual(conn.cancelled, 1)
        self.assertTrue(token.cancelled)
        with self.assertRaises(ep.ResearchCancelled):
            token.check()

    def test_register_after_cancel_raises(self):
        token = ep.CancellationToken()
        token.cancel()

        class FakeConn:
            def cancel(self):
                pass

        with self.assertRaises(ep.ResearchCancelled):
            token.register(FakeConn())


class ResearchDbTests(unittest.TestCase):
    def test_research_connection_read_only_larger_timeout(self):
        import bot_core
        captured = {}

        class FakeConn:
            def cancel(self):
                pass

        def fake_connect(url, **kw):
            captured.update(kw)
            return FakeConn()

        with mock.patch.object(bot_core.psycopg2, "connect",
                               side_effect=fake_connect):
            bot_core.get_research_db()
        opts = captured["options"]
        self.assertIn("default_transaction_read_only=on", opts)
        self.assertIn(str(bot_core.RESEARCH_STATEMENT_TIMEOUT_MS), opts)
        self.assertGreater(bot_core.RESEARCH_STATEMENT_TIMEOUT_MS,
                           bot_core.STATEMENT_TIMEOUT_MS)

    def test_routine_connection_keeps_strict_default(self):
        import bot_core
        captured = {}

        class FakeConn:
            pass

        def fake_connect(url, **kw):
            captured.update(kw)
            return FakeConn()

        with mock.patch.object(bot_core.psycopg2, "connect",
                               side_effect=fake_connect):
            bot_core.get_db()
        opts = captured["options"]
        self.assertIn(str(bot_core.STATEMENT_TIMEOUT_MS), opts)
        self.assertNotIn("default_transaction_read_only=on", opts)
        self.assertEqual(bot_core.STATEMENT_TIMEOUT_MS, 20000)

    def test_research_timeout_env_override(self):
        import importlib
        import bot_core
        try:
            with mock.patch.dict(os.environ, {
                    "DB_RESEARCH_STATEMENT_TIMEOUT_MS": "90000",
                    "DB_STATEMENT_TIMEOUT_MS": "15000"}):
                importlib.reload(bot_core)
                self.assertEqual(bot_core.STATEMENT_TIMEOUT_MS, 15000)
                self.assertEqual(bot_core.RESEARCH_STATEMENT_TIMEOUT_MS, 90000)
        finally:
            importlib.reload(bot_core)


if __name__ == "__main__":
    unittest.main(verbosity=2)
