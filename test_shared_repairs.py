"""Regression tests for shared repairs (no network; DB section skipped locally)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gap_engine
import live_market
import search_visibility as sv


class _Resp429:
    status_code = 429
    headers = {"Retry-After": "0"}


class _Resp200:
    status_code = 200
    headers = {}


class _Session429Then200:
    def __init__(self):
        self.calls = 0

    def get(self, *a, **k):
        self.calls += 1
        return _Resp429() if self.calls == 1 else _Resp200()


class _Session429:
    def get(self, *a, **k):
        return _Resp429()


class _RespEmpty:
    status_code = 200

    def json(self):
        return {"data": [], "nextPageCursor": None}


class _SessionEmpty:
    def get(self, *a, **k):
        return _RespEmpty()


def test_fetch_query_429_sets_error():
    rows, pages, status, error = sv._fetch_query(_Session429(), "query")
    assert status == "failed"
    assert error == "HTTP 429 rate limited", error
    print("PASS visibility 429 error capture")


def test_fetch_query_empty_is_completed():
    rows, pages, status, error = sv._fetch_query(_SessionEmpty(), "query")
    assert status == "completed" and rows == [] and error is None
    print("PASS visibility empty completed")


def test_gap_rejects_cross_family_words():
    assert gap_engine.is_cross_family_type_word("pants", "emote") is True
    assert gap_engine.is_cross_family_type_word("shirt", "emote") is True
    assert gap_engine.is_cross_family_type_word("dance", "emote") is False
    assert gap_engine.is_cross_family_type_word("emote", "emote") is False
    assert gap_engine.specific_niche_terms(["cute", "emote"]) == ["emote"]
    assert gap_engine.specific_niche_terms(["cute"]) == ["cute"]
    print("PASS gap family filtering")


def test_live_market_backoff_honours_retry_after():
    slept = []
    original_sleep = live_market.time.sleep
    original_get = live_market.requests.get
    session = _Session429Then200()

    def fake_get(*a, **k):
        return session.get()

    live_market.time.sleep = lambda s: slept.append(s)
    live_market.requests.get = fake_get
    try:
        r = live_market._get_with_backoff("http://x", {"Keyword": "k"})
        assert r.status_code == 200
        assert slept and slept[0] == 1.0, slept  # Retry-After 0 clamped to 1s
    finally:
        live_market.time.sleep = original_sleep
        live_market.requests.get = original_get
    print("PASS live_market 429 backoff")


def test_chain_fallback_without_ai():
    import chain
    ft = chain._fallback_titles("kawaii sway emote", "emotes")
    assert ft and all(isinstance(t, str) and t for t in ft)
    assert any("Emote" in t for t in ft)
    fi = chain._fallback_intent("kawaii sway emote")
    assert fi["item_type"] == "emote"
    assert fi["primary"]
    print("PASS chain deterministic fallback helpers")

    if not os.getenv("DATABASE_URL"):
        print("SKIP chain offline DB integration (no DATABASE_URL)")
        return
    import gemini_brain

    def boom(*a, **k):
        raise RuntimeError("provider offline")

    saved = (gemini_brain.extract_keywords, gemini_brain.synthesize_hybrid,
             gemini_brain._generate)
    gemini_brain.extract_keywords = boom
    gemini_brain.synthesize_hybrid = boom
    gemini_brain._generate = boom
    try:
        r = chain.run_chain("kawaii sway emote", live_enrich=False)
        scored = r.get("scored_titles") or []
        assert scored, r.get("error") or r
        assert isinstance(scored[0].get("title"), str) and scored[0]["title"]
        assert r.get("merged_description")
    finally:
        (gemini_brain.extract_keywords, gemini_brain.synthesize_hybrid,
         gemini_brain._generate) = saved
    print("PASS chain returns a champion with AI offline")


def test_batch_client_chunks_and_backoff():
    import asyncio
    import roblox_batch_client as rbc

    class Fake(rbc.RobloxBatchClient):
        async def _post(self, ids):
            assert len(ids) <= 30
            return [{"id": i, "name": f"item{i}"} for i in ids], {}

    async def run():
        client = Fake(max_batch=30, rate_per_min=90, max_concurrency=3)
        return await client.fetch_many_items(list(range(1, 66)))

    items, failed = asyncio.run(run())
    assert len(items) == 65 and not failed
    assert rbc.RobloxBatchClient._backoff(3, "7") == 7.0
    print("PASS batch client 30-item chunking and Retry-After")


if __name__ == "__main__":
    test_fetch_query_429_sets_error()
    test_fetch_query_empty_is_completed()
    test_gap_rejects_cross_family_words()
    test_live_market_backoff_honours_retry_after()
    test_chain_fallback_without_ai()
    test_batch_client_chunks_and_backoff()
    print("ALL SHARED REPAIR TESTS PASSED")
