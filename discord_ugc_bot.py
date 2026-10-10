"""
discord_ugc_bot.py — thin orchestrator.
All commands live in commands_*.py modules.

Includes:
- Discord health check (returns 503 when bot is dead)
- Watchdog thread (uses bot.latency + os._exit(1) to force Render restart)
- Background scheduler (daily snapshot + ML train)
"""
import os
import time
import threading
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

_boot_done = False


@bot.event
async def on_ready():
    global _boot_done
    print(f"✅ {bot.user} is online", flush=True)

    if _boot_done:
        print("🔁 on_ready re-fired (reconnect) — skipping setup", flush=True)
        return
    _boot_done = True

    try:
        from database import setup_database
        setup_database()
        print("✅ Database tables verified/created.", flush=True)
    except Exception as e:
        print(f"⚠️ Table setup failed: {e}", flush=True)


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

# ── 🎯 Interactive workflow menu (!start) ────────────────────
try:
    from menu import register_menu_commands
    register_menu_commands(bot, get_db)
    print("✅ Menu command loaded.", flush=True)
except Exception as e:
    print(f"⚠️ Menu command failed to load: {e}", flush=True)

# ── 🩻 X-Ray / Patterns / Failures ───────────────────────────
try:
    from commands_xray import register_xray_commands
    register_xray_commands(bot, get_db)
    print("✅ X-Ray commands loaded.", flush=True)
except Exception as e:
    print(f"⚠️ X-Ray commands failed to load: {e}", flush=True)


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
    try:
        if not bot.is_ready() or bot.is_closed():
            return "Discord disconnected", 503

        lat = bot.latency
        if lat != lat:  # NaN check
            return "Latency is NaN", 503
        if lat > 120:
            return f"High latency: {lat:.1f}s", 503

        return "OK", 200
    except Exception as e:
        return f"Health check error: {e}", 503


def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port, threaded=True)


# ── Watchdog thread ──────────────────────────────────────────
def watchdog():
    print("🐕 [watchdog] Started — checking every 60s", flush=True)
    time.sleep(120)  # Startup grace period

    while True:
        time.sleep(60)
        try:
            if bot.is_closed():
                print("🐕 [watchdog] Bot is closed — exiting for Render restart", flush=True)
                os._exit(1)

            if not bot.is_ready():
                continue

            lat = bot.latency
            if lat != lat:
                print("🐕 [watchdog] Latency is NaN — exiting for Render restart", flush=True)
                os._exit(1)

            if lat > 120:
                print(f"🐕 [watchdog] Latency too high ({lat:.1f}s) — exiting for Render restart", flush=True)
                os._exit(1)

        except Exception as e:
            print(f"🐕 [watchdog] Error: {e}", flush=True)


# ── Main entry ───────────────────────────────────────────────
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()

    print("🔌 Starting bot...", flush=True)
    bot.run(TOKEN)
