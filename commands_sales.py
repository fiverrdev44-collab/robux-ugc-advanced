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
    async def sales_backfill_cmd(ctx, limit: int = 200):
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
            from sales_listener import auto_backfill
            progress = await ctx.send("🧾 Syncing recent sales, then building report...")
            await auto_backfill(bot, limit=500)
        except Exception as e:
            return await ctx.send(f"❌ Backfill failed: {e}")

        try:
            data = await asyncio.to_thread(analyze_sales, 7)
        except Exception as e:
            return await ctx.send(f"❌ {e}")

        report = format_report(data)
        for i in range(0, len(report), 1900):
            await ctx.send(report[i:i+1900])
            await asyncio.sleep(0.2)
        try:
            await progress.edit(content="✅ Report posted above (sales synced first).")
        except Exception:
            pass

    @bot.command(name="sales_probe")
    async def sales_probe_cmd(ctx, *, item: str = ""):
        """Probe Roblox sales APIs for an item (diagnostic)."""
        import requests
        from bot_core import get_db

        if not item.strip():
            return await ctx.send(
                "Usage: `!sales_probe Smooth 360 flip Rizz` or `!sales_probe <item_id>`"
            )

        item_id = None
        item_name = item
        if item.strip().isdigit():
            item_id = int(item.strip())
        else:
            conn = get_db()
            cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT id, name FROM items
                    WHERE lower(name) LIKE lower(%s)
                    ORDER BY favorite_count DESC
                    LIMIT 1
                """, (f"%{item.strip()[:40]}%",))
                row = cur.fetchone()
                if row:
                    item_id, item_name = row
            finally:
                cur.close()
                conn.close()

        if not item_id:
            return await ctx.send(f"❌ Could not resolve `{item}` to an item ID.")

        cookie = (
            os.getenv("ROBLOSECURITY_COOKIE_1")
            or os.getenv("ROBLOSECURITY_COOKIE")
            or ""
        ).strip()

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.roblox.com/",
            "Origin": "https://www.roblox.com",
        }
        if cookie:
            headers["Cookie"] = f".ROBLOSECURITY={cookie}"

        urls = [
            ("economy/v1",
             f"https://economy.roblox.com/v1/assets/{item_id}/sales",
             {"limit": 100}),
            ("economy/v2",
             f"https://economy.roblox.com/v2/assets/{item_id}/sales",
             {"limit": 100}),
            ("creator-analytics",
             f"https://apis.roblox.com/creator-analytics/v1/items/{item_id}/sales",
             {"limit": 100}),
            ("creator-analytics-metrics",
             f"https://apis.roblox.com/creator-analytics/v1/items/{item_id}/metrics",
             {}),
            ("analytics",
             f"https://apis.roblox.com/analytics/v1/items/{item_id}/sales",
             {"limit": 100}),
            ("transactions",
             f"https://apis.roblox.com/transactions/v1/assets/{item_id}/sales",
             {"limit": 100}),
        ]

        def _probe():
            out = []
            for label, url, params in urls:
                try:
                    r = requests.get(url, params=params, headers=headers, timeout=10)
                    body = r.text[:240].replace("\n", " ")
                    out.append((label, r.status_code, body))
                except Exception as e:
                    out.append((label, "ERR", f"{type(e).__name__}: {e}"[:240]))
            return out

        results = await asyncio.to_thread(_probe)

        lines = [
            f"🔎 **SALES PROBE** — `{item_name}` (id `{item_id}`)",
            f"Cookie: {'✅ set' if cookie else '❌ not set'}",
            "",
        ]
        for label, status, body in results:
            icon = "✅" if status == 200 else "❌"
            lines.append(f"{icon} `{label}` → {status}\n`{body}`")
        await ctx.send("\n".join(lines)[:1900])

    @bot.command(name="group_metrics", aliases=["gmetrics"])
    async def group_metrics_cmd(
        ctx,
        group_id: int,
        metric: str = "ItemTotalCreatorEarning",
        days: int = 90,
        limit: int = 20,
    ):
        """Fetch Roblox group analytics (per-item metric) for a group."""
        import json
        import requests
        from datetime import datetime, timedelta, timezone
        from bot_core import get_db

        cookie = (
            os.getenv("ROBLOSECURITY_COOKIE_1")
            or os.getenv("ROBLOSECURITY_COOKIE")
            or ""
        ).strip()
        if not cookie:
            return await ctx.send("❌ ROBLOSECURITY cookie is not set on the server.")

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=max(1, min(days, 365)))
        limit = max(1, min(limit, 100))

        payload = {
            "resourceType": "RESOURCE_TYPE_GROUP",
            "resourceId": str(group_id),
            "query": {
                "metric": metric,
                "granularity": "METRIC_GRANULARITY_NONE",
                "breakdown": [{"dimensions": ["AvatarItemId"]}],
                "startTime": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "endTime": end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "limit": limit,
            },
        }
        url = (
            "https://apis.roblox.com/analytics-query-gateway/v1/metrics/"
            f"resource/RESOURCE_TYPE_GROUP/id/{group_id}"
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://create.roblox.com/",
            "Origin": "https://create.roblox.com",
            "Cookie": f".ROBLOSECURITY={cookie}",
        }

        def _get_csrf():
            try:
                r = requests.post(
                    "https://auth.roblox.com/v2/logout",
                    headers=headers,
                    timeout=10,
                )
                return (
                    r.headers.get("x-csrf-token")
                    or r.headers.get("X-CSRF-Token")
                )
            except Exception:
                return None

        def _post():
            r = requests.post(url, json=payload, headers=headers, timeout=15)
            if r.status_code == 403 and "xsrf" in r.text.lower():
                token = (
                    r.headers.get("x-csrf-token")
                    or r.headers.get("X-CSRF-Token")
                    or _get_csrf()
                )
                if token:
                    h2 = dict(headers)
                    h2["X-CSRF-TOKEN"] = token
                    r = requests.post(url, json=payload, headers=h2, timeout=15)
            return r.status_code, r.text

        status, text = await asyncio.to_thread(_post)
        if status != 200:
            return await ctx.send(
                f"❌ Gateway returned **{status}** for `{metric}`:\n"
                f"```{text[:400]}```"
            )

        try:
            data = json.loads(text)
        except Exception as e:
            return await ctx.send(f"❌ Bad JSON: {e}")

        values = (
            data.get("operation", {})
                .get("queryResult", {})
                .get("values", [])
        )
        rows = []
        for v in values:
            bd = v.get("breakdownValue") or []
            item_id = bd[0].get("value") if bd else None
            for dp in (v.get("dataPoints") or []):
                rows.append((item_id, int(dp.get("value") or 0)))

        if not rows:
            return await ctx.send(
                f"📊 No data for `{metric}` (group `{group_id}`). "
                f"The metric name may be wrong."
            )

        ids = []
        for item_id, _ in rows:
            try:
                ids.append(int(item_id))
            except Exception:
                pass
        names = {}
        if ids:
            conn = get_db()
            cur = conn.cursor()
            try:
                cur.execute("SELECT id, name FROM items WHERE id = ANY(%s)", (ids,))
                names = {i: n for i, n in cur.fetchall()}
            finally:
                cur.close()
                conn.close()

        rows.sort(key=lambda x: -x[1])
        total = sum(v for _, v in rows)

        lines = [
            f"📊 **GROUP METRICS** — group `{group_id}`",
            f"Metric: `{metric}` · last **{days}** days",
            f"Total: **{total:,}**",
            "",
        ]
        for item_id, val in rows[:limit]:
            nm = names.get(int(item_id), "") if item_id else ""
            label = f"{nm[:40]} (`{item_id}`)" if nm else f"`{item_id}`"
            lines.append(f"• {label} — **{val:,}**")

        await ctx.send("\n".join(lines)[:1900])

    @bot.command(name="cookie_check")
    async def cookie_check_cmd(ctx):
        """Verify the server-side Roblox cookie and show which account it is."""
        import json
        import requests

        cookie = (
            os.getenv("ROBLOSECURITY_COOKIE_1")
            or os.getenv("ROBLOSECURITY_COOKIE")
            or ""
        ).strip()
        if not cookie:
            return await ctx.send("❌ ROBLOSECURITY cookie is not set on the server.")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Cookie": f".ROBLOSECURITY={cookie}",
        }

        def _check():
            r = requests.get(
                "https://users.roblox.com/v1/users/authenticated",
                headers=headers,
                timeout=10,
            )
            return r.status_code, r.text

        status, text = await asyncio.to_thread(_check)
        if status != 200:
            return await ctx.send(
                f"❌ **Cookie invalid** (status {status}).\n"
                f"```{text[:200]}```\n"
                f"Stored cookie length: `{len(cookie)}` — re-paste the full cookie."
            )

        try:
            data = json.loads(text)
        except Exception:
            data = {}

        name = data.get("name", "?")
        uid = data.get("id", "?")
        lines = [
            "✅ **Cookie valid**",
            f"Account: **{name}** (id `{uid}`)",
            f"Stored cookie length: `{len(cookie)}`",
        ]

        # Best-effort group membership check.
        try:
            def _groups():
                r = requests.get(
                    f"https://groups.roblox.com/v1/users/{uid}/groups",
                    headers=headers,
                    timeout=10,
                )
                return r.status_code, r.text

            gs, gt = await asyncio.to_thread(_groups)
            if gs == 200:
                gd = json.loads(gt)
                groups = gd.get("data", gd) if isinstance(gd, dict) else gd
                ids = set()
                if isinstance(groups, list):
                    for g in groups:
                        grp = g.get("group", g) if isinstance(g, dict) else {}
                        gid = grp.get("id") if isinstance(grp, dict) else None
                        if gid:
                            ids.add(str(gid))
                lines.append(
                    f"Groups: **{len(ids)}** · contains 181575178: "
                    f"{'✅' if '181575178' in ids else '❌'}"
                )
        except Exception:
            pass

        await ctx.send("\n".join(lines)[:1900])

    @bot.command(name="sales_debug")
    async def sales_debug_cmd(ctx):
        """Diagnose why sales aren't showing: dates, timezone, channel config."""
        from bot_core import get_db

        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT current_setting('TimeZone'), now(),
                       (now() AT TIME ZONE 'UTC')::date
            """)
            tz, now_ts, utc_today = cur.fetchone()

            cur.execute("""
                SELECT count(*), min(sale_date), max(sale_date)
                FROM my_sales
            """)
            total, min_d, max_d = cur.fetchone()

            cur.execute("""
                SELECT sale_date, count(*), coalesce(sum(amount_robux), 0)
                FROM my_sales
                GROUP BY sale_date
                ORDER BY sale_date DESC
                LIMIT 7
            """)
            by_date = cur.fetchall()

            cur.execute("""
                SELECT sale_time, sale_date, item_name, amount_robux
                FROM my_sales
                ORDER BY sale_time DESC
                LIMIT 5
            """)
            recent = cur.fetchall()
        finally:
            cur.close()
            conn.close()

        ch = os.getenv("SALES_CHANNEL_ID", "").strip()
        lines = [
            "🩺 **SALES DEBUG**",
            f"DB timezone: `{tz}`",
            f"now: `{now_ts}`",
            f"UTC today: `{utc_today}`",
            f"SALES_CHANNEL_ID: `{ch or 'NOT SET'}`",
            f"Rows: **{total}** · dates `{min_d}` → `{max_d}`",
            "",
            "**By date:**",
        ]
        for d, units, robux in by_date:
            lines.append(f"• {d} — {units} · R${robux:,}")
        lines.append("")
        lines.append("**Latest 5:**")
        for st, sd, name, amt in recent:
            lines.append(f"• `{(name or '')[:30]}` — {sd} · {st} · R${amt}")

        await ctx.send("\n".join(lines)[:1900])

    @bot.command(name="sales_scan")
    async def sales_scan_cmd(ctx, limit: int = 50):
        """Scan SALES_CHANNEL_ID and report embed formats (diagnostic)."""
        from sales_listener import _extract_sale_from_embed

        ch_id = os.getenv("SALES_CHANNEL_ID", "").strip()
        if not ch_id:
            return await ctx.send("❌ `SALES_CHANNEL_ID` is not set.")

        try:
            ch = bot.get_channel(int(ch_id))
        except Exception:
            ch = None
        if not ch:
            return await ctx.send(
                f"❌ Channel `{ch_id}` not found or not visible to the bot."
            )

        limit = max(1, min(limit, 200))
        scanned = embeds = matched = 0
        samples = []
        newest_ts = oldest_ts = None
        sale_dates = {}

        async for msg in ch.history(limit=limit):
            scanned += 1
            ts = msg.created_at
            if newest_ts is None or ts > newest_ts:
                newest_ts = ts
            if oldest_ts is None or ts < oldest_ts:
                oldest_ts = ts
            for e in (msg.embeds or []):
                embeds += 1
                try:
                    sale = _extract_sale_from_embed(e, msg)
                except Exception as ex:
                    if len(samples) < 5:
                        samples.append((f"ERROR {type(ex).__name__}", []))
                    continue
                if sale:
                    matched += 1
                    d = str(sale["sale_date"])
                    sale_dates[d] = sale_dates.get(d, 0) + 1
                elif len(samples) < 5:
                    samples.append((
                        (e.title or "(no title)")[:70],
                        [f.name for f in (e.fields or [])][:6],
                    ))

        lines = [
            "🔍 **SALES SCAN**",
            f"Channel: <#{ch_id}>",
            f"Messages: **{scanned}** · Embeds: **{embeds}** · "
            f"Matched sales: **{matched}**",
            f"Msg range: `{oldest_ts}` → `{newest_ts}`",
        ]
        if sale_dates:
            recent = sorted(sale_dates.items(), reverse=True)[:7]
            lines.append("**Parsed sale dates:**")
            for d, n in recent:
                lines.append(f"• {d} — {n}")
        if samples:
            lines.append("\n**Unmatched embed samples:**")
            for title, fields in samples:
                lines.append(f"• `{title}` · fields={fields}")
        else:
            lines.append("\n_No unmatched embeds in this window._")

        await ctx.send("\n".join(lines)[:1900])
