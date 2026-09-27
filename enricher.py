import os
import requests
import time
from database import get_db_connection, setup_database

CATALOG_DETAILS_API = "https://catalog.roblox.com/v1/catalog/items/details"
AUTH_URL = "https://auth.roblox.com/v2/logout"

BATCH_SIZE = 500
CHUNK_SIZE = 100           # reduced from 120 — smaller requests = less likely to trigger 429
CHUNK_DELAY = 15           # seconds between chunks — much slower, but reliable
MAX_429_RETRIES = 5        # retries on rate-limit before giving up on a chunk
RETRY_WAIT = 10            # seconds to wait between 429 retries

COOKIE = os.getenv("ROBLOSECURITY_COOKIE")
if not COOKIE:
    raise ValueError("ROBLOSECURITY_COOKIE environment variable not set!")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
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
        print(f"❌ Failed. Status: {resp.status_code}", flush=True)
        return False
    except Exception as e:
        print(f"❌ CSRF error: {e}", flush=True)
        return False


def fetch_batch(item_ids):
    """Fetch one batch with aggressive retry on 429."""
    payload = {"items": [{"itemType": "Asset", "id": iid} for iid in item_ids]}

    for attempt in range(MAX_429_RETRIES):
        try:
            resp = session.post(CATALOG_DETAILS_API, json=payload, timeout=20)

            if resp.status_code == 200:
                return resp.json().get("data", [])

            if resp.status_code == 403:
                print("  CSRF expired, refreshing...", flush=True)
                if get_csrf_token():
                    continue

            if resp.status_code == 429:
                wait = RETRY_WAIT * (attempt + 1)   # exponential: 10, 20, 30, 40, 50s
                print(f"  429 — waiting {wait}s (attempt {attempt+1}/{MAX_429_RETRIES})...", flush=True)
                time.sleep(wait)
                continue

            print(f"  HTTP {resp.status_code}", flush=True)
            time.sleep(2)

        except Exception as e:
            print(f"  Batch error: {e}", flush=True)
            time.sleep(3)

    return []


def enrich_items():
    setup_database()
    conn = get_db_connection()
    cur = conn.cursor()

    if not get_csrf_token():
        print("❌ Cannot proceed without CSRF token.", flush=True)
        cur.close()
        conn.close()
        return

    cur.execute("""
        SELECT id FROM discovered_items 
        WHERE id NOT IN (SELECT id FROM items) 
        LIMIT %s
    """, (BATCH_SIZE,))
    ids = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()

    if not ids:
        print("✅ Nothing to enrich.", flush=True)
        return

    print(f"🔧 Enriching {len(ids)} items in chunks of {CHUNK_SIZE}...", flush=True)
    start = time.time()

    all_data = []
    for i in range(0, len(ids), CHUNK_SIZE):
        chunk = ids[i:i+CHUNK_SIZE]
        chunk_num = i // CHUNK_SIZE + 1
        batch = fetch_batch(chunk)
        all_data.extend(batch)
        print(f"  Chunk {chunk_num}: {len(batch)}/{len(chunk)} items", flush=True)

        # Only delay if there are more chunks to process
        if i + CHUNK_SIZE < len(ids):
            print(f"  Sleeping {CHUNK_DELAY}s before next chunk...", flush=True)
            time.sleep(CHUNK_DELAY)

    print(f"✅ Downloaded {len(all_data)} items in {time.time()-start:.1f}s", flush=True)

    # ---- DB WRITE ----
    conn = get_db_connection()
    cur = conn.cursor()
    enriched = 0
    for d in all_data:
        try:
            item_id = d.get("id")
            if not item_id:
                continue

            favs = d.get("favoriteCount", 0) or 0
            sales = d.get("purchaseCount", 0) or 0
            price = d.get("price", 0) or 0
            creator = d.get("creatorName", "") or ""
            name = d.get("name", "") or ""
            desc = d.get("description", "") or ""
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
            print(f"  DB error {d.get('id')}: {e}", flush=True)

    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ Enriched {enriched} items in {time.time()-start:.1f}s total.", flush=True)


if __name__ == "__main__":
    enrich_items()
