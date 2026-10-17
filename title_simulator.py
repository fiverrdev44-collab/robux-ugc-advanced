"""
title_simulator.py — Score titles against live DB.
"""
import math
import re

TOKEN_RE = re.compile(r"[a-z0-9]+")

FILLER_PENALTY = {
    "chill","groovy","cool","cute","nice","smooth","epic","fun","funny",
    "vibes","vibe","aesthetic","trendy","viral","awesome","amazing",
    "super","best","top","new","hot","troll","meme","memes","lol",
}

ITEM_TYPE_WORDS = {
    "emote","dance","hat","beanie","crown","cap","hair","face","mask",
    "shirt","pants","jacket","shoes","wing","wings","tail","ears","horn",
    "horns","glasses","necklace","chain","backpack","sword","pet","bag",
    "scarf","bandana","beret","visor",
}


def _tokens(text):
    return [t for t in TOKEN_RE.findall((text or "").lower()) if t]


def simulate_title(cur, title, category=None, category_asset_ids=None):
    toks = _tokens(title)
    if not toks:
        return None

    n = len(toks)
    first_token = toks[0]
    last_token = toks[-1]

    # Per-token competition
    token_stats = {}
    for t in toks:
        if len(t) < 3:
            token_stats[t] = {"comp": 0, "searchable": False}
            continue
        if category_asset_ids:
            cur.execute("""
                SELECT COUNT(*) FROM items
                WHERE LOWER(name) LIKE %s AND favorite_count > 5
                  AND asset_type_id = ANY(%s)
            """, (f"%{t}%", category_asset_ids))
        else:
            cur.execute("""
                SELECT COUNT(*) FROM items
                WHERE LOWER(name) LIKE %s AND favorite_count > 5
            """, (f"%{t}%",))
        comp = int(cur.fetchone()[0] or 0)
        token_stats[t] = {"comp": comp, "searchable": comp >= 10}

    searchable = sum(1 for s in token_stats.values() if s["searchable"])

    # Bigram check
    bigram_hits = 0
    for i in range(n - 1):
        bg = f"{toks[i]} {toks[i+1]}"
        if category_asset_ids:
            cur.execute("""
                SELECT COUNT(*) FROM items
                WHERE LOWER(name) LIKE %s AND favorite_count > 5
                  AND asset_type_id = ANY(%s) LIMIT 1
            """, (f"%{bg}%", category_asset_ids))
        else:
            cur.execute("""
                SELECT COUNT(*) FROM items
                WHERE LOWER(name) LIKE %s AND favorite_count > 5 LIMIT 1
            """, (f"%{bg}%",))
        if cur.fetchone()[0] > 5:
            bigram_hits += 1

    # Exact match
    if category_asset_ids:
        cur.execute("""
            SELECT COUNT(*) FROM items
            WHERE LOWER(name) LIKE %s AND favorite_count > 5
              AND asset_type_id = ANY(%s)
        """, (f"%{title.lower()}%", category_asset_ids))
    else:
        cur.execute("""
            SELECT COUNT(*) FROM items
            WHERE LOWER(name) LIKE %s AND favorite_count > 5
        """, (f"%{title.lower()}%",))
    exact_comp = int(cur.fetchone()[0] or 0)

    # Similar items
    tok_set = set(toks)
    if category_asset_ids:
        cur.execute("""
            SELECT LOWER(name), favorite_count FROM items
            WHERE favorite_count > 100 AND asset_type_id = ANY(%s)
            ORDER BY favorite_count DESC LIMIT 500
        """, (category_asset_ids,))
    else:
        cur.execute("""
            SELECT LOWER(name), favorite_count FROM items
            WHERE favorite_count > 100
            ORDER BY favorite_count DESC LIMIT 500
        """)
    similar = []
    for name, favs in cur.fetchall():
        name_set = set(_tokens(name))
        overlap = len(tok_set & name_set)
        if overlap >= 2:
            similar.append({
                "name": name, "favs": favs or 0, "overlap": overlap,
            })
    similar.sort(key=lambda x: (x["overlap"], x["favs"]), reverse=True)
    similar = similar[:5]

    # Scoring
    searchable_score = (searchable / max(1, n)) * 30

    first_stats = token_stats.get(first_token, {})
    if first_stats.get("searchable"):
        fc = first_stats["comp"]
        if 50 <= fc <= 500:
            first_score = 20
        elif fc < 50:
            first_score = 12
        elif fc < 2000:
            first_score = 15
        else:
            first_score = 8
    else:
        first_score = 0

    bigram_score = (bigram_hits / max(1, n - 1)) * 15

    if exact_comp == 0:
        exact_score = 10
    elif exact_comp < 5:
        exact_score = 8
    elif exact_comp < 30:
        exact_score = 5
    else:
        exact_score = 1

    if 3 <= n <= 5:
        length_score = 15
    elif n in (2, 6):
        length_score = 5
    else:
        length_score = 0

    type_score = 10 if last_token in ITEM_TYPE_WORDS else 0

    filler_count = sum(1 for t in toks if t in FILLER_PENALTY)
    filler_penalty = filler_count * 8

    total = (searchable_score + first_score + bigram_score +
             exact_score + length_score + type_score - filler_penalty)
    total = max(0, min(100, total))

    if total >= 80:
        verdict = "🥇 GOLD — likely front page"
    elif total >= 65:
        verdict = "🥈 STRONG — top 10% potential"
    elif total >= 50:
        verdict = "🥉 VIABLE — good chance"
    elif total >= 35:
        verdict = "⚠️ WEAK — needs work"
    else:
        verdict = "❌ DEAD — won't rank"

    return {
        "title": title,
        "front_page_score": round(total, 1),
        "verdict": verdict,
        "similar_titles": similar,
        "raw": {
            "tokens": toks,
            "first_comp": first_stats.get("comp", 0),
            "exact_matches": exact_comp,
            "bigrams": bigram_hits,
            "filler_count": filler_count,
        },
    }


def rank_candidates(cur, titles, category=None, category_asset_ids=None):
    scored = []
    seen = set()
    for title in titles:
        if not title or not title.strip():
            continue
        try:
            result = simulate_title(cur, title, category, category_asset_ids)
            if result:
                sig = tuple(sorted(set(_tokens(title))))
                if sig in seen:
                    continue
                seen.add(sig)
                scored.append(result)
        except Exception as e:
            print(f"[sim] error on '{title}': {e}", flush=True)
    scored.sort(key=lambda x: x["front_page_score"], reverse=True)
    return scored


def format_simulation_report(ranked, show_top=5):
    if not ranked:
        return "# 🧠 TITLE SIMULATOR\n\n_No candidates._"

    lines = ["# 🧠 TITLE SIMULATOR", ""]
    lines.append(f"Scored **{len(ranked)}** candidates.\n")

    for i, r in enumerate(ranked[:show_top], 1):
        lines.append(f"**{i}. `{r['title']}`** — **{r['front_page_score']}/100**")
        lines.append(f"   {r['verdict']}")
        raw = r["raw"]
        lines.append(f"   · tokens: {len(raw['tokens'])} · "
                     f"exact matches: {raw['exact_matches']} · "
                     f"first comp: {raw['first_comp']} · "
                     f"filler: {raw['filler_count']}")

    if len(ranked) > show_top:
        lines.append("")
        lines.append("## 📊 REST\n")
        for i, r in enumerate(ranked[show_top:show_top+10], show_top+1):
            lines.append(f"- `{r['title']}` — {r['front_page_score']}/100")

    return "\n".join(lines)
