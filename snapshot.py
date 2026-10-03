"""
snapshot.py — Fast snapshot with live refresh.
Runs from Render (stable IP) → no rate limits.
"""
import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import get_db_connection


def log(msg):
    print(msg, flush=True)


# ── Lightweight settings (1K items) ──
TOP_ITEMS_LIMIT = 1000
MIN_FAVS = 200
BATCH_SIZE = 500
WORKERS_PER_SESSION = 3
DELAY = 0.4

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
    log("⚠️ No cookies — anonymous mode")
    COOKIES = [None]

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
    if cookie:
        s.cookies[".ROBLOSECURITY"] = cookie
    s.headers.update(HEADERS)
    SESSIONS.append(s)

TOTAL_WORKERS = len(SESSIONS) * WORKERS_PER_SESSION
log(f"🔐 {len(SESSIONS)} session(s) → {TOTAL_WORKERS} workers")


def fetch_fresh_favs(item_id):
    for session in SESSIONS:
        try:
            r = session.get(FAV_URL.format(item_id), timeout=8)
            if r.status_code == 200:
                favs = r.json().get("favoriteCount")
                if favs is not None:
                    return item_id, int(favs)
            elif r.status_code == 429:
                time.sleep(1)
                continue
        except Exception:
            continue
    return item_id, None


def snapshot_top_items():
    log("📸 Snapshot starting (light mode)...")
    start = time.time()

    conn = get_db_connection()
    cur = conn.cursor()

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
    log(f"📊 {len(rows)} items to snapshot.")

    if not rows:
        log("✅ All done for today.")
        cur.close(); conn.close()
        return

    id_to_data = {r[0]: {"total_sales": r[2], "price": r[3]} for r in rows}
    ids = list(id_to_data.keys())

    fresh_favs = {}
    completed = [0]

    def _worker(worker_ids):
        out = {}
        for iid in worker_ids:
            _, favs = fetch_fresh_favs(iid)
            if favs is not None:
                out[iid] = favs
            completed[0] += 1
            if completed[0] % 200 == 0:
                log(f"   {completed[0]}/{len(ids)} fetched")
            time.sleep(DELAY)
        return out

    chunks = [[] for _ in range(TOTAL_WORKERS)]
    for i, iid in enumerate(ids):
        chunks[i % TOTAL_WORKERS].append(iid)

    with ThreadPoolExecutor(max_workers=TOTAL_WORKERS) as ex:
        futures = [ex.submit(_worker, chunk) for chunk in chunks]
        for f in as_completed(futures):
            try:
                fresh_favs.update(f.result(timeout=3600))
            except Exception as e:
                log(f"   worker error: {e}")

    log(f"✅ Fetched {len(fresh_favs)}/{len(ids)}")

    for iid, favs in fresh_favs.items():
        try:
            cur.execute("UPDATE items SET favorite_count = %s WHERE id = %s",
                        (favs, iid))
        except Exception:
            pass
    conn.commit()

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


def snapshot_top_items_wrapper():
    """Wrapper for the scheduler to call."""
    snapshot_top_items()


if __name__ == "__main__":
    try:
        snapshot_top_items()
    except Exception as e:
        log(f"❌ FATAL: {e}")
        import traceback
        traceback.print_exc()
        raise
