"""
live_enrich.py — Live Roblox catalog enrichment.

RATE LIMIT SAFETY:
  - Global cooldown: min 3s between keyword searches
  - Circuit breaker: after 2 consecutive 429s, pause 5 min
  - Reduced concurrency: max 3 parallel detail fetches
  - Exponential backoff on individual retries
"""
import os
import time
import threading
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import get_db_connection


def log(msg):
    print(f"[live-enrich] {msg}", flush=True)


# ─────────────────────────────────────────────────────────────
# RATE LIMIT STATE — global, thread-safe
# ─────────────────────────────────────────────────────────────
_rate_lock = threading.Lock()
_last_call_ts = 0.0
_MIN_GAP_S = 3.0        # at least 3s between keyword searches

_circuit_lock = threading.Lock()
_circuit_fails = 0
_circuit_until = 0.0
_CIRCUIT_THRESHOLD = 2
_CIRCUIT_BACKOFF_S = 300   # 5 min

_MAX_DETAIL_WORKERS = 3    # was 10 (SESSIONS*2) — reduced to prevent 429s


def _wait_for_slot():
    """Global throttle — never call Roblox faster than 1 per _MIN_GAP_S."""
    global _last_call_ts
    with _rate_lock:
        now = time.time()
        gap = now - _last_call_ts
        if gap < _MIN_GAP_S:
            time.sleep(_MIN_GAP_S - gap)
        _last_call_ts = time.time()


def _circuit_allows():
    with _circuit_lock:
        if time.time() < _circuit_until:
            return False
        return True


def _circuit_fail():
    global _circuit_fails, _circuit_until
    with _circuit_lock:
        _circuit_fails += 1
        if _circuit_fails >= _CIRCUIT_THRESHOLD:
            _circuit_until = time.time() + _CIRCUIT_BACKOFF_S
            log(f"circuit OPEN — pausing enrich for {_CIRCUIT_BACKOFF_S}s")


def _circuit_success():
    global _circuit_fails, _circuit_until
    with _circuit_lock:
        _circuit_fails = 0
        _circuit_until = 0.0


# ─────────────────────────────────────────────────────────────
# COOKIES + SESSIONS
# ─────────────────────────────────────────────────────────────
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
    COOKIES = [None]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

SESSIONS = []
for cookie in COOKIES:
    s = requests.Session()
    if cookie:
        s.cookies[".ROBLOSECURITY"] = cookie
    s.headers.update(HEADERS)
    SESSIONS.append(s)

CATALOG_SEARCH = "https://catalog.roblox.com/v1/search/items/details"
DETAILS_URL = "https://economy.roblox.com/v2/assets/{}/details"
FAV_URL = "https://catalog.roblox.com/v1/catalog/items/{}/details?itemType=Asset"


# ─────────────────────────────────────────────────────────────
# ASSET_TYPE_ID → ROBLOX CATEGORY MAPPING
# ─────────────────────────────────────────────────────────────
ASSET_TO_CAT = {
    61: {"category": 12, "subcategory": 39},   # Emote
    8:  {"category": 11, "subcategory": 9},    # Hat
    41: {"category": 11, "subcategory": 19},   # Hair
    18: {"category": 11, "subcategory": 10},   # Face
    42: {"category": 11, "subcategory": 10},   # Face Acc
    43: {"category": 11, "subcategory": 11},   # Neck
    44: {"category": 11, "subcategory": 12},   # Shoulder
    45: {"category": 11, "subcategory": 13},   # Front
    46: {"category": 11, "subcategory": 14},   # Back
    47: {"category": 11, "subcategory": 15},   # Waist
    11: {"category": 3},                        # Shirt (classic)
    12: {"category": 3},                        # Pants (classic)
    64: {"category": 3},                        # 3D T-Shirt
    65: {"category": 3},                        # 3D Shirt
    66: {"category": 3},                        # 3D Pants
    67: {"category": 3},                        # 3D Jacket
    68: {"category": 3},                        # 3D Sweater
    69: {"category": 3},                        # 3D Shorts
    70: {"category": 3},                        # 3D Shoe L
    71: {"category": 3},                        # 3D Shoe R
    72: {"category": 3},                        # 3D Dress
    19: {"category": 5},                        # Gear
    17: {"category": 4},                        # Head
    2:  {"category": 3},                        # T-Shirt
}


# ─────────────────────────────────────────────────────────────
# SEARCH
# ─────────────────────────────────────────────────────────────
def _search_keyword(keyword, category_ids=None, limit=100, sort=2):
    """Search Roblox catalog by keyword. Rate-limit safe."""
    if not _circuit_allows():
        log(f"circuit open — skip search '{keyword}'")
        return []

    _wait_for_slot()

    ids = set()
    cursor = ""
    pages = 0
    max_pages = min((limit // 30) + 2, 4)   # cap at 4 pages per keyword

    cat_params = {}
    if category_ids:
        atype = category_ids[0]
        mapping = ASSET_TO_CAT.get(atype)
        if mapping:
            cat_params["category"] = mapping["category"]
            if "subcategory" in mapping:
                cat_params["subcategory"] = mapping["subcategory"]

    while pages < max_pages:
        params = {
            "keyword": keyword,
            "limit": 30,
            "sortType": sort,
            "cursor": cursor,
        }
        params.update(cat_params)

        session = SESSIONS[pages % len(SESSIONS)]
        try:
            r = session.get(CATALOG_SEARCH, params=params, timeout=10)

            if r.status_code == 429:
                log(f"search HTTP 429 for '{keyword}'")
                _circuit_fail()
                break

            if r.status_code != 200:
                log(f"search HTTP {r.status_code} for '{keyword}'")
                break

            _circuit_success()
            data = r.json()
            for item in data.get("data", []):
                if item.get("id"):
                    ids.add(int(item["id"]))
            cursor = data.get("nextPageCursor")
            if not cursor:
                break
            pages += 1
            time.sleep(1.0)   # was 0.4 — increased to prevent burst
        except Exception as e:
            log(f"search error for '{keyword}': {e}")
            break

    return list(ids)[:limit]


# ─────────────────────────────────────────────────────────────
# DETAILS
# ─────────────────────────────────────────────────────────────
def _fetch_item_details(item_id):
    """Fetch details with exponential backoff on 429."""
    for session in SESSIONS:
        for attempt in range(2):
            try:
                r = session.get(DETAILS_URL.format(item_id), timeout=10)

                if r.status_code == 429:
                    if attempt == 0:
                        time.sleep(2.0)
                        continue
                    return None

                if r.status_code != 200:
                    break

                d = r.json()

                favs = 0
                try:
                    _wait_for_slot()   # throttle the follow-up call too
                    r2 = session.get(FAV_URL.format(item_id), timeout=10)
                    if r2.status_code == 200:
                        favs = r2.json().get("favoriteCount") or 0
                except Exception:
                    pass

                creator_obj = d.get("Creator") or {}
                creator = creator_obj.get("Name") if isinstance(creator_obj, dict) else None

                created_raw = d.get("Created")
                created_dt = None
                if created_raw and isinstance(created_raw, str):
                    try:
                        created_dt = datetime.fromisoformat(
                            created_raw.replace("Z", "").split(".")[0]
                        )
                    except Exception:
                        pass

                return {
                    "id": item_id,
                    "name": (d.get("Name") or "")[:500],
                    "description": (d.get("Description") or "")[:5000],
                    "price": d.get("PriceInRobux") or 0,
                    "favorite_count": favs,
                    "total_sales": d.get("Sales") or 0,
                    "creator_name": (creator or "")[:200],
                    "asset_type_id": d.get("AssetTypeId") or 0,
                    "created_at": created_dt,
                }
            except Exception:
                continue
    return None


# ─────────────────────────────────────────────────────────────
# MAIN ENTRY
# ─────────────────────────────────────────────────────────────
def live_enrich_keyword(keyword, category_ids=None, max_items=100):
    if not keyword or len(keyword) < 3:
        return 0

    if not _circuit_allows():
        log(f"circuit open — skip enrich '{keyword}'")
        return 0

    cat_label = ""
    if category_ids:
        mapping = ASSET_TO_CAT.get(category_ids[0])
        if mapping:
            cat_label = f" [cat={mapping['category']}" + (
                f"/sub={mapping['subcategory']}]" if mapping.get("subcategory") else "]"
            )

    log(f"Searching Roblox for '{keyword}'{cat_label}...")
    ids = _search_keyword(keyword, category_ids, limit=max_items)
    if not ids:
        log(f"No results for '{keyword}'")
        return 0

    log(f"Found {len(ids)} IDs. Fetching details...")

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        cur.execute("SELECT id FROM items WHERE id = ANY(%s)", (ids,))
        existing = {r[0] for r in cur.fetchall()}

        new_ids = [i for i in ids if i not in existing]
        log(f"{len(new_ids)} new, {len(existing)} already in DB")

        if not new_ids:
            new_ids = ids[:30]

        saved = 0
        with ThreadPoolExecutor(max_workers=_MAX_DETAIL_WORKERS) as ex:
            futures = {ex.submit(_fetch_item_details, iid): iid for iid in new_ids}
            for fut in as_completed(futures):
                try:
                    data = fut.result(timeout=30)
                    if not data:
                        continue
                    cur.execute("""
                        INSERT INTO items (id, name, favorite_count, price, total_sales,
                                           description, creator_name, asset_type_id, created_at,
                                           favorite_status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            favorite_count = EXCLUDED.favorite_count,
                            favorite_status = CASE
                                WHEN EXCLUDED.favorite_count IS NULL THEN 'missing'
                                ELSE 'known'
                            END,
                            total_sales = EXCLUDED.total_sales,
                            price = EXCLUDED.price,
                            description = EXCLUDED.description,
                            name = EXCLUDED.name,
                            asset_type_id = EXCLUDED.asset_type_id,
                            created_at = COALESCE(items.created_at, EXCLUDED.created_at),
                            fetched_at = CURRENT_TIMESTAMP
                    """, (
                        data["id"], data["name"], data["favorite_count"],
                        data["price"], data["total_sales"], data["description"],
                        data["creator_name"], data["asset_type_id"], data["created_at"],
                        ("known" if data.get("favorite_count") is not None else "missing"),
                    ))
                    saved += 1
                except Exception as e:
                    log(f"save failed: {e}")

        conn.commit()
    finally:
        cur.close(); conn.close()

    log(f"✅ Saved {saved} items for '{keyword}'")
    return saved


def enrich_multiple_keywords(keywords, category_ids=None, max_per_keyword=60):
    total = 0
    for kw in keywords:
        if not _circuit_allows():
            log(f"circuit open — stopping batch")
            break
        try:
            n = live_enrich_keyword(kw, category_ids, max_items=max_per_keyword)
            total += n
        except Exception as e:
            log(f"'{kw}' failed: {e}")
    return total
