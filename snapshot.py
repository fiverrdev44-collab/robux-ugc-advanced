"""
snapshot.py — Daily snapshot of top items' favourite counts.
Runs on GitHub Actions every 24h.
Inserts one row per item per day into item_history.
"""

import os
import time
from datetime import datetime, timezone
from database import get_db_connection


def log(msg):
    print(msg, flush=True)


# How many top items to snapshot per day
TOP_ITEMS_LIMIT = 5000

# Minimum favs required to be tracked (skip junk)
MIN_FAVS = 50

# Delay between DB inserts (not needed for API, only DB)
BATCH_SIZE = 500


def snapshot_top_items():
    log("📸 Snapshot job started.")
    start = time.time()

    conn = get_db_connection()
    cur = conn.cursor()

    # Get top items by favourite count, but only ones we haven't snapshotted today
    log(f"🔎 Finding top {TOP_ITEMS_LIMIT} items to snapshot...")
    cur.execute("""
        SELECT i.id, i.favorite_count, i.total_sales, i.price
        FROM items i
        WHERE i.favorite_count >= %s
          AND NOT EXISTS (
              SELECT 1 FROM item_history h
              WHERE h.item_id = i.id
                AND h.snapshot_at >= CURRENT_DATE
          )
        ORDER BY i.favorite_count DESC
        LIMIT %s
    """, (MIN_FAVS, TOP_ITEMS_LIMIT))

    rows = cur.fetchall()
    log(f"📊 Found {len(rows)} items without today's snapshot.")

    if not rows:
        log("✅ Nothing to snapshot — all items already have today's snapshot.")
        cur.close()
        conn.close()
        return

    # Insert snapshots in batches
    inserted = 0
    batch = []
    for iid, favs, sales, price in rows:
        batch.append((iid, favs or 0, sales or 0, price or 0))
        if len(batch) >= BATCH_SIZE:
            cur.executemany("""
                INSERT INTO item_history (item_id, favorite_count, total_sales, price)
                VALUES (%s, %s, %s, %s)
            """, batch)
            conn.commit()
            inserted += len(batch)
            log(f"  💾 Inserted {inserted}/{len(rows)}...")
            batch = []

    # Final batch
    if batch:
        cur.executemany("""
            INSERT INTO item_history (item_id, favorite_count, total_sales, price)
            VALUES (%s, %s, %s, %s)
        """, batch)
        conn.commit()
        inserted += len(batch)

    cur.close()
    conn.close()

    elapsed = time.time() - start
    log(f"✅ Snapshot complete: {inserted} rows in {elapsed:.1f}s")
    log(f"   Items snapshotted: {len(rows)}")


if __name__ == "__main__":
    try:
        snapshot_top_items()
    except Exception as e:
        log(f"❌ FATAL: {e}")
        import traceback
        traceback.print_exc()
        raise
