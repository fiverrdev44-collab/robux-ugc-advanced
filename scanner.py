import os
import requests
import time
from database import get_db_connection, setup_database

CATALOG_API = "https://catalog.roblox.com/v1/search/items"
CATEGORIES = [11, 3, 4, 12]
SORT_TYPES = [0, 1, 2, 3, 4, 5]
SEED_KEYWORDS = [
    "hat", "hair", "face", "shirt", "pants", "jacket", "shoe", "wing", "tail",
    "ear", "horn", "crown", "chain", "necklace", "backpack", "bag", "sword",
    "gun", "pet", "animal", "cute", "emo", "goth", "y2k", "pastel", "cyber",
    "kawaii", "fluffy", "bear", "cat", "dog", "dragon", "angel", "demon",
    "robot", "mecha", "armor", "cape", "mask", "glasses", "eyepatch", "bandage"
]
PRICE_RANGES = [(0, 0), (1, 10), (11, 50), (51, 100), (101, 500), (501, 10000)]
DELAY = 0.4

def fetch_and_store_ids(params):
    conn = get_db_connection()
    cur = conn.cursor()
    cursor = ""
    new_ids = 0
    while True:
        p = params.copy()
        p["cursor"] = cursor
        try:
            resp = requests.get(CATALOG_API, params=p, timeout=10)
            if resp.status_code == 429:
                print("Rate limited. Sleeping 60s...")
                time.sleep(60)
                continue
            if resp.status_code != 200:
                break
            data = resp.json()
            items = data.get("data", [])
            for item in items:
                cur.execute(
                    "INSERT INTO discovered_items (id) VALUES (%s) ON CONFLICT (id) DO NOTHING",
                    (item["id"],)
                )
                if cur.rowcount > 0:
                    new_ids += 1
            conn.commit()
            cursor = data.get("nextPageCursor")
            if not cursor:
                break
        except Exception as e:
            print(f"Error: {e}")
            break
        time.sleep(DELAY)
    cur.close()
    conn.close()
    return new_ids

def run_scanner():
    setup_database()
    print("🚀 Starting Full Catalog Scanner...")
    total_new_ids = 0

    for cat in CATEGORIES:
        for sort in SORT_TYPES:
            print(f"  Scanning Category {cat}, Sort {sort}...")
            params = {"category": cat, "sortType": sort, "limit": 30}
            total_new_ids += fetch_and_store_ids(params)

    for kw in SEED_KEYWORDS:
        for sort in [0, 2]:
            print(f"  Scanning Keyword '{kw}', Sort {sort}...")
            params = {"keyword": kw, "sortType": sort, "limit": 30, "category": 11}
            total_new_ids += fetch_and_store_ids(params)

    for min_p, max_p in PRICE_RANGES:
        for cat in [11, 3]:
            print(f"  Scanning Price {min_p}-{max_p}, Category {cat}...")
            params = {"minPrice": min_p, "maxPrice": max_p, "category": cat, "sortType": 2, "limit": 30}
            total_new_ids += fetch_and_store_ids(params)

    print(f"\n✅ Scanner finished. Discovered {total_new_ids} new item IDs.")

if __name__ == "__main__":
    run_scanner()
