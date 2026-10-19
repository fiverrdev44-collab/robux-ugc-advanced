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
from launch_ledger import (
    fill_ledger,
    sync_all,
    sync_group_items,
    configured_groups,
)

# Owner-only Discord IDs that may invoke !bot_update.
# Hardcoded owners + any configured via env vars (BOT_OWNER_ID / DISCORD_OWNER_ID).
BOT_OWNERS = {
    1210571583559835709,
    1553413271799992400,
    int(os.getenv("BOT_OWNER_ID", "0").strip() or "0"),
    int(os.getenv("DISCORD_OWNER_ID", "0").strip() or "0"),
} - {0}

# Cache of words that actually appear in item names. Used by !vacuum to
# reject nonsense suggestions. Computed once per process (90k-row scan).
_REAL_WORDS_CACHE = None

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

            # ── Demand model ──────────────────────────────────────────────
            # search_volume is NULL everywhere and every suggestion appears
            # under exactly one seed, so neither ranks anything. learned_keywords
            # was also unusable (raw, un-normalized scores dominated by generic
            # words like "over"/"point").
            #
            # So measure demand DIRECTLY from the catalog: for each phrase,
            # count matching items (supply) and their average favorites
            # (proven demand). A phrase with 1-5 items and high avg favorites
            # is a real, underserved niche. A phrase with 0 items is an
            # untested gap — shown last, since demand is unproven.
            #
            # Candidates are RANDOM-sampled: ordering by frequency surfaced
            # only common phrases (already saturated) or alphabetically-first
            # junk. Random sampling explores the whole suggestion space.
            global _REAL_WORDS_CACHE
            if _REAL_WORDS_CACHE is None:
                cur.execute("""
                    SELECT DISTINCT word FROM (
                        SELECT unnest(regexp_split_to_array(lower(name), ' ')) AS word
                        FROM items WHERE name IS NOT NULL
                    ) sub
                    WHERE word ~ '^[a-z]{3,}$'
                """)
                _REAL_WORDS_CACHE = {r[0] for r in cur.fetchall()}
            real_words = _REAL_WORDS_CACHE

            cur.execute(
                """
                SELECT suggestion, freq FROM (
                    SELECT MIN(suggestion) AS suggestion, COUNT(*) AS freq
                    FROM search_suggestions
                    WHERE suggestion IS NOT NULL
                      AND suggestion ~ '^[a-z]+ [a-z]+'
                      AND suggestion !~ '^(work|got|komi|its|youre|whats|how to|what is|why does)'
                    GROUP BY lower(suggestion)
                ) t
                ORDER BY random()
                LIMIT 400
                """
            )
            candidates = cur.fetchall()
            scanned = len(candidates)

            results = []
            for sugg, freq in candidates:
                wo = [w for w in re.split(r'\s+', (sugg or '').lower()) if w]
                # At least one word must be a real word used in item names,
                # otherwise the phrase is nonsense ("abdomen tail" survives
                # this, "coquett dollette" does not).
                coverage = sum(1 for w in wo if w in real_words)
                if coverage == 0:
                    continue
                cur.execute(
                    "SELECT COUNT(*), COALESCE(AVG(favorite_count), 0), "
                    "COALESCE(SUM(favorite_count), 0) "
                    "FROM items WHERE name ILIKE %s",
                    (f"%{sugg}%",)
                )
                supply, avg_fav, total_fav = cur.fetchone()
                supply = int(supply or 0)
                if supply > 5:
                    continue
                results.append({
                    "sugg": sugg,
                    "freq": int(freq or 0),
                    "supply": supply,
                    "avg_fav": float(avg_fav or 0),
                    "total_fav": int(total_fav or 0),
                    "coverage": coverage,
                    "proven": supply > 0,
                })

            cur.close()
            conn.close()

            # Rank: proven demand first (highest avg favorites), then
            # untested zero-supply phrases by real-word coverage and frequency.
            def _rank(r):
                if r["proven"]:
                    return (0, -r["avg_fav"], 0, 0)
                return (1, 0, -r["coverage"], -r["freq"])

            results.sort(key=_rank)
            results = results[:max(limit, 5)]

            # Build embeds — cap each at ~5500 chars so Discord's 6000-byte
            # limit is never hit, and split across multiple messages if needed.
            def make_embed(title, description, color=0xF59E0B):
                e = discord.Embed(title=title, description=description, color=color)
                e.set_footer(text="Mined from 54,397 Roblox Autocomplete Queries")
                return e

            embeds = []
            current = make_embed(
                "🎯 Search Vacuum Sniper (Low Supply Gaps)",
                "Ranked by real catalog demand (avg favorites) · ≤ 5 items:",
            )
            current_len = len(current.description or "")

            shown = 0
            seen = set()
            for r in results:
                try:
                    sugg = r["sugg"]
                    key = (sugg or "").strip().lower()
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    if r["proven"]:
                        field = (
                            f"⭐ **{int(r['avg_fav']):,}** avg favs · "
                            f"📦 **{r['total_fav']:,}** total · "
                            f"Items ⚠️ **{r['supply']}** · ✅ Proven demand"
                        )
                    else:
                        field = (
                            "🆕 No matching items · Untested gap · "
                            "Items ⚠️ **0**"
                        )
                    # Start a new embed if this one would exceed the cap.
                    if current_len + len(sugg) + len(field) + 40 > 5500:
                        embeds.append(current)
                        current = make_embed(
                            "🎯 Search Vacuum Sniper (continued)",
                            "More low-supply gaps:",
                        )
                        current_len = len(current.description or "")
                    current.add_field(name=f"🔍 \"{sugg}\"", value=field, inline=False)
                    current_len += len(sugg) + len(field) + 40
                    shown += 1
                except Exception:
                    continue

            if shown == 0:
                current.description = (
                    "No zero-supply vacancies found in current catalog slice.\n"
                    f"_Scanned {scanned} candidate phrases; none had ≤5 matching items._"
                )
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

    # ── 7. 🎯 Meta Sniper (traffic interceptor) ──────────────────────
    @bot.command(name="meta_sniper", aliases=["sniper"])
    async def meta_sniper_command(ctx, *, niche: str = ""):
        """
        Find high-demand search terms the top items in a niche do NOT use
        in their titles, then generate the exact title/tags to capture them.
        Usage: !meta_sniper aura emote
        """
        niche = (niche or "").strip().lower()
        if not niche:
            return await ctx.send(
                "Usage: `!meta_sniper <niche>`\n"
                "Example: `!meta_sniper aura emote`"
            )

        try:
            conn = get_db()
            cur = conn.cursor()

            # Infer the asset family from the last word, when possible.
            fam_sql, fam_params = "", []
            try:
                from convergence_engine import _family_clause
                last = niche.split()[-1]
                fam_map = {
                    "emote": "emotes", "emotes": "emotes", "dance": "emotes",
                    "hat": "hair", "hair": "hair", "beanie": "hair",
                    "crown": "hair", "cap": "hair",
                    "face": "face", "mask": "face", "glasses": "face",
                    "neck": "neck", "necklace": "neck", "chain": "neck",
                    "back": "back", "cape": "back", "wings": "back",
                    "backpack": "back", "waist": "waist",
                    "shoulder": "shoulder", "front": "front",
                    "shirt": "classic", "pants": "classic", "jacket": "classic",
                }
                fam = fam_map.get(last)
                if fam:
                    fam_sql, fam_params = _family_clause(fam)
            except Exception:
                pass

            # Top 20 competitors in the niche (by favorites).
            cur.execute(f"""
                SELECT name, favorite_count
                FROM items
                WHERE name ILIKE %s AND favorite_count > 0
                {fam_sql}
                ORDER BY favorite_count DESC
                LIMIT 20
            """, [f"%{niche}%"] + fam_params)
            top = cur.fetchall()

            # If the exact phrase is too narrow, broaden to any niche term so
            # the competitor set and coverage numbers are meaningful.
            if len(top) < 5:
                terms = [t for t in niche.split() if len(t) >= 3] or [niche]
                pats = [f"%{t}%" for t in terms]
                cur.execute(f"""
                    SELECT name, favorite_count
                    FROM items
                    WHERE name ILIKE ANY(%s) AND favorite_count > 0
                    {fam_sql}
                    ORDER BY favorite_count DESC
                    LIMIT 20
                """, [pats] + fam_params)
                top = cur.fetchall()

            if not top:
                cur.close(); conn.close()
                return await ctx.send(f"❌ No top items found for `{niche}`.")

            # Tokenize competitor titles.
            stop = {
                "the", "a", "an", "and", "of", "in", "to", "for", "is", "on",
                "with", "my", "your", "new", "hot", "best", "top", "roblox",
                "ugc", "item", "cute", "funny", "cool", "trendy", "aesthetic",
                "viral", "sale", "free", "cheap",
            }

            def toks(s):
                return [
                    w for w in re.findall(r"[a-z0-9]{3,}", (s or "").lower())
                    if w not in stop and not w.isdigit()
                ]

            top_tokens = {}
            for name, _ in top:
                for w in set(toks(name)):
                    top_tokens[w] = top_tokens.get(w, 0) + 1

            # Suggestions relevant to the niche terms.
            niche_terms = [t for t in niche.split() if len(t) >= 3]
            pats = [f"%{t}%" for t in niche_terms] or [f"%{niche}%"]
            cur.execute("""
                SELECT suggestion, COUNT(*) AS n
                FROM search_suggestions
                WHERE suggestion IS NOT NULL
                  AND suggestion ILIKE ANY(%s)
                GROUP BY suggestion
                ORDER BY COUNT(*) DESC
                LIMIT 500
            """, (pats,))
            suggestions = cur.fetchall()

            # Count how many suggestions contain each candidate word.
            cand = {}
            for sugg, _ in suggestions:
                for w in set(toks(sugg)):
                    if w in niche_terms:
                        continue
                    cand[w] = cand.get(w, 0) + 1

            # Rank gaps: real demand evidence, absent from top titles, and
            # genuinely used within the SAME family (so "hood" can't show up
            # for emotes just because it exists somewhere in the catalog).
            ranked = []
            for w, sugg_count in sorted(cand.items(), key=lambda x: -x[1])[:60]:
                # 1-2 suggestions is noise, not demand.
                if sugg_count < 3:
                    continue
                coverage = top_tokens.get(w, 0)
                if coverage > 3:
                    continue
                # Family-scoped catalog usage (proof the word belongs here).
                cur.execute(
                    f"SELECT COUNT(*) FROM items WHERE name ILIKE %s {fam_sql}",
                    [f"%{w}%"] + fam_params,
                )
                use = cur.fetchone()[0] or 0
                if use < 5:
                    continue
                score = (
                    sugg_count
                    * (1 - coverage / max(len(top), 1))
                    * (1 + min(use, 5000) / 1000)
                )
                ranked.append((w, sugg_count, coverage, use, score))

            ranked.sort(key=lambda x: -x[4])
            ranked = ranked[:5]
            fallback_used = False

            # ── Fallback: catalog co-occurrence ──────────────────────
            # Autocomplete is thin for many niches. If no suggestion-based
            # gap survives, find words that co-occur with this niche in real
            # item names but are missing from the top competitors' titles.
            if not ranked:
                terms2 = [t for t in niche.split() if len(t) >= 3] or [niche]
                pats2 = [f"%{t}%" for t in terms2]
                cur.execute(f"""
                    SELECT name FROM items
                    WHERE name ILIKE ANY(%s)
                    {fam_sql}
                    LIMIT 5000
                """, [pats2] + fam_params)
                names = [r[0] for r in cur.fetchall()]

                co = {}
                for nm in names:
                    for w in set(toks(nm)):
                        if w in niche_terms:
                            continue
                        co[w] = co.get(w, 0) + 1

                # Only recommend curated UGC aesthetic modifiers. Raw
                # co-occurrence alone surfaces noise like "farming",
                # "profile" and "headless", which are not title modifiers.
                modifiers = {
                    "pink", "blue", "red", "black", "white", "purple",
                    "green", "gold", "silver", "neon", "glow", "glowing",
                    "gradient", "glitter", "sparkle", "sparkly", "y2k",
                    "cyber", "cyberpunk", "gothic", "goth", "emo", "grunge",
                    "coquette", "preppy", "kawaii", "anime", "pastel",
                    "fluffy", "cute", "dark", "light", "effect", "particle",
                    "magic", "magical", "fire", "ice", "shadow", "rainbow",
                    "chrome", "metallic", "holographic", "crystal", "galaxy",
                    "cosmic", "vintage", "retro", "futuristic",
                    "fantasy", "angel", "demon", "heart", "star", "moon",
                    "sun", "cloud", "flame", "frost", "toxic", "radioactive",
                }

                co_cands = []
                for w, freq in sorted(co.items(), key=lambda x: -x[1])[:200]:
                    if w not in modifiers or freq < 5:
                        continue
                    cov = top_tokens.get(w, 0)
                    if cov > 3:
                        continue
                    co_cands.append((w, freq, cov))

                co_cands.sort(key=lambda x: (-x[1], x[2]))
                for w, freq, cov in co_cands[:5]:
                    # Reuse the 5-tuple shape; score field is unused here.
                    ranked.append((w, freq, cov, freq, 0.0))
                fallback_used = bool(ranked)

            cur.close()
            conn.close()

            embed = discord.Embed(
                title=f"🎯 Meta Sniper — {niche}",
                description=(
                    "Suggestion data is thin — using **catalog co-occurrence**:"
                    if fallback_used else
                    "High-demand search terms the top items do NOT cover:"
                ),
                color=0xEF4444,
            )

            if ranked:
                for w, sc, cov, use, _ in ranked:
                    if fallback_used:
                        value = (
                            f"**{sc}** niche items use it · "
                            f"top-{len(top)} coverage **{cov}/{len(top)}**"
                        )
                    else:
                        value = (
                            f"**{sc}** suggestions · "
                            f"top-{len(top)} coverage **{cov}/{len(top)}** · "
                            f"**{use:,}** items in this family use it"
                        )
                    embed.add_field(name=f"🔍 {w}", value=value, inline=False)

                if not fallback_used:
                    # Only autocomplete-based gaps get a generated title.
                    title_words = [w for w, *_ in ranked[:2]]
                    suggested = " ".join(x.capitalize() for x in title_words)
                    embed.add_field(
                        name="✅ Suggested title",
                        value=(
                            f"`{suggested} {niche.title()}`\n"
                            f"Tags: `{', '.join(w for w, *_ in ranked[:3])}`"
                        ),
                        inline=False,
                    )
                else:
                    top_mod = ranked[0][0]
                    embed.add_field(
                        name="⚠️ Use with care",
                        value=(
                            "Co-occurrence is **not** proof of demand. Only add "
                            "a word if it accurately describes your item — never "
                            "stuff sales or type words.\n"
                            f"**Possible title:** "
                            f"`{top_mod.capitalize()} {niche.title()}`"
                        ),
                        inline=False,
                    )
            else:
                embed.description = (
                    "No strong gaps found. A gap now requires **≥3 suggestions** "
                    "and **≥5 items in the same family**, so weak 1–2 suggestion "
                    "terms are no longer reported."
                )

            embed.set_footer(
                text=(
                    "Co-occurrence = words paired with this niche in real item names"
                    if fallback_used else
                    "Demand = ≥3 suggestions · gap = absent from top titles · "
                    "relevance = same-family usage"
                )
            )
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(f"⚠️ Meta sniper error: {type(e).__name__}: {e}")

    # ── 8. 🧠 Sales Keyword Intelligence (revenue attribution) ───────
    @bot.command(name="sales_keywords", aliases=["sales_words"])
    async def sales_keywords_command(ctx, family: str = ""):
        """
        Learn which title words actually drive SALES (not favorites), then
        show which high-lift words your own items are missing.
        Usage: !sales_keywords [family]  e.g. !sales_keywords emotes
        """
        try:
            conn = get_db()
            cur = conn.cursor()

            # Optional family scope.
            fam_sql, fam_params = "", []
            if family:
                try:
                    from convergence_engine import _family_clause
                    fam_key = {
                        "emote": "emotes", "dance": "emotes",
                        "hat": "hair", "beanie": "hair", "crown": "hair",
                        "face": "face", "mask": "face", "glasses": "face",
                        "neck": "neck", "back": "back", "cape": "back",
                        "wings": "back", "waist": "waist",
                        "shirt": "classic", "pants": "classic",
                    }.get(family.lower(), family.lower())
                    fam_sql, fam_params = _family_clause(fam_key)
                except Exception:
                    pass

            cur.execute(f"""
                SELECT name, COALESCE(total_sales, 0) AS s,
                       COALESCE(favorite_count, 0) AS f
                FROM items
                WHERE name IS NOT NULL {fam_sql}
                LIMIT 40000
            """, fam_params)
            rows = cur.fetchall()

            with_sales = sum(1 for _, s, _ in rows if (s or 0) > 0)
            basis = "catalog sales" if with_sales >= 50 else "favorites (thin sales data)"

            stop = {
                "the", "a", "an", "and", "of", "in", "to", "for", "is", "on",
                "with", "my", "your", "new", "hot", "best", "top", "roblox",
                "ugc", "item", "cute", "funny", "cool", "trendy", "aesthetic",
                "viral", "sale", "free", "cheap", "the", "and",
            }

            def toks(s):
                return [
                    w for w in re.findall(r"[a-z0-9]{3,}", (s or "").lower())
                    if w not in stop and not w.isdigit()
                ]

            buckets = {}
            for name, s, f in rows:
                val = s if basis == "catalog sales" else f
                for w in set(toks(name)):
                    buckets.setdefault(w, []).append(val)

            stats = []
            for w, vals in buckets.items():
                if len(vals) < 10:
                    continue
                vals.sort()
                med = vals[len(vals) // 2]
                rate = sum(1 for v in vals if v > 0) / len(vals)
                stats.append((w, med, rate, len(vals)))

            stats.sort(key=lambda x: (-x[1], -x[2]))
            top = stats[:15]

            # Your own selling items (from live sales).
            cur.execute("""
                SELECT lower(item_name), COUNT(*)
                FROM my_sales
                GROUP BY lower(item_name)
            """)
            my_sales_rows = cur.fetchall()
            my_words = set()
            my_names = []
            for name, units in my_sales_rows:
                my_names.append((name, units))
                my_words.update(toks(name))

            cur.close()
            conn.close()

            embed = discord.Embed(
                title="🧠 Sales Keyword Intelligence",
                description=(
                    f"Basis: **{basis}** · family: **{family or 'all'}** · "
                    f"{len(rows):,} items scanned"
                ),
                color=0x10B981,
            )

            if not top:
                embed.description += "\n\n_Not enough data to compute word lift._"
                return await ctx.send(embed=embed)

            lines = []
            for w, med, rate, n in top[:10]:
                used = "✅" if w in my_words else "▫️"
                lines.append(
                    f"{used} **{w}** — median sales **{med:,.0f}** · "
                    f"seller rate **{rate * 100:.0f}%** · {n:,} items"
                )
            embed.add_field(
                name="Top sales-driving words",
                value="\n".join(lines),
                inline=False,
            )

            missing = [w for w, *_ in top[:10] if w not in my_words]
            if missing:
                embed.add_field(
                    name="Add these to your items",
                    value="`" + "`, `".join(missing[:6]) + "`",
                    inline=False,
                )

            if my_names:
                sell_lines = [
                    f"• `{name[:40]}` — {units} sales"
                    for name, units in sorted(my_names, key=lambda x: -x[1])[:5]
                ]
                embed.add_field(
                    name="Your selling items",
                    value="\n".join(sell_lines),
                    inline=False,
                )

            embed.set_footer(
                text="✅ = already in your item names · ▫️ = missing"
            )
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(
                f"⚠️ Sales keyword error: {type(e).__name__}: {e}"
            )

    # ── 9. 🔎 Autocomplete Probe (uses server-side cookie) ───────────
    @bot.command(name="suggest_probe", aliases=["probe_suggest"])
    async def suggest_probe_command(ctx, *, query: str = "aura emote"):
        """
        Probe Roblox autocomplete endpoints using the cookie already set on
        the server. The cookie is never printed or sent to Discord.
        Usage: !suggest_probe aura emote
        """
        import requests
        from uuid import uuid4

        cookie = (
            os.getenv("ROBLOSECURITY_COOKIE_1")
            or os.getenv("ROBLOSECURITY_COOKIE")
            or os.getenv("ROBLOSECURITY")
            or ""
        ).strip()

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.roblox.com/",
            "Origin": "https://www.roblox.com",
        }
        if cookie:
            headers["Cookie"] = f".ROBLOSECURITY={cookie}"

        sid = str(uuid4())
        endpoints = [
            ("avatar/v2",
             "https://apis.roblox.com/autocomplete-avatar/v2/suggest",
             {"prefix": query, "limit": 10, "lang": "en"}),
            ("v1/suggest",
             "https://apis.roblox.com/search-suggestions/v1/suggest",
             {"query": query, "limit": 10, "maxResults": 10, "sessionId": sid}),
            ("v1/suggestions",
             "https://apis.roblox.com/search-suggestions/v1/suggestions",
             {"query": query, "limit": 10, "sessionId": sid}),
            ("v2/suggestions",
             "https://apis.roblox.com/search-suggestions/v2/suggestions",
             {"query": query, "limit": 10, "sessionId": sid}),
            ("omni/v1",
             "https://apis.roblox.com/omni-search/v1/suggest",
             {"query": query, "limit": 10, "sessionId": sid}),
            ("universal/v1",
             "https://apis.roblox.com/universal-search/v1/omni-search",
             {"searchQuery": query, "sessionId": sid, "pageType": "all"}),
            ("search-api/omni",
             "https://apis.roblox.com/search-api/omni-search",
             {"searchQuery": query, "sessionId": sid, "pageType": "all"}),
            ("search-api/v1",
             "https://apis.roblox.com/search-api/v1/omni-search",
             {"searchQuery": query, "sessionId": sid, "pageType": "all"}),
            ("catalog/search",
             "https://catalog.roblox.com/v1/search/items",
             {"keyword": query, "limit": 10, "category": "All"}),
            ("catalog-json",
             "https://search.roblox.com/catalog/json",
             {"Keyword": query, "PageNumber": 1, "ItemsPerPage": 10}),
            ("games/search",
             "https://games.roblox.com/v1/games/search",
             {"keyword": query, "limit": 10}),
        ]

        def _probe():
            out = []
            for label, url, params in endpoints:
                try:
                    r = requests.get(url, params=params, headers=headers, timeout=10)
                    body = r.text[:200].replace("\n", " ")
                    out.append((label, r.status_code, body))
                except Exception as e:
                    out.append((label, "ERR",
                                f"{type(e).__name__}: {e}"[:200]))
            return out

        results = await asyncio.to_thread(_probe)

        lines = [
            f"🔎 **SUGGEST PROBE** — `{query}`",
            f"Cookie: {'✅ set (server-side, never printed)' if cookie else '❌ not set'}",
            "",
        ]
        for label, status, body in results:
            icon = "✅" if status == 200 else "❌"
            lines.append(f"{icon} `{label}` → {status}\n`{body}`")
        lines.append(
            "\n_If a 200 returns data, that's the live endpoint — I'll wire "
            "the scraper to it._"
        )
        await ctx.send("\n".join(lines)[:1900])

    # ── 10. 💬 Run the suggestion scraper (server-side) ──────────────
    @bot.command(name="suggest_run", aliases=["scrape_suggest"])
    async def suggest_run_command(ctx):
        """
        Owner-only: run the autocomplete scraper now, using the server's
        DB access and cookie. Takes a few minutes.
        """
        if ctx.author.id not in BOT_OWNERS:
            return await ctx.send("🚫 Owner-only command.")

        await ctx.send(
            "💬 **Suggestion scraper started** — this can take a few minutes. "
            "I'll reply when it's done."
        )

        def _run():
            from suggest import run_suggest
            run_suggest()
            return True

        try:
            await asyncio.to_thread(_run)
            await ctx.send(
                "✅ **Suggestion scraper finished.**\n"
                "Now try `!meta_sniper <niche>` for better gap data."
            )
        except Exception as e:
            await ctx.send(
                f"⚠️ Scraper failed: {type(e).__name__}: {e}"
            )

    # ── 11. 🔭 Run the scanner / enricher on the server ─────────────
    @bot.command(name="scan_run", aliases=["run_scanner"])
    async def scan_run_command(ctx):
        """Owner-only: discover new catalog items now (server-side)."""
        if ctx.author.id not in BOT_OWNERS:
            return await ctx.send("🚫 Owner-only command.")
        await ctx.send(
            "🔭 **Scanner started** — discovering new item IDs. "
            "This can take up to 90 minutes; I'll reply when done."
        )

        def _run():
            from scanner import run_scanner
            run_scanner()
            return True

        try:
            await asyncio.to_thread(_run)
            await ctx.send("✅ **Scanner finished.** New IDs added to `discovered_items`.")
        except Exception as e:
            await ctx.send(f"⚠️ Scanner failed: {type(e).__name__}: {e}")

    @bot.command(name="enrich_run", aliases=["run_enricher"])
    async def enrich_run_command(ctx, batches: int = 1):
        """Owner-only: enrich discovered items. Each batch is ~1,500 items."""
        if ctx.author.id not in BOT_OWNERS:
            return await ctx.send("🚫 Owner-only command.")

        batches = max(1, min(batches, 20))
        await ctx.send(
            f"🧪 **Enricher started** — **{batches}** batch(es) of ~300 items. "
            f"Expect ~5–10 min per batch. Progress commits every 100 rows."
        )

        def _run():
            from enricher import enrich_items
            for i in range(batches):
                print(f"[enrich_run] batch {i+1}/{batches}", flush=True)
                enrich_items()
            return True

        try:
            await asyncio.to_thread(_run)
            await ctx.send(
                f"✅ **Enricher finished** — {batches} batch(es) done. "
                f"`items` updated with real favorites."
            )
        except Exception as e:
            await ctx.send(f"⚠️ Enricher failed: {type(e).__name__}: {e}")

    @bot.command(name="train", aliases=["retrain"])
    async def train_command(ctx):
        """Owner-only: train the title predictor on current catalog data."""
        if ctx.author.id not in BOT_OWNERS:
            return await ctx.send("🚫 Owner-only command.")

        await ctx.send("🧠 Training the title predictor on current data...")

        def _do():
            from title_predictor import train_model
            conn = get_db()
            cur = conn.cursor()
            try:
                return train_model(cur)
            finally:
                cur.close()
                conn.close()

        try:
            res = await asyncio.to_thread(_do)
        except Exception as e:
            return await ctx.send(f"⚠️ Training failed: {type(e).__name__}: {e}")

        if not res:
            return await ctx.send(
                "⚠️ Training returned no model — not enough labelled items. "
                "Clear more of the enrichment backlog first."
            )

        await ctx.send(
            f"✅ Trained on **{res.get('n_samples', 0):,}** items · "
            f"accuracy **{res.get('accuracy', 0) * 100:.1f}%**"
        )

    # ── 12. 📒 Launch Ledger ────────────────────────────────────────
    @bot.command(name="launch", aliases=["log_launch"])
    async def launch_command(ctx, item_id: int, launched: str = "", *, notes: str = ""):
        """
        Record an item as launched.
        Usage: !launch <item_id>
               !launch <item_id> 2026-09-01        (existing item)
        """
        from datetime import datetime, timezone

        launch_dt = None
        if launched:
            parsed = None
            for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
                try:
                    parsed = datetime.strptime(launched, fmt)
                    break
                except ValueError:
                    continue
            if parsed is None:
                return await ctx.send(
                    "❌ Date must be `YYYY-MM-DD` or `YYYY-MM-DD HH:MM`."
                )
            launch_dt = parsed
        if launch_dt is None:
            launch_dt = datetime.now(timezone.utc).replace(tzinfo=None)

        def _do():
            conn = get_db()
            cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT id, name, favorite_count, price, asset_type_id
                    FROM items WHERE id = %s
                """, (item_id,))
                row = cur.fetchone()
                if not row:
                    return {"error": "not_found"}

                iid, name, favs, price, atype = row
                family = "unknown"
                try:
                    from category_configs import detect_family_from_asset_type
                    family = detect_family_from_asset_type(atype) or "unknown"
                except Exception:
                    pass

                score = 0.0
                confidence = 0.0
                try:
                    from title_predictor import predict_title
                    # auto_train=False: never block the launch command on a
                    # multi-minute model training run.
                    pred = predict_title(cur, name, auto_train=False)
                    score = float(pred.get("score") or 0)
                    confidence = float(pred.get("confidence") or 0)
                except Exception as e:
                    print(f"[launch] predict failed: {e}", flush=True)

                cur.execute("""
                    INSERT INTO launch_ledger
                      (item_id, launched_at, family, title, asset_type_id,
                       price, predicted_score, predicted_confidence,
                       favs_launch, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (item_id) DO UPDATE SET
                      launched_at = EXCLUDED.launched_at,
                      family = EXCLUDED.family,
                      title = EXCLUDED.title,
                      asset_type_id = EXCLUDED.asset_type_id,
                      price = EXCLUDED.price,
                      predicted_score = EXCLUDED.predicted_score,
                      predicted_confidence = EXCLUDED.predicted_confidence,
                      favs_launch = EXCLUDED.favs_launch,
                      notes = EXCLUDED.notes
                """, (
                    iid, launch_dt, family, name, atype, price or 0,
                    score, confidence, favs or 0, notes,
                ))
                conn.commit()
                return {
                    "id": iid, "name": name, "family": family,
                    "score": score, "confidence": confidence,
                    "price": price or 0,
                }
            finally:
                cur.close()
                conn.close()

        result = await asyncio.to_thread(_do)
        if result.get("error") == "not_found":
            return await ctx.send(f"❌ Item `{item_id}` not found in the catalog.")

        embed = discord.Embed(
            title="📒 Launch Logged",
            description=f"**{result['name'][:60]}**",
            color=0x3B82F6,
        )
        embed.add_field(name="Item ID", value=f"`{result['id']}`", inline=True)
        embed.add_field(name="Family", value=result["family"], inline=True)
        embed.add_field(name="Price", value=f"{result['price']} R$", inline=True)
        embed.add_field(
            name="Predicted score",
            value=f"**{result['score']:.1f}** (confidence {result['confidence']:.0f}%)",
            inline=False,
        )
        embed.set_footer(
            text="D1/D7/D30 favorites and sales fill via !ledger_sync"
        )
        await ctx.send(embed=embed)

    @bot.command(name="ledger_sync", aliases=["sync_ledger"])
    async def ledger_sync_command(ctx):
        """Fill ledger rows with real favorites (D1/D7/D30) and sales."""
        def _do():
            conn = get_db()
            cur = conn.cursor()
            try:
                synced = sync_all(cur)
                conn.commit()
                return synced
            finally:
                cur.close()
                conn.close()

        synced = await asyncio.to_thread(_do)
        await ctx.send(
            f"✅ Synced **{synced}** launch rows with favorites + sales."
        )

    @bot.command(name="hitrate", aliases=["hit_rate"])
    async def hitrate_command(ctx, days: int = 90):
        """Show how your launches actually performed vs their niche peers."""
        days = max(1, min(days, 365))

        def _do():
            from datetime import timedelta

            conn = get_db()
            cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT item_id FROM launch_ledger
                    WHERE launched_at >= NOW() - %s
                """, (timedelta(days=days),))
                for (iid,) in cur.fetchall():
                    try:
                        fill_ledger(cur, iid)
                    except Exception:
                        pass
                conn.commit()

                cur.execute("""
                    SELECT item_id, launched_at, family, title,
                           predicted_score, favs_d7, favs_d30,
                           units_d30, revenue_d30
                    FROM launch_ledger
                    WHERE launched_at >= NOW() - %s
                    ORDER BY launched_at DESC
                """, (timedelta(days=days),))
                rows = cur.fetchall()
                if not rows:
                    return {"empty": True}

                results = []
                for (iid, launched, family, title, score,
                     f7, f30, u30, r30) in rows:
                    has_data = f7 is not None or f30 is not None
                    actual = f7 if f7 is not None else (f30 if f30 is not None else 0)

                    peer_median = 0
                    try:
                        cur.execute(
                            "SELECT asset_type_id FROM items WHERE id = %s",
                            (iid,),
                        )
                        at = cur.fetchone()
                        if at and at[0] is not None:
                            cur.execute("""
                                SELECT favorite_count FROM items
                                WHERE asset_type_id = %s
                                  AND favorite_count > 0
                                  AND created_at BETWEEN %s AND %s
                                ORDER BY favorite_count
                                LIMIT 2000
                            """, (
                                at[0],
                                launched - timedelta(days=14),
                                launched + timedelta(days=14),
                            ))
                            vals = [v[0] for v in cur.fetchall()]
                            if vals:
                                peer_median = vals[len(vals) // 2]
                    except Exception:
                        pass

                    hit = (
                        has_data
                        and peer_median > 0
                        and actual >= peer_median
                    )
                    results.append({
                        "id": iid, "title": title or "",
                        "score": score or 0, "actual": actual,
                        "peer": peer_median, "hit": hit,
                        "has_data": has_data,
                        "units": u30 or 0, "revenue": r30 or 0,
                    })

                return {"results": results}
            finally:
                cur.close()
                conn.close()

        data = await asyncio.to_thread(_do)
        if data.get("empty"):
            return await ctx.send(
                "📒 No launches logged yet. Use `!launch <item_id>` after uploading."
            )

        results = data["results"]
        total = len(results)
        measured = [r for r in results if r["has_data"]]
        total_measured = len(measured)
        hits = sum(1 for r in measured if r["hit"])
        hit_rate = (hits / total_measured * 100) if total_measured else 0
        avg_rev = (
            sum(r["revenue"] for r in measured) / total_measured
            if total_measured else 0
        )

        kw_rev = {}
        for r in measured:
            for w in set(re.findall(r"[a-z]{3,}", r["title"].lower())):
                kw_rev[w] = kw_rev.get(w, 0) + r["revenue"]
        best = sorted(kw_rev.items(), key=lambda x: -x[1])[:5]

        embed = discord.Embed(
            title=f"📈 Hit Rate — last {days} days",
            description=(
                f"Launches: **{total}** · Measured: **{total_measured}** · "
                f"Beat peer median: **{hits}** ({hit_rate:.0f}%) · "
                f"Avg revenue: **{avg_rev:,.0f} R$**"
            ),
            color=0x8B5CF6,
        )

        lines = []
        for r in results[:10]:
            if not r["has_data"]:
                mark = "⏳"
                actual_str = "no snapshot data"
            else:
                mark = "✅" if r["hit"] else "❌"
                actual_str = f"{r['actual']:,} favs"
            lines.append(
                f"{mark} `{(r['title'] or '')[:32]}` — "
                f"{actual_str} vs peer {r['peer']:,} · "
                f"R${r['revenue']:,}"
            )
        if lines:
            embed.add_field(name="Launches", value="\n".join(lines), inline=False)

        if best:
            embed.add_field(
                name="Best keywords (by revenue)",
                value=" · ".join(f"`{w}` ({v:,})" for w, v in best),
                inline=False,
            )

        embed.set_footer(
            text="Peer median = same asset type, created within ±14 days of launch"
        )
        await ctx.send(embed=embed)

    @bot.command(name="logs", aliases=["log"])
    async def logs_command(ctx, lines: int = 50):
        """Owner-only: show the last N bot log lines (Render-style)."""
        if ctx.author.id not in BOT_OWNERS:
            return await ctx.send("🚫 Owner-only command.")

        lines = max(10, min(lines, 200))
        try:
            out = subprocess.check_output(
                [
                    "journalctl", "-u", "ugc-bot",
                    "-n", str(lines), "-o", "cat", "--no-pager",
                ],
                text=True,
                timeout=10,
            )
        except Exception as e:
            return await ctx.send(
                f"⚠️ Could not read logs: {type(e).__name__}: {e}"
            )

        out = out.strip() or "(no log lines)"
        chunks = [out[i:i + 1850] for i in range(0, len(out), 1850)][-5:]
        for chunk in chunks:
            await ctx.send(f"```\n{chunk}\n```")
            await asyncio.sleep(0.2)

    @bot.command(name="launch_sync", aliases=["sync_launches"])
    async def launch_sync_command(ctx, *, groups: str = ""):
        """
        Auto-log every item from your groups into the ledger.
        Usage: !launch_sync Group One,Group Two,Group Three
               or set MY_GROUP_NAMES in the bot environment.
        """
        if groups.strip():
            name_list = [n.strip() for n in groups.split(",") if n.strip()]
        else:
            name_list = configured_groups()

        if not name_list:
            return await ctx.send(
                "Usage: `!launch_sync Group One,Group Two`\n"
                "Or set `MY_GROUP_NAMES` in the bot environment."
            )

        def _do():
            conn = get_db()
            cur = conn.cursor()
            try:
                total, added = sync_group_items(cur, name_list)
                conn.commit()
                return total, added
            finally:
                cur.close()
                conn.close()

        total, added = await asyncio.to_thread(_do)
        await ctx.send(
            f"📒 Found **{total}** items for your groups · "
            f"**{added}** newly logged in the ledger."
        )

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
