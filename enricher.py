import os
import requests
import time
from database import get_db_connection, setup_database

CATALOG_DETAILS_API = "https://catalog.roblox.com/v1/catalog/items/details"
BATCH_SIZE = 500        # items to process per run
CHUNK_SIZE = 120        # Roblox API limit per POST request

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def fetch_batch(item_ids):
    """Fetch details for up to 120 items in ONE POST request."""
    payload = {"items": [{"itemType": "Asset", "id": iid} for iid in item_ids]}
    for attempt in range(3):
        try:
            resp = requests.post(
                CATALOG_DETAILS_API,
                json=payload,
                headers=HEADERS,
                timeout=15
            )
            if resp.status_code == 200:
                return resp.json().get("data", [])
            if resp.status_code == 429:
                print(f"  Rate-limited, waiting 3s...")
                time.sleep(3)
                continue
            print(f"  Batch HTTP {resp.status_code}")
        except Exception as e:
            print(f"  Batch error: {e}")
            time.sleep(1)
    return []


def enrich_items():
    setup_database()
    conn = get_db_connection()
    cur = conn.cursor()

    # Get IDs that haven't been enriched yet
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

    print(f"🔧 Enriching {len(ids)} items in batches of {CHUNK_SIZE}...")
    start = time.time()

    # ---- FETCH IN BATCHES ----
    all_data = []
    for i in range(0, len(ids), CHUNK_SIZE):
        chunk = ids[i:i+CHUNK_SIZE]
        batch = fetch_batch(chunk)
        all_data.extend(batch)
        print(f"  Chunk {i//CHUNK_SIZE + 1}: got {len(batch)}/{len(chunk)} items")
        time.sleep(0.3)

    print(f"✅ Downloaded {len(all_data)} items in {time.time()-start:.1f}s")

    # ---- WRITE TO DB ----
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
            print(f"  DB error {d.get('id')}: {e}")

    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ Enriched {enriched} items in {time.time()-start:.1f}s total.")


if __name__ == "__main__":
    enrich_items()
