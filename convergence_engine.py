"""
convergence_engine.py — category-aware niche scoring.
Uses ONLY existing tables. No new columns. No AI calls.

FIXES APPLIED:
- Uses MEDIAN not MEAN for favs (kills mega-item contamination)
- Clamps velocity to 30/day (kills snapshot artifact spikes)
- Requires >= 2 day snapshot span (kills 1-day noise)
- Rejects monopolies (supply < 5)
- Rejects saturated zones (supply > 500)
- Rejects legacy/OG mega-items (median favs > 50k)
- Rejects dead niches (median favs < 3)
- Supply sweet spot: 5-50 gets highest score
"""
from bot_core import get_db


# ── Asset type families — mapped to REAL asset_type_ids in DB ──────
# Distribution (from actual DB counts):
#   61    → 11,960  (EmoteAnimation)
#   8/41  → 13,693  (Hat + HairAccessory)
#   42    → 3,391   (FaceAccessory)  [+76/77 rare]
#   43    → 1,794   (NeckAccessory)
#   44    → 4,295   (ShoulderAccessory)
#   45/64 → 3,455   (FrontAccessory + TShirtAccessory)
#   46/67 → 4,893   (BackAccessory + JacketAccessory)
#   47/69/72 → 3,412 (Waist + Shorts + DressSkirt)
#   65/66/68 → 4,403 (Shirt + Pants + Sweater layered)
#   2/11/12  → 12,044 (Classic T-Shirt/Shirt/Pants)
#   19    → 199     (Gear)
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


def _family_clause(family):
    if not family or family == "all":
        return "", []
    ids = FAMILIES.get(family)
    if not ids:
        return " and false", []
    placeholders = ",".join(["%s"] * len(ids))
    return f" and asset_type_id in ({placeholders})", list(ids)


def _score_keyword(cur, keyword, family=None):
    like = f'%{keyword}%'
    fam_sql, fam_params = _family_clause(family)

    # ── SUPPLY + MEDIAN FAVS (not mean!) + p90 distribution ─────
    cur.execute(f"""
        select count(*),
               coalesce(percentile_cont(0.5) within group
                        (order by favorite_count), 0) as median_favs,
               coalesce(percentile_cont(0.9) within group
                        (order by favorite_count), 0) as p90_favs
        from items
        where name ilike %s and favorite_count > 5
        {fam_sql}
    """, [like] + fam_params)
    row = cur.fetchone()
    supply = row[0] or 0
    median_favs = float(row[1] or 0)
    p90_favs = float(row[2] or 0)

    # ── NICHE GATEKEEPER: must be a real market, not 1-2 OG items ──
    if supply < 5:
        return None                              # monopoly, not a niche
    if supply > 500:
        return None                              # saturated beyond entry
    if median_favs > 50_000:
        return None                              # legacy/OG megaitem
    if median_favs < 3:
        return None                              # dead niche

    # ── DEMAND (global) ──────────────────────────────────────────
    cur.execute(
        "select count(*) from search_suggestions where suggestion ilike %s",
        (like,)
    )
    demand = cur.fetchone()[0] or 0

    # ── FRESHNESS ────────────────────────────────────────────────
    cur.execute(f"""
        select count(*) from items
        where name ilike %s and created_at > now() - interval '14 days'
        {fam_sql}
    """, [like] + fam_params)
    recent = cur.fetchone()[0] or 0

    # ── VELOCITY (median, requires 2-day span, clamped) ──────────
    cur.execute(f"""
        with s as (
            select ih.item_id,
                   max(ih.favorite_count) - min(ih.favorite_count) as delta,
                   extract(epoch from
                       (max(ih.snapshot_at) - min(ih.snapshot_at))
                   )/86400.0 as days
            from item_history ih
            join items i on i.id = ih.item_id
            where i.name ilike %s
              and ih.snapshot_at > now() - interval '14 days'
              {fam_sql.replace('asset_type_id', 'i.asset_type_id')}
            group by ih.item_id
            having extract(epoch from
                   (max(ih.snapshot_at) - min(ih.snapshot_at))
                   )/86400.0 >= 2
        )
        select coalesce(percentile_cont(0.5) within group
                        (order by delta / days), 0)
        from s
    """, [like] + fam_params)
    velocity = float(cur.fetchone()[0] or 0)

    # Clamp — anything over 30/day is snapshot noise, not real growth
    velocity = min(velocity, 30.0)

    # ── CONCENTRATION ────────────────────────────────────────────
    cur.execute(f"""
        with cf as (
            select creator_name, sum(favorite_count) as favs
            from items
            where name ilike %s and favorite_count > 5
            {fam_sql}
            group by creator_name
        )
        select sum(favs), max(favs) from cf
    """, [like] + fam_params)
    crow = cur.fetchone()
    total_favs = float(crow[0] or 0)
    top_favs = float(crow[1] or 0)
    concentration = (top_favs / total_favs) if total_favs else 0.0

    # ── SCORE COMPONENTS ─────────────────────────────────────────
    demand_score   = min(demand / 30.0, 1.0)
    velocity_score = min(velocity / 5.0, 1.0)

    # Supply sweet spot: 5-50. Less = too thin. More = too crowded.
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
        "avg_favs": round(median_favs, 1),  # kept key name for compatibility
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
    cur.execute("""
        select keyword from learned_keywords
        where item_count >= 3 order by score desc limit 200
    """)
    keywords = [r[0] for r in cur.fetchall()]

    results = []
    for kw in keywords:
        try:
            r = _score_keyword(cur, kw, family)
            if r:                       # gatekeeper already filtered
                results.append(r)
        except Exception:
            continue

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
