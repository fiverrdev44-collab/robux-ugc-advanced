"""
snapshot.py — Daily snapshot with LIVE refresh from Roblox.
Fetches fresh favourite counts from Roblox, then saves to item_history.
"""
import os
import time
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import get_db_connection


def log(msg):
    print(msg, flush=True)


TOP_ITEMS_LIMIT = 5000
MIN_FAVS = 50
BATCH_SIZE = 500
WORKERS = 3
SESSION_DELAY = 1.5

COOKIES = []
for i in range(1, 6):
    c = os.getenv(f"ROBLOSECURITY_COOKIE_{i}")
    if c:
        COOKIES.append(c.strip())
if not COOKIES:
    single = os.getenv("ROBLOSECURITY_COOKIE")
    if single:
        COOKIES.append(single.strip())

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}

FAV_URL = "https://catalog.roblox.com/v1/catalog/items/{}/details?itemType=Asset"

SESSIONS = []
for cookie in COOKIES:
    s = requests.Session()
    s.cookies[".ROBLOSECURITY"] = cookie
    s.headers.update(HEADERS)
    SESSIONS.append(s)


def fetch_fresh_favs(item_id):
    """Fetch latest favourite count for one item."""
    for session in SESSIONS:
        try:
            r = session.get(FAV_URL.format(item_id), timeout=10)
            if r.status_code == 200:
                favs = r.json().get("favoriteCount")
                if favs is not None:
                    try:
                        return item_id, int(favs)
                    except (TypeError, ValueError):
                        pass
            elif r.status_code == 429:
                time.sleep(3)
                continue
        except Exception:
            continue
    return item_id, None


def snapshot_top_items():
    log("📸 Snapshot job started (with live refresh).")
    start = time.time()

    conn = get_db_connection()
    cur = conn.cursor()

    # Get top items that don't have today's snapshot yet
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
        log("✅ Nothing to snapshot.")
        cur.close(); conn.close()
        return

    # ── Step 1: Refresh favourite counts from Roblox ──
    log(f"🔄 Fetching live favourite counts for {len(rows)} items...")
    id_to_data = {r[0]: {"total_sales": r[2], "price": r[3]} for r in rows}
    ids = list(id_to_data.keys())

    # Distribute across sessions
    slices = [[] for _ in SESSIONS]
    for i, iid in enumerate(ids):
        slices[i % len(SESSIONS)].append(iid)

    def _worker(session_ids):
        out = {}
        for idx, iid in enumerate(session_ids):
            _, favs = fetch_fresh_favs(iid)
            if favs is not None:
                out[iid] = favs
            if (idx + 1) % 100 == 0:
                log(f"   {idx+1}/{len(session_ids)} fetched")
            time.sleep(SESSION_DELAY)
        return out

    fresh_favs = {}
    with ThreadPoolExecutor(max_workers=len(SESSIONS)) as ex:
        futures = [ex.submit(_worker, s) for s in slices]
        for f in as_completed(futures):
            try:
                fresh_favs.update(f.result(timeout=3600))
            except Exception as e:
                log(f"   worker error: {e}")

    log(f"✅ Got fresh counts for {len(fresh_favs)}/{len(ids)} items.")

    # ── Step 2: Update items table with fresh favs ──
    for iid, favs in fresh_favs.items():
        try:
            cur.execute(
                "UPDATE items SET favorite_count = %s WHERE id = %s",
                (favs, iid)
            )
        except Exception:
            pass
    conn.commit()

    # ── Step 3: Insert snapshots ──
    log("💾 Inserting snapshots...")
    inserted = 0
    batch = []
    for iid, data in id_to_data.items():
        favs = fresh_favs.get(iid)
        if favs is None:
            continue
        batch.append((iid, favs, data["total_sales"] or 0, data["price"] or 0))
        if len(batch) >= BATCH_SIZE:
            cur.executemany("""
                INSERT INTO item_history (item_id, favorite_count, total_sales, price)
                VALUES (%s, %s, %s, %s)
            """, batch)
            conn.commit()
            inserted += len(batch)
            log(f"   inserted {inserted}...")
            batch = []

    if batch:
        cur.executemany("""
            INSERT INTO item_history (item_id, favorite_count, total_sales, price)
            VALUES (%s, %s, %s, %s)
        """, batch)
        conn.commit()
        inserted += len(batch)

    cur.close(); conn.close()
    log(f"✅ Snapshot complete: {inserted} rows in {time.time()-start:.1f}s")


if __name__ == "__main__":
    try:
        snapshot_top_items()
    except Exception as e:
        log(f"❌ FATAL: {e}")
        import traceback
        traceback.print_exc()
        raise
