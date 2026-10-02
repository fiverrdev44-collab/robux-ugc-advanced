"""
backfill_dates.py — Fill missing created_at dates using the economy details endpoint.
Run from GitHub Actions. Processes in batches.
"""
import os
import time
import requests
from datetime import datetime
from database import get_db_connection


def log(msg):
    print(msg, flush=True)


DETAILS_URL = "https://economy.roblox.com/v2/assets/{}/details"


def fetch_created_date(asset_id, session):
    """Get the creation date via the economy details endpoint (returns Created field)."""
    try:
        r = session.get(DETAILS_URL.format(asset_id), timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        created_str = data.get("Created")
        if not created_str:
            return None
        # Strip milliseconds + Z for psycopg2
        created_str = created_raw = str(created_str)
        created_str = created_str.replace("Z", "").split(".")[0]
        return datetime.fromisoformat(created_str)
    except Exception:
        return None


def backfill(batch_size=2000):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id FROM items
        WHERE created_at IS NULL
        ORDER BY favorite_count DESC
        LIMIT %s
    """, (batch_size,))
    ids = [r[0] for r in cur.fetchall()]

    if not ids:
        log("✅ No items need backfilling. All done.")
        cur.close(); conn.close()
        return

    log(f"📅 Backfilling {len(ids)} items (popularity-sorted)")

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
                try:
                    conn.rollback()
                except Exception:
                    pass
                failed += 1
        else:
            failed += 1

        if i % 50 == 0:
            elapsed = time.time() - start
            rate = i / elapsed if elapsed > 0 else 0
            log(f"  [{i}/{len(ids)}] filled={filled} failed={failed} ({rate:.1f}/s)")

        time.sleep(0.35)

    cur.close()
    conn.close()
    log(f"✅ Done: {filled} filled, {failed} failed in {time.time()-start:.1f}s")


if __name__ == "__main__":
    batch = int(os.getenv("BATCH_SIZE", "2000"))
    backfill(batch)
