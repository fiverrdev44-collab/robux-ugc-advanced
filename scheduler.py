"""
scheduler.py — Built-in scheduler for the bot.

Jobs:
  - daily_snapshot    — 03:30 UTC — captures top item favorites
  - daily_ml_train    — 04:00 UTC — retrains title predictor
  - post_monitor      — 18:00 UTC — daily sales report (CSV-based)

FIXES:
  - _run_post_monitor uses _main_loop (captured in on_ready) instead
    of bot.loop — bot.loop doesn't exist in discord.py 2.x.
"""
import os
import asyncio
import time
import traceback
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.background import BackgroundScheduler


SNAPSHOT_HOUR_UTC = 3
SNAPSHOT_MINUTE_UTC = 30
POST_MONITOR_HOUR_UTC = 18  # 22:00 GMT+4

_scheduler = None


def _log(msg):
    print(msg, flush=True)


def _run_snapshot():
    _log("📸 [scheduler] Snapshot job triggered.")
    start = time.time()
    try:
        from snapshot import snapshot_top_items
        result = snapshot_top_items()
        if result is False:
            _log("⚠️ [scheduler] Snapshot already running — skipped this trigger.")
            return
        _log(f"✅ [scheduler] Snapshot finished in {time.time()-start:.1f}s")
    except Exception as e:
        _log(f"❌ [scheduler] Snapshot failed: {type(e).__name__}: {e}")
        traceback.print_exc()


def _run_creator_brain():
    """Nightly systematic review of the creator cohort."""
    _log("🧠 [scheduler] Creator brain refresh triggered.")
    start = time.time()
    try:
        from creator_brain import learn, save
        from bot_core import get_db

        conn = get_db()
        cur = conn.cursor()
        try:
            findings = learn(cur)
            if findings:
                save(cur, findings)
                conn.commit()
                _log(
                    f"✅ [scheduler] Creator brain — {findings['cohort_size']} "
                    f"creators · {findings['items']} items · "
                    f"{time.time()-start:.1f}s"
                )
            else:
                _log("⚠️ [scheduler] Creator brain — not enough history yet.")
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        _log(f"❌ [scheduler] Creator brain failed: {type(e).__name__}: {e}")


def _run_verified_scan():
    """Rolling scan of verified creators (throttled by creator_tracker)."""
    _log("🔎 [scheduler] Verified creator scan triggered.")
    start = time.time()
    try:
        from creator_tracker import run_batch
        from bot_core import get_db

        conn = get_db()
        cur = conn.cursor()
        try:
            scanned, upserted, discovered, note = run_batch(cur, limit=20)
        finally:
            cur.close()
            conn.close()

        _log(
            f"✅ [scheduler] Verified scan — {scanned} creators · "
            f"{upserted} items · {discovered} new · {time.time()-start:.1f}s"
            + (f" · {note}" if note else "")
        )
    except Exception as e:
        _log(f"❌ [scheduler] Verified scan failed: {type(e).__name__}: {e}")


def _run_ml_train():
    _log("🧠 [scheduler] ML train job triggered.")
    try:
        from title_predictor import train_model
        from bot_core import get_db

        conn = get_db()
        cur = conn.cursor()
        try:
            res = train_model(cur)
        finally:
            cur.close()
            conn.close()

        if res:
            _log(
                f"✅ [scheduler] ML train finished — "
                f"{res.get('n_samples', 0)} samples, "
                f"accuracy {res.get('accuracy', 0) * 100:.1f}%"
            )
        else:
            _log("⚠️ [scheduler] ML train returned no model (not enough data).")
    except ImportError:
        _log("⚠️ [scheduler] title_predictor not found — skipping.")
    except Exception as e:
        _log(f"❌ [scheduler] ML train failed: {type(e).__name__}: {e}")


def _run_post_monitor():
    """Daily sales report → ALERT_CHANNEL_ID."""
    try:
        channel_id = os.getenv("ALERT_CHANNEL_ID")
        if not channel_id:
            _log("⚠️ [post-monitor] ALERT_CHANNEL_ID not set")
            return

        # Import bot + captured loop from orchestrator
        from discord_ugc_bot import bot, _main_loop

        if _main_loop is None or _main_loop.is_closed():
            _log("⚠️ [post-monitor] main loop not ready yet (bot not connected?)")
            return

        from post_monitor import send_daily_report
        asyncio.run_coroutine_threadsafe(
            send_daily_report(bot, channel_id),
            _main_loop,     # ← captured loop, NOT bot.loop
        )
        _log("📡 [post-monitor] report queued")
    except Exception as e:
        _log(f"❌ [post-monitor] {type(e).__name__}: {e}")
        traceback.print_exc()


def _run_launch_sync():
    """Auto-log group items and refresh ledger outcomes daily."""
    _log("📒 [scheduler] Launch sync triggered.")
    try:
        from launch_ledger import configured_groups, sync_group_items, sync_all
        from bot_core import get_db

        groups = configured_groups()
        if not groups:
            _log("⚠️ [scheduler] MY_GROUP_NAMES not set — skipping launch sync.")
            return

        conn = get_db()
        cur = conn.cursor()
        try:
            total, added = sync_group_items(cur, groups)
            synced = sync_all(cur)
            conn.commit()
            _log(
                f"✅ [scheduler] Launch sync — found {total} group items, "
                f"{added} new, {synced} outcomes synced."
            )
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        _log(f"❌ [scheduler] Launch sync failed: {type(e).__name__}: {e}")
        traceback.print_exc()


def _run_experiment_measure():
    """Measure due recommendation experiments daily."""
    _log("🧪 [scheduler] Experiment measurement triggered.")
    try:
        from experiments import auto_apply_changes, measure_due
        from bot_core import get_db

        conn = get_db(); cur = conn.cursor()
        try:
            auto_applied = auto_apply_changes(cur)
            measured = measure_due(cur)
            conn.commit()
            _log(f"✅ [scheduler] Auto-applied {auto_applied}, "
                 f"measured {measured} experiment(s).")
        finally:
            cur.close(); conn.close()
    except Exception as e:
        _log(f"❌ [scheduler] Experiment measurement failed: "
             f"{type(e).__name__}: {e}")


def _run_visibility():
    """Twice daily: collect sampled search-visibility observations."""
    try:
        from search_visibility import collect, seed_queries
        from bot_core import get_db

        conn = get_db(); cur = conn.cursor()
        try:
            cur.execute("SELECT count(*) FROM search_queries")
            if not cur.fetchone()[0]:
                seed_queries(cur, 50)
            done = collect(cur, limit=20)
            conn.commit()
            _log(f"✅ [scheduler] Visibility collected {done} query run(s).")
        finally:
            cur.close(); conn.close()
    except Exception as e:
        _log(f"❌ [scheduler] Visibility failed: {type(e).__name__}: {e}")


def _run_favorites_backfill():
    """Daily: fill missing favorites, ledger items first."""
    _log("⭐ [scheduler] Favorites backfill triggered.")
    try:
        from favorites_backfill import run
        ok, failed = run(limit=500, sleep=1.0)
        _log(f"✅ [scheduler] Favorites backfill: ok={ok}, failed={failed}")
    except Exception as e:
        _log(f"❌ [scheduler] Favorites backfill failed: "
             f"{type(e).__name__}: {e}")


def _run_experiment_watch():
    """Every 15 min: auto-apply detected item changes and measure due rows."""
    try:
        from experiments import auto_apply_changes, measure_due
        from bot_core import get_db

        conn = get_db(); cur = conn.cursor()
        try:
            auto_applied = auto_apply_changes(cur)
            measured = measure_due(cur)
            conn.commit()
            if auto_applied or measured:
                _log(f"🧪 [watch] auto-applied {auto_applied}, "
                     f"measured {measured} experiment(s).")
        finally:
            cur.close(); conn.close()
    except Exception as e:
        _log(f"❌ [watch] Experiment watch failed: "
             f"{type(e).__name__}: {e}")


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        _log("⚠️ [scheduler] Already running — skipping duplicate start.")
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="UTC")

    _scheduler.add_job(_run_snapshot, "cron",
        hour=SNAPSHOT_HOUR_UTC, minute=SNAPSHOT_MINUTE_UTC,
        id="daily_snapshot", replace_existing=True, misfire_grace_time=21600)

    # Top-up runs later in the day. The snapshot query skips items already
    # captured today, so these fill in whatever throttling left behind.
    for hour in (9, 15, 21):
        _scheduler.add_job(_run_snapshot, "cron",
            hour=hour, minute=SNAPSHOT_MINUTE_UTC,
            id=f"snapshot_topup_{hour}", replace_existing=True,
            misfire_grace_time=3600)

    _scheduler.add_job(_run_ml_train, "cron",
        hour=SNAPSHOT_HOUR_UTC + 1, minute=0,
        id="daily_ml_train", replace_existing=True, misfire_grace_time=3600)

    _scheduler.add_job(_run_creator_brain, "cron",
        hour=5, minute=0,
        id="daily_creator_brain", replace_existing=True, misfire_grace_time=3600)

    for hour in (1, 7, 13, 19):
        _scheduler.add_job(_run_verified_scan, "cron",
            hour=hour, minute=15,
            id=f"verified_scan_{hour}", replace_existing=True,
            misfire_grace_time=3600)

    _scheduler.add_job(_run_post_monitor, "cron",
        hour=POST_MONITOR_HOUR_UTC, minute=0,
        id="post_monitor", replace_existing=True, misfire_grace_time=3600)

    _scheduler.add_job(_run_launch_sync, "cron",
        hour=7, minute=30,
        id="launch_sync", replace_existing=True, misfire_grace_time=3600)

    _scheduler.add_job(_run_experiment_measure, "cron",
        hour=8, minute=0,
        id="experiment_measure", replace_existing=True, misfire_grace_time=3600)

    _scheduler.add_job(_run_experiment_watch, "interval", minutes=15,
        id="experiment_watch", replace_existing=True,
        max_instances=1, coalesce=True, misfire_grace_time=600)

    _scheduler.add_job(_run_favorites_backfill, "cron",
        hour=2, minute=30,
        id="favorites_backfill", replace_existing=True,
        misfire_grace_time=3600)

    for hour in (4, 16):
        _scheduler.add_job(_run_visibility, "cron",
            hour=hour, minute=30,
            id=f"visibility_{hour}", replace_existing=True,
            misfire_grace_time=3600)

    # Catch up if the daily snapshot was missed (bot restarted at 03:30,
    # long downtime, or a failed run). Prevents 24h+ gaps in item_history,
    # which would break velocity/oracle/ledger windows.
    try:
        from bot_core import get_db

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT max(snapshot_at) FROM item_history")
        last_snap = cur.fetchone()[0]
        cur.close()
        conn.close()

        now = datetime.now(timezone.utc)
        stale = (
            last_snap is None
            or (now - last_snap.replace(tzinfo=timezone.utc)).total_seconds() > 86400
        )
        if stale:
            _scheduler.add_job(
                _run_snapshot, "date",
                run_date=now + timedelta(seconds=30),
                id="snapshot_catchup", replace_existing=True,
            )
            _log("📸 [scheduler] Snapshot stale — catch-up scheduled in 30s")
    except Exception as e:
        _log(f"⚠️ [scheduler] snapshot catch-up check failed: {e}")

    _scheduler.start()

    for job in _scheduler.get_jobs():
        _log(f"🕐 [scheduler] '{job.id}' next run: {job.next_run_time}")

    _log(f"✅ [scheduler] Started — snapshot 03:30 UTC "
         f"(top-ups 09:30/15:30/21:30), "
         f"ML train 04:00 UTC, launch sync 07:30 UTC, "
         f"post-monitor 18:00 UTC (scanner/suggest via GitHub → Server 2)")

    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler:
        try:
            _scheduler.shutdown(wait=False)
            _log("🛑 [scheduler] Stopped.")
        except Exception:
            pass
        _scheduler = None
