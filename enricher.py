import os
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import get_db_connection, setup_database

# ============================================================
# COOKIE POOLING
# ------------------------------------------------------------
# Set up to 5 cookies on Render:
#   ROBLOSECURITY_COOKIE_1, ROBLOSECURITY_COOKIE_2, ... _5
# Falls back to single ROBLOSECURITY_COOKIE if numbered ones missing.
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

# Batch endpoint — POST list of {itemType, id} → returns details for up to ~120
BATCH_ENDPOINT = "https://catalog.roblox.com/v1/catalog/items/details"
# Single-item fallback (economy endpoint returns AssetTypeId reliably)
FALLBACK_ENDPOINT = "https://economy.roblox.com/v2/assets/{}/details"
AUTH_URL = "https://auth.roblox.com/v2/logout"

BATCH_SIZE = 1500          # IDs to pull from DB per run
BATCH_CHUNK = 100          # IDs per batch POST request
REFRESH_EXISTING = os.getenv("REFRESH_MODE", "false").lower() == "true"
PRIORITY = os.getenv("PRIORITY", "newest").lower()

MIN_VALID_ID = 1_000_000
MAX_VALID_ID = 2_000_000_000

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.roblox.com/",
    "Origin": "https://www.roblox.com",
}

# One session per cookie
SESSIONS = []
for cookie in COOKIES:
    s = requests.Session()
    s.cookies[".ROBLOSECURITY"] = cookie
    s.headers.update(HEADERS)
    SESSIONS.append(s)

_session_idx = 0
_fail_codes = {}


def log(msg):
    print(msg, flush=True)


def get_session():
    """Round-robin session selection."""
    global _session_idx
    s = SESSIONS[_session_idx % len(SESSIONS)]
    _session_idx += 1
    return s


def get_csrf_token(session):
    try:
        resp = session.post(AUTH_URL, timeout=10)
        token = resp.headers.get("X-CSRF-Token")
        if token:
            session.headers["X-CSRF-Token"] = token
            return True
    except Exception as e:
        log(f"⚠️ CSRF error: {e}")
    return False


def fetch_batch(session, ids):
    """
    POST /v1/catalog/items/details with a batch of asset IDs.
    Returns (ok_count, {id: data}, failed_ids).
    """
    payload = {"items": [{"itemType": "Asset", "id": i} for i in ids]}
    for attempt in range(3):
        try:
            resp = session.post(
                BATCH_ENDPOINT,
                json=payload,
                timeout=15,
                headers={"Content-Type": "application/json"},
            )
            code = resp.status_code
            if code == 200:
                data = resp.json().get("data", [])
                by_id = {d["id"]: d for d in data if "id" in d}
                failed = [i for i in ids if i not in by_id]
                return len(by_id), by_id, failed
            if code == 429:
                _fail_codes[429] = _fail_codes.get(429, 0) + 1
                retry_after = int(resp.headers.get("Retry-After", 5))
                log(f"  ⏳ 429 — waiting {retry_after}s (attempt {attempt+1})")
                time.sleep(retry_after)
                continue
            if code == 403:
                _fail_codes[403] = _fail_codes.get(403, 0) + 1
                get_csrf_token(session)
                continue
            _fail_codes[code] = _fail_codes.get(code, 0) + 1
            return 0, {}, list(ids)
        except Exception:
            _fail_codes["exc"] = _fail_codes.get("exc", 0) + 1
            time.sleep(1)
    return 0, {}, list(ids)


def fetch_single(session, item_id):
    """Fallback via economy endpoint for items the batch missed."""
    try:
        resp = session.get(FALLBACK_ENDPOINT.format(item_id), timeout=12)
        if resp.status_code == 200:
            return item_id, resp.json()
        if resp.status_code == 404:
            _fail_codes[404] = _fail_codes.get(404, 0) + 1
        elif resp.status_code == 429:
            _fail_codes[429] = _fail_codes.get(429, 0) + 1
            time.sleep(2)
        return item_id, None
    except Exception:
        _fail_codes["exc"] = _fail_codes.get("exc", 0) + 1
        return item_id, None


def enrich_items():
    setup_database()
    conn = get_db_connection()
    cur = conn.cursor()

    # Refresh CSRF on all sessions
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

    log(f"🔧 Enriching {len(ids)} items with {len(SESSIONS)} cookie(s), "
        f"batch size {BATCH_CHUNK}...")
    start = time.time()

    # Split into batches, one per executor task
    batches = [ids[i:i + BATCH_CHUNK] for i in range(0, len(ids), BATCH_CHUNK)]
    results = {}
    failed_ids = []

    with ThreadPoolExecutor(max_workers=len(SESSIONS)) as ex:
        futures = {}
        for batch in batches:
            s = get_session()
            futures[ex.submit(fetch_batch, s, batch)] = batch

        done = 0
        for fut in as_completed(futures):
            done += 1
            try:
                ok, by_id, failed = fut.result(timeout=60)
                results.update(by_id)
                failed_ids.extend(failed)
            except Exception:
                pass
            if done % 5 == 0 or done == len(batches):
                elapsed = time.time() - start
                log(f"  batches: {done}/{len(batches)} — "
                    f"items: {len(results)} ok, {len(failed_ids)} pending "
                    f"({elapsed:.0f}s)")

    # Retry a capped number of misses via single endpoint
    if failed_ids:
        retry_cap = min(len(failed_ids), 200)
        log(f"🔁 Retrying {retry_cap} misses via single endpoint...")
        for i, iid in enumerate(failed_ids[:retry_cap]):
            s = get_session()
            _, data = fetch_single(s, iid)
            if data:
                results[iid] = data
            time.sleep(0.3)
            if (i + 1) % 50 == 0:
                log(f"  retried {i+1}/{retry_cap} — now {len(results)} ok")

    log(f"✅ Downloaded {len(results)} items in {time.time()-start:.1f}s")
    log(f"📊 Failure breakdown: {_fail_codes}")

    # Write to DB
    conn = get_db_connection()
    cur = conn.cursor()
    enriched = 0
    emote_count = 0
    for item_id, d in results.items():
        try:
            favs = d.get("favoriteCount", 0) or 0
            price = d.get("price", 0) or 0
            sales = d.get("purchaseCount", 0) or 0
            name = d.get("name", "") or ""
            desc = d.get("description", "") or ""
            creator = d.get("creatorName", "") or ""
            # Some responses use assetType, some use AssetTypeId
            asset_type = d.get("assetType", d.get("AssetTypeId", 0)) or 0

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
            log(f"  DB error {item_id}: {e}")

    conn.commit()
    cur.close(); conn.close()
    log(f"✅ Enriched {enriched} items ({emote_count} emotes) in {time.time()-start:.1f}s")


if __name__ == "__main__":
    enrich_items()
