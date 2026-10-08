"""portfolio_tracker.py — Track YOUR OWN Roblox UGC items (clothing excluded)."""
import os
import requests
from monitoring_config import is_excluded

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


def _fetch_my_items_from_roblox(user_id, cookie=None, limit=100):
    if not user_id:
        return []
    headers = {"User-Agent": ROBLOX_UA, "Accept": "application/json"}
    if cookie:
        headers["Cookie"] = f".ROBLOSECURITY={cookie}"

    out, cursor, skipped = [], "", 0
    for _ in range(10):
        url = (
            "https://catalog.roblox.com/v1/search/items/details"
            f"?Category=All&CreatorTargetId={user_id}&CreatorType=User"
            f"&Limit=30&SortType=3"
        )
        if cursor:
            url += f"&Cursor={cursor}"
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code != 200:
                print(f"[portfolio] HTTP {r.status_code}", flush=True)
                break
            data = r.json()
        except Exception as e:
            print(f"[portfolio] fetch: {e}", flush=True)
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
        print(f"[portfolio] skipped {skipped} clothing items", flush=True)
    return out


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


from monitoring_config import EXCLUDED_ASSET_IDS  # for purge
