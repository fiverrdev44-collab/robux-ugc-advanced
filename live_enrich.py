"""
live_enrich.py — Live Roblox catalog enrichment.
Fetches real items from Roblox API by keyword, saves to DB.
"""
import os
import time
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import get_db_connection


def log(msg):
    print(f"[live-enrich] {msg}", flush=True)


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
# ASSET_TYPE_ID → ROBLOX CATEGORY MAPPING (critical fix)
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


def _search_keyword(keyword, category_ids=None, limit=100, sort=2):
    """
    Search Roblox catalog by keyword.
    category_ids = [asset_type_id, ...] from CATEGORY_MAP.
    """
    ids = set()
    cursor = ""
    pages = 0
    max_pages = (limit // 30) + 2

    # Resolve the category/subcategory from asset_type_id
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
            if r.status_code != 200:
                log(f"search HTTP {r.status_code}")
                break
            data = r.json()
            for item in data.get("data", []):
                if item.get("id"):
                    ids.add(int(item["id"]))
            cursor = data.get("nextPageCursor")
            if not cursor:
                break
            pages += 1
            time.sleep(0.4)
        except Exception as e:
            log(f"search error: {e}")
            break

    return list(ids)[:limit]


def _fetch_item_details(item_id):
    for session in SESSIONS:
        try:
            r = session.get(DETAILS_URL.format(item_id), timeout=10)
            if r.status_code != 200:
                continue
            d = r.json()

            favs = 0
            try:
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


def live_enrich_keyword(keyword, category_ids=None, max_items=100):
    if not keyword or len(keyword) < 3:
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

    cur.execute("SELECT id FROM items WHERE id = ANY(%s)", (ids,))
    existing = {r[0] for r in cur.fetchall()}

    new_ids = [i for i in ids if i not in existing]
    log(f"{len(new_ids)} new, {len(existing)} already in DB")

    if not new_ids:
        new_ids = ids[:30]

    saved = 0
    with ThreadPoolExecutor(max_workers=len(SESSIONS) * 2) as ex:
        futures = {ex.submit(_fetch_item_details, iid): iid for iid in new_ids}
        for fut in as_completed(futures):
            try:
                data = fut.result(timeout=30)
                if not data:
                    continue
                cur.execute("""
                    INSERT INTO items (id, name, favorite_count, price, total_sales,
                                       description, creator_name, asset_type_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        favorite_count = EXCLUDED.favorite_count,
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
                ))
                saved += 1
            except Exception as e:
                log(f"save failed: {e}")

    conn.commit()
    cur.close(); conn.close()
    log(f"✅ Saved {saved} items for '{keyword}'")
    return saved


def enrich_multiple_keywords(keywords, category_ids=None, max_per_keyword=60):
    total = 0
    for kw in keywords:
        try:
            n = live_enrich_keyword(kw, category_ids, max_items=max_per_keyword)
            total += n
        except Exception as e:
            log(f"'{kw}' failed: {e}")
    return total
