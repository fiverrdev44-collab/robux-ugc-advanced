import os
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import get_db_connection, setup_database

ECONOMY_API = "https://economy.roblox.com/v2/assets/{}/details"
CATALOG_API = "https://catalog.roblox.com/v1/catalog/items/{}/details?itemType=Asset"

BATCH_SIZE = 500
WORKERS = 10
FORCE_REFRESH = True   # set True to re-enrich already-processed items

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def fetch_detail(item_id):
    """Fetch from BOTH endpoints and merge data."""
    merged = {}

    # Economy API — sales, price, description, creator
    try:
        resp = requests.get(ECONOMY_API.format(item_id), headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            merged.update(resp.json())
    except Exception:
        pass

    # Catalog API — favourite count, purchase count, name
    try:
        resp = requests.get(CATALOG_API.format(item_id), headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            c = resp.json()
            merged["FavoriteCount"] = c.get("favoriteCount", 0)
            merged["PurchaseCount"] = c.get("purchaseCount", 0)
            if not merged.get("Name"):
                merged["Name"] = c.get("name", "")
            if not merged.get("Description"):
                merged["Description"] = c.get("description", "")
    except Exception:
        pass

    if not merged.get("Name"):
        return item_id, None
    return item_id, merged


def enrich_items():
    setup_database()
    conn = get_db_connection()
    cur = conn.cursor()

    if FORCE_REFRESH:
        # Re-fetch everything — useful to fix data after bug fixes
        cur.execute("SELECT id FROM discovered_items LIMIT %s", (BATCH_SIZE,))
    else:
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

    # ---- DB WRITE ----
    conn = get_db_connection()
    cur = conn.cursor()
    enriched = 0
    for item_id, d in results:
        try:
            favs = d.get("FavoriteCount", 0) or 0
            sales = d.get("Sales", 0) or d.get("PurchaseCount", 0) or 0
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
