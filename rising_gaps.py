"""
rising_gaps.py — Find keywords that are RISING but still low-competition.
The holy grail: momentum high, competition low.
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
    "dance","emote","animation","style","aesthetic",
}


def _tokens(text):
    return [t for t in TOKEN_RE.findall((text or "").lower()) if t not in STOP]


def _percentile(vals, pct):
    if not vals: return 0
    idx = min(int(len(vals) * pct), len(vals) - 1)
    return vals[idx]


def find_rising_gaps(cur, days=14, max_competition=150, min_momentum=1.5, top_n=20):
    """
    Find keywords where:
      - favourite velocity is ACCELERATING (momentum > min_momentum)
      - total items using that keyword < max_competition
      - median favourite count is meaningful (demand exists)

    Returns ranked list of gap opportunities.
    """
    # ── Step 1: Pull item_history for recent window ──
    cur.execute(f"""
        SELECT i.id, LOWER(i.name), h.favorite_count, h.snapshot_at
        FROM item_history h
        JOIN items i ON i.id = h.item_id
        WHERE h.snapshot_at > NOW() - INTERVAL '{days * 2} days'
          AND h.favorite_count > 0
        ORDER BY h.item_id, h.snapshot_at
    """)
    rows = cur.fetchall()
    if not rows:
        return {"error": "no_history"}

    # Group by item
    item_series = defaultdict(list)
    for iid, name, favs, snap in rows:
        item_series[iid].append((snap, favs, name))

    now = max(r[3] for r in rows)
    cutoff = now - timedelta(days=days)

    # ── Step 2: Compute per-keyword momentum ──
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

    # ── Step 3: For each keyword, get competition + demand from full DB ──
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

        # Global competition: how many items in DB use this word
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

        # GAP SCORE: reward momentum + demand, punish competition
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
        "total_keywords_scanned": len(keyword_momentum),
    }


def cross_reference_gaps(cur, seed_keyword, gaps):
    """
    Given a saturated seed keyword and a list of candidate gaps,
    find which gaps are SEMANTICALLY CLOSE to the seed.
    Uses co-occurrence in item names.
    """
    if not gaps or not seed_keyword:
        return gaps

    seed_tokens = set(_tokens(seed_keyword))
    if not seed_tokens:
        return gaps

    # Pull items matching the seed to find co-occurring words
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

    # Score each gap by how often it appears alongside the seed
    for g in gaps:
        co_count = co_occur.get(g["word"], 0)
        g["co_occurrence"] = co_count
        # Boost gaps that co-occur (same vibe/niche as seed)
        # Penalize totally unrelated words
        if co_count > 0:
            g["gap_score"] = int(g["gap_score"] * (1 + math.log1p(co_count) * 0.3))
        else:
            g["gap_score"] = int(g["gap_score"] * 0.6)

    gaps.sort(key=lambda x: x["gap_score"], reverse=True)
    return gaps


def format_rising_gaps(result, seed=None):
    if not result or result.get("error"):
        return "# 🌱 RISING GAPS\n\n_Not enough history yet. Run snapshots daily._"

    cands = result.get("candidates", [])
    if not cands:
        return ("# 🌱 RISING GAPS\n\n"
                "_No rising-low-competition keywords found this window._\n"
                "_Try `!rising_gaps 30` for a wider window._")

    lines = ["# 🌱 RISING GAPS — Where To Build Next", ""]
    if seed:
        lines.append(f"_Cross-referenced with `{seed}` to find adjacent niches._\n")
    lines.append(f"_Scanned **{result.get('total_keywords_scanned', 0):,}** keywords over "
                 f"**{result.get('window_days', 14)} days**. "
                 f"Showing {len(cands[:15])}.\n")

    lines.append("## 🎯 TOP GAP OPPORTUNITIES")
    lines.append("_High momentum + low competition. Enter before the crowd._\n")
    for i, c in enumerate(cands[:15], 1):
        co = c.get("co_occurrence", 0)
        co_str = f" · co-occurs with seed **{co}x**" if co > 0 else ""
        lines.append(
            f"**{i}. `{c['word']}`** — score **{c['gap_score']:,}**\n"
            f"   · momentum **{c['momentum_ratio']:.1f}x** · "
            f"velocity **{c['velocity']:.0f}** favs/day\n"
            f"   · **{c['comp']}** competitors · median **{c['median_favs']:,}** favs{co_str}\n"
        )

    lines.append("---")
    lines.append("## 💡 HOW TO USE THIS")
    lines.append("1. Pick a top-3 keyword from the list")
    lines.append("2. Run `!predict <keyword>` to score it fully")
    lines.append("3. Run `!brainstorm <keyword>` to get titles")
    lines.append("4. Launch within 7 days before competition floods in")
    return "\n".join(lines)
