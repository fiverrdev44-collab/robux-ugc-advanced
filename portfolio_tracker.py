"""portfolio_tracker.py — Track YOUR OWN Roblox UGC items (clothing excluded)."""
import os
import requests
from monitoring_config import is_excluded, EXCLUDED_ASSET_IDS

ROBLOX_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _ensure_table(cur):
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS my_portfolio (
                item_id BIGINT PRIMARY KEY,
                name TEXT,
                asset_type_id BIGINT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_refresh TIMESTAMP,
                notes TEXT
            )
        """)
        cur.connection.commit()
    except Exception as e:
        print(f"[portfolio] table init: {e}", flush=True)


def _fetch_catalog_page(creator_id, creator_type, cookie, cursor=""):
    headers = {"User-Agent": ROBLOX_UA, "Accept": "application/json"}
    if cookie:
        headers["Cookie"] = f".ROBLOSECURITY={cookie}"

    url = (
        "https://catalog.roblox.com/v1/search/items/details"
        f"?Category=All&CreatorTargetId={creator_id}&CreatorType={creator_type}"
        f"&Limit=30&SortType=3"
    )
    if cursor:
        url += f"&Cursor={cursor}"

    try:
        r = requests.get(url, headers=headers, timeout=12)
        if r.status_code != 200:
            print(f"[portfolio] HTTP {r.status_code} for {creator_type} {creator_id}", flush=True)
            return None
        return r.json()
    except Exception as e:
        print(f"[portfolio] fetch {creator_type} {creator_id}: {e}", flush=True)
        return None


def _fetch_items_for_creator(creator_id, creator_type, cookie, limit=200):
    out, cursor, skipped = [], "", 0
    for _ in range(10):
        data = _fetch_catalog_page(creator_id, creator_type, cookie, cursor)
        if not data:
            break
        for it in data.get("data") or []:
            atype = it.get("assetType") or it.get("assetTypeId") or 0
            if is_excluded(atype):
                skipped += 1
                continue
            out.append({
                "id": it.get("id"),
                "name": (it.get("name") or "")[:200],
                "asset_type_id": atype,
            })
        cursor = data.get("nextPageCursor")
        if not cursor or len(out) >= limit:
            break

    if skipped:
        print(f"[portfolio] {creator_type} {creator_id}: skipped {skipped} clothing items", flush=True)
    return out


def _fetch_my_items_from_roblox(user_id, cookie=None, limit=200):
    all_items = []
    seen_ids = set()

    if user_id:
        items = _fetch_items_for_creator(user_id, "User", cookie, limit)
        for it in items:
            if it["id"] not in seen_ids:
                seen_ids.add(it["id"])
                all_items.append(it)

    group_ids_raw = os.getenv("ROBLOX_GROUP_IDS", "")
    group_ids = [g.strip() for g in group_ids_raw.split(",") if g.strip().isdigit()]

    for gid in group_ids:
        items = _fetch_items_for_creator(gid, "Group", cookie, limit)
        for it in items:
            if it["id"] not in seen_ids:
                seen_ids.add(it["id"])
                all_items.append(it)

    print(
        f"[portfolio] fetched {len(all_items)} items "
        f"({len(group_ids)} groups + {'user' if user_id else 'no user'})",
        flush=True,
    )
    return all_items


def _enrich_item_into_catalog(cur, item_id, cookie):
    """Fetch full details + created_at from Roblox and upsert into items table."""
    headers = {"User-Agent": ROBLOX_UA, "Accept": "application/json"}
    if cookie:
        headers["Cookie"] = f".ROBLOSECURITY={cookie}"

    details = None
    try:
        r = requests.get(
            f"https://economy.roblox.com/v2/assets/{item_id}/details",
            headers=headers, timeout=10,
        )
        if r.status_code == 200:
            details = r.json()
    except Exception:
        pass

    if not details:
        return False

    favs = 0
    try:
        r = requests.get(
            f"https://catalog.roblox.com/v1/favorites/assets/{item_id}/count",
            headers=headers, timeout=10,
        )
        if r.status_code == 200:
            favs = r.json() or 0
    except Exception:
        pass

    # Fetch created_at
    created_at = None
    try:
        r = requests.get(
            f"https://www.roblox.com/marketplace/productinfo?assetId={item_id}",
            headers=headers, timeout=10,
        )
        if r.status_code == 200:
            created_at = r.json().get("Created")
    except Exception:
        pass

    creator_obj = details.get("Creator") or {}
    creator_name = creator_obj.get("Name") if isinstance(creator_obj, dict) else None

    try:
        if created_at:
            cur.execute("""
                INSERT INTO items (id, name, favorite_count, price, total_sales,
                                   description, creator_name, asset_type_id,
                                   created_at, fetched_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    favorite_count = EXCLUDED.favorite_count,
                    price = EXCLUDED.price,
                    description = COALESCE(NULLIF(EXCLUDED.description, ''), items.description),
                    name = EXCLUDED.name,
                    creator_name = COALESCE(NULLIF(EXCLUDED.creator_name, ''), items.creator_name),
                    asset_type_id = EXCLUDED.asset_type_id,
                    created_at = COALESCE(items.created_at, EXCLUDED.created_at),
                    fetched_at = NOW()
            """, (
                item_id,
                (details.get("Name") or "")[:500],
                favs,
                details.get("PriceInRobux") or 0,
                details.get("Sales") or 0,
                (details.get("Description") or "")[:5000],
                (creator_name or "")[:200],
                details.get("AssetTypeId") or 0,
                created_at,
            ))
        else:
            cur.execute("""
                INSERT INTO items (id, name, favorite_count, price, total_sales,
                                   description, creator_name, asset_type_id, fetched_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    favorite_count = EXCLUDED.favorite_count,
                    price = EXCLUDED.price,
                    description = COALESCE(NULLIF(EXCLUDED.description, ''), items.description),
                    name = EXCLUDED.name,
                    creator_name = COALESCE(NULLIF(EXCLUDED.creator_name, ''), items.creator_name),
                    asset_type_id = EXCLUDED.asset_type_id,
                    fetched_at = NOW()
            """, (
                item_id,
                (details.get("Name") or "")[:500],
                favs,
                details.get("PriceInRobux") or 0,
                details.get("Sales") or 0,
                (details.get("Description") or "")[:5000],
                (creator_name or "")[:200],
                details.get("AssetTypeId") or 0,
            ))
        return True
    except Exception as e:
        print(f"[portfolio] enrich {item_id}: {e}", flush=True)
        return False


def refresh_portfolio(cur, cookie, user_id):
    _ensure_table(cur)
    items = _fetch_my_items_from_roblox(user_id, cookie)
    if not items:
        return []

    enriched = 0
    for it in items:
        try:
            cur.execute("""
                INSERT INTO my_portfolio (item_id, name, asset_type_id, last_refresh)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (item_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    asset_type_id = EXCLUDED.asset_type_id,
                    last_refresh = NOW()
            """, (it["id"], it["name"], it["asset_type_id"]))
            if _enrich_item_into_catalog(cur, it["id"], cookie):
                enriched += 1
        except Exception as e:
            print(f"[portfolio] upsert {it['id']}: {e}", flush=True)

    try:
        cur.connection.commit()
    except Exception:
        pass

    print(f"[portfolio] enriched {enriched}/{len(items)} items into catalog", flush=True)
    return items


def purge_excluded(cur):
    try:
        cur.execute(
            "DELETE FROM my_portfolio WHERE asset_type_id = ANY(%s)",
            (list(EXCLUDED_ASSET_IDS),)
        )
        n = cur.rowcount
        cur.connection.commit()
        return n
    except Exception as e:
        print(f"[portfolio] purge: {e}", flush=True)
        return 0


def get_portfolio(cur):
    _ensure_table(cur)
    try:
        cur.execute("""
            SELECT item_id, name, asset_type_id, first_seen, last_refresh
            FROM my_portfolio ORDER BY first_seen DESC
        """)
        return [
            {"id": r[0], "name": r[1], "asset_type_id": r[2],
             "first_seen": r[3], "last_refresh": r[4]}
            for r in cur.fetchall()
        ]
    except Exception as e:
        print(f"[portfolio] get_portfolio: {e}", flush=True)
        return []
