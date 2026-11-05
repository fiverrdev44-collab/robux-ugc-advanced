"""
snapshot.py — Fast favorites snapshot from the bot server.
"""
import os
import time
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import get_db_connection
from creator_identity import has_creator_type


def log(msg):
    print(msg, flush=True)


# ── Production settings (1000 items) ──
# All tunable from the service environment (.env) — no code edit needed.
def _env_int(name, default):
    try:
        return max(1, int(os.getenv(name, default)))
    except (TypeError, ValueError):
        return int(default)


def _env_float(name, default):
    try:
        return max(0.0, float(os.getenv(name, default)))
    except (TypeError, ValueError):
        return float(default)


TOP_ITEMS_LIMIT = _env_int("SNAPSHOT_TOP_ITEMS", 1000)
MIN_FAVS = _env_int("SNAPSHOT_MIN_FAVS", 200)
BATCH_SIZE = _env_int("SNAPSHOT_BATCH_SIZE", 500)
# One worker per session is the sweet spot from a single server IP;
# Roblox throttles per-IP hard and extra concurrency only adds 429s.
WORKERS_PER_SESSION = _env_int("SNAPSHOT_WORKERS_PER_SESSION", 1)
DELAY = _env_float("SNAPSHOT_DELAY", 1.0)
MAX_RETRIES = _env_int("SNAPSHOT_MAX_RETRIES", 2)

COOKIES = []
for i in range(1, 6):
    c = os.getenv(f"ROBLOSECURITY_COOKIE_{i}")
    if c:
        COOKIES.append(c.strip())
if not COOKIES:
    single = os.getenv("ROBLOSECURITY_COOKIE")
    if single:
        COOKIES.append(single.strip())
if not COOKIES:
    log("⚠️ No cookies — anonymous mode")
    COOKIES = [None]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

FAV_URL = "https://catalog.roblox.com/v1/catalog/items/{}/details?itemType=Asset"

SESSIONS = []
for cookie in COOKIES:
    s = requests.Session()
    if cookie:
        s.cookies[".ROBLOSECURITY"] = cookie
    s.headers.update(HEADERS)
    SESSIONS.append(s)

# Public fallback: the catalog details endpoint works anonymously even
# when a stored .ROBLOSECURITY cookie is expired/invalid.
ANON_SESSION = requests.Session()
ANON_SESSION.headers.update(HEADERS)

# Roblox throttles per IP, so rotating accounts does not buy much once the
# IP is hot. SNAPSHOT_SESSIONS=1 gives the gentlest single stream.
SESSIONS = SESSIONS[: _env_int("SNAPSHOT_SESSIONS", len(SESSIONS) or 1)]

TOTAL_WORKERS = max(1, len(SESSIONS) * WORKERS_PER_SESSION)
log(f"🔐 {len(SESSIONS)} sessions → {TOTAL_WORKERS} workers · {DELAY}s delay")

_stats = {"ok": 0, "429": 0, "403": 0, "404": 0, "other": 0, "exc": 0}

# Hard cap on the fetch phase so a slow/rate-limited run can never hold the
# scheduler (and !snapshot_now) hostage for the rest of the day.
try:
    FETCH_DEADLINE_SECONDS = max(30, int(os.getenv("SNAPSHOT_FETCH_DEADLINE", "600")))
except ValueError:
    FETCH_DEADLINE_SECONDS = 600

# Only one snapshot may run at a time. The scheduler and !snapshot_now
# used to overlap, doubling the API load and stalling both.
_RUN_LOCK = threading.Lock()


def fetch_fresh_favs(item_id, deadline=None):
    # Try authenticated sessions first, then the anonymous session.
    for session in SESSIONS + [ANON_SESSION]:
        for attempt in range(MAX_RETRIES):
            if deadline is not None and time.monotonic() >= deadline:
                return item_id, None
            try:
                r = session.get(FAV_URL.format(item_id), timeout=6)
                if r.status_code == 200:
                    favs = r.json().get("favoriteCount")
                    if favs is not None:
                        _stats["ok"] += 1
                        return item_id, int(favs)
                    else:
                        _stats["other"] += 1
                        return item_id, None
                elif r.status_code == 429:
                    _stats["429"] += 1
                    # Roblox sometimes sends Retry-After: 60+; never sleep
                    # that long inside a single item — the run deadline wins.
                    try:
                        wait = int(r.headers.get("Retry-After", 3))
                    except (TypeError, ValueError):
                        wait = 3
                    wait = max(1, min(wait, 30))
                    if deadline is not None and time.monotonic() + wait >= deadline:
                        return item_id, None
                    time.sleep(wait + attempt * 2)
                    continue
                elif r.status_code in (401, 403):
                    # Bad/expired cookie — move on to the next session
                    # (the anonymous session is the last resort).
                    _stats["403"] += 1
                    break
                elif r.status_code == 404:
                    _stats["404"] += 1
                    return item_id, None
                else:
                    _stats["other"] += 1
                    return item_id, None
            except Exception:
                _stats["exc"] += 1
                time.sleep(1)
    return item_id, None


def snapshot_top_items():
    """Public entry point — refuses concurrent runs."""
    if not _RUN_LOCK.acquire(blocking=False):
        log("⚠️ Snapshot already running — skipping this trigger.")
        return False
    try:
        return _snapshot_top_items_inner()
    finally:
        _RUN_LOCK.release()


_SELECTION_SQL = """
    WITH ranked_items AS (
        SELECT id, total_sales, price, favorite_count, created_at,
               COALESCE(fetched_at, updated_at) AS last_updated_at,
            CASE
                WHEN id IN (SELECT item_id FROM launch_ledger)
                  OR created_at > NOW() - INTERVAL '3 days'
                  OR (COALESCE(favorite_count, 0) > 1000
                      AND COALESCE(fetched_at, updated_at) < NOW() - INTERVAL '2 hours')
                    THEN 0
                WHEN (COALESCE(favorite_count, 0) BETWEEN 100 AND 1000
                      AND COALESCE(fetched_at, updated_at) < NOW() - INTERVAL '8 hours')
                  OR (created_at > NOW() - INTERVAL '14 days'
                      AND COALESCE(fetched_at, updated_at) < NOW() - INTERVAL '6 hours')
                    THEN 1
                WHEN COALESCE(fetched_at, updated_at) < NOW() - INTERVAL '7 days'
                    THEN 2
                ELSE 99
            END AS tier,
            CASE
                WHEN id IN (SELECT item_id FROM launch_ledger) THEN 0
                WHEN created_at > NOW() - INTERVAL '3 days' THEN 1
                ELSE 2
            END AS tier0_priority
        FROM items
    )
    SELECT id, total_sales, price
    FROM ranked_items
    WHERE tier < 99
    ORDER BY tier ASC,
             CASE WHEN tier = 0 THEN tier0_priority ELSE 2 END ASC,
             last_updated_at ASC NULLS FIRST
    LIMIT %s
"""


def _snapshot_top_items_inner():
    log("📸 Snapshot job started.")
    for key in _stats:
        _stats[key] = 0
    start = time.time()

    conn = get_db_connection()
    cur = conn.cursor()

    # Tiered half-life selection. `last_updated_at` is the freshest observed
    # timestamp we store (fetched_at, else updated_at). Active ledger items and
    # very new items are always tier 0; within tier 0 launch-ledger items come
    # first, then recently created items, then stale/high-favorite items. This
    # keeps the same limit/API budget while preventing fresh items from being
    # displaced by thousands of older tier-0 rows.
    tier_limit = int(os.getenv("SNAPSHOT_TIER_LIMIT", "1500"))
    cur.execute(_SELECTION_SQL, (tier_limit,))
    rows = cur.fetchall()
    log(f"📊 Found {len(rows)} items to snapshot.")

    if not rows:
        log("✅ Nothing to snapshot.")
        cur.close(); conn.close()
        return True

    id_to_data = {r[0]: {"total_sales": r[1], "price": r[2]} for r in rows}
    ids = list(id_to_data.keys())

    log(f"🔄 Fetching {len(ids)} items via 30-item batch client...")
    from roblox_batch_client import fetch_many_items_sync

    items, failed = fetch_many_items_sync(
        ids,
        max_batch=30,
        rate_per_min=int(os.getenv("SNAPSHOT_BATCH_RATE", "60")),
        max_concurrency=int(os.getenv("SNAPSHOT_BATCH_CONCURRENCY", "3")),
    )
    fresh_favs, fresh_prices = {}, {}
    fresh_identity = {}
    for iid, d in (items or {}).items():
        if d.get("favorite_count") is not None:
            fresh_favs[iid] = d["favorite_count"]
        if d.get("price") is not None:
            fresh_prices[iid] = d["price"]
        identity = {
            "creator_id": d.get("creator_id"),
            "creator_type": d.get("creator_type"),
            "creator_verified": d.get("creator_verified"),
        }
        if any(value is not None for value in identity.values()):
            fresh_identity[iid] = identity
    log(f"✅ Success: {len(fresh_favs)}/{len(ids)} items "
        f"({len(failed)} failed / not returned)")

    if fresh_favs:
        id_list = list(fresh_favs.keys())
        fav_list = [int(fresh_favs[i]) for i in id_list]
        price_list = [fresh_prices.get(i) for i in id_list]
        creator_ids = [(fresh_identity.get(i) or {}).get("creator_id")
                       for i in id_list]
        creator_types = [(fresh_identity.get(i) or {}).get("creator_type")
                         for i in id_list]
        creator_verified = [
            (fresh_identity.get(i) or {}).get("creator_verified")
            for i in id_list]
        has_type = has_creator_type(cur)
        try:
            if has_type:
                cur.execute("""
                    UPDATE items AS i
                    SET favorite_count = v.favs,
                        price = COALESCE(v.price, i.price),
                        favorite_status = 'known',
                        creator_id = COALESCE(v.creator_id, i.creator_id),
                        creator_type = COALESCE(v.creator_type,
                                                i.creator_type),
                        creator_verified = COALESCE(v.creator_verified,
                                                    i.creator_verified)
                    FROM (SELECT unnest(%s::bigint[]) AS id,
                                 unnest(%s::int[]) AS favs,
                                 unnest(%s::int[]) AS price,
                                 unnest(%s::bigint[]) AS creator_id,
                                 unnest(%s::text[]) AS creator_type,
                                 unnest(%s::boolean[]) AS creator_verified) AS v
                    WHERE i.id = v.id
                """, (id_list, fav_list, price_list, creator_ids,
                      creator_types, creator_verified))
            else:
                cur.execute("""
                    UPDATE items AS i
                    SET favorite_count = v.favs,
                        price = COALESCE(v.price, i.price),
                        favorite_status = 'known',
                        creator_id = COALESCE(v.creator_id, i.creator_id),
                        creator_verified = COALESCE(v.creator_verified,
                                                    i.creator_verified)
                    FROM (SELECT unnest(%s::bigint[]) AS id,
                                 unnest(%s::int[]) AS favs,
                                 unnest(%s::int[]) AS price,
                                 unnest(%s::bigint[]) AS creator_id,
                                 unnest(%s::boolean[]) AS creator_verified) AS v
                    WHERE i.id = v.id
                """, (id_list, fav_list, price_list, creator_ids,
                      creator_verified))
        except Exception as e:
            log(f"⚠️ bulk item update failed: {e}")
            for iid, favs in fresh_favs.items():
                try:
                    identity = fresh_identity.get(iid) or {}
                    if has_type:
                        cur.execute("""
                            UPDATE items
                            SET favorite_count = %s,
                                creator_id = COALESCE(%s, creator_id),
                                creator_type = COALESCE(%s, creator_type),
                                creator_verified = COALESCE(%s,
                                                           creator_verified)
                            WHERE id = %s
                        """, (favs, identity.get("creator_id"),
                              identity.get("creator_type"),
                              identity.get("creator_verified"), iid))
                    else:
                        cur.execute("""
                            UPDATE items
                            SET favorite_count = %s,
                                creator_id = COALESCE(%s, creator_id),
                                creator_verified = COALESCE(%s,
                                                           creator_verified)
                            WHERE id = %s
                        """, (favs, identity.get("creator_id"),
                              identity.get("creator_verified"), iid))
                except Exception:
                    pass
    conn.commit()

    log("💾 Inserting snapshots...")
    inserted = 0
    batch = []
    for iid, data in id_to_data.items():
        favs = fresh_favs.get(iid)
        if favs is None:
            continue
        price = fresh_prices.get(iid, data["price"] or 0)
        batch.append((iid, favs, data["total_sales"] or 0, price))
        if len(batch) >= BATCH_SIZE:
            cur.executemany("""
                INSERT INTO item_history (item_id, favorite_count, total_sales, price)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, batch)
            conn.commit()
            inserted += len(batch)
            batch = []

    if batch:
        cur.executemany("""
            INSERT INTO item_history (item_id, favorite_count, total_sales, price)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, batch)
        conn.commit()
        inserted += len(batch)

    cur.close(); conn.close()
    log(f"✅ Snapshot complete: {inserted} rows in {time.time()-start:.1f}s")
    return True


if __name__ == "__main__":
    try:
        snapshot_top_items()
    except Exception as e:
        log(f"❌ FATAL: {e}")
        import traceback
        traceback.print_exc()
        raise
