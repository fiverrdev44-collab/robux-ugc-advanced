import os
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import get_db_connection, setup_database

ITEM_APIS = [
    "https://catalog.roproxy.com/v1/catalog/items/{}/details?itemType=Asset",
    "https://catalog.roproxy.io/v1/catalog/items/{}/details?itemType=Asset",
    "https://catalog.roblox.com/v1/catalog/items/{}/details?itemType=Asset",
]
AUTH_URL = "https://auth.roblox.com/v2/logout"

# Bumped from 500 → 1500 (3x per run, still polite)
BATCH_SIZE = 1500
WORKERS = 4
ITEM_DELAY = 0.5

# Set REFRESH_MODE=true via env var to re-enrich top items (builds velocity history)
REFRESH_EXISTING = os.getenv("REFRESH_MODE", "false").lower() == "true"

# Set PRIORITY=newest (default) or PRIORITY=oldest
PRIORITY = os.getenv("PRIORITY", "newest").lower()

COOKIE = os.getenv("ROBLOSECURITY_COOKIE")
if not COOKIE:
    raise ValueError("ROBLOSECURITY_COOKIE environment variable not set!")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.roblox.com/",
    "Origin": "https://www.roblox.com",
}

session = requests.Session()
session.cookies[".ROBLOSECURITY"] = COOKIE
session.headers.update(HEADERS)


def log(msg):
    print(msg, flush=True)


def get_csrf_token():
    log("🔐 Fetching X-CSRF-Token...")
    try:
        resp = session.post(AUTH_URL, timeout=10)
        token = resp.headers.get("X-CSRF-Token")
        if token:
            session.headers["X-CSRF-Token"] = token
            log(f"✅ Got CSRF token: {token[:8]}...")
            return True
    except Exception as e:
        log(f"⚠️ CSRF error (OK for RoProxy): {e}")
    return False


def fetch_item(item_id):
    for api_template in ITEM_APIS:
        url = api_template.format(item_id)
        for attempt in range(3):
            try:
                resp = session.get(url, timeout=12)
                if resp.status_code == 200:
                    return item_id, resp.json()
                if resp.status_code == 429:
                    time.sleep(1 + attempt)
                    continue
                if resp.status_code == 403 and "roblox.com" in url:
                    get_csrf_token()
                    continue
                break
            except Exception:
                time.sleep(0.5)
                continue
    return item_id, None


def enrich_items():
    setup_database()
    conn = get_db_connection()
    cur = conn.cursor()

    get_csrf_token()

    # ---- PICK ITEMS TO ENRICH ----
    if REFRESH_EXISTING:
        log("🔄 REFRESH MODE: re-enriching top items by favourite count")
        cur.execute("""
            SELECT id FROM items
            WHERE favorite_count > 0
            ORDER BY favorite_count DESC
            LIMIT %s
        """, (BATCH_SIZE,))
    else:
        order = "DESC" if PRIORITY == "newest" else "ASC"
        log(f"🆕 NORMAL MODE: enriching new items (priority: {PRIORITY})")

        # NOT EXISTS is much faster than NOT IN on large tables
        # ORDER BY id DESC puts newest Roblox items first —
        # this is what makes the freshly-scanned emotes process first
        cur.execute(f"""
            SELECT d.id
            FROM discovered_items d
            WHERE NOT EXISTS (
                SELECT 1 FROM items i WHERE i.id = d.id
            )
            ORDER BY d.id {order}
            LIMIT %s
        """, (BATCH_SIZE,))

    ids = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()

    if not ids:
        log("✅ Nothing to enrich.")
        return

    log(f"🔧 Enriching {len(ids)} items with {WORKERS} workers (RoProxy)...")
    log(f"   ID range: {min(ids)} → {max(ids)}")
    start = time.time()

    results = []
    failed = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(fetch_item, iid): iid for iid in ids}
        for i, future in enumerate(as_completed(futures), 1):
            try:
                item_id, data = future.result(timeout=30)
                if data:
                    results.append((item_id, data))
                else:
                    failed += 1
            except Exception:
                failed += 1

            if i <= 10 or i % 50 == 0:
                elapsed = time.time() - start
                rate = i / elapsed if elapsed > 0 else 0
                log(f"  {i}/{len(ids)} — ok: {len(results)}, fail: {failed} ({rate:.1f}/s)")

    log(f"✅ Downloaded {len(results)} items in {time.time()-start:.1f}s")

    # ---- DB WRITE ----
    conn = get_db_connection()
    cur = conn.cursor()
    enriched = 0
    emote_count = 0
    for item_id, d in results:
        try:
            favs = d.get("favoriteCount", 0) or 0
            sales = d.get("purchaseCount", 0) or 0
            price = d.get("price", 0) or 0
            name = d.get("name", "") or ""
            desc = d.get("description", "") or ""
            creator = d.get("creatorName", "") or ""
            asset_type = d.get("assetType", 0) or 0

            if asset_type == 61:
                emote_count += 1

            cur.execute("""
                INSERT INTO items (
                    id, name, favorite_count, price, total_sales,
                    description, creator_name, asset_type_id
                )
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
    cur.close()
    conn.close()
    log(f"✅ Enriched {enriched} items ({emote_count} emotes) in {time.time()-start:.1f}s total.")


if __name__ == "__main__":
    enrich_items()
