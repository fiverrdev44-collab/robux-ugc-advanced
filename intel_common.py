"""
intel_common.py — shared intelligence layer.
Used by !brainstorm, !autopsy, !verdict, !converge.
Single source of truth for:
  - keyword classification (SATURATED / GOLD / etc.)
  - percentile ranking vs category peers
  - portfolio context (your winners, your losers)
  - multi-signal verdict logic
  - deterministic pivot picker (no AI flip-flop)

VERDICT PRIORITY ORDER:
  1. Sales data (strongest signal — real money)
  2. Fast riser velocity override
  3. Hard-kill rules (age × favs)
  4. Freefaller detection
  5. TOO_NEW guards (with velocity exception)
  6. Percentile buckets
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
    median_favs = min(float(row[1] or 0), 5000)  # cap outlier skew

    cur.execute(
        "select count(*) from search_suggestions where suggestion ilike %s",
        (like,)
    )
    demand = cur.fetchone()[0] or 0

    if supply == 0 and demand == 0:
        bucket = "GHOST"
    elif supply == 0:
        bucket = "VIRGIN"
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
    Returns dict with percentile, sample_size, velocity, family, age_days.
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


# ── Multi-signal verdict — 6-priority decision tree ──
def decide_verdict(percentile, age_days=None, favs=None, velocity=None,
                   total_sales=None, sample_size=None):
    """
    Multi-signal verdict. Returns (verdict, emoji, reason).

    Priority:
      1. Sales data (>= 10 → DOUBLE_DOWN, >= 3 → KEEP, 0 & old → KILL)
      2. Fast riser velocity (>= 10/day)
      3. Hard-kill rules (age × favs)
      4. Freefaller detection
      5. TOO_NEW (with velocity exception)
      6. Percentile buckets
    """
    p = percentile if percentile is not None else 0
    age = float(age_days) if age_days is not None else None
    f = int(favs) if favs is not None else None
    v = float(velocity) if velocity is not None else 0.0
    sales = int(total_sales) if total_sales is not None else None
    sample = int(sample_size) if sample_size is not None else None

    low_conf = ""
    if sample is not None and sample < 20:
        low_conf = f" (⚠️ only {sample} peers — low confidence)"

    # PRIORITY 1: SALES
    if sales is not None and sales >= 10:
        return ("DOUBLE_DOWN", "🔥",
                f"{sales} sales in 30d. Real money. Ship a variant.{low_conf}")
    if sales is not None and sales >= 3:
        return ("KEEP", "✅",
                f"{sales} sales in 30d. Steady revenue.{low_conf}")
    if (sales is not None and sales == 0
            and age is not None and age >= 30
            and f is not None and f >= 5):
        return ("KILL", "🪦",
                f"{age:.0f}d · {f}♥ · 0 sales in 30d. "
                f"Favorites don't convert.{low_conf}")

    # PRIORITY 2: FAST RISER
    if v >= 10 and age is not None and age >= 3:
        return ("DOUBLE_DOWN", "🔥",
                f"{v}/day at {age:.0f}d. Velocity alone wins.{low_conf}")

    # PRIORITY 3: HARD KILL
    if age is not None and f is not None:
        if age >= 60 and f < 20:
            return ("KILL", "🪦",
                    f"{age:.0f}d · only {f}♥. High probability of "
                    f"unrecoverable.{low_conf}")
        if age >= 30 and f < 10:
            return ("KILL", "🪦",
                    f"{age:.0f}d · {f}♥. Peer median is higher. "
                    f"Move on.{low_conf}")
        if age >= 14 and f < 5:
            return ("KILL", "🪦",
                    f"{age:.0f}d · {f}♥. Not being discovered.{low_conf}")
        if age >= 7 and f < 3:
            return ("KILL", "🪦",
                    f"{age:.0f}d · {f}♥. Zero traction after a week.{low_conf}")

    # PRIORITY 4: FREEFALLER
    if (v < 0.3 and age is not None and age >= 14
            and f is not None and f < 50):
        return ("KILL", "🪦",
                f"{v}/day at {age:.0f}d · {f}♥. Trajectory has "
                f"flatlined.{low_conf}")

    # PRIORITY 5: TOO_NEW
    if age is not None and age < 7:
        if f is None:
            return ("TOO_NEW", "⏳",
                    f"Only {age:.1f}d old. No data yet.")
        if v >= 5:
            return ("DOUBLE_DOWN", "🔥",
                    f"{v}/day at {age:.1f}d · {f}♥. Fast riser.{low_conf}")
        if f < 30:
            days_left = max(1, int(7 - age))
            return ("TOO_NEW", "⏳",
                    f"{age:.1f}d old · {f}♥. "
                    f"Re-run in {days_left} days.")

    # PRIORITY 6: PERCENTILE
    if p >= 90:
        return ("DOUBLE_DOWN", "🔥",
                f"Top {100 - int(p)}% of peers. Strong.{low_conf}")
    if p >= 75 and f is not None and f >= 50:
        return ("DOUBLE_DOWN", "🔥",
                f"Top {100 - int(p)}% · {f}♥. Strong traction.{low_conf}")
    if p >= 60:
        return ("KEEP", "✅",
                f"Top {100 - int(p)}% of peers. Above median.{low_conf}")
    if p >= 45 and f is not None and f >= 20:
        return ("KEEP", "✅",
                f"Top {100 - int(p)}% · {f}♥. Steady.{low_conf}")
    if p >= 25:
        return ("RENAME", "🔧",
                f"Top {100 - int(p)}% — item has demand, "
                f"title/thumbnail blocking conversion.{low_conf}")

    return ("KILL", "🪦",
            f"Bottom {int(p)}% of peers. No signal to salvage.{low_conf}")


# ── DETERMINISTIC PIVOT PICKER ───────────────────────────────────────
def pick_pivot_from_data(niche_data, keyword_intel=None):
    """
    Deterministic pivot picker. Uses real DB data, not AI opinion.
    Same input → same output. Returns (keyword, confidence, reason).
    """
    if not niche_data:
        return (None, 0.0, "no niche data")

    scored = []
    for k in niche_data:
        bucket = k.get("bucket", "NEUTRAL")
        median = k.get("median_favs", 0)
        supply = k.get("supply", 0)
        demand = k.get("demand", 0)

        bmap = {"GOLD": 100, "OPPORTUNITY": 80, "VIRGIN": 70,
                "NEUTRAL": 40, "SATURATED": 20, "GHOST": 5}
        b = bmap.get(bucket, 40)

        m = min(median / 50.0, 3.0) * 15
        d = min(demand / 100.0, 2.0) * 10

        if supply < 5:
            s = -20
        elif supply <= 50:
            s = 20
        elif supply <= 150:
            s = 5
        else:
            s = -10

        total = b + m + d + s
        scored.append({
            "keyword": k["keyword"],
            "score": total,
            "bucket": bucket,
            "median": median,
            "supply": supply,
            "demand": demand,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    best = scored[0]

    if len(scored) > 1:
        margin = best["score"] - scored[1]["score"]
        confidence = min(margin / 30.0, 1.0)
    else:
        confidence = 0.5

    reason = (
        f"bucket={best['bucket']} · supply={best['supply']} · "
        f"median={best['median']} · demand={best['demand']}"
    )
    return (best["keyword"], round(confidence, 2), reason)
