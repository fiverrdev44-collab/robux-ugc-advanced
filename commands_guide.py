"""
commands_guide.py — registers !guide and related commands.
"""
import io
import re
import asyncio
import math
import discord
from datetime import datetime
from collections import Counter, defaultdict

from bot_ui import ask_nav
from bot_core import (
    get_db, get_db_stats, rollback_quietly, extract_words,
    word_boundary_pattern, classify_word, is_emote_word,
    analyze_opportunity,
    _analyze_word, _analyze_combo, _get_adjacent_for, _find_alternatives,
    smart_verdict, build_strategy,
    get_or_create_profile, increment_consultations,
    save_consultation, get_past_consultations, add_to_watchlist,
    get_timing_intelligence, get_launch_window, get_niche_graph,
    get_creator_dominance, generate_ab_titles, _compute_roi,
    _assess_risk, _get_trend_signal, _generate_portfolio,
    _analyze_rivals, _optimize_price, _make_design_brief,
    build_full_report,
    MAX_PRICE,
)


async def _safe_send(ctx, embed=None, content=None, label=""):
    for attempt in range(2):
        try:
            if embed is not None:
                await ctx.send(embed=embed)
            else:
                await ctx.send(content)
            return True
        except discord.HTTPException as e:
            print(f"⚠️ HTTP error {label} ({attempt+1}): {e}", flush=True)
            if attempt == 0:
                await asyncio.sleep(3)
                continue
            return False
        except Exception as e:
            print(f"❌ Failed {label}: {e}", flush=True)
            return False
    return False


def register_guide_commands(bot):

    @bot.command(name="guide")
    async def guide(ctx, *, idea: str = None):
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        discord_id = ctx.author.id
        username = str(ctx.author)

        try:
            conn = get_db(); cur = conn.cursor()
            profile = get_or_create_profile(cur, discord_id, username)
            past = get_past_consultations(cur, discord_id, limit=3)
            stats = get_db_stats(cur)
            conn.commit()
            cur.close(); conn.close()
        except Exception as e:
            print(f"Setup error: {e}", flush=True)
            profile = {"total_consultations": 0, "first_seen": None}
            past = []
            stats = {"discovered": 0, "analyzed": 0, "snapshots": 0,
                     "suggestions": 0, "learned": 0, "consultations": 0}

        greeting = ""
        if profile["total_consultations"] > 0:
            greeting = f"👋 Welcome back, **{ctx.author.display_name}**. Consultation **#{profile['total_consultations'] + 1}**.\n\n"

        db_status = (
            f"```\n"
            f"┌─ LIVE DATABASE ──────────────┐\n"
            f"│ 🔍 IDs Discovered   {stats['discovered']:>10,} │\n"
            f"│ 📦 Items Analyzed   {stats['analyzed']:>10,} │\n"
            f"│ 📊 History Snapshots{stats['snapshots']:>10,} │\n"
            f"│ 💬 Search Suggestions{stats['suggestions']:>9,} │\n"
            f"│ 🧠 Learned Keywords {stats['learned']:>10,} │\n"
            f"└──────────────────────────────┘\n"
            f"```"
        )

        if not idea:
            await _safe_send(ctx, discord.Embed(
                title="🧠 Elite UGC Consultation",
                description=(f"{greeting}{db_status}\n"
                             "**4 sections** — buttons control the pace.\n\n"
                             "**What's your UGC idea?**\n"
                             "*Examples: `korean dance` · `y2k cyber visor` · `transparent beanie`*"),
                color=0x00aaff), "Intake")
            try:
                msg = await bot.wait_for("message", check=check, timeout=600)
                idea = msg.content.strip().lower()
            except asyncio.TimeoutError:
                await ctx.send("⏰ Timed out.")
                return

        if idea in ("cancel", "exit", "stop"):
            await ctx.send("❌ Cancelled.")
            return

        idea_clean = re.sub(r'[^a-z0-9\s]', '', idea.lower()).strip()
        words = [w for w in idea_clean.split() if len(w) >= 2]
        if not words:
            await ctx.send("❌ Need at least one real word.")
            return

        classifications = []
        icons = {"slang": "⚡", "color": "🎨", "style": "✨", "item": "🧢",
                 "emote": "💃", "number": "🔢", "unknown": "❔"}
        try:
            conn_c = get_db(); cur_c = conn_c.cursor()
            for w in words:
                c = classify_word(w)
                if c == "unknown" and is_emote_word(cur_c, w):
                    c = "emote"
                classifications.append(c)
            cur_c.close(); conn_c.close()
        except Exception:
            classifications = [classify_word(w) for w in words]

        understanding = "\n".join(f"{icons[c]} `{w}` — **{c}**" for w, c in zip(words, classifications))

        await _safe_send(ctx, discord.Embed(
            title=f"📖 Section 1/4 — Understanding `{idea_clean}`",
            description=(f"{db_status}\n**Parsing {len(words)} components:**\n\n"
                         f"{understanding}\n\n*Scanning {stats['analyzed']:,} items...*"),
            color=0x00aaff), "S1")
        await asyncio.sleep(0.3)

        progress = await ctx.send("🔄 Loading market data...")
        word_stats, combo_stats, opportunity_data = [], None, None
        adjacent, rivals, dominance, alternatives, portfolio = [], [], [], [], []
        trend_data, timing, launch_window = {}, None, "N/A"
        graph = {"level_1": [], "level_2": {}}
        desc_keywords, gap_keywords = [], []
        risks, pricing, roi, ab_titles, design = [], [], None, [], ""
        total_items = 0
        total_described = 0

        conn = None; cur = None
        try:
            conn = get_db(); cur = conn.cursor()

            try:
                word_stats = [_analyze_word(cur, w) for w in words]
            except Exception as e:
                print(f"Word stats failed: {e}", flush=True)
                rollback_quietly(cur)

            try:
                combo_stats = _analyze_combo(cur, words) if len(words) >= 2 else None
            except Exception as e:
                print(f"Combo stats failed: {e}", flush=True)
                rollback_quietly(cur)
                combo_stats = None

            try:
                await progress.edit(content="🔄 Analyzing keywords (emote-aware)...")
            except Exception: pass

            try:
                opportunity_data = analyze_opportunity(cur, idea_clean)
                if (not opportunity_data or not opportunity_data.get("top_keywords")) and len(words) > 1:
                    opportunity_data = analyze_opportunity(cur, words[-1])
            except Exception as e:
                print(f"Opportunity failed: {e}", flush=True)
                rollback_quietly(cur)
                opportunity_data = None

            try:
                adjacent = _get_adjacent_for(cur, words[-1], limit=25)
            except Exception as e:
                print(f"Adjacent failed: {e}", flush=True)
                rollback_quietly(cur)
                adjacent = []

            try:
                await progress.edit(content="🔄 Loading rivals + trends...")
            except Exception: pass

            try:
                rivals = _analyze_rivals(cur, words[-1], top_n=3)
            except Exception as e:
                print(f"Rivals failed: {e}", flush=True)
                rollback_quietly(cur)
                rivals = []

            try:
                trend_data = _get_trend_signal(cur, words[-1]) or {}
            except Exception as e:
                print(f"Trend failed: {e}", flush=True)
                rollback_quietly(cur)
                trend_data = {}

            try:
                timing = get_timing_intelligence(cur, words[-1])
            except Exception as e:
                print(f"Timing failed: {e}", flush=True)
                rollback_quietly(cur)
                timing = None

            try:
                launch_window = get_launch_window(cur, words[-1])
            except Exception as e:
                print(f"Launch window failed: {e}", flush=True)
                rollback_quietly(cur)
                launch_window = "N/A"

            try:
                graph = get_niche_graph(cur, words[-1], top_per_level=12)
            except Exception as e:
                print(f"Graph failed: {e}", flush=True)
                rollback_quietly(cur)
                graph = {"level_1": [], "level_2": {}}

            try:
                dominance = get_creator_dominance(cur, words[-1])
            except Exception as e:
                print(f"Dominance failed: {e}", flush=True)
                rollback_quietly(cur)
                dominance = []

            try:
                await progress.edit(content="🔄 Loading descriptions + gaps...")
            except Exception: pass
            pattern = word_boundary_pattern(words[-1])

            try:
                cur.execute("SELECT COUNT(*) FROM items WHERE description IS NOT NULL AND description != ''")
                total_described = cur.fetchone()[0] or 0
                cur.execute("SELECT COUNT(*) FROM items")
                total_items = cur.fetchone()[0] or 0
            except Exception:
                rollback_quietly(cur)

            try:
                cur.execute("""SELECT name, COALESCE(description, ''), favorite_count FROM items 
                               WHERE name ~* %s AND description IS NOT NULL AND description != ''
                               AND favorite_count > 0 LIMIT 1000""", (pattern,))
                desc_rows = cur.fetchall()
                if desc_rows:
                    dc = Counter(); df = defaultdict(int)
                    for name, desc, favs in desc_rows:
                        for w in set(extract_words(desc)):
                            dc[w] += 1; df[w] += favs or 0
                    for w, count in dc.most_common(50):
                        if count < 2: continue
                        af = df[w] / count
                        desc_keywords.append((w, af, count, af / math.log1p(count)))
            except Exception as e:
                print(f"Desc keywords failed: {e}", flush=True)
                rollback_quietly(cur)

            try:
                cur.execute("""SELECT name, COALESCE(description, ''), favorite_count FROM items 
                               WHERE (name ~* %s OR COALESCE(description, '') ~* %s) 
                               AND favorite_count > 50 LIMIT 1000""", (pattern, pattern))
                gap_rows = cur.fetchall()
                if gap_rows:
                    gs = defaultdict(lambda: {"favs": 0, "count": 0})
                    for name, desc, favs in gap_rows:
                        for w in set(extract_words(f"{name} {desc}")):
                            if w == words[-1]: continue
                            gs[w]["favs"] += (favs or 0); gs[w]["count"] += 1
                    for w, s in gs.items():
                        if s["count"] < 2 or s["count"] > 20: continue
                        af = s["favs"] / s["count"]
                        if af < 500: continue
                        gap_keywords.append((w, af, s["count"]))
                    gap_keywords.sort(key=lambda x: x[1], reverse=True)
                    gap_keywords = gap_keywords[:25]
            except Exception as e:
                print(f"Gaps failed: {e}", flush=True)
                rollback_quietly(cur)

            try:
                if len(words) >= 2 and word_stats and word_stats[0]["count"] < 100:
                    alternatives = _find_alternatives(cur, words[0], words[-1], limit=8)
            except Exception as e:
                print(f"Alternatives failed: {e}", flush=True)
                rollback_quietly(cur)

            try:
                portfolio = _generate_portfolio(cur, idea_clean, alternatives, adjacent, opportunity_data)
            except Exception as e:
                print(f"Portfolio failed: {e}", flush=True)

            try:
                risks = _assess_risk(word_stats, combo_stats, opportunity_data, trend_data)
            except Exception as e:
                print(f"Risks failed: {e}", flush=True)
                risks = [("🟢", "Analysis unavailable", "Solid opportunity — proceed")]

            try:
                pricing = _optimize_price(opportunity_data, combo_stats, word_stats)
            except Exception as e:
                print(f"Pricing failed: {e}", flush=True)

            try:
                roi = _compute_roi(opportunity_data, combo_stats, word_stats)
            except Exception as e:
                print(f"ROI failed: {e}", flush=True)

            try:
                ab_titles = generate_ab_titles(idea_clean, words, combo_stats, alternatives, adjacent, opportunity_data)
            except Exception as e:
                print(f"A/B titles failed: {e}", flush=True)

            try:
                design = _make_design_brief(idea_clean, word_stats, adjacent, opportunity_data)
            except Exception as e:
                print(f"Design failed: {e}", flush=True)

            try:
                increment_consultations(cur, discord_id)
                conn.commit()
            except Exception: pass

        except Exception as e:
            print(f"Outer scan error: {e}", flush=True)
            import traceback
            traceback.print_exc()
        finally:
            try: cur.close()
            except Exception: pass
            try: conn.close()
            except Exception: pass

        try: await progress.delete()
        except Exception: pass
        await asyncio.sleep(0.3)

        pulse = discord.Embed(title="📊 Section 1 — Market Pulse",
                              description="Real data per word:", color=0x66ccff)
        for i, w in enumerate(word_stats, 1):
            if w["count"] == 0: status = "❌ Not in DB"
            elif w["count"] < 10: status = f"🟡 Rare ({w['count']})"
            elif w["count"] < 100: status = f"🟢 Niche ({w['count']})"
            elif w["count"] < 500: status = f"🟠 Popular ({w['count']})"
            else: status = f"🔴 Saturated ({w['count']})"
            price_display = f"{w['avg_price']:,.0f} R$" if w['avg_price'] > 0 else "—"
            pulse.add_field(name=f"{i}. `{w['word']}` — {status}",
                            value=f"Avg Favs: **{w['avg_favs']:,.0f}** · Median Price: **{price_display}**",
                            inline=False)
        if trend_data and trend_data.get("avg_growth") is not None:
            g = trend_data["avg_growth"]
            arrow = "📈" if g > 50 else "📉" if g < -50 else "➡️"
            pulse.add_field(name=f"{arrow} Trend",
                            value=f"**{g:+,.0f}** favs/snapshot ({trend_data.get('tracked', 0)} tracked)",
                            inline=False)
        await _safe_send(ctx, pulse, "Pulse")

        choice = await ask_nav(ctx, "**Section 1 done.** See keywords + adjacent + description + gaps?")
        goto_strategy = False
        if choice == "stop":
            await ctx.send("⏹ Guide ended.")
            return
        if choice == "skip":
            goto_strategy = True
        else:
            await ctx.send("🔄 Loading Section 2...")
            await asyncio.sleep(0.3)

        if not goto_strategy:
            if opportunity_data and opportunity_data.get("top_keywords"):
                kw_all = opportunity_data["top_keywords"][:15]
                fallback_note = ""
                if opportunity_data.get("used_fallback"):
                    fallback_note = " *(multi-word fallback)*"
                if opportunity_data.get("is_emote_seed"):
                    fallback_note += " *(💃 emote-aware)*"
                for page_start in range(0, len(kw_all), 8):
                    chunk = kw_all[page_start:page_start + 8]
                    kw_embed = discord.Embed(
                        title=f"🎯 Section 2 — Top Keywords ({page_start+1}–{page_start+len(chunk)})",
                        description=f"From **{opportunity_data['total_matches']}** items.{fallback_note}",
                        color=0x00ff88)
                    for i, (w, af, c, sc) in enumerate(chunk, page_start + 1):
                        kw_embed.add_field(name=f"{i}. {w}",
                                           value=f"Score: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Comp: **{c:,}**",
                                           inline=False)
                    await _safe_send(ctx, kw_embed, "Kw")
                    await asyncio.sleep(0.5)
            else:
                await _safe_send(ctx, content="🎯 Section 2 — No top keywords found.", label="Kw-Empty")

            if adjacent:
                for page_start in range(0, len(adjacent), 30):
                    chunk = adjacent[page_start:page_start + 30]
                    adj_embed = discord.Embed(
                        title=f"🔗 Section 2 — Adjacent Keywords ({page_start+1}–{page_start+len(chunk)})",
                        description="Words that appear alongside your idea.",
                        color=0x66ccff)
                    half = (len(chunk) + 1) // 2
                    left = " · ".join(f"`{w}`" for w in chunk[:half])
                    right = " · ".join(f"`{w}`" for w in chunk[half:])
                    if left: adj_embed.add_field(name="\u200b", value=left, inline=True)
                    if right: adj_embed.add_field(name="\u200b", value=right, inline=True)
                    await _safe_send(ctx, adj_embed, "Adj")
                    await asyncio.sleep(0.5)

            if desc_keywords:
                for page_start in range(0, min(len(desc_keywords), 20), 8):
                    chunk = desc_keywords[page_start:page_start + 8]
                    desc_embed = discord.Embed(
                        title=f"📝 Section 2 — Hidden Description Keywords ({page_start+1}–{page_start+len(chunk)})",
                        description="SEO words buried in descriptions:",
                        color=0xaa66ff)
                    for i, (w, af, c, sc) in enumerate(chunk, page_start + 1):
                        desc_embed.add_field(name=f"{i}. {w}",
                                             value=f"Score: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Used in **{c}** descs",
                                             inline=False)
                    await _safe_send(ctx, desc_embed, "Desc")
                    await asyncio.sleep(0.5)
            else:
                if total_items > 0:
                    diag_msg = (
                        f"**No descriptions found for this niche.**\n\n"
                        f"📊 Database-wide: **{total_described:,}** of **{total_items:,}** items have descriptions "
                        f"({(total_described/total_items*100):.1f}%).\n\n"
                        f"Run the **enricher** workflow more times to fill them in."
                    )
                else:
                    diag_msg = "**No descriptions found.** Run the enricher."
                await _safe_send(ctx, discord.Embed(
                    title="📝 Section 2 — Hidden Description Keywords",
                    description=diag_msg, color=0xaa66ff), "Desc-Empty")

            if gap_keywords:
                for page_start in range(0, len(gap_keywords), 8):
                    chunk = gap_keywords[page_start:page_start + 8]
                    gap_embed = discord.Embed(
                        title=f"🕳️ Section 2 — Market Gaps ({page_start+1}–{page_start+len(chunk)})",
                        description="High demand + low competition:",
                        color=0x00ffcc)
                    for i, (w, af, c) in enumerate(chunk, page_start + 1):
                        gap_embed.add_field(name=f"{i}. {w}",
                                            value=f"AvgFav: **{af:,.0f}** | Used by **{c}** items — untapped!",
                                            inline=False)
                    await _safe_send(ctx, gap_embed, "Gaps")
                    await asyncio.sleep(0.5)

            choice = await ask_nav(ctx, "**Section 2 done.** See diagnosis + risks + rivals + dominance?")
            if choice == "stop":
                await ctx.send("⏹ Guide ended.")
                return
            if choice == "skip":
                goto_strategy = True
            else:
                await ctx.send("🔄 Loading Section 3...")
                await asyncio.sleep(0.3)

        verdict = smart_verdict(word_stats, combo_stats)

        if not goto_strategy:
            emoji, label, explanation = verdict
            color_map = {"🔥": 0xff2266, "🟢": 0x00ff88, "🟡": 0xffaa00, "🟠": 0xff6600, "🔴": 0xff2222}
            diag = discord.Embed(title=f"{emoji} Section 3 — Diagnosis: {label}",
                                 description=f"━━━━━━━━━━━━━━━━━━━━━\n\n{explanation}",
                                 color=color_map.get(emoji, 0x00aaff))
            if combo_stats and combo_stats["count"] > 0:
                diag.add_field(name="🎯 Combo Match",
                               value=f"**{combo_stats['count']}** items\nAvg Fav: **{combo_stats['avg_favs']:,.0f}**",
                               inline=False)
            await _safe_send(ctx, diag, "Diag")
            await asyncio.sleep(0.5)

            risk_embed = discord.Embed(title="⚠️ Section 3 — Risks",
                                       description=f"**{len(risks)}** identified:", color=0xff8800)
            for icon, risk, mit in risks:
                risk_embed.add_field(name=f"{icon} {risk}", value=f"→ *{mit}*", inline=False)
            await _safe_send(ctx, risk_embed, "Risks")
            await asyncio.sleep(0.5)

            if rivals:
                rival_embed = discord.Embed(title="🥊 Section 3 — Top Rivals",
                                            description="Study these before you build:", color=0xff3388)
                for iid, name, favs, price, creator in rivals:
                    creator_str = f"by {creator}" if creator else "unknown"
                    price_str = f"{price} R$" if price and price <= MAX_PRICE else "N/A"
                    rival_embed.add_field(name=f"`{iid}` — {name[:55]}",
                                          value=f"**{favs:,}** favs · **{price_str}** · {creator_str}",
                                          inline=False)
                await _safe_send(ctx, rival_embed, "Rivals")
                await asyncio.sleep(0.5)

            if dominance and len(dominance) > 1:
                dom_embed = discord.Embed(title="👑 Section 3 — Creator Dominance",
                                          description="Who owns this niche?", color=0xffcc00)
                for creator, cnt, total_favs in dominance[:5]:
                    dom_embed.add_field(name=creator,
                                        value=f"**{cnt}** items · **{total_favs:,}** favs", inline=True)
                await _safe_send(ctx, dom_embed, "Dom")
                await asyncio.sleep(0.5)

            choice = await ask_nav(ctx, "**Section 3 done.** See ROI + pricing + final package?")
            if choice == "stop":
                await ctx.send("⏹ Guide ended.")
                return
            await ctx.send("🔄 Loading final section...")
            await asyncio.sleep(0.3)

        try:
            combo = discord.Embed(title="💰 Section 4 — ROI, Pricing & Alternatives",
                                  color=0x00ff88)
            if alternatives:
                combo.add_field(name="🎨 Proven Alternatives",
                                value="\n".join(f"• `{a['word']}` — **{a['count']}** items, avg **{a['avg_favs']:,.0f}** favs"
                                                for a in alternatives[:5]),
                                inline=False)
            if graph.get("level_1"):
                combo.add_field(name="🕸️ Keyword Graph",
                                value=" · ".join(f"`{w}`" for w in graph["level_1"][:10]),
                                inline=False)
            if roi:
                combo.add_field(name="📈 Expected Favs", value=f"**~{roi['expected_favs']:,}**", inline=True)
                combo.add_field(name="💸 Expected Sales", value=f"**~{roi['expected_sales']:,}**", inline=True)
                combo.add_field(name="💎 Expected Revenue", value=f"**~{roi['expected_revenue']:,} R$**\n({roi['confidence']})", inline=True)
            if pricing:
                combo.add_field(name="💵 Pricing Options",
                                value="\n".join(f"{p['name']} — **{p['price']} R$** · *{p['pro']}*" for p in pricing),
                                inline=False)
            await _safe_send(ctx, combo, "S4-1")
            await asyncio.sleep(1)

            design_embed = discord.Embed(title="✏️ Section 4 — Design Package", color=0x9966ff)
            if portfolio:
                design_embed.add_field(name="🎨 Portfolio Blueprint",
                                       value="\n".join(f"**{i}. [{item['angle']}]** `{item['idea']}`\n    *{item['why']}*"
                                                       for i, item in enumerate(portfolio, 1)),
                                       inline=False)
            if design:
                design_embed.add_field(name="📐 Design Brief", value=design, inline=False)
            if adjacent:
                design_embed.add_field(name="🔗 Title/Description Keywords",
                                       value=" · ".join(f"`{w}`" for w in adjacent[:10]), inline=False)
            if ab_titles:
                design_embed.add_field(name="🅰️ Title Variants",
                                       value="\n\n".join(f"**{chr(64+i)}. {t['strategy']}** [{t['predicted']}]\n`{t['title']}`"
                                                         for i, t in enumerate(ab_titles, 1)),
                                       inline=False)
            await _safe_send(ctx, design_embed, "S4-2")
            await asyncio.sleep(1)

            final_embed = discord.Embed(title="🎯 Final Strategy & Launch Plan", color=0x00ffcc)
            if timing:
                final_embed.add_field(name="📅 Best Day", value=f"**{timing['best_day']}**", inline=True)
                final_embed.add_field(name="⏰ Best Hours", value=", ".join(timing["best_hours"]), inline=True)
            final_embed.add_field(name="🚀 Launch Window", value=launch_window, inline=False)
            final_embed.add_field(name="🎯 Strategy",
                                  value=build_strategy(verdict, word_stats, combo_stats, adjacent, alternatives, opportunity_data),
                                  inline=False)
            final_title = ab_titles[0]["title"] if ab_titles else " ".join(w.capitalize() for w in words)[:80]
            final_price = roi["best_price"] if roi else 100
            final_embed.add_field(name="✅ Launch Checklist",
                                  value=(f"**Day 1 — Design**\n☐ Model in Roblox Studio\n☐ Reference rivals\n\n"
                                         f"**Day 2 — Upload**\n☐ Title: `{final_title}`\n☐ Price: **{final_price} R$**\n☐ Full SEO description\n\n"
                                         f"**Day 3–7** — Track favourites daily\n**Day 8–30** — Scale or pivot"),
                                  inline=False)
            await _safe_send(ctx, final_embed, "S4-3")
        except Exception as e:
            print(f"❌ Section 4 error: {e}", flush=True)
            try: await ctx.send(f"⚠️ **Section 4 error:** `{e}`")
            except Exception: pass

        await ctx.send(
            f"🎉 **Done!** Guide complete for `{idea_clean}`.\n\n"
            f"👁️ Add `{words[-1]}` to **watchlist**? — reply `yes`\n"
            f"📄 Export **full report** as file? — reply `export`\n"
            f"⏹ End? — reply `no`"
        )

        try:
            msg = await bot.wait_for("message", check=check, timeout=300)
            reply = msg.content.strip().lower()
            if reply in ("yes", "y", "yup", "yeah", "ok", "sure"):
                try:
                    conn = get_db(); cur = conn.cursor()
                    added = add_to_watchlist(cur, discord_id, words[-1], baseline_favs=0)
                    conn.commit(); cur.close(); conn.close()
                    await ctx.send(f"✅ `{words[-1]}` added to watchlist." if added else f"ℹ️ Already on watchlist.")
                except Exception as e:
                    await ctx.send(f"⚠️ Watchlist error: {e}")
            if reply == "export" or reply.startswith("export"):
                session_data = type("Session", (), {"seed": idea_clean, "words": words,
                                                    "word_stats": word_stats, "combo_stats": combo_stats})()
                report = build_full_report(session_data, verdict, roi, risks, pricing, portfolio, design,
                                            timing, launch_window, ab_titles, graph, dominance)
                try:
                    conn = get_db(); cur = conn.cursor()
                    save_consultation(cur, discord_id, idea_clean, verdict, report)
                    conn.commit(); cur.close(); conn.close()
                except Exception: pass
                file = discord.File(io.BytesIO(report.encode("utf-8")),
                                    filename=f"ugc_report_{idea_clean.replace(' ', '_')}.txt")
                try: await ctx.send("📄 **Report attached:**", file=file)
                except Exception as e: await ctx.send(f"⚠️ Attach failed: {e}")
        except asyncio.TimeoutError:
            pass
