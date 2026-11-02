"""Portfolio-wide change intelligence (legacy module path).

The scheduled entry point monitors all IDs in my_portfolio. Each distinct
metadata intervention gets its own Astra run/outcome, committed atomically
with the corresponding items-table baseline update.
"""
import json
import os

BATCH_RATE = int(os.getenv("PORTFOLIO_WATCH_RATE", "45"))
HEURISTIC_VERSION = "portfolio-change-v1"


def classify_change(old_name, old_description, live_name, live_description):
    """Return name_only, description_only, both, or None.

    NULL is an unknown prior value, not an empty string to compare against.
    """
    name_changed = old_name is not None and old_name != live_name
    description_changed = (
        old_description is not None
        and old_description != live_description
    )
    if name_changed and description_changed:
        return "both"
    if name_changed:
        return "name_only"
    if description_changed:
        return "description_only"
    return None


def _family_for(asset_type_id):
    try:
        from category_configs import detect_family_from_asset_type
        return detect_family_from_asset_type(asset_type_id)
    except Exception:
        return None


def _baseline_sales(cur, item_id, stored_total_sales):
    """Return the latest known cumulative total_sales, or NULL.

    my_sales stores individual observed sale events and launch_ledger stores
    windowed unit counts, not lifetime totals. item_history.total_sales is the
    available point-in-time cumulative total; items.total_sales is a fallback.
    """
    cur.execute("""
        SELECT total_sales
        FROM item_history
        WHERE item_id = %s AND total_sales IS NOT NULL
        ORDER BY snapshot_at DESC
        LIMIT 1
    """, (item_id,))
    row = cur.fetchone()
    if row and row[0] is not None:
        return int(row[0])
    return int(stored_total_sales) if stored_total_sales is not None else None


def _baseline_favorites(live, stored_favorites):
    value = live.get("favorite_count")
    if value is None:
        value = stored_favorites
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _matching_recommendation(cur, item_id, live_name):
    cur.execute("""
        SELECT id
        FROM recommendation_ledger
        WHERE item_id = %s
          AND rec_type = 'rename'
          AND recommended_name IS NOT NULL
          AND lower(recommended_name) = lower(%s)
          AND created_at > now() - interval '30 days'
        ORDER BY created_at DESC
        LIMIT 1
    """, (item_id, live_name))
    row = cur.fetchone()
    return row[0] if row else None


def portfolio_change_watcher(db_factory=None, notifier=None, fetcher=None):
    """Watch every portfolio item and atomically record metadata interventions."""
    if db_factory is None:
        from bot_core import get_db as db_factory
    if fetcher is None:
        from roblox_batch_client import fetch_many_items_sync as fetcher

    conn = None
    cur = None
    item_ids = []
    live_items = {}
    failed_count = 0
    captured = []
    alerts = []
    try:
        conn = db_factory()

        # Read the full portfolio, independent of recommendation history.
        with conn:
            cur = conn.cursor()
            try:
                cur.execute("SET statement_timeout='20s'")
                cur.execute("""
                    SELECT item_id
                    FROM my_portfolio
                    WHERE item_id IS NOT NULL
                    ORDER BY item_id
                """)
                item_ids = list(dict.fromkeys(
                    int(row[0]) for row in cur.fetchall() if row and row[0]
                ))
            finally:
                cur.close()
                cur = None

        if not item_ids:
            return {"portfolio": 0, "checked": 0, "captured": [],
                    "failed": 0}

        live_items, failed = fetcher(
            item_ids, max_batch=30, rate_per_min=BATCH_RATE,
            max_concurrency=2,
        )
        failed_count = len(failed or {})
        if not live_items:
            return {"portfolio": len(item_ids), "checked": 0,
                    "captured": [], "failed": failed_count,
                    "note": "No live portfolio items were returned"}

        # A single transaction protects every Astra event and baseline update.
        with conn:
            cur = conn.cursor()
            try:
                cur.execute("SET statement_timeout='20s'")
                for item_id in item_ids:
                    live = live_items.get(item_id)
                    if not live:
                        continue
                    live_name = live.get("name")
                    live_description = live.get("description")
                    if live_name is None or not str(live_name).strip():
                        continue
                    live_name = str(live_name)[:500]
                    live_description = (
                        str(live_description)[:5000]
                        if live_description is not None else None
                    )

                    # Re-read under a row lock. A second watcher instance will
                    # see the first instance's committed baseline and dedupe.
                    cur.execute("""
                        SELECT name, description, favorite_count,
                               asset_type_id, total_sales
                        FROM items
                        WHERE id = %s
                        FOR UPDATE
                    """, (item_id,))
                    stored = cur.fetchone()
                    if not stored:
                        # No prior local state: initialize without claiming
                        # that the live value is a user intervention.
                        cur.execute("""
                            INSERT INTO items
                              (id, name, description, favorite_count,
                               asset_type_id, fetched_at)
                            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                            ON CONFLICT (id) DO NOTHING
                        """, (
                            item_id, live_name, live_description,
                            live.get("favorite_count"),
                            live.get("asset_type_id") or None,
                        ))
                        continue

                    (old_name, old_description, stored_favorites,
                     stored_asset_type, stored_total_sales) = stored
                    change_type = classify_change(
                        old_name, old_description, live_name,
                        live_description,
                    )
                    if change_type is None:
                        continue

                    changed_fields = (
                        ["name", "description"] if change_type == "both"
                        else ["name"] if change_type == "name_only"
                        else ["description"]
                    )
                    baseline_favs = _baseline_favorites(
                        live, stored_favorites
                    )
                    baseline_sales = _baseline_sales(
                        cur, item_id, stored_total_sales
                    )
                    recommendation_id = (
                        _matching_recommendation(cur, item_id, live_name)
                        if "name" in changed_fields else None
                    )
                    source = (
                        "recommendation_match"
                        if recommendation_id is not None else "manual_change"
                    )
                    event = {
                        "event_type": change_type,
                        "changed_fields": changed_fields,
                        "source": source,
                        "source_recommendation_id": recommendation_id,
                        "old_name": old_name,
                        "new_name": live_name,
                        "old_description": old_description,
                        "new_description": live_description,
                    }
                    family = _family_for(
                        live.get("asset_type_id") or stored_asset_type
                    )

                    cur.execute("""
                        INSERT INTO astra_runs
                          (item_id, linked_item_id, concept, asset_type,
                           angles, titles, chosen_title, preview_version,
                           linked_at)
                        VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb,
                                %s, %s, now())
                        RETURNING id
                    """, (
                        item_id, item_id,
                        f"Portfolio change: {change_type}", family,
                        json.dumps(event, ensure_ascii=False, default=str),
                        json.dumps([old_name, live_name], ensure_ascii=False),
                        live_name[:200], HEURISTIC_VERSION,
                    ))
                    run_row = cur.fetchone()
                    if not run_row:
                        raise RuntimeError(
                            f"astra_runs insert returned no run_id for {item_id}"
                        )
                    run_id = run_row[0]

                    cur.execute("""
                        INSERT INTO astra_outcomes
                          (run_id, item_id, baseline_favorites,
                           baseline_sales, baseline_captured_at, launched_at,
                           heuristic_version)
                        VALUES (%s, %s, %s, %s, now(), now(), %s)
                    """, (
                        run_id, item_id, baseline_favs, baseline_sales,
                        HEURISTIC_VERSION,
                    ))

                    cur.execute("""
                        UPDATE items
                        SET name = %s,
                            description = %s,
                            favorite_count = COALESCE(%s, favorite_count),
                            asset_type_id = COALESCE(%s, asset_type_id),
                            fetched_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (
                        live_name, live_description,
                        live.get("favorite_count"),
                        live.get("asset_type_id") or None, item_id,
                    ))

                    field_label = (
                        "name and description" if change_type == "both"
                        else "name" if change_type == "name_only"
                        else "description"
                    )
                    captured.append({
                        "run_id": run_id,
                        "item_id": item_id,
                        "item_name": live_name,
                        "change_type": change_type,
                        "baseline_favorites": baseline_favs,
                        "baseline_sales": baseline_sales,
                        "source": source,
                        "recommendation_id": recommendation_id,
                    })
                    alerts.append(
                        "🤖 Auto-Tracked Change! I detected a "
                        f"{field_label} update for '{live_name}'. "
                        "Baseline captured. Tracking D7/D30 outcomes now."
                    )
            finally:
                cur.close()
                cur = None

        # Alert only after commit; rolled-back writes cannot emit success alerts.
        for message in alerts:
            if notifier:
                try:
                    notifier(message)
                except Exception as exc:
                    print(
                        f"[portfolio-watcher] Discord alert failed: "
                        f"{type(exc).__name__}: {exc}",
                        flush=True,
                    )
            print(f"[portfolio-watcher] {message}", flush=True)

        return {
            "portfolio": len(item_ids),
            "checked": len(live_items),
            "captured": captured,
            "failed": failed_count,
        }
    except Exception as exc:
        print(
            f"[portfolio-watcher] failed: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return {
            "portfolio": len(item_ids),
            "checked": len(live_items),
            "captured": [],
            "failed": failed_count,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


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
