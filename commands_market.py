"""
commands_market.py — market data commands (dbtest, scan_status, trends,
analyze, opportunity, emote, classic, gap, velocity, track, etc).
"""
import math
import re
from collections import Counter, defaultdict

from bot_ui import SimplePaginator, MultiViewPaginator
from bot_core import (
    get_db, get_db_stats, rollback_quietly, extract_words,
    word_boundary_pattern, analyze_opportunity,
    ASSET_TYPE_NAMES,
)


def register_market_commands(bot):

    @bot.command(name="emote_status")
    async def emote_status(ctx):
        try:
            conn = get_db(); cur = conn.cursor()
            try:
                cur.execute("SELECT COUNT(*) FROM items WHERE asset_type_id = 61")
                emote_count = cur.fetchone()[0] or 0
            except Exception:
                rollback_quietly(cur); emote_count = 0
            try:
                cur.execute("SELECT COUNT(*) FROM items WHERE name ~* '\\mdance\\M|\\memote\\M|\\mfloss\\M|\\mgriddy\\M|\\mmoonwalk\\M'")
                kw_emote = cur.fetchone()[0] or 0
            except Exception:
                rollback_quietly(cur); kw_emote = 0
            try:
                cur.execute("SELECT COUNT(*) FROM items")
                total = cur.fetchone()[0] or 0
            except Exception:
                rollback_quietly(cur); total = 0
            cur.close(); conn.close()

            embed = discord.Embed(title="💃 Emote Coverage Diagnostic", color=0xff66aa)
            embed.add_field(name="By AssetTypeId (61)", value=f"**{emote_count:,}** items", inline=True)
            embed.add_field(name="By Title Keyword", value=f"**{kw_emote:,}** items", inline=True)
            embed.add_field(name="Total in DB", value=f"**{total:,}** items", inline=True)
            if emote_count == 0:
                embed.add_field(name="⚠️ No emotes detected",
                                value="Run the Daily Scanner workflow on GitHub. It may take a full scan to fetch emotes.",
                                inline=False)
            else:
                embed.add_field(name="✅ Emotes Detected",
                                value=f"You have **{emote_count:,}** emotes in the database. "
                                      f"Run the enricher to fill details.",
                                inline=False)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Error: {e}")


    @bot.command(name="watchlist")
    async def watchlist_cmd(ctx):
        try:
            conn = get_db(); cur = conn.cursor()
            cur.execute("""SELECT keyword, baseline_favs, added_at FROM watchlist
                           WHERE discord_id = %s ORDER BY added_at DESC LIMIT 20""", (ctx.author.id,))
            rows = cur.fetchall()
            cur.close(); conn.close()
        except Exception as e:
            await ctx.send(f"⚠️ DB error: {e}"); return
        if not rows:
            await ctx.send("👁️ Your watchlist is empty."); return
        embed = discord.Embed(title=f"👁️ {ctx.author.display_name}'s Watchlist",
                              description=f"Tracking **{len(rows)}** keywords:", color=0x00aaff)
        for kw, baseline, added in rows:
            embed.add_field(name=f"`{kw}`", value=f"Added {added.strftime('%m/%d')}", inline=True)
        await ctx.send(embed=embed)


    @bot.command(name="history")
    async def history_cmd(ctx):
        try:
            conn = get_db(); cur = conn.cursor()
            cur.execute("""SELECT seed, verdict_label, verdict_emoji, created_at
                           FROM saved_consultations WHERE discord_id = %s
                           ORDER BY created_at DESC LIMIT 15""", (ctx.author.id,))
            rows = cur.fetchall()
            cur.close(); conn.close()
        except Exception as e:
            await ctx.send(f"⚠️ DB error: {e}"); return
        if not rows:
            await ctx.send("📖 No consultation history yet. Run `!guide`."); return
        embed = discord.Embed(title=f"📖 {ctx.author.display_name}'s Consultation History",
                              description=f"**{len(rows)}** saved:", color=0xffaa00)
        for seed, label, emoji, when in rows:
            embed.add_field(name=f"{emoji} `{seed}` — {label}",
                            value=when.strftime("%Y-%m-%d %H:%M"), inline=False)
        await ctx.send(embed=embed)


    @bot.command(name="dbtest")
    async def dbtest(ctx):
        try:
            conn = get_db(); cur = conn.cursor()
            lines = []
            for table in ["discovered_items", "items", "item_history",
                          "search_suggestions", "learned_keywords",
                          "user_profiles", "saved_consultations", "watchlist"]:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    lines.append(f"✅ `{table}` — **{cur.fetchone()[0]:,}** rows")
                except Exception:
                    rollback_quietly(cur)
                    lines.append(f"❌ `{table}` — missing")
            try:
                cur.execute("SELECT COUNT(*) FROM items WHERE description IS NOT NULL AND description != ''")
                with_desc = cur.fetchone()[0] or 0
                cur.execute("SELECT COUNT(*) FROM items")
                total = cur.fetchone()[0] or 0
                lines.append(f"\n📝 Descriptions: **{with_desc:,}** of **{total:,}** items")
            except Exception:
                rollback_quietly(cur)
            cur.close(); conn.close()
            embed = discord.Embed(title="🔬 Database Diagnostic",
                                  description="\n".join(lines), color=0x00ff88)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Connection failed: {e}")


    @bot.command(name="scan_status")
    async def scan_status(ctx):
        conn = get_db(); cur = conn.cursor()
        stats = get_db_stats(cur)
        cur.close(); conn.close()
        embed = discord.Embed(title="📡 Market Intelligence Status", color=0x00aaff)
        embed.add_field(name="🔍 IDs Discovered", value=f"**{stats['discovered']:,}**", inline=True)
        embed.add_field(name="📦 Items Analyzed", value=f"**{stats['analyzed']:,}**", inline=True)
        embed.add_field(name="📊 History Snapshots", value=f"**{stats['snapshots']:,}**", inline=True)
        embed.add_field(name="💬 Search Suggestions", value=f"**{stats['suggestions']:,}**", inline=True)
        embed.add_field(name="🧠 Learned Keywords", value=f"**{stats['learned']:,}**", inline=True)
        embed.add_field(name="📖 Past Consultations", value=f"**{stats['consultations']:,}**", inline=True)
        await ctx.send(embed=embed)


    @bot.command(name="trends")
    async def trends(ctx):
        conn = get_db(); cur = conn.cursor()
        cur.execute("""SELECT name, description FROM items WHERE favorite_count > 0 
                       ORDER BY favorite_count DESC LIMIT 1000""")
        rows = cur.fetchall()
        cur.close(); conn.close()
        if not rows:
            await ctx.send("⚠️ No data yet."); return
        counter = Counter()
        for name, desc in rows:
            counter.update(extract_words(name))
            counter.update(extract_words(desc))
        embed = discord.Embed(title="📈 Top Trend Words", color=0xffaa00)
        for i, (w, c) in enumerate(counter.most_common(15), 1):
            embed.add_field(name=f"{i}. {w}", value=f"Appears **{c}** times", inline=False)
        await ctx.send(embed=embed)


    @bot.command(name="analyze")
    async def analyze(ctx, *, keyword: str):
        kw = keyword.strip().lower()
        if not kw:
            await ctx.send("❌ Provide a keyword."); return
        conn = get_db(); cur = conn.cursor()
        pattern = word_boundary_pattern(kw)
        cur.execute("""SELECT name, description, favorite_count FROM items 
                       WHERE (name ~* %s OR COALESCE(description, '') ~* %s) 
                       AND favorite_count > 0 LIMIT 2000""", (pattern, pattern))
        rows = cur.fetchall()
        if not rows:
            await ctx.send(f"⚠️ No data for `{kw}`."); cur.close(); conn.close(); return
        stats = defaultdict(lambda: {"favs": 0, "count": 0})
        for name, desc, favs in rows:
            for w in set(extract_words(f"{name} {desc}")):
                if w == kw: continue
                stats[w]["favs"] += (favs or 0); stats[w]["count"] += 1
        cur.execute("SELECT LOWER(name) FROM items WHERE favorite_count > 0")
        all_names = [r[0] for r in cur.fetchall()]
        word_list = [w for w, s in stats.items() if s["count"] >= 3]
        comp_map = defaultdict(int)
        for name in all_names:
            for w in word_list:
                if re.search(r'\b' + re.escape(w) + r'\b', name):
                    comp_map[w] += 1
        results = []
        for w in word_list:
            s = stats[w]; af = s["favs"] / s["count"]
            c = comp_map.get(w, 1) or 1
            results.append((w, af, c, af / math.log1p(c)))
        cur.close(); conn.close()
        results.sort(key=lambda x: x[3], reverse=True)
        if not results:
            await ctx.send(f"⚠️ Not enough data."); return
        view = SimplePaginator(kw, results, "🧠 Deep Analysis", 0x00ff88, per_page=10)
        embed = view.build_embed()
        embed.description = f"Analyzed **{len(rows)}** items."
        await ctx.send(embed=embed, view=view)


    @bot.command(name="desc_analyze")
    async def desc_analyze(ctx, *, keyword: str):
        kw = keyword.strip().lower()
        if not kw:
            await ctx.send("❌ Provide a keyword."); return
        conn = get_db(); cur = conn.cursor()
        pattern = word_boundary_pattern(kw)
        cur.execute("""SELECT name, COALESCE(description, ''), favorite_count FROM items 
                       WHERE name ~* %s AND description IS NOT NULL AND description != ''
                       AND favorite_count > 0 LIMIT 1500""", (pattern,))
        rows = cur.fetchall()
        if not rows:
            await ctx.send(f"⚠️ No descriptions for `{kw}`."); cur.close(); conn.close(); return
        counter = Counter(); word_favs = defaultdict(int)
        for name, desc, favs in rows:
            for w in set(extract_words(desc)):
                counter[w] += 1; word_favs[w] += favs or 0
        cur.execute("SELECT LOWER(name), COALESCE(LOWER(description), '') FROM items WHERE favorite_count > 0")
        all_rows = cur.fetchall()
        cur.close(); conn.close()
        word_list = [w for w, _ in counter.most_common(80)]
        comp_map = defaultdict(int)
        for name, desc in all_rows:
            text = f"{name} {desc}"
            for w in word_list:
                if re.search(r'\b' + re.escape(w) + r'\b', text):
                    comp_map[w] += 1
        results = []
        for w, count in counter.most_common(80):
            if count < 2: continue
            avg_favs = word_favs[w] / count
            comp = comp_map.get(w, 1) or 1
            results.append((w, avg_favs, comp, avg_favs / math.log1p(comp)))
        results.sort(key=lambda x: x[3], reverse=True)
        if not results:
            await ctx.send(f"⚠️ Not enough data."); return
        view = SimplePaginator(kw, results, "📝 Hidden Description Keywords", 0xaa66ff, per_page=10)
        embed = view.build_embed()
        embed.description = f"Analyzed **{len(rows)}** descriptions."
        await ctx.send(embed=embed, view=view)


    @bot.command(name="opportunity")
    async def opportunity(ctx, *, keyword: str):
        kw = keyword.strip().lower()
        if not kw:
            await ctx.send("❌ Provide a keyword."); return
        conn = get_db(); cur = conn.cursor()
        data = analyze_opportunity(cur, kw)
        cur.close(); conn.close()
        if not data:
            await ctx.send(f"⚠️ No data for `{kw}`."); return
        view = MultiViewPaginator(data)
        await ctx.send(embed=view.build_embed(), view=view)


    @bot.command(name="emote")
    async def emote(ctx, *, keyword: str):
        kw = keyword.strip().lower()
        if not kw:
            await ctx.send("❌ Provide a keyword."); return
        conn = get_db(); cur = conn.cursor()
        data = analyze_opportunity(cur, kw)
        cur.close(); conn.close()
        if not data:
            await ctx.send(f"⚠️ No emote data for `{kw}`."); return
        view = MultiViewPaginator(data)
        await ctx.send(embed=view.build_embed(), view=view)


    @bot.command(name="classic")
    async def classic(ctx, *, keyword: str):
        kw = keyword.strip().lower()
        if not kw:
            await ctx.send("❌ Provide a keyword."); return
        conn = get_db(); cur = conn.cursor()
        data = analyze_opportunity(cur, kw)
        cur.close(); conn.close()
        if not data:
            await ctx.send(f"⚠️ No classic data for `{kw}`."); return
        view = MultiViewPaginator(data)
        await ctx.send(embed=view.build_embed(), view=view)


    @bot.command(name="gap")
    async def gap(ctx, *, keyword: str = ""):
        kw = (keyword or "").strip().lower()
        try:
            conn = get_db(); cur = conn.cursor()

            cur.execute("""
                SELECT name, favorite_count 
                FROM items 
                WHERE favorite_count > 50
                  AND asset_type_id = 61
                LIMIT 5000
            """)
            rows = cur.fetchall()
            if not rows:
                await ctx.send("⚠️ No emote data in DB.")
                cur.close(); conn.close(); return

            stats = defaultdict(lambda: {"favs": 0, "count": 0})
            for name, favs in rows:
                for w in set(extract_words(name)):
                    stats[w]["favs"] += (favs or 0)
                    stats[w]["count"] += 1

            candidates = []
            for w, s in stats.items():
                if s["count"] < 3: continue
                if s["count"] > 100: continue
                af = s["favs"] / s["count"]
                if af < 500: continue
                candidates.append((w, af))

            if not candidates:
                await ctx.send("⚠️ No gaps found.")
                cur.close(); conn.close(); return

            word_list = [c[0] for c in candidates]
            patterns = [f"%{w}%" for w in word_list]
            cur.execute("""
                SELECT LOWER(name) FROM items 
                WHERE favorite_count > 0 
                  AND LOWER(name) LIKE ANY(%s)
            """, (patterns,))
            matched_names = cur.fetchall()
            cur.close(); conn.close()

            comp_map = defaultdict(int)
            for (name,) in matched_names:
                for w in word_list:
                    if re.search(r'\b' + re.escape(w) + r'\b', name):
                        comp_map[w] += 1

            gaps = []
            for w, af in candidates:
                c = comp_map.get(w, 0)
                if c < 1: continue
                if c > 50: continue
                score = af / math.log1p(c)
                if kw and kw not in w.lower():
                    continue
                gaps.append((w, af, c, score))

            if not gaps and kw:
                for w, af in candidates:
                    c = comp_map.get(w, 0)
                    if c < 1 or c > 50: continue
                    score = af / math.log1p(c)
                    gaps.append((w, af, c, score))

            gaps.sort(key=lambda x: x[3], reverse=True)
            if not gaps:
                await ctx.send("⚠️ No gaps found."); return

            gaps = gaps[:30]
            title = f"filter: {kw}" if kw else "all emotes"
            view = SimplePaginator(title, gaps, "🕳️ Market Gaps", 0x00ffcc, per_page=10)
            await ctx.send(embed=view.build_embed(), view=view)
        except Exception as e:
            try:
                await ctx.send(f"❌ Error: {e}")
            except Exception:
                pass


    @bot.command(name="velocity")
    async def velocity(ctx, days: int = 30, limit: int = 15):
        days = max(1, min(days, 90))
        limit = max(1, min(limit, 25))
        try:
            conn = get_db(); cur = conn.cursor()
            cur.execute(f"""
                SELECT i.id, i.name, i.price, i.creator_name, i.asset_type_id,
                       MAX(h.favorite_count) - MIN(h.favorite_count) AS growth,
                       COUNT(h.*) AS snaps
                FROM items i
                JOIN item_history h ON h.item_id = i.id
                WHERE h.snapshot_at >= NOW() - INTERVAL '{days} days'
                  AND i.favorite_count > 50
                GROUP BY i.id, i.name, i.price, i.creator_name, i.asset_type_id
                HAVING COUNT(h.*) >= 2
                   AND MAX(h.favorite_count) - MIN(h.favorite_count) > 0
                ORDER BY growth DESC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()
            cur.close(); conn.close()
        except Exception as e:
            await ctx.send(f"❌ DB error: {e}")
            return

        if not rows:
            await ctx.send(
                f"⚠️ **No growth detected in the last {days} days.**\n\n"
                f"**Possible reasons:**\n"
                f"• Snapshot job hasn't run 2+ times yet\n"
                f"• Items have <2 snapshots\n"
                f"• Growth is real but tiny\n\n"
                f"**Try:** `!velocity 90` for a wider window\n"
                f"**Check:** `!scan_status` — History Snapshots count"
            )
            return

        embed = discord.Embed(
            title=f"🚀 Fastest Rising Items (last {days}d)",
            description=f"Top **{len(rows)}** by favorite growth · all categories",
            color=0xff5500)
        for i, (iid, name, price, creator, atype, growth, snaps) in enumerate(rows, 1):
            price_str = f"{price} R$" if price else "Free"
            type_name = ASSET_TYPE_NAMES.get(atype, f"Type {atype}")
            embed.add_field(
                name=f"{i}. {name[:50]}",
                value=(f"📈 **+{growth:,}** favs · 💰 {price_str} · `{type_name}`\n"
                       f"by {creator or '?'} · `{iid}`"),
                inline=False)
        await ctx.send(embed=embed)


    @bot.command(name="track")
    async def track(ctx, item_id: int):
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT name FROM items WHERE id = %s", (item_id,))
        m = cur.fetchone()
        cur.execute("""SELECT favorite_count, price, snapshot_at FROM item_history 
                       WHERE item_id = %s ORDER BY snapshot_at DESC LIMIT 15""", (item_id,))
        rows = cur.fetchall()
        cur.close(); conn.close()
        if not rows:
            await ctx.send(f"⚠️ No history for `{item_id}`."); return
        title = m[0] if m else f"Item {item_id}"
        embed = discord.Embed(title=f"📊 Tracking: {title[:60]}", color=0x66ccff)
        for favs, price, when in rows:
            embed.add_field(name=f"🕐 {when.strftime('%m/%d %H:%M')}",
                            value=f"Favs: **{favs:,}** | Price: **{price} R$**", inline=False)
        await ctx.send(embed=embed)
