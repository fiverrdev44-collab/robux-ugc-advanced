"""portfolio_tracker.py — Track YOUR OWN Roblox UGC items (clothing excluded).

Fetches from:
  - Personal account (ROBLOX_USER_ID)
  - All groups listed in ROBLOX_GROUP_IDS (comma-separated)
"""
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
    """Fetch one page of items for a given creator (User or Group)."""
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
    """Fetch all items for a single creator (user OR group), skipping clothing."""
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
    """
    Fetch items from personal account AND all configured groups.
    Groups read from ROBLOX_GROUP_IDS env var (comma-separated).
    """
    all_items = []
    seen_ids = set()

    # ── Personal account ──
    if user_id:
        items = _fetch_items_for_creator(user_id, "User", cookie, limit)
        for it in items:
            if it["id"] not in seen_ids:
                seen_ids.add(it["id"])
                all_items.append(it)

    # ── Groups ──
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


def refresh_portfolio(cur, cookie, user_id):
    _ensure_table(cur)
    items = _fetch_my_items_from_roblox(user_id, cookie)
    if not items:
        return []
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
        except Exception as e:
            print(f"[portfolio] upsert {it['id']}: {e}", flush=True)
    try:
        cur.connection.commit()
    except Exception:
        pass
    return items


def purge_excluded(cur):
    """Delete any previously-synced clothing rows."""
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
