# TEST PUSH LOG MARKER 2026
print("[UGC Bot] 🚀 TEST PUSH LIVE UPDATE SUCCESSFUL!")
"""
discord_ugc_bot.py — thin orchestrator.
All commands live in commands_*.py modules.

Includes:
- Discord health check (returns 503 when bot is dead)
- Watchdog thread (uses bot.latency + os._exit(1) to force Render restart)
- Background scheduler (daily snapshot + ML train + daily report)
- Sales listener (reads Roblox sale webhook embeds from SALES_CHANNEL_ID)
- Main event loop captured in on_ready → exposed as _main_loop for scheduler

FIXES:
- Captures bot's running loop in on_ready (bot.loop doesn't exist in d.py 2.x)
- Removed bot.run() retry loop — single attempt + os._exit(1) for clean restart
"""
import os
import time
import asyncio
import threading
import discord
from discord.ext import commands
from flask import Flask, request

from bot_core import get_db, ASSET_TYPE_NAMES
from commands_guide import register_guide_commands
from commands_market import register_market_commands
from commands_ai import register_ai_commands

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

_boot_done = False
_main_loop = None   # captured in on_ready — scheduler uses this


@bot.event
async def on_ready():
    global _boot_done, _main_loop

    # Capture the bot's running event loop for the scheduler
    if _main_loop is None:
        try:
            _main_loop = asyncio.get_running_loop()
            print("🔗 Main event loop captured for scheduler.", flush=True)
        except Exception as e:
            print(f"⚠️ Failed to capture main loop: {e}", flush=True)

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


@bot.event
async def on_message(message):
    """Listen for sale embeds + process commands."""
    if message.author.id == bot.user.id:
        return

    sales_ch_id = os.getenv("SALES_CHANNEL_ID", "").strip()
    if sales_ch_id and str(message.channel.id) == sales_ch_id:
        try:
            from sales_listener import handle_sale_message
            await handle_sale_message(message)
        except Exception as e:
            print(f"[on_message] sales handler failed: {e}", flush=True)

    await bot.process_commands(message)


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

# ── 💰 Sales commands + listener ─────────────────────────────
try:
    from commands_sales import register_sales_commands
    register_sales_commands(bot, get_db)
    print("✅ Sales commands loaded.", flush=True)
except Exception as e:
    print(f"⚠️ Sales commands failed to load: {e}", flush=True)

# ── 🩻 X-Ray / Patterns / Failures ───────────────────────────
try:
    from commands_xray import register_xray_commands
    register_xray_commands(bot, get_db)
    print("✅ X-Ray commands loaded.", flush=True)
except Exception as e:
    print(f"⚠️ X-Ray commands failed to load: {e}", flush=True)

# ── 🚀 Supercomputer 100x Upgrade Commands ───────────────────
try:
    from commands_supercomputer import register_supercomputer_commands
    register_supercomputer_commands(bot)
    print("✅ Supercomputer commands loaded.", flush=True)
except Exception as e:
    print(f"⚠️ Supercomputer commands failed to load: {e}", flush=True)



# ── Start background scheduler ───────────────────────────────
try:
    from scheduler import start_scheduler
    start_scheduler()
except Exception as e:
    print(f"⚠️ [scheduler] Failed to start: {e}", flush=True)


# ── Flask health check + report trigger for Render ───────────
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


@app.route('/trigger-report', methods=['POST'])
def trigger_report():
    """
    External trigger for the daily sales report.
    Auth via X-Trigger-Token header.
    Used by GitHub Actions backup cron so the report fires even
    if Render restarts near 18:00 UTC.
    """
    expected = os.getenv("TRIGGER_TOKEN", "").strip()
    if not expected:
        return "TRIGGER_TOKEN not set", 500
    provided = request.headers.get("X-Trigger-Token", "").strip()
    if provided != expected:
        return "Unauthorized", 401

    try:
        from scheduler import _run_post_monitor
        _run_post_monitor()
        return "OK", 200
    except Exception as e:
        return f"Error: {e}", 500


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
    try:
        bot.run(TOKEN)
    except Exception as e:
        print(f"❌ bot.run() failed: {type(e).__name__}: {e}", flush=True)
        print("⏳ Exiting for Render restart in 30s...", flush=True)
        time.sleep(30)
        os._exit(1)
