"""confidence.py — 80% intervals computed from real cohorts.

No point estimate is shown without its interval. Every interval is either a
percentile bootstrap (favorites) or a Wilson interval (proportions). When the
sample is too small, the function returns None instead of inventing precision.
"""
import math
import random
import re
from statistics import median, mean

CONFIDENCE = 0.80
BOOT_ITERS = 1500
BOOT_SEED = 1729


def _quantile(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = (len(sorted_vals) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_vals[lo])
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def bootstrap_ci(values, stat=median, confidence=CONFIDENCE,
                 iters=BOOT_ITERS, seed=BOOT_SEED):
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    if len(vals) == 1:
        return {"point": round(float(stat(vals)), 2),
                "lo": round(float(stat(vals)), 2),
                "hi": round(float(stat(vals)), 2),
                "n": 1}
    rng = random.Random(seed)
    n = len(vals)
    stats = []
    for _ in range(iters):
        sample = [vals[rng.randrange(n)] for _ in range(n)]
        stats.append(float(stat(sample)))
    stats.sort()
    alpha = (1.0 - confidence) / 2.0
    return {
        "point": round(float(stat(vals)), 2),
        "lo": round(_quantile(stats, alpha), 2),
        "hi": round(_quantile(stats, 1 - alpha), 2),
        "n": n,
    }


def wilson_interval(successes, n, confidence=CONFIDENCE):
    if n <= 0:
        return None
    z = _z_for(confidence)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return {
        "point": round(100 * p, 1),
        "lo": round(100 * max(0.0, centre - margin), 1),
        "hi": round(100 * min(1.0, centre + margin), 1),
        "n": n,
    }


def _z_for(confidence):
    try:
        from statistics import NormalDist
        return NormalDist().inv_cdf(1 - (1 - confidence) / 2)
    except Exception:
        return 1.2816 if confidence == 0.80 else 1.96


def _family_ids(family):
    try:
        from convergence_engine import resolve_family_ids
        ids = resolve_family_ids(family)
        return list(ids) if ids else None
    except Exception:
        return None


def _cohort_filters(family=None, phrase=None):
    sql = ""
    params = []
    ids = _family_ids(family)
    if ids:
        sql += " and asset_type_id in (" + ",".join(["%s"] * len(ids)) + ")"
        params.extend(ids)
    if phrase:
        clean = " ".join(re.findall(r"[a-z0-9]+", phrase.lower()))
        if clean:
            sql += " and lower(name) like %s"
            params.append(f"%{clean}%")
    return sql, params


def velocity_cohort(cur, family=None, phrase=None, days=90, min_favs=5,
                    min_age=7):
    fam_sql, fam_params = _cohort_filters(family, phrase)
    cur.execute(f"""
        select id, favorite_count,
               extract(epoch from (now() - created_at)) / 86400.0 as age_days
        from items
        where created_at is not null
          and created_at < now() - make_interval(days => %s)
          and created_at > now() - make_interval(days => %s)
          and favorite_count > %s
          {fam_sql}
        limit 5000
    """, [int(min_age), int(days), int(min_favs)] + fam_params)
    out = []
    for item_id, favs, age_days in cur.fetchall():
        try:
            age = float(age_days or 0)
            if age <= 0:
                continue
            f = float(favs or 0)
            out.append({
                "id": item_id,
                "favs": f,
                "age_days": round(age, 2),
                "favs_per_day": round(f / age, 3),
                "favs_30d": round(f / age * 30.0, 1),
            })
        except Exception:
            continue
    return out


def prediction_interval(values, confidence=CONFIDENCE):
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return {"point": round(vals[0], 2), "lo": round(vals[0], 2),
                "hi": round(vals[0], 2), "n": 1}
    alpha = (1.0 - confidence) / 2.0
    return {
        "point": round(median(vals), 2),
        "lo": round(_quantile(vals, alpha), 2),
        "hi": round(_quantile(vals, 1 - alpha), 2),
        "n": len(vals),
    }


def favorites_ci(cohort, confidence=CONFIDENCE):
    vals = [c["favs_30d"] for c in cohort if c.get("favs_30d") is not None]
    pred = prediction_interval(vals, confidence=confidence)
    if not pred:
        return None
    centre = bootstrap_ci(vals, stat=median, confidence=confidence)
    pred["median_lo"] = centre["lo"]
    pred["median_hi"] = centre["hi"]
    return pred


def velocity_ci(cohort, confidence=CONFIDENCE):
    vals = [c["favs_per_day"] for c in cohort if c.get("favs_per_day") is not None]
    pred = prediction_interval(vals, confidence=confidence)
    if not pred:
        return None
    centre = bootstrap_ci(vals, stat=median, confidence=confidence)
    pred["median_lo"] = centre["lo"]
    pred["median_hi"] = centre["hi"]
    return pred


def threshold_for(cohort, top_frac):
    vals = sorted(c["favs_30d"] for c in cohort if c.get("favs_30d") is not None)
    if not vals:
        return None
    return round(_quantile(vals, 1 - top_frac), 2)


def front_page_stats(fav_ci, cohort, top_frac, confidence=CONFIDENCE):
    if not fav_ci or not cohort:
        return None
    threshold = threshold_for(cohort, top_frac)
    if threshold is None:
        return None
    vals = [c["favs_30d"] for c in cohort if c.get("favs_30d") is not None]
    successes = sum(1 for v in vals if v >= threshold)
    rate = wilson_interval(successes, len(vals), confidence=confidence)
    return {
        "top_frac": top_frac,
        "threshold": threshold,
        "base_rate": rate,
        "range_reaches": bool(fav_ci["hi"] >= threshold),
        "range_hi": fav_ci["hi"],
    }


def sales_ratio(cur, days=90, min_favs=10, min_items=5):
    try:
        cur.execute("""
            select item_name, count(*) as units
            from my_sales
            where sale_time > now() - make_interval(days => %s)
              and amount_robux > 0
            group by item_name
        """, (int(days),))
        sales_rows = cur.fetchall()
    except Exception:
        return None
    if not sales_rows:
        return None

    names = [str(r[0] or "").strip().lower() for r in sales_rows if r[0]]
    if not names:
        return None
    cur.execute("""
        select lower(name), favorite_count
        from items
        where lower(name) = any(%s)
    """, (names,))
    favs_by_name = {}
    for name, favs in cur.fetchall():
        if name:
            favs_by_name[name] = float(favs or 0)

    ratios = []
    used = 0
    matched_names = 0
    for name, units in sales_rows:
        key = str(name or "").strip().lower()
        favs = favs_by_name.get(key, 0.0)
        if favs > 0:
            matched_names += 1
        if favs < min_favs:
            continue
        ratios.append(float(units) / favs)
        used += 1

    if used < min_items:
        return {
            "available": False,
            "reason": (
                f"only {matched_names} of {len(sales_rows)} sold item names "
                f"match a catalog row with {min_favs}+ favorites "
                f"(need {min_items})"
            ),
            "n": used,
            "matched_names": matched_names,
            "sold_names": len(sales_rows),
        }

    ci = bootstrap_ci(ratios, stat=median)
    return {
        "available": True,
        "ratio": ci,
        "n": used,
        "basis": "units per cumulative favorite, matched to your own items",
    }


def sales_history_ci(cur, item_name, days=90, confidence=CONFIDENCE,
                     min_units=5):
    from datetime import date, timedelta
    end = date.today()
    start = end - timedelta(days=days - 1)
    try:
        cur.execute("""
            select created_at::date
            from items
            where lower(name) = lower(%s) and created_at is not null
            order by favorite_count desc nulls last
            limit 1
        """, (item_name,))
        row = cur.fetchone()
        if row and row[0] and row[0] > start:
            start = row[0]
        cur.execute("""
            select coalesce(sale_date, sale_time::date) as d, count(*)
            from my_sales
            where lower(item_name) = lower(%s)
              and coalesce(sale_date, sale_time::date) between %s and %s
            group by 1
        """, (item_name, start, end))
        rows = cur.fetchall()
    except Exception as e:
        return {"available": False, "reason": f"sales query failed: {type(e).__name__}"}

    observed = {}
    for d, count in rows:
        if d is not None:
            observed[d] = int(count or 0)
    n_days = (end - start).days + 1
    daily = [float(observed.get(start + timedelta(days=i), 0))
             for i in range(n_days)]
    total = int(sum(daily))
    if total < min_units:
        return {
            "available": False,
            "reason": f"{total} sales in {n_days}d (need {min_units})",
            "units": total,
        }

    ci = bootstrap_ci(daily, stat=mean, confidence=confidence)
    scale = 30.0
    return {
        "available": True,
        "units_observed": total,
        "window_days": n_days,
        "units_30d": {
            "point": round(ci["point"] * scale, 1),
            "lo": round(ci["lo"] * scale, 1),
            "hi": round(ci["hi"] * scale, 1),
        },
        "n_days": n_days,
    }

MIN_COHORT = 20


def build_confidence(cur, family=None, phrase=None, price=0,
                     confidence=CONFIDENCE):
    family_cohort = velocity_cohort(cur, family=family, days=90)
    niche_cohort = velocity_cohort(cur, family=family, phrase=phrase, days=90) if phrase else []
    cohort = niche_cohort if len(niche_cohort) >= MIN_COHORT else family_cohort
    scope = "niche" if cohort is niche_cohort and niche_cohort else "family"

    if len(cohort) < MIN_COHORT:
        return {
            "confidence": confidence,
            "scope": scope,
            "cohort_size": len(cohort),
            "insufficient": True,
            "reason": (
                f"need {MIN_COHORT} comparable items; found {len(cohort)}"
            ),
            "favorites_30d": None,
            "velocity_per_day": None,
            "top10": None,
            "top1": None,
            "sales": None,
            "family": family,
            "phrase": phrase,
        }

    fav = favorites_ci(cohort, confidence=confidence)
    vel = velocity_ci(cohort, confidence=confidence)
    top10 = front_page_stats(fav, cohort, 0.10, confidence=confidence)
    top1 = front_page_stats(fav, cohort, 0.01, confidence=confidence)

    sales = sales_ratio(cur)
    sales_out = None
    if sales and sales.get("available") and fav:
        ratio = sales["ratio"]
        units_lo = fav["lo"] * ratio["lo"]
        units_hi = fav["hi"] * ratio["hi"]
        units_point = fav["point"] * ratio["point"]
        revenue = None
        if price and price > 0:
            revenue = {
                "price": price,
                "point": round(units_point * price),
                "lo": round(units_lo * price),
                "hi": round(units_hi * price),
            }
        sales_out = {
            "units": {
                "point": round(units_point, 1),
                "lo": round(units_lo, 1),
                "hi": round(units_hi, 1),
            },
            "revenue": revenue,
            "ratio": ratio,
            "n": sales["n"],
            "basis": sales["basis"],
        }
    elif sales:
        sales_out = {"available": False, "reason": sales.get("reason")}

    return {
        "confidence": confidence,
        "scope": scope,
        "cohort_size": len(cohort),
        "favorites_30d": fav,
        "velocity_per_day": vel,
        "top10": top10,
        "top1": top1,
        "sales": sales_out,
        "family": family,
        "phrase": phrase,
    }


def format_confidence(conf):
    if not conf:
        return "## 📉 Cohort Evidence\n_No comparable cohort — cannot estimate._"
    if conf.get("insufficient"):
        return (
            "## 📉 Cohort Evidence\n"
            f"• **Not enough comparable items** — {conf.get('reason')}.\n"
            "_No interval is shown because the sample is too small._"
        )

    lines = ["## 📉 Cohort Evidence (80% intervals)"]
    lines.append(
        f"• Cohort: **{conf.get('cohort_size', 0)}** comparable items "
        f"({conf.get('scope', 'family')}, last 90d)"
    )
    fav = conf.get("favorites_30d")
    if fav:
        lines.append(
            f"• 30-day favorites: median **{fav['point']:,.0f}** · "
            f"80% of comparable launches **{fav['lo']:,.0f}–{fav['hi']:,.0f}** "
            f"(median CI {fav.get('median_lo', fav['lo']):,.0f}–"
            f"{fav.get('median_hi', fav['hi']):,.0f}, n={fav['n']})"
        )
    vel = conf.get("velocity_per_day")
    if vel:
        lines.append(
            f"• Velocity: median **{vel['point']:.2f}/day** · "
            f"80% of launches {vel['lo']:.2f}–{vel['hi']:.2f}"
        )

    for label, stats in (("Front page (top 1%)", conf.get("top1")),
                         ("Top 10%", conf.get("top10"))):
        if not stats:
            continue
        rate = stats.get("base_rate") or {}
        reach = ("reaches the threshold"
                 if stats.get("range_reaches")
                 else "falls short of the threshold")
        lines.append(
            f"• {label}: threshold **{stats['threshold']:,.1f}** favs/30d · "
            f"**{rate.get('point', 0):.1f}%** of comparable launches "
            f"(80% CI {rate.get('lo', 0):.1f}–{rate.get('hi', 0):.1f}%) · "
            f"your range top {stats.get('range_hi', 0):,.1f} {reach}"
        )

    sales = conf.get("sales")
    if sales and sales.get("units"):
        u = sales["units"]
        lines.append(
            f"• Sales (30d): median **{u['point']:,.0f} units** · "
            f"80% of launches **{u['lo']:,.0f}–{u['hi']:,.0f}** · "
            f"n={sales['n']} own items"
        )
        rev = sales.get("revenue")
        if rev:
            lines.append(
                f"• Revenue (30d): median **R${rev['point']:,}** · "
                f"80% of launches **R${rev['lo']:,}–R${rev['hi']:,}** "
                f"at R${rev['price']} each"
            )
        lines.append(
            f"_Basis: {sales['basis']} at {sales['ratio']['point']:.3f} "
            f"units/fav (80% CI {sales['ratio']['lo']:.3f}–{sales['ratio']['hi']:.3f}). "
            f"Assumes your conversion rate transfers to this niche._"
        )
    elif sales and sales.get("reason"):
        lines.append(f"• Sales: **not verifiable** — {sales['reason']}")

    lines.append(
        "_Intervals describe comparable launches, not a guarantee for this one._"
    )
    return "\n".join(lines)
