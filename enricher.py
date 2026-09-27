import os
import requests
import time
from database import get_db_connection, setup_database

DETAILS_API = "https://economy.roblox.com/v2/assets/{}/details"
DELAY = 0.3
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
    ids = [row[0] for row in cur.fetchall()]

    if not ids:
        print("✅ Nothing to enrich.")
        cur.close(); conn.close()
        return

    print(f"🔧 Enriching {len(ids)} items...")
    enriched = 0
    for item_id in ids:
        try:
            resp = requests.get(DETAILS_API.format(item_id), timeout=10)
            if resp.status_code == 200:
                d = resp.json()
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

                conn.commit()
                enriched += 1
            time.sleep(DELAY)
        except Exception as e:
            print(f"Failed {item_id}: {e}")

    cur.close(); conn.close()
    print(f"✅ Enriched {enriched} items.")

if __name__ == "__main__":
    enrich_items()
