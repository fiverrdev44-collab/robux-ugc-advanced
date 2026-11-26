"""Bounded Avatar Background discovery and daily observation collection.

Uses the existing rate-limited read-only catalog transports and the existing
items/item_history schema. Never infers creation time or growth from discovery.
No new Discord command, migration, credentials, or AI call is required.
"""
import threading

from creator_identity import catalog_identity
from safe_roblox import get as safe_get, shared_circuit_open
from time_utils import ensure_utc, utc_now

SEARCH_URL = "https://catalog.roblox.com/v1/search/items/details"
DETAILS_URL = "https://economy.roblox.com/v2/assets/{}/details"
FAVORITES_URL = "https://catalog.roblox.com/v1/catalog/items/{}/details?itemType=Asset"
ASSET_TYPE = 92
# General terms run every cycle; rotating scene seeds expand beyond one query.
GENERAL = ("avatar background", "background")
SCENES = ("city", "forest", "room", "street", "sky", "meme", "horror",
          "game", "beach", "space", "garden", "school", "office", "castle",
          "landscape", "anime", "retro", "map", "cozy", "ocean", "arcade",
          "desert", "mountain", "neon")
MAX_SEARCH_PAGES = 12
REFRESH_LIMIT = 120
DATE_LIMIT = 8
_LOCK = threading.Lock()


def _integer(value, maximum=2147483647):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= maximum else None


def _normalize(raw, now):
    if not isinstance(raw, dict):
        return None
    if raw.get("itemType") and str(raw["itemType"]).lower() != "asset":
        return None
    kind = raw.get("assetType", raw.get("assetTypeId", raw.get("asset_type_id")))
    if str(kind) != "92":
        return None
    iid = _integer(raw.get("id"), 9223372036854775807)
    name = raw.get("name")
    if not iid or not isinstance(name, str) or not name.strip():
        return None
    created = ensure_utc(raw.get("itemCreatedUtc") or raw.get("created_at"))
    if created and created > now:
        created = None
    identity = catalog_identity(raw)
    return dict(id=iid, name=name[:500],
                description=str(raw.get("description") or "")[:5000],
                favorite_count=_integer(raw.get("favoriteCount",
                                                raw.get("favorite_count"))),
                price=None if raw.get("price_missing") else _integer(raw.get("price")),
                creator_name=str(raw.get("creatorName") or raw.get("creator_name") or "")[:200],
                created_at=created, **identity)


def _fetch_favorite_count(item_id):
    """Read catalog favoriteCount when the batch response omits it.

    Zero is a valid observation. Only a missing field triggers this fallback;
    rate limits and unavailable responses remain unknown, never zero.
    """
    if shared_circuit_open("catalog_details"):
        return None
    try:
        response = safe_get(
            "catalog_details", FAVORITES_URL.format(int(item_id)), timeout=10)
        if response.status_code != 200:
            return None
        payload = response.json() or {}
        value = payload.get("favoriteCount")
        if value is None:
            return None
        return _integer(value)
    except Exception:
        return None


def _queries(now):
    slot = int(now.timestamp()) // (6 * 3600)
    offset = (slot * 4) % len(SCENES)
    return [(term, sort) for term in GENERAL for sort in (3, "Relevance")] + [
        (SCENES[(offset + i) % len(SCENES)] + " background", 3)
        for i in range(4)]


def discover(now, get=None, circuit=None):
    get = get or safe_get
    circuit = circuit or shared_circuit_open
    found, requests, failures = {}, 0, 0
    for keyword, sort in _queries(now):
        cursor, seen = None, set()
        for _ in range(2 if keyword in GENERAL else 1):
            if requests >= MAX_SEARCH_PAGES or circuit("catalog_search"):
                return found, requests, failures, True
            params = {"Keyword": keyword, "SortType": sort, "Limit": 30}
            if cursor:
                params["Cursor"] = cursor
            requests += 1
            try:
                response = get("catalog_search", SEARCH_URL, params=params, timeout=12)
                if response.status_code in (0, 429):
                    return found, requests, failures + 1, True
                if response.status_code != 200:
                    failures += 1
                    break
                body = response.json()
                if not isinstance(body, dict) or not isinstance(body.get("data"), list):
                    failures += 1
                    break
            except Exception:
                failures += 1
                break
            for raw in body["data"]:
                row = _normalize(raw, now)
                if row is None:
                    continue
                old = found.get(row["id"])
                if old:
                    # Keep observed fields when another result omits them.
                    for key in ("created_at", "favorite_count", "price",
                                "creator_id", "creator_type", "creator_verified"):
                        if row[key] is None:
                            row[key] = old[key]
                found[row["id"]] = row
            cursor = body.get("nextPageCursor")
            if not cursor or not isinstance(cursor, str) or cursor in seen:
                break
            seen.add(cursor)
    return found, requests, failures, False


def store_rows(cur, rows):
    """Store fresh observations; existing UTC-day uniqueness stays intact."""
    snapshots = 0
    for row in rows:
        cur.execute("""
            INSERT INTO items (id, name, description, favorite_count, price,
                creator_name, creator_id, creator_type, creator_verified,
                asset_type_id, created_at, fetched_at, favorite_status)
            VALUES (%(id)s, %(name)s, %(description)s, %(favorite_count)s,
                %(price)s, %(creator_name)s, %(creator_id)s, %(creator_type)s,
                %(creator_verified)s, 92, %(created_at)s, CURRENT_TIMESTAMP,
                CASE WHEN %(favorite_count)s IS NULL THEN 'missing' ELSE 'known' END)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                description = COALESCE(NULLIF(EXCLUDED.description, ''), items.description),
                favorite_count = COALESCE(EXCLUDED.favorite_count, items.favorite_count),
                favorite_status = CASE WHEN EXCLUDED.favorite_count IS NULL
                    THEN items.favorite_status ELSE 'known' END,
                price = COALESCE(EXCLUDED.price, items.price),
                creator_name = COALESCE(NULLIF(EXCLUDED.creator_name, ''), items.creator_name),
                creator_id = COALESCE(EXCLUDED.creator_id, items.creator_id),
                creator_type = COALESCE(EXCLUDED.creator_type, items.creator_type),
                creator_verified = COALESCE(EXCLUDED.creator_verified, items.creator_verified),
                asset_type_id = 92,
                created_at = COALESCE(items.created_at, EXCLUDED.created_at),
                fetched_at = CURRENT_TIMESTAMP
        """, row)
        if row["favorite_count"] is not None:
            cur.execute("""
                INSERT INTO item_history (item_id, favorite_count, total_sales, price)
                VALUES (%(id)s, %(favorite_count)s, NULL, %(price)s)
                ON CONFLICT DO NOTHING
            """, row)
            snapshots += max(0, cur.rowcount)
    return snapshots


def due_ids(cur, limit=REFRESH_LIMIT):
    """Reserve capacity independent of generic popularity/top-item limits."""
    cur.execute("""
        SELECT i.id FROM items i
        LEFT JOIN LATERAL (
            SELECT max(h.snapshot_at) AS last_at FROM item_history h
            WHERE h.item_id = i.id AND h.favorite_count IS NOT NULL
        ) h ON TRUE
        WHERE i.asset_type_id = 92
          AND (h.last_at IS NULL OR
               (h.last_at AT TIME ZONE 'UTC')::date <
               (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date)
        ORDER BY CASE WHEN i.created_at >= NOW() - INTERVAL '30 days'
                      THEN 0 WHEN i.created_at IS NULL THEN 1 ELSE 2 END,
                 h.last_at ASC NULLS FIRST, i.id
        LIMIT %s
    """, (limit,))
    return [r[0] for r in cur.fetchall()]


def missing_dates(cur, now):
    cur.execute("""
        SELECT id FROM items WHERE asset_type_id = 92 AND created_at IS NULL
        ORDER BY md5(id::text || %s) LIMIT %s
    """, (str(int(now.timestamp()) // (6 * 3600)), DATE_LIMIT))
    return [r[0] for r in cur.fetchall()]


def _with_db(factory, fn):
    conn = factory()
    try:
        cur = conn.cursor()
        try:
            value = fn(cur)
            conn.commit()
            return value
        finally:
            cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_cycle(db_factory=None, batch_fn=None):
    if not _LOCK.acquire(blocking=False):
        return {"status": "already_running"}
    try:
        if db_factory is None:
            from bot_core import get_db as db_factory
        now = utc_now()
        found, requests, failures, deferred = discover(now)
        snapshots = _with_db(db_factory, lambda c: store_rows(c, found.values()))
        refreshed, dates, date_requests, refresh_failures = 0, 0, 0, 0
        if not shared_circuit_open("catalog_details"):
            ids = _with_db(db_factory, due_ids)
            if ids:
                if batch_fn is None:
                    from roblox_batch_client import fetch_many_items_sync as batch_fn
                items, _failed = batch_fn(ids, max_batch=30, rate_per_min=30,
                                          max_concurrency=1)
                rows = []
                favorite_fallback_requests = 0
                favorite_fallback_failures = 0
                for iid, detail in (items or {}).items():
                    try:
                        item_id = int(iid)
                    except (TypeError, ValueError):
                        continue
                    if item_id not in ids or not isinstance(detail, dict):
                        continue
                    normalized_detail = dict(detail, id=item_id)
                    observed_favs = normalized_detail.get(
                        "favorite_count", normalized_detail.get("favoriteCount"))
                    if observed_favs is None:
                        favorite_fallback_requests += 1
                        observed_favs = _fetch_favorite_count(item_id)
                        if observed_favs is None:
                            favorite_fallback_failures += 1
                        else:
                            normalized_detail["favorite_count"] = observed_favs
                    row = _normalize(normalized_detail, utc_now())
                    if row is not None:
                        rows.append(row)
                snapshots += _with_db(db_factory, lambda c: store_rows(c, rows))
                refreshed = sum(r.get("favorite_count") is not None for r in rows)
                refresh_failures = len(ids) - refreshed
        if not shared_circuit_open("catalog_details"):
            missing = _with_db(db_factory, lambda c: missing_dates(c, now))
            verified = []
            for iid in missing:
                if shared_circuit_open("catalog_details"):
                    break
                date_requests += 1
                try:
                    response = safe_get("catalog_details", DETAILS_URL.format(iid), timeout=10)
                    if response.status_code in (0, 429):
                        break
                    if response.status_code != 200:
                        continue
                    body = response.json() or {}
                    if not isinstance(body, dict):
                        continue
                    created = ensure_utc(body.get("Created"))
                    if str(body.get("AssetTypeId")) == "92" and created and created <= utc_now():
                        verified.append((created, iid))
                except Exception:
                    continue
            if verified:
                def update(cur):
                    for row in verified:
                        cur.execute("UPDATE items SET created_at=%s WHERE id=%s "
                                    "AND asset_type_id=92 AND created_at IS NULL", row)
                    return len(verified)
                dates = _with_db(db_factory, update)
        return {"status": "partial" if deferred or failures or refresh_failures or shared_circuit_open("catalog_details") else "ok",
                "search_requests": requests, "search_failures": failures,
                "discovered": len(found), "refreshed": refreshed,
                "refresh_failures": refresh_failures,
                "favorite_fallback_requests": locals().get("favorite_fallback_requests", 0),
                "favorite_fallback_failures": locals().get("favorite_fallback_failures", 0),
                "new_daily_snapshots": snapshots, "dates_filled": dates,
                "date_requests": date_requests,
                "deferred": deferred or shared_circuit_open("catalog_details")}
    finally:
        _LOCK.release()


if __name__ == "__main__":
    print(run_cycle(), flush=True)
