"""
title_miner.py — Brute-force title discovery.
Mines co-occurring words, generates combinations, scores by gap.
"""
import re
import math
from collections import Counter, defaultdict

TOKEN_RE = re.compile(r"[a-z]{3,}")

STOP = {
    "the","a","an","of","and","or","for","to","in","on","with","my","your",
    "is","it","as","at","by","from","new","old","roblox","ugc","free","item",
    "this","that","very","cool","nice","cute","best","top","big","small",
}

FILLER = {
    "chill","groovy","cool","cute","nice","smooth","epic","fun","funny",
    "vibes","vibe","aesthetic","trendy","viral","awesome","amazing",
    "super","best","top","new","hot","troll","meme","memes","lol",
}

ITEM_TYPES = {
    "emote","dance","hat","beanie","crown","cap","hair","face","mask",
    "shirt","pants","jacket","shoes","wing","wings","tail","ears","horn",
    "horns","glasses","necklace","chain","backpack","sword","pet","bag",
    "scarf","bandana","beret","visor",
}


def _tokens(text):
    return [t for t in TOKEN_RE.findall((text or "").lower()) if t not in STOP]


def mine_keyword_pool(cur, seed_keywords, category_asset_ids=None, pool_size=40):
    if not seed_keywords:
        return []

    conditions = " OR ".join(["LOWER(name) LIKE %s"] * len(seed_keywords))
    patterns = [f"%{k}%" for k in seed_keywords]
    cat_filter = ""
    params = list(patterns)

    if category_asset_ids:
        cat_filter = " AND asset_type_id = ANY(%s)"
        params.append(category_asset_ids)

    cur.execute(f"""
        SELECT LOWER(name), favorite_count
        FROM items
        WHERE ({conditions}) AND favorite_count > 20
        {cat_filter}
        LIMIT 2000
    """, tuple(params))
    seed_items = cur.fetchall()
    if not seed_items:
        return []

    word_counter = Counter()
    seed_set = set(seed_keywords)
    for name, favs in seed_items:
        tokens = set(_tokens(name))
        for t in tokens:
            if t in seed_set or len(t) < 4 or t in FILLER:
                continue
            word_counter[t] += 1

    candidates = []
    for word, count in word_counter.most_common(150):
        if count < 3:
            continue

        if category_asset_ids:
            cur.execute("""
                SELECT COUNT(*), COALESCE(AVG(favorite_count), 0),
                       COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP
                                (ORDER BY favorite_count), 0)
                FROM items
                WHERE LOWER(name) LIKE %s AND favorite_count > 5
                  AND asset_type_id = ANY(%s)
            """, (f"%{word}%", category_asset_ids))
        else:
            cur.execute("""
                SELECT COUNT(*), COALESCE(AVG(favorite_count), 0),
                       COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP
                                (ORDER BY favorite_count), 0)
                FROM items
                WHERE LOWER(name) LIKE %s AND favorite_count > 5
            """, (f"%{word}%",))
        comp, avg_f, med_f = cur.fetchone()
        comp = int(comp or 0)
        med_f = float(med_f or 0)

        local_rate = count / len(seed_items)
        demand = math.log1p(med_f)
        gap_score = (local_rate * 5 + demand) / math.log1p(comp)

        candidates.append({
            "word": word,
            "local_count": count,
            "local_rate": round(local_rate * 100, 1),
            "comp": comp,
            "median_favs": int(med_f),
            "avg_favs": int(avg_f or 0),
            "gap_score": round(gap_score, 3),
        })

    candidates.sort(key=lambda x: x["gap_score"], reverse=True)
    return candidates[:pool_size]


def score_combo(cur, combo, category_asset_ids=None):
    title_lower = " ".join(combo).lower()

    if category_asset_ids:
        cur.execute("""
            SELECT COUNT(*), COALESCE(AVG(favorite_count), 0),
                   COALESCE(MAX(favorite_count), 0)
            FROM items
            WHERE LOWER(name) LIKE %s AND favorite_count > 5
              AND asset_type_id = ANY(%s)
        """, (f"%{title_lower}%", category_asset_ids))
    else:
        cur.execute("""
            SELECT COUNT(*), COALESCE(AVG(favorite_count), 0),
                   COALESCE(MAX(favorite_count), 0)
            FROM items
            WHERE LOWER(name) LIKE %s AND favorite_count > 5
        """, (f"%{title_lower}%",))
    exact_count, exact_avg, exact_max = cur.fetchone()
    exact_count = int(exact_count or 0)
    exact_avg = float(exact_avg or 0)
    exact_max = int(exact_max or 0)

    token_stats = []
    for t in combo:
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
        token_stats.append({"token": t, "comp": comp})

    bigram_hits = 0
    for i in range(len(combo) - 1):
        bg = f"{combo[i]} {combo[i+1]}"
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
        if cur.fetchone()[0] > 3:
            bigram_hits += 1

    if exact_count == 0:
        scarcity_score = 30
    elif exact_count < 5:
        scarcity_score = 25
    elif exact_count < 20:
        scarcity_score = 15
    elif exact_count < 50:
        scarcity_score = 8
    else:
        scarcity_score = 0

    demand_score = min(30, math.log1p(max(exact_avg, 200)) * 3)

    first = token_stats[0]
    if 30 <= first["comp"] <= 500:
        first_score = 15
    elif first["comp"] < 30:
        first_score = 8
    elif first["comp"] < 2000:
        first_score = 12
    else:
        first_score = 3

    bigram_score = (bigram_hits / max(1, len(combo) - 1)) * 15
    n = len(combo)
    length_score = 10 if 3 <= n <= 4 else 5 if n == 5 else 0

    final = scarcity_score + demand_score + first_score + bigram_score + length_score

    return {
        "title": " ".join(w.capitalize() for w in combo),
        "combo": combo,
        "final_score": round(final, 1),
        "exact_matches": exact_count,
        "exact_avg_favs": int(exact_avg),
        "exact_max_favs": exact_max,
        "first_token_comp": first["comp"],
        "bigram_hits": bigram_hits,
        "n_tokens": n,
    }


def brute_force_combinations(cur, pool, item_type="emote",
                             max_combos=150, category_asset_ids=None):
    if not pool:
        return []

    top_words = [c["word"] for c in pool[:20]]

    type_variants = {
        "emote": ["emote", "dance"],
        "hat": ["hat", "beanie", "cap"],
        "hair": ["hair"],
        "face": ["face", "mask"],
    }.get(item_type, [item_type])

    combos = []
    for w in top_words:
        for tv in type_variants:
            combos.append((w, tv))

    for i, a in enumerate(top_words[:12]):
        for b in top_words[i+1:i+9]:
            combos.append((a, b, type_variants[0]))

    for i, a in enumerate(top_words[:8]):
        for b in top_words[i+1:i+6]:
            for c in top_words[i+2:i+4]:
                if len({a, b, c}) < 3:
                    continue
                combos.append((a, b, c, type_variants[0]))

    seen = set()
    scored = []
    for combo in combos:
        title = " ".join(combo)
        if title in seen:
            continue
        seen.add(title)
        if len(combo) < 3 or len(combo) > 5:
            continue
        try:
            score = score_combo(cur, combo, category_asset_ids)
            if score:
                scored.append(score)
        except Exception:
            continue

    scored.sort(key=lambda x: x["final_score"], reverse=True)
    return scored[:max_combos]


def format_miner_report(seed_keywords, pool, combos):
    lines = ["# 🧬 AUTO-TITLE DISCOVERY", ""]
    lines.append(f"**Seeds:** `{'`, `'.join(seed_keywords)}`\n")

    if pool:
        lines.append("## 🎯 MINED KEYWORD POOL\n")
        for i, p in enumerate(pool[:10], 1):
            lines.append(
                f"**{i}. `{p['word']}`** — "
                f"{p['comp']} competitors · "
                f"median {p['median_favs']:,} favs · "
                f"score **{p['gap_score']}**"
            )
        lines.append("")

    if combos:
        first_movers = [c for c in combos if c["exact_matches"] == 0][:5]
        if first_movers:
            lines.append("## 🏆 FIRST-MOVER TITLES (0 exact matches)\n")
            for i, c in enumerate(first_movers, 1):
                lines.append(
                    f"**{i}. `{c['title']}`** — "
                    f"{c['first_token_comp']} comp · score **{c['final_score']}**"
                )
            lines.append("")

        lines.append("## 🥇 TOP RANKED TITLES\n")
        for i, c in enumerate(combos[:10], 1):
            lines.append(f"**{i}. `{c['title']}`** — **{c['final_score']}/100**")
            lines.append(
                f"   · Exact matches: {c['exact_matches']} · "
                f"First token comp: {c['first_token_comp']} · "
                f"Bigrams: {c['bigram_hits']}"
            )
    return "\n".join(lines)
