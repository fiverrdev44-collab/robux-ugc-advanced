"""Evidence-bounded description cohort learning from measured favorite snapshots.

Does not learn seller sales, CTR, conversion or causal description effectiveness.
No external requests, migrations, writes, or new background jobs. All SQL is
parameterized, category-restricted, and bounded before history lookups.
"""
import re
from datetime import datetime, timezone

CANDIDATE_LIMIT = 250
OBSERVATION_DAYS = 14
MAX_SNAPSHOT_AGE_DAYS = 3
MIN_OBSERVATION_HOURS = 6


def family_asset_ids(family):
    """Known categories only; an unknown family must not search global UGC."""
    if not family or str(family).lower() in ("all", "unknown"):
        return []
    try:
        from convergence_engine import resolve_family_ids
        ids = resolve_family_ids(family)
    except Exception:
        return []
    if not ids:
        return []
    return [int(i) for i in ids if int(i) > 0]


def measured_favorite_growth(rows, *, now=None, limit=20):
    """Rank bounded DB snapshot pairs by *measured* per-day favorites change.

    Rows: id, name, description, favorites, price, first_favs, first_at,
    last_favs, last_at. Negative/zero/stale/short spans never qualify.
    Favorite growth is observational; it cannot establish sales or copy lift.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    selected = []
    seen = set()
    for row in list(rows or [])[:CANDIDATE_LIMIT]:
        try:
            (item_id, name, description, favorites, price,
             first_favs, first_at, last_favs, last_at) = row[:9]
            item_id = int(item_id)
            first_count = int(first_favs)
            last_count = int(last_favs)
            if not isinstance(first_at, datetime) or not isinstance(last_at, datetime):
                continue
            start = first_at.replace(tzinfo=timezone.utc) if first_at.tzinfo is None else first_at.astimezone(timezone.utc)
            end = last_at.replace(tzinfo=timezone.utc) if last_at.tzinfo is None else last_at.astimezone(timezone.utc)
            elapsed_days = (end - start).total_seconds() / 86400.0
            age_days = (now - end).total_seconds() / 86400.0
            delta = last_count - first_count
            if (item_id <= 0 or item_id in seen or first_count < 0
                or not isinstance(name, str) or not isinstance(description, str)
                or len(description.strip()) <= 20 or favorites is None
                or elapsed_days < MIN_OBSERVATION_HOURS / 24.0
                or elapsed_days > OBSERVATION_DAYS + 0.01
                or age_days < 0 or age_days > MAX_SNAPSHOT_AGE_DAYS
                or delta <= 0):
                continue
            seen.add(item_id)
            selected.append({
                "item_id": item_id,
                "row": (name, description, max(int(favorites), 0), price),
                "delta_favorites": delta,
                "observation_days": round(elapsed_days, 3),
                "favorites_per_day": round(delta / elapsed_days, 2),
                "last_snapshot_at": end.isoformat(),
                "short_window": elapsed_days < 1,
            })
        except (ValueError, TypeError, OverflowError, IndexError):
            continue
    selected.sort(key=lambda x: (
        -x["favorites_per_day"], -x["delta_favorites"],
        -x["observation_days"], x["item_id"]
    ))
    return selected[:max(0, min(int(limit), CANDIDATE_LIMIT))]


def query_rising_descriptions(cur, keyword_variants, family, *, limit=15, now=None):
    """Exactly one read-only query: capped candidates and indexed snapshot pairs.

    The recent-growth cohort is explicitly unavailable if the category is
    unknown, the snapshots are insufficient, or the database is unreachable.
    """
    ids = family_asset_ids(family)
    candidates = []
    for value in keyword_variants or []:
        value = re.sub(r"\s+", " ", str(value or "").lower()).strip()
        if (len(value) < 3 or len(value) > 80
                or value in ("background", "backgrounds", "emote",
                             "emotes", "item", "avatar", "roblox")):
            continue
        if value not in candidates:
            candidates.append(value)
    if not ids:
        return {"status": "unavailable", "reason": "unknown_or_unscoped_family",
                "rising": [], "sampled": 0}
    if not candidates:
        return {"status": "unavailable", "reason": "missing_relevant_keywords",
                "rising": [], "sampled": 0}
    # Escape LIKE metacharacters in untrusted creator input; all arguments are
    # bound parameters, and candidate names are matched in the same category.
    patterns = ["%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                for value in candidates[:8]]
    sql = """
        WITH candidates AS MATERIALIZED (
            SELECT id, name, description, favorite_count, price, fetched_at
            FROM items
            WHERE asset_type_id = ANY(%s)
              AND name ILIKE ANY(%s)
              AND favorite_count IS NOT NULL
              AND description IS NOT NULL
              AND length(trim(description)) > 20
            ORDER BY fetched_at DESC NULLS LAST, id DESC
            LIMIT %s
        )
        SELECT c.id, c.name, c.description, c.favorite_count, c.price,
               first_seen.favorite_count, first_seen.snapshot_at,
               last_seen.favorite_count, last_seen.snapshot_at
        FROM candidates c
        JOIN LATERAL (
            SELECT favorite_count, snapshot_at
            FROM item_history
            WHERE item_id = c.id AND favorite_count IS NOT NULL
              AND snapshot_at >= NOW() - INTERVAL '14 days'
            ORDER BY snapshot_at ASC
            LIMIT 1
        ) first_seen ON true
        JOIN LATERAL (
            SELECT favorite_count, snapshot_at
            FROM item_history
            WHERE item_id = c.id AND favorite_count IS NOT NULL
              AND snapshot_at >= NOW() - INTERVAL '14 days'
            ORDER BY snapshot_at DESC
            LIMIT 1
        ) last_seen ON true
    """
    cur.execute(sql, (ids, patterns, CANDIDATE_LIMIT))
    observed = cur.fetchall() or []
    rising = measured_favorite_growth(observed, now=now, limit=limit)
    return {
        "status": "measured" if rising else "insufficient_history",
        "reason": None if rising else "no_qualifying_snapshot_growth",
        "rising": rising, "sampled": len(observed),
        "category_ids": ids, "window_days": OBSERVATION_DAYS,
        "minimum_observation_hours": MIN_OBSERVATION_HOURS,
        "maximum_snapshot_age_days": MAX_SNAPSHOT_AGE_DAYS,
    }


def combine_cohorts(established, rising, *, limit=20):
    """Use both cohorts without duplicate listings or treating volume as sales."""
    limit = max(0, min(int(limit), 40))
    rising = list(rising or [])
    established = list(established or [])
    selected = []
    seen = set()

    def add(row):
        if not isinstance(row, (list, tuple)) or len(row) < 4:
            return
        name = str(row[0] or "").strip()
        if not name or name.casefold() in seen:
            return
        seen.add(name.casefold())
        selected.append(tuple(row[:4]))

    # Give observed breakouts meaningful representation, but never allow them
    # to crowd out the established sample or imply causal performance.
    for entry in rising[:max(1, limit // 2)] if limit else []:
        row = entry.get("row") if isinstance(entry, dict) else entry
        add(row)
    remaining = limit - len(selected)
    for row in established[:remaining]:
        add(row)
    # If overlapping established names reduced the total, fill with remaining.
    for row in established:
        if len(selected) >= limit:
            break
        add(row)
    for entry in rising:
        if len(selected) >= limit:
            break
        add(entry.get("row") if isinstance(entry, dict) else entry)
    return selected[:limit]
