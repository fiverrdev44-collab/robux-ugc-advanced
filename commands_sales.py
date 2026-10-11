"""
commands_sales.py — !sales_report, !sales_for, !sales_backfill, !sales_post_now.

Sales come from sales_listener.py (reads Discord webhook embeds).
"""
import asyncio
import os
import discord


def register_sales_commands(bot, get_db):

    @bot.command(name="sales_report")
    async def sales_report_cmd(ctx, days: int = 30):
        """Revenue summary: top items, daily trend."""
        from sales_listener import sales_summary

        days = max(1, min(days, 365))
        progress = await ctx.send(f"📊 Building {days}-day sales report...")

        try:
            data = await asyncio.to_thread(sales_summary, days)
        except Exception as e:
            return await progress.edit(content=f"❌ {e}")

        if not data["total_units"]:
            return await progress.edit(
                content=(
                    f"📊 No sales data for last {days} days.\n"
                    f"Run `!sales_backfill` to import past sales from "
                    f"the sales channel."
                )
            )

        lines = [
            f"# 📊 SALES REPORT — last {days} days",
            f"**Units:** {data['total_units']:,}  ·  "
            f"**Robux:** R${data['total_robux']:,}",
            "",
        ]

        if data["top_items"]:
            lines.append("## 🏆 Top items")
            for name, units, robux in data["top_items"]:
                lines.append(f"• `{name[:45]}` — {units} units · R${robux:,}")
            lines.append("")

        if data["daily"]:
            lines.append("## 📅 Daily (most recent 14)")
            for d, units, robux in data["daily"][:14]:
                lines.append(f"• {d} — {units} sales · R${robux}")

        body = "\n".join(lines)
        try:
            await progress.edit(content=body[:1900])
        except Exception:
            await ctx.send(body[:1900])
        if len(body) > 1900:
            for i in range(1900, len(body), 1900):
                await ctx.send(body[i:i+1900])
                await asyncio.sleep(0.2)

    @bot.command(name="sales_for")
    async def sales_for_cmd(ctx, *, item_name: str = ""):
        """Sales for a specific item by name (fuzzy)."""
        from sales_listener import item_sales_summary

        if not item_name.strip():
            return await ctx.send("Usage: `!sales_for Smooth 360 flip Rizz`")

        try:
            data = await asyncio.to_thread(item_sales_summary, item_name, 30)
        except Exception as e:
            return await ctx.send(f"❌ {e}")

        if not data:
            return await ctx.send(
                f"No sales found for `{item_name}` in last 30 days."
            )

        await ctx.send(
            f"**📊 Sales for `{item_name[:50]}`** (last 30 days)\n"
            f"• Units: **{data['units']}**\n"
            f"• Robux: **R${data['robux']:,}**\n"
            f"• Last sale: {data['last_sale']}"
        )

    @bot.command(name="sales_backfill")
    async def sales_backfill_cmd(ctx, limit: int = 500):
        """
        Read past sale notifications from SALES_CHANNEL_ID and import them.
        !sales_backfill          → last 500 messages
        !sales_backfill 2000     → last 2000 messages
        """
        from sales_listener import backfill_channel

        sales_ch_id = os.getenv("SALES_CHANNEL_ID", "").strip()
        if not sales_ch_id:
            return await ctx.send(
                "❌ `SALES_CHANNEL_ID` env var is not set on Render.\n"
                "Add it, redeploy, then run this command."
            )

        limit = max(10, min(limit, 5000))
        progress = await ctx.send(
            f"🔍 Scanning last {limit} messages in sales channel..."
        )

        try:
            scanned, saved = await backfill_channel(bot, sales_ch_id, limit=limit)
        except Exception as e:
            return await progress.edit(content=f"❌ {e}")

        await progress.edit(
            content=(
                f"✅ **Backfill complete**\n"
                f"• Scanned messages: **{scanned}**\n"
                f"• New sales imported: **{saved}**\n"
                f"\nRun `!sales_report` to see totals."
            )
        )

    @bot.command(name="sales_post_now")
    async def sales_post_now_cmd(ctx):
        """Manually trigger today's post-monitor report."""
        from post_monitor import analyze_sales, format_report

        try:
            data = await asyncio.to_thread(analyze_sales, 7)
        except Exception as e:
            return await ctx.send(f"❌ {e}")

        report = format_report(data)
        for i in range(0, len(report), 1900):
            await ctx.send(report[i:i+1900])
            await asyncio.sleep(0.2)
