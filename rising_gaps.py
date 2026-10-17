"""
rising_gaps.py — Find keywords that are RISING but still low-competition.
Supports category filtering + auto-detection from seed keyword.
"""
import math
import re
from collections import defaultdict, Counter
from datetime import timedelta

TOKEN_RE = re.compile(r"[a-z]{4,}")
STOP = {
    "the","a","an","of","and","or","for","to","in","on","with","my","your",
    "is","it","as","at","by","from","new","old","roblox","ugc","free","item",
    "this","that","very","cool","nice","cute","best","top","big","small",
}

CATEGORY_MAP = {
    "emote": [61],
    "hat": [8],
    "hair": [41],
    "face": [18, 42],
    "accessory": [8, 41, 42, 43, 44, 45, 46, 47],
    "shirt": [11, 64, 65],
    "pants": [12, 66],
    "jacket": [67],
    "gear": [19],
}

CATEGORY_HINTS = {
    "emote": [
        "dance", "emote", "sway", "groove", "bounce", "floss", "griddy",
        "wave", "moonwalk", "shuffle", "spin", "twirl", "kick", "pose",
        "salute", "clap", "cheer", "victory", "idle", "sit", "crouch",
        "laugh", "cry", "smile", "silly", "rage", "twerk", "shmoney",
        "dougie", "stanky", "gangnam", "salsa", "ballet", "krump",
        "hip", "hop", "hiphop", "freestyle", "flow", "smooth", "vibe",
        "gesture", "expression", "reaction", "animation", "loop",
    ],
    "hat": [
        "hat", "beanie", "crown", "cap", "beret", "bonnet", "balaclava",
        "visor", "helmet", "headband", "snapback", "fedora", "tophat",
    ],
    "hair": [
        "hair", "bangs", "ponytail", "curls", "wig", "bob", "braids",
        "afro", "mullet", "fringe", "hairstyle", "locks",
    ],
    "face": [
        "face", "glasses", "mask", "monocle", "eyepatch",
        "sunglasses", "goggles", "eyebrows", "eyes", "mouth",
    ],
    "accessory": [
        "necklace", "chain", "wings", "cape", "backpack", "bag",
        "sword", "pet", "tail", "ears", "horn", "horns", "scarf",
        "bandana", "shoulder", "waist", "neck", "lanyard",
    ],
    "shirt": ["shirt", "tshirt", "t-shirt", "hoodie", "sweater", "jersey"],
    "pants": ["pants", "jeans", "shorts", "cargo"],
    "jacket": ["jacket", "coat", "blazer"],
}


def _tokens(text):
    return [t for t in TOKEN_RE.findall((text or "").lower()) if t not in STOP]


def detect_category_from_keyword(seed):
    """Guess the category based on words in the seed phrase."""
    if not seed:
        return None
    seed_lower = seed.lower()
    tokens = set(re.findall(r"[a-z]+", seed_lower))

    scores = {}
    for cat, hints in CATEGORY_HINTS.items():
        score = 0
        for hint in hints:
            if hint in tokens:
                score += 3
            elif hint in seed_lower:
                score += 1
        if score > 0:
            scores[cat] = score

    if not scores:
        return None
    return max(scores, key=scores.get)


def find_rising_gaps(cur, days=14, category=None,
                     max_competition=150, min_momentum=1.5, top_n=20):
    """Find keywords with rising velocity + low competition."""
    cat_filter = ""
    cat_params = []
    if category and category.lower() in CATEGORY_MAP:
        asset_ids = CATEGORY_MAP[category.lower()]
        cat_filter = " AND i.asset_type_id = ANY(%s)"
        cat_params.append(asset_ids)

    cur.execute(f"""
        SELECT i.id, LOWER(i.name), h.favorite_count, h.snapshot_at
        FROM item_history h
        JOIN items i ON i.id = h.item_id
        WHERE h.snapshot_at > NOW() - INTERVAL '{days * 2} days'
          AND h.favorite_count > 0
          {cat_filter}
        ORDER BY h.item_id, h.snapshot_at
    """, tuple(cat_params))
    rows = cur.fetchall()
    if not rows:
        return {"error": "no_history", "category": category}

    item_series = defaultdict(list)
    for iid, name, favs, snap in rows:
        item_series[iid].append((snap, favs, name))

    now = max(r[3] for r in rows)
    cutoff = now - timedelta(days=days)

    keyword_momentum = defaultdict(lambda: {"v_now": 0.0, "v_prev": 0.0, "items": set()})

    for iid, series in item_series.items():
        series.sort()
        if len(series) < 2:
            continue
        name = series[0][2]
        words = set(_tokens(name))

        recent = [s for s in series if s[0] >= cutoff]
        older = [s for s in series if s[0] < cutoff]

        vn = 0.0
        if len(recent) >= 2:
            growth = recent[-1][1] - recent[0][1]
            ddays = max(1, (recent[-1][0] - recent[0][0]).days)
            vn = growth / ddays

        vp = 0.0
        if len(older) >= 2:
            growth = older[-1][1] - older[0][1]
            ddays = max(1, (older[-1][0] - older[0][0]).days)
            vp = growth / ddays

        for w in words:
            if vn > 0:
                keyword_momentum[w]["v_now"] += vn
                keyword_momentum[w]["items"].add(iid)
            if vp > 0:
                keyword_momentum[w]["v_prev"] += vp

    candidates = []
    for word, mdata in keyword_momentum.items():
        item_count = len(mdata["items"])
        if item_count < 2:
            continue

        vn = mdata["v_now"]
        vp = mdata["v_prev"]
        if vn <= 0:
            continue

        momentum_ratio = vn / vp if vp > 0 else 999.0
        if momentum_ratio < min_momentum:
            continue

        if category and category.lower() in CATEGORY_MAP:
            asset_ids = CATEGORY_MAP[category.lower()]
            cur.execute("""
                SELECT COUNT(*), COALESCE(AVG(favorite_count), 0),
                       COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP
                                (ORDER BY favorite_count), 0)
                FROM items
                WHERE LOWER(name) LIKE %s
                  AND favorite_count > 5
                  AND asset_type_id = ANY(%s)
            """, (f"%{word}%", asset_ids))
        else:
            cur.execute("""
                SELECT COUNT(*), COALESCE(AVG(favorite_count), 0),
                       COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP
                                (ORDER BY favorite_count), 0)
                FROM items
                WHERE LOWER(name) LIKE %s
                  AND favorite_count > 5
            """, (f"%{word}%",))

        comp, avg_f, med_f = cur.fetchone()
        comp = int(comp or 0)
        avg_f = float(avg_f or 0)
        med_f = float(med_f or 0)

        if comp > max_competition or comp < 3:
            continue
        if med_f < 200:
            continue

        gap_score = (vn * 1.5 + med_f * 0.1) / math.log1p(comp)

        candidates.append({
            "word": word,
            "comp": comp,
            "median_favs": int(med_f),
            "avg_favs": int(avg_f),
            "velocity": round(vn, 1),
            "momentum_ratio": round(momentum_ratio, 2),
            "gap_score": int(gap_score),
        })

    candidates.sort(key=lambda x: x["gap_score"], reverse=True)
    return {
        "candidates": candidates[:top_n * 3],
        "window_days": days,
        "category": category,
        "total_keywords_scanned": len(keyword_momentum),
    }


def cross_reference_gaps(cur, seed_keyword, gaps):
    """Boost gaps semantically close to seed keyword."""
    if not gaps or not seed_keyword:
        return gaps

    seed_tokens = set(_tokens(seed_keyword))
    if not seed_tokens:
        return gaps

    pattern = f"%{seed_keyword}%"
    cur.execute("""
        SELECT LOWER(name) FROM items
        WHERE LOWER(name) LIKE %s AND favorite_count > 5
        LIMIT 1000
    """, (pattern,))
    seed_items = cur.fetchall()

    co_occur = Counter()
    for (name,) in seed_items:
        for w in _tokens(name):
            if w not in seed_tokens:
                co_occur[w] += 1

    for g in gaps:
        co_count = co_occur.get(g["word"], 0)
        g["co_occurrence"] = co_count
        if co_count > 0:
            g["gap_score"] = int(g["gap_score"] * (1 + math.log1p(co_count) * 0.3))
        else:
            g["gap_score"] = int(g["gap_score"] * 0.6)

    gaps.sort(key=lambda x: x["gap_score"], reverse=True)
    return gaps


def format_rising_gaps(result, seed=None):
    if not result or result.get("error"):
        cat_label = result.get("category") if result else "all"
        return (
            f"# 🌱 RISING GAPS ({cat_label})\n\n"
            "_No history found. Run snapshot workflow 3-4 days in a row._"
        )

    cands = result.get("candidates", [])
    cat = result.get("category") or "all categories"

    if not cands:
        return (
            f"# 🌱 RISING GAPS — {cat.upper()}\n\n"
            "_No rising-low-competition keywords found this window._\n\n"
            "**Try:**\n"
            "- `!rising_gaps 30` — wider window\n"
            "- `!rising_gaps emote 30` — category + window\n"
            "- Run **snapshot workflow** daily to build history"
        )

    lines = [f"# 🌱 RISING GAPS — {cat.upper()}", ""]
    if seed:
        lines.append(f"_Cross-referenced with `{seed}`._\n")
    lines.append(
        f"_Scanned **{result.get('total_keywords_scanned', 0):,}** keywords over "
        f"**{result.get('window_days', 14)} days**._\n"
    )

    lines.append("## 🎯 TOP GAP OPPORTUNITIES\n")
    for i, c in enumerate(cands[:15], 1):
        co = c.get("co_occurrence", 0)
        co_str = f" · co-occurs **{co}x**" if co > 0 else ""
        lines.append(
            f"**{i}. `{c['word']}`** — score **{c['gap_score']:,}**\n"
            f"   · momentum **{c['momentum_ratio']:.1f}x** · "
            f"velocity **{c['velocity']:.0f}** favs/day\n"
            f"   · **{c['comp']}** competitors · "
            f"median **{c['median_favs']:,}** favs{co_str}\n"
        )

    lines.append("---")
    lines.append("## 💡 USAGE")
    lines.append("- `!rising_gaps hip sway dance` → auto-detects emote")
    lines.append("- `!rising_gaps crown` → auto-detects hat")
    lines.append("- `!rising_gaps accessory` → explicit accessory filter")
    return "\n".join(lines)
