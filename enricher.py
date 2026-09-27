import os
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from psycopg2.extras import execute_values
from database import get_db_connection, setup_database

DETAILS_API = "https://economy.roblox.com/v2/assets/{}/details"
BATCH_SIZE = 500
WORKERS = 10   # parallel requests — safe for Roblox


def fetch_detail(item_id):
    """Fetch one item's details. Retries on rate-limit."""
    for attempt in range(3):
        try:
            resp = requests.get(DETAILS_API.format(item_id), timeout=10)
            if resp.status_code == 200:
                return item_id, resp.json()
            if resp.status_code == 429:
                time.sleep(1.5)
                continue
            return item_id, None
        except Exception:
            time.sleep(0.5)
    return item_id, None


def enrich_items():
    setup_database()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id FROM discovered_items 
        WHERE id NOT IN (SELECT id FROM items) 
        LIMIT %s
    """, (BATCH_SIZE,))
    ids = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()

    if not ids:
        print("✅ Nothing to enrich.")
        return

    print(f"🔧 Enriching {len(ids)} items with {WORKERS} workers...")
    start = time.time()

    # ---- PARALLEL FETCH ----
    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(fetch_detail, iid): iid for iid in ids}
        for i, future in enumerate(as_completed(futures), 1):
            item_id, data = future.result()
            if data:
                results.append((item_id, data))
            if i % 50 == 0:
                print(f"  Fetched {i}/{len(ids)}...")

    print(f"✅ Downloaded {len(results)} items in {time.time()-start:.1f}s")

    # ---- SEQUENTIAL DB WRITE (single connection, safe) ----
    conn = get_db_connection()
    cur = conn.cursor()
    enriched = 0
    for item_id, d in results:
        try:
            favs = d.get("FavoriteCount", 0)
            sales = d.get("Sales", 0)
            price = d.get("PriceInRobux", 0) or 0

            cur.execute("""
                INSERT INTO items (
                    id, name, favorite_count, price, total_sales,
                    description, creator_name, asset_type_id,
                    created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    favorite_count = EXCLUDED.favorite_count,
                    total_sales = EXCLUDED.total_sales,
                    price = EXCLUDED.price,
                    description = EXCLUDED.description,
                    fetched_at = CURRENT_TIMESTAMP
            """, (
                item_id, d.get("Name"), favs, price, sales,
                d.get("Description", ""),
                d.get("Creator", {}).get("Name", ""),
                d.get("AssetTypeId"),
                d.get("Created"), d.get("Updated")
            ))

            cur.execute("""
                INSERT INTO item_history (item_id, favorite_count, total_sales, price)
                VALUES (%s, %s, %s, %s)
            """, (item_id, favs, sales, price))

            enriched += 1
        except Exception as e:
            print(f"DB error {item_id}: {e}")

    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ Enriched {enriched} items in {time.time()-start:.1f}s total.")


if __name__ == "__main__":
    enrich_items()
