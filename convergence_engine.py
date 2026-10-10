"""
convergence_engine.py — category-aware niche scoring.
Uses ONLY existing tables. No new columns. No AI calls.
"""
from bot_core import get_db


FAMILIES = {
    "emotes":   [61, 78],
    "hats":     [8, 41],
    "face":     [42, 76, 77],
    "neck":     [43],
    "shoulder": [44],
    "front":    [45, 64],
    "back":     [46, 67],
    "waist":    [47, 69, 72],
    "shoes":    [70, 71],
    "classic":  [2, 11, 12],
    "bundle":   [79],
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

    cur.execute(f"""
        select count(*), avg(favorite_count)
        from items
        where name ilike %s and favorite_count > 5
        {fam_sql}
    """, [like] + fam_params)
    row = cur.fetchone()
    supply = row[0] or 0
    avg_favs = float(row[1] or 0)
    if supply == 0:
        return None

    cur.execute("select count(*) from search_suggestions where suggestion ilike %s", (like,))
    demand = cur.fetchone()[0] or 0

    cur.execute(f"""
        select count(*) from items
        where name ilike %s and created_at > now() - interval '14 days'
        {fam_sql}
    """, [like] + fam_params)
    recent = cur.fetchone()[0] or 0

    cur.execute(f"""
        with s as (
            select ih.item_id,
                   max(ih.favorite_count) - min(ih.favorite_count) as delta,
                   extract(epoch from (max(ih.snapshot_at) - min(ih.snapshot_at)))/86400.0 as days
            from item_history ih
            join items i on i.id = ih.item_id
            where i.name ilike %s
              and ih.snapshot_at > now() - interval '14 days'
              {fam_sql.replace('asset_type_id', 'i.asset_type_id')}
            group by ih.item_id
            having extract(epoch from (max(ih.snapshot_at) - min(ih.snapshot_at)))/86400.0 > 1
        )
        select avg(delta / days) from s
    """, [like] + fam_params)
    velocity = float(cur.fetchone()[0] or 0)

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

    demand_score   = min(demand / 30.0, 1.0)
    velocity_score = min(velocity / 5.0, 1.0)
    supply_score   = 1.0 if supply < 10 else 0.7 if supply < 50 else 0.4 if supply < 150 else 0.15
    fresh_score    = 1.0 if recent == 0 else 0.7 if recent < 5 else 0.3 if recent < 15 else 0.1
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
        "avg_favs": round(avg_favs, 1),
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
    if r["recent"] == 0 and r["supply"] < 30 and r["velocity"] > 1:
        zone = " 🔥 **SNIPE ZONE**"
    elif r["velocity"] > 3 and r["recent"] < 5:
        zone = " ⚡ **RISING**"
    elif r["supply"] > 200 or r["concentration"] > 0.5:
        zone = " 💀 **SATURATED**"
    elif r["velocity"] < 0.3 and r["demand"] < 5:
        zone = " 🪦 **DEAD**"

    fam = f" · `{r['family']}`" if r.get("family") and r["family"] != "all" else ""
    return (
        f"**🎯 `{r['keyword']}`{fam} — [{r['score']}]**{zone}\n"
        f"  📈 demand {r['demand']} · ⚡ vel {r['velocity']}/d · "
        f"📦 supply {r['supply']} · 🆕 recent {r['recent']} · "
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
            if r and r["supply"] <= 500:
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
