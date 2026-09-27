import os
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import get_db_connection, setup_database

ITEM_API = "https://catalog.roblox.com/v1/catalog/items/{}/details?itemType=Asset"
AUTH_URL = "https://auth.roblox.com/v2/logout"

BATCH_SIZE = 500
WORKERS = 2              # low workers = fewer rate limits
ITEM_DELAY = 0.4         # seconds between item requests per worker

COOKIE = os.getenv("ROBLOSECURITY_COOKIE")
if not COOKIE:
    raise ValueError("ROBLOSECURITY_COOKIE environment variable not set!")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

session = requests.Session()
session.cookies[".ROBLOSECURITY"] = COOKIE
session.headers.update(HEADERS)


def get_csrf_token():
    print("🔐 Fetching X-CSRF-Token...", flush=True)
    try:
        resp = session.post(AUTH_URL, timeout=10)
        token = resp.headers.get("X-CSRF-Token")
        if token:
            session.headers["X-CSRF-Token"] = token
            print(f"✅ Got CSRF token: {token[:8]}...", flush=True)
            return True
        return False
    except Exception as e:
        print(f"❌ CSRF error: {e}", flush=True)
        return False


def fetch_item(item_id):
    """Fetch one item, with rate-limit backoff."""
    for attempt in range(4):
        try:
            resp = session.get(ITEM_API.format(item_id), timeout=10)
            if resp.status_code == 200:
                return item_id, resp.json()
            if resp.status_code == 429:
                wait = 2 + attempt * 2
                time.sleep(wait)
                continue
            if resp.status_code == 403:
                # CSRF expired
                get_csrf_token()
                continue
            return item_id, None
        except Exception:
            time.sleep(1)
    return item_id, None


def enrich_items():
    setup_database()
    conn = get_db_connection()
    cur = conn.cursor()

    if not get_csrf_token():
        print("❌ Cannot proceed without CSRF token.", flush=True)
        cur.close(); conn.close()
        return

    cur.execute("""
        SELECT id FROM discovered_items 
        WHERE id NOT IN (SELECT id FROM items) 
        LIMIT %s
    """, (BATCH_SIZE,))
    ids = [row[0] for row in cur.fetchall()]
    cur.close(); conn.close()

    if not ids:
        print("✅ Nothing to enrich.", flush=True)
        return

    print(f"🔧 Enriching {len(ids)} items with {WORKERS} workers...", flush=True)
    start = time.time()

    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(fetch_item, iid): iid for iid in ids}
        for i, future in enumerate(as_completed(futures), 1):
            item_id, data = future.result()
            if data:
                results.append((item_id, data))
            if i % 50 == 0:
                print(f"  Fetched {i}/{len(ids)}... ({len(results)} success)", flush=True)

    print(f"✅ Downloaded {len(results)} items in {time.time()-start:.1f}s", flush=True)

    # ---- DB WRITE ----
    conn = get_db_connection()
    cur = conn.cursor()
    enriched = 0
    for item_id, d in results:
        try:
            favs = d.get("favoriteCount", 0) or 0
            sales = d.get("purchaseCount", 0) or 0
            price = d.get("price", 0) or 0
            name = d.get("name", "") or ""
            desc = d.get("description", "") or ""
            creator = d.get("creatorName", "") or ""
            asset_type = d.get("assetType", 0) or 0

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
                    fetched_at = CURRENT_TIMESTAMP
            """, (item_id, name, favs, price, sales, desc, creator, asset_type))

            cur.execute("""
                INSERT INTO item_history (item_id, favorite_count, total_sales, price)
                VALUES (%s, %s, %s, %s)
            """, (item_id, favs, sales, price))

            enriched += 1
        except Exception as e:
            print(f"  DB error {item_id}: {e}", flush=True)

    conn.commit()
    cur.close(); conn.close()
    print(f"✅ Enriched {enriched} items in {time.time()-start:.1f}s total.", flush=True)


if __name__ == "__main__":
    enrich_items()
