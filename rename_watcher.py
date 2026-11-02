"""rename_watcher.py — 15-minute watcher for applied/renamed items.

Reads recent rename recommendations, checks live titles in one bounded batch,
and captures a fresh baseline (astra_outcomes) the moment a rename is detected.
"""
import os

WATCH_DAYS = int(os.getenv("RENAME_WATCH_DAYS", "14"))
BATCH_RATE = int(os.getenv("RENAME_WATCH_RATE", "45"))


def is_rename_detected(live_name, baseline_name, recommended_name):
    """Live title equals the recommendation, or differs from the old title."""
    live = (live_name or "").strip().lower()
    if not live:
        return False
    if recommended_name and live == recommended_name.strip().lower():
        return True
    if baseline_name and live != baseline_name.strip().lower():
        return True
    return False


def _family_for(atype):
    try:
        from category_configs import detect_family_from_asset_type
        return detect_family_from_asset_type(atype)
    except Exception:
        return None


def auto_rename_watcher(db_factory=None, notifier=None, fetcher=None):
    """Detect renames and snapshot the new baseline. Returns a summary dict."""
    if db_factory is None:
        from bot_core import get_db as db_factory
    if fetcher is None:
        from roblox_batch_client import fetch_many_items_sync as fetcher

    conn = db_factory(); cur = conn.cursor()
    matches = []
    try:
        cur.execute("SET statement_timeout='20s'")
        cur.execute("""
            select id, item_id, baseline_name, recommended_name, status
            from recommendation_ledger
            where rec_type = 'rename'
              and recommended_name is not null
              and item_id is not null
              and created_at > now() - make_interval(days => %s)
              and coalesce(status, '') in ('proposed', 'applied',
                                           'creator_reported')
            order by created_at desc
        """, (WATCH_DAYS,))
        recs = cur.fetchall()
        latest = {}
        for rid, item_id, baseline, recommended, status in recs:
            latest.setdefault(item_id, {"rec_id": rid, "baseline": baseline,
                                         "recommended": recommended,
                                         "status": status})
        if not latest:
            return {"checked": 0, "captured": []}

        ids = list(latest.keys())[:60]
        items, failed = fetcher(ids, max_batch=30, rate_per_min=BATCH_RATE,
                                max_concurrency=2)
        if not items:
            return {"checked": len(ids), "captured": [],
                    "note": "no live items returned", "failed": len(failed)}

        for item_id, rec in latest.items():
            live = items.get(item_id)
            if not live:
                continue
            live_name = (live.get("name") or "").strip()
            if not is_rename_detected(live_name, rec["baseline"],
                                      rec["recommended"]):
                continue

            cur.execute("""
                select id from astra_runs
                where linked_item_id = %s
                   or (item_id = %s and lower(chosen_title) = lower(%s))
                order by id desc limit 1
            """, (item_id, item_id, live_name))
            run = cur.fetchone()
            run_id = run[0] if run else None
            if run_id is None:
                family = _family_for(live.get("asset_type_id"))
                cur.execute("""
                    insert into astra_runs
                      (item_id, concept, asset_type, titles, chosen_title)
                    values (%s, %s, %s, %s::jsonb, %s)
                    returning id
                """, (item_id, (rec["baseline"] or live_name)[:300], family,
                      str([live_name]), live_name[:200]))
                run_id = cur.fetchone()[0]

            cur.execute("select 1 from astra_outcomes where run_id = %s",
                        (run_id,))
            if cur.fetchone():
                continue  # baseline already captured for this run

            from creator_memory import link_run
            res = link_run(cur, run_id, item_id,
                           heuristic_version="astra-fit-v1")
            if res.get("ok"):
                matches.append({"run_id": run_id, "item_id": item_id,
                                "new_title": live_name,
                                "old_title": rec["baseline"]})
        conn.commit()

        for m in matches:
            text = (f"🤖 Auto-Tracked Rename! I detected that you renamed "
                    f"{m['item_id']} to '{m['new_title']}'. I have captured "
                    f"the baseline snapshot. Tracking D7/D30 outcomes now.")
            if notifier:
                try:
                    notifier(text)
                except Exception as e:
                    print(f"[rename-watcher] notify failed: {e}", flush=True)
            print(f"[rename-watcher] {text}", flush=True)
        return {"checked": len(ids), "captured": matches}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[rename-watcher] failed: {type(e).__name__}: {e}", flush=True)
        return {"error": f"{type(e).__name__}: {e}", "captured": []}
    finally:
        try:
            cur.close(); conn.close()
        except Exception:
            pass
