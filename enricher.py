import os
import requests
import time
from database import get_db_connection, setup_database

DETAILS_API = "https://economy.roblox.com/v2/assets/{}/details"
DELAY = 0.5
BATCH_SIZE = 500

def enrich_items():
    setup_database()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id FROM discovered_items 
        WHERE id NOT IN (SELECT id FROM items) 
        LIMIT %s
    """, (BATCH_SIZE,))
    ids_to_enrich = [row[0] for row in cur.fetchall()]

    if not ids_to_enrich:
        print("✅ No new items to enrich.")
        cur.close(); conn.close()
        return

    print(f"🔧 Enriching {len(ids_to_enrich)} items...")
    enriched = 0

    for item_id in ids_to_enrich:
        try:
            resp = requests.get(DETAILS_API.format(item_id), timeout=10)
            if resp.status_code == 200:
                d = resp.json()
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
                    item_id,
                    d.get("Name"),
                    d.get("FavoriteCount", 0),
                    d.get("PriceInRobux", 0),
                    d.get("Sales", 0),
                    d.get("Description", ""),
                    d.get("Creator", {}).get("Name", ""),
                    d.get("AssetTypeId"),
                    d.get("Created"),
                    d.get("Updated")
                ))
                conn.commit()
                enriched += 1
            time.sleep(DELAY)
        except Exception as e:
            print(f"Failed to enrich {item_id}: {e}")

    cur.close(); conn.close()
    print(f"✅ Enriched {enriched} items this run.")

if __name__ == "__main__":
    enrich_items()
