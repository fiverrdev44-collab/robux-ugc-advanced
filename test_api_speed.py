"""Benchmark: legacy 1-by-1 GET vs 30-item batch POST.

Read-only DB query, one live sequence per method, no production writes.
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import requests

from bot_core import get_db

ECONOMY_URL = "https://economy.roblox.com/v2/assets/{}/details"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/120.0.0.0 Safari/537.36",
           "Accept": "application/json"}
N = 30
PACING = float(os.getenv("SPEED_TEST_DELAY", "0.25"))


def fetch_ids():
    con = get_db()
    con.set_session(readonly=True)
    cur = con.cursor()
    cur.execute("SET statement_timeout='20s'")
    cur.execute("""SELECT id FROM items WHERE favorite_count > 0
                   ORDER BY favorite_count DESC NULLS LAST LIMIT %s""", (N,))
    ids = [r[0] for r in cur.fetchall()]
    cur.close(); con.close()
    return ids


def old_way(ids):
    session = requests.Session()
    session.headers.update(HEADERS)
    statuses = []
    t0 = time.perf_counter()
    for i, iid in enumerate(ids, 1):
        try:
            r = session.get(ECONOMY_URL.format(iid), timeout=15)
            statuses.append(r.status_code)
        except Exception as e:
            statuses.append(type(e).__name__)
        if i < len(ids) and PACING > 0:
            time.sleep(PACING)
    return time.perf_counter() - t0, statuses


def new_way(ids):
    from roblox_batch_client import fetch_many_items_sync
    t0 = time.perf_counter()
    items, failed = fetch_many_items_sync(ids, max_batch=30,
                                          rate_per_min=90, max_concurrency=3)
    elapsed = time.perf_counter() - t0
    return elapsed, items, failed


def main():
    ids = fetch_ids()
    print(f"Sample: {len(ids)} asset IDs (production DB, read-only)")
    print(f"Old-way pacing between GETs: {PACING}s (to avoid tripping 429)")
    assert len(ids) == N, f"expected {N} ids, got {len(ids)}"

    t_old, statuses = old_way(ids)
    old_429 = sum(1 for s in statuses if s == 429)
    print(f"\nA. OLD WAY — {N} sequential GETs: {t_old:.3f}s "
          f"({t_old / N:.3f}s/item), statuses={statuses}")
    print(f"   HTTP 429 in old way: {old_429}")

    print("\nWaiting 5s to clear rate-limit windows...")
    time.sleep(5)

    t_new, items, failed = new_way(ids)
    new_429 = sum(1 for v in failed.values() if "rate" in str(v).lower()
                  or "429" in str(v))
    print(f"\nB. NEW WAY — 1 POST batch of {N}: {t_new:.3f}s, "
          f"items_returned={len(items)}, failed={failed}")
    print(f"   HTTP 429 in new way: {new_429}")

    speedup = (t_old / t_new) if t_new > 0 else float("inf")
    print("\n" + "=" * 58)
    print("SPEED REPORT")
    print("=" * 58)
    print(f"Old way (30 GETs)     : {t_old:.3f}s")
    print(f"New way (1 POST batch): {t_new:.3f}s")
    print(f"Speedup               : {speedup:.1f}x faster")
    print(f"429s                  : old={old_429}, new={new_429}")
    print("=" * 58)
    if old_429 or new_429:
        print("NOTE: a 429 occurred; timing comparison is still valid but "
              "the run was rate-limited.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
