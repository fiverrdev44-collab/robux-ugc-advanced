"""Held-out human-rated benchmark for emote title creative quality.

Human rubric (assigned before running the engine, independently of its
formula):
  2 = Strong: clearly identifies the movement/style, reads like a natural
      product name, and adds a distinct angle.
  1 = Mediocre: valid and grounded, but vague, awkward, or weakly angled.
  0 = Weak: generic filler, no recognizable identity, or unsafe branding.

The test compares the engine's ranking against these human tiers pairwise.
Disagreements are reported with the component scores that caused them. The
benchmark is separate from the 10-case development set and from the real
Discord example, so it is held out from tuning.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import emote_title_engine as ete

NEUTRAL_DB = {"ok": True, "top_examples": [], "live_shortlist": [],
              "matches": 0}
NEUTRAL_LIVE = []

CASES = [
    {
        "label": "anime power-up",
        "desc": "A dramatic anime power-up pose with clenched fists and a "
                "glowing aura.",
        "candidates": [
            ("Anime Power Up Pose", 2),
            ("Glowing Fist Pose", 2),
            ("Dramatic Power Up Emote", 2),
            ("Powerful Anime Style", 1),
            ("Mysterious Energetic Emote", 0),
            ("Epic Emote", 0),
        ],
    },
    {
        "label": "robot",
        "desc": "A stiff robotic dance with mechanical arm movements.",
        "candidates": [
            ("Robotic Dance Emote", 2),
            ("Mechanical Arm Dance", 2),
            ("Stiff Robot Dance", 2),
            ("Robot Style Emote", 1),
            ("Cool Emote", 0),
            ("Vanta Robo Performance", 0),
        ],
    },
    {
        "label": "sports celebration",
        "desc": "A basketball free-throw celebration with a confident fist "
                "pump.",
        "candidates": [
            ("Free Throw Celebration", 2),
            ("Confident Fist Pump", 2),
            ("Basketball Celebration Emote", 2),
            ("Sports Style Emote", 1),
            ("Winning Emote", 1),
            ("Powerful Emote", 0),
        ],
    },
    {
        "label": "winter idle",
        "desc": "A cozy winter idle where the character shivers and hugs "
                "themselves.",
        "candidates": [
            ("Cozy Winter Idle", 2),
            ("Shivering Hug Idle", 2),
            ("Winter Shiver Emote", 2),
            ("Stay Warm Emote", 1),
            ("Cozy Emote", 1),
            ("Seasonal Style Emote", 0),
        ],
    },
    {
        "label": "magic spin",
        "desc": "A magical staff spin followed by a heroic pose.",
        "candidates": [
            ("Magical Staff Spin", 2),
            ("Heroic Staff Pose", 2),
            ("Wizard Spin Emote", 2),
            ("Magic Style Emote", 1),
            ("Cool Emote", 0),
            ("Mysterious Emote", 0),
        ],
    },
    {
        "label": "shy reaction",
        "desc": "A shy reaction where the character looks away and fidgets.",
        "candidates": [
            ("Shy Fidget Reaction", 2),
            ("Nervous Fidget Emote", 2),
            ("Looking Away Emote", 1),
            ("Reaction Emote", 1),
            ("Shy Style Emote", 1),
            ("Cool Emote", 0),
        ],
    },
    {
        "label": "cat stretch",
        "desc": "A playful cat-like stretch pose with a slow tail flick.",
        "candidates": [
            ("Playful Cat Stretch", 2),
            ("Cat Tail Flick Pose", 2),
            ("Stretching Cat Emote", 2),
            ("Animal Style Emote", 1),
            ("Cute Emote", 0),
            ("Mysterious Emote", 0),
        ],
    },
    {
        "label": "breakdance freeze",
        "desc": "A fast breakdance routine with a freeze at the end.",
        "candidates": [
            ("Breakdance Freeze Emote", 2),
            ("Fast Breakdance Routine", 2),
            ("Freeze Dance Emote", 2),
            ("Battle Style Emote", 1),
            ("Powerful Emote", 0),
            ("Mysterious Emote", 0),
        ],
    },
]


class HeldOutQualityTests(unittest.TestCase):
    def test_engine_agrees_with_human_tiers(self):
        total_pairs = 0
        agreements = 0
        disagreements = []
        weak_winners = []

        for case in CASES:
            desc = case["desc"]
            protected = ete.extract_protected_names(desc)
            concepts = ete.extract_concepts(desc, exclude=protected)
            identity = ete.extract_product_identity(desc, concepts)

            valid, rejected = [], []
            for title, tier in case["candidates"]:
                clean, why = ete._validate_candidate(desc, title, protected)
                if not clean:
                    rejected.append((title, tier, why))
                    continue
                valid.append((clean, tier))

            ranked = ete.rank_titles(
                [{"title": t, "strategy": "human"} for t, _ in valid],
                desc, concepts, NEUTRAL_DB, NEUTRAL_LIVE,
                title_checks=[], identity=identity)
            order = {t["title"]: i for i, t in enumerate(ranked)}
            tier_of = {t: tier for t, tier in valid}

            for i in range(len(valid)):
                for j in range(i + 1, len(valid)):
                    a, b = valid[i][0], valid[j][0]
                    if tier_of[a] == tier_of[b]:
                        continue
                    total_pairs += 1
                    higher, lower = ((a, b) if tier_of[a] > tier_of[b]
                                     else (b, a))
                    if order[higher] < order[lower]:
                        agreements += 1
                    else:
                        ca = next(t for t in ranked if t["title"] == a)["components"]
                        cb = next(t for t in ranked if t["title"] == b)["components"]
                        disagreements.append({
                            "case": case["label"], "human_higher": higher,
                            "engine_higher": lower,
                            "higher_components": ca,
                            "lower_components": cb,
                        })

            top = ranked[0]["title"] if ranked else None
            if top and tier_of.get(top) == 0:
                weak_winners.append((case["label"], top))
            print(
                f"[heldout] {case['label']:18} top={top!r} "
                f"tier={tier_of.get(top)} valid={len(valid)} "
                f"rejected={[r[0] for r in rejected]}")

        rate = (agreements / total_pairs) if total_pairs else 1.0
        print(f"[heldout] pairwise agreement {agreements}/{total_pairs} "
              f"= {rate:.1%}")
        for d in disagreements:
            print(
                f"[heldout][disagreement] {d['case']}: human prefers "
                f"{d['human_higher']!r} over {d['engine_higher']!r}; "
                f"clarity {d['higher_components']['product_clarity']} vs "
                f"{d['lower_components']['product_clarity']}, originality "
                f"{d['higher_components']['originality']} vs "
                f"{d['lower_components']['originality']}, "
                f"memorability {d['higher_components']['memorability']} vs "
                f"{d['lower_components']['memorability']}, naturalness "
                f"{d['higher_components']['natural_readability']} vs "
                f"{d['lower_components']['natural_readability']}, relevance "
                f"{d['higher_components']['relevance']} vs "
                f"{d['lower_components']['relevance']}")

        self.assertGreaterEqual(rate, 0.80)
        self.assertEqual(weak_winners, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
