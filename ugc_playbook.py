"""ugc_playbook.py — encoded UGC creator playbook.

This is not new analytics. It is the proven, publicly known set of tactics
that top Roblox UGC creators use, expressed as rules the bot can apply to
its existing outputs.
"""

TOPICS = {
    "niche": [
        "Enter niches with rising demand and low supply growth — not after saturation.",
        "Check median favorites and supply growth before committing.",
        "Prefer a niche you can describe in 2–3 words (e.g. 'coquette bow').",
        "Validate demand with autocomplete suggestions, not vibes.",
        "If the top 10 items are all 100k+ favorites, the lane is closed.",
        "Look for 'boring' niches with steady sales, not just viral spikes.",
        "Best window: 1–2 weeks before a niche saturates.",
        "Avoid niches where the top item owns >60% of favorites.",
    ],
    "naming": [
        "Front-load the highest-volume keyword — search reads left to right.",
        "3–5 words is ideal; stay under ~50 characters.",
        "Include the item type (emote, beanie, wings, aura).",
        "Use one aesthetic modifier (kawaii, y2k, gothic), not five.",
        "Never stuff: 'cute kawaii aesthetic pastel pink beanie' is spam.",
        "Avoid generic words: item, ugc, roblox, cheap, best.",
        "Never say 'limited' or 'free' unless it is literally true.",
        "Use at most one emoji, and only if it fits the brand.",
        "Match the exact phrase people search, not a clever pun.",
        "Keep a consistent naming pattern across your catalog.",
    ],
    "pricing": [
        "Emotes have a floor price; do not race to the bottom.",
        "Accessories can carry premium prices when demand is proven.",
        "Test ±20% — small changes reveal elasticity.",
        "Low prices do not guarantee volume; they guarantee low margin.",
        "Price by perceived value and niche, not by competitor average.",
        "R$2 clothing teaches buyers your catalog is cheap — avoid it.",
        "Premium items need premium presentation (thumbnail, description).",
        "Never discount by editing the price after launch; re-upload instead.",
    ],
    "tags": [
        "Use all 5 tag slots.",
        "Mix one broad tag, two long-tail tags, and two aesthetic tags.",
        "Mine tags from top sellers with `!tags`.",
        "Cover synonyms buyers actually type.",
        "Do not use irrelevant tags — it dilutes relevance.",
        "Update tags when a trend changes.",
        "Tags support search; the title still does the heavy lifting.",
    ],
    "thumbnail": [
        "High contrast, readable at 100px wide.",
        "Show the item clearly — no clutter, no tiny details.",
        "Use 2–3 dominant colors that match the item.",
        "Add 2–4 words of text maximum.",
        "Consistent style across your catalog builds brand recognition.",
        "Test two thumbnails on similar items and compare CTR proxies (favorites/day).",
        "Avoid dark-on-dark and low-contrast renders.",
    ],
    "launch": [
        "Upload during your audience's peak hours.",
        "Group shout immediately after publishing.",
        "Post a Discord announcement with the link.",
        "Post one TikTok/Short the same day.",
        "Ask your group to favorite in the first 48 hours.",
        "Monitor favorites at T+6h and T+24h against peers.",
        "If velocity is below peers, retitle or shout again — do not wait.",
        "Do not launch into a saturated niche and expect the algorithm to save you.",
    ],
    "catalog": [
        "A scattered catalog dilutes your algorithmic signal.",
        "Pick one aesthetic and dominate it.",
        "20–50 items is the minimum for compounding discovery.",
        "Clone winners into 3–5 variants before trying unrelated concepts.",
        "Kill or refresh items with no sales after 30 days.",
        "Keep a consistent price band per family.",
        "Every new item should reinforce the same brand keywords.",
    ],
    "variants": [
        "Preserve the winning keywords in every variant.",
        "Change one variable at a time (color, theme, effect).",
        "Avoid variants that cannibalize the original (>50% overlap).",
        "Stagger variant launches by 7–14 days.",
        "Use the original's best-performing tag set as the base.",
        "Retire variants that do not beat the original after 30 days.",
    ],
    "cross_promo": [
        "Put your winner's name in the description of dead items.",
        "Group shout: 'Love X? Get the matching Y.'",
        "Cross-link only related items — not random catalog spam.",
        "Track whether paired items' favorites/day rise.",
        "Use Discord announcements and pins.",
        "A warm buyer is cheaper than a cold impression.",
    ],
    "external": [
        "Roblox cold start is brutal — external traffic is the fastest trigger.",
        "Post 15-second clips showing the item in action.",
        "Use trending sounds; the audio does half the work.",
        "Post 3–5 times per week, not once per launch.",
        "Hook in the first second: show the item, not a logo.",
        "Put the item name on screen so viewers can search it.",
        "Send traffic to the group and Discord, not just the item.",
    ],
    "measurement": [
        "Log every launch — no cherry-picking.",
        "Measure D1/D7/D30 favorites and D7/D30 revenue.",
        "Compare against peers created around the same time.",
        "Do not trust a hit rate under 20 launches.",
        "Change one variable per test.",
        "Keep what wins; revert what loses.",
        "Revenue is only as complete as your sales capture.",
    ],
    "failure_modes": [
        "Keyword stuffing — spammy titles get filtered.",
        "Misleading tags or false 'limited' claims — moderation risk.",
        "Launching into a saturated niche.",
        "Overpricing without proven demand.",
        "Inconsistent aesthetic across the catalog.",
        "No external traffic — relying on the algorithm alone.",
        "Too few items — no compounding discovery.",
        "Ignoring early velocity and waiting too long to adjust.",
        "Copying a saturated item instead of improving it.",
        "Trusting small samples and random variation.",
    ],
    "economics": [
        "Roblox keeps roughly 70% of UGC sales; creators keep roughly 30%.",
        "DevEx: 100,000 Robux ≈ $350; minimum cash-out is 30,000 Robux.",
        "$100/month ≈ 28,571 Robux net.",
        "$1,000/month ≈ 285,714 Robux net.",
        "$10,000/month ≈ 2,857,143 Robux net.",
        "At R$20 net/unit, $1,000/month needs ~14,300 units/month (~475/day).",
        "At R$50 net/unit, $1,000/month needs ~5,700 units/month (~190/day).",
        "Volume and price are the only two revenue levers; both need traffic.",
        "No bot can guarantee virality or income. These are platform mechanics, not promises.",
    ],
    "path": [
        "Stage 0 (under R$5k/mo): fix data, 10–20 items, clone the top 2, one clip per launch.",
        "Stage 1 (R$5k–50k/mo): 20–50 items, two niches, retire dead stock, A/B titles.",
        "Stage 2 (R$50k–300k/mo): 50–100 items, systemized production, brand aesthetic.",
        "Stage 3 (R$300k–1M/mo): studio operations, multiple groups, paid promotion.",
        "Stage 4 (R$1M+/mo): team, licensing, collaborations, platform diversification.",
        "Move one stage at a time; do not skip the catalog scale step.",
    ],
}

TOPIC_ALIASES = {
    "names": "naming",
    "name": "naming",
    "title": "naming",
    "titles": "naming",
    "price": "pricing",
    "tag": "tags",
    "tags": "tags",
    "thumb": "thumbnail",
    "thumbnails": "thumbnail",
    "launching": "launch",
    "variants": "variants",
    "variant": "variants",
    "crosspromo": "cross_promo",
    "cross-sell": "cross_promo",
    "tiktok": "external",
    "marketing": "external",
    "measure": "measurement",
    "metrics": "measurement",
    "failures": "failure_modes",
    "mistakes": "failure_modes",
    "catalog": "catalog",
    "niches": "niche",
}


def resolve_topic(topic):
    key = (topic or "").strip().lower().replace(" ", "_")
    key = TOPIC_ALIASES.get(key, key)
    if key in TOPICS:
        return key
    return None


def format_topic(topic):
    key = resolve_topic(topic)
    if not key:
        return None
    lines = [f"# 📘 {key.replace('_', ' ').title()}"]
    for tip in TOPICS[key]:
        lines.append(f"• {tip}")
    return "\n".join(lines)


def topic_list():
    return sorted(TOPICS.keys())


def audit_title(title, max_len=50):
    """Return a short list of concrete issues with a proposed title."""
    issues = []
    t = (title or "").strip()
    low = t.lower()

    if not t:
        return ["Title is empty."]

    if len(t) > max_len:
        issues.append(f"too long ({len(t)} chars) — trim to <{max_len}")

    words = [w for w in low.replace("-", " ").split() if w]
    if len(words) < 3:
        issues.append("too short — add a descriptor or item type")
    if len(words) > 6:
        issues.append("too many words — keyword stuffing risk")

    generic = {"item", "ugc", "roblox", "cheap", "best", "good", "new"}
    found = sorted(set(words) & generic)
    if found:
        issues.append(f"generic words: {', '.join(found)}")

    if "limited" in words or "free" in words:
        issues.append("'limited'/'free' only if literally true")

    emojis = sum(1 for ch in t if ord(ch) > 0x2000)
    if emojis > 1:
        issues.append("more than one emoji")

    if low.count("  "):
        issues.append("double spaces")

    return issues


def audit_price(price):
    """Return a pricing note, or None if the price looks reasonable."""
    try:
        p = int(price)
    except (TypeError, ValueError):
        return None
    if p <= 2:
        return "very low price — signals a cheap catalog and kills margin"
    if p < 15:
        return "below the typical floor — consider 15+ if demand allows"
    if p > 500:
        return "premium price — make sure the thumbnail/value justifies it"
    return None


def next_actions(stats):
    """Turn a few stats into ranked next actions from the playbook."""
    actions = []
    total = stats.get("launches", 0)
    measured = stats.get("measured", 0)
    hits = stats.get("hits", 0)
    revenue = stats.get("revenue", 0)
    backlog = stats.get("backlog", 0)

    if measured < 5:
        actions.append("Log 5+ launches before trusting the hit rate.")
    if total and measured and hits / max(measured, 1) < 0.3:
        actions.append("Hit rate <30% — refresh dead items before launching more.")
    if revenue == 0 and total:
        actions.append("No revenue captured — check the sales channel/backfill.")
    if backlog > 50000:
        actions.append("Enrichment backlog is high — rankings are still noisy.")
    actions.append("Clone your top 2 items into 3–5 variants before new concepts.")
    actions.append("Post one external clip per launch; do not rely on search alone.")
    return actions[:4]
