"""
discord_ugc_bot.py — thin orchestrator.
All commands live in commands_*.py modules.
"""
import os
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


@bot.event
async def on_ready():
    print(f"✅ {bot.user} is online", flush=True)
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


# ── Flask health check for Render ────────────────────────────
app = Flask(__name__)


@app.route('/')
def health():
    return "OK", 200


def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port)


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)
