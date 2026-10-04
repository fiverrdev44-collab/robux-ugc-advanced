"""
scheduler.py — Built-in daily scheduler for the bot.
Runs snapshot daily from Render's IP (avoids GitHub Actions rate limits).
"""
import os
import time
import asyncio
import traceback
from datetime import datetime, timezone
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


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        _log("⚠️ [scheduler] Already running — skipping duplicate start.")
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="UTC")

    _scheduler.add_job(
        _run_snapshot, "cron",
        hour=SNAPSHOT_HOUR_UTC, minute=SNAPSHOT_MINUTE_UTC,
        id="daily_snapshot", replace_existing=True,
        misfire_grace_time=3600,
    )

    _scheduler.add_job(
        _run_ml_train, "cron",
        hour=SNAPSHOT_HOUR_UTC + 1, minute=0,
        id="daily_ml_train", replace_existing=True,
        misfire_grace_time=3600,
    )

    _scheduler.start()

    for job in _scheduler.get_jobs():
        _log(f"🕐 [scheduler] '{job.id}' next run: {job.next_run_time}")

    _log(f"✅ [scheduler] Started — snapshot daily at "
         f"{SNAPSHOT_HOUR_UTC:02d}:{SNAPSHOT_MINUTE_UTC:02d} UTC")

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
