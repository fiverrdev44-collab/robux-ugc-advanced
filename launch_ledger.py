"""launch_ledger.py — shared helpers for the launch ledger.

Used by both the Discord commands and the in-bot scheduler so that group
items are auto-logged and outcomes are auto-synced.
"""
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import psycopg2


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
        features = {
            "title": name,
            "price": price or 0,
            "family": family,
            "asset_type_id": atype,
            "title_words": len(re.findall(r"[a-z0-9]+", (name or "").lower())),
            "launch_hour": launched.hour if launched else None,
            "launch_dow": launched.weekday() if launched else None,
        }
        try:
            from opportunity_score import score_opportunity
            opp = score_opportunity(cur, name, family)
            if opp:
                features.update({
                    "demand_live": opp.get("demand_live", 0),
                    "demand_volume": opp.get("demand_volume", 0),
                    "supply": opp.get("supply", 0),
                    "strong": opp.get("strong", 0),
                    "exact": opp.get("exact", 0),
                    "ctr_proxy": opp.get("ctr_proxy"),
                    "verdict": opp.get("verdict"),
                })
        except Exception as e:
            print(f"[launch_ledger] feature snapshot failed: {e}", flush=True)
        cur.execute("""
            INSERT INTO launch_ledger
              (item_id, launched_at, tracking_started_at, family, title, asset_type_id,
               price, favs_launch, features)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (item_id) DO NOTHING
        """, (iid, launched, launched, family, name, atype, price or 0, favs,
              json.dumps(features, default=str)))
        added += cur.rowcount

        # Published date is a property of the asset, not of when we started
        # tracking it. Use the catalog creation date when available so age,
        # D1/D7/D30 windows and "mature" checks are not reset by renames.
        cur.execute("""
            UPDATE launch_ledger l
            SET published_at = COALESCE(l.published_at, i.created_at)
            FROM items i
            WHERE i.id = l.item_id AND l.item_id = %s
        """, (iid,))

    return len(rows), added


def fill_ledger(cur, item_id):
    """Fill one ledger row with D1/D7/D30 favorites and D7/D30 sales.

    The row lock is taken up front (FOR UPDATE) and deadlocks are retried after
    a rollback so a failed fill can never poison the caller's transaction.
    """
    last_error = None
    for attempt in range(3):
        try:
            return _fill_ledger_once(cur, item_id)
        except psycopg2.errors.DeadlockDetected as e:
            last_error = e
            try:
                cur.connection.rollback()
            except Exception:
                pass
            print(f"[launch_ledger] deadlock on {item_id}, retry {attempt + 1}",
                  flush=True)
            time.sleep(1.0)
        except psycopg2.Error:
            # Any other DB error: never leave an aborted transaction behind.
            try:
                cur.connection.rollback()
            except Exception:
                pass
            raise
    print(f"[launch_ledger] gave up after 3 deadlocks on {item_id}: "
          f"{type(last_error).__name__}", flush=True)
    return False


def _fill_ledger_once(cur, item_id):
    cur.execute("""
        SELECT item_id, COALESCE(published_at, launched_at), title, family
        FROM launch_ledger WHERE item_id = %s
        FOR UPDATE
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

    def _norm(s):
        return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

    cur.execute("SELECT name FROM items WHERE id = %s", (iid,))
    row_name = cur.fetchone()
    current_name = row_name[0] if row_name else None
    sale_names = sorted({_norm(title), _norm(current_name)} - {""})

    def sales_window(days):
        if not sale_names:
            return 0, 0
        cur.execute("""
            SELECT count(*), COALESCE(SUM(amount_robux), 0)
            FROM my_sales
            WHERE regexp_replace(lower(item_name), '[^a-z0-9]+', ' ', 'g')
                  = ANY(%s)
              AND sale_time >= %s
              AND sale_time < %s
        """, (sale_names, launched, launched + timedelta(days=days)))
        return cur.fetchone()

    units_d7, revenue_d7 = sales_window(7)
    units_d30, revenue_d30 = sales_window(30)

    # Last 30 days regardless of launch date — useful for legacy items
    # whose launch window predates the sales/snapshot coverage.
    if sale_names:
        cur.execute("""
            SELECT count(*), COALESCE(SUM(amount_robux), 0)
            FROM my_sales
            WHERE regexp_replace(lower(item_name), '[^a-z0-9]+', ' ', 'g')
                  = ANY(%s)
              AND sale_time >= NOW() - interval '30 days'
        """, (sale_names,))
    else:
        cur.execute("SELECT 0, 0")
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

    launched_cmp = launched
    if launched_cmp is not None and launched_cmp.tzinfo is None:
        launched_cmp = launched_cmp.replace(tzinfo=timezone.utc)
    if (favs_d30 is not None and units_d30 is not None
            and launched_cmp is not None
            and launched_cmp <= datetime.now(timezone.utc) - timedelta(days=30)):
        try:
            from convergence_engine import resolve_family_ids
            ids = resolve_family_ids(family)
            if ids:
                ph = ",".join(["%s"] * len(ids))
                cur.execute(f"""
                    SELECT percentile_cont(0.5) WITHIN GROUP
                             (ORDER BY favorite_count),
                           percentile_cont(0.9) WITHIN GROUP
                             (ORDER BY favorite_count)
                    FROM items WHERE favorite_count > 5
                      AND asset_type_id IN ({ph})
                """, list(ids))
            else:
                cur.execute("""
                    SELECT percentile_cont(0.5) WITHIN GROUP
                             (ORDER BY favorite_count),
                           percentile_cont(0.9) WITHIN GROUP
                             (ORDER BY favorite_count)
                    FROM items WHERE favorite_count > 5
                """)
            med, p90 = cur.fetchone()
            med = float(med or 0)
            p90 = float(p90 or 0)
            fee = int(os.getenv("UGC_UPLOAD_FEE_ROBUX", "750"))
            cur.execute("""
                UPDATE launch_ledger SET
                    label_beat_median = %s,
                    label_top_decile = %s,
                    label_recouped = %s,
                    labeled_at = now()
                WHERE item_id = %s
            """, (
                favs_d30 >= med,
                favs_d30 >= p90,
                int(revenue_d30 or 0) >= fee,
                iid,
            ))
        except Exception as e:
            print(f"[launch_ledger] label failed: {e}", flush=True)
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
