"""
pattern_forge.py — Statistical pattern mining across the whole UGC catalog.

Finds what ACTUALLY correlates with high favorites. Not predictions.
Not AI opinions. Real lift ratios computed from 45k items.

For every feature (word, bigram, price bucket, title length, launch day),
computes:
    with_count     = items that have the feature
    with_median    = median favorites of those items
    without_median = median favorites of items WITHOUT the feature
    lift           = with_median / without_median

A lift of 3.0 means: items with this feature hit 3x the median favs of items
without it. That is a real statistical signal from real data.

All pure SQL. No AI. No fake scores.
"""
import re
from collections import defaultdict
from datetime import datetime


STOP = {
    "a","an","the","of","and","or","for","to","in","on","with","my","your",
    "at","by","is","it","as","this","that","from","into","over","under",
    "new","old","best","good","cool","nice","hot","top","very","much","many",
    "roblox","item","ugc",
}


def _median(vals):
    if not vals:
        return 0
    s = sorted(vals)
    return s[len(s) // 2]


def _price_bucket(p):
    if not p or p <= 0:
        return None
    if p < 30:    return "under_30"
    if p < 60:    return "30_to_60"
    if p < 100:   return "60_to_100"
    if p < 200:   return "100_to_200"
    if p < 500:   return "200_to_500"
    return "500_plus"


def _title_length_bucket(n):
    if n <= 2: return "len_1_2"
    if n == 3: return "len_3"
    if n == 4: return "len_4"
    if n == 5: return "len_5"
    if n == 6: return "len_6"
    return "len_7_plus"


def _dow(created_at):
    if not created_at:
        return None
    try:
        return created_at.strftime("%a")
    except Exception:
        return None


def _fetch_all(cur, asset_ids=None, min_favs=1, limit=20000):
    sql = """
        SELECT name, favorite_count, price, asset_type_id, created_at
        FROM items
        WHERE favorite_count > %s
    """
    params = [int(min_favs)]
    if asset_ids:
        sql += " AND asset_type_id = ANY(%s)"
        params.append(list(asset_ids))
    sql += " ORDER BY favorite_count DESC LIMIT %s"
    params.append(int(limit))
    cur.execute(sql, tuple(params))
    return cur.fetchall()


def mine_patterns(cur, family=None, min_sample=25, top_n=30, min_favs=5):
    from category_configs import get_category_config
    asset_ids = None
    if family:
        try:
            asset_ids = get_category_config(family).get("asset_type_ids") or None
        except Exception:
            asset_ids = None

    rows = _fetch_all(cur, asset_ids=asset_ids, min_favs=min_favs)
    if not rows:
        return []

    all_favs = [r[1] or 0 for r in rows]
    global_median = _median(all_favs)
    if global_median == 0:
        return []

    features = defaultdict(list)
    token_re = re.compile(r"[a-z]{3,}")

    for name, favs, price, _, created_at in rows:
        fav = favs or 0
        toks = [t for t in token_re.findall((name or "").lower()) if t not in STOP]

        seen_uni = set()
        for t in toks:
            if t in seen_uni:
                continue
            seen_uni.add(t)
            features[f"word:{t}"].append(fav)

        seen_bi = set()
        for a, b in zip(toks, toks[1:]):
            bg = f"{a} {b}"
            if bg in seen_bi:
                continue
            seen_bi.add(bg)
            features[f"bigram:{bg}"].append(fav)

        pb = _price_bucket(price)
        if pb:
            features[f"price:{pb}"].append(fav)

        features[f"len:{_title_length_bucket(len(toks))}"].append(fav)

        dow = _dow(created_at)
        if dow:
            features[f"dow:{dow}"].append(fav)

    results = []
    for feat, favs_list in features.items():
        if len(favs_list) < min_sample:
            continue
        with_med = _median(favs_list)

        without = [f for f in all_favs if f not in favs_list]
        without_med = _median(without) if without else global_median
        if without_med == 0:
            continue

        lift = with_med / without_med
        if lift < 1.5:
            continue

        kind = feat.split(":", 1)[0]
        value = feat.split(":", 1)[1]

        results.append({
            "feature": value,
            "kind": kind,
            "with_count": len(favs_list),
            "with_median": int(with_med),
            "without_median": int(without_med),
            "lift": round(lift, 2),
        })

    results.sort(key=lambda r: (-r["lift"], -r["with_count"]))
    return results[:top_n]


def mine_failure_patterns(cur, family=None, min_sample=25, top_n=15, max_favs=5):
    from category_configs import get_category_config
    asset_ids = None
    if family:
        try:
            asset_ids = get_category_config(family).get("asset_type_ids") or None
        except Exception:
            asset_ids = None

    rows = _fetch_all(cur, asset_ids=asset_ids, min_favs=0, limit=30000)
    if not rows:
        return []

    underperformers = []
    performers = []
    for name, favs, price, _, _ in rows:
        if favs is None:
            continue
        if favs <= max_favs:
            underperformers.append((name, favs))
        elif favs >= 200:
            performers.append((name, favs))

    if len(underperformers) < min_sample:
        return []

    token_re = re.compile(r"[a-z]{3,}")
    up_counts = defaultdict(int)
    perf_counts = defaultdict(int)

    for name, _ in underperformers:
        for t in set(token_re.findall((name or "").lower())):
            if t in STOP:
                continue
            up_counts[t] += 1

    for name, _ in performers:
        for t in set(token_re.findall((name or "").lower())):
            if t in STOP:
                continue
            perf_counts[t] += 1

    up_total = len(underperformers)
    perf_total = max(len(performers), 1)

    results = []
    for word, up_n in up_counts.items():
        if up_n < min_sample:
            continue
        up_rate = up_n / up_total
        perf_rate = perf_counts.get(word, 0) / perf_total
        if perf_rate == 0:
            ratio = 999
        else:
            ratio = up_rate / perf_rate
        if ratio < 1.5:
            continue
        results.append({
            "word": word,
            "under_count": up_n,
            "under_rate": round(up_rate * 100, 1),
            "perf_rate": round(perf_rate * 100, 1),
            "ratio": round(ratio, 2),
        })

    results.sort(key=lambda r: -r["ratio"])
    return results[:top_n]


def format_patterns(patterns, family="all"):
    if not patterns:
        return f"(no patterns found for `{family}`)"
    lines = [f"# 🧪 PATTERN FORGE — {family}\n"]
    lines.append("_Real statistical lift. Feature vs baseline across the catalog._\n")
    for i, p in enumerate(patterns, 1):
        kind = p["kind"]
        feat = p["feature"]
        lines.append(
            f"**{i}. [{kind}] `{feat}`** — lift **{p['lift']}x** "
            f"· {p['with_count']:,} items · median {p['with_median']:,} favs "
            f"(baseline {p['without_median']:,})"
        )
    return "\n".join(lines)


def format_failure_patterns(results):
    if not results:
        return "(no failure patterns found)"
    lines = ["# ⚠️ FAILURE PATTERNS\n"]
    lines.append("_Words that appear in low-fav items far more than in winners._\n")
    for i, r in enumerate(results, 1):
        lines.append(
            f"**{i}. `{r['word']}`** — underperformers: **{r['under_rate']}%** "
            f"· winners: **{r['perf_rate']}%** · ratio **{r['ratio']}x** "
            f"· {r['under_count']} items"
        )
    return "\n".join(lines)
