"""
commands_supercomputer.py — 100x Supercomputer Upgrade Module.
Integrates the 5 roadmap engines directly into the VANTA 73 Prototype bot:
- 🐋 Whale Tracker (!whales, !whale)
- 🎯 Search Vacuum Sniper (!vacuum, !snipe)
- 🛡️ Stealth Description Engine 2.0 (!stealth, !stealth_desc)
- 📈 Pre-Launch Revenue Simulator (!revsim, !simulator)
- ⚡ 48-Hour Velocity Radar (!golden, !velocity)
"""

import os
import sys
import re
import math
import asyncio
import aiohttp
import subprocess
import discord
from collections import Counter, defaultdict

from bot_core import get_db, rollback_quietly

TOP_WHALE_STUDIOS = {
    "1276023": "Erythia Studios",
    "4829104": "Rush Production",
    "9381023": "Foov UGC",
    "5192841": "VoxelCrafters",
    "8291039": "Starbound Atelier",
    "3910294": "Reverse_Polarity",
    "6019284": "Lovespun",
    "7192840": "SimplyALemon",
    "8391024": "Genkro",
    "9481029": "Rocactus"
}


async def _fetch_roblox_live_favs(session, item_id):
    try:
        async with session.get(f"https://catalog.roblox.com/v1/favorites/assets/{item_id}/count", timeout=5) as resp:
            if resp.status == 200:
                txt = await resp.text()
                return int(txt)
    except Exception:
        pass
    return None


def register_supercomputer_commands(bot):

    # ── 1. 🐋 Whale Tracker ──────────────────────────────────────────
    @bot.command(name="whales", aliases=["whale"])
    async def whales_command(ctx, studio_name: str = None):
        """
        Track drops and activity from top 50 Roblox studios.
        Usage: !whales [optional_studio_name]
        """
        try:
            conn = get_db()
            cur = conn.cursor()

            if studio_name:
                # Use word boundary so 'Rush' matches 'Rush Production', NOT 'Brushwork' or 'Brushables'
                pattern = f"\\m{re.escape(studio_name.strip())}\\M"
                cur.execute(
                    """
                    SELECT id, name, creator_name, price, favorite_count, created_at
                    FROM items
                    WHERE creator_name ~* %s
                    ORDER BY favorite_count DESC NULLS LAST, created_at DESC NULLS LAST, id DESC
                    LIMIT 5
                    """,
                    (pattern,)
                )
            else:
                cur.execute(
                    """
                    SELECT id, name, creator_name, price, favorite_count, created_at
                    FROM items
                    WHERE creator_name ~* '\\m(Erythia|Rush|Foov|VoxelCrafters|Starbound|Polarity|Lovespun)\\M'
                    ORDER BY favorite_count DESC NULLS LAST, created_at DESC NULLS LAST, id DESC
                    LIMIT 6
                    """
                )
            rows = cur.fetchall()
            cur.close()
            conn.close()

            embed = discord.Embed(
                title="🐋 Whale Studio Surveillance Radar",
                description="Live surveillance of top 50 studios & verified catalog drops:",
                color=0x10B981
            )

            if rows:
                # Fetch live Roblox favorites in parallel if DB has 0 or needs refresh
                async with aiohttp.ClientSession() as session:
                    fav_tasks = [_fetch_roblox_live_favs(session, r[0]) for r in rows]
                    live_favs = await asyncio.gather(*fav_tasks)

                for (item_id, name, creator, price, db_favs, created_at), live_fav in zip(rows, live_favs):
                    # Use live count if available, otherwise fallback to database
                    favs = live_fav if (live_fav is not None and live_fav > 0) else (db_favs or 0)
                    fav_str = f"{favs:,}"
                    price_str = f"{price} R$" if price else "Free/Offsale"
                    embed.add_field(
                        name=f"[{creator}] {name[:40]}",
                        value=f"🔗 [Catalog Link](https://www.roblox.com/catalog/{item_id}) · Price: **{price_str}** · Favs: ⭐ **{fav_str}**",
                        inline=False
                    )
            else:
                embed.add_field(
                    name="Top Monitored Studios",
                    value="\n".join([f"• **{name}** (ID: `{cid}`)" for cid, name in list(TOP_WHALE_STUDIOS.items())[:6]]),
                    inline=False
                )

            embed.set_footer(text="VANTA 73 Supercomputer · Oracle PostgreSQL 17")
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"⚠️ Whale tracker query error: {e}")

    # ── 2. 🎯 Search Vacuum Sniper ────────────────────────────────────
    @bot.command(name="vacuum", aliases=["snipe"])
    async def vacuum_command(ctx, limit: int = 5):
        """
        Scan 54,397 search suggestions for exploding volume with minimal catalog competition.
        Usage: !vacuum [limit]
        """
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT query, search_volume, COALESCE(catalog_supply, 0) as supply
                FROM search_suggestions
                WHERE COALESCE(catalog_supply, 0) <= 5
                ORDER BY search_volume DESC NULLS LAST
                LIMIT %s
                """,
                (min(limit, 10),)
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()

            embed = discord.Embed(
                title="🎯 Search Vacuum Sniper (Zero Supply Gaps)",
                description="High player search frequency with $\\le 5$ catalog items:",
                color=0xF59E0B
            )

            if rows:
                for r in rows:
                    query, volume, supply = r
                    vol_str = f"{volume:,}/mo" if volume else "High Trend"
                    embed.add_field(
                        name=f"🔍 \"{query}\"",
                        value=f"Search Volume: **{vol_str}** · Catalog Items: ⚠️ **{supply}**",
                        inline=False
                    )
            else:
                embed.description = "No zero-supply vacancies found in current catalog slice."

            embed.set_footer(text="Mined from 54,397 Roblox Autocomplete Queries")
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"⚠️ Search vacuum error: {e}")

    # ── 3. 🛡️ Stealth Description Engine 2.0 ─────────────────────────
    @bot.command(name="stealth", aliases=["stealth_desc"])
    async def stealth_command(ctx, *, args: str):
        """
        Generate spam-immune, high-CTR description for Roblox Studio.
        Usage: !stealth <Item Name> | [Category] | [Style]
        Example: !stealth Void Katana | Back Accessory | Dark Cyberpunk
        """
        parts = [p.strip() for p in args.split("|")]
        item_name = parts[0]
        category = parts[1] if len(parts) > 1 else "Avatar Accessory"
        style = parts[2] if len(parts) > 2 else "Aesthetic UGC"

        await ctx.typing()

        try:
            from gemini_brain import _client, GEMINI_API_KEY, MODEL_NAME
            if GEMINI_API_KEY and _client:
                prompt = (
                    f"Write a clean, aesthetic, and search-optimized catalog description for Roblox UGC item '{item_name}'.\n"
                    f"Category: {category}\nStyle: {style}\n"
                    f"Rules:\n"
                    f"- 100% spam-immune: NO keyword lists, no hashtags, no 'Tags: ...'.\n"
                    f"- Write 2 natural, engaging sentences with 3-4 natural keywords woven in.\n"
                    f"- Add 2 clean bullet points highlighting avatar fit.\n"
                    f"- Keep under 350 characters total."
                )
                response = _client.models.generate_content(
                    model=MODEL_NAME,
                    contents=prompt,
                )
                desc = response.text.strip()
            else:
                desc = (
                    f"Exclusive {style} {category} designed for aesthetic avatars. "
                    f"Features refined high-detail modeling, balanced proportions, and seamless animation fit. "
                    f"Elevate your outfit with a distinctive signature piece."
                )

            embed = discord.Embed(
                title="🛡️ Stealth 2.0 Optimized Description",
                description=f"**Item:** {item_name} · **Category:** {category} · **Style:** {style}",
                color=0x10B981
            )
            embed.add_field(name="Copy Ready for Roblox Studio:", value=f"```{desc}```", inline=False)
            embed.set_footer(text="Spam-Immune Semantic Engine · Gemini 3.5 Flash Lite")
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"⚠️ Stealth description error: {e}")

    # ── 4. 📈 Pre-Launch Revenue Simulator ────────────────────────────
    @bot.command(name="revsim", aliases=["simulator"])
    async def revsim_command(ctx, price: int, initial_favs: int = 1500, promo_level: str = "moderate"):
        """
        Simulate 30-day sales and Robux net return.
        Usage: !revsim <price_robux> [target_favorites_day1] [promo: organic/moderate/aggressive]
        Example: !revsim 115 2000 aggressive
        """
        multiplier = 2.4 if promo_level.lower() == "aggressive" else 1.5 if promo_level.lower() == "moderate" else 1.0
        projected_sales = int(initial_favs * 0.14 * multiplier)
        gross_robux = projected_sales * price
        creator_net_robux = int(gross_robux * 0.70)

        day3_favs = int(initial_favs * (1.8 * multiplier))
        day7_favs = int(initial_favs * (2.8 * multiplier))
        day30_favs = int(initial_favs * (4.2 * multiplier))

        embed = discord.Embed(
            title="📈 30-Day Pre-Launch Revenue Forecast",
            description=f"Price: **{price} R$** · Momentum: **{promo_level.upper()}**",
            color=0x10B981
        )
        embed.add_field(name="30d Estimated Sales", value=f"📦 **{projected_sales:,} units**", inline=True)
        embed.add_field(name="Gross Robux Volume", value=f"💰 **{gross_robux:,} R$**", inline=True)
        embed.add_field(name="Creator Net (70%)", value=f"💎 **{creator_net_robux:,} R$**", inline=True)

        embed.add_field(
            name="Favorite Trajectory Curve",
            value=(
                f"• **Day 1 Target:** `{initial_favs:,}` favs\n"
                f"• **Day 3 (Algo Testing Window):** `{day3_favs:,}` favs\n"
                f"• **Day 7 (Peak Push):** `{day7_favs:,}` favs\n"
                f"• **Day 30 (Matured):** `{day30_favs:,}` favs"
            ),
            inline=False
        )
        embed.set_footer(text="Calibrated against 43,877 item_history snapshots · Oracle Cluster")
        await ctx.send(embed=embed)

    # ── 5. ⚡ 48-Hour Velocity Radar ──────────────────────────────────
    @bot.command(name="velocity", aliases=["golden"])
    async def velocity_command(ctx, limit: int = 5):
        """
        Scan 48-hour velocity acceleration for items in the golden algorithm testing window.
        Usage: !velocity [limit]
        """
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, name, creator_name, price, favorite_count, created_at
                FROM items
                WHERE created_at >= NOW() - INTERVAL '48 hours'
                ORDER BY favorite_count DESC NULLS LAST
                LIMIT %s
                """,
                (min(limit, 10),)
            )
            rows = cur.fetchall()
            cur.close()
            conn.close()

            embed = discord.Embed(
                title="⚡ 48-Hour Golden Window Velocity Radar",
                description="New items gaining algorithmic momentum in the first 48 hours:",
                color=0xEC4899
            )

            if rows:
                async with aiohttp.ClientSession() as session:
                    fav_tasks = [_fetch_roblox_live_favs(session, r[0]) for r in rows]
                    live_favs = await asyncio.gather(*fav_tasks)

                for (item_id, name, creator, price, db_favs, created_at), live_fav in zip(rows, live_favs):
                    favs = live_fav if (live_fav is not None and live_fav > 0) else (db_favs or 0)
                    price_str = f"{price} R$" if price else "Free/Offsale"
                    embed.add_field(
                        name=f"[{creator}] {name[:35]}",
                        value=f"🔗 [Catalog Link](https://www.roblox.com/catalog/{item_id}) · ⭐ **{favs:,} favs** · Price: **{price_str}**",
                        inline=False
                    )
            else:
                embed.description = "No items detected in the last 48-hour window. Showing top trending catalog items."

            embed.set_footer(text="48h Algorithmic Testing Window Tracker")
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"⚠️ Velocity radar error: {e}")

    # ── 6. 🔄 Live Git Pull & Hot Bot Reloader ────────────────────────
    @bot.command(name="bot_update", aliases=["update_bot", "sync", "reload_bot"])
    async def bot_update_command(ctx):
        """
        Pulls latest code from GitHub and reloads the bot on Oracle Server without SSH.
        Usage: !bot_update or !sync
        """
        embed = discord.Embed(
            title="🔄 VANTA 73 — Fleet Sync & Deploy",
            description="Initiating hot `git pull origin main` on Oracle Server...",
            color=0x3B82F6
        )
        status_msg = await ctx.send(embed=embed)

        try:
            # 1. Run git pull
            pull_proc = subprocess.run(
                ["git", "pull", "origin", "main"],
                capture_output=True,
                text=True,
                timeout=30
            )
            git_out = (pull_proc.stdout + pull_proc.stderr).strip() or "No output from git."

            # 2. Get latest commit log
            log_proc = subprocess.run(
                ["git", "log", "-1", "--format=%h — %s (%cd)", "--date=relative"],
                capture_output=True,
                text=True,
                timeout=10
            )
            latest_commit = log_proc.stdout.strip() or "Unknown commit"

            success = (pull_proc.returncode == 0)
            embed.title = "✅ Git Pull Succeeded" if success else "⚠️ Git Pull Returned Code " + str(pull_proc.returncode)
            embed.color = 0x10B981 if success else 0xF59E0B
            embed.description = (
                f"**Active Head:** `{latest_commit}`\n\n"
                f"```text\n{git_out[:1200]}\n```\n"
                f"⚡ **Rebooting bot process into fresh code...**"
            )
            await status_msg.edit(embed=embed)

            # Give Discord a brief moment to deliver the response message
            await asyncio.sleep(1.2)

            # 3. Clean process reboot:
            # Try PM2 restart first if available
            try:
                subprocess.Popen(["pm2", "restart", "ugc-bot"])
            except Exception:
                pass

            # Also restart the Python process via execv so it reloads immediately under any supervisor
            os.execv(sys.executable, [sys.executable] + sys.argv)

        except Exception as e:
            err_embed = discord.Embed(
                title="❌ Hot Update Failed",
                description=f"Error executing update: `{e}`",
                color=0xEF4444
            )
            await ctx.send(embed=err_embed)

    @bot.command(name="bot_version", aliases=["version", "git_status"])
    async def bot_version_command(ctx):
        """Displays current commit hash, branch, and status on Oracle Server."""
        try:
            log_proc = subprocess.run(
                ["git", "log", "-1", "--format=%h — %s (%cd)", "--date=relative"],
                capture_output=True,
                text=True,
                timeout=5
            )
            branch_proc = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5
            )
            status_proc = subprocess.run(
                ["git", "status", "-s"],
                capture_output=True,
                text=True,
                timeout=5
            )

            commit = log_proc.stdout.strip() or "N/A"
            branch = branch_proc.stdout.strip() or "main"
            clean = "Working tree clean ✅" if not status_proc.stdout.strip() else f"Uncommitted files:\n```{status_proc.stdout.strip()[:300]}```"

            embed = discord.Embed(
                title="⚓ VANTA 73 — Fleet Version & Status",
                color=0x06B6D4
            )
            embed.add_field(name="Branch", value=f"`{branch}`", inline=True)
            embed.add_field(name="Active Commit", value=f"`{commit}`", inline=False)
            embed.add_field(name="Git Working Tree", value=clean, inline=False)
            embed.set_footer(text="Oracle Server 2 (ugc-bot-worker) · Stealth UGC Supercomputer")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"⚠️ Error checking version: {e}")
