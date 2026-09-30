import os
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import get_db_connection, setup_database

# ============================================================
# COOKIE POOLING
# ============================================================
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

# ============================================================
# ENDPOINT
# ============================================================
DETAILS_URL = "https://economy.roblox.com/v2/assets/{}/details"
AUTH_URL = "https://auth.roblox.com/v2/logout"

BATCH_SIZE = 1500
REFRESH_EXISTING = os.getenv("REFRESH_MODE", "false").lower() == "true"
PRIORITY = os.getenv("PRIORITY", "newest").lower()

MIN_VALID_ID = 1_000_000
MAX_VALID_ID = 100_000_000_000_000_000   # 10^17

SESSION_DELAY = 0.9

# Roblox's economy endpoint returns huge sentinel values for
# unknown/off-sale prices. Clamp these before writing to DB.
MAX_SANE_PRICE = 1_000_000        # 1M Robux — no real emote costs this
MAX_SANE_SALES = 100_000_000      # 100M sales — no real emote has this
MAX_SANE_FAVS = 10_000_000_000    # 10B favs — Roblox's all-time max is ~2B

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


def fetch_worker(session, ids, worker_id):
    """
    One worker owns one session (one cookie) and processes its
    slice of IDs sequentially with a polite delay between calls.
    """
    results = {}
    for idx, item_id in enumerate(ids):
        for attempt in range(3):
            try:
                resp = session.get(DETAILS_URL.format(item_id), timeout=12)
                code = resp.status_code
                if code == 200:
                    results[item_id] = resp.json()
                    break
                if code == 404:
                    _fail_codes[404] = _fail_codes.get(404, 0) + 1
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
    return results


def _safe_int(val, max_val, default=0):
    """Convert to int, clamp anything absurd to the default."""
    try:
        n = int(val or 0)
    except (TypeError, ValueError):
        return default
    if n < 0 or n > max_val:
        return default
    return n


def enrich_items():
    setup_database()
    conn = get_db_connection()
    cur = conn.cursor()

    for s in SESSIONS:
        get_csrf_token(s)
    log(f"🔐 CSRF tokens fetched for {len(SESSIONS)} session(s).")

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
            AND d.id BETWEEN %s AND %s
            ORDER BY d.id {order} LIMIT %s
        """, (MIN_VALID_ID, MAX_VALID_ID, BATCH_SIZE))

    ids = [row[0] for row in cur.fetchall()]
    cur.close(); conn.close()

    if not ids:
        log("✅ Nothing to enrich.")
        return

    log(f"🔧 Enriching {len(ids)} items with {len(SESSIONS)} cookie(s)...")
    start = time.time()

    slices = [[] for _ in SESSIONS]
    for i, iid in enumerate(ids):
        slices[i % len(SESSIONS)].append(iid)

    results = {}
    with ThreadPoolExecutor(max_workers=len(SESSIONS)) as ex:
        futures = {
            ex.submit(fetch_worker, SESSIONS[i], slices[i], i + 1): i
            for i in range(len(SESSIONS))
        }
        done = 0
        for fut in as_completed(futures):
            done += 1
            try:
                r = fut.result(timeout=3600)
                results.update(r)
            except Exception as e:
                log(f"  worker {done} error: {e}")
            elapsed = time.time() - start
            log(f"  workers done: {done}/{len(SESSIONS)} — "
                f"items: {len(results)} ({elapsed:.0f}s)")

    log(f"✅ Downloaded {len(results)} items in {time.time()-start:.1f}s")
    log(f"📊 Failure breakdown: {_fail_codes}")

    # Write to DB
    conn = get_db_connection()
    cur = conn.cursor()
    enriched = 0
    emote_count = 0
    db_errors = 0
    for item_id, d in results.items():
        try:
            favs = _safe_int(d.get("FavoriteCount"), MAX_SANE_FAVS)
            price = _safe_int(d.get("PriceInRobux"), MAX_SANE_PRICE)
            sales = _safe_int(d.get("Sales"), MAX_SANE_SALES)
            name = (d.get("Name", "") or "")[:500]
            desc = (d.get("Description", "") or "")[:5000]
            creator_obj = d.get("Creator") or {}
            creator = (creator_obj.get("Name", "") if isinstance(creator_obj, dict) else "")[:200]
            asset_type = _safe_int(d.get("AssetTypeId"), 1000)

            if asset_type == 61:
                emote_count += 1

            cur.execute("""
                INSERT INTO items (id, name, favorite_count, price, total_sales,
                                   description, creator_name, asset_type_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    favorite_count = EXCLUDED.favorite_count,
                    total_sales = EXCLUDED.total_sales,
                    price = EXCLUDED.price,
                    description = EXCLUDED.description,
                    name = EXCLUDED.name,
                    asset_type_id = EXCLUDED.asset_type_id,
                    fetched_at = CURRENT_TIMESTAMP
            """, (item_id, name, favs, price, sales, desc, creator, asset_type))

            cur.execute("""
                INSERT INTO item_history (item_id, favorite_count, total_sales, price)
                VALUES (%s, %s, %s, %s)
            """, (item_id, favs, sales, price))
            enriched += 1
        except Exception as e:
            db_errors += 1
            log(f"  DB error {item_id}: {e}")
            # CRITICAL: rollback so the next INSERT starts a fresh
            # transaction. Without this, one bad item kills every
            # subsequent item in the same transaction.
            try:
                conn.rollback()
                cur = conn.cursor()
            except Exception:
                pass

    conn.commit()
    cur.close(); conn.close()
    log(f"✅ Enriched {enriched} items ({emote_count} emotes) "
        f"in {time.time()-start:.1f}s — {db_errors} DB errors")


if __name__ == "__main__":
    enrich_items()
