"""
commands_ugc.py — Master `!ugc` command + supporting commands.

!ugc            — runs EVERYTHING in one shot: sync, monitor, pulse, briefing, jarvis
!ugc sync       — force portfolio sync only
!ugc brief      — briefing only
!ugc ai         — jarvis only
!portfolio      — list tracked items (clothing excluded)
!pulse          — raw pulse
!events         — event log
"""
import os
import asyncio
import discord
from discord.ext import tasks
from bot_core import get_db


def register_ugc_commands(bot, get_db):

    async def _send_long(ctx, body):
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900])
            await asyncio.sleep(0.3)

    async def _do_sync(ctx):
        from portfolio_tracker import refresh_portfolio, purge_excluded
        cookie = os.getenv("ROBLOSECURITY_COOKIE_1") or os.getenv("ROBLOSECURITY_COOKIE")
        uid = os.getenv("ROBLOX_USER_ID")
        if not uid:
            return "❌ `ROBLOX_USER_ID` not set in Render env vars."

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

    @bot.command(name="ugc")
    async def ugc_cmd(ctx, sub: str = ""):
        sub = (sub or "").lower().strip()

        # ── !ugc sync ──
        if sub == "sync":
            progress = await ctx.send("📡 **Syncing portfolio...**")
            msg = await _do_sync(ctx)
            try: await progress.delete()
            except Exception: pass
            await ctx.send(msg)
            return

        # ── !ugc brief ──
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

        # ── !ugc ai ──
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

        # ── !ugc  (full run) ──
        progress = await ctx.send("🩺 **Full portfolio analysis...**")

        # 1. Sync silently
        sync_msg = await _do_sync(ctx)

        # 2. Pulse
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

        # ── Header ──
        header = []
        header.append("```")
        header.append("╔══════════════════════════════════════════════════════════╗")
        header.append("║       U G C   C O M M A N D   C E N T E R                ║")
        header.append("║       Post-Monitor · Briefing · AI Strategist            ║")
        header.append("╚══════════════════════════════════════════════════════════╝")
        header.append("```")
        await _send_long(ctx, "\n".join(header))

        # ── Live pulse ──
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

        # ── Recent events ──
        if events:
            e_lines = ["# 📜 EVENTS — 24h\n"]
            emoji = {"critical": "🔴", "warning": "🟡", "info": "🔵"}
            for e in events[:12]:
                em = emoji.get(e["severity"], "⚪")
                t = e["at"].strftime("%m-%d %H:%M") if e["at"] else "?"
                e_lines.append(f"{em} `{t}` **{e['type'].replace('_',' ').title()}** — {e['message']}")
            await _send_long(ctx, "\n".join(e_lines))
            await asyncio.sleep(0.5)

        # ── Briefing (rule-based decisions) ──
        from ugc_watchdog import run_watchdog, format_briefing
        try:
            bdata = await asyncio.to_thread(run_watchdog, get_db)
            await _send_long(ctx, format_briefing(bdata))
        except Exception as e:
            await ctx.send(f"⚠️ Briefing failed: `{e}`")
        await asyncio.sleep(0.5)

        # ── Jarvis (AI strategist) ──
        from jarvis import run_jarvis, format_jarvis_report
        try:
            jdata = await asyncio.to_thread(run_jarvis, get_db)
            await _send_long(ctx, format_jarvis_report(jdata))
        except Exception as e:
            await ctx.send(f"⚠️ JARVIS failed: `{e}`")

    # ── Auto-runners (silent, post to ALERT_CHANNEL_ID on change) ──
    @tasks.loop(hours=1)
    async def auto_watchdog():
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
            alert, sig = should_alert(data, auto_watchdog._last_sig)
            auto_watchdog._last_sig = sig
            if alert:
                await channel.send(format_briefing(data))
        except Exception as e:
            print(f"[auto_watchdog] {e}", flush=True)

    @bot.event
    async def on_ready():
        if not auto_watchdog.is_running():
            auto_watchdog._last_sig = None
            auto_watchdog.start()
            print("🩺 [ugc] auto watchdog started", flush=True)
