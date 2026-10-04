"""
discord_ugc_bot.py — thin orchestrator.
All commands live in commands_*.py modules.

Includes:
- Discord health check (returns 503 when bot is dead)
- Watchdog thread (auto-reconnects on silent disconnect)
- Auto-restart loop (catches crashes)
- Background scheduler (daily snapshot)
"""
import os
import time
import threading
import asyncio
import traceback
import discord
from discord.ext import commands
from flask import Flask

from bot_core import get_db, ASSET_TYPE_NAMES
from commands_guide import register_guide_commands
from commands_market import register_market_commands
from commands_ai import register_ai_commands

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ── Shared state for watchdog ────────────────────────────────
_last_heartbeat = time.time()
_watchdog_running = True


@bot.event
async def on_ready():
    global _last_heartbeat
    _last_heartbeat = time.time()
    print(f"✅ {bot.user} is online", flush=True)
    try:
        from database import setup_database
        setup_database()
        print("✅ Database tables verified/created.", flush=True)
    except Exception as e:
        print(f"⚠️ Table setup failed: {e}", flush=True)


@bot.event
async def on_disconnect():
    print("⚠️ Discord disconnected — watchdog will attempt reconnect.", flush=True)


@bot.event
async def on_resumed():
    global _last_heartbeat
    _last_heartbeat = time.time()
    print("✅ Discord session resumed.", flush=True)


@bot.event
async def on_socket_raw_receive(msg):
    """Heartbeat: any socket activity means connection is alive."""
    global _last_heartbeat
    _last_heartbeat = time.time()


# ── Register all command modules ─────────────────────────────
register_guide_commands(bot)
print("✅ Guide commands loaded.", flush=True)

register_market_commands(bot)
print("✅ Market commands loaded.", flush=True)

register_ai_commands(bot)
print("✅ AI commands loaded.", flush=True)

try:
    from commands_intel import register_intel_commands
    register_intel_commands(bot, get_db, ASSET_TYPE_NAMES)
    print("✅ Intel commands loaded.", flush=True)
except Exception as e:
    print(f"⚠️ Intel commands failed to load: {e}", flush=True)

try:
    from commands_advanced import register_advanced_commands
    register_advanced_commands(bot, get_db)
    print("✅ Advanced commands loaded.", flush=True)
except Exception as e:
    print(f"⚠️ Advanced commands failed to load: {e}", flush=True)


# ── Start background scheduler ───────────────────────────────
try:
    from scheduler import start_scheduler
    start_scheduler()
except Exception as e:
    print(f"⚠️ [scheduler] Failed to start: {e}", flush=True)


# ── Flask health check for Render ────────────────────────────
app = Flask(__name__)


@app.route('/')
def health():
    """
    Returns 200 only when Discord client is connected AND heartbeat is fresh.
    Otherwise 503 — UptimeRobot will go red.
    """
    try:
        if not bot.is_ready() or bot.is_closed():
            return "Discord disconnected", 503
        # If no heartbeat in 5 minutes, something is stuck
        stale_seconds = time.time() - _last_heartbeat
        if stale_seconds > 300:
            return f"Heartbeat stale ({stale_seconds:.0f}s)", 503
        return "OK", 200
    except Exception as e:
        return f"Health check error: {e}", 503


def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port, threaded=True)


# ── Watchdog thread ──────────────────────────────────────────
def watchdog():
    """
    Every 30s: check if bot is alive. If not, force-close and reconnect.
    Catches the 'silent disconnect' failure mode where the process is
    running but Discord session is dead.
    """
    global _last_heartbeat
    print("🐕 [watchdog] Started — checking every 30s", flush=True)

    while _watchdog_running:
        time.sleep(30)

        try:
            if bot.is_closed():
                print("🐕 [watchdog] Bot is closed — restarting.", flush=True)
                _restart_bot()
                continue

            if not bot.is_ready():
                print("🐕 [watchdog] Bot not ready — waiting one cycle.", flush=True)
                continue

            stale = time.time() - _last_heartbeat
            if stale > 300:
                print(f"🐕 [watchdog] Heartbeat stale for {stale:.0f}s — "
                      f"forcing reconnect.", flush=True)
                _restart_bot()
        except Exception as e:
            print(f"🐕 [watchdog] Error in check: {e}", flush=True)


def _restart_bot():
    """Force the Discord client to reconnect."""
    global _last_heartbeat
    try:
        # Schedule close on the bot's event loop
        if not bot.is_closed():
            future = asyncio.run_coroutine_threadsafe(bot.close(), bot.loop)
            try:
                future.result(timeout=10)
            except Exception as e:
                print(f"🐕 [watchdog] Close timeout: {e}", flush=True)
        _last_heartbeat = time.time()  # reset so we don't trigger immediately
    except Exception as e:
        print(f"🐕 [watchdog] Restart failed: {e}", flush=True)


# ── Main entry — reconnect loop + watchdog + flask ───────────
if __name__ == "__main__":
    # Flask health check in background
    threading.Thread(target=run_flask, daemon=True).start()

    # Watchdog in background
    threading.Thread(target=watchdog, daemon=True).start()

    # Main bot loop — restart on crash
    while True:
        try:
            print("🔌 Starting bot...", flush=True)
            _last_heartbeat = time.time()
            bot.run(TOKEN)
            print("⚠️ bot.run() returned cleanly — restarting in 10s...", flush=True)
        except discord.errors.LoginFailure as e:
            print(f"❌ Login failed (bad token?): {e}", flush=True)
            print("🛑 Not retrying — fix TOKEN and redeploy.", flush=True)
            break
        except Exception as e:
            print(f"❌ Bot crashed: {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
            print("🔄 Restarting in 10s...", flush=True)

        time.sleep(10)
