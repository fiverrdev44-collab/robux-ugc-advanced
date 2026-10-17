"""
post_monitor.py — CSV-based sales monitor.

Runs daily via scheduler. Reads my_sales table.
Computes: today's sales, weekly trend, top items, spikes, silent items.
Posts report to ALERT_CHANNEL_ID.

NOT the old API version (that was blocked).
This version reads CSV data you upload.
"""
import asyncio
from datetime import datetime, timezone
from bot_core import get_db


def analyze_sales(days=7):
    conn = get_db(); cur = conn.cursor()
    try:
        # Today
        cur.execute("""
            select count(*), coalesce(sum(amount_robux), 0)
            from my_sales where sale_date = (now() AT TIME ZONE 'UTC')::date
        """)
        today_units, today_robux = cur.fetchone()

        # Last 24h — timezone-agnostic sanity check. If "today" is 0 but this
        # is non-zero, the issue is a day-boundary/timezone mismatch; if both
        # are 0, the sales were never captured in my_sales.
        cur.execute("""
            select count(*), coalesce(sum(amount_robux), 0)
            from my_sales
            where sale_time >= now() - interval '24 hours'
        """)
        last24_units, last24_robux = cur.fetchone()

        # This week (last 7 days, excl today)
        cur.execute("""
            select count(*), coalesce(sum(amount_robux), 0)
            from my_sales
            where sale_date >= (now() AT TIME ZONE 'UTC')::date - interval '7 days'
              and sale_date < (now() AT TIME ZONE 'UTC')::date
        """)
        week_units, week_robux = cur.fetchone()

        # Prev week
        cur.execute("""
            select count(*), coalesce(sum(amount_robux), 0)
            from my_sales
            where sale_date >= (now() AT TIME ZONE 'UTC')::date - interval '14 days'
              and sale_date < (now() AT TIME ZONE 'UTC')::date - interval '7 days'
        """)
        prev_units, prev_robux = cur.fetchone()

        # Top items
        cur.execute("""
            select item_name, count(*), coalesce(sum(amount_robux), 0)
            from my_sales
            where sale_date >= (now() AT TIME ZONE 'UTC')::date - interval '7 days'
            group by item_name
            order by 3 desc limit 5
        """)
        top_items = cur.fetchall()

        # Spikes (2x their 7d avg, min 3 sales)
        cur.execute("""
            with t as (
                select item_name, count(*)::float as u
                from my_sales where sale_date = (now() AT TIME ZONE 'UTC')::date
                group by item_name
            ),
            a as (
                select item_name, count(*)::float / 7 as avg_u
                from my_sales
                where sale_date >= (now() AT TIME ZONE 'UTC')::date - interval '7 days'
                  and sale_date < (now() AT TIME ZONE 'UTC')::date
                group by item_name
            )
            select t.item_name, t.u, a.avg_u
            from t join a on a.item_name = t.item_name
            where t.u >= a.avg_u * 2 and t.u >= 3
            order by t.u desc
        """)
        spikes = cur.fetchall()

        # Silent items (sold last week, not this week)
        cur.execute("""
            with p as (
                select distinct item_name from my_sales
                where sale_date >= (now() AT TIME ZONE 'UTC')::date - interval '14 days'
                  and sale_date < (now() AT TIME ZONE 'UTC')::date - interval '7 days'
            ),
            w as (
                select distinct item_name from my_sales
                where sale_date >= (now() AT TIME ZONE 'UTC')::date - interval '7 days'
            )
            select p.item_name from p
            where p.item_name not in (select item_name from w)
            limit 10
        """)
        silent = [r[0] for r in cur.fetchall()]

        trend = "flat"
        if week_units and prev_units:
            if week_units > prev_units * 1.15:
                trend = "up"
            elif week_units < prev_units * 0.85:
                trend = "down"

        return {
            "today_units": today_units or 0, "today_robux": today_robux or 0,
            "week_units": week_units or 0, "week_robux": week_robux or 0,
            "prev_units": prev_units or 0, "prev_robux": prev_robux or 0,
            "top_items": top_items, "spikes": spikes, "silent": silent,
            "trend": trend,
            "report_date": datetime.now(timezone.utc).date().isoformat(),
            "last24_units": last24_units or 0,
            "last24_robux": last24_robux or 0,
        }
    finally:
        cur.close(); conn.close()


def format_report(data):
    t = {"up": "📈", "down": "📉", "flat": "➡️"}[data["trend"]]

    lines = [
        f"# 📡 POST MONITOR — daily report (UTC {data.get('report_date', '')})\n",
        f"## Today\n"
        f"• **{data['today_units']}** sales · **R${data['today_robux']:,}**\n",
        f"## Week {t} vs last week\n"
        f"• This week: **{data['week_units']}** · **R${data['week_robux']:,}**\n"
        f"• Last week: {data['prev_units']} · R${data['prev_robux']:,}",
    ]

    if data["week_units"] and data["prev_units"]:
        pct = ((data["week_units"] - data["prev_units"]) / data["prev_units"]) * 100
        sign = "+" if pct >= 0 else ""
        lines.append(f"• Change: **{sign}{pct:.0f}%**")

    if data["top_items"]:
        lines.append("\n## 🏆 Top items")
        for name, units, robux in data["top_items"]:
            lines.append(f"• `{name[:45]}` — {units} · R${robux:,}")

    if data["spikes"]:
        lines.append("\n## 🚀 Spikes (2x+ their avg)")
        for name, units, avg in data["spikes"]:
            lines.append(f"• `{name[:45]}` — {int(units)} today (avg {avg:.1f})")

    if data["silent"]:
        lines.append("\n## 🪦 Silent (stopped selling)")
        for name in data["silent"][:5]:
            lines.append(f"• `{name[:45]}`")

    if not data["today_units"] and not data["week_units"]:
        lines.append("\n_No data. Run `!sales_backfill` first._")
    elif not data["today_units"] and data.get("last24_units"):
        lines.append(
            f"\n_Last 24h: **{data['last24_units']}** sales · "
            f"R${data['last24_robux']:,} (UTC day boundary)_"
        )

    return "\n".join(lines)


async def send_daily_report(bot, channel_id):
    try:
        channel = bot.get_channel(int(channel_id))
        if not channel:
            print(f"[post_monitor] channel {channel_id} not found", flush=True)
            return
        data = await asyncio.to_thread(analyze_sales, 7)
        report = format_report(data)
        for i in range(0, len(report), 1900):
            await channel.send(report[i:i+1900])
        print("[post_monitor] daily report sent", flush=True)
    except Exception as e:
        print(f"[post_monitor] failed: {e}", flush=True)
