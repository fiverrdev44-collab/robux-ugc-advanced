"""Tests for the Emote Reference Title Engine (AI-first, ranked, secure)."""
import asyncio
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astra
import chain
import emote_title_engine as ete
from product_understanding import validate_title

JABBA = ("I made a new emote inspired by Jabbawockeez. It's a mysterious, "
         "energetic street dance.")


def _db(*a, **k):
    return {"ok": True, "matches": 12, "sampled": 12,
            "top_examples": [{"name": "Mysterious Street Dance",
                              "favorites": 120, "price": 45}],
            "note": "sampled"}


def _live_ok(*a, **k):
    return [{"keyword": "mysterious", "ok": True, "sampled_results": 30,
             "category_correct": 28, "category_mismatched": 2,
             "exact_title_matches": 1, "conceptual_matches": 6,
             "top_competitors": [{"name": "Energetic Street Dance",
                                  "favorites": 90, "price": 40,
                                  "asset_type_id": 61}],
             "verification_timestamp": "2026-11-04T00:00:00Z"}]


def _live_429(*a, **k):
    return [{"keyword": "mysterious", "ok": False, "error": "rate limited (429)"}]


def _ai(titles):
    def fn(prompt, **kwargs):
        return json.dumps({"titles": [{"strategy": s, "title": t}
                                      for s, t in titles]})
    return fn


FIVE_GOOD = [
    ("Search", "Mysterious Street Dance Emote"),
    ("Branding", "Energetic Street Dance Emote"),
    ("Aesthetic", "Mysterious Energetic Dance Emote"),
    ("Community", "Energetic Mysterious Street Emote"),
    ("Balanced", "Street Mysterious Energetic Dance Emote"),
]


class JabbaTests(unittest.TestCase):
    def setUp(self):
        self.res = ete.generate(
            JABBA, db_fn=_db, live_fn=_live_ok, generate_fn=_ai(FIVE_GOOD))

    def test_five_meaningfully_different_titles(self):
        titles = [t["title"] for t in self.res["titles"]]
        self.assertEqual(len(titles), 5)
        self.assertEqual(len({t.lower() for t in titles}), 5)
        for i in range(len(titles)):
            for j in range(i + 1, len(titles)):
                a = {x for x in ete._tokens(titles[i]) if x != "emote"}
                b = {x for x in ete._tokens(titles[j]) if x != "emote"}
                jaccard = len(a & b) / max(1, len(a | b))
                self.assertLess(jaccard, 0.8, (titles[i], titles[j]))

    def test_no_unauthorized_performer_branding(self):
        for t in self.res["titles"]:
            self.assertNotIn("jabbawockeez", t["title"].lower())
        self.assertIn("jabbawockeez", self.res["protected_names"])

    def test_no_mechanical_titles(self):
        for t in self.res["titles"]:
            self.assertNotRegex(t["title"].lower(), r"\b(made|based|inspired)\b")

    def test_titles_are_grounded_and_validated(self):
        for t in self.res["titles"]:
            self.assertTrue(ete.motion_grounded(JABBA, t["title"]), t)
            ok, why = validate_title(JABBA, t["title"], family="emotes")
            self.assertTrue(ok, (t["title"], why))
            self.assertFalse(astra.contains_banned_platform(t["title"]))

    def test_recommended_is_evaluated_not_first(self):
        # The AI's first title exactly matches a DB competitor, so its
        # differentiation drops and it must not win automatically.
        self.assertEqual(self.res["titles"][0]["recommended"], True)
        self.assertNotEqual(self.res["recommended"],
                            "Mysterious Street Dance Emote")
        scores = [t["score"] for t in self.res["titles"]]
        self.assertEqual(self.res["titles"][0]["score"], max(scores))
        for t in self.res["titles"]:
            self.assertIn("components", t)
            for key in ("accuracy", "natural", "search",
                        "differentiation", "evidence"):
                self.assertIn(key, t["components"])

    def test_experiment_is_observational(self):
        exp = self.res["experiment"].lower()
        self.assertIn("observational", exp)
        self.assertIn("not a randomized a/b test", exp)
        self.assertNotIn("seven days", exp)

    def test_banned_words_stripped(self):
        desc = "a viral trending tiktok youtube fairy that floats"
        res = ete.generate(desc, db_fn=_db, live_fn=_live_ok,
                           generate_fn=_ai([("Search", "Viral Fairy Emote"),
                                            ("Branding", "TikTok Float Emote")]))
        for t in res["titles"]:
            for bad in ("viral", "trending", "tiktok", "youtube"):
                self.assertNotIn(bad, t["title"].lower())
        self.assertNotIn("viral", res["description"].lower())

    def test_motion_invention_rejected(self):
        desc = "a calm idle emote"
        res = ete.generate(
            desc, db_fn=_db, live_fn=_live_ok,
            generate_fn=_ai([("Search", "Spinning Flip Emote"),
                             ("Branding", "Calm Idle Emote")]))
        for t in res["titles"]:
            self.assertTrue(ete.motion_grounded(desc, t["title"]), t)
            self.assertNotIn("spinning", t["title"].lower())
            self.assertNotIn("flip", t["title"].lower())

    def test_live_429_is_honest(self):
        res = ete.generate(JABBA, db_fn=_db, live_fn=_live_429,
                           generate_fn=_ai(FIVE_GOOD))
        self.assertFalse(res["research"]["live_ok"])
        report = ete.format_report(res)
        self.assertIn("incomplete", report.lower())
        self.assertIn("429", report)
        # Evidence quality is marked incomplete; no competitor is invented.
        self.assertTrue(all(t["evidence_quality"] == "incomplete"
                            for t in res["titles"]))


class SecureTikTokTests(unittest.TestCase):
    def test_rejects_non_tiktok_hosts(self):
        for url in ("https://tiktok.com.evil.com/x",
                    "https://evil.com/?tiktok.com",
                    "javascript:alert(1)",
                    "https://tiktok.com@127.0.0.1/x",
                    "https://www.tiktok.com:8443/x",
                    "http://www.tiktok.com/@x/video/1"):
            host, err = ete.validate_tiktok_url(url)
            self.assertTrue(err, url)

    def test_valid_reference_has_no_network_access(self):
        with mock.patch("socket.getaddrinfo", side_effect=AssertionError("dns called")), \
             mock.patch("requests.sessions.Session.get", side_effect=AssertionError("HTTP called")):
            res = ete.fetch_tiktok_meta("https://www.tiktok.com/@x/video/1")
        self.assertFalse(res["ok"])
        self.assertTrue(res["reference_valid"])
        self.assertIn("disabled", res["error"])
        self.assertIsNone(ete.validate_tiktok_url("https://vm.tiktok.com/Zabc123/")[1])

    def test_description_only_fallback(self):
        with mock.patch("requests.sessions.Session.get", side_effect=AssertionError("HTTP called")):
            result = ete.generate(JABBA, url="https://www.tiktok.com/@x/video/1",
                                  db_fn=_db, live_fn=_live_ok,
                                  generate_fn=_ai(FIVE_GOOD))
        self.assertTrue(result["titles"])
        self.assertFalse(result["research"]["tiktok"]["ok"])


class ListingAndEvidenceTests(unittest.TestCase):
    def test_no_brand_or_creator_instructions_in_public_description(self):
        result = ete.generate(JABBA, db_fn=_db, live_fn=_live_ok,
                              generate_fn=_ai(FIVE_GOOD))
        desc = result["description"].lower()
        for forbidden in ("jabbawockeez", "i made", "inspired by",
                          "based on"):
            self.assertNotIn(forbidden, desc)

    def test_feasible_observational_experiment(self):
        res = ete.generate(JABBA, db_fn=_db, live_fn=_live_ok,
                           generate_fn=_ai(FIVE_GOOD))
        plan = res["experiment"].lower()
        self.assertIn("observational", plan)
        self.assertIn("not a randomized a/b test", plan)
        self.assertIn("does not establish causality", plan)
        self.assertNotIn("show", plan)

    def test_evidence_requires_relevant_competitor_names(self):
        titles = [{"strategy": "Test", "title": "Mysterious Street Dance Emote"}]
        no_names = {"ok": True, "matches": 0, "top_examples": []}
        clean_live = [{"ok": True, "top_competitors": []}]
        ranked = ete.rank_titles(titles, JABBA, ["mysterious"], no_names, clean_live)
        comp = ranked[0]["components"]
        self.assertEqual(comp["retrieval"], 1.0)
        self.assertEqual(comp["market_context"], 0.0)
        self.assertEqual(comp["evidence"], 0.0)
        self.assertEqual(ranked[0]["evidence_quality"],
                         "sampled, no relevant matches")


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
            asyncio.run(bot.commands["emote_title"](ctx, args=JABBA))
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
