import os
import sys
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from psycopg2.extras import execute_values
from database import get_db_connection, setup_database

def log(msg):
    print(msg, flush=True)

CATALOG_API = "https://catalog.roblox.com/v1/search/items"
CATEGORIES = [11, 3, 4, 12]
SORT_TYPES = [0, 1, 2, 3, 4, 5]
WORKERS = 6
DELAY = 0.1
MAX_PAGES_PER_QUERY = 10
HTTP_TIMEOUT = 6
MAX_429_RETRIES = 3
QUERY_TIMEOUT = 45          # hard cap per future (seconds)

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

PRICE_RANGES = [(0, 0), (1, 10), (11, 50), (51, 100)]


def get_dynamic_keywords():
    log("🧠 Loading learned keywords...")
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT keyword FROM learned_keywords ORDER BY score DESC LIMIT 100")
        rows = cur.fetchall()
        cur.close(); conn.close()
        existing = set(UGC_KEYWORDS + CLASSIC_KEYWORDS + EMOTE_KEYWORDS)
        dynamic = [row[0] for row in rows if row[0] and row[0] not in existing][:80]
        log(f"🧠 Loaded {len(dynamic)} learned keywords.")
        return dynamic
    except Exception as e:
        log(f"⚠️ Learned keywords error: {e}")
        return []


def scan_query(params):
    """Hardened: capped retries, no infinite loops."""
    found = set()
    cursor = ""
    pages = 0
    retries_429 = 0

    while pages < MAX_PAGES_PER_QUERY:
        p = params.copy()
        p["cursor"] = cursor
        try:
            resp = requests.get(CATALOG_API, params=p, timeout=HTTP_TIMEOUT)

            # ---- RATE LIMIT: hard cap ----
            if resp.status_code == 429:
                retries_429 += 1
                if retries_429 > MAX_429_RETRIES:
                    return found  # give up on this query, keep what we have
                time.sleep(1)
                continue

            if resp.status_code != 200:
                return found  # any other error = bail

            data = resp.json()
            for item in data.get("data", []):
                found.add(item["id"])

            cursor = data.get("nextPageCursor")
            if not cursor:
                return found  # no more pages

            pages += 1
        except Exception:
            return found  # timeout/network error = bail

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
            queries.append({"minPrice": min_p, "maxPrice": max_p,
                            "category": cat, "sortType": 2, "limit": 30})
    for kw in get_dynamic_keywords():
        queries.append({"keyword": kw, "sortType": 2, "limit": 30})
    log(f"🔨 Built {len(queries)} queries.")
    return queries


def run_scanner():
    log("🚀 Scanner started.")
    setup_database()
    log("📦 DB setup done.")

    queries = build_all_queries()
    log(f"🚀 Running {len(queries)} queries with {WORKERS} workers...")
    start = time.time()

    all_ids = set()
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(scan_query, q): q for q in queries}
        done = 0
        for future in as_completed(futures):
            done += 1
            try:
                found = future.result(timeout=QUERY_TIMEOUT)
                all_ids.update(found)
            except Exception as e:
                log(f"  Query #{done} failed: {e}")

            # Log every query so we always see progress
            if done <= 10 or done % 10 == 0:
                log(f"  {done}/{len(queries)} — {len(all_ids)} IDs")

    log(f"✅ Scan collected {len(all_ids)} IDs in {time.time()-start:.1f}s")

    if not all_ids:
        log("⚠️ No IDs collected — bailing without writing.")
        return

    log("💾 Writing to database...")
    conn = get_db_connection()
    cur = conn.cursor()
    ids_list = [(iid,) for iid in all_ids]
    new_count = 0
    for i in range(0, len(ids_list), 1000):
        chunk = ids_list[i:i+1000]
        execute_values(
            cur,
            "INSERT INTO discovered_items (id) VALUES %s ON CONFLICT (id) DO NOTHING",
            chunk
        )
        new_count += cur.rowcount
        conn.commit()
    cur.close(); conn.close()
    log(f"✅ Inserted {new_count} NEW item IDs.")


if __name__ == "__main__":
    try:
        run_scanner()
    except Exception as e:
        log(f"❌ FATAL: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
