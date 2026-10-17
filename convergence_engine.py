"""
convergence_engine.py — category-aware niche scoring.

FIXES in this version:
- ACCESSORY FIX: "accessory" family now matches all 5 sub-types
  (43 neck, 44 shoulder, 45 front, 46 back, 47 waist).
- Multi-source keyword gathering (learned_keywords + search_suggestions).
- Family-presence gate: keyword must appear in 5+ family items, median 40+.
- Word-length floor: 5+ chars.
- 3-tier median fallback: 25 → 20 → 15 (never empty).
- Bulletproof family clause.
"""
import re
from collections import Counter
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


# ── Generic words that are NEVER niche keywords ────────────────
_GENERIC_BLOCK = {
    "the", "and", "for", "with", "you", "your", "from", "that", "this",
    "into", "over", "under", "onto", "upon", "than", "then", "them",
    "they", "there", "here", "when", "what", "where", "which", "while",
    "who", "why", "how", "all", "any", "some", "each", "every", "both",
    "other", "another", "such", "only", "very", "just", "also", "even",
    "still", "more", "most", "less", "few", "many", "much", "right",
    "left", "high", "low", "one", "two", "three", "four", "five",
    "into", "onto", "your", "yours", "ours", "theirs", "its", "his",
    "her", "she", "him", "hers", "our", "ours", "who", "whom", "whose",
    "new", "old", "best", "top", "good", "great", "cool", "nice", "cute",
    "big", "small", "hot", "cold", "fast", "slow", "bad", "hard", "easy",
    "free", "open", "real", "fake", "true", "happy", "sad", "love",
    "hate", "tiny", "huge", "mini", "max", "super", "uber", "ultra",
    "mega", "pro", "plus", "zero", "first", "last", "next", "prev",
    "young", "early", "late", "full", "half", "empty", "sweet",
    "sour", "soft", "hard", "smooth", "rough", "sharp", "dull",
    "bright", "dark", "light", "heavy", "clear", "blur", "pure",
    "point", "place", "thing", "stuff", "item", "items", "asset",
    "roblox", "ugc", "shop", "store", "buy", "sell", "sale", "price",
    "got", "get", "make", "made", "use", "used", "has", "have", "had",
    "head", "face", "hand", "foot", "arm", "leg", "body", "skin",
    "hair", "eye", "eyes", "mouth", "nose", "ear", "ears", "back",
    "side", "top", "bottom", "front", "mid", "center", "corner",
    "world", "life", "way", "days", "day", "night", "time", "hour",
    "year", "week", "month", "minute", "second",
    "style", "design", "designs", "version", "edit", "edited", "update",
    "updated", "original", "reupload", "reuploaded", "upload", "uploaded",
    "credit", "credits", "created", "made", "make", "maker",
    "cheap", "expensive", "discount", "promo", "deal",
    "popular", "trending", "trend", "trendy", "viral", "iconic", "famous",
    "adorable", "beautiful", "pretty", "lovely", "amazing", "awesome",
    "wonderful", "fantastic", "perfect", "special", "unique", "fashion",
    "styles", "styled", "designer", "creator",
}


def _family_clause(family):
    """
    Bulletproof family clause.
    Special case: "accessory" matches ALL 5 accessory sub-types.
    Otherwise accepts both naming schemes (category_configs / convergence).
    """
    if not family or family == "all":
        return "", []

    # ── ACCESSORY SPECIAL CASE: covers neck + shoulder + front + back + waist ──
    if family == "accessory":
        return " and asset_type_id in (43, 44, 45, 46, 47)", []
    # ────────────────────────────────────────────────────────────────────────

    # Direct match on FAMILIES key
    if family in FAMILIES:
        ids = FAMILIES[family]
        ph = ",".join(["%s"] * len(ids))
        return f" and asset_type_id in ({ph})", list(ids)

    # Translate from category_configs naming
    try:
        from category_configs import to_convergence_family
        translated = to_convergence_family(family)
        if translated == "accessory":
            return " and asset_type_id in (43, 44, 45, 46, 47)", []
        if translated and translated in FAMILIES:
            ids = FAMILIES[translated]
            ph = ",".join(["%s"] * len(ids))
            return f" and asset_type_id in ({ph})", list(ids)
    except Exception:
        pass

    # Unknown — no filter (better than returning nothing)
    print(f"[convergence] unknown family '{family}' — no filter", flush=True)
    return "", []


def _kw_pattern(keyword):
    kw = keyword.strip().lower()
    if " " in kw:
        return f"%{kw}%"
    return rf"\y{re.escape(kw)}\y"


def _gather_keywords(cur, family=None):
    """Multi-source gathering with family-presence filter."""
    keywords = set()

    # Source 1: learned_keywords
    try:
        cur.execute("""
            select keyword from learned_keywords
            where item_count >= 3 order by score desc limit 300
        """)
        for r in cur.fetchall():
            if r[0]:
                kw = r[0].strip().lower()
                if len(kw) >= 5 and kw not in _GENERIC_BLOCK:
                    keywords.add(kw)
    except Exception as e:
        print(f"[convergence] learned_keywords read failed: {e}", flush=True)

    # Source 2: search_suggestions tokens
    try:
        cur.execute("""
            select suggestion from search_suggestions
            where suggestion is not null
              and length(suggestion) between 5 and 40
            limit 3000
        """)
        token_counter = Counter()
        for (s,) in cur.fetchall():
            if not s:
                continue
            for t in re.findall(r"[a-z]{5,}", s.lower()):
                if t not in _GENERIC_BLOCK:
                    token_counter[t] += 1
        for t, _ in token_counter.most_common(150):
            keywords.add(t)
    except Exception as e:
        print(f"[convergence] search_suggestions read failed: {e}", flush=True)

    # Family-presence filter
    if family and family != "all":
        fam_sql, fam_params = _family_clause(family)
        if fam_sql:
            validated = set()
            for kw in keywords:
                try:
                    pat = _kw_pattern(kw)
                    is_phrase = " " in kw
                    match_op = "ilike" if is_phrase else "~*"
                    cur.execute(f"""
                        select count(*),
                               coalesce(percentile_cont(0.5) within group
                                        (order by favorite_count), 0)
                        from items
                        where name {match_op} %s and favorite_count > 5
                        {fam_sql}
                    """, [pat] + fam_params)
                    cnt, med = cur.fetchone()
                    cnt = int(cnt or 0)
                    med = float(med or 0)
                    if cnt >= 5 and med >= 40:
                        validated.add(kw)
                except Exception:
                    continue
            print(f"[convergence] family filter: {len(validated)}/{len(keywords)} pass", flush=True)
            keywords = validated

    print(f"[convergence] gathered {len(keywords)} candidate keywords", flush=True)
    return list(keywords)


def _score_keyword(cur, keyword, family=None, min_median=15, min_demand=1):
    kw_clean = (keyword or "").strip().lower()
    if not kw_clean or len(kw_clean) < 5:
        return None
    if kw_clean in _GENERIC_BLOCK:
        return None
    if " " in kw_clean:
        tokens = kw_clean.split()
        if all(t in _GENERIC_BLOCK or len(t) < 3 for t in tokens):
            return None

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

    if supply < 3:                 return None
    if supply > 500:               return None
    if median_favs > 50_000:       return None
    if median_favs < min_median:   return None

    cur.execute(
        f"select count(*) from search_suggestions where suggestion {match_op} %s",
        (pat,)
    )
    demand = cur.fetchone()[0] or 0
    if demand < min_demand:        return None

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
        select avg(delta / days) from s where delta >= 1
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
        return None

    demand_score   = min(demand / 30.0, 1.0)
    velocity_score = min(velocity / 5.0, 1.0)

    if supply <= 5:      supply_score = 0.3
    elif supply <= 15:   supply_score = 1.0
    elif supply <= 50:   supply_score = 0.8
    elif supply <= 150:  supply_score = 0.4
    else:                supply_score = 0.15

    fresh_score = (1.0 if recent == 0 else
                   0.7 if recent < 5 else
                   0.3 if recent < 15 else 0.1)
    conc_score = 1.0 - concentration

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


def scan_convergence(family=None, limit=15):
    conn = get_db(); cur = conn.cursor()
    keywords = _gather_keywords(cur, family=family)

    print(f"[convergence] scanning {len(keywords)} keywords family={family}", flush=True)

    tiers = [(25, 2, "strict"), (20, 1, "mid"), (15, 1, "loose")]

    for min_med, min_dem, label in tiers:
        results = []
        for kw in keywords:
            try:
                r = _score_keyword(cur, kw, family,
                                   min_median=min_med, min_demand=min_dem)
                if r:
                    results.append(r)
            except Exception as e:
                print(f"[convergence] {kw}: {e}", flush=True)

        print(f"[convergence] {label} tier (median>={min_med}, demand>={min_dem}): {len(results)}", flush=True)

        if len(results) >= 3:
            cur.close(); conn.close()
            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:limit]

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
