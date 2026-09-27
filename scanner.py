import os
import requests
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from psycopg2.extras import execute_values
from database import get_db_connection, setup_database

CATALOG_API = "https://catalog.roblox.com/v1/search/items"
CATEGORIES = [11, 3, 4, 12]
SORT_TYPES = [0, 1, 2, 3, 4, 5]
WORKERS = 8   # parallel queries (safe for Roblox)
DELAY = 0.15  # per-page delay per worker

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

STOP_WORDS = {
    "the","a","an","and","of","in","to","for","is","on","that","by","with",
    "from","as","it","at","be","or","no","not","but","all","are","was","were",
    "they","them","his","her","my","your","its","i","you","he","she","we","me",
    "us","our","new","one","if","so","up","out","just","can","also","do","get"
}


def get_dynamic_keywords():
    """
    Pull top learned keywords from the `learned_keywords` table (populated by
    discover_keywords.py). This is the self-learning loop.
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT keyword FROM learned_keywords 
            ORDER BY score DESC 
            LIMIT 300
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        existing = set(UGC_KEYWORDS + CLASSIC_KEYWORDS + EMOTE_KEYWORDS)
        dynamic = [row[0] for row in rows if row[0] and row[0] not in existing][:200]
        print(f"🧠 Loaded {len(dynamic)} learned keywords from database.")
        return dynamic
    except Exception as e:
        print(f"⚠️ Could not load learned keywords (table may be empty): {e}")
        return []


def scan_query(params):
    """Run one query, paginate, return a set of IDs. Thread-safe."""
    found = set()
    cursor = ""
    pages = 0
    while True:
        p = params.copy()
        p["cursor"] = cursor
        try:
            resp = requests.get(CATALOG_API, params=p, timeout=10)
            if resp.status_code == 429:
                time.sleep(2)
                continue
            if resp.status_code != 200:
                break
            data = resp.json()
            for item in data.get("data", []):
                found.add(item["id"])
            cursor = data.get("nextPageCursor")
            if not cursor or pages > 40:
                break
            pages += 1
        except Exception:
            break
        time.sleep(DELAY)
    return found


def build_all_queries():
    queries = []

    # Categories × sort types
    for cat in CATEGORIES:
        for sort in SORT_TYPES:
            queries.append({"category": cat, "sortType": sort, "limit": 30})

    # UGC keywords
    for kw in UGC_KEYWORDS:
        for sort in [0, 2]:
            queries.append({"keyword": kw, "sortType": sort, "limit": 30, "category": 11})

    # Classic keywords
    for kw in CLASSIC_KEYWORDS:
        for sort in [0, 2]:
            queries.append({"keyword": kw, "sortType": sort, "limit": 30, "category": 3})

    # Emote keywords
    for kw in EMOTE_KEYWORDS:
        for sort in [0, 2]:
            queries.append({"keyword": kw, "sortType": sort, "limit": 30, "category": 12})

    # Price ranges
    for min_p, max_p in PRICE_RANGES:
        for cat in [11, 3, 12]:
            queries.append({
                "minPrice": min_p, "maxPrice": max_p,
                "category": cat, "sortType": 2, "limit": 30
            })

    # NEW: learned keywords from discover_keywords.py
    dynamic = get_dynamic_keywords()
    for kw in dynamic:
        queries.append({"keyword": kw, "sortType": 2, "limit": 30})
        # Also scan without category restriction for broader reach
        queries.append({"keyword": kw, "sortType": 0, "limit": 30})

    return queries


def run_scanner():
    setup_database()
    queries = build_all_queries()
    print(f"🚀 Running {len(queries)} queries with {WORKERS} parallel workers...")
    start = time.time()

    all_ids = set()
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(scan_query, q): q for q in queries}
        for i, future in enumerate(as_completed(futures), 1):
            try:
                found = future.result()
                all_ids.update(found)
            except Exception as e:
                print(f"Query failed: {e}")
            if i % 20 == 0:
                print(f"  {i}/{len(queries)} queries done — {len(all_ids)} unique IDs so far")

    print(f"✅ Scan collected {len(all_ids)} unique IDs in {time.time()-start:.1f}s")

    # ---- BULK INSERT ----
    conn = get_db_connection()
    cur = conn.cursor()
    ids_list = [(iid,) for iid in all_ids]

    new_count = 0
    chunk_size = 1000
    for i in range(0, len(ids_list), chunk_size):
        chunk = ids_list[i:i+chunk_size]
        execute_values(
            cur,
            "INSERT INTO discovered_items (id) VALUES %s ON CONFLICT (id) DO NOTHING",
            chunk
        )
        new_count += cur.rowcount
        conn.commit()

    cur.close()
    conn.close()
    print(f"✅ Inserted {new_count} NEW item IDs into the database.")


if __name__ == "__main__":
    run_scanner()
