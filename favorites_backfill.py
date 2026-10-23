"""favorites_backfill.py — fill missing favorites from the live Roblox API.

Prioritizes launch-ledger items first, then the newest missing items. This is
rate-limited and resumable; run it repeatedly (or let the scheduler do it).
"""
import argparse
import time

from bot_core import get_db
from recovery_brain import fetch_item_from_roblox, save_item_to_db


def pick_ids(cur, limit):
    limit = int(limit)
    cur.execute("SELECT item_id FROM launch_ledger LIMIT %s", (limit,))
    ids = [r[0] for r in cur.fetchall()]
    remaining = max(0, limit - len(ids))
    if remaining:
        cur.execute("""
            SELECT id FROM items
            WHERE favorite_count IS NULL
            ORDER BY created_at DESC NULLS LAST, id DESC
            LIMIT %s
        """, (remaining,))
        ids.extend(r[0] for r in cur.fetchall())
    return list(dict.fromkeys(ids))[:limit]


def run(limit=300, sleep=1.0):
    conn = get_db()
    cur = conn.cursor()
    ids = pick_ids(cur, limit)
    print(f"[favorites_backfill] selected {len(ids)} items", flush=True)
    ok = 0
    failed = 0
    for index, item_id in enumerate(ids, 1):
        try:
            item = fetch_item_from_roblox(item_id)
            if item and item.get("favorite_count") is not None:
                save_item_to_db(cur, item)
                ok += 1
            else:
                failed += 1
            if index % 20 == 0:
                conn.commit()
                print(f"[favorites_backfill] {index}/{len(ids)} "
                      f"ok={ok} failed={failed}", flush=True)
        except Exception as e:
            failed += 1
            conn.rollback()
            print(f"[favorites_backfill] {item_id} failed: {e}", flush=True)
        time.sleep(sleep)
    conn.commit()
    cur.close()
    conn.close()
    return ok, failed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--sleep", type=float, default=1.0)
    args = parser.parse_args()
    ok, failed = run(limit=args.limit, sleep=args.sleep)
    print(f"done: ok={ok} failed={failed}")


if __name__ == "__main__":
    main()
