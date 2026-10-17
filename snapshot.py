"""
snapshot.py — Fast snapshot from Render's trusted IP.
"""
import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import get_db_connection


def log(msg):
    print(msg, flush=True)


# ── Production settings (1000 items) ──
TOP_ITEMS_LIMIT = 1000
MIN_FAVS = 200
BATCH_SIZE = 500
WORKERS_PER_SESSION = 3
DELAY = 0.4
MAX_RETRIES = 3

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
log(f"🔐 {len(SESSIONS)} sessions → {TOTAL_WORKERS} workers · {DELAY}s delay")

_stats = {"ok": 0, "429": 0, "403": 0, "404": 0, "other": 0, "exc": 0}


def fetch_fresh_favs(item_id):
    for session in SESSIONS:
        for attempt in range(MAX_RETRIES):
            try:
                r = session.get(FAV_URL.format(item_id), timeout=10)
                if r.status_code == 200:
                    favs = r.json().get("favoriteCount")
                    if favs is not None:
                        _stats["ok"] += 1
                        return item_id, int(favs)
                    else:
                        _stats["other"] += 1
                        return item_id, None
                elif r.status_code == 429:
                    _stats["429"] += 1
                    wait = int(r.headers.get("Retry-After", 3))
                    time.sleep(wait + attempt * 2)
                    continue
                elif r.status_code == 403:
                    _stats["403"] += 1
                    time.sleep(2)
                    continue
                elif r.status_code == 404:
                    _stats["404"] += 1
                    return item_id, None
                else:
                    _stats["other"] += 1
                    return item_id, None
            except Exception:
                _stats["exc"] += 1
                time.sleep(1)
    return item_id, None


def snapshot_top_items():
    log("📸 Snapshot job started.")
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
    log(f"📊 Found {len(rows)} items to snapshot.")

    if not rows:
        log("✅ Nothing to snapshot.")
        cur.close(); conn.close()
        return

    log(f"🔄 Fetching with {TOTAL_WORKERS} workers, {DELAY}s delay...")
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
                log(f"   {completed[0]}/{len(ids)} fetched · "
                    f"ok={_stats['ok']} 429={_stats['429']}")
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

    log(f"✅ Success: {len(fresh_favs)}/{len(ids)} items")
    log(f"📊 Stats: {_stats}")

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


if __name__ == "__main__":
    try:
        snapshot_top_items()
    except Exception as e:
        log(f"❌ FATAL: {e}")
        import traceback
        traceback.print_exc()
        raise
