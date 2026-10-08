"""
commands_ugc.py — Master `!ugc` command + all portfolio commands.

!ugc            — runs EVERYTHING: sync, pulse, events, briefing, jarvis
!ugc sync       — force portfolio sync only
!ugc brief      — briefing only
!ugc ai         — jarvis only
!portfolio      — list tracked items
!pulse [hours]  — raw pulse
!events [hours] — event log
!mystats        — aggregate stats
"""
import os
import asyncio
import discord
from bot_core import get_db


def register_ugc_commands(bot, get_db):

    async def _send_long(ctx, body):
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900])
            await asyncio.sleep(0.3)

    async def _do_sync(ctx):
        from portfolio_tracker import refresh_portfolio, purge_excluded
        cookie = os.getenv("ROBLOSECURITY_COOKIE_1") or os.getenv("ROBLOSECURITY_COOKIE")
        uid = os.getenv("ROBLOX_USER_ID") or None
        gids = os.getenv("ROBLOX_GROUP_IDS", "").strip()
        if not uid and not gids:
            return "❌ Neither `ROBLOX_USER_ID` nor `ROBLOX_GROUP_IDS` set in Render env vars."

        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                purged = purge_excluded(cur)
                items = refresh_portfolio(cur, cookie, uid)
                return purged, items
            finally:
                cur.close(); conn.close()

        try:
            purged, items = await asyncio.to_thread(_run)
        except Exception as e:
            return f"❌ Sync failed: `{e}`"

        msg = f"✅ Synced **{len(items)}** items"
        if purged:
            msg += f" · purged {purged} clothing rows"
        return msg

    # ─────────────────────────────────────────────────────────
    # !ugc  (master)
    # ─────────────────────────────────────────────────────────
    @bot.command(name="ugc")
    async def ugc_cmd(ctx, sub: str = ""):
        sub = (sub or "").lower().strip()

        if sub == "sync":
            progress = await ctx.send("📡 **Syncing portfolio...**")
            msg = await _do_sync(ctx)
            try: await progress.delete()
            except Exception: pass
            await ctx.send(msg)
            return

        if sub == "brief":
            from ugc_watchdog import run_watchdog, format_briefing
            progress = await ctx.send("🩺 **Analyzing...**")
            try:
                data = await asyncio.to_thread(run_watchdog, get_db)
            except Exception as e:
                await progress.edit(content=f"❌ {e}"); return
            try: await progress.delete()
            except Exception: pass
            await _send_long(ctx, format_briefing(data))
            return

        if sub == "ai":
            from jarvis import run_jarvis, format_jarvis_report
            progress = await ctx.send("🤖 **JARVIS analyzing...**")
            try:
                data = await asyncio.to_thread(run_jarvis, get_db)
            except Exception as e:
                await progress.edit(content=f"❌ {e}"); return
            try: await progress.delete()
            except Exception: pass
            await _send_long(ctx, format_jarvis_report(data))
            return

        # ── Full run ──
        progress = await ctx.send("🩺 **Full portfolio analysis...**")

        sync_msg = await _do_sync(ctx)

        from post_monitor import get_pulse, get_recent_events
        try:
            pulse = await asyncio.to_thread(get_pulse, get_db, 24)
            events = await asyncio.to_thread(get_recent_events, get_db, 24)
        except Exception as e:
            await progress.edit(content=f"❌ {e}"); return

        try: await progress.delete()
        except Exception: pass

        await ctx.send(f"**{sync_msg}**")
        await asyncio.sleep(0.5)

        header = [
            "```",
            "╔══════════════════════════════════════════════════════════╗",
            "║       U G C   C O M M A N D   C E N T E R                ║",
            "║       Post-Monitor · Briefing · AI Strategist            ║",
            "╚══════════════════════════════════════════════════════════╝",
            "```",
        ]
        await _send_long(ctx, "\n".join(header))

        if pulse:
            items_sorted = sorted(pulse, key=lambda x: -(x["sales_24h"] * 1000 + x["fav_velocity"]))
            tot_s = sum(i["sales_24h"] for i in pulse)
            tot_r = sum(i["revenue_24h"] for i in pulse)
            tot_f = sum(i["favs"] for i in pulse)

            p_lines = ["# 📡 LIVE PULSE — 24h\n"]
            p_lines.append(f"**{len(pulse)} items** · **{tot_s}** sales · **R${tot_r:,}** revenue · **{tot_f:,}** favs\n")
            for i, it in enumerate(items_sorted, 1):
                tag = "🔥" if it["sales_24h"] > 0 and it["sales_6h"] > 0 else (
                    "⚡" if it["fav_velocity"] >= 20 else (
                        "💤" if it["sales_24h"] == 0 and it["favs"] > 0 else ""))
                p_lines.append(
                    f"**{i}. {tag} `{it['name'][:42]}`**\n"
                    f"   Favs **{it['favs']:,}** (+{it['fav_velocity']}) · "
                    f"Sales **{it['sales_24h']}** (1h {it['sales_1h']} / 6h {it['sales_6h']})\n"
                    f"   Revenue **R${it['revenue_24h']:,}** · Conv **{it['conversion_pct']}%** · R${it['price']}"
                )
            await _send_long(ctx, "\n".join(p_lines))
        else:
            await ctx.send("# 📡 PULSE\n_No items. Publish one and re-run `!ugc sync`._")
            return

        await asyncio.sleep(0.5)

        if events:
            e_lines = ["# 📜 EVENTS — 24h\n"]
            emoji = {"critical": "🔴", "warning": "🟡", "info": "🔵"}
            for e in events[:12]:
                em = emoji.get(e["severity"], "⚪")
                t = e["at"].strftime("%m-%d %H:%M") if e["at"] else "?"
                e_lines.append(f"{em} `{t}` **{e['type'].replace('_',' ').title()}** — {e['message']}")
            await _send_long(ctx, "\n".join(e_lines))
            await asyncio.sleep(0.5)

        from ugc_watchdog import run_watchdog, format_briefing
        try:
            bdata = await asyncio.to_thread(run_watchdog, get_db)
            await _send_long(ctx, format_briefing(bdata))
        except Exception as e:
            await ctx.send(f"⚠️ Briefing failed: `{e}`")
        await asyncio.sleep(0.5)

        from jarvis import run_jarvis, format_jarvis_report
        try:
            jdata = await asyncio.to_thread(run_jarvis, get_db)
            await _send_long(ctx, format_jarvis_report(jdata))
        except Exception as e:
            await ctx.send(f"⚠️ JARVIS failed: `{e}`")

    # ─────────────────────────────────────────────────────────
    # !portfolio — list tracked items
    # ─────────────────────────────────────────────────────────
    @bot.command(name="portfolio")
    async def portfolio_cmd(ctx):
        progress = await ctx.send("📁 **Loading portfolio...**")

        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                from portfolio_tracker import get_portfolio
                return get_portfolio(cur)
            finally:
                cur.close(); conn.close()

        try:
            items = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ {e}"); return

        try: await progress.delete()
        except Exception: pass

        if not items:
            await ctx.send("# 📁 PORTFOLIO\n\nNo items tracked.\nRun `!ugc sync` first.")
            return

        lines = [f"# 📁 PORTFOLIO — {len(items)} items\n"]
        for i, it in enumerate(items[:25], 1):
            lines.append(f"**{i}. `{it['name'][:50]}`** — `{it['id']}`")
        if len(items) > 25:
            lines.append(f"\n_+{len(items) - 25} more_")
        await _send_long(ctx, "\n".join(lines))

    # ─────────────────────────────────────────────────────────
    # !pulse — raw pulse
    # ─────────────────────────────────────────────────────────
    @bot.command(name="pulse")
    async def pulse_cmd(ctx, hours: int = 24):
        from post_monitor import get_pulse
        hours = max(1, min(int(hours), 168))
        progress = await ctx.send(f"📡 **Pulling pulse (last {hours}h)...**")

        try:
            items = await asyncio.to_thread(get_pulse, get_db, hours)
        except Exception as e:
            await progress.edit(content=f"❌ {e}"); return

        try: await progress.delete()
        except Exception: pass

        if not items:
            await ctx.send("# 📡 PULSE\n\nNo items. Run `!ugc sync` first.")
            return

        items.sort(key=lambda x: -(x["sales_24h"] * 1000 + x["fav_velocity"]))
        total_s = sum(i["sales_24h"] for i in items)
        total_r = sum(i["revenue_24h"] for i in items)
        total_f = sum(i["favs"] for i in items)

        lines = [f"# 📡 PULSE — last {hours}h\n"]
        lines.append(f"**{len(items)} items** · **{total_s}** sales · **R${total_r:,}** · **{total_f:,}** favs\n")

        for i, it in enumerate(items, 1):
            tag = "🔥" if it["sales_24h"] > 0 and it["sales_6h"] > 0 else (
                "⚡" if it["fav_velocity"] >= 20 else (
                    "💤" if it["sales_24h"] == 0 and it["favs"] > 0 else ""))
            lines.append(
                f"**{i}. {tag} `{it['name'][:45]}`**\n"
                f"   Favs **{it['favs']:,}** (+{it['fav_velocity']}/24h)\n"
                f"   Sales **{it['sales_24h']}** (1h {it['sales_1h']} · 6h {it['sales_6h']})\n"
                f"   Revenue **R${it['revenue_24h']:,}** · Conv **{it['conversion_pct']}%**"
            )
            lines.append("")
        await _send_long(ctx, "\n".join(lines))

    # ─────────────────────────────────────────────────────────
    # !events — event log
    # ─────────────────────────────────────────────────────────
    @bot.command(name="events")
    async def events_cmd(ctx, hours: int = 24):
        from post_monitor import get_recent_events
        hours = max(1, min(int(hours), 168))
        progress = await ctx.send("📜 **Loading events...**")

        try:
            events = await asyncio.to_thread(get_recent_events, get_db, hours)
        except Exception as e:
            await progress.edit(content=f"❌ {e}"); return

        try: await progress.delete()
        except Exception: pass

        if not events:
            await ctx.send(f"# 📜 EVENTS — {hours}h\n\nNo events.")
            return

        emoji = {"critical": "🔴", "warning": "🟡", "info": "🔵"}
        lines = [f"# 📜 EVENT LOG — {hours}h\n"]
        for e in events:
            em = emoji.get(e["severity"], "⚪")
            t = e["at"].strftime("%m-%d %H:%M") if e["at"] else "?"
            lines.append(f"{em} `{t}` **{e['type'].replace('_', ' ').title()}** — {e['message']}")
        await _send_long(ctx, "\n".join(lines))

    # ─────────────────────────────────────────────────────────
    # !mystats — aggregate stats
    # ─────────────────────────────────────────────────────────
    @bot.command(name="mystats")
    async def mystats_cmd(ctx):
        progress = await ctx.send("📈 **Computing stats...**")

        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                from portfolio_tracker import get_portfolio
                items = get_portfolio(cur)
                stats = []
                for it in items:
                    cur.execute("SELECT favorite_count, total_sales FROM items WHERE id = %s",
                                (it["id"],))
                    r = cur.fetchone()
                    if r:
                        stats.append({
                            "name": it["name"],
                            "favs": r[0] or 0,
                            "sales": r[1] or 0,
                        })
                return stats
            finally:
                cur.close(); conn.close()

        try:
            stats = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ {e}"); return

        try: await progress.delete()
        except Exception: pass

        if not stats:
            await ctx.send("# 📈 STATS\n\nNo items tracked.")
            return

        favs = [s["favs"] for s in stats]
        total_f = sum(favs)
        total_s = sum(s["sales"] for s in stats)
        stats.sort(key=lambda s: s["favs"], reverse=True)

        lines = ["# 📈 PORTFOLIO STATS\n"]
        lines.append(f"• Items: **{len(stats)}**")
        lines.append(f"• Total favs: **{total_f:,}**")
        lines.append(f"• Avg favs: **{total_f // len(stats):,}**")
        lines.append(f"• Total sales: **{total_s}**")
        lines.append("")
        lines.append(f"**🥇 Best:** `{stats[0]['name'][:50]}` — {stats[0]['favs']:,} favs, {stats[0]['sales']} sales")
        lines.append(f"**💀 Worst:** `{stats[-1]['name'][:50]}` — {stats[-1]['favs']:,} favs, {stats[-1]['sales']} sales")
        await _send_long(ctx, "\n".join(lines))


# ─────────────────────────────────────────────────────────────
# Auto-watchdog loop — started from discord_ugc_bot.py on_ready
# ─────────────────────────────────────────────────────────────
_auto_watchdog_task = None


def start_ugc_loops(bot):
    """Called from discord_ugc_bot.on_ready to start the auto-watchdog."""
    global _auto_watchdog_task

    if _auto_watchdog_task and _auto_watchdog_task.is_running():
        return

    from discord.ext import tasks
    from bot_core import get_db
    import os

    @tasks.loop(hours=1)
    async def _watchdog_loop():
        try:
            ch_id = int(os.getenv("ALERT_CHANNEL_ID", "0"))
            if not ch_id:
                return
            channel = bot.get_channel(ch_id)
            if not channel:
                return

            from ugc_watchdog import run_watchdog, format_briefing, should_alert
            data = await asyncio.to_thread(run_watchdog, get_db)
            if not data or data.get("error"):
                return

            last_sig = getattr(_watchdog_loop, "_last_sig", None)
            alert, sig = should_alert(data, last_sig)
            _watchdog_loop._last_sig = sig

            if alert:
                body = format_briefing(data)
                for i in range(0, len(body), 1900):
                    await channel.send(body[i:i+1900])
        except Exception as e:
            print(f"[ugc_watchdog_loop] {e}", flush=True)

    _watchdog_loop._last_sig = None
    _watchdog_loop.start()
    _auto_watchdog_task = _watchdog_loop
