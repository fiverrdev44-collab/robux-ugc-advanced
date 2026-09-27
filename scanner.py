import os
import sys
import requests
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from psycopg2.extras import execute_values
from database import get_db_connection, setup_database

def log(msg):
    """Print with immediate flush for GitHub Actions."""
    print(msg, flush=True)

CATALOG_API = "https://catalog.roblox.com/v1/search/items"
CATEGORIES = [11, 3, 4, 12]
SORT_TYPES = [0, 1, 2, 3, 4, 5]
WORKERS = 6
DELAY = 0.1
MAX_PAGES_PER_QUERY = 20
HTTP_TIMEOUT = 8

UGC_KEYWORDS = [
    "hat", "hair", "face", "shirt", "pants", "jacket", "shoe", "wing", "tail",
    "ear", "horn", "crown", "chain", "necklace", "backpack", "bag", "sword",
    "pet", "cute", "emo", "goth", "y2k", "pastel", "cyber", "kawaii", "fluffy",
    "bear", "cat", "dog", "dragon", "angel", "demon", "robot", "armor", "cape",
    "mask", "glasses", "bandage", "coquette", "grunge", "vampire", "fairy"
]

CLASSIC_KEYWORDS = [
    "t-shirt", "tshirt", "shirt", "pants", "jeans", "hoodie", "sweater",
    "jacket", "plaid", "flannel", "preppy", "grunge", "y2k", "emo", "goth",
    "aesthetic", "streetwear", "casual", "dress", "skirt", "shorts", "cargo",
    "denim", "leather", "sports", "jersey", "varsity", "anime", "kawaii"
]

EMOTE_KEYWORDS = [
    "dance", "floss", "wave", "griddy", "emote", "russian", "meme",
    "renegade", "shuffle", "spin", "flip", "kick", "punch", "idle", "sit",
    "laugh", "cry", "rage", "silly", "bunny", "dab", "sigma", "rizz",
    "skibidi", "moonwalk", "robot", "victory", "clap", "cheer", "flex",
    "salute", "pose", "walk", "swim", "fly", "float", "anime", "aura"
]

PRICE_RANGES = [(0, 0), (1, 10), (11, 50), (51, 100), (101, 500)]

STOP_WORDS = {"the","a","an","and","of","in","to","for","is","on","that","by","with"}


def get_dynamic_keywords():
    log("🧠 Loading learned keywords from DB...")
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT keyword FROM learned_keywords ORDER BY score DESC LIMIT 200")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        existing = set(UGC_KEYWORDS + CLASSIC_KEYWORDS + EMOTE_KEYWORDS)
        dynamic = [row[0] for row in rows if row[0] and row[0] not in existing][:150]
        log(f"🧠 Loaded {len(dynamic)} learned keywords.")
        return dynamic
    except Exception as e:
        log(f"⚠️ Could not load learned keywords: {e}")
        return []


def scan_query(params):
    found = set()
    cursor = ""
    pages = 0
    while pages < MAX_PAGES_PER_QUERY:
        p = params.copy()
        p["cursor"] = cursor
        try:
            resp = requests.get(CATALOG_API, params=p, timeout=HTTP_TIMEOUT)
            if resp.status_code == 429:
                time.sleep(2)
                continue
            if resp.status_code != 200:
                break
            data = resp.json()
            for item in data.get("data", []):
                found.add(item["id"])
            cursor = data.get("nextPageCursor")
            if not cursor:
                break
            pages += 1
        except Exception:
            break
        time.sleep(DELAY)
    return found


def build_all_queries():
    log("🔨 Building query list...")
    queries = []
    for cat in CATEGORIES:
        for sort in SORT_TYPES:
            queries.append({"category": cat, "sortType": sort, "limit": 30})
    for kw in UGC_KEYWORDS:
        for sort in [0, 2]:
            queries.append({"keyword": kw, "sortType": sort, "limit": 30, "category": 11})
    for kw in CLASSIC_KEYWORDS:
        for sort in [0, 2]:
            queries.append({"keyword": kw, "sortType": sort, "limit": 30, "category": 3})
    for kw in EMOTE_KEYWORDS:
        for sort in [0, 2]:
            queries.append({"keyword": kw, "sortType": sort, "limit": 30, "category": 12})
    for min_p, max_p in PRICE_RANGES:
        for cat in [11, 3, 12]:
            queries.append({"minPrice": min_p, "maxPrice": max_p, "category": cat, "sortType": 2, "limit": 30})
    dynamic = get_dynamic_keywords()
    for kw in dynamic:
        queries.append({"keyword": kw, "sortType": 2, "limit": 30})
    log(f"🔨 Built {len(queries)} queries.")
    return queries


def run_scanner():
    log("🚀 Scanner started.")
    setup_database()
    log("📦 DB setup done.")

    queries = build_all_queries()
    log(f"🚀 Running {len(queries)} queries with {WORKERS} parallel workers...")
    start = time.time()

    all_ids = set()
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(scan_query, q): q for q in queries}
        done = 0
        for future in as_completed(futures):
            done += 1
            try:
                found = future.result(timeout=30)
                all_ids.update(found)
            except Exception as e:
                log(f"  Query failed: {e}")
            if done % 20 == 0:
                log(f"  {done}/{len(queries)} queries done — {len(all_ids)} unique IDs so far")

    log(f"✅ Scan collected {len(all_ids)} unique IDs in {time.time()-start:.1f}s")

    log("💾 Writing to database...")
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
    log(f"✅ Inserted {new_count} NEW item IDs into the database.")


if __name__ == "__main__":
    try:
        run_scanner()
    except Exception as e:
        log(f"❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
