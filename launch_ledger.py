"""launch_ledger.py — shared helpers for the launch ledger.

Used by both the Discord commands and the in-bot scheduler so that group
items are auto-logged and outcomes are auto-synced.
"""
import os
from datetime import timedelta


def detect_family(asset_type_id):
    try:
        from category_configs import detect_family_from_asset_type
        return detect_family_from_asset_type(asset_type_id) or "unknown"
    except Exception:
        return "unknown"


def sync_group_items(cur, group_names):
    """Insert every item owned by the given creators into launch_ledger."""
    names = [n.strip().lower() for n in group_names if n and n.strip()]
    if not names:
        return 0, 0

    cur.execute("""
        SELECT id, name, favorite_count, price, asset_type_id,
               created_at, fetched_at
        FROM items
        WHERE lower(creator_name) = ANY(%s)
    """, (names,))
    rows = cur.fetchall()

    added = 0
    for (iid, name, favs, price, atype, created, fetched) in rows:
        launched = created or fetched
        family = detect_family(atype)
        cur.execute("""
            INSERT INTO launch_ledger
              (item_id, launched_at, family, title, asset_type_id,
               price, favs_launch)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (item_id) DO NOTHING
        """, (iid, launched, family, name, atype, price or 0, favs))
        added += cur.rowcount

    return len(rows), added


def fill_ledger(cur, item_id):
    """Fill one ledger row with D1/D7/D30 favorites and D7/D30 sales."""
    cur.execute("""
        SELECT item_id, launched_at, title, family
        FROM launch_ledger WHERE item_id = %s
    """, (item_id,))
    row = cur.fetchone()
    if not row:
        return False
    iid, launched, title, family = row

    cur.execute("""
        SELECT favorite_count FROM item_history
        WHERE item_id = %s
          AND snapshot_at <= %s
          AND snapshot_at >= %s
        ORDER BY snapshot_at DESC LIMIT 1
    """, (iid, launched, launched - timedelta(days=7)))
    r = cur.fetchone()
    favs_launch = r[0] if r else None

    def fav_at(days):
        target = launched + timedelta(days=days)
        cur.execute("""
            SELECT favorite_count FROM item_history
            WHERE item_id = %s
              AND snapshot_at >= %s
              AND snapshot_at < %s
            ORDER BY abs(extract(epoch from (snapshot_at - %s))) ASC
            LIMIT 1
        """, (iid, target - timedelta(hours=18),
              target + timedelta(hours=36), target))
        r2 = cur.fetchone()
        return r2[0] if r2 else None

    favs_d1 = fav_at(1)
    favs_d7 = fav_at(7)
    favs_d30 = fav_at(30)

    prefix = (title or "").lower()
    import re as _re
    prefix = _re.sub(r"[^a-z0-9 ]", "", prefix)
    prefix = _re.sub(r"\s+", " ", prefix).strip()[:24]
    like = f"%{prefix}%" if prefix else "%"

    def sales_window(days):
        cur.execute("""
            SELECT count(*), COALESCE(SUM(amount_robux), 0)
            FROM my_sales
            WHERE regexp_replace(lower(item_name), '[^a-z0-9]+', ' ', 'g') LIKE %s
              AND sale_time >= %s
              AND sale_time < %s
        """, (like, launched, launched + timedelta(days=days)))
        return cur.fetchone()

    units_d7, revenue_d7 = sales_window(7)
    units_d30, revenue_d30 = sales_window(30)

    # Last 30 days regardless of launch date — useful for legacy items
    # whose launch window predates the sales/snapshot coverage.
    cur.execute("""
        SELECT count(*), COALESCE(SUM(amount_robux), 0)
        FROM my_sales
        WHERE regexp_replace(lower(item_name), '[^a-z0-9]+', ' ', 'g') LIKE %s
          AND sale_time >= NOW() - interval '30 days'
    """, (like,))
    recent_units, recent_revenue = cur.fetchone()

    cur.execute("""
        UPDATE launch_ledger SET
            favs_launch = %s,
            favs_d1 = %s, favs_d7 = %s, favs_d30 = %s,
            units_d7 = %s, units_d30 = %s,
            revenue_d7 = %s, revenue_d30 = %s,
            recent_units_30d = %s, recent_revenue_30d = %s,
            last_synced = CURRENT_TIMESTAMP
        WHERE item_id = %s
    """, (
        favs_launch, favs_d1, favs_d7, favs_d30,
        units_d7 or 0, units_d30 or 0,
        revenue_d7 or 0, revenue_d30 or 0,
        recent_units or 0, recent_revenue or 0,
        iid,
    ))
    return True


def sync_all(cur):
    """Fill every ledger row. Returns the number synced."""
    cur.execute("SELECT item_id FROM launch_ledger")
    ids = [r[0] for r in cur.fetchall()]
    synced = 0
    for iid in ids:
        try:
            if fill_ledger(cur, iid):
                synced += 1
        except Exception:
            pass
    return synced


def configured_groups():
    raw = os.getenv("MY_GROUP_NAMES", "")
    return [g.strip() for g in raw.split(",") if g.strip()]
