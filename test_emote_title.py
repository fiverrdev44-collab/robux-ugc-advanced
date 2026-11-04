"""Tests for the Emote Reference Title Engine.

All DB/network/live calls are mocked; no production data is touched.
"""
import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astra
import chain
import emote_title_engine as ete
from product_understanding import validate_title

DESC = "a dreamy fairy that floats and glows softly"


def _db(*a, **k):
    return {"ok": True, "matches": 12, "sampled": 12,
            "top_examples": [{"name": "Dreamy Fairy", "favorites": 120,
                              "price": 45}],
            "note": "sampled"}


def _live_ok(*a, **k):
    return [{"keyword": "dreamy", "ok": True, "sampled_results": 30,
             "category_correct": 28, "category_mismatched": 2,
             "exact_title_matches": 1, "conceptual_matches": 6,
             "top_competitors": [{"name": "Dreamy Float", "favorites": 90,
                                  "price": 40, "asset_type_id": 61}],
             "verification_timestamp": "2026-11-04T00:00:00Z"}]


def _live_429(*a, **k):
    return [{"keyword": "dreamy", "ok": False,
             "error": "rate limited (429)"}]


class EngineTests(unittest.TestCase):
    def _assert_titles_valid(self, res, concept=DESC):
        self.assertEqual(len(res["titles"]), 5)
        self.assertTrue(res["recommended"])
        titles = [t["title"] for t in res["titles"]]
        self.assertEqual(len({t.lower() for t in titles}), 5)
        for t in titles:
            ok, why = validate_title(concept, t, family="emotes")
            self.assertTrue(ok, (t, why))
            self.assertFalse(astra.contains_banned_platform(t), t)
            self.assertNotIn("viral", t.lower())
            self.assertNotIn("trending", t.lower())
            self.assertNotIn("tiktok", t.lower())
            self.assertNotIn("youtube", t.lower())

    def test_without_url(self):
        res = ete.generate(DESC, url=None, db_fn=_db, live_fn=_live_ok)
        self._assert_titles_valid(res)
        self.assertIn("fairy", res["description"].lower())
        self.assertTrue(res["experiment"])
        self.assertEqual(res["titles"][0]["title"], res["recommended"])

    def test_with_url_caption(self):
        meta = {"ok": True, "caption": "fairy glow #fyp #fairycore",
                "hashtags": ["fairycore"]}
        with mock.patch.object(ete, "fetch_tiktok_meta", return_value=meta):
            res = ete.generate(DESC, url="https://www.tiktok.com/@x/video/1",
                               db_fn=_db, live_fn=_live_ok)
        self._assert_titles_valid(res)
        self.assertTrue(res["research"]["tiktok"]["ok"])
        # Hashtag keywords are research-only; titles stay description-grounded.
        for t in res["titles"]:
            self.assertNotIn("fairycore", t["title"].lower())

    def test_url_inaccessible(self):
        with mock.patch.object(ete, "fetch_tiktok_meta",
                               return_value={"ok": False, "error": "HTTP 403"}):
            res = ete.generate(DESC, url="https://www.tiktok.com/@x/video/2",
                               db_fn=_db, live_fn=_live_ok)
        self._assert_titles_valid(res)
        self.assertIn("unavailable", ete.format_report(res).lower())

    def test_banned_words_stripped(self):
        desc = "a viral trending tiktok youtube fairy that floats"
        res = ete.generate(desc, db_fn=_db, live_fn=_live_ok)
        self._assert_titles_valid(res, concept=desc)
        for bad in ("viral", "trending", "tiktok", "youtube"):
            self.assertNotIn(bad, res["description"].lower())
            for t in res["titles"]:
                self.assertNotIn(bad, t["title"].lower())

    def test_live_429_is_incomplete_not_invented(self):
        res = ete.generate(DESC, db_fn=_db, live_fn=_live_429)
        self._assert_titles_valid(res)
        self.assertFalse(res["research"]["live_ok"])
        report = ete.format_report(res)
        self.assertIn("incomplete", report.lower())
        self.assertIn("429", report)
        self.assertNotIn("Dreamy Float", report)  # no fabricated competitor

    def test_every_title_revalidated_before_output(self):
        res = ete.generate(DESC, db_fn=_db, live_fn=_live_ok)
        for t in res["titles"]:
            ok, _ = validate_title(DESC, t["title"], family="emotes")
            self.assertTrue(ok)


class ChainStillWorksTests(unittest.TestCase):
    def test_chain_astra_filter_rejects_banned_and_motion_swaps(self):
        kept = chain._astra_filter(
            ["Viral TikTok Emote", "Dreamy Fairy Emote"], DESC, "emotes")
        self.assertEqual(kept, ["Dreamy Fairy Emote"])

        kept_motion = chain._astra_filter(
            ["Fairy Dance Emote", "Fairy Float Emote"],
            "fairy float", "emotes")
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
        fake_result = {"titles": [], "recommended": None,
                       "description": "d", "experiment": "e",
                       "research": {}}
        with mock.patch.object(ete, "generate", return_value=fake_result), \
                mock.patch.object(ete, "format_report",
                                  return_value="REPORT-BODY"):
            asyncio.run(bot.commands["emote_title"](ctx, args=DESC))
        self.assertIn("REPORT-BODY", ctx.channel.sent)

    def test_command_requires_description(self):
        import commands_emote
        bot = _FakeBot()
        commands_emote.register_emote_commands(bot, None)
        ctx = _FakeCtx()
        asyncio.run(bot.commands["emote_title"](ctx, args="https://x.com/a"))
        self.assertTrue(any("Usage" in (m or "") for m in ctx.channel.sent))


if __name__ == "__main__":
    unittest.main(verbosity=2)
