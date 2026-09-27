import os
import requests
import time
from database import get_db_connection, setup_database

CATALOG_API = "https://catalog.roblox.com/v1/search/items"
CATEGORIES = [11, 3, 4, 12]
SORT_TYPES = [0, 1, 2, 3, 4, 5]

UGC_KEYWORDS = [
    "hat", "hair", "face", "shirt", "pants", "jacket", "shoe", "wing", "tail",
    "ear", "horn", "crown", "chain", "necklace", "backpack", "bag", "sword",
    "gun", "pet", "animal", "cute", "emo", "goth", "y2k", "pastel", "cyber",
    "kawaii", "fluffy", "bear", "cat", "dog", "dragon", "angel", "demon",
    "robot", "mecha", "armor", "cape", "mask", "glasses", "eyepatch", "bandage"
]

CLASSIC_KEYWORDS = [
    "t-shirt", "tshirt", "shirt", "pants", "jeans", "hoodie", "sweater",
    "jacket", "plaid", "flannel", "preppy", "grunge", "y2k", "emo", "goth",
    "aesthetic", "streetwear", "casual", "formal", "school", "uniform",
    "dress", "skirt", "shorts", "cargo", "denim", "leather", "sports",
    "jersey", "varsity", "anime", "kawaii", "cute", "dark", "light", "neon"
]

EMOTE_KEYWORDS = [
    "dance", "floss", "wave", "griddy", "emote", "russian", "meme",
    "orange justice", "default dance", "renegade", "crip walk", "shuffle",
    "spin", "twirl", "backflip", "frontflip", "kick", "punch", "punching",
    "idle", "crouch", "sit", "sleep", "laugh", "cry", "crying", "rage",
    "cute", "kawaii", "silly", "cat", "dog", "bunny", "dab", "whip",
    "nae nae", "gangnam", "fortnite", "sigma", "rizz", "gyatt", "skibidi",
    "hip hop", "ballet", "breakdance", "moonwalk", "robot", "salsa", "tango",
    "victory", "defeat", "greeting", "wave hello", "clap", "cheer", "pose",
    "flex", "point", "salute", "bow", "dance loop", "running", "walk",
    "swimming", "flying", "float", "aura", "vibe", "glitch", "anime"
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
    total = 0

    for cat in CATEGORIES:
        for sort in SORT_TYPES:
            print(f"  Category {cat}, Sort {sort}...")
            total += fetch_and_store_ids({"category": cat, "sortType": sort, "limit": 30})

    print("\n  --- UGC Keywords ---")
    for kw in UGC_KEYWORDS:
        for sort in [0, 2]:
            print(f"  UGC '{kw}' sort {sort}...")
            total += fetch_and_store_ids({"keyword": kw, "sortType": sort, "limit": 30, "category": 11})

    print("\n  --- Classic Clothing Keywords ---")
    for kw in CLASSIC_KEYWORDS:
        for sort in [0, 2]:
            print(f"  Classic '{kw}' sort {sort}...")
            total += fetch_and_store_ids({"keyword": kw, "sortType": sort, "limit": 30, "category": 3})

    print("\n  --- Emote Keywords ---")
    for kw in EMOTE_KEYWORDS:
        for sort in [0, 2]:
            print(f"  Emote '{kw}' sort {sort}...")
            total += fetch_and_store_ids({"keyword": kw, "sortType": sort, "limit": 30, "category": 12})

    for min_p, max_p in PRICE_RANGES:
        for cat in [11, 3, 12]:
            print(f"  Price {min_p}-{max_p}, Cat {cat}...")
            total += fetch_and_store_ids({"minPrice": min_p, "maxPrice": max_p, "category": cat, "sortType": 2, "limit": 30})

    print(f"\n✅ Scanner done. {total} new IDs.")


if __name__ == "__main__":
    run_scanner()
