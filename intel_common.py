"""
intel_common.py — shared intelligence layer.
Used by !brainstorm, !autopsy, !verdict, !converge.

FIXES in this version:
  - ACCESSORY UMBRELLA: "accessory" family matches all 5 sub-types
    (43, 44, 45, 46, 47).
  - classify_keyword uses WORD BOUNDARY for single words (hip ≠ chip).
  - pick_pivot_from_data uses ABSOLUTE confidence (not margin-based).
  - _family_clause translates category_configs → convergence_engine.
"""
import re
import math
from bot_core import get_db
from convergence_engine import ASSET_TO_FAMILY, FAMILIES


ACCESSORY_IDS = [43, 44, 45, 46, 47]


def _family_clause(family):
    """
    Bulletproof family clause.
    Special case: "accessory" matches all 5 accessory sub-types.
    Otherwise translates category_configs → convergence_engine names.
    """
    if not family or family == "all":
        return "", []

    # ── ACCESSORY UMBRELLA ─────────────────────────────────────
    if family == "accessory":
        return " and asset_type_id in (43, 44, 45, 46, 47)", []
    # ────────────────────────────────────────────────────────────

    try:
        from category_configs import to_convergence_family
        fam = to_convergence_family(family)
    except Exception:
        fam = family

    # Translation might have produced "accessory" — handle it
    if fam == "accessory":
        return " and asset_type_id in (43, 44, 45, 46, 47)", []
    if fam is None:
        return " and false", []
    ids = FAMILIES.get(fam)
    if not ids:
        return " and false", []
    ph = ",".join(["%s"] * len(ids))
    return f" and asset_type_id in ({ph})", list(ids)


def _kw_match_op(keyword):
    """Word boundary for single words, ILIKE for phrases."""
    kw = (keyword or "").strip().lower()
    if " " in kw:
        return "ilike", f"%{kw}%"
    return "~*", rf"\y{re.escape(kw)}\y"


# ── Shared classification thresholds — one place, one truth ──
def classify_keyword(cur, keyword, family=None):
    """
    Returns dict with classification fields used EVERYWHERE.

    GOLD        — supply < 20  AND median_favs >= 150
    OPPORTUNITY — supply < 50  AND median_favs >= 80
    SATURATED   — supply > 200 OR median_favs < 15
    VIRGIN      — supply = 0 but demand > 0
    GHOST       — no supply, no demand
    """
    match_op, pat = _kw_match_op(keyword)
    fam_sql, fam_params = _family_clause(family)

    # Supply + median (word-boundary matched)
    cur.execute(f"""
        select count(*),
               percentile_cont(0.5) within group (order by favorite_count)
        from items
        where name {match_op} %s and favorite_count > 5
        {fam_sql}
    """, [pat] + fam_params)
    row = cur.fetchone()
    supply = row[0] or 0
    median_favs = min(float(row[1] or 0), 5000)  # cap outlier skew

    # Demand (word-boundary matched, live suggestions preferred)
    cur.execute(f"""
        select count(*),
               count(*) filter (where seed_keyword is distinct from %s),
               coalesce(sum(search_volume) filter
                        (where seed_keyword is distinct from %s), 0)
        from search_suggestions
        where suggestion {match_op} %s
    """, ("__db_mined__", "__db_mined__", pat))
    demand_row = cur.fetchone()
    demand_all = int(demand_row[0] or 0)
    demand_live = int(demand_row[1] or 0)
    demand_volume = int(demand_row[2] or 0)
    demand_reliable = demand_live > 0
    demand = demand_live if demand_reliable else demand_all

    if supply == 0 and demand_live == 0:
        bucket = "GHOST"
    elif supply == 0 and demand_live > 0:
        bucket = "VIRGIN"
    elif supply < 20 and median_favs >= 150:
        bucket = "GOLD"
    elif supply < 50 and median_favs >= 80:
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
        "demand_live": demand_live,
        "demand_mined": demand_all - demand_live,
        "demand_volume": demand_volume,
        "demand_reliable": demand_reliable,
        "bucket": bucket,
    }


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


# ── Portfolio context ──
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


# ── Maturity-aware survival intelligence ─────────────────────────────
def d30_milestone_probability(cur, family, favs=None, age_days=None,
                              velocity=None, min_cohort=20):
    """Estimate the chance of reaching the family D30-favorites median.

    Uses only mature, observed launch_ledger.favs_d30 values for this family.
    The returned percentage is an explicitly uncalibrated logistic heuristic,
    not a trained probability. It is withheld when fewer than min_cohort
    mature outcomes exist.
    """
    family = str(family or "").strip().lower()
    if not family or family == "unknown":
        return {
            "available": False, "family": family or "unknown",
            "cohort_n": 0, "reason": "No reliable category family is available.",
        }

    try:
        from convergence_engine import resolve_family_ids
        family_ids = resolve_family_ids(family)
        if not family_ids:
            return {
                "available": False, "family": family, "cohort_n": 0,
                "reason": f"No asset-type mapping is available for {family}.",
            }
        placeholders = ",".join(["%s"] * len(family_ids))
        cur.execute(f"""
            SELECT favs_d30
            FROM launch_ledger
            WHERE asset_type_id IN ({placeholders})
              AND favs_d30 IS NOT NULL
              AND favs_d30 >= 0
              AND COALESCE(published_at, launched_at)
                    <= NOW() - INTERVAL '30 days'
            ORDER BY favs_d30
        """, list(family_ids))
        outcomes = sorted(
            float(row[0]) for row in cur.fetchall()
            if row and row[0] is not None and float(row[0]) >= 0
        )
    except Exception as exc:
        try:
            cur.connection.rollback()
        except Exception:
            pass
        return {
            "available": False, "family": family, "cohort_n": 0,
            "reason": f"D30 family cohort unavailable ({type(exc).__name__}).",
        }

    n = len(outcomes)
    if n < int(min_cohort):
        return {
            "available": False, "family": family, "cohort_n": n,
            "reason": (
                f"Only {n} mature {family} D30 outcomes; "
                f"at least {int(min_cohort)} are required."
            ),
        }

    mid = n // 2
    milestone = (
        outcomes[mid] if n % 2 else
        (outcomes[mid - 1] + outcomes[mid]) / 2.0
    )
    age = max(0.0, float(age_days or 0.0))
    current_favs = max(0.0, float(favs or 0.0))
    pace = max(0.0, float(velocity or 0.0))
    # Linear pace projection is a transparent baseline, not an ML forecast.
    projected = (
        current_favs + pace * max(0.0, 30.0 - age)
        if age < 30.0 else current_favs
    )

    deviations = sorted(abs(value - milestone) for value in outcomes)
    mad_mid = n // 2
    mad = (
        deviations[mad_mid] if n % 2 else
        (deviations[mad_mid - 1] + deviations[mad_mid]) / 2.0
    )
    scale = max(1.0, 1.4826 * mad)
    z = max(-20.0, min(20.0, (projected - milestone) / scale))
    probability = 100.0 / (1.0 + math.exp(-z))

    return {
        "available": True,
        "family": family,
        "cohort_n": n,
        "milestone_favs": round(milestone, 1),
        "projected_favs_d30": round(projected, 1),
        "probability": round(probability, 1),
        "probability_label": "uncalibrated family-cohort heuristic",
        "not_calibrated": True,
        "method": "current lifetime pace projected to D30; logistic MAD scale",
    }


def decide_verdict(percentile, age_days=None, favs=None, velocity=None,
                   total_sales=None, sample_size=None, d30_probability=None):
    """Return a maturity-aware state, emoji, and evidence-based explanation.

    States:
      TOO_EARLY, WATCH, RECOVERING, STAGNATING, KILL_CANDIDATE, WINNER.

    KILL_CANDIDATE is a review state only; it never authorizes an automatic
    removal. Sparse peer samples prevent a candidate classification.
    """
    p = float(percentile) if percentile is not None else 0.0
    age = float(age_days) if age_days is not None else None
    f = int(favs) if favs is not None else None
    v = max(0.0, float(velocity or 0.0))
    sales = int(total_sales) if total_sales is not None else None
    sample = int(sample_size) if sample_size is not None else None
    d30_p = (
        float(d30_probability)
        if d30_probability is not None else None
    )

    low_conf = (
        f" (⚠️ only {sample} peers — low confidence)"
        if sample is not None and sample < 20 else ""
    )
    viral = (
        v >= 10.0
        or (sales is not None and sales >= 3)
        or (p >= 95.0 and f is not None and f >= 25
            and sample is not None and sample >= 20)
        or (d30_p is not None and d30_p >= 90.0 and v >= 1.0)
    )

    if age is None:
        return (
            "WATCH", "👀",
            "Item age is unavailable. Keep observing until its maturity window can be established."
            + low_conf,
        )

    if age < 14.0:
        wait_days = max(1, int(math.ceil(14.0 - age)))
        if viral:
            return (
                "WINNER", "🏆",
                f"Breakout signal at {age:.1f}d ({v:.2f} favorites/day). "
                "Keep monitoring; this early signal is promising."
                + low_conf,
            )
        return (
            "TOO_EARLY", "⏳",
            f"This item is too young to judge. The data is still maturing. "
            f"We should WATCH it for another {wait_days} days."
            + low_conf,
        )

    # Strong observed performance can earn WINNER status at any mature age.
    if (sales is not None and sales >= 3) or (
        p >= 95.0 and sample is not None and sample >= 20
    ) or (d30_p is not None and d30_p >= 90.0 and v >= 1.0):
        return (
            "WINNER", "🏆",
            f"Strong family-relative performance: {p:.1f}th percentile, "
            f"{v:.2f} favorites/day."
            + low_conf,
        )

    if age < 30.0:
        if v > 0.0:
            if v >= 0.25 or p >= 60.0 or (d30_p is not None and d30_p >= 60.0):
                return (
                    "RECOVERING", "📈",
                    f"Still gaining traction at {v:.2f} favorites/day. "
                    "The item is within its first 30 days; monitor the next snapshots."
                    + low_conf,
                )
            return (
                "WATCH", "👀",
                f"Some positive activity ({v:.2f} favorites/day), but not enough "
                "evidence yet to call a sustained recovery."
                + low_conf,
            )
        return (
            "WATCH", "👀",
            f"{age:.1f}d old with flat recent pace. Continue observation through "
            "the 30-day maturity window."
            + low_conf,
        )

    # Past D30, flat items stagnate. Only well-supported, prolonged low
    # traction becomes a candidate for manual review.
    if v > 0.05:
        if v >= 0.25 or p >= 40.0 or (d30_p is not None and d30_p >= 50.0):
            return (
                "RECOVERING", "📈",
                f"Positive ongoing pace ({v:.2f} favorites/day). "
                "The trajectory is not flat."
                + low_conf,
            )
        return (
            "WATCH", "👀",
            f"Low but non-zero activity ({v:.2f} favorites/day). "
            "Keep monitoring before changing the listing."
            + low_conf,
        )

    if (
        age >= 45.0
        and sales == 0
        and f is not None and f < 50
        and sample is not None and sample >= 20
        and p < 20.0
    ):
        return (
            "KILL_CANDIDATE", "⚠️",
            f"{age:.0f}d old with near-flat pace, {f} favorites and "
            f"bottom-{int(p)}th-percentile performance. Manual review only; "
            "this is not an automatic removal decision."
            + low_conf,
        )

    return (
        "STAGNATING", "🟠",
        f"{age:.0f}d old with near-flat pace ({v:.2f} favorites/day). "
        "The item is stagnating, but evidence does not justify an automatic removal."
        + low_conf,
    )


# ── DETERMINISTIC PIVOT PICKER ──
def pick_pivot_from_data(niche_data, keyword_intel=None):
    """
    Deterministic pivot picker. Uses real DB data, not AI opinion.
    Same input → same output. Returns (keyword, confidence, reason).

    Confidence is ABSOLUTE (based on winning score), not margin-based.
    Margin-based was giving ~3% when all candidates were NEUTRAL with
    similar scores, even when the winning score was high.
    """
    if not niche_data:
        return (None, 0.0, "no niche data")

    scored = []
    for k in niche_data:
        bucket = k.get("bucket", "NEUTRAL")
        median = k.get("median_favs", 0)
        supply = k.get("supply", 0)
        demand = k.get("demand_live", k.get("demand", 0))

        # No live demand or a saturated/ghost lane is not a pivot.
        if demand == 0 or bucket in ("SATURATED", "GHOST", "DEAD"):
            continue
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
    if not scored:
        return (None, 0.0, "no demand-backed pivot")
    best = scored[0]

    # ── ABSOLUTE CONFIDENCE ────────────────────────────────────
    # 120 = practical top score (100 base + 20 supply + 10 demand - small)
    # Cap at 90% — no system should be 100% confident.
    confidence = min(best["score"] / 120.0, 0.9)
    if len(scored) == 1:
        confidence = 0.5
    # ────────────────────────────────────────────────────────────

    reason = (
        f"bucket={best['bucket']} · supply={best['supply']} · "
        f"median={best['median']} · demand={best['demand']}"
    )
    return (best["keyword"], round(confidence, 2), reason)
