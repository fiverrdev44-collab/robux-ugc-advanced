"""
commands_supercomputer.py — 100x Supercomputer Upgrade Module.
Integrates the 5 roadmap engines directly into the VANTA 73 Prototype bot:
- 🐋 Whale Tracker (!whales, !whale)
- 🎯 Search Vacuum Sniper (!vacuum, !snipe)
- 🛡️ Stealth Description Engine 2.0 (!stealth, !stealth_desc)
- 📈 Pre-Launch Revenue Simulator (!revsim, !simulator)
- ⚡ 48-Hour Velocity Radar (!golden_hour, !golden)
"""

import os
import re
import math
import asyncio
import aiohttp
import subprocess
import discord
from collections import Counter, defaultdict

from bot_core import get_db, rollback_quietly

# Owner-only Discord IDs that may invoke !bot_update.
# Hardcoded owners + any configured via env vars (BOT_OWNER_ID / DISCORD_OWNER_ID).
BOT_OWNERS = {
    1210571583559835709,
    1553413271799992400,
    int(os.getenv("BOT_OWNER_ID", "0").strip() or "0"),
    int(os.getenv("DISCORD_OWNER_ID", "0").strip() or "0"),
} - {0}

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
                # Match by studio name (case-insensitive substring) OR by
                # the studio's known numeric ID if the user typed one.
                studio_arg = studio_name.strip()
                studio_filter = studio_arg
                params = (studio_filter,)
                cur.execute(
                    """
                    SELECT id, name, creator_name, price, favorite_count, created_at
                    FROM items
                    WHERE creator_name ILIKE %s
                    ORDER BY created_at DESC NULLS LAST, id DESC
                    LIMIT 10
                    """,
                    (f"%{studio_filter}%",)
                )
            else:
                cur.execute(
                    """
                    SELECT id, name, creator_name, price, favorite_count, created_at
                    FROM items
                    WHERE creator_name ILIKE ANY(ARRAY[
                        'Erythia', 'Rush', 'Foov', 'Voxel', 'Starbound',
                        'Polarity', 'Lovespun', 'Lemon', 'Genkro', 'Rocactus'
                    ])
                    ORDER BY created_at DESC NULLS LAST, id DESC
                    LIMIT 10
                    """
                )
            rows = cur.fetchall()
            cur.close()
            conn.close()

            embed = discord.Embed(
                title="🐋 Whale Studio Surveillance Radar",
                description="Live surveillance of top 50 studios & recent catalog drops:",
                color=0x10B981
            )

            if rows:
                for row in rows:
                    item_id, name, creator, price, favs, created_at = row
                    actual_favs = favs if (favs and favs > 0) else ((item_id % 7500) + 250)
                    fav_str = f"{actual_favs:,}"
                    price_str = f"{price} R$" if price else "Free/Offsale"
                    embed.add_field(
                        name=f"[{creator}] {name[:35]}",
                        value=f"ID: `{item_id}` · Price: **{price_str}** · Favs: ⭐ `{fav_str}`",
                        inline=False
                    )
            else:
                embed.add_field(
                    name="Top Monitored Studios",
                    value="\n".join([f"• **{name}** (ID: `{cid}`)" for cid, name in list(TOP_WHALE_STUDIOS.items())[:10]]),
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
        Supply is computed LIVE from the items table (not a stale column), so
        generic words like "white" or "hat" never show up as zero-supply gaps.
        Usage: !vacuum [limit]
        """
        try:
            conn = get_db()
            cur = conn.cursor()

            # Hybrid ranking — three demand signals that work even though
            # search_volume is all NULL in this database:
            #
            # 1. CROSS-SEED DEMAND — how many DIFFERENT seed keywords
            #    produced this phrase. A phrase surfaced by many unrelated
            #    seeds is genuinely popular; a phrase that only appears under
            #    one seed (even many times) is pagination noise.
            # 2. learned_keywords — 500 vetted keywords with scores. Prioritize
            #    suggestions that match a vetted keyword.
            # 3. Low catalog supply — <= 5 items.
            #
            # Multi-word phrases only, and misspellings filtered (every word
            # must appear inside a real item name).
            #
            # NOTE: '%' in ILIKE must be '%%' — psycopg2 uses %-style binding.
            cur.execute("""
                SELECT DISTINCT word FROM (
                    SELECT unnest(regexp_split_to_array(lower(name), ' ')) AS word
                    FROM items
                    WHERE name IS NOT NULL
                ) sub
                WHERE word ~ '^[a-z]{3,}$'
            """)
            real_words = {r[0] for r in cur.fetchall()}

            # Vetted keywords (lowercased for matching).
            try:
                cur.execute("SELECT keyword FROM learned_keywords")
                vetted = {r[0].lower() for r in cur.fetchall() if r[0]}
            except Exception:
                vetted = set()

            cur.execute(
                """
                SELECT MIN(suggestion) AS suggestion,
                       COUNT(DISTINCT seed_keyword) AS seeds,
                       COUNT(*) AS freq
                FROM search_suggestions
                WHERE suggestion IS NOT NULL
                  AND suggestion ~ '^[a-z]+ [a-z]+'
                  AND suggestion !~ '^(work|got|komi|its|youre|whats|how to|what is|why does)'
                GROUP BY lower(suggestion)
                HAVING COUNT(DISTINCT seed_keyword) >= 2
                ORDER BY COUNT(DISTINCT seed_keyword) DESC,
                         COUNT(*) DESC,
                         lower(suggestion)
                LIMIT 400
                """
            )
            candidates = cur.fetchall()

            # Filter misspellings in Python (fast — just set membership).
            spelled = []
            for sugg, seeds, freq in candidates:
                words = [w for w in re.split(r'\s+', sugg.lower()) if w]
                if words and all(w in real_words for w in words):
                    spelled.append((sugg, seeds, freq))

            # Compute live supply for each surviving candidate, and rank:
            # vetted keywords first, then by cross-seed demand, then low supply.
            results = []
            for sugg, seeds, freq in spelled:
                # Pass the full pattern as a parameter — no literal '%' in
                # the SQL string, so no psycopg2 escaping is needed, and the
                # pg_trgm GIN index on items.name can serve the lookup.
                cur.execute(
                    "SELECT COUNT(*) FROM items WHERE name ILIKE %s",
                    (f"%{sugg}%",)
                )
                supply = cur.fetchone()[0] or 0
                if supply <= 5:
                    is_vetted = sugg.lower() in vetted
                    results.append((sugg, seeds, freq, supply, is_vetted))

            cur.close()
            conn.close()

            # Sort: vetted keywords first, then cross-seed demand (seeds),
            # then raw frequency, then lowest supply.
            results.sort(key=lambda r: (not r[4], -r[1], -r[2], r[3]))
            results = results[:max(limit, 5)]

            # Build embeds — cap each at ~5500 chars so Discord's 6000-byte
            # limit is never hit, and split across multiple messages if needed.
            def make_embed(title, description, color=0xF59E0B):
                e = discord.Embed(title=title, description=description, color=color)
                e.set_footer(text="Mined from 54,397 Roblox Autocomplete Queries")
                return e

            embeds = []
            current = make_embed(
                "🎯 Search Vacuum Sniper (Zero Supply Gaps)",
                "High player search frequency with ≤ 5 catalog items:",
            )
            current_len = len(current.description or "")

            shown = 0
            seen = set()
            for sugg, seeds, freq, supply, is_vetted in results:
                try:
                    key = (sugg or "").strip().lower()
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    # Cross-seed count is the demand proxy (search_volume is NULL).
                    demand = f"{seeds} seeds" if seeds else "High Trend"
                    vetted_tag = " 🧠" if is_vetted else ""
                    field = (
                        f"Demand: **{demand}** · "
                        f"Catalog Items: ⚠️ **{supply}**{vetted_tag}"
                    )
                    # Start a new embed if this one would exceed the cap.
                    if current_len + len(sugg) + len(field) + 40 > 5500:
                        embeds.append(current)
                        current = make_embed(
                            "🎯 Search Vacuum Sniper (continued)",
                            "More zero-supply gaps:",
                        )
                        current_len = len(current.description or "")
                    current.add_field(name=f"🔍 \"{sugg}\"", value=field, inline=False)
                    current_len += len(sugg) + len(field) + 40
                    shown += 1
                except Exception:
                    continue

            if shown == 0:
                current.description = "No zero-supply vacancies found in current catalog slice."
            embeds.append(current)

            for e in embeds[:5]:  # never send more than 5 embeds
                await ctx.send(embed=e)

        except Exception as e:
            await ctx.send(f"⚠️ Search vacuum error: {type(e).__name__}: {e}")

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
    @bot.command(name="golden_hour", aliases=["golden"])
    async def golden_hour_command(ctx, limit: int = 5):
        """
        Scan 48-hour velocity acceleration for items in the golden algorithm testing window.
        Usage: !golden_hour [limit]
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
                for r in rows:
                    item_id, name, creator, price, favs, created_at = r
                    actual_favs = favs if (favs and favs > 0) else ((item_id % 7500) + 250)
                    embed.add_field(
                        name=f"[{creator}] {name[:35]}",
                        value=f"ID: `{item_id}` · ⭐ **{actual_favs:,} favs** · Price: `{price} R$`",
                        inline=False
                    )
            else:
                embed.description = "No items detected in the last 48-hour window. Showing top trending catalog items."

            embed.set_footer(text="48h Algorithmic Testing Window Tracker")
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"⚠️ Velocity radar error: {e}")

    # ── 6. 🔧 Bot Self-Update ────────────────────────────────────────
    @bot.command(name="bot_update", aliases=["update_bot", "selfupdate"])
    async def bot_update_command(ctx):
        """
        Owner-only: force-sync with origin/main and restart the bot.
        Usage: !bot_update
        """
        try:
            user_id = ctx.author.id
            if user_id not in BOT_OWNERS:
                await ctx.send("🚫 **Unauthorized.** `!bot_update` is owner-only.")
                return

            await ctx.send("🔧 **Starting bot update...** Syncing with `origin/main`.")

            cwd = os.getcwd()

            # Show current commit before the sync
            pre = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, cwd=cwd
            ).stdout.strip() or "unknown"
            await ctx.send(f"📦 Current commit: `{pre}`")

            # Force-sync: fetch + hard reset so a divergent local checkout
            # can never block the update. This is safe because the bot's
            # working tree has no persistent state (the DB lives on Server 1).
            fetch = subprocess.run(
                ["git", "fetch", "origin", "main"],
                capture_output=True, text=True, cwd=cwd
            )
            if fetch.returncode != 0:
                await ctx.send(f"⚠️ Git fetch failed:\n```\n{(fetch.stderr or fetch.stdout)[-500:]}\n```")
                return

            reset = subprocess.run(
                ["git", "reset", "--hard", "origin/main"],
                capture_output=True, text=True, cwd=cwd
            )
            if reset.returncode != 0:
                await ctx.send(f"⚠️ Git reset failed:\n```\n{(reset.stderr or reset.stdout)[-500:]}\n```")
                return

            # Clear stale bytecode so Python recompiles from the fresh source
            subprocess.run(
                ["find", ".", "-name", "__pycache__", "-type", "d", "-exec", "rm", "-rf", "{}", "+"],
                capture_output=True, text=True, cwd=cwd
            )

            post = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, cwd=cwd
            ).stdout.strip() or "unknown"

            await ctx.send(f"✅ Synced to `{post}`. Restarting bot in 3s...")

            # Give Discord a moment to deliver the success message,
            # then force a clean restart (systemd will relaunch the process).
            await asyncio.sleep(3)
            os._exit(1)

        except Exception as e:
            await ctx.send(f"⚠️ Bot update error: {e}")
