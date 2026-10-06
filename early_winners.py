"""
early_winners.py — Detect items that are winning BEFORE the market notices.

FIXED:
- Uses RAREST token in the title, not the first one.
- Lower thresholds (min_rate 15, min_favs 20) so real signals don't get filtered.
- Relaxed fallback: if strict pass returns nothing, uses a wider pass.
- Noise filter applied.
"""
import re
from collections import defaultdict


STOPWORDS = {
    "a","an","the","of","and","or","for","to","in","on","with","my","your",
    "at","by","is","it","as","this","that","from","into","over","under",
    "roblox","item","ugc",
}

NOISE_TOKENS = {
    "background", "addon", "bundle", "package", "official", "sponsor",
    "limited", "exclusive", "premium", "season", "event", "collab",
    "shirt", "pants", "tshirt", "t-shirt",
}

PLATFORM_CREATORS = {
    "Roblox", "Sony Immersive Music Studios", "Ice Spice Munchland",
    "Netflix", "Gucci", "Nike", "Twitch", "Disney", "Warner",
    "Universal", "Sony", "Microsoft", "Xbox",
}


def _is_noise(name):
    n = (name or "").lower()
    if any(tok in n for tok in NOISE_TOKENS):
        return True
    if n.startswith("[") and n.count("[") >= 2:  # [tag] ... [tag] format
        return True
    return False


def _tokens(name):
    return [t for t in re.findall(r"[a-z]{4,}", (name or "").lower())
            if t not in STOPWORDS]


def find_early_winners(cur, days=14, min_rate=15.0, max_supply=50,
                       min_favs=20, limit=15):
    """
    Find items in their breakout phase.
    Uses RAREST token in the title as the keyword signal.
    Falls back to wider thresholds if strict pass is empty.
    """
    rows = _fetch_candidates(cur, days=days, min_favs=min_favs)
    if not rows:
        return []

    all_names = _fetch_all_names(cur)
    # Precompute token -> supply once (avoids O(n*m) loops)
    token_supply = _build_token_supply(all_names)

    # Strict pass
    results = _apply_filters(rows, token_supply,
                             min_rate=min_rate,
                             max_supply=max_supply,
                             exclude_platform=True,
                             exclude_noise=True)

    # Fallback: relax thresholds if strict pass empty
    if not results:
        results = _apply_filters(rows, token_supply,
                                 min_rate=max(5.0, min_rate * 0.5),
                                 max_supply=max_supply * 2,
                                 exclude_platform=True,
                                 exclude_noise=True)

    # Final fallback: no platform filter
    if not results:
        results = _apply_filters(rows, token_supply,
                                 min_rate=5.0,
                                 max_supply=200,
                                 exclude_platform=False,
                                 exclude_noise=True)

    results.sort(key=lambda w: -w["favs_per_day"])
    return results[:limit]


def _fetch_candidates(cur, days=14, min_favs=20, limit=2000):
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
            LIMIT %s
        """, (int(days), int(min_favs), int(limit)))
        return cur.fetchall()
    except Exception as e:
        print(f"[early] fetch failed: {e}", flush=True)
        return []


def _fetch_all_names(cur):
    try:
        cur.execute("""
            SELECT LOWER(name) FROM items
            WHERE favorite_count > 5
            LIMIT 60000
        """)
        return [r[0] for r in cur.fetchall() if r[0]]
    except Exception:
        return []


def _build_token_supply(all_names):
    """Count how many item names contain each token."""
    supply = defaultdict(int)
    for n in all_names:
        seen = set()
        for t in re.findall(r"[a-z]{4,}", n):
            if t in seen:
                continue
            seen.add(t)
            supply[t] += 1
    return supply


def _apply_filters(rows, token_supply, min_rate, max_supply,
                   exclude_platform, exclude_noise):
    out = []
    for item_id, name, creator, favs, price, age, atype in rows:
        if not name:
            continue
        if exclude_noise and _is_noise(name):
            continue
        if exclude_platform and creator in PLATFORM_CREATORS:
            continue

        try:
            age_f = float(age or 0)
            if age_f < 0.5:
                continue
            rate = (favs or 0) / age_f
        except Exception:
            continue

        if rate < min_rate:
            continue

        toks = _tokens(name)
        if not toks:
            continue

        # RAREST token is the keyword signal — most unique word in the title
        rarest = min(toks, key=lambda t: token_supply.get(t, 999999))
        supply = token_supply.get(rarest, 0)
        if supply > max_supply:
            continue

        out.append({
            "id": item_id,
            "name": (name or "")[:60],
            "creator": (creator or "")[:30],
            "favs": int(favs or 0),
            "age_days": round(age_f, 1),
            "favs_per_day": round(rate, 1),
            "keyword": rarest,
            "keyword_supply": supply,
            "price": int(price or 0),
            "asset_type_id": atype,
        })
    return out


def format_early_winners(results, days=14):
    if not results:
        return (
            f"# ⚡ EARLY WINNERS — last {days}d\n\n"
            "No items matched. Either the market is quiet, or your DB has too "
            "few items with a `created_at` in the last 14 days. Try `!early 30` "
            "or run the backfill."
        )

    lines = [f"# ⚡ EARLY WINNERS — last {days} days\n"]
    lines.append(
        "_Items gaining ≥15 favs/day with a low-competition keyword. "
        "This is the actual alpha._\n"
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
        "Launch a variant with a different keyword angle in 48h."
    )
    return "\n".join(lines)
