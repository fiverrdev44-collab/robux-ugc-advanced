"""
convergence_engine.py — category-aware niche scoring.
Uses ONLY existing tables. No new columns. No AI calls.

FIXES in this version:
- Bulletproof family clause: if the family name is already a FAMILIES
  key, use it directly. Only translate if it's a category_configs name.
  This prevents "emotes" → None → "and false" from killing all queries.
- Debug prints on gate rejections (first 5 per tier).
"""
import re
from bot_core import get_db


FAMILIES = {
    "emotes":   [61],
    "hair":     [8, 41],
    "face":     [42, 76, 77],
    "neck":     [43],
    "shoulder": [44],
    "front":    [45, 64],
    "back":     [46, 67],
    "waist":    [47, 69, 72],
    "tops":     [65, 66, 68],
    "classic":  [2, 11, 12],
    "gear":     [19],
}

ASSET_TO_FAMILY = {}
for fam, ids in FAMILIES.items():
    for aid in ids:
        ASSET_TO_FAMILY[aid] = fam


_GENERIC_BLOCK = {
    "the", "and", "for", "with", "you", "your", "from", "that", "this",
    "into", "over", "under", "onto", "upon", "than", "then", "them",
    "they", "there", "here", "when", "what", "where", "which", "while",
    "who", "why", "how", "all", "any", "some", "each", "every", "both",
    "other", "another", "such", "only", "very", "just", "also", "even",
    "still", "more", "most", "less", "few", "many", "much",
    "new", "old", "best", "top", "good", "great", "cool", "nice", "cute",
    "big", "small", "hot", "cold", "fast", "slow", "high", "low",
    "bad", "hard", "easy", "free", "open", "real", "fake", "true",
    "happy", "sad", "love", "hate",
    "point", "place", "thing", "stuff", "item", "items", "asset",
    "roblox", "ugc", "shop", "store", "buy", "sell", "sale", "price",
    "got", "get", "make", "made", "use", "used", "has", "have", "had",
    "one", "two", "three", "four", "five",
    "style", "design", "designs", "version", "edit", "edited", "update",
    "updated", "original", "reupload", "reuploaded", "upload", "uploaded",
    "credit", "credits", "created",
    "cheap", "expensive", "discount", "promo", "deal",
    "popular", "trending", "trend", "trendy", "viral", "iconic", "famous",
}


def _family_clause(family):
    """
    Bulletproof:
      1. If family is already a FAMILIES key, use it directly.
      2. Else try to translate from category_configs naming.
      3. If nothing works, return "and false" (no filter).
    """
    if not family or family == "all":
        return "", []

    # Step 1: already a valid convergence_engine family name?
    if family in FAMILIES:
        ids = FAMILIES[family]
        placeholders = ",".join(["%s"] * len(ids))
        return f" and asset_type_id in ({placeholders})", list(ids)

    # Step 2: try translating from category_configs naming scheme
    try:
        from category_configs import to_convergence_family
        translated = to_convergence_family(family)
        if translated and translated in FAMILIES:
            ids = FAMILIES[translated]
            placeholders = ",".join(["%s"] * len(ids))
            return f" and asset_type_id in ({placeholders})", list(ids)
    except Exception as e:
        print(f"[convergence] family translate failed: {e}", flush=True)

    # Step 3: unknown family — no filter instead of "and false"
    # (safer: gives results instead of silently empty)
    print(f"[convergence] unknown family '{family}' — no filter", flush=True)
    return "", []


def _kw_pattern(keyword):
    kw = keyword.strip().lower()
    if " " in kw:
        return f"%{kw}%"
    return rf"\y{re.escape(kw)}\y"


def _score_keyword(cur, keyword, family=None, min_median=15, min_demand=1,
                   debug=False):
    """Returns dict on pass, None on reject. If debug=True, prints why."""
    def _reject(reason):
        if debug:
            print(f"[conv-debug] '{keyword}' REJECTED: {reason}", flush=True)
        return None

    kw_clean = (keyword or "").strip().lower()
    if not kw_clean or len(kw_clean) < 3:
        return _reject(f"too short ({kw_clean!r})")
    if kw_clean in _GENERIC_BLOCK:
        return _reject("blocklist")
    if " " in kw_clean:
        tokens = kw_clean.split()
        if all(t in _GENERIC_BLOCK or len(t) < 3 for t in tokens):
            return _reject("all tokens blocked")

    pat = _kw_pattern(keyword)
    is_phrase = " " in keyword.strip()
    use_regex = not is_phrase

    fam_sql, fam_params = _family_clause(family)
    match_op = "~*" if use_regex else "ilike"

    cur.execute(f"""
        select count(*),
               coalesce(percentile_cont(0.5) within group
                        (order by favorite_count), 0),
               coalesce(percentile_cont(0.9) within group
                        (order by favorite_count), 0)
        from items
        where name {match_op} %s and favorite_count > 5
        {fam_sql}
    """, [pat] + fam_params)
    row = cur.fetchone()
    supply = row[0] or 0
    median_favs = float(row[1] or 0)
    p90_favs = float(row[2] or 0)

    if supply < 3:                return _reject(f"supply {supply} < 3")
    if supply > 500:              return _reject(f"supply {supply} > 500")
    if median_favs > 50_000:      return _reject(f"median {median_favs} > 50k")
    if median_favs < min_median:  return _reject(f"median {median_favs} < {min_median}")

    cur.execute(
        f"select count(*) from search_suggestions where suggestion {match_op} %s",
        (pat,)
    )
    demand = cur.fetchone()[0] or 0

    if demand < min_demand:       return _reject(f"demand {demand} < {min_demand}")

    cur.execute(f"""
        select count(*) from items
        where name {match_op} %s and created_at > now() - interval '14 days'
        {fam_sql}
    """, [pat] + fam_params)
    recent = cur.fetchone()[0] or 0

    cur.execute(f"""
        with s as (
            select ih.item_id,
                   max(ih.favorite_count) - min(ih.favorite_count) as delta,
                   extract(epoch from
                       (max(ih.snapshot_at) - min(ih.snapshot_at))
                   )/86400.0 as days
            from item_history ih
            join items i on i.id = ih.item_id
            where i.name {match_op} %s
              and ih.snapshot_at > now() - interval '14 days'
              {fam_sql.replace('asset_type_id', 'i.asset_type_id')}
            group by ih.item_id
            having extract(epoch from
                   (max(ih.snapshot_at) - min(ih.snapshot_at))
                   )/86400.0 >= 2
        )
        select avg(delta / days) from s
        where delta >= 1
    """, [pat] + fam_params)
    velocity = float(cur.fetchone()[0] or 0)
    velocity = min(velocity, 20.0)

    cur.execute(f"""
        with cf as (
            select creator_name, sum(favorite_count) as favs
            from items
            where name {match_op} %s and favorite_count > 5
            {fam_sql}
            group by creator_name
        )
        select sum(favs), max(favs) from cf
    """, [pat] + fam_params)
    crow = cur.fetchone()
    total_favs = float(crow[0] or 0)
    top_favs = float(crow[1] or 0)
    concentration = (top_favs / total_favs) if total_favs else 0.0

    if concentration > 0.65:
        return _reject(f"concentration {concentration:.2f} > 0.65")

    demand_score   = min(demand / 30.0, 1.0)
    velocity_score = min(velocity / 5.0, 1.0)

    if supply <= 5:      supply_score = 0.3
    elif supply <= 15:   supply_score = 1.0
    elif supply <= 50:   supply_score = 0.8
    elif supply <= 150:  supply_score = 0.4
    else:                supply_score = 0.15

    fresh_score    = (1.0 if recent == 0 else
                      0.7 if recent < 5 else
                      0.3 if recent < 15 else 0.1)
    conc_score     = 1.0 - concentration

    score = (demand_score * 25 + velocity_score * 25 +
             supply_score * 20 + fresh_score * 20 + conc_score * 10)

    return {
        "keyword": keyword,
        "family": family or "all",
        "score": round(score, 1),
        "demand": demand,
        "velocity": round(velocity, 2),
        "supply": supply,
        "recent": recent,
        "avg_favs": round(median_favs, 1),
        "p90_favs": round(p90_favs, 1),
        "concentration": round(concentration, 2),
    }


def score_keyword(keyword, family=None):
    conn = get_db(); cur = conn.cursor()
    try:
        return _score_keyword(cur, keyword, family)
    finally:
        cur.close(); conn.close()


def family_for_asset(asset_type_id):
    return ASSET_TO_FAMILY.get(asset_type_id)


def format_brief(r):
    if r is None:
        return "⚠️ *No items found in this category — no signal.*"

    zone = ""
    if r["recent"] == 0 and 5 <= r["supply"] <= 30 and r["velocity"] > 1:
        zone = " 🔥 **SNIPE ZONE**"
    elif r["velocity"] > 3 and r["recent"] < 5:
        zone = " ⚡ **RISING**"
    elif r["supply"] > 200 or r["concentration"] > 0.5:
        zone = " 💀 **SATURATED**"
    elif r["velocity"] < 0.3 and r["demand"] < 5:
        zone = " 🪦 **DEAD**"

    fam = (f" · `{r['family']}`"
           if r.get("family") and r["family"] != "all" else "")
    return (
        f"**🎯 `{r['keyword']}`{fam} — [{r['score']}]**{zone}\n"
        f"  📈 demand {r['demand']} · ⚡ vel {r['velocity']}/d · "
        f"📦 supply {r['supply']} · 🆕 recent {r['recent']} · "
        f"🎯 median {r['avg_favs']}♥ · "
        f"👑 top {int(r['concentration']*100)}%"
    )


def scan_convergence(family=None, limit=15, debug=False):
    """Single-pass scan with min_median=15, min_demand=1."""
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        select keyword from learned_keywords
        where item_count >= 3 order by score desc limit 200
    """)
    keywords = [
        r[0] for r in cur.fetchall()
        if r[0] and len(r[0].strip()) >= 3
    ]

    print(f"[convergence] scanning {len(keywords)} keywords family={family}", flush=True)

    results = []
    for i, kw in enumerate(keywords):
        try:
            # Debug first 5 rejects only
            show_debug = debug and i < 5 and len(results) < 3
            r = _score_keyword(cur, kw, family,
                               min_median=15, min_demand=1,
                               debug=show_debug)
            if r:
                results.append(r)
        except Exception as e:
            print(f"[convergence] {kw}: {e}", flush=True)

    print(f"[convergence] total results: {len(results)}", flush=True)

    cur.close(); conn.close()
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def scan_all_families(limit_each=5):
    out = {}
    for fam in FAMILIES.keys():
        try:
            out[fam] = scan_convergence(family=fam, limit=limit_each)
        except Exception:
            out[fam] = []
    return out
