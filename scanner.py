import os
import sys
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from psycopg2.extras import execute_values
from database import get_db_connection, setup_database


def log(msg):
    print(msg, flush=True)


# RoProxy — relays Roblox API calls from residential IPs so keyword search works
CATALOG_APIS = [
    "https://catalog.roproxy.com/v1/search/items",
    "https://catalog.roblox.com/v1/search/items",
]

CATEGORIES = [11, 3, 4, 12, 5]
SORT_TYPES = [0, 1, 2, 3, 4, 5]
WORKERS = 3
DELAY = 0.2
MAX_PAGES_PER_QUERY = 15   # bumped from 10 → deeper emote coverage
HTTP_TIMEOUT = 10
MAX_429_RETRIES = 3
QUERY_TIMEOUT = 60

# ---------------------------------------------------------------------------
# EMOTE DISCOVERY — the critical fix
# Roblox catalog: category 12 = Community Creations, subcategory 39 = Emotes
# Without subcategory 39, emotes get buried under other Community Creations items.
# ---------------------------------------------------------------------------
EMOTE_CATEGORY = 12
EMOTE_SUBCATEGORY = 39

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.roblox.com/",
    "Origin": "https://www.roblox.com",
}

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

# Massively expanded — 180 terms to catch every emote subgenre
EMOTE_KEYWORDS = [
    # Core dance moves
    "dance", "floss", "griddy", "dab", "moonwalk", "shuffle", "renegade",
    "wave", "spin", "twirl", "kick", "bounce", "jump", "walk", "run",
    "gangnam", "salsa", "ballet", "breakdance", "krump", "hiphop", "hip-hop",
    "twist", "robot", "vogue", "stanky", "dougie", "whip", "nae nae",
    "harlem shake", "milky", "milkshake", "tiktok", "renegade",
    # Gestures / reactions
    "wave", "clap", "cheer", "salute", "pose", "flex", "point", "thumbsup",
    "peace", "handshake", "hug", "highfive", "fist", "bump", "heart",
    "kiss", "wink", "nod", "shrug", "pray", "beg", "thumbs",
    # Emotions
    "laugh", "cry", "rage", "angry", "sad", "happy", "silly", "cringe",
    "shy", "embarrassed", "confused", "shock", "surprised", "smile", "smirk",
    # Idle / movement loops
    "idle", "sit", "crouch", "sleep", "meditate", "levitate", "float",
    "hover", "fly", "swim", "swim", "victory", "defeat", "die", "fall",
    # Animal / character emotes
    "cat", "dog", "bunny", "bear", "panda", "fox", "wolf", "dragon",
    "frog", "monkey", "penguin", "duck", "chicken", "crab", "snake",
    # Anime / pop culture
    "anime", "naruto", "dragonball", "jujutsu", "demon slayer", "onepiece",
    "kpop", "blackpink", "bts", "twice", "bts", "korean", "japanese",
    "jojo", "sasuke", "goku", "luffy", "itachi", "gojo", "levi",
    # Slang / meme emotes
    "sigma", "rizz", "skibidi", "ohio", "gyatt", "mewing", "aura",
    "based", "cringe", "sus", "ratio", "goat", "slay", "bussin",
    "griddy", "fanum", "cap", "yeet", "poggers", "bruh", "sussy",
    # Reactions / emotes catalog
    "emote", "expression", "gesture", "reaction", "animation", "loop",
    "greeting", "hello", "goodbye", "welcome", "swag", "hype", "party",
    "groove", "sway", "smooth", "cool", "savage", "epic", "goofy",
    # Russian / cultural
    "russian", "slav", "kazakh", "polish", "gangnam", "bollywood",
    # Misc viral
    "sturdy", "default", "classic", "old", "nostalgia", "retro",
    "among", "imposter", "fortnite", "minecraft", "fnaf", "poppy",
    "twerk", "booty", "shmoney", "hit", "folks",
    # Emotional reactions
    "smug", "laughing", "crying", "sobbing", "dying", "dead", "ghost",
    # Sports / action
    "boxing", "karate", "taekwondo", "kungfu", "punch", "kickbox",
]

PRICE_RANGES = [(0, 0), (1, 10), (11, 50), (51, 100), (101, 500), (501, 10000)]


def get_dynamic_keywords():
    log("🧠 Loading learned keywords...")
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT keyword FROM learned_keywords ORDER BY score DESC LIMIT 100")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        existing = set(UGC_KEYWORDS + CLASSIC_KEYWORDS + EMOTE_KEYWORDS)
        dynamic = [row[0] for row in rows if row[0] and row[0] not in existing][:80]
        log(f"🧠 Loaded {len(dynamic)} learned keywords.")
        return dynamic
    except Exception as e:
        log(f"⚠️ Learned keywords error: {e}")
        return []


def try_api(api_url, params):
    """Try one API endpoint. Return (found_set, success_bool)."""
    found = set()
    cursor = ""
    pages = 0
    retries_429 = 0

    while pages < MAX_PAGES_PER_QUERY:
        p = params.copy()
        p["cursor"] = cursor
        try:
            resp = requests.get(
                api_url,
                params=p,
                headers=HEADERS,
                timeout=HTTP_TIMEOUT
            )
            if resp.status_code == 429:
                retries_429 += 1
                if retries_429 > MAX_429_RETRIES:
                    return found, len(found) > 0
                time.sleep(1)
                continue

            if resp.status_code != 200:
                return found, len(found) > 0

            data = resp.json()
            for item in data.get("data", []):
                found.add(item["id"])

            cursor = data.get("nextPageCursor")
            if not cursor:
                return found, True

            pages += 1
        except Exception:
            return found, len(found) > 0

        time.sleep(DELAY)

    return found, True


def scan_query(params):
    """Try RoProxy first, fall back to direct Roblox."""
    for api_url in CATALOG_APIS:
        found, success = try_api(api_url, params)
        if found:
            return found
    return set()


def build_all_queries():
    log("🔨 Building query list...")
    queries = []

    # ---- General category scans ----
    for cat in CATEGORIES:
        for sort in SORT_TYPES:
            queries.append({"category": cat, "sortType": sort, "limit": 30})

    # =========================================================
    # DEDICATED EMOTE DISCOVERY — the fix
    # Category 12 + Subcategory 39 = Emotes specifically
    # =========================================================
    for sort in SORT_TYPES:
        queries.append({
            "category": EMOTE_CATEGORY,
            "subcategory": EMOTE_SUBCATEGORY,
            "sortType": sort,
            "limit": 30,
        })

    # Emote price-band sweeps — catches cheap + premium emotes
    for min_p, max_p in PRICE_RANGES:
        queries.append({
            "category": EMOTE_CATEGORY,
            "subcategory": EMOTE_SUBCATEGORY,
            "minPrice": min_p,
            "maxPrice": max_p,
            "sortType": 2,
            "limit": 30,
        })

    # =========================================================
    # KEYWORD SEARCHES
    # =========================================================
    all_keywords = list(set(UGC_KEYWORDS + CLASSIC_KEYWORDS + EMOTE_KEYWORDS))
    for kw in all_keywords:
        for sort in [0, 2]:
            queries.append({"keyword": kw, "sortType": sort, "limit": 30})

    # Emote keyword + subcategory combined (deep coverage)
    for kw in EMOTE_KEYWORDS[:60]:  # top 60 emote keywords get extra depth
        queries.append({
            "keyword": kw,
            "category": EMOTE_CATEGORY,
            "subcategory": EMOTE_SUBCATEGORY,
            "sortType": 2,
            "limit": 30,
        })

    # ---- Price sweep for non-emote categories ----
    for min_p, max_p in PRICE_RANGES:
        queries.append({"minPrice": min_p, "maxPrice": max_p, "sortType": 2, "limit": 30})

    # ---- Learned keywords from DB ----
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

            if done <= 10 or done % 10 == 0:
                log(f"  {done}/{len(queries)} — {len(all_ids)} IDs")

    log(f"✅ Scan collected {len(all_ids)} IDs in {time.time()-start:.1f}s")

    if not all_ids:
        log("⚠️ No IDs collected — bailing.")
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
    cur.close()
    conn.close()
    log(f"✅ Inserted {new_count} NEW item IDs.")


if __name__ == "__main__":
    try:
        run_scanner()
    except Exception as e:
        log(f"❌ FATAL: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
