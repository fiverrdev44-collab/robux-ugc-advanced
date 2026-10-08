"""
scheduler.py — Built-in scheduler for the bot.

Jobs:
  - daily_snapshot   — 03:30 UTC — captures top item favorites
  - daily_ml_train   — 04:00 UTC — retrains title predictor
  - post_monitor     — every 15 min — polls portfolio items for spikes/stalls
"""
import os
import time
import traceback
from apscheduler.schedulers.background import BackgroundScheduler


SNAPSHOT_HOUR_UTC = 3
SNAPSHOT_MINUTE_UTC = 30

_scheduler = None


def _log(msg):
    print(msg, flush=True)


def _run_snapshot():
    _log("📸 [scheduler] Snapshot job triggered.")
    start = time.time()
    try:
        from snapshot import snapshot_top_items
        snapshot_top_items()
        elapsed = time.time() - start
        _log(f"✅ [scheduler] Snapshot finished in {elapsed:.1f}s")
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
        _log("⚠️ [scheduler] title_predictor.train_model not found — skipping.")
    except Exception as e:
        _log(f"❌ [scheduler] ML train failed: {type(e).__name__}: {e}")


def _run_post_monitor():
    """Poll portfolio items every 15 min. Alerts are handled inside poll_all."""
    try:
        from bot_core import get_db
        from post_monitor import poll_all
        alerts = poll_all(get_db)
        if alerts:
            _log(f"🩺 [post-monitor] {len(alerts)} alerts detected")
        else:
            _log("🩺 [post-monitor] poll complete — no alerts")
    except Exception as e:
        _log(f"❌ [post-monitor] failed: {type(e).__name__}: {e}")


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        _log("⚠️ [scheduler] Already running — skipping duplicate start.")
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="UTC")

    # Daily snapshot at 03:30 UTC
    _scheduler.add_job(
        _run_snapshot, "cron",
        hour=SNAPSHOT_HOUR_UTC, minute=SNAPSHOT_MINUTE_UTC,
        id="daily_snapshot", replace_existing=True,
        misfire_grace_time=3600,
    )

    # ML train at 04:00 UTC
    _scheduler.add_job(
        _run_ml_train, "cron",
        hour=SNAPSHOT_HOUR_UTC + 1, minute=0,
        id="daily_ml_train", replace_existing=True,
        misfire_grace_time=3600,
    )

    # Portfolio monitor every 15 min
    _scheduler.add_job(
        _run_post_monitor, "interval",
        minutes=15,
        id="post_monitor", replace_existing=True,
        misfire_grace_time=300,
    )

    _scheduler.start()

    for job in _scheduler.get_jobs():
        _log(f"🕐 [scheduler] '{job.id}' next run: {job.next_run_time}")

    _log(f"✅ [scheduler] Started — snapshot daily at "
         f"{SNAPSHOT_HOUR_UTC:02d}:{SNAPSHOT_MINUTE_UTC:02d} UTC, "
         f"monitor every 15 min")

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
