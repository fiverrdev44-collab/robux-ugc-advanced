"""
creative_pivot.py — Category-aware creative expansion + super-computer pivot finder.

Combines:
  - AI fan-out (category-aware via creative_expand)
  - Real search data (search_suggestions)
  - Proven demand (learned_keywords)
Then cross-references every candidate against DB supply/demand and (optionally)
live Roblox API.

Public API:
  find_creative_pivots(seed_words, item_type="emote", ...) -> dict
  format_creative_pivot_report(result) -> str
"""
import os
import re
from collections import Counter

from category_configs import (
    get_category_config,
    detect_family_from_asset_type,
    get_filler_block,
)


def _normalize(word):
    return (word or "").lower().strip()


def _looks_like_concept(word, config):
    """Category-aware filter — rejects filler + type words + stopwords."""
    w = _normalize(word)
    if len(w) < 3:
        return False
    if w in config["filler_block"]:
        return False
    if w in set(config.get("type_words", [])):
        return False
    if w.isdigit():
        return False
    return True


def _fetch_db_stats_batch(cur, words):
    if not words or cur is None:
        return {}
    clean = [w for w in {_normalize(w) for w in words}]
    clean = [w for w in clean if len(w) >= 3 and not w.isdigit()]
    if not clean:
        return {}

    parts, params = [], []
    for w in clean:
        parts.append("""
            SELECT %s AS word,
                   COUNT(*) AS supply,
                   COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP
                            (ORDER BY favorite_count), 0) AS median_favs,
                   COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP
                            (ORDER BY price), 0) AS median_price
            FROM items
            WHERE LOWER(name) LIKE %s AND favorite_count > 5
        """)
        params.extend([w, f"%{w}%"])

    sql = " UNION ALL ".join(parts)
    out = {}
    try:
        cur.execute(sql, tuple(params))
        for row in cur.fetchall():
            word = _normalize(row[0])
            out[word] = {
                "supply": int(row[1] or 0),
                "median_favs": int(row[2] or 0),
                "median_price": int(row[3] or 0),
            }
    except Exception as e:
        print(f"[creative_pivot] batch stats failed: {e}", flush=True)
    return out


def _classify(supply, median_favs):
    if median_favs < 15:
        return ("DEAD", "🔴")
    if supply < 20 and median_favs >= 150:
        return ("GOLD", "🟢")
    if supply < 50 and median_favs >= 80:
        return ("OPPORTUNITY", "🔵")
    if supply >= 50 and median_favs >= 80:
        return ("SATURATED", "🟡")
    if supply < 20 and median_favs < 50:
        return ("WEAK", "🟠")
    return ("NEUTRAL", "⚪")


def _seeds_from_creative_expand(seed_words, item_type, config, n=12):
    anchor = " ".join(seed_words[:4]) or "ugc"
    try:
        from creative_expand import expand_with_validation
        data = expand_with_validation(anchor, n=n, item_type=item_type)
        results = data.get("results") or []
        concepts = []
        for r in results:
            c = _normalize(r.get("concept") or "")
            if not c:
                continue
            first = c.split()[0] if c.split() else ""
            if _looks_like_concept(first, config):
                concepts.append(first)
        return concepts
    except Exception as e:
        print(f"[creative_pivot] creative_expand failed: {e}", flush=True)
        return []


def _seeds_from_search_suggestions(cur, seed_words, config, limit=25):
    if cur is None or not seed_words:
        return []
    try:
        patterns = [f"%{_normalize(w)}%" for w in seed_words if w]
        cur.execute("""
            SELECT DISTINCT suggestion FROM search_suggestions
            WHERE LOWER(suggestion) LIKE ANY(%s)
            LIMIT 300
        """, (patterns,))
        rows = cur.fetchall()
    except Exception as e:
        print(f"[creative_pivot] search_suggestions failed: {e}", flush=True)
        return []

    seed_set = {_normalize(w) for w in seed_words}
    counter = Counter()
    for (s,) in rows:
        for tok in re.findall(r"[a-z]{3,}", (s or "").lower()):
            if tok in seed_set:
                continue
            if not _looks_like_concept(tok, config):
                continue
            counter[tok] += 1
    return [w for w, _ in counter.most_common(limit)]


def _seeds_from_learned_keywords(cur, seed_words, config, limit=15):
    if cur is None:
        return []
    try:
        cur.execute("""
            SELECT keyword, score FROM learned_keywords
            WHERE score > 0
            ORDER BY score DESC
            LIMIT 200
        """)
        rows = cur.fetchall()
    except Exception as e:
        print(f"[creative_pivot] learned_keywords failed: {e}", flush=True)
        return []

    seed_set = {_normalize(w) for w in seed_words}
    out = []
    for kw, _ in rows:
        for tok in re.findall(r"[a-z]{3,}", (kw or "").lower()):
            if tok in seed_set:
                continue
            if _looks_like_concept(tok, config) and tok not in out:
                out.append(tok)
            if len(out) >= limit:
                return out
    return out


def _live_verify_batch(candidates, cookie):
    out = {}
    try:
        import requests
    except Exception:
        return out
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    if cookie:
        headers["Cookie"] = f".ROBLOSECURITY={cookie}"
    for c in candidates:
        w = c["keyword"]
        try:
            url = ("https://catalog.roblox.com/v1/search/items/details"
                   f"?Category=12&Keyword={requests.utils.quote(w)}&Limit=30")
            r = requests.get(url, headers=headers, timeout=8)
            if r.status_code != 200:
                continue
            data = r.json()
            items = data.get("data") or []
            favs = [it.get("favoriteCount") or 0 for it in items]
            favs = [f for f in favs if f > 0]
            if not favs:
                continue
            favs.sort()
            median = favs[len(favs) // 2]
            out[w] = {
                "supply": data.get("total") or len(items),
                "median_favs": median,
            }
        except Exception:
            continue
    return out


def find_creative_pivots(seed_words, intent=None, item_type="emote",
                          cur=None, cookie=None, max_candidates=25,
                          live_verify_top_n=0):
    """
    Fan out from seed words and find GOLD / OPPORTUNITY pivots.
    Category-aware: uses item_type to pick the right buckets and filters.
    """
    config = get_category_config(item_type)
    seed_words = [_normalize(w) for w in (seed_words or []) if w]

    result = {
        "family": config["label"],
        "original": [],
        "original_all_bad": False,
        "candidates": [],
        "top_pivots": [],
        "recommendation": "",
    }
    if not seed_words or cur is None:
        return result

    seed_stats = _fetch_db_stats_batch(cur, seed_words)
    for w in seed_words:
        s = seed_stats.get(w) or {"supply": 0, "median_favs": 0}
        bucket, emoji = _classify(s["supply"], s["median_favs"])
        result["original"].append({
            "keyword": w,
            "supply": s["supply"],
            "median_favs": s["median_favs"],
            "bucket": bucket,
            "emoji": emoji,
        })

    bad = {"SATURATED", "WEAK", "DEAD", "NEUTRAL"}
    result["original_all_bad"] = all(c["bucket"] in bad for c in result["original"])

    creative_seeds = _seeds_from_creative_expand(seed_words, item_type, config, n=12)
    search_seeds = _seeds_from_search_suggestions(cur, seed_words, config, limit=25)
    learned_seeds = _seeds_from_learned_keywords(cur, seed_words, config, limit=15)

    seed_set = set(seed_words)
    combined, seen = [], set()
    for src in (creative_seeds, learned_seeds, search_seeds):
        for w in src:
            w = _normalize(w)
            if not w or w in seed_set or w in seen:
                continue
            if not _looks_like_concept(w, config):
                continue
            seen.add(w)
            combined.append(w)
    combined = combined[:max_candidates]

    if not combined:
        result["recommendation"] = (
            "No adjacent concepts found. Try a more descriptive seed or wait "
            "for more search_suggestions to accumulate."
        )
        return result

    stats = _fetch_db_stats_batch(cur, combined)
    candidates = []
    for w in combined:
        s = stats.get(w) or {"supply": 0, "median_favs": 0}
        bucket, emoji = _classify(s["supply"], s["median_favs"])
        candidates.append({
            "keyword": w,
            "supply": s["supply"],
            "median_favs": s["median_favs"],
            "median_price": s.get("median_price", 0),
            "bucket": bucket,
            "emoji": emoji,
        })
    result["candidates"] = candidates

    bucket_rank = {"GOLD": 0, "OPPORTUNITY": 1, "SATURATED": 2,
                   "NEUTRAL": 3, "WEAK": 4, "DEAD": 5}
    ranked = sorted(candidates,
                     key=lambda c: (bucket_rank[c["bucket"]], -c["median_favs"],
                                    c["supply"]))
    gold_opp = [c for c in ranked if c["bucket"] in ("GOLD", "OPPORTUNITY")]
    if gold_opp:
        top = gold_opp[:5]
    else:
        top = [c for c in ranked if c["bucket"] == "SATURATED"][:3]
        if not top:
            top = ranked[:3]
    result["top_pivots"] = top

    if not top:
        result["recommendation"] = (
            "No strong pivots found. All adjacent concepts are weak or dead."
        )
    else:
        best = top[0]
        orig_desc = ", ".join(
            f"{c['emoji']} {c['keyword']} ({c['bucket']}, supply={c['supply']})"
            for c in result["original"]
        )
        result["recommendation"] = (
            f"Original seeds: {orig_desc}. "
            f"Best creative pivot: {best['emoji']} **`{best['keyword']}`** "
            f"({best['bucket']}, supply={best['supply']}, "
            f"median_favs={best['median_favs']}). "
            f"Spans out from your seeds while avoiding the saturated tier."
        )

    if live_verify_top_n > 0 and top:
        live_results = _live_verify_batch(top[:live_verify_top_n], cookie)
        for c in top[:live_verify_top_n]:
            live = live_results.get(c["keyword"])
            if live:
                c["live_supply"] = live.get("supply")
                c["live_median_favs"] = live.get("median_favs")
                if live.get("supply") is not None and live.get("median_favs") is not None:
                    lb, le = _classify(live["supply"], live["median_favs"])
                    c["live_bucket"] = lb
                    c["live_emoji"] = le

    return result


def format_creative_pivot_report(result):
    if not result:
        return "(no creative pivot data)"

    lines = [f"# 🚀 CREATIVE PIVOT — {result.get('family', 'UGC')}\n"]

    orig = result.get("original") or []
    if orig:
        lines.append("**Original seeds:**")
        for c in orig:
            lines.append(
                f"{c['emoji']} `{c['keyword']}` — {c['bucket']} "
                f"(supply={c['supply']}, median_favs={c['median_favs']})"
            )
        lines.append("")

    if result.get("original_all_bad"):
        lines.append("⚠️ **All original seeds are saturated/weak.** Expanded search.")
        lines.append("")

    candidates = result.get("candidates") or []
    if candidates:
        order = {"GOLD": 0, "OPPORTUNITY": 1, "SATURATED": 2,
                 "NEUTRAL": 3, "WEAK": 4, "DEAD": 5}
        sc = sorted(candidates,
                     key=lambda c: (order.get(c["bucket"], 9),
                                    -c["median_favs"], c["supply"]))
        lines.append(f"**All expanded candidates ({len(candidates)} total):**")
        for c in sc[:12]:
            lines.append(
                f"{c['emoji']} `{c['keyword']}` — {c['bucket']} "
                f"· supply={c['supply']} · median_favs={c['median_favs']}"
            )
        if len(sc) > 12:
            lines.append(f"_(+{len(sc) - 12} more)_")
        lines.append("")

    top = result.get("top_pivots") or []
    if top:
        lines.append("## 🎯 TOP PIVOTS")
        for i, c in enumerate(top[:5], 1):
            live_tag = ""
            if c.get("live_bucket"):
                live_tag = f" · LIVE: {c['live_emoji']} {c['live_bucket']}"
            lines.append(
                f"**{i}. {c['emoji']} `{c['keyword']}`** — {c['bucket']} "
                f"(supply={c['supply']}, median_favs={c['median_favs']}){live_tag}"
            )
        lines.append("")

    rec = result.get("recommendation")
    if rec:
        lines.append("## 🧠 RECOMMENDATION")
        lines.append(rec)

    return "\n".join(lines)
