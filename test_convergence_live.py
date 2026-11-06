"""Regression tests for the two-stage convergence pipeline (offline).

Stage A gate logic (generic rejection, evidence qualification, median/velocity
labeling) is tested as pure functions. Stage B live verification is tested with
mocked Roblox responses — no network, no database writes.
"""
import asyncio
import email.utils
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))

import convergence_engine as ce
import convergence_live as cl
import execution_policy as ep
import emote_title_engine as ete


def _fast_scheduler():
    """Reconfigure the shared scheduler for fast, non-sleeping tests."""
    s = cl._get_scheduler()
    s.configure("catalog_search", rate_per_min=100000, max_concurrency=5,
                cache_ttl=0, max_retries=1, circuit_threshold=1,
                circuit_cooldown=30.0, backoff_base=0.001, backoff_cap=0.001,
                honor_retry_after=False, retry_after_budget=3600)
    return s


class _FakeResp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


def _candidate(**kw):
    base = {
        "keyword": "levitation pose", "family": "emotes", "score": 62.0,
        "demand": 4, "demand_live": 4, "demand_reliable": True,
        "demand_volume": 120, "velocity": 1.5, "velocity_measured": True,
        "observations": 3, "stale": False, "supply": 18, "recent": 2,
        "median_favs": 42.0, "avg_favs": 42.0, "p90_favs": 120.0,
        "concentration": 0.35,
    }
    base.update(kw)
    return base


class GenericRejectionTests(unittest.TestCase):
    def test_generic_single_word_rejected(self):
        for w in ("fairy", "waist", "emote", "float", "music", "matching",
                  "confess", "farming", "heart", "model"):
            self.assertTrue(ce._is_generic(w), w)

    def test_actionable_bigram_not_generic(self):
        self.assertFalse(ce._is_generic("fairy levitation"))
        self.assertFalse(ce._is_generic("floating battle stance"))
        self.assertFalse(ce._is_generic("levitation"))

    def test_generic_seed_kept_as_multiword_concept(self):
        # "float"/"fairy"/"heart" are gated standalone but survive as concepts.
        self.assertTrue(ce._is_generic("float"))
        self.assertFalse(ce._is_generic("floating pose"))
        self.assertTrue(ce._is_generic("fairy"))
        self.assertFalse(ce._is_generic("fairy levitation"))
        self.assertTrue(ce._is_generic("heart"))
        self.assertFalse(ce._is_generic("heart pose"))

    def test_qualifies_rejects_generic(self):
        ok, reason = ce.qualifies(_candidate(keyword="fairy"))
        self.assertFalse(ok)
        self.assertIn("generic", reason)

    def test_qualifies_rejects_unmeasured_and_stale(self):
        ok, reason = ce.qualifies(
            _candidate(velocity_measured=False, velocity=None, recent=0))
        self.assertFalse(ok)
        self.assertIn("velocity", reason)

    def test_qualifies_allows_measured(self):
        ok, _ = ce.qualifies(_candidate())
        self.assertTrue(ok)

    def test_qualifies_allows_fresh_supply_when_unmeasured(self):
        ok, reason = ce.qualifies(
            _candidate(velocity_measured=False, velocity=None, recent=3))
        self.assertTrue(ok)
        self.assertIn("fresh supply", reason)


class LabelingTests(unittest.TestCase):
    def test_velocity_unavailable(self):
        self.assertEqual(ce._fmt_velocity(_candidate(velocity_measured=False)),
                         "unavailable")
        self.assertEqual(ce._fmt_velocity(_candidate(velocity=1.5)), "1.5/d")

    def test_brief_labels_median_and_unverified_autocomplete(self):
        text = ce.format_brief(_candidate())
        self.assertIn("median", text)
        self.assertIn("unverified", text)
        self.assertIn("velocity 1.5/d", text)

    def test_brief_flags_unmeasured_velocity(self):
        text = ce.format_brief(
            _candidate(velocity_measured=False, velocity=None))
        self.assertIn("unavailable", text)


class ConvergeDebugTests(unittest.TestCase):
    class _Cursor:
        def __init__(self, rows):
            self._rows = list(rows)
        def execute(self, *a, **k):
            pass
        def fetchone(self):
            return self._rows.pop(0) if self._rows else None
        def close(self):
            pass

    def test_debug_accepts_kwarg_and_rejects_generic(self):
        # Generic keyword is rejected before any SQL; debug=True must not raise.
        cur = self._Cursor([])
        self.assertIsNone(
            ce._score_keyword(cur, "fairy", "emotes", debug=True))

    def test_debug_scores_a_viable_keyword(self):
        cur = self._Cursor([
            (18, 42, 120),            # supply, median, p90
            (4, 120, 4, 120),         # demand_all, volume_all, live, volume_live
            (2,),                     # recent
            (3, 1.5),                 # observations, avg velocity
            ("2026-11-01T00:00:00+00:00",),  # last obs
            (5000, 1000),             # total favs, top favs
        ])
        r = ce._score_keyword(cur, "levitation pose", "emotes", debug=True)
        self.assertIsNotNone(r)
        self.assertTrue(r.get("velocity_measured"))
        self.assertEqual(r.get("median_favs"), 42.0)


class StageAFixTests(unittest.TestCase):
    class _Cursor:
        def __init__(self, rows):
            self._rows = list(rows)
        def execute(self, *a, **k):
            pass
        def fetchone(self):
            return self._rows.pop(0) if self._rows else None
        def close(self):
            pass

    def _score(self, vel_row, last_obs):
        cur = self._Cursor([
            (18, 42, 120),            # supply, median, p90
            (4, 120, 4, 120),         # demand, volume
            (2,),                     # recent
            vel_row,                  # observations, avg velocity
            (last_obs,),              # last observation timestamp
            (5000, 1000),             # total favs, top favs
        ])
        return ce._score_keyword(cur, "levitation pose", "emotes")

    def test_flat_velocity_no_none_exception(self):
        # Observations exist but every delta is zero -> avg is NULL. Must not
        # raise and must report a measured (flat) 0.0 velocity.
        r = self._score((3, None), None)
        self.assertIsNotNone(r)
        self.assertTrue(r["velocity_measured"])
        self.assertEqual(r["velocity"], 0.0)
        self.assertIn("velocity 0.0/d", ce.format_brief(r))

    def test_no_history_freshness_is_none(self):
        r = self._score((0, None), None)
        self.assertFalse(r["velocity_measured"])
        self.assertEqual(r["freshness"], "none")
        self.assertFalse(r["stale"])

    def test_stale_history_freshness(self):
        old = datetime(2000, 1, 1, tzinfo=timezone.utc)
        r = self._score((3, 1.5), old)
        self.assertEqual(r["freshness"], "stale")
        self.assertTrue(r["stale"])

    def test_fresh_history_freshness(self):
        # Relative timestamp: stays "recent" regardless of the wall clock.
        recent = datetime.now(timezone.utc) - timedelta(days=1)
        r = self._score((3, 1.5), recent)
        self.assertEqual(r["freshness"], "recent")
        self.assertFalse(r["stale"])


class LimitTests(unittest.TestCase):
    class _Cur:
        def close(self):
            pass

    class _Conn:
        def cursor(self):
            return LimitTests._Cur()

        def close(self):
            pass

    def _detailed(self, limit, shortlist, count=8):
        def fake_score(cur, kw, family, **kwargs):
            return _candidate(keyword=kw, score=100 - int(kw.rsplit(" ", 1)[-1]))

        keywords = [f"levitation pose {i}" for i in range(count)]
        with mock.patch.object(ce, "get_research_db",
                               return_value=self._Conn()), \
                mock.patch.object(ce, "_gather_keywords",
                                  return_value=keywords), \
                mock.patch.object(ce, "_score_keyword",
                                  side_effect=fake_score):
            return ce.scan_convergence_detailed(
                "emotes", limit, shortlist=shortlist)

    def test_limit_clamp_is_documented_and_bounded(self):
        self.assertEqual(ce.clamp_convergence_limit(3), 3)
        self.assertEqual(ce.clamp_convergence_limit(0), 1)
        self.assertEqual(ce.clamp_convergence_limit(-5), 1)
        self.assertEqual(ce.clamp_convergence_limit(999), 8)
        self.assertEqual(ce.clamp_convergence_limit(None), 8)
        self.assertEqual(ce.clamp_convergence_limit("3"), 3)
        self.assertEqual(ce.clamp_convergence_limit("bad"), 8)

    def test_detailed_shortlist_never_exceeds_requested_limit(self):
        out = self._detailed(3, 8)
        self.assertEqual(out["limit"], 3)
        self.assertEqual(len(out["candidates"]), 3)
        self.assertEqual(len(out["shortlist"]), 3)

    def test_default_detailed_shortlist_remains_eight(self):
        out = self._detailed(10, 8)
        self.assertEqual(out["limit"], 10)
        self.assertEqual(len(out["candidates"]), 8)
        self.assertEqual(len(out["shortlist"]), 8)

    def test_legacy_report_renders_only_limited_shortlist(self):
        rows = [_candidate(keyword=f"levitation pose {i}") for i in range(3)]
        text = cl.format_report(
            {"shortlist": rows, "candidates": rows, "limit": 3,
             "gated": []}, {}, family="emotes")
        self.assertEqual(text.count("### 🎯"), 3)
        self.assertIn("Shortlist (3 candidates)", text)

    def test_converge_command_honors_limit_and_accessory(self):
        import commands_advanced as ca

        class FakeBot:
            def __init__(self):
                self.commands = {}

            def command(self, name=None, **kw):
                def deco(fn):
                    self.commands[name or kw.get("name")] = fn
                    return fn
                return deco

        class FakeCtx:
            def __init__(self):
                self.sent = []

            async def send(self, content=None, **kw):
                self.sent.append(content)

        calls = {}

        def fake_detailed(family, limit, shortlist=None):
            calls["args"] = (family, limit, shortlist)
            rows = [_candidate(keyword=f"levitation pose {i}")
                    for i in range(shortlist)]
            return {"family": family, "shortlist": rows,
                    "candidates": rows, "limit": limit, "gated": []}

        def fake_verify(keywords, family=None, **kwargs):
            calls["keywords"] = list(keywords)
            return {}

        def fake_format(detailed, verified, family):
            return "ok"

        for family, requested, expected in (
                ("emotes", 3, 3), ("accessory", 3, 3),
                ("emotes", 999, 8), ("emotes", 0, 1)):
            bot = FakeBot()
            ca.register_advanced_commands(bot, lambda: None)
            ctx = FakeCtx()
            with mock.patch.object(ce, "scan_convergence_detailed",
                                   side_effect=fake_detailed), \
                    mock.patch.object(cl, "verify_shortlist",
                                      side_effect=fake_verify), \
                    mock.patch.object(cl, "format_report",
                                      side_effect=fake_format), \
                    mock.patch.dict(os.environ,
                                    {"PHASE2_M3_ENABLED": "0"}):
                asyncio.run(bot.commands["converge"](
                    ctx, family=family, limit=requested))
            self.assertEqual(calls["args"], (family, expected, expected))
            self.assertEqual(len(calls["keywords"]), expected)
            self.assertLessEqual(len(ctx.sent), 3)


class LiveVerificationTests(unittest.TestCase):
    def setUp(self):
        cl.clear_cache()
        cl._reset_circuit()
        _fast_scheduler()

    def _patch(self, responses):
        return mock.patch.object(cl, "_get_with_backoff", side_effect=responses)

    def _items(self, n=3, asset_type=61, name="levitation", favs=100, price=50):
        return [{"name": f"{name} {i}", "favoriteCount": favs + i,
                 "price": price, "assetType": asset_type,
                 "creatorName": f"creator{i}"} for i in range(n)]

    def test_emotes_category_verification(self):
        payload = {"data": self._items(), "nextPageCursor": None}
        with self._patch([_FakeResp(200, payload)]):
            r = cl.verify_niche("levitation", family="emotes")
        self.assertTrue(r["ok"])
        self.assertEqual(r["category_correct"], 3)
        self.assertEqual(r["category_mismatched"], 0)
        self.assertEqual(r["sampled_results"], 3)

    def test_unrelated_category_flagged(self):
        items = self._items(asset_type=8)  # hats, not emotes
        with self._patch([_FakeResp(200, {"data": items, "nextPageCursor": None})]):
            r = cl.verify_niche("levitation", family="emotes")
        self.assertEqual(r["category_correct"], 0)
        self.assertEqual(r["category_mismatched"], 3)

    def test_wrong_category_competitors_excluded(self):
        # A high-favorite hat must not appear as a competitor for an emote.
        rows = self._items(n=2, asset_type=61, name="levitation", favs=50)
        rows.append({"name": "levitation hat", "favoriteCount": 999999,
                     "price": 10, "assetType": 8, "creatorName": "hatmaker"})
        payload = {"data": rows, "nextPageCursor": None}
        with self._patch([_FakeResp(200, payload)]):
            r = cl.verify_niche("levitation", family="emotes")
        self.assertEqual(r["category_correct"], 2)
        self.assertEqual(r["category_mismatched"], 1)
        self.assertTrue(all(c["asset_type_id"] == 61
                            for c in r["top_competitors"]))

    def test_verify_sorts_related_competitors_first(self):
        rows = [
            {"name": "Levitation Float", "favoriteCount": 10, "price": 50,
             "assetType": 61, "creatorName": "a"},
            {"name": "Random Dance", "favoriteCount": 9999, "price": 50,
             "assetType": 61, "creatorName": "b"},
        ]
        with self._patch([_FakeResp(200, {"data": rows, "nextPageCursor": None})]):
            r = cl.verify_niche("levitation", family="emotes")
        self.assertTrue(r["top_competitors"][0]["related"])
        self.assertEqual(r["top_competitors"][0]["name"], "Levitation Float")

    def test_timeout_forwarded(self):
        resp = _FakeResp(200, {"data": self._items(n=1), "nextPageCursor": None})
        m = mock.Mock(return_value=resp)
        with mock.patch.object(cl, "_get_with_backoff", m):
            cl.verify_niche("levitation", family="emotes", timeout=7)
        self.assertEqual(m.call_args.kwargs.get("timeout"), 7)
        self.assertEqual(m.call_args.kwargs.get("max_attempts"), 1)

    def test_429_trips_circuit(self):
        calls = {"n": 0}

        def fake(*a, **k):
            calls["n"] += 1
            return _FakeResp(429, {}, {"Retry-After": "60"})

        with mock.patch.object(cl, "_get_with_backoff", side_effect=fake):
            r1 = cl.verify_niche("levitation", family="emotes")
            r2 = cl.verify_niche("levitation", family="emotes")
        self.assertFalse(r1["ok"])
        self.assertFalse(r2["ok"])
        self.assertIn("circuit open", r2["error"])
        self.assertEqual(calls["n"], 2)  # scheduler retries once before tripping

    def test_http_429(self):
        with mock.patch.object(
                cl, "_get_with_backoff",
                side_effect=lambda *a, **k: _FakeResp(
                    429, {}, {"Retry-After": "1"})):
            r = cl.verify_niche("levitation", family="emotes")
        self.assertFalse(r["ok"])
        self.assertIn("429", r["error"])

    def test_api_outage(self):
        def boom(*a, **k):
            raise RuntimeError("connection reset")
        with mock.patch.object(cl, "_get_with_backoff", side_effect=boom):
            r = cl.verify_niche("levitation", family="emotes")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "RuntimeError")

    def test_pagination_capped(self):
        page1 = {"data": self._items(), "nextPageCursor": "cursor1"}
        page2 = {"data": self._items(), "nextPageCursor": "cursor2"}
        with self._patch([_FakeResp(200, page1), _FakeResp(200, page2)]):
            r = cl.verify_niche("levitation", family="emotes", max_pages=2)
        self.assertTrue(r["capped"])
        self.assertEqual(r["pages"], 2)

    def test_cache_reuse(self):
        cl.clear_cache()
        payload = {"data": self._items(), "nextPageCursor": None}
        calls = {"n": 0}

        def fake(*a, **k):
            calls["n"] += 1
            return _FakeResp(200, payload)

        with mock.patch.object(cl, "_get_with_backoff", side_effect=fake):
            r1 = cl.verify_niche("levitation", family="emotes")
            r2 = cl.verify_niche("levitation", family="emotes")
        self.assertFalse(r1.get("cached"))
        self.assertTrue(r2.get("cached"))
        self.assertEqual(calls["n"], 1)
        self.assertEqual(r2["observed_at"], r1["verification_timestamp"])
        self.assertEqual(r2["verification_timestamp"],
                         r1["verification_timestamp"])
        self.assertGreaterEqual(r2["cache_age_seconds"], 0.0)
        cl.clear_cache()


class ShortlistCircuitTests(unittest.TestCase):
    def setUp(self):
        cl.clear_cache()
        cl._reset_circuit()
        _fast_scheduler()

    def test_circuit_prevents_new_requests(self):
        state = {"open": False}
        calls = []

        def fake_verify(k, *a, **kw):
            if state["open"]:
                return {"ok": False, "error": "circuit open (rate limited)",
                        "keyword": k, "cached": k == "cached",
                        "deferred": True, "skipped": True}
            calls.append(k)
            state["open"] = True
            return {"ok": False, "error": "rate limited (429)", "keyword": k,
                    "deferred": True, "retry_after": 90.0}

        with mock.patch.object(cl, "verify_niche", side_effect=fake_verify), \
                mock.patch.object(cl, "_circuit_open",
                                  side_effect=lambda: state["open"]):
            out = cl.verify_shortlist(
                ["a", "cached", "c", "d"], family="emotes", max_workers=1)
        self.assertEqual(calls, ["a"])
        self.assertEqual(out["a"]["retry_after"], 90.0)
        self.assertTrue(out["cached"]["cached"])
        self.assertTrue(out["c"]["skipped"])
        self.assertTrue(out["d"]["skipped"])

    def test_already_open_circuit_uses_cache_or_defers(self):
        calls = []

        def fake_verify(k, *a, **kw):
            calls.append(k)
            return {"ok": False, "error": "circuit open (rate limited)",
                    "keyword": k, "cached": k == "cached",
                    "deferred": True, "skipped": True}

        with mock.patch.object(cl, "verify_niche", side_effect=fake_verify), \
                mock.patch.object(cl, "_circuit_open",
                                  return_value=True):
            out = cl.verify_shortlist(
                ["cached", "other"], family="emotes", max_workers=3)
        self.assertTrue(out["cached"]["cached"])
        self.assertTrue(out["other"]["deferred"])
        self.assertEqual(len(calls), 2)  # cache/circuit resolution, no network

    def test_cached_evidence_survives_circuit_with_timestamps(self):
        payload = {"data": _items_for_cache(), "nextPageCursor": None}
        with mock.patch.object(cl, "_get_with_backoff",
                               return_value=_FakeResp(200, payload)):
            first = cl.verify_niche("levitation", family="emotes")
        self.assertFalse(first["cached"])
        self.assertTrue(first["verification_timestamp"])
        self.assertTrue(first["observed_at"])

        cl._trip_circuit(60)
        try:
            with mock.patch.object(
                    cl, "_get_with_backoff",
                    side_effect=AssertionError("network call attempted")):
                cached = cl.verify_niche("levitation", family="emotes")
        finally:
            cl._reset_circuit()
        self.assertTrue(cached["cached"])
        self.assertEqual(cached["observed_at"], first["verification_timestamp"])
        self.assertEqual(cached["verification_timestamp"],
                         first["verification_timestamp"])
        self.assertGreaterEqual(cached["cache_age_seconds"], 0.0)


def _items_for_cache():
    return [{"name": "levitation 1", "favoriteCount": 100, "price": 50,
             "assetType": 61, "creatorName": "a"}]


class RetryEvidencePropagationTests(unittest.TestCase):
    def test_retry_after_and_deferred_reach_research_and_report(self):
        class _FakeSched:
            def request(self, *a, **k):
                return ep.SchedulerResult(
                    ok=False, endpoint="catalog_search", status=429,
                    headers={"Retry-After": "90"},
                    error="rate limited (429); Retry-After 90s — deferred",
                    deferred=True, retry_after=90.0)

        with mock.patch.object(cl, "_get_scheduler", return_value=_FakeSched()):
            vr = cl.verify_niche("street dance", family="emotes",
                                 use_cache=False)
        self.assertFalse(vr["ok"])
        self.assertTrue(vr["deferred"])
        self.assertEqual(vr["retry_after"], 90.0)
        self.assertIn("Retry-After", vr["error"])

        calls = []

        def fake_verify(phrase, **kw):
            calls.append(phrase)
            return dict(vr)

        with mock.patch.object(cl, "verify_niche", side_effect=fake_verify):
            live = ete.research_live(["street dance", "hip hop dance"])
        self.assertEqual(calls, ["street dance"])  # no further requests
        self.assertEqual(len(live), 1)
        self.assertTrue(live[0]["deferred"])
        self.assertEqual(live[0]["retry_after"], 90.0)

        report = ete.format_report({
            "titles": [], "recommended": None, "description": "d",
            "experiment": "e",
            "research": {"db": {"ok": False}, "live": live,
                         "live_deferred": True, "tiktok": {}},
        })
        self.assertIn("Retry-After 90s", report)
        self.assertIn("deferred", report.lower())


class ReportTests(unittest.TestCase):
    def test_no_qualifying_opportunities(self):
        detailed = {"family": "emotes", "candidates": [], "shortlist": [],
                    "gated": [{"keyword": "fairy", "reason": "generic",
                               "score": 70.2}]}
        text = cl.format_report(detailed, {}, family="emotes")
        self.assertIn("No qualifying opportunities", text)
        self.assertIn("fairy", text)

    def test_recommendation_live_disagreement_lowers_confidence(self):
        c = _candidate()
        live = {"ok": True, "keyword": "levitation pose", "sampled_results": 30,
                "category_correct": 0, "category_mismatched": 30,
                "exact_title_matches": 0, "conceptual_matches": 2,
                "top_competitors": [], "verification_timestamp": "2026-11-03T00:00:00",
                "sample_note": "first 30", "capped": False}
        level, why = cl._confidence(c, live)
        self.assertEqual(level, "low")
        self.assertIn("correct-category", why)

    def test_zero_category_results_are_not_category_absence(self):
        c = _candidate()
        live = {"ok": True, "keyword": "levitation pose", "sampled_results": 30,
                "category_correct": 0, "category_mismatched": 30,
                "exact_title_matches": 0, "conceptual_matches": 0,
                "top_competitors": [], "verification_timestamp": "2026-11-03T00:00:00",
                "sample_note": "first 30", "capped": False}
        text = cl.format_recommendation(c, live)
        self.assertIn("insufficient evidence", text)
        self.assertIn("does not prove", text)
        self.assertIn("observed sample", text)
        self.assertNotIn("0 competitors", text)
        self.assertNotIn("no products", text)

    def test_zero_category_capped_sample_is_explicit(self):
        c = _candidate()
        live = {"ok": True, "keyword": "levitation pose", "sampled_results": 30,
                "category_correct": 0, "category_mismatched": 30,
                "exact_title_matches": 0, "conceptual_matches": 0,
                "top_competitors": [], "verification_timestamp": "2026-11-03T00:00:00",
                "sample_note": "first 60 results sampled (capped before catalog exhausted)",
                "capped": True}
        text = cl.format_recommendation(c, live)
        self.assertIn("live sample capped", text)
        self.assertIn("zero correct-category matches in sample; not proof of absence",
                      text)
        self.assertIn("insufficient evidence", text)

    def test_competitor_examples_are_concept_related(self):
        live = {"ok": True, "keyword": "levitation", "sampled_results": 2,
                "category_correct": 2, "category_mismatched": 0,
                "exact_title_matches": 0, "conceptual_matches": 1,
                "top_competitors": [
                    {"name": "Levitation Float", "favorites": 100, "price": 50,
                     "asset_type_id": 61, "creator": "a", "related": True},
                    {"name": "Random Dance Party", "favorites": 9000, "price": 50,
                     "asset_type_id": 61, "creator": "b", "related": False},
                ],
                "verification_timestamp": "2026-11-03T00:00:00",
                "sample_note": "first 2", "capped": False}
        text = cl.format_recommendation(_candidate(), live)
        self.assertIn("Levitation Float", text)
        self.assertNotIn("Random Dance Party", text)


class RetryAfterTests(unittest.TestCase):
    def setUp(self):
        cl.clear_cache()
        cl._reset_circuit()
        _fast_scheduler()

    def test_numeric_retry_after(self):
        self.assertEqual(cl._parse_retry_after("120"), 120.0)
        self.assertEqual(cl._parse_retry_after("0"), 0.0)

    def test_http_date_retry_after(self):
        future = datetime.now(timezone.utc) + timedelta(seconds=90)
        header = email.utils.format_datetime(future, usegmt=True)
        seconds = cl._parse_retry_after(header)
        self.assertIsNotNone(seconds)
        self.assertGreater(seconds, 60)
        self.assertLess(seconds, 120)

    def test_invalid_retry_after_is_none(self):
        self.assertIsNone(cl._parse_retry_after(None))
        self.assertIsNone(cl._parse_retry_after(""))
        self.assertIsNone(cl._parse_retry_after("not-a-date"))

    def test_http_date_429_trips_circuit_without_exception(self):
        cl._reset_circuit()
        future = datetime.now(timezone.utc) + timedelta(seconds=60)
        header = email.utils.format_datetime(future, usegmt=True)
        with mock.patch.object(
                cl, "_get_with_backoff",
                return_value=_FakeResp(429, {}, {"Retry-After": header})):
            r = cl.verify_niche("levitation", family="emotes")
        self.assertFalse(r["ok"])
        self.assertTrue(cl._circuit_open())
        cl._reset_circuit()


if __name__ == "__main__":
    unittest.main(verbosity=2)
