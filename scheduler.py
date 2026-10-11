"""
scheduler.py — Built-in scheduler for the bot.

Jobs:
  - daily_snapshot    — 03:30 UTC — captures top item favorites
  - daily_ml_train    — 04:00 UTC — retrains title predictor
  - post_monitor      — 18:00 UTC — daily sales report (CSV-based)
"""
import os
import asyncio
import time
import traceback
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
        snapshot_top_items()
        _log(f"✅ [scheduler] Snapshot finished in {time.time()-start:.1f}s")
    except Exception as e:
        _log(f"❌ [scheduler] Snapshot failed: {type(e).__name__}: {e}")
        traceback.print_exc()


def _run_ml_train():
    _log("🧠 [scheduler] ML train job triggered.")
    try:
        from title_predictor import train_model
        train_model()
        _log("✅ [scheduler] ML train finished.")
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

        from discord_ugc_bot import bot
        if bot.loop is None or bot.loop.is_closed():
            _log("⚠️ [post-monitor] bot loop not ready")
            return

        from post_monitor import send_daily_report
        asyncio.run_coroutine_threadsafe(
            send_daily_report(bot, channel_id),
            bot.loop,
        )
        _log("📡 [post-monitor] report queued")
    except Exception as e:
        _log(f"❌ [post-monitor] {type(e).__name__}: {e}")


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        _log("⚠️ [scheduler] Already running — skipping duplicate start.")
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="UTC")

    _scheduler.add_job(_run_snapshot, "cron",
        hour=SNAPSHOT_HOUR_UTC, minute=SNAPSHOT_MINUTE_UTC,
        id="daily_snapshot", replace_existing=True, misfire_grace_time=3600)

    _scheduler.add_job(_run_ml_train, "cron",
        hour=SNAPSHOT_HOUR_UTC + 1, minute=0,
        id="daily_ml_train", replace_existing=True, misfire_grace_time=3600)

    _scheduler.add_job(_run_post_monitor, "cron",
        hour=POST_MONITOR_HOUR_UTC, minute=0,
        id="post_monitor", replace_existing=True, misfire_grace_time=3600)

    _scheduler.start()

    for job in _scheduler.get_jobs():
        _log(f"🕐 [scheduler] '{job.id}' next run: {job.next_run_time}")

    _log(f"✅ [scheduler] Started — snapshot 03:30 UTC, "
         f"ML train 04:00 UTC, post-monitor 18:00 UTC")

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
