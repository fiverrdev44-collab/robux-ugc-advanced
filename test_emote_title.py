"""Regression tests for live !emote_title defects.

All DB/live/AI calls are mocked. No production data or network is touched.
"""
import asyncio
import json
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astra
import chain
import emote_title_engine as ete
from product_understanding import validate_title

LIVE_INPUT = (
    "I created a new Roblox emote inspired by Jabbawockeez. It's a mysterious, "
    "energetic street dance with a powerful hip-hop performance style.")

PRODUCTION_INPUT = (
    "I created a new Roblox emote inspired by Jabbawockeez. It's a mysterious, "
    "energetic hip-hop street dance with a confident, powerful performance style.")

PRODUCTION_INPUT_NO_PERIOD = (
    "I created a new Roblox emote inspired by Jabbawockeez, it's a mysterious, "
    "energetic hip-hop street dance with a confident, powerful performance style.")

PROD_GOOD = [
    ("Search", "Confident Street Dance"),
    ("Branding", "Mysterious Hip Hop Dance"),
    ("Aesthetic", "Energetic Street Dance Emote"),
    ("Community", "Powerful Hip Hop Dance Emote"),
    ("Balanced", "Confident Hip Hop Street Dance"),
]

FIVE = [
    ("Search", "Mysterious Street Dance Emote"),
    ("Branding", "Energetic Street Dance Emote"),
    ("Aesthetic", "Mysterious Energetic Dance Emote"),
    ("Community", "Hip Hop Dance Emote"),
    ("Balanced", "Powerful Street Dance Emote"),
]


def _ai(titles):
    def fn(prompt, **kw):
        return json.dumps({"titles": [{"strategy": s, "title": t}
                                      for s, t in titles]})
    return fn


def _db(phrases):
    return {
        "ok": True, "matches": 18, "sampled": 18,
        "phrases": [{"phrase": p, "token_matches": 5, "exact_matches": 1,
                     "tokens": len(p.split())} for p in phrases],
        "live_shortlist": ["energetic street dance", "hip hop dance"],
        "top_examples": [{"name": "Mysterious Street Dance",
                          "favorites": 120, "price": 45}],
        "note": "sampled",
    }


def _db_clean(phrases):
    result = _db(phrases)
    result["top_examples"] = []
    return result


def _live_ok(phrases):
    return [{"keyword": p, "ok": True, "category_correct": 10,
             "category_mismatched": 0, "exact_title_matches": 0,
             "conceptual_matches": 3, "top_competitors": [],
             "checked_at": "2026-11-05T00:00:00Z"} for p in phrases]


def _live_429(phrases):
    if not phrases:
        return []
    p = phrases[0]
    return [{"keyword": p, "ok": False, "error": "rate limited (429)",
             "checked_at": "2026-11-05T00:00:00Z", "deferred": True}]


def _title_db(title):
    return {"ok": True, "exact": False, "source": "database",
            "checked_at": "2026-11-05T00:00:00Z"}


def _title_live_mixed(title):
    if "Mysterious Street Dance" in title:
        return {"ok": True, "exact_title_matches": 1, "conceptual_matches": 3,
                "top_competitors": [{"name": title, "asset_type_id": 61}],
                "checked_at": "2026-11-05T00:00:00Z"}
    return {"ok": True, "exact_title_matches": 0, "conceptual_matches": 4,
            "top_competitors": [{"name": "Some Other Emote",
                                 "asset_type_id": 61}],
            "checked_at": "2026-11-05T00:00:00Z"}


def _title_live_exact_similar(title):
    if title == "Mysterious Street Dance Emote":
        return {"ok": True, "exact_title_matches": 1, "conceptual_matches": 3,
                "top_competitors": [{"name": title, "asset_type_id": 61}],
                "checked_at": "2026-11-05T00:00:00Z"}
    if title == "Energetic Street Dance Emote":
        return {"ok": True, "exact_title_matches": 0, "conceptual_matches": 4,
                "top_competitors": [{"name": "Energetic Street Dance",
                                     "asset_type_id": 61}],
                "checked_at": "2026-11-05T00:00:00Z"}
    return {"ok": True, "exact_title_matches": 0, "conceptual_matches": 0,
            "top_competitors": [], "checked_at": "2026-11-05T00:00:00Z"}


def _generate(**overrides):
    kw = dict(db_fn=_db, live_fn=_live_ok, generate_fn=_ai(FIVE),
              title_db_fn=_title_db, title_live_fn=_title_live_mixed)
    kw.update(overrides)
    return ete.generate(LIVE_INPUT, **kw)


class SemanticExtractionTests(unittest.TestCase):
    def test_created_never_researched(self):
        captured = {}

        def db_fn(phrases):
            captured["db"] = list(phrases)
            return _db(phrases)

        def live_fn(phrases):
            captured["live"] = list(phrases)
            return _live_ok(phrases)

        res = _generate(db_fn=db_fn, live_fn=live_fn)
        terms = captured["db"] + captured["live"]
        self.assertFalse(any("created" in t for t in terms), terms)
        self.assertNotIn("created", res["research_keywords"])

    def test_multiword_dance_concepts_preferred(self):
        res = _generate()
        concepts = res["concepts"]
        expected = ("street dance", "hip hop dance", "mysterious dance",
                    "energetic street dance")
        present = [c for c in expected if c in concepts]
        self.assertGreaterEqual(len(present), 3, concepts)
        self.assertTrue(any(" " in p for p in res["research_keywords"][:2]),
                        res["research_keywords"])

    def test_public_description_is_natural(self):
        res = _generate()
        desc = res["description"]
        low = desc.lower()
        for bad in ("created", "centered on", "built around", "inspired by",
                    "based on", "jabbawockeez", "keyword"):
            self.assertNotIn(bad, low)
        self.assertIn("street dance", low)
        self.assertTrue(desc.startswith("Meet "))
        self.assertGreaterEqual(low.count("."), 2)
        self.assertNotIn("mysterious, energetic, street.", low)


class TitleVerificationTests(unittest.TestCase):
    def test_exact_similar_conceptual_insufficient(self):
        direct = ete.verify_titles(
            [{"title": "Mysterious Street Dance Emote"},
             {"title": "Hip Hop Dance Emote"}],
            db_fn=_title_db, live_fn=_title_live_mixed)
        self.assertEqual([c["status"] for c in direct],
                         ["exact", "conceptual"])
        self.assertTrue(all(c["checked_at"] for c in direct))

    def test_generate_attaches_title_checks(self):
        res = _generate(title_live_budget=2)
        self.assertTrue(res["title_checks"])
        valid = {"exact", "similar", "conceptual", "none", "insufficient"}
        for c in res["title_checks"]:
            self.assertIn(c["status"], valid)
            self.assertTrue(c["checked_at"])
        report = ete.format_report(res)
        self.assertIn("Title-level verification", report)
        self.assertIn("keyword-level, not candidate-title", report)

    def test_exact_title_is_demoted(self):
        titles = [{"title": "Mysterious Street Dance Emote", "strategy": "A"},
                  {"title": "Hip Hop Dance Emote", "strategy": "B"}]
        checks = [{"title": "Mysterious Street Dance Emote",
                   "status": "exact", "checked_at": "2026-11-05T00:00:00Z"}]
        ranked = ete.rank_titles(
            titles, LIVE_INPUT, ["street dance", "hip hop dance"],
            _db(["street dance"]), _live_ok(["street dance"]),
            title_checks=checks)
        self.assertEqual(ranked[0]["title"], "Hip Hop Dance Emote")
        exact = next(t for t in ranked
                     if t["title"] == "Mysterious Street Dance Emote")
        self.assertEqual(exact["components"]["verified_similarity"], 0.0)

    def test_unchecked_winner_is_labeled_unverified(self):
        # The first two candidates are checked and demoted (exact/similar);
        # whichever candidate wins afterwards was not checked and must be
        # labeled unverified without another API request.
        res = _generate(db_fn=_db_clean,
                        title_live_fn=_title_live_exact_similar,
                        title_live_budget=2)
        winner = res["titles"][0]
        checked = {c["title"] for c in res["title_checks"]}
        self.assertIn("Mysterious Street Dance Emote", checked)
        self.assertIn("Energetic Street Dance Emote", checked)
        self.assertNotIn(winner["title"], checked)
        self.assertEqual(winner["title_check_status"], "unverified")
        self.assertEqual(res["recommended_verification"]["status"],
                         "unverified")
        report = ete.format_report(res)
        self.assertIn("unverified (not checked", report)
        # No extra live requests were made for the unchecked winner.
        self.assertEqual(len(res["title_checks"]), 2)


class RateLimitTests(unittest.TestCase):
    def test_research_live_stops_after_429(self):
        calls = []

        def fake_verify(phrase, family=None, max_pages=None):
            calls.append(phrase)
            return {"ok": False, "error": "rate limited (429)"}

        with mock.patch("convergence_live.verify_niche",
                        side_effect=fake_verify):
            out = ete.research_live(["street dance", "hip hop dance"])
        self.assertEqual(calls, ["street dance"])
        self.assertTrue(out[-1]["deferred"])
        self.assertTrue(out[-1]["checked_at"])

    def test_generate_defers_title_live_after_429(self):
        def must_not_call(title):
            raise AssertionError("title live check called after rate limit")

        res = _generate(live_fn=_live_429, title_live_fn=must_not_call)
        self.assertTrue(res["research"]["live_deferred"])
        report = ete.format_report(res)
        self.assertIn("incomplete", report.lower())
        self.assertIn("deferred", report.lower())
        self.assertTrue(all(c["status"] in ("insufficient", "exact",
                                            "unverified")
                            for c in res["title_checks"]))

    def test_no_evidence_caps_score_and_labels_unknown(self):
        res = _generate(
            db_fn=lambda p: {"ok": False, "error": "db down",
                             "live_shortlist": []},
            live_fn=_live_429,
            title_db_fn=lambda t: {"ok": False, "exact": False,
                                   "error": "db down",
                                   "checked_at": "2026-11-05T00:00:00Z"})
        for t in res["titles"]:
            self.assertLessEqual(t["score"], 60.0)
            self.assertEqual(t["evidence_status"], "insufficient")
            self.assertEqual(t["components"]["unknown_demand"], "unknown")
        self.assertIn("demand: unknown", ete.format_report(res).lower())


class GenerationQualityTests(unittest.TestCase):
    def test_five_distinct_grounded_titles(self):
        res = _generate()
        titles = [t["title"] for t in res["titles"]]
        self.assertEqual(len(titles), 5)
        self.assertEqual(len({t.lower() for t in titles}), 5)
        for t in titles:
            self.assertNotIn("jabbawockeez", t.lower())
            self.assertIsNone(
                re.search(r"\b(made|based|inspired)\b", t.lower()), t)
            ok, why = validate_title(LIVE_INPUT, t, family="emotes")
            self.assertTrue(ok, (t, why))
            self.assertTrue(ete.motion_grounded(LIVE_INPUT, t), t)
            self.assertFalse(astra.contains_banned_platform(t), t)

    def test_no_movement_hallucinated(self):
        desc = "a calm idle emote"
        res = ete.generate(
            desc, db_fn=_db, live_fn=_live_ok,
            generate_fn=_ai([("Search", "Spinning Flip Emote"),
                             ("Branding", "Calm Idle Emote")]),
            title_db_fn=_title_db, title_live_fn=_title_live_mixed)
        for t in res["titles"]:
            self.assertTrue(ete.motion_grounded(desc, t["title"]), t)
            self.assertNotIn("spinning", t["title"].lower())
            self.assertNotIn("flip", t["title"].lower())

    def test_experiment_is_observational(self):
        res = _generate()
        plan = res["experiment"].lower()
        self.assertIn("observational", plan)
        self.assertIn("not a randomized a/b test", plan)
        self.assertIn("does not establish causality", plan)
        self.assertNotIn("seven days", plan)


class RealDiscordExampleTests(unittest.TestCase):
    def test_five_candidate_calibration(self):
        concepts = ete.extract_concepts(LIVE_INPUT)
        identity = ete.extract_product_identity(LIVE_INPUT, concepts)
        names = [
            "Mysterious Energetic Emote",
            "Mysterious Hip Hop Dance",
            "Energetic Hip Hop Dance",
            "Mysterious Street Dance",
            "Mysterious Emote",
        ]
        ranked = ete.rank_titles(
            [{"title": n, "strategy": "example"} for n in names],
            LIVE_INPUT, concepts, _db_clean(["dance"]), _live_ok(["dance"]),
            title_checks=[], identity=identity)
        by = {t["title"]: t for t in ranked}
        for n in names:
            c = by[n]["components"]
            print(
                f"[five] {n!r}: score={by[n]['score']} "
                f"natural={c['natural_readability']} "
                f"memory={c['memorability']} clarity={c['product_clarity']} "
                f"originality={c['originality']} relevance={c['relevance']} "
                f"identity={c['identity_recognized']}")

        self.assertLess(by["Mysterious Energetic Emote"]["components"][
            "product_clarity"], 0.5)
        self.assertLess(by["Mysterious Emote"]["components"][
            "product_clarity"], 0.5)
        for good in ("Mysterious Hip Hop Dance", "Energetic Hip Hop Dance",
                     "Mysterious Street Dance"):
            self.assertGreaterEqual(by[good]["components"][
                "product_clarity"], 0.9)

        order = [t["title"] for t in ranked]
        self.assertIn(order[0], ("Mysterious Hip Hop Dance",
                                 "Energetic Hip Hop Dance",
                                 "Mysterious Street Dance"))
        self.assertIn(order[-1], ("Mysterious Energetic Emote",
                                  "Mysterious Emote"))


class ProductionAcceptanceTests(unittest.TestCase):
    def test_redundant_phrase_deduped(self):
        calls = []

        def fake_verify(phrase, **kw):
            calls.append(phrase)
            return {"ok": True, "category_correct": 3,
                    "category_mismatched": 0, "exact_title_matches": 0,
                    "conceptual_matches": 1, "top_competitors": [],
                    "verification_timestamp": "2026-11-05T00:00:00Z"}

        with mock.patch("convergence_live.verify_niche",
                        side_effect=fake_verify):
            out = ete.research_live(["hip hop street dance",
                                     "hop street dance"])
        self.assertEqual(calls, ["hip hop street dance"])
        self.assertEqual(len(out), 1)

    def test_sufficiency_skips_distinct_second_query(self):
        calls = []

        def fake_verify(phrase, **kw):
            calls.append(phrase)
            return {"ok": True, "category_correct": 24,
                    "category_mismatched": 0, "exact_title_matches": 0,
                    "conceptual_matches": 2, "top_competitors": [],
                    "verification_timestamp": "2026-11-05T00:00:00Z"}

        with mock.patch("convergence_live.verify_niche",
                        side_effect=fake_verify):
            out = ete.research_live(["hip hop street dance", "robot dance"])
        self.assertEqual(calls, ["hip hop street dance"])
        self.assertEqual(out[0].get("skipped_for_sufficiency"),
                         ["robot dance"])

    def test_second_distinct_query_when_insufficient(self):
        calls = []

        def fake_verify(phrase, **kw):
            calls.append(phrase)
            return {"ok": True, "category_correct": 3,
                    "category_mismatched": 0, "exact_title_matches": 0,
                    "conceptual_matches": 1, "top_competitors": [],
                    "verification_timestamp": "2026-11-05T00:00:00Z"}

        with mock.patch("convergence_live.verify_niche",
                        side_effect=fake_verify):
            out = ete.research_live(["hip hop street dance", "robot dance"])
        self.assertEqual(calls, ["hip hop street dance", "robot dance"])
        self.assertEqual(len(out), 2)

    def test_unsupported_claims_rejected_metaphors_allowed(self):
        protected = ete.extract_protected_names(PRODUCTION_INPUT)
        bad, why = ete._validate_candidate(PRODUCTION_INPUT,
                                           "Masked Groove Dance", protected)
        self.assertIsNone(bad)
        self.assertIn("unsupported claim", why)

        good, why_good = ete._validate_candidate(
            PRODUCTION_INPUT, "Enigma Street Dance", protected)
        self.assertEqual(good, "Enigma Street Dance")
        self.assertIsNone(why_good)

        bad2, _ = ete._validate_candidate(PRODUCTION_INPUT,
                                          "Glowing Aura Emote", protected)
        self.assertIsNone(bad2)

        confident, _ = ete._validate_candidate(
            PRODUCTION_INPUT, "Confident Street Dance", protected)
        self.assertEqual(confident, "Confident Street Dance")

    def test_description_preserves_identity(self):
        for desc in (PRODUCTION_INPUT, PRODUCTION_INPUT_NO_PERIOD):
            with self.subTest(desc=desc[:45]):
                res = ete.generate(
                    desc, db_fn=_db_clean, live_fn=_live_ok,
                    generate_fn=_ai(PROD_GOOD), title_db_fn=_title_db,
                    title_live_budget=0)
                text = res["description"]
                low = text.lower()
                self.assertIn("street dance", low)
                self.assertTrue("hip-hop" in low or "hip hop" in low, text)
                self.assertIn("mysterious", low)
                self.assertIn("confident", low)
                self.assertIn("powerful", low)
                for bad in ("created", "jabbawockeez", "centered on",
                            "built around", "keyword"):
                    self.assertNotIn(bad, low)

    def test_provenance_provider_and_fallback(self):
        res = _generate()
        prov = res["provenance"]
        self.assertEqual(prov["provider"], "mock")
        self.assertFalse(prov["fallback_used"])
        self.assertGreater(prov["ai_generated"], 0)
        self.assertGreater(prov["deterministic_generated"], 0)

        res2 = _generate(generate_fn=lambda *a, **k: None)
        prov2 = res2["provenance"]
        self.assertTrue(prov2["fallback_used"])
        self.assertEqual(prov2["ai_generated"], 0)
        self.assertGreater(prov2["deterministic_generated"], 0)


class SecureTikTokTests(unittest.TestCase):
    def test_rejects_non_tiktok_hosts(self):
        for url in ("https://tiktok.com.evil.com/x",
                    "https://evil.com/?tiktok.com",
                    "javascript:alert(1)",
                    "https://tiktok.com@127.0.0.1/x",
                    "https://www.tiktok.com:8443/x",
                    "http://www.tiktok.com/@x/video/1"):
            _host, err = ete.validate_tiktok_url(url)
            self.assertTrue(err, url)

    def test_no_network_for_reference(self):
        with mock.patch("socket.getaddrinfo",
                        side_effect=AssertionError("dns called")), \
                mock.patch("requests.sessions.Session.get",
                           side_effect=AssertionError("HTTP called")):
            res = ete.fetch_tiktok_meta("https://www.tiktok.com/@x/video/1")
        self.assertFalse(res["ok"])
        self.assertTrue(res["reference_valid"])


class ChainStillWorksTests(unittest.TestCase):
    def test_chain_astra_filter_rejects_banned_and_motion_swaps(self):
        kept = chain._astra_filter(
            ["Viral TikTok Emote", "Dreamy Fairy Emote"], "fairy float",
            "emotes")
        self.assertEqual(kept, ["Dreamy Fairy Emote"])
        kept_motion = chain._astra_filter(
            ["Fairy Dance Emote", "Fairy Float Emote"], "fairy float",
            "emotes")
        self.assertEqual(kept_motion, ["Fairy Float Emote"])


class _FakeMessage:
    def __init__(self, channel):
        self.channel = channel

    async def edit(self, content=None, **kw):
        self.channel.edits.append(content)
        return self

    async def delete(self):
        self.channel.deleted = True


class _FakeChannel:
    def __init__(self):
        self.sent = []
        self.edits = []
        self.deleted = False

    async def send(self, content=None, **kw):
        self.sent.append(content)
        return _FakeMessage(self)


class _FakeCtx:
    def __init__(self):
        self.channel = _FakeChannel()

    async def send(self, content=None, **kw):
        self.channel.sent.append(content)
        return _FakeMessage(self.channel)


class _FakeBot:
    def __init__(self):
        self.commands = {}

    def command(self, name=None, **kw):
        def deco(fn):
            self.commands[name or kw.get("name")] = fn
            return fn
        return deco


class CommandTests(unittest.TestCase):
    def test_command_renders_report(self):
        import commands_emote
        bot = _FakeBot()
        commands_emote.register_emote_commands(bot, None)
        ctx = _FakeCtx()
        fake_result = {"titles": [], "recommended": None, "description": "d",
                       "experiment": "e", "research": {}}
        with mock.patch.object(ete, "generate", return_value=fake_result), \
                mock.patch.object(ete, "format_report",
                                  return_value="REPORT-BODY"):
            asyncio.run(bot.commands["emote_title"](ctx, args=LIVE_INPUT))
        self.assertIn("REPORT-BODY", ctx.channel.sent)

    def test_command_requires_description(self):
        import commands_emote
        bot = _FakeBot()
        commands_emote.register_emote_commands(bot, None)
        ctx = _FakeCtx()
        asyncio.run(bot.commands["emote_title"](ctx,
                                                args="https://x.com/a"))
        self.assertTrue(any("Usage" in (m or "") for m in ctx.channel.sent))


if __name__ == "__main__":
    unittest.main(verbosity=2)
