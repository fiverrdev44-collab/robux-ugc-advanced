"""
pattern_forge.py — Statistical pattern mining across the UGC catalog.

Finds associations between an item-level feature (word, bigram, price bucket,
title length, launch day) and favorite counts. It is explicitly observational:
no causal claims, no probability estimates, and no AI.

For every feature:
    with_ids       = item IDs that have the feature
    without_ids    = item IDs that do not have the feature
    with_median    = median favorites of with_ids
    without_median = median favorites of the comparison group

Comparison group:
  * prefer non-featured items in the same (category, age bucket, price bucket)
    stratum;
  * fall back to the same category;
  * fall back to the global non-featured pool, with the scope reported.

Favorite counts are observed marketplace values. They are not sales, demand,
CTR, or revenue. Missing favorites stay missing and are excluded.
"""
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone


STOP = {
    "a", "an", "the", "of", "and", "or", "for", "to", "in", "on", "with",
    "my", "your", "at", "by", "is", "it", "as", "this", "that", "from",
    "into", "over", "under", "new", "old", "best", "good", "cool", "nice",
    "hot", "top", "very", "much", "many", "roblox", "item", "ugc",
}


def _median(vals):
    """True median (average of the two middle values for even samples)."""
    s = sorted(v for v in vals if v is not None)
    if not s:
        return 0
    n = len(s)
    if n % 2:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2.0


def _price_bucket(p):
    if p is None or p <= 0:
        return "price_unknown"
    if p < 30:
        return "under_30"
    if p < 60:
        return "30_to_60"
    if p < 100:
        return "60_to_100"
    if p < 200:
        return "100_to_200"
    if p < 500:
        return "200_to_500"
    return "500_plus"


def _title_length_bucket(n):
    if n <= 2:
        return "len_1_2"
    if n == 3:
        return "len_3"
    if n == 4:
        return "len_4"
    if n == 5:
        return "len_5"
    if n == 6:
        return "len_6"
    return "len_7_plus"


def _age_bucket(age_days):
    if age_days is None:
        return "age_unknown"
    if age_days < 30:
        return "age_0_30"
    if age_days < 90:
        return "age_30_90"
    if age_days < 180:
        return "age_90_180"
    if age_days < 365:
        return "age_180_365"
    return "age_365_plus"


def _dow(created_at):
    if not created_at:
        return None
    try:
        return created_at.strftime("%a")
    except Exception:
        return None


def _age_days(created_at, now):
    if created_at is None or now is None:
        return None
    try:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return (now - created_at).total_seconds() / 86400.0
    except Exception:
        return None


def _fetch_all(cur, asset_ids=None, min_favs=0, limit=20000):
    sql = """
        SELECT id, name, favorite_count, price, asset_type_id, created_at,
               creator_name
        FROM items
        WHERE favorite_count >= %s
    """
    params = [int(min_favs)]
    if asset_ids:
        sql += " AND asset_type_id = ANY(%s)"
        params.append(list(asset_ids))
    sql += " ORDER BY favorite_count DESC LIMIT %s"
    params.append(int(limit))
    cur.execute(sql, tuple(params))
    return cur.fetchall()


def mine_patterns(cur, family=None, min_sample=25, top_n=30, min_favs=5,
                  now=None):
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

    now = now or datetime.now(timezone.utc)
    items = []
    for (item_id, name, favs, price, asset_type, created_at,
         creator_name) in rows:
        if favs is None:
            continue  # missing values stay missing
        age = _age_days(created_at, now)
        items.append({
            "id": item_id,
            "name": name or "",
            "favs": int(favs),
            "price": price,
            "category": asset_type,
            "age": age,
            "created_at": created_at,
            "stratum": (asset_type, _age_bucket(age), _price_bucket(price)),
            "creator": (creator_name or "").strip().lower(),
        })
    if not items:
        return []

    all_ids = {it["id"] for it in items}
    fav_by_id = {it["id"]: it["favs"] for it in items}
    stratum_by_id = {it["id"]: it["stratum"] for it in items}
    category_by_id = {it["id"]: it["category"] for it in items}
    creator_by_id = {it["id"]: it["creator"] for it in items}

    features = defaultdict(set)
    token_re = re.compile(r"[a-z]{3,}")
    for it in items:
        toks = [t for t in token_re.findall(it["name"].lower())
                if t not in STOP]
        for tok in set(toks):
            features[f"word:{tok}"].add(it["id"])
        for a, b in set(zip(toks, toks[1:])):
            features[f"bigram:{a} {b}"].add(it["id"])
        features[f"price:{_price_bucket(it['price'])}"].add(it["id"])
        features[f"len:{_title_length_bucket(len(toks))}"].add(it["id"])
        dow = _dow(it.get("created_at"))
        if dow:
            features[f"dow:{dow}"].add(it["id"])

    results = []
    for feat, with_ids in features.items():
        if len(with_ids) < min_sample:
            continue
        without_ids = all_ids - with_ids
        if len(without_ids) < min_sample:
            continue

        featured_strata = {stratum_by_id[i] for i in with_ids}
        featured_categories = {category_by_id[i] for i in with_ids}
        scope = "global"
        compare_ids = [
            i for i in without_ids if stratum_by_id[i] in featured_strata]
        if len(compare_ids) >= min_sample:
            scope = "same_category_price_age"
        else:
            compare_ids = [
                i for i in without_ids
                if category_by_id[i] in featured_categories]
            if len(compare_ids) >= min_sample:
                scope = "same_category"
            else:
                compare_ids = list(without_ids)

        with_median = _median([fav_by_id[i] for i in with_ids])
        without_median = _median([fav_by_id[i] for i in compare_ids])
        if without_median <= 0:
            continue
        lift = with_median / without_median
        if lift < 1.5:
            continue

        creators = Counter(creator_by_id[i] for i in with_ids
                           if creator_by_id[i])
        concentration = (max(creators.values()) / len(with_ids)
                         if creators else 0.0)
        kind, value = feat.split(":", 1)
        results.append({
            "feature": value,
            "kind": kind,
            "with_count": len(with_ids),
            "without_count": len(compare_ids),
            "with_median": round(with_median, 1),
            "without_median": round(without_median, 1),
            "lift": round(lift, 2),
            "comparison_scope": scope,
            "creator_concentration": round(concentration, 2),
            "single_creator_dominated": concentration > 0.5,
            "metric": "favorites",
            "causal": False,
        })

    results.sort(key=lambda r: (-r["lift"], -r["with_count"]))
    return results[:top_n]


def mine_failure_patterns(cur, family=None, min_sample=25, top_n=15,
                          max_favs=5):
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
    for (item_id, name, favs, price, asset_type, created_at,
         creator_name) in rows:
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
        ratio = 999 if perf_rate == 0 else up_rate / perf_rate
        if ratio < 1.5:
            continue
        results.append({
            "word": word,
            "under_count": up_n,
            "under_rate": round(up_rate * 100, 1),
            "perf_rate": round(perf_rate * 100, 1),
            "ratio": round(ratio, 2),
            "comparison": "low-favorite vs high-favorite items (selection-biased)",
            "causal": False,
        })

    results.sort(key=lambda r: -r["ratio"])
    return results[:top_n]


def format_patterns(patterns, family="all"):
    if not patterns:
        return f"(no patterns found for `{family}`)"
    lines = [f"# 🧪 PATTERN FORGE — {family}\n"]
    lines.append("_Observational association with favorites — not sales, "
                 "demand, or causal effects._\n")
    for i, p in enumerate(patterns, 1):
        scope = p.get("comparison_scope", "global")
        conc = p.get("creator_concentration", 0)
        flag = " · ⚠️ creator-concentrated" if p.get(
            "single_creator_dominated") else ""
        lines.append(
            f"**{i}. [{p['kind']}] `{p['feature']}`** — lift **{p['lift']}x** "
            f"· {p['with_count']:,} with / {p.get('without_count', 0):,} "
            f"comparison items · median {p['with_median']:,} vs "
            f"{p['without_median']:,} favs · scope `{scope}` · "
            f"creator share {int(conc * 100)}%{flag}"
        )
    return "\n".join(lines)


def format_failure_patterns(results):
    if not results:
        return "(no failure patterns found)"
    lines = ["# ⚠️ FAILURE PATTERNS\n"]
    lines.append("_Associations in a selection-biased comparison "
                 "(low-favorite vs high-favorite items); not causal._\n")
    for i, r in enumerate(results, 1):
        lines.append(
            f"**{i}. `{r['word']}`** — underperformers: **{r['under_rate']}%** "
            f"· winners: **{r['perf_rate']}%** · ratio **{r['ratio']}x** "
            f"· {r['under_count']} items"
        )
    return "\n".join(lines)
