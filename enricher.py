import os
import requests
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from psycopg2.extras import execute_values
from database import get_db_connection, setup_database

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
    raise ValueError("No ROBLOSECURITY_COOKIE configured!")

DETAILS_URL = "https://economy.roblox.com/v2/assets/{}/details"
FAVORITES_URL = "https://catalog.roblox.com/v1/catalog/items/{}/details?itemType=Asset"
AUTH_URL = "https://auth.roblox.com/v2/logout"

BATCH_SIZE = int(os.getenv("ENRICH_BATCH_SIZE", "300"))
REFRESH_EXISTING = os.getenv("REFRESH_MODE", "false").lower() == "true"
PRIORITY = os.getenv("PRIORITY", "newest").lower()

MIN_VALID_ID = 1_000_000
MAX_VALID_ID = 100_000_000_000_000_000

SESSION_DELAY = float(os.getenv("ENRICH_SESSION_DELAY", "2.5"))

MAX_SANE_PRICE = 1_000_000
MAX_SANE_SALES = 100_000_000
MAX_SANE_FAVS = 10_000_000_000

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.roblox.com/",
    "Origin": "https://www.roblox.com",
}

SESSIONS = []
for cookie in COOKIES:
    s = requests.Session()
    s.cookies[".ROBLOSECURITY"] = cookie
    s.headers.update(HEADERS)
    SESSIONS.append(s)

# Public fallback: the catalog favorites endpoint works anonymously even
# when a stored .ROBLOSECURITY cookie is expired/invalid. This is what
# left ~78k items with NULL favorites.
ANON_SESSION = requests.Session()
ANON_SESSION.headers.update(HEADERS)

_fail_codes = {}


def log(msg):
    print(msg, flush=True)


def get_csrf_token(session):
    try:
        resp = session.post(AUTH_URL, timeout=10)
        token = resp.headers.get("X-CSRF-Token")
        if token:
            session.headers["X-CSRF-Token"] = token
            return True
    except Exception:
        pass
    return False


def fetch_favorites(session, item_id):
    """Catalog endpoint returns favoriteCount. Falls back to anonymous."""
    for s in (session, ANON_SESSION):
        try:
            resp = s.get(FAVORITES_URL.format(item_id), timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                favs = data.get("favoriteCount")
                if favs is None:
                    return None
                try:
                    return int(favs)
                except (TypeError, ValueError):
                    return None
            if resp.status_code == 429:
                _fail_codes[429] = _fail_codes.get(429, 0) + 1
                time.sleep(2)
                continue
            if resp.status_code in (401, 403):
                # Invalid cookie — retry anonymously.
                _fail_codes[403] = _fail_codes.get(403, 0) + 1
                continue
            return None
        except Exception:
            _fail_codes["exc_fav"] = _fail_codes.get("exc_fav", 0) + 1
            continue
    return None


def fetch_worker(session, ids, worker_id):
    results = {}
    failed = {}
    for idx, item_id in enumerate(ids):
        for attempt in range(3):
            try:
                resp = session.get(DETAILS_URL.format(item_id), timeout=12)
                code = resp.status_code
                if code == 200:
                    data = resp.json()
                    favs = fetch_favorites(session, item_id)
                    if favs is not None:
                        data["FavoriteCount"] = favs
                    results[item_id] = data
                    break
                if code in (400, 404):
                    _fail_codes[code] = _fail_codes.get(code, 0) + 1
                    failed[item_id] = str(code)
                    break
                if code == 429:
                    _fail_codes[429] = _fail_codes.get(429, 0) + 1
                    retry_after = int(resp.headers.get("Retry-After", 3))
                    time.sleep(retry_after)
                    continue
                if code == 403:
                    _fail_codes[403] = _fail_codes.get(403, 0) + 1
                    get_csrf_token(session)
                    continue
                _fail_codes[code] = _fail_codes.get(code, 0) + 1
                break
            except Exception:
                _fail_codes["exc"] = _fail_codes.get("exc", 0) + 1
                time.sleep(1)
        time.sleep(SESSION_DELAY)

        if (idx + 1) % 100 == 0:
            log(f"  [worker {worker_id}] {idx+1}/{len(ids)} done, "
                f"{len(results)} ok")
    return results, failed


def _safe_int(val, max_val, default=0):
    """Convert to int, clamp anything absurd to the default."""
    try:
        n = int(val or 0)
    except (TypeError, ValueError):
        return default
    if n < 0 or n > max_val:
        return default
    return n


def _parse_created(raw):
    """Parse Roblox Created string like '2012-08-06T22:15:45.993Z'."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "").split(".")[0])
    except Exception:
        return None


def enrich_items():
    setup_database()
    conn = get_db_connection()
    cur = conn.cursor()

    # Batch client handles CSRF internally; per-session warm-up no longer needed.

    if REFRESH_EXISTING:
        log("🔄 REFRESH MODE")
        cur.execute("""
            SELECT id FROM items WHERE favorite_count > 0
            ORDER BY favorite_count DESC LIMIT %s
        """, (BATCH_SIZE,))
    else:
        order = "DESC" if PRIORITY == "newest" else "ASC"
        log(f"🆕 NORMAL MODE ({PRIORITY})")
        cur.execute(f"""
            SELECT d.id FROM discovered_items d
            WHERE NOT EXISTS (SELECT 1 FROM items i WHERE i.id = d.id)
            AND NOT EXISTS (
                SELECT 1 FROM failed_items f
                WHERE f.id = d.id AND f.attempts >= 3
            )
            AND d.id BETWEEN %s AND %s
            ORDER BY d.id {order} LIMIT %s
        """, (MIN_VALID_ID, MAX_VALID_ID, BATCH_SIZE))

    ids = [row[0] for row in cur.fetchall()]
    cur.close(); conn.close()

    if not ids:
        log("✅ Nothing to enrich.")
        return

    log(f"🔧 Enriching {len(ids)} items in 30-item batches...")
    start = time.time()

    from roblox_batch_client import fetch_many_items_sync
    raw_results, failed_ids = fetch_many_items_sync(
        ids, max_batch=30, rate_per_min=90, max_concurrency=3
    )
    results = {iid: d for iid, d in raw_results.items()}

    log(f"✅ Downloaded {len(results)} items in {time.time()-start:.1f}s "
        f"({len(failed_ids)} failed)")

    conn = get_db_connection()
    cur = conn.cursor()
    enriched = 0
    emote_count = 0
    db_errors = 0
    dates_filled = 0

    def _row(item_id, d):
        favs = d.get("favorite_count")
        favs = (_safe_int(favs, MAX_SANE_FAVS) if favs is not None else None)
        price = _safe_int(d.get("price"), MAX_SANE_PRICE)
        name = (d.get("name") or "")[:500]
        desc = (d.get("description") or "")[:5000]
        creator = (d.get("creator_name") or "")[:200]
        asset_type = _safe_int(d.get("asset_type_id"), 1000)
        status = "known" if favs is not None else "missing"
        return (item_id, name, favs, price, desc, creator, asset_type, status)

    rows = []
    for item_id, d in results.items():
        try:
            rows.append(_row(item_id, d))
            if _safe_int(d.get("asset_type_id"), 1000) == 61:
                emote_count += 1
        except Exception as e:
            db_errors += 1
            log(f"  row build error {item_id}: {e}")

    upsert = """
        INSERT INTO items (id, name, favorite_count, price, description,
                           creator_name, asset_type_id, favorite_status,
                           fetched_at)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            favorite_count = EXCLUDED.favorite_count,
            favorite_status = EXCLUDED.favorite_status,
            price = EXCLUDED.price,
            description = EXCLUDED.description,
            name = EXCLUDED.name,
            asset_type_id = EXCLUDED.asset_type_id,
            fetched_at = CURRENT_TIMESTAMP
    """
    template = "(%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)"

    for i in range(0, len(rows), 100):
        chunk = rows[i:i + 100]
        try:
            execute_values(cur, upsert, chunk, template=template, page_size=100)
            conn.commit()
            enriched += len(chunk)
        except Exception as e:
            conn.rollback()
            db_errors += len(chunk)
            log(f"  bulk upsert failed ({len(chunk)} rows): {e}")
            for row in chunk:
                try:
                    execute_values(cur, upsert, [row], template=template)
                    conn.commit()
                    enriched += 1
                    db_errors -= 1
                except Exception as e2:
                    conn.rollback()
                    log(f"  DB error {row[0]}: {e2}")

    # Record permanent failures (404/invalid) so they are skipped after 3 tries.
    for fid, reason in failed_ids.items():
        try:
            cur.execute("""
                INSERT INTO failed_items (id, reason, attempts, last_tried)
                VALUES (%s, %s, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (id) DO UPDATE SET
                    attempts = failed_items.attempts + 1,
                    reason = EXCLUDED.reason,
                    last_tried = CURRENT_TIMESTAMP
            """, (fid, reason))
        except Exception:
            pass

    conn.commit()
    cur.close(); conn.close()
    log(f"✅ Enriched {enriched} items ({emote_count} emotes, "
        f"{dates_filled} dates) in {time.time()-start:.1f}s — {db_errors} DB errors · "
        f"{len(failed_ids)} permanently failed")


if __name__ == "__main__":
    enrich_items()
