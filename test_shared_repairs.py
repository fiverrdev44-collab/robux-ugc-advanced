"""Regression tests for shared repairs (no network; DB section skipped locally)."""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gap_engine
import live_market
import safe_roblox
import search_visibility as sv
from execution_policy import default_scheduler


def _reset_shared():
    safe_roblox.reset_for_tests()
    default_scheduler().reset()


class _Resp429:
    status_code = 429
    headers = {"Retry-After": "0"}


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
    _reset_shared()
    rows, pages, status, error = sv._fetch_query(_Session429(), "query")
    assert status == "rate_limited", status
    assert error == "HTTP 429 rate limited", error
    print("PASS visibility 429 error capture")


def test_fetch_query_empty_is_completed():
    _reset_shared()
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


def test_live_market_uses_shared_transport_without_local_retry():
    class Response:
        status_code = 429
        headers = {"Retry-After": "0"}

    with mock.patch.object(
            live_market, "safe_get", return_value=Response()) as shared_get:
        r = live_market._get_with_backoff("http://x", {"Keyword": "k"})
    assert r.status_code == 429
    shared_get.assert_called_once()
    assert shared_get.call_args.args[:2] == ("catalog_search", "http://x")
    print("PASS live_market delegates to shared transport")


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


def test_chain_type_detection_word_boundary():
    import chain
    # "that" must not match the hat type word "hat".
    text = ("A 3D wooden picket fence accessory featuring signs that read "
            "'i need personal space!'")
    assert chain._detect_type_override(text) is None, text
    assert chain._detect_type_override("cute beanie") == "hat"
    assert chain._detect_type_override("personal space sign") is None
    assert "belt" in chain._DEFAULT_TYPE_WORDS["waist"]
    assert "hat" not in chain._DEFAULT_TYPE_WORDS["waist"]

    titles = chain._fallback_titles(text, "waist")
    assert all(len(t) <= 50 for t in titles)
    assert any("Belt" in t for t in titles)
    assert all("Hat" not in t for t in titles)
    assert "Accessory" not in titles[0]  # short core, no vision boilerplate
    print("PASS chain type detection uses word boundaries")


def test_autopsy_sales_ground_truth():
    import recovery_brain as rb
    assert rb.choose_protocol("KEEP", 3) == "scale"
    assert rb.choose_protocol("KILL", 3) == "scale"
    assert rb.choose_protocol("KILL", 0) == "recovery"
    body = rb.format_scale_protocol("KEEP", 3, {"favs": 11, "age_days": 182.0,
                                                "price": 65})
    low = body.lower()
    assert "keep" in low
    assert "zero sales" not in low and "no sales" not in low
    assert "kill" not in low
    guard = rb.sales_guard_instruction(3)
    assert "total_sales_30d = 3" in guard and "FORBIDDEN" in guard
    print("PASS autopsy sales ground truth")


def test_static_prop_title_gate():
    from category_configs import is_static_prop
    import chain
    concept = "waist: wooden fence sign with personal space planks"
    assert is_static_prop(concept)
    raw = ["Cyber Board Necklace", "Cardboard Sign Chain",
           "Wooden Fence Sign", "Personal Space Necklace"]
    cleaned = chain._sanitize_titles(raw)
    text = " ".join(cleaned).lower()
    assert "necklace" not in text and "chain" not in text
    assert cleaned
    titles = chain._fallback_titles(concept, "waist")
    assert all("necklace" not in t.lower() and "chain" not in t.lower()
               for t in chain._sanitize_titles(titles))
    print("PASS static prop title gate")


if __name__ == "__main__":
    test_fetch_query_429_sets_error()
    test_fetch_query_empty_is_completed()
    test_gap_rejects_cross_family_words()
    test_live_market_uses_shared_transport_without_local_retry()
    test_chain_fallback_without_ai()
    test_batch_client_chunks_and_backoff()
    test_chain_type_detection_word_boundary()
    test_autopsy_sales_ground_truth()
    test_static_prop_title_gate()
    print("ALL SHARED REPAIR TESTS PASSED")
