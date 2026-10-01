"""
gap_engine.py — Market Gap Engine for Roblox UGC.
Finds low-competition / high-demand pockets in the catalog.
"""

import math
import re
from collections import Counter, defaultdict

FILLER = {
    "the","a","an","of","and","or","for","to","in","on","with","my","your",
    "is","it","as","at","by","from","new","old","hot","best","top","roblox",
    "ugc","item","asset","free","sale","buy","sell","use","used","get","got",
    "made","make","has","have","funny","troll","meme","memes","epic","hype",
    "viral","trending","trend","popular","style","styles","design","designed",
    "reupload","reuploaded","original","credit","credits","inspired","based",
    "emoji","emojis","update","version","creator","catalog",
}

TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text):
    return TOKEN_RE.findall((text or "").lower())


def _tokens_with_stop(text, extra_stop):
    out = []
    for t in _tokens(text):
        if len(t) < 3:
            continue
        if t in FILLER:
            continue
        if t in extra_stop:
            continue
        out.append(t)
    return out


def _relevance(word, intent_terms):
    if not intent_terms:
        return 0.5
    w = word.lower()
    hits = 0
    for t in intent_terms:
        tl = t.lower()
        if w == tl or w in tl or tl in w:
            hits += 1
    return min(1.0, 0.4 + 0.3 * hits)


def find_candidate_terms(cur, user_terms, max_scan=4000):
    if not user_terms:
        return Counter(), []

    patterns = [f"%{t}%" for t in user_terms if len(t) >= 2]
    if not patterns:
        return Counter(), []

    cur.execute("""
        SELECT LOWER(name), COALESCE(LOWER(description), ''), favorite_count
        FROM items
        WHERE favorite_count > 0
          AND (LOWER(name) LIKE ANY(%s) OR COALESCE(LOWER(description),'') LIKE ANY(%s))
        LIMIT %s
    """, (patterns, patterns, max_scan))
    rows = cur.fetchall()

    user_set = {t.lower() for t in user_terms}
    unigrams = Counter()
    bigrams = Counter()
    for name, desc, _ in rows:
        toks = _tokens_with_stop(name, user_set)
        for t in set(toks):
            unigrams[t] += 1
        for a, b in zip(toks, toks[1:]):
            bigrams[f"{a} {b}"] += 1

    merged = Counter()
    for t, c in bigrams.items():
        if c >= 2:
            merged[t] = c
    for t, c in unigrams.items():
        if t not in merged:
            merged[t] = c

    return merged, rows


def score_candidates(cur, candidates, user_terms, top_k=120):
    top_words = [w for w, _ in candidates.most_common(top_k)]
    if not top_words:
        return []

    like_patterns = [f"%{w}%" for w in top_words]
    cur.execute("""
        SELECT LOWER(name), favorite_count
        FROM items
        WHERE favorite_count > 0
          AND LOWER(name) LIKE ANY(%s)
    """, (like_patterns,))
    global_rows = cur.fetchall()

    comp = defaultdict(int)
    favs = defaultdict(list)
    for name, f in global_rows:
        for w in top_words:
            if re.search(r'\b' + re.escape(w) + r'\b', name):
                comp[w] += 1
                favs[w].append(f or 0)

    scored = []
    for w in top_words:
        c = comp.get(w, 0)
        if c < 1:
            continue
        f_list = sorted(favs.get(w, []))
        if not f_list:
            continue
        median_f = f_list[len(f_list) // 2]
        top_f = f_list[int(len(f_list) * 0.9)] if len(f_list) >= 3 else f_list[-1]
        avg_f = sum(f_list) / len(f_list)
        rel = _relevance(w, user_terms)

        demand = (0.5 * median_f) + (0.3 * top_f) + (0.2 * avg_f)
        score = (demand * rel) / math.log1p(c)

        scored.append({
            "word": w,
            "comp": c,
            "avg_favs": int(avg_f),
            "median_favs": int(median_f),
            "top_favs": int(top_f),
            "relevance": round(rel, 2),
            "gap_score": int(score),
        })

    scored.sort(key=lambda x: x["gap_score"], reverse=True)
    return scored


def find_combo_gaps(cur, proven_words, user_terms, limit=8):
    if len(proven_words) < 2:
        return []

    pool = [w["word"] for w in proven_words[:20]]
    combos = []
    for i, a in enumerate(pool):
        for b in pool[i+1:]:
            combo = f"{a} {b}"
            try:
                cur.execute("""
                    SELECT COUNT(*), COALESCE(AVG(favorite_count), 0),
                           COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP
                                    (ORDER BY favorite_count), 0)
                    FROM items
                    WHERE favorite_count > 0
                      AND LOWER(name) LIKE %s
                """, (f"%{combo}%",))
                c, avg_f, med_f = cur.fetchone()
            except Exception:
                try:
                    cur.connection.rollback()
                except Exception:
                    pass
                continue

            c = c or 0
            avg_f = avg_f or 0
            med_f = med_f or 0

            if c < 1 or c > 30:
                continue
            if med_f < 500:
                continue

            score = (med_f * 1.5) / math.log1p(c)
            combos.append({
                "combo": combo,
                "comp": c,
                "median_favs": int(med_f),
                "avg_favs": int(avg_f),
                "score": int(score),
            })

    combos.sort(key=lambda x: x["score"], reverse=True)
    return combos[:limit]


def find_pivots(cur, user_terms, saturated_words, limit=6):
    if not saturated_words:
        return []

    patterns = [f"%{w}%" for w in saturated_words[:5]]
    cur.execute("""
        SELECT LOWER(name), favorite_count FROM items
        WHERE favorite_count > 0 AND LOWER(name) LIKE ANY(%s)
        LIMIT 2000
    """, (patterns,))
    rows = cur.fetchall()

    sat_set = {w.lower() for w in saturated_words}
    counter = Counter()
    favs = defaultdict(list)
    for name, f in rows:
        for t in set(_tokens_with_stop(name, sat_set)):
            if t in sat_set:
                continue
            counter[t] += 1
            favs[t].append(f or 0)

    pivots = []
    for w, c in counter.most_common(60):
        if c < 3:
            continue
        f_list = sorted(favs[w])
        med_f = f_list[len(f_list) // 2]
        if med_f < 800:
            continue
        if c > 200:
            continue
        score = med_f / math.log1p(c)
        pivots.append({
            "word": w,
            "comp": c,
            "median_favs": int(med_f),
            "score": int(score),
        })

    pivots.sort(key=lambda x: x["score"], reverse=True)
    return pivots[:limit]


def classify_gaps(scored, top_n=12):
    golden, sweet, saturated = [], [], []
    for s in scored[:top_n * 3]:
        c = s["comp"]
        med = s["median_favs"]
        if c < 100 and med > 1000:
            golden.append(s)
        elif c < 500 and med > 500:
            sweet.append(s)
        else:
            saturated.append(s)
    return golden[:top_n], sweet[:top_n], saturated[:8]


def build_gap_titles(golden_gaps, combo_gaps, user_terms, max_titles=3):
    titles = []
    seen = set()

    for combo in combo_gaps[:max_titles]:
        words = combo["combo"].split()
        title = " ".join(w.capitalize() for w in words)
        if title.lower() not in seen:
            seen.add(title.lower())
            titles.append({
                "title": title,
                "why": f"Combo gap: only {combo['comp']} items, median {combo['median_favs']:,} favs",
                "score": combo["score"],
            })

    if len(titles) < max_titles:
        gap_words = [g["word"] for g in golden_gaps[:5]]
        last_term = user_terms[-1] if user_terms else ""
        for gw in gap_words:
            candidate = f"{gw.capitalize()} {last_term.capitalize()}".strip()
            if candidate.lower() in seen or not last_term:
                continue
            seen.add(candidate.lower())
            matched = [g for g in golden_gaps if g["word"] == gw][0]
            titles.append({
                "title": candidate,
                "why": f"Low comp ({matched['comp']}) + proven demand",
                "score": matched["gap_score"],
            })
            if len(titles) >= max_titles:
                break

    return titles[:max_titles]


def run_gap_engine(cur, user_terms, max_scan=4000):
    candidates, matched_rows = find_candidate_terms(cur, user_terms, max_scan)
    if not candidates:
        return {
            "golden": [], "sweet": [], "saturated": [],
            "combo_gaps": [], "pivots": [], "titles": [],
            "matched": 0,
        }

    scored = score_candidates(cur, candidates, user_terms, top_k=120)
    golden, sweet, saturated = classify_gaps(scored)
    combo_gaps = find_combo_gaps(cur, golden + sweet, user_terms, limit=8)

    saturated_user = [t for t in user_terms if any(
        s["word"] == t.lower() and s["comp"] > 300 for s in scored
    )]
    pivots = find_pivots(cur, user_terms, saturated_user, limit=6) if saturated_user else []

    gap_titles = build_gap_titles(golden, combo_gaps, user_terms, max_titles=3)

    return {
        "golden": golden,
        "sweet": sweet,
        "saturated": saturated,
        "combo_gaps": combo_gaps,
        "pivots": pivots,
        "titles": gap_titles,
        "matched": len(matched_rows),
    }
