"""
smart_pipeline.py — v3.5: parallel scan + single-writer live enrichment.

FIXES in this version:
- search_terms REMOVED entirely from _extract_seeds. Gemini's expansion
  pulls in unrelated words from your OWN DB history (e.g. "russian"
  leaking in after chaining a "viral russian kick dance" item). The
  trade-off isn't worth it — chain runs 3-5x faster without it.

- Only pulls from intent["specific_moves"] + intent["primary"]
  (user-typed words that are guaranteed relevant).

- _DRIFT_BLOCK still filters the most obvious noise tokens.
"""
import math
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# ── Drift blocklist ────────────────────────────────────────────
# Filter for tokens that should never trigger live-enrich.
_DRIFT_BLOCK = {
    # Time
    "month", "week", "year", "time", "hour", "minute", "second",
    "today", "tomorrow", "yesterday", "morning", "evening", "night",
    # Generic nationalities
    "russian", "japanese", "korean", "chinese", "english", "american",
    "french", "german", "spanish", "italian", "mexican", "indian",
    "african", "european", "asian",
    # Generic motion words
    "movement", "motion", "action", "gesture", "expression", "reaction",
    # Generic nouns
    "thing", "stuff", "person", "people", "place", "point", "case",
    "way", "kind", "sort", "type", "form", "part", "line", "area",
    # Meta
    "sport", "game", "play", "playing", "trend", "trends", "popular",
    "memes", "meme", "first", "second", "third", "next", "last",
    # Abstract
    "world", "life", "work", "school", "home", "house", "friend",
    "family", "story", "book", "paper", "letter", "note", "list",
}

SATURATION_RED = 200
SATURATION_YELLOW = 100
MIN_DATA_ITEMS = 20

LIVE_ENRICH_CONCURRENCY = 1
MAX_WORKERS = 6

_live_enrich_sem = threading.Semaphore(LIVE_ENRICH_CONCURRENCY)


def _tokens(text):
    return [t for t in TOKEN_RE.findall((text or "").lower()) if t not in STOP]


def _extract_seeds(description, intent=None, top_n=5):
    """
    Extract seed keywords for live enrichment.

    ONLY pulls from specific_moves + primary. search_terms is EXCLUDED.
    Reason: Gemini's expansion drags in unrelated words from your own
    DB history (e.g. "russian" appears after chaining a "viral russian
    kick dance" item). Every live-enrich call is expensive; the noise
    isn't worth the trade-off.
    """
    words = _tokens(description)
    if intent:
        # Only the trustworthy, user-typed sources
        priority = (intent.get("specific_moves") or []) + (intent.get("primary") or [])
        for p in priority:
            for t in _tokens(p):
                if t not in words:
                    words.insert(0, t)

    seen = set()
    out = []
    for w in words:
        if len(w) < 4 or w in seen or w in _DRIFT_BLOCK:
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
            SELECT COUNT(*),
                   COALESCE(PERCENTILE_CONT(0.5)
                       WITHIN GROUP (ORDER BY favorite_count), 0),
                   COALESCE(PERCENTILE_CONT(0.5)
                       WITHIN GROUP (ORDER BY price)
                       FILTER (WHERE price BETWEEN 5 AND 10000), 0)
            FROM items
            WHERE LOWER(name) LIKE %s AND favorite_count > 5
              AND asset_type_id = ANY(%s)
        """, (f"%{phrase_lower}%", category_asset_ids))
    else:
        cur.execute("""
            SELECT COUNT(*),
                   COALESCE(PERCENTILE_CONT(0.5)
                       WITHIN GROUP (ORDER BY favorite_count), 0),
                   COALESCE(PERCENTILE_CONT(0.5)
                       WITHIN GROUP (ORDER BY price)
                       FILTER (WHERE price BETWEEN 5 AND 10000), 0)
            FROM items
            WHERE LOWER(name) LIKE %s AND favorite_count > 5
        """, (f"%{phrase_lower}%",))
    row = cur.fetchone()
    return {
        "phrase": phrase,
        "comp": int(row[0] or 0),
        "median_favs": int(row[1] or 0),
        "median_price": int(row[2] or 0),
    }


def _comp_check_worker(seed, category_asset_ids, live_enrich, db_factory):
    conn = db_factory()
    try:
        cur = conn.cursor()
        try:
            local = _check_comp_local(cur, seed, category_asset_ids)
        finally:
            cur.close()

        if local["comp"] < MIN_DATA_ITEMS and live_enrich:
            with _live_enrich_sem:
                try:
                    from live_enrich import live_enrich_keyword
                    print(f"[smart] thin ({local['comp']}) '{seed}' — live enriching", flush=True)
                    live_enrich_keyword(seed, category_asset_ids, max_items=80)
                except Exception as e:
                    print(f"[smart] live enrich failed '{seed}': {e}", flush=True)

            conn.close()
            conn = db_factory()
            cur = conn.cursor()
            try:
                local = _check_comp_local(cur, seed, category_asset_ids)
                local["live_enriched"] = True
            finally:
                cur.close()

        return local
    finally:
        try: conn.close()
        except Exception: pass


def _parallel_comp_check(seeds, category_asset_ids, live_enrich, db_factory):
    if not seeds:
        return []
    results = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {
            ex.submit(_comp_check_worker, s, category_asset_ids, live_enrich, db_factory): s
            for s in seeds
        }
        for fut in as_completed(futures):
            seed = futures[fut]
            try:
                results[seed] = fut.result()
            except Exception as e:
                print(f"[smart] comp worker fail '{seed}': {e}", flush=True)
                results[seed] = {"phrase": seed, "comp": 0, "median_favs": 0, "median_price": 0}
    return [results[s] for s in seeds if s in results]


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


def _find_alt_candidates(cur, saturated_seeds, category_asset_ids):
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
            if w in seed_set or len(w) < 4 or w in FILLER or w in _DRIFT_BLOCK:
                continue
            word_counter[w] += 1

    return [(w, c) for w, c in word_counter.most_common(40) if c >= 3]


def _alt_worker(word, count, category_asset_ids, db_factory, live_enrich):
    conn = db_factory()
    try:
        cur = conn.cursor()
        try:
            data = _check_comp_local(cur, word, category_asset_ids)
        finally:
            cur.close()

        if data["comp"] < MIN_DATA_ITEMS and live_enrich:
            with _live_enrich_sem:
                try:
                    from live_enrich import live_enrich_keyword
                    live_enrich_keyword(word, category_asset_ids, max_items=80)
                except Exception:
                    pass
            conn.close()
            conn = db_factory()
            cur = conn.cursor()
            try:
                data = _check_comp_local(cur, word, category_asset_ids)
            finally:
                cur.close()

        comp = data["comp"]
        med = data["median_favs"]
        if comp > SATURATION_YELLOW or med < 100:
            return None
        gap_score = (med * 0.5 + count * 20) / math.log1p(comp + 1)
        return {
            "word": word, "comp": comp, "median_favs": med,
            "median_price": data["median_price"],
            "co_occurs": count, "gap_score": round(gap_score, 1),
        }
    finally:
        try: conn.close()
        except Exception: pass


def find_alternatives_parallel(saturated_seeds, category_asset_ids, db_factory,
                               limit=10, live_enrich=True):
    if not saturated_seeds:
        return []
    conn = db_factory()
    try:
        cur = conn.cursor()
        try:
            candidates = _find_alt_candidates(cur, saturated_seeds, category_asset_ids)
        finally:
            cur.close()
    finally:
        conn.close()

    if not candidates:
        return []

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {
            ex.submit(_alt_worker, w, c, category_asset_ids, db_factory, live_enrich): w
            for w, c in candidates
        }
        for fut in as_completed(futures):
            try:
                r = fut.result()
                if r:
                    results.append(r)
            except Exception as e:
                print(f"[smart] alt worker fail: {e}", flush=True)

    results.sort(key=lambda x: x["gap_score"], reverse=True)
    return results[:limit]


def find_alternatives(cur, saturated_seeds, category_asset_ids=None, limit=10,
                      live_enrich=True):
    if not saturated_seeds:
        return []
    candidates = _find_alt_candidates(cur, saturated_seeds, category_asset_ids)
    out = []
    for word, count in candidates:
        data = check_competition(cur, word, category_asset_ids, live_enrich=live_enrich)
        comp = data["comp"]
        med = data["median_favs"]
        if comp > SATURATION_YELLOW or med < 100:
            continue
        gap_score = (med * 0.5 + count * 20) / math.log1p(comp + 1)
        out.append({
            "word": word, "comp": comp, "median_favs": med,
            "median_price": data.get("median_price", 0),
            "co_occurs": count, "gap_score": round(gap_score, 1),
        })
    out.sort(key=lambda x: x["gap_score"], reverse=True)
    return out[:limit]


def run_full_pipeline(cur=None, description="", intent=None, item_type="emote",
                      category_asset_ids=None, ai_titles=None,
                      live_enrich=True, db_factory=None):
    parallel = db_factory is not None

    result = {
        "seeds": [], "seed_analysis": [], "saturated_seeds": [],
        "alternatives": [],
        "live_enriched": live_enrich, "parallel": parallel, "report": "",
    }

    seeds = _extract_seeds(description, intent, top_n=12)
    result["seeds"] = seeds
    if not seeds:
        return result

    if parallel:
        seed_analysis = _parallel_comp_check(seeds, category_asset_ids, live_enrich, db_factory)
    else:
        seed_analysis = []
        for s in seeds:
            seed_analysis.append(check_competition(cur, s, category_asset_ids, live_enrich=live_enrich))

    saturated, good_seeds = [], []
    for s in seed_analysis:
        if s["comp"] >= SATURATION_RED:
            saturated.append(s["phrase"])
        else:
            good_seeds.append(s["phrase"])

    result["seed_analysis"] = seed_analysis
    result["saturated_seeds"] = saturated

    if saturated:
        if parallel:
            alternatives = find_alternatives_parallel(
                saturated, category_asset_ids, db_factory,
                limit=12, live_enrich=live_enrich)
        else:
            alternatives = find_alternatives(
                cur, saturated, category_asset_ids,
                limit=12, live_enrich=live_enrich)
    else:
        alternatives = []
    result["alternatives"] = alternatives

    result["report"] = _format_report(result)
    return result


def _format_report(r):
    lines = ["# 🧬 SMART PIPELINE — Live Enriched", ""]
    if r.get("parallel"):
        lines.append("_Parallel scan · single-writer enrich mode._\n")
    elif r["live_enriched"]:
        lines.append("_Live API enrichment active._\n")

    if r["seeds"]:
        lines.append(f"**Seeds:** `{'`, `'.join(r['seeds'])}`\n")

    if r["seed_analysis"]:
        lines.append("## 🔍 SEED COMPETITION")
        lines.append("")
        for s in r["seed_analysis"]:
            comp = s["comp"]
            med = s["median_favs"]
            price = s.get("median_price", 0)
            if comp >= SATURATION_RED:
                icon, note = "🔴", "SATURATED"
            elif comp >= SATURATION_YELLOW:
                icon, note = "🟡", "Competitive"
            elif comp < 30:
                icon, note = "🟢", "LOW COMP"
            else:
                icon, note = "🟢", "Healthy"
            enriched = " · ⚡live" if s.get("live_enriched") else ""
            price_str = f" · median {price} R$" if price else ""
            lines.append(f"- {icon} `{s['phrase']}` — **{comp}** competitors · "
                         f"median **{med:,}** favs{price_str} · {note}{enriched}")
        lines.append("")

    if r["saturated_seeds"]:
        lines.append(f"## 🚨 AUTO-REPLACED: `{'`, `'.join(r['saturated_seeds'])}`\n")

    if r["alternatives"]:
        lines.append("## 💎 ALTERNATIVES\n")
        for i, a in enumerate(r["alternatives"][:10], 1):
            price = a.get("median_price", 0)
            price_str = f" · {price} R$" if price else ""
            lines.append(f"**{i}. `{a['word']}`** — {a['comp']} comp · "
                         f"median {a['median_favs']:,} favs{price_str} · score {a['gap_score']}")
        lines.append("")

    return "\n".join(lines)
