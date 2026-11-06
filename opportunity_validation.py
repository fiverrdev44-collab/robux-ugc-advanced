"""Milestone 3 opportunity validation bridge.

This module does not discover candidates or make marketplace requests. It takes
the shortlist and live-verification results already produced by ``!converge``
and adds a structured, read-only evidence bundle. The Creator Registry is
optional: when it is missing, registry-dependent measurements are explicitly
unavailable and the rest of the evidence remains usable.
"""
import os
from datetime import datetime, timedelta, timezone
from math import ceil, floor
from statistics import median

from convergence_engine import _family_clause, _kw_pattern
from creator_identity import has_creator_type

M3_FLAG_ENV = "PHASE2_M3_ENABLED"
DEFAULT_SAMPLE_WINDOW_DAYS = 180

VERDICT_INSUFFICIENT = "INSUFFICIENT EVIDENCE"
VERDICT_INVESTIGATE = "INVESTIGATE"
VERDICT_VALIDATE = "VALIDATE EXPERIMENTALLY"
VERDICT_REJECT = "REJECT / AVOID"

SALES_UNAVAILABLE = "Attributable sales evidence unavailable."


def m3_enabled():
    """Off by default. Only an explicit truthy flag enables the M3 report."""
    return os.getenv(M3_FLAG_ENV, "0").strip().lower() in {
        "1", "true", "yes", "on"}


def _now():
    return datetime.now(timezone.utc)


def _as_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _age_days(value, now):
    value = _as_utc(value)
    if value is None:
        return None
    return max(0.0, (now - value).total_seconds() / 86400.0)


def _resolved_creator_type(value):
    """Only explicit User/Group types are confirmed composite identities."""
    text = (value or "").strip().lower()
    if text == "user":
        return "User"
    if text == "group":
        return "Group"
    return None


def _percentile(values, q):
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo, hi = floor(pos), ceil(pos)
    if lo == hi:
        return ordered[int(pos)]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _distribution(values, unit):
    values = [float(v) for v in values if v is not None]
    if not values:
        return {
            "available": False, "sample_n": 0, "unit": unit,
            "min": None, "p25": None, "median": None, "p75": None,
            "p90": None, "max": None,
        }
    return {
        "available": True,
        "sample_n": len(values),
        "unit": unit,
        "min": round(min(values), 2),
        "p25": round(_percentile(values, 0.25), 2),
        "median": round(float(median(values)), 2),
        "p75": round(_percentile(values, 0.75), 2),
        "p90": round(_percentile(values, 0.90), 2),
        "max": round(max(values), 2),
    }


def _table_columns(cur, table):
    try:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_schema = current_schema() and table_name = %s",
            (table,))
        return {row[0] for row in (cur.fetchall() or [])}
    except Exception:
        return set()


def fetch_item_sample(cur, keyword, family=None, limit=200, has_type=None,
                      sample_window_days=DEFAULT_SAMPLE_WINDOW_DAYS):
    """Bounded, popularity-ordered sample from the enforced creation window.

    Items with a missing creation timestamp are excluded from this sample and
    counted separately by ``count_undated_matches``. The result is a
    convenience sample, not a representative population.
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return []
    pattern = _kw_pattern(keyword)
    match_op = "ilike" if " " in keyword else "~*"
    fam_sql, fam_params = _family_clause(family)
    fam_sql = fam_sql.replace("asset_type_id", "i.asset_type_id")
    if has_type is None:
        has_type = has_creator_type(cur)
    type_expr = "i.creator_type" if has_type else "NULL::text"
    cur.execute(f"""
        SELECT i.id, i.name, i.favorite_count, i.price, i.created_at,
               i.creator_id, {type_expr} AS creator_type,
               i.creator_verified, i.creator_name, i.fetched_at
        FROM items i
        WHERE i.name {match_op} %s
          AND i.favorite_count > 5
          AND i.created_at IS NOT NULL
          AND i.created_at >= NOW() - make_interval(days => %s)
          {fam_sql}
        ORDER BY i.favorite_count DESC, i.id ASC
        LIMIT %s
    """, [pattern, int(sample_window_days)] + fam_params + [int(limit)])
    rows = cur.fetchall() or []
    return [{
        "id": r[0],
        "name": r[1],
        "favorite_count": r[2],
        "price": r[3],
        "created_at": r[4],
        "creator_id": r[5],
        "creator_type": r[6],
        "creator_verified": r[7],
        "creator_name": r[8],
        "fetched_at": r[9],
    } for r in rows]


def count_undated_matches(cur, keyword, family=None, limit=200):
    """Bounded count of matching items excluded for a missing created_at."""
    keyword = (keyword or "").strip()
    if not keyword:
        return {"count": 0, "capped": False, "limit": int(limit)}
    pattern = _kw_pattern(keyword)
    match_op = "ilike" if " " in keyword else "~*"
    fam_sql, fam_params = _family_clause(family)
    fam_sql = fam_sql.replace("asset_type_id", "i.asset_type_id")
    cur.execute(f"""
        SELECT count(*) FROM (
            SELECT 1
            FROM items i
            WHERE i.name {match_op} %s
              AND i.favorite_count > 5
              AND i.created_at IS NULL
              {fam_sql}
            LIMIT %s
        ) undated
    """, [pattern] + fam_params + [int(limit)])
    count = int((cur.fetchone() or [0])[0] or 0)
    return {"count": count, "capped": count >= int(limit),
            "limit": int(limit)}


def fetch_sales_evidence(cur, asset_ids, days=90, now=None):
    """Exact asset-ID sales attribution only. Fuzzy title matching is excluded."""
    now = now or _now()
    ids = sorted({int(x) for x in (asset_ids or []) if x is not None})
    base = {
        "available": False,
        "status": "unavailable",
        "attribution": None,
        "window_days": int(days),
        "window_start": (now - timedelta(days=days)).isoformat(),
        "window_end": now.isoformat(),
        "confirmed_units": None,
        "confirmed_robux": None,
        "first_sale": None,
        "last_sale": None,
        "unresolved_transactions": None,
        "limitations": [],
    }
    if not ids:
        base["limitations"].append(
            "No sampled asset IDs were available for exact sales attribution.")
        return base

    columns = _table_columns(cur, "my_sales")
    if not columns:
        base["limitations"].append("my_sales is unavailable.")
        return base
    if "asset_id" not in columns:
        base["limitations"].append(
            "my_sales.asset_id is unavailable; title matching is not confirmation.")
        return base
    if "sale_time" not in columns or "amount_robux" not in columns:
        base["limitations"].append(
            "my_sales lacks sale_time or amount_robux.")
        return base

    start = now - timedelta(days=days)
    cur.execute("""
        SELECT count(*), COALESCE(sum(amount_robux), 0),
               min(sale_time), max(sale_time)
        FROM my_sales
        WHERE asset_id = ANY(%s)
          AND sale_time >= %s AND sale_time < %s
    """, (ids, start, now))
    units, robux, first_sale, last_sale = cur.fetchone() or (0, 0, None, None)
    cur.execute("""
        SELECT count(*) FROM my_sales
        WHERE sale_time >= %s AND sale_time < %s AND asset_id IS NULL
    """, (start, now))
    unresolved = int((cur.fetchone() or [0])[0] or 0)

    base.update({
        "available": True,
        "status": "confirmed" if int(units or 0) > 0
        else "no_exact_asset_sales",
        "attribution": "exact_asset_id",
        "confirmed_units": int(units or 0),
        "confirmed_robux": int(robux or 0),
        "first_sale": _as_utc(first_sale).isoformat() if first_sale else None,
        "last_sale": _as_utc(last_sale).isoformat() if last_sale else None,
        "unresolved_transactions": unresolved,
        "limitations": [
            "Exact sales are matched only by my_sales.asset_id; title matches "
            "are never treated as confirmed sales.",
            "Sales ingestion coverage may be incomplete; absence in this window "
            "is not proof of zero marketplace sales.",
        ],
    })
    if unresolved:
        base["limitations"].append(
            f"{unresolved} window transactions have no asset_id and cannot be "
            "attributed to this niche.")
    return base


def _creator_summary(item_rows):
    verified = nonverified = verification_unknown = 0
    no_identity = 0
    numeric_id_items = 0
    resolved_items = 0
    unknown_type_items = 0
    numeric_ids = set()
    unknown_type_ids = set()
    unknown_type_names = {}
    groups = {}
    name_groups = {}
    name_keys = {}
    for row in item_rows:
        cid = row.get("creator_id")
        favs = int(row.get("favorite_count") or 0)
        ctype = None
        if cid is None:
            no_identity += 1
        else:
            cid = int(cid)
            numeric_id_items += 1
            numeric_ids.add(cid)
            ctype = _resolved_creator_type(row.get("creator_type"))
            if ctype is None:
                unknown_type_items += 1
                unknown_type_ids.add(cid)
                unresolved_name = (row.get("creator_name") or "").strip()
                if unresolved_name:
                    unknown_type_names.setdefault(cid, set()).add(
                        unresolved_name)
            else:
                resolved_items += 1
                key = (ctype, cid)
                entry = groups.setdefault(
                    key, {"creator_type": ctype, "creator_id": cid,
                          "items": 0, "favorites": 0})
                entry["items"] += 1
                entry["favorites"] += favs
        badge = row.get("creator_verified")
        if badge is True:
            verified += 1
        elif badge is False:
            nonverified += 1
        else:
            verification_unknown += 1

        name = (row.get("creator_name") or "").strip().lower()
        if name:
            entry = name_groups.setdefault(
                name, {"name": row.get("creator_name"), "items": 0,
                       "favorites": 0})
            entry["items"] += 1
            entry["favorites"] += favs
            if ctype is not None:
                name_keys.setdefault(name, set()).add((ctype, cid))

    sample_n = len(item_rows)
    resolved_coverage = (
        round(100.0 * resolved_items / sample_n, 1) if sample_n else None)
    numeric_coverage = (
        round(100.0 * numeric_id_items / sample_n, 1) if sample_n else None)
    total_favs = sum(g["favorites"] for g in groups.values())
    top = max(groups.values(), key=lambda g: g["favorites"],
              default=None)
    concentration = (round(top["favorites"] / total_favs, 3)
                     if top and total_favs else None)
    name_total = sum(g["favorites"] for g in name_groups.values())
    name_top = max(name_groups.values(), key=lambda g: g["favorites"],
                   default=None)
    name_concentration = (round(name_top["favorites"] / name_total, 3)
                          if name_top and name_total else None)

    top_creators = sorted(groups.values(),
                          key=lambda g: (-g["favorites"], g["creator_type"],
                                         g["creator_id"]))[:5]
    for entry in top_creators:
        entry["share_of_identified_favorites"] = (
            round(entry["favorites"] / total_favs, 3) if total_favs else None)

    ids_by_type = {}
    for ctype, cid in groups:
        ids_by_type.setdefault(cid, set()).add(ctype)

    return {
        "identity_basis": "(creator_type, creator_id)",
        "sample_items": sample_n,
        "numeric_id_items": numeric_id_items,
        "numeric_creator_count": len(numeric_ids),
        "numeric_id_coverage_pct": numeric_coverage,
        "resolved_composite_items": resolved_items,
        "identified_items": resolved_items,
        "unknown_identity_items": no_identity,
        "unknown_creator_type_items": unknown_type_items,
        "unknown_creator_type_numeric_ids": len(unknown_type_ids),
        "resolved_composite_coverage_pct": resolved_coverage,
        "identity_coverage_pct": resolved_coverage,
        "identified_creator_count": len(groups),
        "creator_concentration_identified": concentration,
        "creator_concentration_name_approx": name_concentration,
        "name_approximation_label": (
            "Display-name concentration is approximate and must not be read as "
            "stable creator identity."),
        "top_creators": top_creators,
        "verification_counts": {
            "verified": verified,
            "nonverified": nonverified,
            "unknown": verification_unknown,
        },
        "duplicate_names_distinct_ids": [
            {
                "display_name": name_groups[name]["name"],
                "creator_keys": [f"{t}:{i}" for t, i in sorted(keys)],
                "note": "same display name, distinct stable identities",
            }
            for name, keys in sorted(name_keys.items()) if len(keys) > 1
        ],
        "unresolved_numeric_id_display_names": [
            {"creator_id": cid, "display_names": sorted(names),
             "note": "unresolved creator type; names are not merged"}
            for cid, names in sorted(unknown_type_names.items())
            if len(names) > 1
        ],
        "numeric_ids_with_multiple_types": [
            {"creator_id": cid, "types": sorted(types)}
            for cid, types in sorted(ids_by_type.items()) if len(types) > 1
        ],
    }


def summarize_item_sample(item_rows, now=None, sample_limit=200,
                          undated_matches=0, undated_capped=False,
                          sample_window_days=DEFAULT_SAMPLE_WINDOW_DAYS):
    """Summarize only dated rows from the enforced creation window.

    Rows with no creation timestamp are excluded from the bounded distributions
    and reported separately. The caller supplies ``undated_matches`` for items
    excluded by SQL; any undated rows passed directly are also counted.
    """
    now = now or _now()
    dated_rows = [r for r in item_rows if r.get("created_at") is not None]
    in_rows_undated = len(item_rows) - len(dated_rows)
    excluded_undated = int(undated_matches or 0) + in_rows_undated
    favorites = [r.get("favorite_count") for r in dated_rows
                 if r.get("favorite_count") is not None]
    prices = [r.get("price") for r in dated_rows
              if r.get("price") is not None and int(r.get("price") or 0) > 0]
    missing_price = sum(1 for r in dated_rows if r.get("price") is None)
    free_price = sum(1 for r in dated_rows if r.get("price") == 0)
    ages = [_age_days(r.get("created_at"), now) for r in dated_rows]
    ages = [a for a in ages if a is not None]
    created_values = [_as_utc(r.get("created_at")) for r in dated_rows]
    created_values = [v for v in created_values if v is not None]
    fav_dist = _distribution(favorites, "favorites")
    total_favs = sum(float(f) for f in favorites)
    fav_dist.update({
        "window_days": int(sample_window_days),
        "ordering": "favorite_count_desc_convenience",
        "representative": False,
        "created_at_null_excluded_n": excluded_undated,
        "source": "bounded items sample; popularity-ordered convenience sample",
    })
    fav_dist["top_item_share"] = (
        round(max(float(f) for f in favorites) / total_favs, 3)
        if total_favs and favorites else None)
    creator = _creator_summary(dated_rows)
    return {
        "sample_items": len(dated_rows),
        "sample_limit": int(sample_limit),
        "sample_window_days": int(sample_window_days),
        "sample_capped": len(dated_rows) >= int(sample_limit),
        "sample_created_at_min": (
            min(created_values).isoformat() if created_values else None),
        "sample_created_at_max": (
            max(created_values).isoformat() if created_values else None),
        "undated_matches": int(undated_matches or 0),
        "undated_capped": bool(undated_capped),
        "undated_excluded_n": excluded_undated,
        "favorite_distribution": fav_dist,
        "price_distribution": {
            **_distribution(prices, "Robux"),
            "missing_n": missing_price,
            "free_n": free_price,
            "created_at_null_excluded_n": excluded_undated,
            "zero_or_missing_note": (
                "Free items and missing prices are excluded from paid-price "
                "comparability."),
        },
        "item_age_distribution": {
            **_distribution(ages, "days"),
            "missing_created_at_n": excluded_undated,
            "missing_created_at_included": False,
            "window_days": int(sample_window_days),
        },
        "recent_observations": {
            "last_14d": sum(1 for a in ages if a <= 14),
            "last_30d": sum(1 for a in ages if a <= 30),
            "window_days": 14,
            "sample_n": len(ages),
            "sample_window_days": int(sample_window_days),
        },
        "creator": creator,
    }


def _marketplace_evidence(live):
    if live is None:
        return {
            "available": False, "status": "not_verified",
            "error_category": None, "error": None, "partial": False,
            "sampled_results": None, "category_correct": None,
            "category_mismatched": None, "exact_title_competitors": None,
            "conceptually_related_competitors": None, "capped": None,
            "pages": None, "sample_note": None, "top_competitors": [],
            "verification_timestamp": None, "cached": False,
            "cache_age_seconds": None, "observed_at": None,
        }
    ok = bool(live.get("ok"))
    error = live.get("error")
    lowered = str(error or "").lower()
    if not ok:
        if "429" in lowered or "rate" in lowered or "circuit" in lowered:
            category = "HTTP_429" if "429" in lowered else "rate_limited"
        elif "403" in lowered:
            category = "HTTP_403"
        elif "timeout" in lowered or "timed out" in lowered:
            category = "timeout"
        elif "server error" in lowered:
            category = "HTTP_5xx"
        else:
            category = "other"
    else:
        category = None
    return {
        "available": ok,
        "status": "ok" if ok else "unavailable",
        "error_category": category,
        "error": error,
        "partial": bool(ok and (live.get("deferred")
                                or live.get("retry_after") is not None)),
        "sampled_results": live.get("sampled_results"),
        "category_correct": live.get("category_correct"),
        "category_mismatched": live.get("category_mismatched"),
        "exact_title_competitors": live.get("exact_title_matches"),
        "conceptually_related_competitors": live.get("conceptual_matches"),
        "capped": live.get("capped"),
        "pages": live.get("pages"),
        "sample_note": live.get("sample_note"),
        "top_competitors": live.get("top_competitors") or [],
        "verification_timestamp": live.get("verification_timestamp"),
        "cached": bool(live.get("cached")),
        "cache_age_seconds": live.get("cache_age_seconds"),
        "observed_at": (live.get("observed_at")
                        or live.get("verification_timestamp")),
    }


def _creator_context(summary, category_context):
    context = category_context or {}
    registry = context.get("registry") or {"available": False,
                                           "reason": "not_queried"}
    comparison = context.get("comparison") or {}
    coverage = summary.get("identity_coverage_pct")
    unresolved_types = summary.get("unknown_creator_type_items") or 0
    limited = (not registry.get("available", False)
               or coverage is None or coverage < 50.0
               or unresolved_types > 0)
    verification = summary.get("verification_counts") or {}
    if registry.get("available"):
        uncertainty = (
            "registry-backed; "
            f"{registry.get('unknown_verification', 0)} unknown-verification "
            "creators")
    elif verification.get("unknown", 0) > 0:
        uncertainty = "partial item-level badges; registry unavailable"
    else:
        uncertainty = "unknown; registry unavailable"
    return {
        **summary,
        "registry": registry,
        "registry_available": bool(registry.get("available")),
        "registry_comparison": ({
            "creators": comparison.get("creators"),
            "segments": comparison.get("segments"),
            "concentration": comparison.get("concentration"),
            "sample": comparison.get("sample"),
        } if registry.get("available") else None),
        "category_snapshot_coverage": context.get("snapshot_coverage"),
        "creator_level_confidence_limited": limited,
        "creator_verification_uncertainty": uncertainty,
        "limitations": [
            ("Creator Registry unavailable; stable-ID creator metrics are "
             "limited to the item sample.") if not registry.get("available")
            else "Creator Registry available; category comparison is bounded.",
            ("Confirmed composite identity coverage below 50%; creator "
             "participation and concentration are not representative.") if (
                coverage is not None and coverage < 50.0) else
            ("Confirmed composite identity coverage unavailable."
             if coverage is None else
             "Creator identity coverage is item-sample based, not population "
             "coverage."),
            (f"{unresolved_types} sampled items have numeric creator IDs but "
             "no confirmed User/Group creator type; they are not counted as "
             "independent creators.") if unresolved_types else
            "All sampled numeric creator IDs have confirmed User/Group types.",
        ],
    }


def _growth_evidence(candidate):
    measured = bool(candidate.get("velocity_measured"))
    velocity = candidate.get("velocity") if measured else None
    return {
        "measured": measured,
        "velocity_per_day": velocity,
        "snapshot_item_count": int(candidate.get("observations") or 0),
        "measurement_window": (
            "last 14 days; per-item snapshot span >= 2 days" if measured
            else None),
        "stale": bool(candidate.get("stale")),
        "freshness": candidate.get("freshness"),
        "source": "convergence_engine._score_keyword snapshot query",
        "limitations": ([
            "Growth is unavailable because no qualifying snapshot pair exists; "
            "this is not zero growth."
        ] if not measured else []),
    }


def _evidence_checks(bundle):
    db = bundle["database"]
    market = bundle["marketplace"]
    creator = bundle["creator"]
    sales = bundle["sales"]
    growth = db["snapshot_growth"]
    recent = db["recent_item_observations"]
    supply = db.get("sample_size") or 0
    checks = [
        ("database_sample", supply >= 3,
         f"{supply} matching items with favorites > 5"),
        ("marketplace_verified",
         market["available"] and (market["category_correct"] or 0) > 0,
         "live sample has correct-category results"),
        ("growth_measured", growth["measured"],
         "snapshot velocity measured" if growth["measured"]
         else "no qualifying snapshot pair"),
        ("creator_identity_coverage",
         (creator.get("resolved_composite_coverage_pct") or 0) >= 50.0,
         ">=50% of sampled items have confirmed User/Group composite IDs"),
        ("independent_creators",
         (creator.get("identified_creator_count") or 0) >= 3,
         "at least three confirmed composite creator identities"),
        ("recent_observations",
         (recent.get("last_14d") or 0) > 0 and not growth["stale"],
         "recent item observations are fresh"),
        ("price_comparability",
         (db["price_distribution"].get("sample_n") or 0) >= 2,
         "at least two paid prices observed"),
        ("age_observability",
         (db["item_age_distribution"].get("sample_n") or 0) >= 2,
         "at least two item creation timestamps observed"),
        ("sample_not_capped",
         not bool(market.get("capped")) and not bool(db.get("sample_capped")),
         "marketplace and database samples are not capped"),
        ("sales_attribution", sales.get("status") == "confirmed",
         "confirmed exact-asset-ID sales present"),
    ]
    available = sum(1 for _, ok, _ in checks if ok)
    pct = round(100.0 * available / len(checks), 1)
    if (available >= 8 and market["available"] and growth["measured"]
            and not growth["stale"]):
        quality = "HIGH"
    elif available >= 5 and market["available"]:
        quality = "MEDIUM"
    elif available >= 2:
        quality = "LOW"
    else:
        quality = "INSUFFICIENT"
    return {
        "completeness_pct": pct,
        "checks_available": available,
        "checks_total": len(checks),
        "quality": quality,
        "checks": [
            {"name": name, "status": "observed" if ok else "missing",
             "detail": detail}
            for name, ok, detail in checks
        ],
        "missing_checks": [name for name, ok, _ in checks if not ok],
    }


def _contradictions(bundle):
    db = bundle["database"]
    market = bundle["marketplace"]
    creator = bundle["creator"]
    out = []
    candidate = bundle.get("_candidate") or {}
    demand = int(candidate.get("demand") or 0)
    median_favs = db.get("median_favorites")
    recent = db["recent_item_observations"].get("last_14d") or 0
    if demand >= 10 and ((median_favs is not None and median_favs < 15)
                         or recent == 0):
        out.append("high_autocomplete_weak_engagement")
    top_item = db["favorite_distribution"].get("top_item_share")
    if top_item is not None and top_item > 0.5:
        out.append("outlier_dependence")
    concentration = creator.get("creator_concentration_identified")
    name_conc = creator.get("creator_concentration_name_approx")
    if ((concentration is not None and concentration > 0.65)
            or (name_conc is not None and name_conc > 0.65)):
        out.append("creator_concentration")
    if market.get("partial"):
        out.append("marketplace_partial_results")
    growth = db["snapshot_growth"]
    if growth["measured"] and (growth["velocity_per_day"] or 0) <= 0:
        out.append("measured_flat_or_negative_growth")
    if growth.get("stale"):
        out.append("stale_observations")
    return out


def _verdict(bundle, evidence):
    db = bundle["database"]
    market = bundle["marketplace"]
    creator = bundle["creator"]
    sales = bundle["sales"]
    growth = db["snapshot_growth"]
    exact = market.get("exact_title_competitors") or 0
    correct = market.get("category_correct") or 0
    creators = creator.get("identified_creator_count") or 0
    coverage = creator.get("identity_coverage_pct")
    concentration = creator.get("creator_concentration_identified")
    name_conc = creator.get("creator_concentration_name_approx")
    top_item = db["favorite_distribution"].get("top_item_share")
    recent = db["recent_item_observations"].get("last_14d") or 0
    price_n = db["price_distribution"].get("sample_n") or 0
    age_n = db["item_age_distribution"].get("sample_n") or 0
    contradictions = bundle["contradictory_evidence"]
    sales_confirmed = sales.get("status") == "confirmed"
    stale = growth.get("stale")
    capped = bool(market.get("capped")) or bool(db.get("sample_capped"))
    concentration_risk = (
        (concentration is not None and concentration > 0.65)
        or (name_conc is not None and name_conc > 0.65))
    outlier = top_item is not None and top_item > 0.5

    reasons = []
    if not market["available"]:
        reasons.append(
            "Marketplace verification unavailable "
            f"({market.get('error_category') or 'not verified'}); missing "
            "results are not zero competition.")
        return VERDICT_INSUFFICIENT, reasons, (
            "Do not pursue yet; obtain a successful marketplace verification "
            "without increasing the API budget.")
    if correct == 0:
        reasons.append(
            "No correct-category matches in the observed marketplace sample; "
            "this does not establish category-wide absence or demand.")
        return VERDICT_INSUFFICIENT, reasons, (
            "Do not pursue yet; confirm category presence with a bounded "
            "marketplace check.")
    if exact >= 10 or (correct >= 50 and exact >= 3):
        reasons.append(
            f"Exact-title saturation: {exact} exact and {correct} "
            "correct-category sampled results.")
        return VERDICT_REJECT, reasons, (
            "Avoid this concept; exact-title competitors already saturate the "
            "sampled marketplace.")
    if not growth["measured"]:
        if creators >= 3 and recent > 0 and not concentration_risk and not outlier:
            reasons.append(
                "Several independent creators and recent supply exist, but no "
                "qualifying snapshot pair measures growth.")
            return VERDICT_INVESTIGATE, reasons, (
                "Collect at least two valid snapshots spanning one hour before "
                "judging demand.")
        reasons.append(
            "Growth is unmeasured; favorites or low competition alone do not "
            "establish demand.")
        return VERDICT_INSUFFICIENT, reasons, (
            "Do not pursue yet; obtain measured growth and independent creator "
            "evidence.")
    velocity = growth.get("velocity_per_day")
    if (velocity or 0) <= 0:
        if sales_confirmed and creators >= 3:
            reasons.append(
                "Measured growth is flat or negative, but confirmed exact-asset "
                "sales exist.")
            return VERDICT_INVESTIGATE, reasons, (
                "Investigate whether confirmed sales persist without favorite "
                "growth.")
        reasons.append(
            "Measured growth is flat or negative; this is not a growth signal.")
        return VERDICT_INSUFFICIENT, reasons, (
            "Do not pursue yet; wait for positive measured growth.")
    if creators < 2 or concentration_risk or outlier:
        reasons.append(
            "Creator concentration or single-item outlier dependence "
            "undermines independent demand.")
        return (VERDICT_INVESTIGATE if creators >= 2 else VERDICT_INSUFFICIENT,
                reasons,
                "Sample more independent creators and items before validating.")
    if stale or "marketplace_partial_results" in contradictions:
        reasons.append(
            "Observations are stale or the marketplace sample is partial.")
        return VERDICT_INVESTIGATE, reasons, (
            "Refresh observations on the next scheduled cycle; do not increase "
            "API frequency.")
    if (creators >= 3 and (coverage or 0) >= 50 and price_n >= 2
            and age_n >= 2 and not capped
            and evidence["quality"] in ("HIGH", "MEDIUM")
            and not any(c in contradictions for c in (
                "high_autocomplete_weak_engagement", "outlier_dependence",
                "creator_concentration", "marketplace_wrong_category_results"))):
        reasons.append(
            f"Measured velocity {velocity}/day, {creators} identified creators, "
            "correct-category competition, and comparable prices/ages.")
        return VERDICT_VALIDATE, reasons, (
            "Run a small bounded listing experiment and compare outcomes "
            "against a matched cohort; favorites are not sales.")
    reasons.append(
        "Evidence is incomplete or capped; a positive recommendation is not "
        "justified yet.")
    return VERDICT_INVESTIGATE, reasons, (
        "Fill the missing evidence (growth, creator identity, price/age "
        "comparability, or complete sample) before experimenting.")


def build_evidence_bundle(candidate, live, item_rows, category_context,
                          sales_evidence, sample_limit=200,
                          sample_window_days=DEFAULT_SAMPLE_WINDOW_DAYS,
                          undated_matches=0, undated_capped=False, now=None,
                          db_error=None):
    """Pure evidence-bundle builder. All missing values remain explicit None."""
    now = now or _now()
    summary = summarize_item_sample(
        item_rows, now=now, sample_limit=sample_limit,
        undated_matches=undated_matches, undated_capped=undated_capped,
        sample_window_days=sample_window_days)
    market = _marketplace_evidence(live)
    creator = _creator_context(summary["creator"], category_context)
    growth = _growth_evidence(candidate)
    sales = sales_evidence or {
        "available": False, "status": "unavailable",
        "attribution": None, "confirmed_units": None,
        "confirmed_robux": None, "limitations": [SALES_UNAVAILABLE],
    }
    median_favs = candidate.get("median_favs")
    median_source = "convergence_engine_all_time"
    median_bounded = False
    if median_favs is None:
        median_favs = summary["favorite_distribution"].get("median")
        median_source = "bounded_item_sample"
        median_bounded = True
    database = {
        "sample_size": int(candidate.get("supply") or 0),
        "sample_size_source": "convergence_engine_all_time",
        "distribution_sample_size": summary["sample_items"],
        "sample_window_days": int(sample_window_days),
        "sample_window_enforced": True,
        "sample_limit": int(sample_limit),
        "sample_capped": summary["sample_capped"],
        "distribution_ordering": "favorite_count_desc_convenience",
        "distribution_representative": False,
        "distribution_sample_created_at_min": summary[
            "sample_created_at_min"],
        "distribution_sample_created_at_max": summary[
            "sample_created_at_max"],
        "undated_matches_excluded": summary["undated_excluded_n"],
        "undated_matches_capped": summary["undated_capped"],
        "median_favorites": median_favs,
        "median_favorites_source": median_source,
        "median_favorites_is_bounded": median_bounded,
        "favorite_distribution": summary["favorite_distribution"],
        "recent_item_observations": {
            **summary["recent_observations"],
            "candidate_recent_14d": candidate.get("recent"),
            "candidate_recent_source": "convergence_engine_all_time",
            "bounded_sample_source": "item-age sample within enforced window",
        },
        "price_distribution": summary["price_distribution"],
        "item_age_distribution": summary["item_age_distribution"],
        "convergence_all_time": {
            "supply": int(candidate.get("supply") or 0),
            "median_favorites": candidate.get("median_favs"),
            "recent_14d": candidate.get("recent"),
            "source": "convergence_engine._score_keyword",
        },
        "bounded_item_sample": {
            "window_days": int(sample_window_days),
            "ordering": "favorite_count_desc_convenience",
            "representative": False,
            "sample_n": summary["sample_items"],
            "sample_limit": int(sample_limit),
            "capped": summary["sample_capped"],
            "created_at_min": summary["sample_created_at_min"],
            "created_at_max": summary["sample_created_at_max"],
            "undated_excluded_n": summary["undated_excluded_n"],
            "undated_capped": summary["undated_capped"],
        },
        "snapshot_growth": growth,
        "db_error": db_error,
    }
    bundle = {
        "schema_version": "m3.opportunity_evidence.v1",
        "candidate": {
            "keyword": candidate.get("keyword"),
            "concept": candidate.get("keyword"),
            "asset_family": candidate.get("family"),
            "convergence_score": candidate.get("score"),
            "score_label": (
                "existing convergence heuristic rank score; not a probability"),
        },
        "database": database,
        "marketplace": market,
        "creator": creator,
        "sales": sales,
        "source_timestamps": {
            "database_sampled_at": now.isoformat(),
            "live_verification_at": market.get("verification_timestamp"),
            "creator_evidence_generated_at": (category_context or {}).get(
                "generated_at"),
            "sales_window_end": sales.get("window_end"),
        },
        "missing_evidence": [],
        "contradictory_evidence": [],
        "confidence_limitations": [],
        "investigation_verdict": None,
        "verdict_reasons": [],
        "next_validation": None,
        "_candidate": candidate,
    }
    if not market["available"]:
        bundle["missing_evidence"].append("marketplace_verification")
    if not growth["measured"]:
        bundle["missing_evidence"].append("measured_snapshot_growth")
    if sales.get("status") != "confirmed":
        bundle["missing_evidence"].append("confirmed_attributable_sales")
    if not summary["price_distribution"].get("available"):
        bundle["missing_evidence"].append("price_evidence")
    if not summary["item_age_distribution"].get("available"):
        bundle["missing_evidence"].append("creation_timestamp_evidence")
    if summary["undated_excluded_n"]:
        bundle["missing_evidence"].append("undated_items_excluded")
    if not creator.get("registry_available"):
        bundle["missing_evidence"].append("creator_registry")
    if (creator.get("identity_coverage_pct") or 0) < 50.0:
        bundle["missing_evidence"].append("creator_identity_coverage")
    if creator.get("unknown_creator_type_items"):
        bundle["missing_evidence"].append("creator_type_unknown")
    if ((creator.get("numeric_id_coverage_pct") or 0)
            > (creator.get("resolved_composite_coverage_pct") or 0)):
        bundle["missing_evidence"].append(
            "resolved_composite_identity_coverage")
    if summary["sample_capped"]:
        bundle["missing_evidence"].append("complete_database_sample")
    if market.get("capped"):
        bundle["missing_evidence"].append("complete_marketplace_sample")
    bundle["contradictory_evidence"] = _contradictions(bundle)
    bundle["confidence_limitations"] = (
        list(bundle["missing_evidence"])
        + list(bundle["contradictory_evidence"])
        + list(creator.get("limitations") or [])
        + list(sales.get("limitations") or [])
        + list(growth.get("limitations") or [])
    )
    bundle["confidence_limitations"].append(
        "Item distributions are popularity-ordered convenience samples inside "
        f"the enforced {int(sample_window_days)}-day window; they are not "
        "statistically representative.")
    if summary["undated_excluded_n"]:
        bundle["confidence_limitations"].append(
            f"{summary['undated_excluded_n']} matching items lacked creation "
            "timestamps and were excluded from the bounded distribution.")
    if market.get("sample_note"):
        bundle["confidence_limitations"].append(market["sample_note"])
    if not market["available"] and market.get("error"):
        bundle["confidence_limitations"].append(
            f"live error: {market['error']}")
    evidence = _evidence_checks(bundle)
    bundle["evidence"] = evidence
    verdict, reasons, next_step = _verdict(bundle, evidence)
    bundle["investigation_verdict"] = verdict
    bundle["verdict_reasons"] = reasons
    bundle["next_validation"] = next_step
    bundle.pop("_candidate", None)
    return bundle


def build_category_context(cur, family, days=180, limit=5000, now=None):
    """One bounded Creator Intelligence query per category."""
    from creator_registry import creator_evidence
    try:
        return creator_evidence(cur, family=family, days=days, limit=limit)
    except Exception as exc:
        return {
            "generated_at": (now or _now()).isoformat(),
            "category": family or "all",
            "registry": {"available": False, "error": type(exc).__name__},
            "comparison": {},
            "snapshot_coverage": {},
            "error": type(exc).__name__,
        }


def build_validation_bundles(detailed, verified, family, cur, now=None,
                             item_limit=200, sample_window_days=(
                                 DEFAULT_SAMPLE_WINDOW_DAYS),
                             sales_days=90):
    """Build one bundle per existing shortlist candidate. No discovery/live pass."""
    candidates = ((detailed or {}).get("shortlist")
                  or (detailed or {}).get("candidates") or [])
    if not candidates:
        return []
    verified = verified or {}
    context = build_category_context(cur, family, now=now)
    has_type = has_creator_type(cur)
    bundles = []
    for candidate in candidates:
        keyword = candidate.get("keyword")
        rows = []
        db_error = None
        undated = {"count": 0, "capped": False}
        try:
            rows = fetch_item_sample(
                cur, keyword, family, limit=item_limit, has_type=has_type,
                sample_window_days=sample_window_days)
            undated = count_undated_matches(
                cur, keyword, family, limit=item_limit)
        except Exception as exc:
            db_error = type(exc).__name__
        asset_ids = [r.get("id") for r in rows if r.get("id") is not None]
        try:
            sales = fetch_sales_evidence(cur, asset_ids, days=sales_days,
                                         now=now)
            if sales.get("available"):
                sales["limitations"].append(
                    "Sales attribution is limited to exact asset IDs in the "
                    "bounded item sample.")
        except Exception as exc:
            sales = {
                "available": False, "status": "unavailable",
                "attribution": None, "confirmed_units": None,
                "confirmed_robux": None,
                "limitations": [f"Sales evidence error: {type(exc).__name__}"],
            }
        bundles.append(build_evidence_bundle(
            candidate, verified.get(keyword), rows, context, sales,
            sample_limit=item_limit, sample_window_days=sample_window_days,
            undated_matches=undated.get("count", 0),
            undated_capped=undated.get("capped", False),
            now=now, db_error=db_error))
    return bundles


def _fmt_number(value, suffix=""):
    if value is None:
        return "unavailable"
    if isinstance(value, float):
        return f"{value:,.2f}{suffix}"
    return f"{value:,}{suffix}"


def format_bundle(bundle):
    """Concise, deterministic Discord-ready evidence report for one candidate."""
    candidate = bundle["candidate"]
    db = bundle["database"]
    market = bundle["marketplace"]
    creator = bundle["creator"]
    sales = bundle["sales"]
    growth = db["snapshot_growth"]
    fav = db["favorite_distribution"]
    price = db["price_distribution"]
    age = db["item_age_distribution"]
    identified_conc = creator.get("creator_concentration_identified")
    name_conc = creator.get("creator_concentration_name_approx")
    verified_at = (market.get("observed_at")
                   or market.get("verification_timestamp") or "?")[:19]
    lines = [
        "🎯 VANTA OPPORTUNITY VALIDATION",
        f"Concept: `{candidate.get('concept')}` · "
        f"{candidate.get('asset_family') or 'all'}",
        (f"Database Evidence: supply {_fmt_number(db.get('sample_size'))} "
         f"(all-time, favorites>5); median "
         f"{_fmt_number(db.get('median_favorites'))}♥ "
         f"({db.get('median_favorites_source')}); bounded distribution "
         f"n={db.get('distribution_sample_size')} "
         f"(last {db.get('sample_window_days')}d, popularity-ordered "
         f"convenience sample, not representative; undated excluded "
         f"{_fmt_number(db.get('undated_matches_excluded'))}); "
         f"favorite p25–p75 {_fmt_number(fav.get('p25'))}–"
         f"{_fmt_number(fav.get('p75'))}; recent14 "
         f"{_fmt_number(db['recent_item_observations'].get('last_14d'))}"
         + (" (capped)" if db.get("sample_capped") else "")),
        (f"Marketplace Competition: sampled "
         f"{_fmt_number(market.get('sampled_results'))}, correct-category "
         f"{_fmt_number(market.get('category_correct'))}, exact-title "
         f"{_fmt_number(market.get('exact_title_competitors'))}, related "
         f"{_fmt_number(market.get('conceptually_related_competitors'))}"
         + (" · capped" if market.get("capped") else "")
         + (" · partial" if market.get("partial") else "")
         + (" · cached (age "
            f"{_fmt_number(market.get('cache_age_seconds'), 's')})"
            if market.get("cached") else
            (f" · verified {verified_at}"
             if market.get("available") else
             f" · unavailable ({market.get('error_category')})"))),
        (f"Creator Intelligence: "
         f"{_fmt_number(creator.get('numeric_creator_count'))} numeric IDs / "
         f"{_fmt_number(creator.get('identified_creator_count'))} confirmed "
         f"composite / "
         f"{_fmt_number(creator.get('unknown_creator_type_items'))} unknown-type "
         f"items / {_fmt_number(creator.get('unknown_identity_items'))} no-ID; "
         f"numeric-ID coverage "
         f"{_fmt_number(creator.get('numeric_id_coverage_pct'), '%')}; "
         f"composite coverage "
         f"{_fmt_number(creator.get('resolved_composite_coverage_pct'), '%')}; "
         f"stable-ID concentration "
         f"{_fmt_number(identified_conc * 100 if identified_conc is not None else None, '%')}; "
         f"name-approx "
         f"{_fmt_number(name_conc * 100 if name_conc is not None else None, '%')}; "
         f"registry {'available' if creator.get('registry_available') else 'unavailable'}"),
        (f"Growth: {_fmt_number(growth.get('velocity_per_day'), '/day')} "
         f"({growth.get('snapshot_item_count')} snapshot items; "
         f"{growth.get('measurement_window') or 'unavailable'})"
         if growth.get("measured") else
         "Growth: unavailable (no qualifying snapshot pair)"),
        (f"Price: n={_fmt_number(price.get('sample_n'))} · median "
         f"{_fmt_number(price.get('median'), ' R$')} · missing "
         f"{_fmt_number(price.get('missing_n'))} · free "
         f"{_fmt_number(price.get('free_n'))}; Age n={_fmt_number(age.get('sample_n'))} "
         f"median {_fmt_number(age.get('median'), 'd')}"),
        ("Sales: " + (
            f"confirmed {_fmt_number(sales.get('confirmed_units'))} units / "
            f"{_fmt_number(sales.get('confirmed_robux'))} R$ via exact asset IDs "
            f"(last {_fmt_number(sales.get('window_days'))}d)"
            if sales.get("status") == "confirmed" else
            "No exact-asset-attributable sales in the window."
            if sales.get("status") == "no_exact_asset_sales" else
            SALES_UNAVAILABLE)),
        ("Risks: " + (", ".join(
            list(bundle.get("contradictory_evidence") or [])
            + [m for m in (bundle.get("missing_evidence") or [])
               if m not in (bundle.get("contradictory_evidence") or [])][:4]
        ) or "none identified")),
        (f"Evidence Quality: {bundle['evidence']['quality']} "
         f"({bundle['evidence']['checks_available']}/"
         f"{bundle['evidence']['checks_total']} checks; missing: "
         f"{', '.join(bundle['evidence']['missing_checks'][:4]) or 'none'})"),
        (f"Heuristic score: {_fmt_number(candidate.get('convergence_score'))} "
         f"({candidate.get('score_label')})"),
        f"Verdict: {bundle['investigation_verdict']}",
        f"Next Validation: {bundle['next_validation']}",
    ]
    return "\n".join(lines)


def format_validation_report(bundles, family="all"):
    family = family or "all"
    if not bundles:
        return (
            "🎯 VANTA OPPORTUNITY VALIDATION\n"
            f"Category: {family}\n\n"
            "No qualifying candidates. An empty shortlist is a valid outcome; "
            "no recommendation was forced and no missing evidence was treated "
            "as demand.")
    sections = [
        "# 🎯 VANTA OPPORTUNITY VALIDATION — "
        f"{family}\n"
        "_Research evidence only; favorites and autocomplete are not sales. "
        "Missing evidence is not zero._\n"
    ]
    for bundle in bundles:
        sections.append(format_bundle(bundle))
        sections.append("")
    return "\n".join(sections)


def render_converge_report(detailed, verified, family, get_db,
                           legacy_formatter):
    """Flag-gated integration point for the existing !converge command."""
    if not m3_enabled():
        return legacy_formatter(detailed, verified, family)
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        bundles = build_validation_bundles(detailed, verified, family, cur)
        return format_validation_report(bundles, family)
    except Exception as exc:
        return (
            "⚠️ M3 opportunity validation unavailable; no evidence-based "
            f"verdict was produced. Reason: {type(exc).__name__}.")
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
