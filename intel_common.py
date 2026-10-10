"""
intel_common.py — shared intelligence layer.
Used by !brainstorm, !autopsy, !verdict, !converge.
Single source of truth for:
  - keyword classification (SATURATED / GOLD / etc.)
  - percentile ranking vs category peers
  - portfolio context (your winners, your losers)
"""
from bot_core import get_db
from convergence_engine import ASSET_TO_FAMILY, FAMILIES


# ── Shared classification thresholds — one place, one truth ──
def classify_keyword(cur, keyword, family=None):
    """
    Returns dict with classification fields used EVERYWHERE.
    No more contradictions between modules.
    """
    like = f'%{keyword}%'
    fam_sql, fam_params = _family_clause(family)

    cur.execute(f"""
        select count(*),
               percentile_cont(0.5) within group (order by favorite_count)
        from items
        where name ilike %s and favorite_count > 5
        {fam_sql}
    """, [like] + fam_params)
    row = cur.fetchone()
    supply = row[0] or 0
    median_favs = float(row[1] or 0)

    cur.execute(
        "select count(*) from search_suggestions where suggestion ilike %s",
        (like,)
    )
    demand = cur.fetchone()[0] or 0

    # ── SHARED CLASSIFICATION — no disagreement ──
    if supply == 0 and demand == 0:
        bucket = "GHOST"
    elif supply == 0:
        bucket = "VIRGIN"        # demand but no items — pure gold
    elif supply < 20 and demand >= 10:
        bucket = "GOLD"
    elif supply < 60 and median_favs >= 50:
        bucket = "OPPORTUNITY"
    elif supply > 200 or median_favs < 15:
        bucket = "SATURATED"
    else:
        bucket = "NEUTRAL"

    return {
        "keyword": keyword,
        "family": family,
        "supply": supply,
        "median_favs": round(median_favs, 1),
        "demand": demand,
        "bucket": bucket,
    }


def _family_clause(family):
    if not family or family == "all":
        return "", []
    ids = FAMILIES.get(family)
    if not ids:
        return " and false", []
    ph = ",".join(["%s"] * len(ids))
    return f" and asset_type_id in ({ph})", list(ids)


# ── Percentile rank — how good is THIS item vs peers? ──
def item_percentile(cur, item_id):
    """
    Returns (percentile, sample_size, velocity, family, age_days).
    percentile: 0-100, higher = better. Real benchmark, not vibes.
    """
    cur.execute("""
        select i.asset_type_id,
               i.favorite_count,
               extract(epoch from (now() - i.created_at))/86400.0
        from items i where i.id = %s
    """, (item_id,))
    row = cur.fetchone()
    if not row:
        return None

    asset_type_id, favs, age_days = row
    age_days = max(float(age_days or 1), 1)
    velocity = float(favs) / age_days
    family = ASSET_TO_FAMILY.get(asset_type_id, "other")

    fam_ids = [a for a, f in ASSET_TO_FAMILY.items() if f == family]
    if not fam_ids:
        return {
            "percentile": 50.0, "sample_size": 0,
            "velocity": round(velocity, 2),
            "family": family, "age_days": round(age_days, 1),
        }

    ph = ",".join(["%s"] * len(fam_ids))
    cur.execute(f"""
        with peers as (
            select favorite_count::float /
                   greatest(
                     extract(epoch from (now() - created_at))/86400.0, 1
                   ) as v
            from items
            where asset_type_id in ({ph})
              and favorite_count > 5
              and created_at > now() - interval '120 days'
        )
        select
          count(*) filter (where v < %s) * 100.0 / greatest(count(*), 1),
          count(*)
        from peers
    """, fam_ids + [velocity])
    pctile, sample_size = cur.fetchone()

    return {
        "percentile": round(float(pctile or 0), 1),
        "sample_size": sample_size or 0,
        "velocity": round(velocity, 2),
        "family": family,
        "age_days": round(age_days, 1),
    }


# ── Portfolio context — your winners shape every recommendation ──
def portfolio_context(cur, top_n=5):
    """
    Returns your top-N items by velocity. Injected into brainstorm prompts
    so AI output is stylistically consistent with what already works for you.
    """
    cur.execute("""
        select i.id, i.name, i.favorite_count, i.asset_type_id,
               extract(epoch from (now() - i.created_at))/86400.0 as age_days
        from items i
        join my_portfolio mp on mp.item_id = i.id
        where i.favorite_count > 0
    """)
    rows = cur.fetchall()
    if not rows:
        return {"winners": [], "avg_velocity": 0, "count": 0}

    scored = []
    for iid, name, favs, atid, age in rows:
        age = max(float(age or 1), 1)
        v = float(favs) / age
        fam = ASSET_TO_FAMILY.get(atid, "other")
        scored.append({
            "id": iid, "name": name, "favs": favs,
            "velocity": round(v, 2), "family": fam,
        })

    scored.sort(key=lambda x: x["velocity"], reverse=True)
    avg_v = sum(s["velocity"] for s in scored) / len(scored)
    return {
        "winners": scored[:top_n],
        "avg_velocity": round(avg_v, 2),
        "count": len(scored),
    }


def decide_verdict(percentile):
    """Map percentile → decision. Used by !verdict and !autopsy."""
    if percentile >= 90:
        return "DOUBLE_DOWN", "🔥"
    if percentile >= 60:
        return "KEEP", "✅"
    if percentile >= 30:
        return "RENAME", "🔧"
    return "KILL", "🪦"
