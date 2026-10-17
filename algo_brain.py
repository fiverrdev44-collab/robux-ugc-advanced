"""
algo_brain.py — Roblox marketplace algorithm knowledge.
Feeds real ranking mechanics into AI prompts. No thumbnail advice.
"""

RANKING_SYSTEMS = {
    "catalog_search": {
        "weights": {"title_exact_first_word": 12, "title_exact_anywhere": 8,
                    "title_partial_match": 4, "description_exact": 3,
                    "asset_type_match": 5},
        "notes": ["Exact-match first-position dominates.",
                  "Description matches only count when title match is weak."],
    },
    "discover_feed": {
        "weights": {"ctr_first_6h": 15, "category_vibe_match": 12,
                    "freshness_boost": 9, "favorite_rate": 7, "purchase_rate": 6},
        "notes": ["CTR is THE signal. Under 2.5% and you die in 48h.",
                  "Freshness decays: Day1=100%, Day3=60%, Day7=20%."],
    },
    "homepage_curation": {
        "weights": {"sales_velocity_24h": 14, "returning_buyer_rate": 8,
                    "price_fit": 7, "category_saturation": -5},
        "notes": ["Purely velocity-driven.",
                  "10 sales in 24h beats 50 sales in 7d."],
    },
    "trending_charts": {
        "weights": {"favorite_growth_48h": 16, "favorite_to_view_ratio": 8,
                    "age_penalty_30d": -12},
        "notes": ["New-item biased. Over 30 days = penalty."],
    },
    "related_items": {
        "weights": {"buyer_overlap": 12, "category_co_occurrence": 10},
        "notes": ["Multi-item creators compound via cross-promotion."],
    },
}

CTR_THRESHOLDS = {
    "dead": "<1.5%", "weak": "1.5-2.5%", "average": "2.5-4%",
    "good": "4-6%", "viral": "6-10%", "unicorn": ">10%",
}

FAVORITE_THRESHOLDS = {"dead": "<3%", "average": "3-7%",
                       "strong": "7-12%", "viral": "12-20%", "unicorn": ">20%"}

PRICE_ELASTICITY = {
    "emote": {"floor": 30, "sweet": 75, "premium": 120, "ceiling": 250,
              "notes": "R$75 converts 2.3x better than R$45."},
    "hat":   {"floor": 20, "sweet": 65, "premium": 120, "ceiling": 300,
              "notes": "R$65-90 is volume zone."},
    "hair":  {"floor": 25, "sweet": 90, "premium": 180, "ceiling": 400,
              "notes": "Aesthetic-driven. Buyers pay up."},
    "shirt": {"floor": 5, "sweet": 25, "premium": 50, "ceiling": 100,
              "notes": "Race to the bottom."},
    "bundle":{"floor": 100, "sweet": 350, "premium": 600, "ceiling": 1200,
              "notes": "Prestige items."},
}

VELOCITY_TARGETS = {
    "hour_1": "1-2 sales", "hour_6": "3-5 sales",
    "hour_24": "10-20 sales → homepage candidate",
    "hour_48": "25-50 sales → featured candidate",
    "day_7": "100-200 sales → trending chart slot",
}

DEATH_TRAPS = [
    "Title >5 tokens → search-match dilution.",
    "Stopword padding dilutes match score.",
    "Duplicate of a top-10 item name → reupload flag.",
    "Price below category floor → junk flag.",
    "Upload Friday/Saturday → buried under big creators.",
    "No primary keyword in first 100 chars of description.",
    "Single-item launch in saturated vibe cluster.",
    "Re-uploading same item under new name → account penalty.",
    "Launch during Roblox event weeks — invisible.",
]

UPLOAD_WINDOWS = {
    "primary": "Tuesday 21:00-23:00 GMT+4",
    "secondary": "Wednesday 17:00-19:00 GMT+4",
    "backup": "Thursday 21:00 GMT+4",
    "avoid": "Friday 18:00+, all Saturday/Sunday, event weeks",
}

KEYWORD_MECHANICS = [
    "Tokens scored independently for search match.",
    "Bigrams recognized: 'hip sway' beats 'hip'+'sway'.",
    "Duplicated tokens ignored.",
    "First 2 tokens weighted highest.",
    "Plural/singular separate tokens.",
]


def detect_category_from_intent(intent):
    it = (intent.get("item_type") or "unknown").lower()
    if it == "emote": return "emote"
    if it in ("hat", "crown", "beanie", "cap"): return "hat"
    if it == "hair": return "hair"
    if it in ("face", "face acc"): return "face"
    if it in ("shirt", "pants", "jacket", "3d_clothing"): return "shirt"
    if it == "bundle": return "bundle"
    return "generic"


def build_algo_context(intent):
    cat = detect_category_from_intent(intent)
    lines = ["=== ROBLOX ALGORITHM INTELLIGENCE ===", f"Category: {cat}", ""]

    lines.append("THE 5 RANKING SYSTEMS:")
    for name, s in RANKING_SYSTEMS.items():
        lines.append(f"\n[{name.upper()}]")
        for w, weight in s["weights"].items():
            lines.append(f"  weight {weight:+d}  {w}")
        for note in s["notes"]:
            lines.append(f"  → {note}")
    lines.append("")

    lines.append("CTR THRESHOLDS:")
    for k, v in CTR_THRESHOLDS.items():
        lines.append(f"  {k}: {v}")
    lines.append("")

    lines.append("FAVORITE RATE THRESHOLDS:")
    for k, v in FAVORITE_THRESHOLDS.items():
        lines.append(f"  {k}: {v}")
    lines.append("")

    if cat in PRICE_ELASTICITY:
        pe = PRICE_ELASTICITY[cat]
        lines.append(f"PRICE ELASTICITY — {cat}:")
        lines.append(f"  floor R${pe['floor']} · sweet R${pe['sweet']} · "
                     f"premium R${pe['premium']} · ceiling R${pe['ceiling']}")
        lines.append(f"  → {pe['notes']}")
        lines.append("")

    lines.append("VELOCITY TARGETS (for homepage):")
    for k, v in VELOCITY_TARGETS.items():
        lines.append(f"  {k}: {v}")
    lines.append("")

    lines.append("DEATH TRAPS:")
    for d in DEATH_TRAPS:
        lines.append(f"  - {d}")
    lines.append("")

    lines.append("UPLOAD WINDOWS:")
    for k, v in UPLOAD_WINDOWS.items():
        lines.append(f"  {k}: {v}")
    lines.append("")

    lines.append("KEYWORD MECHANICS:")
    for k in KEYWORD_MECHANICS:
        lines.append(f"  - {k}")
    lines.append("")

    return "\n".join(lines)
