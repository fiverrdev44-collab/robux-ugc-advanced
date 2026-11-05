"""
creator_registry.py — additive Creator Intelligence registry.

Keyed by (creator_type, creator_id), never by display name. Missing creator
type/verification stays unknown; missing values are never treated as confirmed
nonverified or non-sales. Reads existing items/tracked_creators and writes only
the additive creator_registry table (staging/approval required).

No Roblox API calls are made here: discovery reuses already-collected catalog
rows, so the live API budget is unchanged.
"""
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone


def _median(values):
    vals = sorted(v for v in values if v is not None)
    n = len(vals)
    if n == 0:
        return None
    if n % 2:
        return vals[n // 2]
    return (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def _as_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _price_bucket(price):
    if price is None or price <= 0:
        return "unknown"
    if price < 30:
        return "under_30"
    if price < 60:
        return "30_to_60"
    if price < 100:
        return "60_to_100"
    if price < 200:
        return "100_to_200"
    if price < 500:
        return "200_to_500"
    return "500_plus"


def _age_days(created_at, now):
    created = _as_utc(created_at)
    if created is None or now is None:
        return None
    return (now - created).total_seconds() / 86400.0


def _verification(values):
    """Tri-state verification with provenance; NULL is unknown."""
    known = [v for v in values if v is not None]
    if any(v is True for v in known):
        provenance = ("catalog_flag_mixed"
                      if any(v is False for v in known)
                      else "catalog_flag")
        return "verified", provenance
    if any(v is False for v in known):
        return "nonverified", "catalog_flag"
    return "unknown", "missing"


def resolve_creator_type(item_type, tracked_type, item_name, tracked_name):
    """Resolve a creator type without relying on numeric ID alone.

    The catalog item's own creator_type is authoritative. A tracked creator's
    type is used only when the display name corroborates the composite
    identity. Otherwise the type stays unknown.
    """
    if item_type:
        return item_type, "item_catalog"
    if (tracked_type and item_name and tracked_name
            and item_name.strip().lower() == tracked_name.strip().lower()):
        return tracked_type, "tracked_name_match"
    return "unknown", "missing"


def _items_has_creator_type(cur):
    try:
        cur.execute(
            "select 1 from information_schema.columns "
            "where table_schema = current_schema() "
            "and table_name = 'items' and column_name = 'creator_type'")
        return cur.fetchone() is not None
    except Exception:
        return False


def build_registry_rows(item_rows, now=None):
    """Aggregate item-level rows into registry rows (pure).

    Row shape:
      (item_id, creator_type, creator_id, creator_name, creator_verified,
       asset_type_id, price, favorite_count, created_at, fetched_at,
       snapshot_count, type_provenance)
    """
    now = now or datetime.now(timezone.utc)
    diagnostics = {
        "items_total": 0,
        "items_missing_creator_id": 0,
        "items_missing_creator_type": 0,
        "duplicate_item_rows_removed": 0,
        "creators": 0,
    }

    # Deduplicate repeated marketplace rows per (creator, item).
    unique = {}
    for row in item_rows:
        (item_id, creator_type, creator_id, creator_name, creator_verified,
         asset_type_id, price, favorite_count, created_at, fetched_at,
         snapshot_count, type_provenance) = row
        diagnostics["items_total"] += 1
        if creator_id is None:
            diagnostics["items_missing_creator_id"] += 1
            continue
        ctype = (creator_type or "").strip() or "unknown"
        if ctype == "unknown":
            diagnostics["items_missing_creator_type"] += 1
        observed = _as_utc(fetched_at) or _as_utc(created_at)
        key = (ctype, int(creator_id))
        item_key = (ctype, int(creator_id), item_id)
        if item_key in unique:
            diagnostics["duplicate_item_rows_removed"] += 1
            previous = unique[item_key]
            previous_observed = (_as_utc(previous[9])
                                 or _as_utc(previous[8]))
            if observed and (previous_observed is None
                             or observed > previous_observed):
                unique[item_key] = row
            continue
        unique[item_key] = row

    grouped = defaultdict(list)
    for row in unique.values():
        ctype = (row[1] or "").strip() or "unknown"
        grouped[(ctype, int(row[2]))].append(row)

    rows = []
    for (ctype, creator_id), group in grouped.items():
        names = []
        for row in group:
            name = (row[3] or "").strip()
            observed = _as_utc(row[9]) or _as_utc(row[8])
            if name:
                names.append((observed, name))
        display_name = (max(names, key=lambda x: (x[0] or datetime.min.replace(
            tzinfo=timezone.utc), x[1]))[1] if names else None)
        names_seen = sorted({name for _observed, name in names})
        previous_names = [n for n in names_seen if n != display_name]

        verification, provenance = _verification([row[4] for row in group])
        incoming_provenances = {row[11] for row in group if row[11]}
        if "item_catalog" in incoming_provenances:
            type_prov = "item_catalog"
        elif "tracked_name_match" in incoming_provenances:
            type_prov = "tracked_name_match"
        elif "tracked_creator" in incoming_provenances:
            type_prov = "tracked_creator"
        else:
            type_prov = "missing"

        observed_times = [
            _as_utc(row[9]) or _as_utc(row[8]) for row in group]
        observed_times = [t for t in observed_times if t is not None]
        created_times = [
            _as_utc(row[8]) for row in group if row[8] is not None]

        favorites = [int(row[7]) for row in group
                     if row[7] is not None]
        missing_favorites = sum(1 for row in group if row[7] is None)
        prices = [int(row[6]) for row in group
                  if row[6] is not None and int(row[6]) > 0]
        ages = [_age_days(row[8], now) for row in group
                if row[8] is not None]
        snapshots = [int(row[10] or 0) for row in group]

        rows.append({
            "creator_type": ctype,
            "creator_id": creator_id,
            "display_name": display_name,
            "verification_status": verification,
            "verification_provenance": provenance,
            "type_provenance": type_prov,
            "first_seen": min(observed_times) if observed_times else None,
            "last_seen": max(observed_times) if observed_times else None,
            "item_count": len({row[0] for row in group}),
            "category_counts": dict(Counter(
                str(row[5]) if row[5] is not None else "unknown"
                for row in group)),
            "price_counts": dict(Counter(_price_bucket(row[6])
                                         for row in group)),
            "median_favorites": _median(favorites),
            "median_price": _median(prices),
            "median_age_days": (round(_median(ages), 2)
                                if _median(ages) is not None else None),
            "snapshot_item_count": sum(1 for n in snapshots if n >= 2),
            "max_snapshots": max(snapshots, default=0),
            "missing_favorite_items": missing_favorites,
            "previous_names": previous_names,
            "published_first": min(created_times) if created_times else None,
            "published_last": max(created_times) if created_times else None,
        })

    rows.sort(key=lambda r: (r["creator_type"], r["creator_id"]))
    diagnostics["creators"] = len(rows)
    return {"rows": rows, "diagnostics": diagnostics}


_UPSERT_SQL = """
    INSERT INTO creator_registry (
        creator_type, creator_id, display_name, verification_status,
        verification_provenance, type_provenance, first_seen, last_seen,
        item_count, category_counts, price_counts, median_favorites,
        median_price, median_age_days, snapshot_item_count, max_snapshots,
        missing_favorite_items, previous_names)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
            %s, %s, %s, %s, %s, %s, %s::jsonb)
    ON CONFLICT (creator_type, creator_id) DO UPDATE SET
        display_name = COALESCE(NULLIF(EXCLUDED.display_name, ''),
                                creator_registry.display_name),
        verification_status = CASE
            WHEN EXCLUDED.verification_status = 'unknown'
                THEN creator_registry.verification_status
            ELSE EXCLUDED.verification_status END,
        verification_provenance = CASE
            WHEN EXCLUDED.verification_provenance = 'missing'
                THEN creator_registry.verification_provenance
            ELSE EXCLUDED.verification_provenance END,
        type_provenance = CASE
            WHEN creator_registry.type_provenance = 'tracked_creator'
              OR EXCLUDED.type_provenance = 'tracked_creator'
                THEN 'tracked_creator'
            ELSE EXCLUDED.type_provenance END,
        first_seen = LEAST(creator_registry.first_seen, EXCLUDED.first_seen),
        last_seen = GREATEST(creator_registry.last_seen, EXCLUDED.last_seen),
        item_count = EXCLUDED.item_count,
        category_counts = EXCLUDED.category_counts,
        price_counts = EXCLUDED.price_counts,
        median_favorites = EXCLUDED.median_favorites,
        median_price = EXCLUDED.median_price,
        median_age_days = EXCLUDED.median_age_days,
        snapshot_item_count = EXCLUDED.snapshot_item_count,
        max_snapshots = EXCLUDED.max_snapshots,
        missing_favorite_items = EXCLUDED.missing_favorite_items,
        previous_names = COALESCE((
            SELECT jsonb_agg(DISTINCT n ORDER BY n)
            FROM jsonb_array_elements_text(
                creator_registry.previous_names
                || EXCLUDED.previous_names
                || CASE
                    WHEN NULLIF(EXCLUDED.display_name, '') IS NOT NULL
                     AND creator_registry.display_name IS DISTINCT FROM
                         EXCLUDED.display_name
                    THEN jsonb_build_array(creator_registry.display_name)
                    ELSE '[]'::jsonb
                END
            ) AS t(n)
            WHERE n IS NOT NULL
              AND n <> COALESCE(NULLIF(EXCLUDED.display_name, ''),
                                creator_registry.display_name, '')
        ), '[]'::jsonb),
        updated_at = CURRENT_TIMESTAMP
"""


def upsert_registry(cur, rows):
    """Idempotently upsert registry rows; preserves first_seen and names."""
    written = 0
    for row in rows:
        cur.execute(_UPSERT_SQL, (
            row["creator_type"], row["creator_id"], row["display_name"],
            row["verification_status"], row["verification_provenance"],
            row["type_provenance"], row["first_seen"], row["last_seen"],
            row["item_count"], json.dumps(row["category_counts"]),
            json.dumps(row["price_counts"]), row["median_favorites"],
            row["median_price"], row["median_age_days"],
            row["snapshot_item_count"], row["max_snapshots"],
            row["missing_favorite_items"],
            json.dumps(row["previous_names"]),
        ))
        written += 1
    return written


_REFRESH_SQL = """
    WITH typed AS (
        SELECT i.id, i.creator_id, i.creator_name, i.creator_verified,
               i.asset_type_id, i.price, i.favorite_count, i.created_at,
               i.fetched_at,
               COALESCE(NULLIF(i.creator_type, ''),
                        t.creator_type,
                        'unknown') AS creator_type,
               CASE
                   WHEN NULLIF(i.creator_type, '') IS NOT NULL
                       THEN 'item_catalog'
                   WHEN t.creator_type IS NOT NULL
                       THEN 'tracked_name_match'
                   ELSE 'missing'
               END AS type_provenance
        FROM items i
        LEFT JOIN LATERAL (
            SELECT t2.creator_type
            FROM tracked_creators t2
            WHERE t2.creator_id = i.creator_id
              AND t2.creator_type IS NOT NULL
              AND lower(t2.creator_name) = lower(i.creator_name)
            ORDER BY t2.creator_type
            LIMIT 1
        ) t ON true
        WHERE i.creator_id IS NOT NULL
    ),
    batch_keys AS (
        SELECT DISTINCT creator_type, creator_id
        FROM typed
        WHERE (%s IS NULL OR (creator_type, creator_id) > (%s, %s))
        ORDER BY creator_type, creator_id
        LIMIT %s
    )
    SELECT ty.id, ty.creator_type, ty.creator_id, ty.creator_name,
           ty.creator_verified, ty.asset_type_id, ty.price,
           ty.favorite_count, ty.created_at, ty.fetched_at,
           COALESCE(h.snapshots, 0), ty.type_provenance
    FROM typed ty
    JOIN batch_keys bk
      ON bk.creator_type = ty.creator_type
     AND bk.creator_id = ty.creator_id
    LEFT JOIN LATERAL (
        SELECT count(*) AS snapshots
        FROM item_history ih
        WHERE ih.item_id = ty.id
    ) h ON true
    ORDER BY ty.creator_type, ty.creator_id, ty.id
"""


def refresh_from_items(cur, batch_size=500, max_batches=None, cursor=None,
                       now=None):
    """Rebuild the registry from stored items in resumable creator batches.

    ``cursor`` is an explicit continuation key ``(creator_type, creator_id)``
    returned as ``next_cursor`` by a previous invocation. Ordering is stable by
    ``(creator_type, creator_id)``; each key is visited at most once per sweep.
    If the source gains creators with keys below the cursor, they are picked up
    by the next full sweep from ``cursor=None``.

    No Roblox API calls are made. The caller owns the transaction/commit and
    must have approval before writing to the registry.
    """
    batch_size = max(1, int(batch_size))
    start_type, start_id = (cursor if cursor else (None, None))
    after_type, after_id = start_type, start_id
    done = False
    totals = {"batches": 0, "creators": 0, "items": 0,
              "items_missing_creator_id": 0,
              "items_missing_creator_type": 0,
              "duplicate_item_rows_removed": 0,
              "started_after": (list(cursor) if cursor else None)}
    while True:
        cur.execute(_REFRESH_SQL,
                    (after_type, after_type, after_id, batch_size))
        rows = cur.fetchall() or []
        if not rows:
            done = True
            break
        built = build_registry_rows(rows, now=now)
        upsert_registry(cur, built["rows"])
        diag = built["diagnostics"]
        totals["batches"] += 1
        totals["creators"] += len(built["rows"])
        totals["items"] += len(rows)
        for key in ("items_missing_creator_id", "items_missing_creator_type",
                    "duplicate_item_rows_removed"):
            totals[key] += diag.get(key, 0)
        last = rows[-1]
        after_type, after_id = last[1], last[2]
        if max_batches is not None and totals["batches"] >= int(max_batches):
            break
    totals["done"] = done
    totals["next_cursor"] = ([after_type, after_id]
                             if after_type is not None else None)
    return totals


_DISCOVER_SQL = """
    SELECT creator_type, creator_id, display_name, verification_status,
           verification_provenance, type_provenance, item_count,
           category_counts, snapshot_item_count, last_seen
    FROM creator_registry
    WHERE verification_status IN ('nonverified', 'unknown')
    ORDER BY item_count DESC, last_seen DESC NULLS LAST
    LIMIT %s
"""


def discover_nonverified(cur, limit=50):
    """Return stored nonverified/unknown creators; no live API calls."""
    cur.execute(_DISCOVER_SQL, (max(1, int(limit)),))
    rows = cur.fetchall() or []
    out = []
    for (ctype, cid, name, verification, ver_prov, type_prov,
         item_count, categories, snapshot_items, last_seen) in rows:
        out.append({
            "creator_type": ctype,
            "creator_id": cid,
            "display_name": name,
            "verification_status": verification,
            "verification_provenance": ver_prov,
            "type_provenance": type_prov,
            "item_count": int(item_count or 0),
            "category_counts": categories or {},
            "snapshot_item_count": int(snapshot_items or 0),
            "last_seen": last_seen,
            "source": "stored_catalog",
            "live_api_calls": 0,
        })
    return out


_COMPARISON_SQL = """
    SELECT i.id, {type_expr} AS creator_type,
           i.creator_id, i.creator_name, i.creator_verified,
           i.asset_type_id, i.price, i.favorite_count, i.created_at,
           i.fetched_at,
           COALESCE(h.snapshots, 0) AS snapshots
    FROM items i
    LEFT JOIN LATERAL (
        SELECT t2.creator_type
        FROM tracked_creators t2
        WHERE t2.creator_id = i.creator_id
          AND t2.creator_type IS NOT NULL
          AND lower(t2.creator_name) = lower(i.creator_name)
        ORDER BY t2.creator_type
        LIMIT 1
    ) t ON true
    LEFT JOIN LATERAL (
        SELECT count(*) AS snapshots
        FROM item_history ih
        WHERE ih.item_id = i.id
    ) h ON true
    WHERE i.creator_id IS NOT NULL
      AND i.created_at >= NOW() - make_interval(days => %s)
      {family_clause}
    ORDER BY i.id
    LIMIT %s
"""


def _summarize_segment(creators):
    return {
        "creators": len(creators),
        "items": sum(c["items"] for c in creators),
        "median_favorites": _median(
            [c["median_favorites"] for c in creators]),
        "median_price": _median([c["median_price"] for c in creators]),
        "median_age_days": _median(
            [c["median_age_days"] for c in creators]),
        "snapshot_items": sum(c["snapshot_items"] for c in creators),
    }


def summarize_comparison(item_rows, family=None, now=None):
    """Build category-aware segments from item-level rows (pure)."""
    now = now or datetime.now(timezone.utc)
    unique = {}
    for row in item_rows:
        (item_id, creator_type, creator_id, creator_name, creator_verified,
         asset_type_id, price, favorite_count, created_at, fetched_at,
         snapshots) = row
        observed = _as_utc(fetched_at) or _as_utc(created_at)
        key = (item_id, creator_type, creator_id)
        previous_observed = None
        if key in unique:
            previous_observed = (_as_utc(unique[key][9])
                                 or _as_utc(unique[key][8]))
        if key not in unique or (
                observed and (previous_observed is None
                              or observed > previous_observed)):
            unique[key] = row

    grouped = defaultdict(list)
    for row in unique.values():
        grouped[((row[1] or "unknown"), int(row[2]))].append(row)

    creators = []
    for (ctype, cid), group in grouped.items():
        names = [( _as_utc(row[9]) or _as_utc(row[8]), row[3])
                 for row in group if (row[3] or "").strip()]
        name = (max(names, key=lambda x: (x[0] or datetime.min.replace(
            tzinfo=timezone.utc), x[1]))[1] if names else None)
        verification, _prov = _verification([row[4] for row in group])
        favorites = [int(row[7]) for row in group if row[7] is not None]
        prices = [int(row[6]) for row in group
                  if row[6] is not None and int(row[6]) > 0]
        ages = [_age_days(row[8], now) for row in group
                if row[8] is not None]
        creators.append({
            "creator_type": ctype,
            "creator_id": cid,
            "display_name": name,
            "verification_status": verification,
            "items": len({row[0] for row in group}),
            "median_favorites": _median(favorites),
            "median_price": _median(prices),
            "median_age_days": _median(ages),
            "snapshot_items": sum(1 for row in group
                                  if int(row[10] or 0) >= 2),
            "missing_favorites": sum(1 for row in group if row[7] is None),
        })

    established = [c for c in creators if c["items"] >= 5]
    emerging = [c for c in creators if c["items"] < 5]
    verified = [c for c in creators if c["verification_status"] == "verified"]
    nonverified = [c for c in creators
                   if c["verification_status"] == "nonverified"]
    unknown = [c for c in creators
               if c["verification_status"] == "unknown"]

    perf = [c for c in creators if c["median_favorites"] is not None]
    perf.sort(key=lambda c: c["median_favorites"])
    if len(perf) < 3:
        bottom, middle, top = [], perf, []
    else:
        third = max(1, len(perf) // 3)
        bottom, top = perf[:third], perf[-third:]
        middle = perf[third:len(perf) - third]

    top_creator = max(creators, key=lambda c: c["items"]) if creators else None
    total_items = sum(c["items"] for c in creators)
    concentration = (top_creator["items"] / total_items
                     if top_creator and total_items else 0.0)

    return {
        "category": family or "all",
        "creators": len(creators),
        "items": total_items,
        "segments": {
            "established": _summarize_segment(established),
            "emerging": _summarize_segment(emerging),
            "verified": _summarize_segment(verified),
            "nonverified": _summarize_segment(nonverified),
            "unknown_verification": _summarize_segment(unknown),
            "top_performers": _summarize_segment(top),
            "average_performers": _summarize_segment(middle),
            "underperformers": _summarize_segment(bottom),
        },
        "concentration": {
            "top_creator": (top_creator["display_name"]
                            if top_creator else None),
            "top_creator_items": (top_creator["items"]
                                  if top_creator else 0),
            "item_share": round(concentration, 3),
        },
        "missing": {
            "items_without_favorites": sum(c["missing_favorites"]
                                           for c in creators),
            "creators_without_snapshots": sum(
                1 for c in creators if c["snapshot_items"] == 0),
            "creators_without_known_favorites": sum(
                1 for c in creators if c["median_favorites"] is None),
        },
        "selection": {
            "population": ("stored catalog items with creator IDs in the "
                           "category/age window; deterministic item-id "
                           "ordering; sampled convenience sample, not "
                           "probability-representative"),
            "favorites_not_sales": True,
            "representative": False,
            "growth_only_from_snapshots": True,
            "causal": False,
        },
    }


def creator_comparison(cur, family=None, days=180, limit=5000, now=None,
                       has_creator_type=None):
    """Fetch a bounded, deterministically ordered item sample and summarize."""
    from category_configs import get_category_config
    family_clause = ""
    params = [int(days)]
    if family:
        try:
            asset_ids = get_category_config(family).get("asset_type_ids")
        except Exception:
            asset_ids = None
        if asset_ids:
            family_clause = "AND i.asset_type_id = ANY(%s)"
            params.append(list(asset_ids))
    params.append(int(limit))
    if has_creator_type is None:
        has_creator_type = _items_has_creator_type(cur)
    type_expr = ("COALESCE(NULLIF(i.creator_type, ''), t.creator_type, "
                 "'unknown')" if has_creator_type
                 else "COALESCE(t.creator_type, 'unknown')")
    cur.execute(_COMPARISON_SQL.format(family_clause=family_clause,
                                       type_expr=type_expr),
                tuple(params))
    rows = cur.fetchall() or []
    summary = summarize_comparison(rows, family=family, now=now)
    summary["sample"] = {
        "requested_limit": int(limit),
        "returned_items": len(rows),
        "window_days": int(days),
        "order": "item_id",
        "deterministic": True,
        "representative": False,
    }
    return summary


_SNAPSHOT_COVERAGE_SQL = """
    WITH recent AS (
        SELECT id
        FROM items
        WHERE created_at >= NOW() - make_interval(hours => %s)
    ),
    snap AS (
        SELECT h.item_id, count(*) AS n,
               min(h.snapshot_at) AS first_at,
               max(h.snapshot_at) AS last_at
        FROM item_history h
        JOIN recent r ON r.id = h.item_id
        WHERE h.snapshot_at >= NOW() - make_interval(hours => %s)
          AND h.favorite_count IS NOT NULL
        GROUP BY h.item_id
    )
    SELECT count(*),
           count(*) FILTER (WHERE s.n IS NULL),
           count(*) FILTER (WHERE s.n = 1),
           count(*) FILTER (WHERE s.n >= 2),
           count(*) FILTER (WHERE s.n >= 2
                              AND EXTRACT(EPOCH FROM
                                  (s.last_at - s.first_at)) >= 3600),
           COALESCE(sum(s.n), 0)
    FROM recent r
    LEFT JOIN snap s ON s.item_id = r.id
"""


def snapshot_coverage(cur, window_hours=48):
    """Measure recent item snapshot coverage; read-only, no fabrication."""
    cur.execute(_SNAPSHOT_COVERAGE_SQL, (int(window_hours),
                                        int(window_hours)))
    row = cur.fetchone() or (0, 0, 0, 0, 0, 0)
    recent, none, one, two_plus, valid, snapshot_rows = [
        int(x or 0) for x in row]
    pct = (round(100.0 * valid / recent, 1) if recent else None)
    return {
        "window_hours": int(window_hours),
        "recent_items": recent,
        "no_snapshots": none,
        "one_snapshot": one,
        "two_plus_snapshots": two_plus,
        "valid_growth_items": valid,
        "snapshot_rows": snapshot_rows,
        "valid_growth_pct": pct,
        "missing_evidence": (recent == 0 or valid == 0),
        "notes": ("Coverage is observed from stored snapshots only. Database "
                  "counts cannot distinguish collection cadence from selection "
                  "rules or API failures."),
    }


_EVIDENCE_REGISTRY_SQL = """
    SELECT count(*),
           count(*) FILTER (WHERE verification_status = 'verified'),
           count(*) FILTER (WHERE verification_status = 'nonverified'),
           count(*) FILTER (WHERE verification_status = 'unknown'),
           count(*) FILTER (WHERE type_provenance = 'missing'),
           COALESCE(sum(item_count), 0),
           COALESCE(sum(snapshot_item_count), 0)
    FROM creator_registry
"""


def _table_exists(cur, table):
    """Safe availability check; does not abort a healthy transaction."""
    try:
        cur.execute("select to_regclass(%s)", (table,))
        row = cur.fetchone()
        return bool(row and row[0] is not None)
    except Exception:
        return False


def creator_evidence(cur, family=None, days=180, limit=5000):
    """Milestone 3 evidence interface (read-only). No opportunity engine."""
    if not _table_exists(cur, "creator_registry"):
        registry = {"available": False, "reason": "missing_table"}
    else:
        autocommit = getattr(getattr(cur, "connection", None),
                             "autocommit", True)
        if not autocommit:
            cur.execute("SAVEPOINT creator_evidence_registry")
        try:
            cur.execute(_EVIDENCE_REGISTRY_SQL)
            row = cur.fetchone() or (0, 0, 0, 0, 0, 0, 0)
            registry = {
                "creators": int(row[0] or 0),
                "verified": int(row[1] or 0),
                "nonverified": int(row[2] or 0),
                "unknown_verification": int(row[3] or 0),
                "missing_type": int(row[4] or 0),
                "items": int(row[5] or 0),
                "snapshot_items": int(row[6] or 0),
            }
            if not autocommit:
                cur.execute("RELEASE SAVEPOINT creator_evidence_registry")
        except Exception as e:
            if not autocommit:
                try:
                    cur.execute(
                        "ROLLBACK TO SAVEPOINT creator_evidence_registry")
                    cur.execute(
                        "RELEASE SAVEPOINT creator_evidence_registry")
                except Exception:
                    pass
            registry = {"available": False, "error": type(e).__name__}
    comparison = creator_comparison(cur, family=family, days=days,
                                    limit=limit)
    coverage = snapshot_coverage(cur, 48)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "category": family or "all",
        "registry": registry,
        "comparison": comparison,
        "snapshot_coverage": coverage,
        "sample_sizes": {
            "comparison_items": comparison.get("sample", {}).get(
                "returned_items", 0),
            "comparison_creators": comparison.get("creators", 0),
            "snapshot_recent_items": coverage["recent_items"],
        },
        "missing": {
            "snapshot_growth_evidence": coverage["missing_evidence"],
            "registry_type_missing": registry.get("missing_type", 0)
            if registry.get("available", True) else None,
        },
        "contract": {
            "favorites_not_sales": True,
            "representative": False,
            "growth_requires_snapshots": True,
            "no_invented_demand": True,
            "created_by": "phase2_creator_registry",
        },
    }
