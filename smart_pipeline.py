"""
smart_pipeline.py — Recursive competition-aware pipeline with live enrichment.
v2: Creative concepts from intent["search_terms"] now flow through the pipeline.
"""
import math
import re
from collections import Counter

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

SATURATION_RED = 200
SATURATION_YELLOW = 100
MIN_DATA_ITEMS = 20


def _tokens(text):
    return [t for t in TOKEN_RE.findall((text or "").lower()) if t not in STOP]


def _extract_seeds(description, intent=None, top_n=5):
    words = _tokens(description)
    if intent:
        priority = (intent.get("specific_moves") or []) + (intent.get("primary") or [])
        for p in priority:
            for t in _tokens(p):
                if t not in words:
                    words.insert(0, t)
        # NEW: include creative concepts as full phrases (kept intact)
        for p in (intent.get("search_terms") or []):
            p_clean = (p or "").strip().lower()
            if p_clean and p_clean not in words:
                words.append(p_clean)
    seen = set()
    out = []
    for w in words:
        if len(w) < 4 or w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= top_n:
            break
    return out


def _check_comp_local(cur, phrase, category_asset_ids=None):
    phrase_lower = phrase.lower().strip()
    if category_asset_ids:
        cur.execute("""
            SELECT COUNT(*), COALESCE(PERCENTILE_CONT(0.5)
                WITHIN GROUP (ORDER BY favorite_count), 0)
            FROM items
            WHERE LOWER(name) LIKE %s AND favorite_count > 5
              AND asset_type_id = ANY(%s)
        """, (f"%{phrase_lower}%", category_asset_ids))
    else:
        cur.execute("""
            SELECT COUNT(*), COALESCE(PERCENTILE_CONT(0.5)
                WITHIN GROUP (ORDER BY favorite_count), 0)
            FROM items
            WHERE LOWER(name) LIKE %s AND favorite_count > 5
        """, (f"%{phrase_lower}%",))
    row = cur.fetchone()
    return {
        "phrase": phrase,
        "comp": int(row[0] or 0),
        "median_favs": int(row[1] or 0),
    }


def check_competition(cur, phrase, category_asset_ids=None, live_enrich=True):
    local = _check_comp_local(cur, phrase, category_asset_ids)
    if local["comp"] >= MIN_DATA_ITEMS:
        return local
    if live_enrich:
        try:
            from live_enrich import live_enrich_keyword
            print(f"[smart] Local thin ({local['comp']}) for '{phrase}' — enriching", flush=True)
            live_enrich_keyword(phrase, category_asset_ids, max_items=80)
            local = _check_comp_local(cur, phrase, category_asset_ids)
        except Exception as e:
            print(f"[smart] live enrich failed: {e}", flush=True)
    return local


def find_alternatives(cur, saturated_seeds, category_asset_ids=None, limit=10,
                      live_enrich=True):
    if not saturated_seeds:
        return []

    conditions = " OR ".join(["LOWER(name) LIKE %s"] * len(saturated_seeds))
    patterns = [f"%{s}%" for s in saturated_seeds]
    cat_filter = ""
    params = list(patterns)
    if category_asset_ids:
        cat_filter = " AND asset_type_id = ANY(%s)"
        params.append(category_asset_ids)

    cur.execute(f"""
        SELECT LOWER(name), favorite_count
        FROM items
        WHERE ({conditions}) AND favorite_count > 50
        {cat_filter}
        LIMIT 800
    """, tuple(params))
    rows = cur.fetchall()
    if not rows:
        return []

    seed_set = set(saturated_seeds)
    word_counter = Counter()
    for name, favs in rows:
        for w in set(_tokens(name)):
            if w in seed_set or len(w) < 4 or w in FILLER:
                continue
            word_counter[w] += 1

    candidates = []
    for word, count in word_counter.most_common(40):
        if count < 3:
            continue
        data = check_competition(cur, word, category_asset_ids, live_enrich=live_enrich)
        comp = data["comp"]
        med = data["median_favs"]
        if comp > SATURATION_YELLOW:
            continue
        if med < 100:
            continue
        gap_score = (med * 0.5 + count * 20) / math.log1p(comp + 1)
        candidates.append({
            "word": word, "comp": comp, "median_favs": med,
            "co_occurs": count, "gap_score": round(gap_score, 1),
        })

    candidates.sort(key=lambda x: x["gap_score"], reverse=True)
    return candidates[:limit]


def build_titles(seeds, alternatives, item_type="emote"):
    type_variants = {
        "emote": ["emote", "dance"],
        "hat": ["hat", "beanie"],
        "hair": ["hair"],
    }.get(item_type, [item_type])

    alt_words = [a["word"] for a in alternatives]
    titles = set()

    # Expanded: use up to 6 seeds so creative concepts reach title building
    if len(seeds) >= 2:
        for i, a in enumerate(seeds[:6]):
            for b in seeds[i+1:i+4]:
                titles.add((a, b, type_variants[0]))
        for s in seeds[:5]:
            titles.add((s, type_variants[0]))

    for orig in seeds[:3]:
        for alt in alt_words[:5]:
            titles.add((orig, alt, type_variants[0]))
            titles.add((alt, orig, type_variants[0]))

    for i, a in enumerate(alt_words[:5]):
        for b in alt_words[i+1:i+4]:
            titles.add((a, b, type_variants[0]))

    for alt in alt_words[:6]:
        titles.add((alt, type_variants[0]))

    return [" ".join(t) for t in titles if 2 <= len(t) <= 5]


def score_title(cur, title, category_asset_ids=None):
    toks = _tokens(title)
    n = len(toks)
    if n < 2 or n > 6:
        return None

    data = _check_comp_local(cur, title, category_asset_ids)
    exact = data["comp"]
    med_favs = data["median_favs"]

    first = toks[0]
    first_data = _check_comp_local(cur, first, category_asset_ids)

    if exact == 0 and med_favs == 0 and first_data["comp"] < 10:
        return {
            "title": title, "score": 0, "verdict": "⛔ NO DATA",
            "exact_matches": 0, "median_favs": 0,
            "first_comp": first_data["comp"],
            "filler_count": 0, "tokens": n,
        }

    if exact == 0:
        scarcity = 30
    elif exact < 5:
        scarcity = 25
    elif exact < 20:
        scarcity = 15
    elif exact < 50:
        scarcity = 8
    else:
        scarcity = 0

    demand = min(30, math.log1p(med_favs) * 3) if med_favs > 0 else 5

    if 50 <= first_data["comp"] <= 500:
        first_score = 15
    elif first_data["comp"] < 50:
        first_score = 10
    elif first_data["comp"] < 2000:
        first_score = 12
    else:
        first_score = 4

    if 3 <= n <= 4:
        length_score = 10
    elif n == 5:
        length_score = 6
    else:
        length_score = 2

    type_score = 10 if toks[-1] in ITEM_TYPES else 0
    filler_count = sum(1 for t in toks if t in FILLER)
    filler_penalty = filler_count * 10

    total = scarcity + demand + first_score + length_score + type_score - filler_penalty
    total = max(0, min(100, total))

    if total >= 80:
        verdict = "🥇 GOLD"
    elif total >= 65:
        verdict = "🥈 STRONG"
    elif total >= 50:
        verdict = "🥉 VIABLE"
    elif total >= 35:
        verdict = "⚠️ WEAK"
    else:
        verdict = "❌ DEAD"

    return {
        "title": title, "score": round(total, 1), "verdict": verdict,
        "exact_matches": exact, "median_favs": med_favs,
        "first_comp": first_data["comp"], "filler_count": filler_count,
        "tokens": n,
    }


def run_full_pipeline(cur, description, intent=None, item_type="emote",
                      category_asset_ids=None, ai_titles=None,
                      live_enrich=True):
    result = {
        "seeds": [], "seed_analysis": [], "saturated_seeds": [],
        "alternatives": [], "scored_titles": [], "best_title": None,
        "live_enriched": live_enrich, "report": "",
    }

    # Bumped top_n from 5 → 12 so creative concepts survive truncation
    seeds = _extract_seeds(description, intent, top_n=12)
    result["seeds"] = seeds
    if not seeds:
        return result

    seed_analysis = []
    saturated = []
    good_seeds = []
    for seed in seeds:
        data = check_competition(cur, seed, category_asset_ids, live_enrich=live_enrich)
        seed_analysis.append(data)
        if data["comp"] >= SATURATION_RED:
            saturated.append(seed)
        else:
            good_seeds.append(seed)

    result["seed_analysis"] = seed_analysis
    result["saturated_seeds"] = saturated

    alternatives = []
    if saturated:
        alternatives = find_alternatives(cur, saturated, category_asset_ids,
                                         limit=12, live_enrich=live_enrich)
    result["alternatives"] = alternatives

    candidates = set()
    if ai_titles:
        for t in ai_titles:
            if t and t.strip():
                candidates.add(t)
    for t in build_titles(good_seeds, alternatives, item_type):
        candidates.add(t)

    candidates = list(candidates)[:25]

    scored = []
    for title in candidates:
        try:
            s = score_title(cur, title, category_asset_ids)
            if s:
                scored.append(s)
        except Exception as e:
            print(f"[smart] score fail '{title}': {e}", flush=True)

    scored.sort(key=lambda x: x["score"], reverse=True)
    result["scored_titles"] = scored
    if scored:
        result["best_title"] = scored[0]

    result["report"] = _format_report(result)
    return result


def _format_report(r):
    lines = ["# 🧬 SMART PIPELINE — Live Enriched", ""]
    if r["live_enriched"]:
        lines.append("_Live API enrichment active._\n")
    if r["seeds"]:
        lines.append(f"**Seeds:** `{'`, `'.join(r['seeds'])}`\n")

    if r["seed_analysis"]:
        lines.append("## 🔍 SEED COMPETITION (Roblox Live)\n")
        for s in r["seed_analysis"]:
            comp = s["comp"]
            med = s["median_favs"]
            if comp >= SATURATION_RED:
                icon, note = "🔴", "SATURATED"
            elif comp >= SATURATION_YELLOW:
                icon, note = "🟡", "Competitive"
            elif comp < 30:
                icon, note = "🟢", "LOW COMP"
            else:
                icon, note = "🟢", "Healthy"
            lines.append(f"- {icon} `{s['phrase']}` — **{comp}** competitors · "
                         f"median **{med:,}** favs · {note}")
        lines.append("")

    if r["saturated_seeds"]:
        lines.append(f"## 🚨 AUTO-REPLACED: `{'`, `'.join(r['saturated_seeds'])}`\n")

    if r["alternatives"]:
        lines.append("## 💎 ALTERNATIVES\n")
        for i, a in enumerate(r["alternatives"][:10], 1):
            lines.append(f"**{i}. `{a['word']}`** — {a['comp']} comp · "
                         f"median {a['median_favs']:,} favs · score {a['gap_score']}")
        lines.append("")

    if r["scored_titles"]:
        lines.append("## 🥇 FINAL RANKED TITLES\n")
        for i, s in enumerate(r["scored_titles"][:10], 1):
            lines.append(f"**{i}. `{s['title']}`** — **{s['score']}/100**")
            lines.append(f"   · {s['verdict']} · exact: {s['exact_matches']} · "
                         f"first comp: {s['first_comp']}")
        lines.append("")

    if r["best_title"]:
        b = r["best_title"]
        lines.append("## ✅ TOP RECOMMENDATION\n")
        lines.append(f"### `{b['title']}`")
        lines.append(f"**Score: {b['score']}/100** — {b['verdict']}")
        lines.append(f"- Exact matches: **{b['exact_matches']}**")
        lines.append(f"- Median favs: **{b['median_favs']:,}**")
        lines.append(f"- First comp: **{b['first_comp']}**")
        lines.append("")
        lines.append("**→ Use this title.**")

    return "\n".join(lines)
