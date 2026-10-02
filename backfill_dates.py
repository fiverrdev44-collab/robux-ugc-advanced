"""
backfill_dates.py — Fill in missing created_at dates from Roblox productinfo API.
Run once. Takes ~3-7 hours for 24k items.
"""
import os
import time
import requests
from datetime import datetime
from database import get_db_connection


def log(msg):
    print(msg, flush=True)


def fetch_created_date(asset_id, session):
    """
    Get the creation date for a single asset via the productinfo endpoint.
    Returns a datetime or None.
    """
    url = f"https://www.roblox.com/marketplace/productinfo?assetId={asset_id}"
    try:
        r = session.get(url, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        created_str = data.get("Created")
        if not created_str:
            return None
        # Roblox returns ISO 8601 like "2015-03-14T18:23:11.407Z"
        # Strip the Z and milliseconds for psycopg2
        created_str = created_str.replace("Z", "").split(".")[0]
        return datetime.fromisoformat(created_str)
    except Exception:
        return None


def backfill(batch_size=500):
    conn = get_db_connection()
    cur = conn.cursor()

    # Get items missing created_at
    cur.execute("""
        SELECT id FROM items
        WHERE created_at IS NULL
        ORDER BY favorite_count DESC
        LIMIT %s
    """, (batch_size,))
    ids = [r[0] for r in cur.fetchall()]

    log(f"📅 Backfilling {len(ids)} items (sorted by popularity — real items first)")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    })

    filled = 0
    failed = 0
    start = time.time()

    for i, asset_id in enumerate(ids, 1):
        created = fetch_created_date(asset_id, session)
        if created:
            try:
                cur.execute(
                    "UPDATE items SET created_at = %s WHERE id = %s",
                    (created, asset_id)
                )
                conn.commit()
                filled += 1
            except Exception as e:
                log(f"  DB error for {asset_id}: {e}")
                conn.rollback()
                failed += 1
        else:
            failed += 1

        if i % 50 == 0:
            elapsed = time.time() - start
            rate = i / elapsed if elapsed > 0 else 0
            log(f"  [{i}/{len(ids)}] filled={filled} failed={failed} ({rate:.1f}/s)")

        time.sleep(0.3)  # ~3 req/sec — respectful

    cur.close()
    conn.close()
    log(f"✅ Done: {filled} filled, {failed} failed in {time.time()-start:.1f}s")


if __name__ == "__main__":
    backfill()
