"""Offline quality evaluation for the emote title engine.

Ten diverse descriptions (hip-hop, comedy, idle, pose, expressive, etc.) are
run against deterministic candidate pools that deliberately mix strong names,
generic filler, awkward phrasing, and VANTA branding. The tests assert that the
engine selects the strongest five by creative quality — not merely that titles
pass ASTRA validation. No network, DB, or AI calls are made.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astra
import emote_title_engine as ete
from product_understanding import validate_title

BAD = [
    ("Vanta Power Performance", "unrequested brand (VANTA/platform)"),
    ("Made Emote", "mechanical wording"),
    ("Based On Jabbawockeez Emote", "mechanical wording"),
    ("Powerful Style Emote", None),          # valid but generic filler
]

CASES = [
    {
        "label": "hip-hop",
        "desc": "A mysterious, energetic street dance inspired by hip-hop "
                "performance style.",
        "generic": "Hip Hop Street Dance",
        "good": ["Mysterious Street Dance Emote",
                 "Energetic Street Dance Emote",
                 "Mysterious Hip Hop Dance Emote",
                 "Energetic Dance Emote",
                 "Mysterious Street Emote"],
    },
    {
        "label": "comedy",
        "desc": "A goofy clumsy dance where the character trips and wobbles.",
        "generic": "Funny Dance Emote",
        "good": ["Goofy Trip Dance Emote", "Clumsy Wobble Emote",
                 "Goofy Clumsy Emote", "Wobble Trip Emote",
                 "Goofy Wobble Dance Emote"],
    },
    {
        "label": "idle",
        "desc": "A calm idle emote with gentle breathing and a slow blink.",
        "generic": "Calm Style Emote",
        "good": ["Calm Idle Emote", "Gentle Breathing Emote",
                 "Slow Blink Emote", "Calm Breathing Idle",
                 "Gentle Idle Emote"],
    },
    {
        "label": "pose",
        "desc": "A confident hero pose with hands on hips.",
        "generic": "Hero Style Emote",
        "good": ["Confident Hero Pose", "Hands On Hips Pose",
                 "Confident Hips Pose", "Hero Pose Emote",
                 "Confident Hands Pose"],
    },
    {
        "label": "shocked",
        "desc": "An exaggerated shocked reaction with wide eyes and a gasp.",
        "generic": "Shock Style Emote",
        "good": ["Shocked Reaction Emote", "Wide Eyed Gasp Emote",
                 "Exaggerated Shock Emote", "Shocked Gasp Emote",
                 "Wide Eyed Shocked Emote"],
    },
    {
        "label": "floating",
        "desc": "A dreamy floating pose with soft glowing movement.",
        "generic": "Float Style Emote",
        "good": ["Dreamy Floating Pose", "Soft Floating Glow Emote",
                 "Dreamy Glow Pose", "Floating Dream Emote",
                 "Soft Dreamy Float Emote", "Dreamy Floating Emote"],
    },
    {
        "label": "sad",
        "desc": "A slow sad walk with slumped shoulders.",
        "generic": "Sad Style Emote",
        "good": ["Slow Sad Walk Emote", "Slumped Shoulders Walk",
                 "Sad Slumped Walk Emote", "Slow Slumped Emote",
                 "Sad Walk Emote"],
    },
    {
        "label": "victory",
        "desc": "A celebratory victory dance with fist pumps.",
        "generic": "Victory Style Emote",
        "good": ["Victory Dance Emote", "Celebratory Victory Dance",
                 "Fist Pump Dance Emote", "Victory Fist Pump Emote",
                 "Celebratory Dance Emote"],
    },
    {
        "label": "scared",
        "desc": "A nervous scared idle with trembling and looking around.",
        "generic": "Scared Style Emote",
        "good": ["Nervous Scared Idle", "Trembling Scared Emote",
                 "Scared Look Around Emote", "Nervous Trembling Idle",
                 "Scared Nervous Emote"],
    },
    {
        "label": "confident",
        "desc": "A cool confident lean against an invisible wall.",
        "generic": "Cool Style Emote",
        "good": ["Confident Lean Emote", "Cool Confident Lean",
                 "Confident Wall Lean Emote", "Cool Lean Emote",
                 "Confident Cool Lean"],
    },
]


def _fake_ai(candidates):
    def fn(prompt, **kwargs):
        return json.dumps({"titles": [
            {"strategy": f"S{i}", "title": t}
            for i, t in enumerate(candidates)]})
    return fn


def _db(phrases):
    return {"ok": True, "matches": 9, "sampled": 9,
            "phrases": [{"phrase": p, "token_matches": 3, "exact_matches": 0,
                         "tokens": len(p.split())} for p in phrases],
            "live_shortlist": ["dance"],
            "top_examples": [{"name": "Unrelated Emote", "favorites": 10,
                              "price": 5}],
            "note": "sampled"}


def _live(phrases):
    return [{"keyword": p, "ok": True, "category_correct": 5,
             "category_mismatched": 0, "exact_title_matches": 0,
             "conceptual_matches": 1, "top_competitors": [],
             "checked_at": "2026-11-05T00:00:00Z"} for p in phrases]


def _title_db(title):
    return {"ok": True, "exact": False, "source": "database",
            "checked_at": "2026-11-05T00:00:00Z"}


class QualityEvaluationSetTests(unittest.TestCase):
    def test_ten_diverse_descriptions_select_quality(self):
        for case in CASES:
            with self.subTest(case=case["label"]):
                candidates = (case["good"] + [case["generic"]]
                              + [t for t, _ in BAD])
                res = ete.generate(
                    case["desc"], db_fn=_db, live_fn=_live,
                    generate_fn=_fake_ai(candidates),
                    title_db_fn=_title_db, title_live_budget=0)

                titles = res["titles"]
                self.assertEqual(len(titles), 5)
                self.assertGreaterEqual(res["candidates_generated"], 10)
                self.assertGreaterEqual(res["candidates_eligible"], 5)

                for t in titles:
                    self.assertFalse(astra.contains_banned_platform(t["title"]))
                    self.assertNotIn("vanta", t["title"].lower())
                    self.assertTrue(ete.motion_grounded(case["desc"],
                                                        t["title"]), t)
                    ok, why = validate_title(case["desc"], t["title"],
                                             family="emotes")
                    self.assertTrue(ok, (t["title"], why))

                winner = titles[0]
                self.assertIn(res["recommended"], case["good"])
                self.assertNotEqual(res["recommended"], case["generic"])
                self.assertGreaterEqual(
                    winner["components"]["product_clarity"], 0.7)
                self.assertGreater(winner["components"]["originality"], 0.3)
                self.assertGreaterEqual(
                    sum(1 for t in titles
                        if t["components"]["product_clarity"] >= 0.7), 3)

                # The generic best-overlap title must not survive in the five.
                final_lower = [t["title"].lower() for t in titles]
                self.assertNotIn(case["generic"].lower(), final_lower)
                accounted = (
                    [r["title"].lower() for r in res["rejected"]]
                    + [t["title"].lower() for t in res.get("not_selected", [])])
                self.assertIn(case["generic"].lower(), accounted)

                reasons = {r.get("reason") for r in res["rejected"]}
                self.assertIn("unrequested brand (VANTA/platform)", reasons)
                self.assertIn("mechanical wording", reasons)

                # Evidence availability is recorded, not fabricated.
                self.assertIn("db", res["research"])
                self.assertIn("live", res["research"])
                self.assertIn("live_ok", res["research"])

                print(
                    f"[quality] {case['label']:9} "
                    f"generated={res['candidates_generated']:2} "
                    f"eligible={res['candidates_eligible']:2} "
                    f"recommended={res['recommended']!r} "
                    f"clarity={winner['components']['product_clarity']} "
                    f"originality={winner['components']['originality']} "
                    f"rejected={len(res['rejected'])} "
                    f"evidence={'db+live' if res['research']['live_ok'] else 'partial'}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
