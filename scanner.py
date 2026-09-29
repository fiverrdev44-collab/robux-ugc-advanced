import os
import sys
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from psycopg2.extras import execute_values
from database import get_db_connection, setup_database


def log(msg):
    print(msg, flush=True)


# ============================================================
# COOKIE POOLING
# ------------------------------------------------------------
# Reads ROBLOSECURITY_COOKIE_1 .. _5 (falls back to single
# ROBLOSECURITY_COOKIE if numbered ones aren't set).
# Each cookie gets its own requests.Session with its own
# cookie jar, so requests spread across accounts and avoid
# per-account rate limits.
# ============================================================
COOKIES = []
for i in range(1, 6):
    c = os.getenv(f"ROBLOSECURITY_COOKIE_{i}")
    if c:
        COOKIES.append(c.strip())

if not COOKIES:
    single = os.getenv("ROBLOSECURITY_COOKIE")
    if single:
        COOKIES.append(single.strip())

if not COOKIES:
    raise ValueError("No ROBLOSECURITY_COOKIE configured!")

# ============================================================
# ENDPOINTS
# ------------------------------------------------------------
# The /details endpoint is REQUIRED for Category+Subcategory
# filtering. Without /details, the API silently ignores filters
# and returns generic items (which is why emotes never showed up).
# ============================================================
CATALOG_APIS = [
    "https://catalog.roproxy.com/v1/search/items/details",
    "https://catalog.roblox.com/v1/search/items/details",
]

# Category 11 = Accessories, 3 = Clothing, 4 = BodyParts,
# 12 = AvatarAnimations (includes Emotes), 5 = Gear,
# 13 = CommunityCreations (UGC landing category)
CATEGORIES = [11, 3, 4, 12, 5, 13]
SORT_TYPES = [0, 1, 2, 3, 4, 5]

# ============================================================
# THROUGHPUT
# ------------------------------------------------------------
# WORKERS scales with cookie count — each cookie gets its own
# dedicated workers, so throughput is roughly N_cookies × 3.
# With 2 cookies = 6 workers = ~2x the old single-cookie speed.
# ============================================================
WORKERS_PER_COOKIE = 3
WORKERS = WORKERS_PER_COOKIE * len(COOKIES)

DELAY = 0.4                # seconds between requests per worker
MAX_PAGES_PER_QUERY = 12
HTTP_TIMEOUT = 10
MAX_429_RETRIES = 3
QUERY_TIMEOUT = 60

# Roblox catalog constants
EMOTE_CATEGORY = 12
EMOTE_SUBCATEGORY = 39
COMMUNITY_CATEGORY = 13

SALES_TYPE_FOR_SALE = 1
ASSET_TYPE_EMOTE = 61

# ============================================================
# ID BOUNDS — CRITICAL FIX
# ------------------------------------------------------------
# Modern Roblox catalog IDs (including ALL UGC emotes created
# since 2023) are 13-15 digits (10^12 – 10^15). The old
# MAX_VALID_ID of 10^10 silently rejected every emote before
# it could be saved.
# ============================================================
MIN_VALID_ID = 1_000_000
MAX_VALID_ID = 100_000_000_000_000_000   # 10^17

# ============================================================
# SESSIONS
# ------------------------------------------------------------
# One requests.Session per cookie. Round-robin selected per
# request so load spreads evenly across accounts.
# ============================================================
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.roblox.com/",
    "Origin": "https://www.roblox.com",
}

SESSIONS = []
for cookie in COOKIES:
    s = requests.Session()
    s.cookies[".ROBLOSECURITY"] = cookie
    s.headers.update(HEADERS)
    SESSIONS.append(s)

_session_idx = 0


def get_session():
    """Round-robin session selection."""
    global _session_idx
    s = SESSIONS[_session_idx % len(SESSIONS)]
    _session_idx += 1
    return s


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
    "dance", "floss", "griddy", "dab", "moonwalk", "shuffle", "renegade",
    "wave", "spin", "twirl", "kick", "bounce", "jump", "walk", "run",
    "gangnam", "salsa", "ballet", "breakdance", "krump", "hiphop",
    "twist", "robot", "vogue", "stanky", "dougie", "whip", "nae nae",
    "milky", "milkshake", "tiktok",
    "clap", "cheer", "salute", "pose", "flex", "point", "thumbsup",
    "peace", "handshake", "hug", "highfive", "heart",
    "kiss", "wink", "nod", "shrug", "pray",
    "laugh", "cry", "rage", "angry", "sad", "happy", "silly", "cringe",
    "shy", "confused", "shock", "surprised", "smile",
    "idle", "sit", "crouch", "sleep", "meditate", "levitate", "float",
    "hover", "fly", "swim", "victory", "defeat", "fall",
    "cat", "dog", "bunny", "bear", "panda", "fox", "wolf", "dragon",
    "frog", "monkey", "penguin", "duck",
    "anime", "naruto", "dragonball", "jujutsu", "demon slayer", "onepiece",
    "kpop", "blackpink", "bts", "twice", "korean", "japanese",
    "jojo", "goku", "luffy", "gojo",
    "sigma", "rizz", "skibidi", "ohio", "gyatt", "mewing", "aura",
    "sus", "ratio", "goat", "slay", "bussin", "fanum", "cap", "yeet", "bruh",
    "emote", "expression", "gesture", "reaction", "animation",
    "greeting", "hello", "goodbye", "welcome", "swag", "hype", "party",
    "groove", "sway", "smooth", "savage", "epic", "goofy",
    "russian", "slav", "bollywood",
    "retro", "among", "imposter", "fortnite", "minecraft", "fnaf",
    "twerk", "shmoney",
    "smug", "crying", "sobbing", "dying", "dead", "ghost",
    "boxing", "karate", "taekwondo", "kungfu", "punch",
]

PRICE_RANGES = [(0, 0), (1, 10), (11, 50), (51, 100), (101, 500), (501, 10000)]


def is_valid_asset_id(iid):
    """Reject bundle IDs, user IDs, timestamps, and any other garbage."""
    try:
        n = int(iid)
    except (TypeError, ValueError):
        return False
    return MIN_VALID_ID <= n <= MAX_VALID_ID


def is_asset_item(item):
    """
    Accept items the API marks as Asset.
    Reject bundles/universes which have different itemTypes.
    """
    if not isinstance(item, dict):
        return False
    item_type = (item.get("itemType") or "").lower()
    if item_type and "asset" not in item_type:
        return False
    return is_valid_asset_id(item.get("id"))


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
    """
    Fetch one query's worth of results across pagination.
    Uses a round-robin session from the cookie pool.
    """
    session = get_session()
    found = set()
    cursor = ""
    pages = 0
    retries_429 = 0

    while pages < MAX_PAGES_PER_QUERY:
        p = params.copy()
        p["cursor"] = cursor
        try:
            resp = session.get(api_url, params=p, timeout=HTTP_TIMEOUT)
            if resp.status_code == 429:
                retries_429 += 1
                if retries_429 > MAX_429_RETRIES:
                    return found, len(found) > 0
                retry_after = int(resp.headers.get("Retry-After", 2))
                time.sleep(retry_after)
                # Rotate to a different cookie on 429
                session = get_session()
                continue

            if resp.status_code != 200:
                return found, len(found) > 0

            data = resp.json()
            for item in data.get("data", []):
                if is_asset_item(item):
                    found.add(int(item["id"]))

            cursor = data.get("nextPageCursor")
            if not cursor:
                return found, True

            pages += 1
        except Exception:
            return found, len(found) > 0

        time.sleep(DELAY)

    return found, True


def scan_query(params):
    for api_url in CATALOG_APIS:
        found, success = try_api(api_url, params)
        if found:
            return found
    return set()


def build_all_queries():
    log("🔨 Building query list...")
    queries = []

    # ---- General category sweeps ----
    for cat in CATEGORIES:
        for sort in SORT_TYPES:
            queries.append({
                "category": cat,
                "sortType": sort,
                "limit": 30,
                "salesTypeFilter": SALES_TYPE_FOR_SALE,
            })

    # ---- Dedicated emote discovery ----
    for sort in SORT_TYPES:
        queries.append({
            "category": EMOTE_CATEGORY,
            "subcategory": EMOTE_SUBCATEGORY,
            "sortType": sort,
            "limit": 30,
            "salesTypeFilter": SALES_TYPE_FOR_SALE,
        })

    for kw in EMOTE_KEYWORDS[:60]:
        queries.append({
            "keyword": kw,
            "category": EMOTE_CATEGORY,
            "subcategory": EMOTE_SUBCATEGORY,
            "sortType": 2,
            "limit": 30,
            "salesTypeFilter": SALES_TYPE_FOR_SALE,
        })

    for min_p, max_p in PRICE_RANGES:
        queries.append({
            "category": EMOTE_CATEGORY,
            "subcategory": EMOTE_SUBCATEGORY,
            "minPrice": min_p,
            "maxPrice": max_p,
            "sortType": 2,
            "limit": 30,
            "salesTypeFilter": SALES_TYPE_FOR_SALE,
        })

    # ---- Alternative emote path: assetType=61 ----
    for sort in [0, 2, 3]:
        queries.append({
            "assetType": ASSET_TYPE_EMOTE,
            "sortType": sort,
            "limit": 30,
            "salesTypeFilter": SALES_TYPE_FOR_SALE,
        })

    # ---- General keyword sweeps ----
    all_keywords = list(set(UGC_KEYWORDS + CLASSIC_KEYWORDS + EMOTE_KEYWORDS))
    for kw in all_keywords:
        for sort in [0, 2]:
            queries.append({
                "keyword": kw,
                "sortType": sort,
                "limit": 30,
                "salesTypeFilter": SALES_TYPE_FOR_SALE,
            })

    # ---- Price-band sweeps ----
    for min_p, max_p in PRICE_RANGES:
        queries.append({
            "minPrice": min_p,
            "maxPrice": max_p,
            "sortType": 2,
            "limit": 30,
            "salesTypeFilter": SALES_TYPE_FOR_SALE,
        })

    # ---- Learned keywords ----
    for kw in get_dynamic_keywords():
        queries.append({
            "keyword": kw,
            "sortType": 2,
            "limit": 30,
            "salesTypeFilter": SALES_TYPE_FOR_SALE,
        })

    log(f"🔨 Built {len(queries)} queries.")
    return queries


def run_scanner():
    log("🚀 Scanner started.")
    setup_database()
    log("📦 DB setup done.")

    log(f"🔐 Loaded {len(SESSIONS)} cookie session(s) for scanning.")

    queries = build_all_queries()
    log(f"🚀 Running {len(queries)} queries with {WORKERS} workers "
        f"({WORKERS_PER_COOKIE} per cookie × {len(SESSIONS)} cookies)...")
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

            if done <= 10 or done % 20 == 0:
                elapsed = time.time() - start
                rate = done / elapsed if elapsed > 0 else 0
                log(f"  {done}/{len(queries)} — {len(all_ids)} IDs "
                    f"({rate:.1f} q/s)")

    log(f"✅ Scan collected {len(all_ids)} valid IDs in {time.time()-start:.1f}s")

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
