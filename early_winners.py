"""
early_winners.py — Detect items that are winning BEFORE the market notices.

Criteria:
  - Age <= 14 days
  - favs/day >= min_rate
  - keyword supply <= max_supply (niche not yet saturated)
  - item passes a basic name sanity filter

This is the actual alpha. Everything else is context.
"""
import re
from collections import defaultdict


STOPWORDS = {
    "a","an","the","of","and","or","for","to","in","on","with","my","your",
    "at","by","is","it","as","this","that","from","into","over","under",
    "roblox","item","ugc",
}

# Names containing these are platform/brand content, not solo UGC
NOISE_TOKENS = {
    "background", "addon", "bundle", "package", "official", "sponsor",
    "limited", "exclusive", "premium", "season", "event", "collab",
}

# These creators are platform accounts, not competitors
PLATFORM_CREATORS = {
    "Roblox", "Sony Immersive Music Studios", "Ice Spice Munchland",
    "Netflix", "Gucci", "Nike", "Twitch",
}


def _is_noise(name):
    n = (name or "").lower()
    return any(tok in n for tok in NOISE_TOKENS)


def _first_keyword(name):
    """First meaningful token in the title."""
    for t in re.findall(r"[a-z]{4,}", (name or "").lower()):
        if t not in STOPWORDS:
            return t
    return None


def find_early_winners(cur, days=14, min_rate=20.0, max_supply=50,
                       min_favs=40, limit=20):
    """
    Find items in their breakout phase. Pure SQL + Python. Fast.
    Returns list of dicts sorted by favs/day desc.
    """
    try:
        cur.execute("""
            SELECT id, name, creator_name, favorite_count, price,
                   EXTRACT(EPOCH FROM (NOW() - created_at))/86400 AS age_days,
                   asset_type_id
            FROM items
            WHERE created_at IS NOT NULL
              AND created_at >= NOW() - INTERVAL '%s days'
              AND favorite_count >= %s
            ORDER BY favorite_count DESC
            LIMIT 2000
        """, (int(days), int(min_favs)))
        rows = cur.fetchall()
    except Exception as e:
        print(f"[early] fetch failed: {e}", flush=True)
        return []

    if not rows:
        return []

    # Pre-fetch item names once for supply checks (batched)
    try:
        cur.execute("""
            SELECT LOWER(name) FROM items
            WHERE favorite_count > 5
            LIMIT 60000
        """)
        all_names = [r[0] for r in cur.fetchall() if r[0]]
    except Exception:
        all_names = []

    winners = []
    for item_id, name, creator, favs, price, age, atype in rows:
        if not name or _is_noise(name):
            continue
        if creator in PLATFORM_CREATORS:
            continue

        try:
            age_f = float(age or 0)
            if age_f < 0.5:  # too new to trust the rate
                continue
            rate = (favs or 0) / age_f
        except Exception:
            continue

        if rate < min_rate:
            continue

        keyword = _first_keyword(name)
        if not keyword:
            continue

        supply = sum(1 for n in all_names if keyword in n)
        if supply > max_supply:
            continue

        winners.append({
            "id": item_id,
            "name": (name or "")[:60],
            "creator": (creator or "")[:30],
            "favs": int(favs or 0),
            "age_days": round(age_f, 1),
            "favs_per_day": round(rate, 1),
            "keyword": keyword,
            "keyword_supply": supply,
            "price": int(price or 0),
            "asset_type_id": atype,
        })

    winners.sort(key=lambda w: -w["favs_per_day"])
    return winners[:limit]


def format_early_winners(results, days=14):
    if not results:
        return (
            f"# ⚡ EARLY WINNERS — last {days}d\n\n"
            "No items matched the criteria (rate ≥ 20/day, supply ≤ 50).\n"
            "Either the market is quiet or your thresholds need tuning."
        )

    lines = [f"# ⚡ EARLY WINNERS — last {days} days\n"]
    lines.append(
        "_Items gaining ≥20 favs/day with almost no competition yet. "
        "These are the ones to study or race._\n"
    )

    for i, w in enumerate(results, 1):
        lines.append(
            f"**{i}. `{w['name']}`** — **{w['favs_per_day']}/day**\n"
            f"   {w['favs']:,} favs · {w['age_days']}d old · "
            f"R${w['price']} · by `{w['creator']}`\n"
            f"   → keyword `{w['keyword']}` — supply **{w['keyword_supply']}** items"
        )
    lines.append("")
    lines.append("---")
    lines.append(
        "**What to do:** Pick one. Look at its title pattern. "
        "Launch a variant with a different keyword angle in 48h. "
        "That's your window."
    )
    return "\n".join(lines)
