"""
commands_advanced.py — Advanced analytics commands.
Loaded by discord_ugc_bot.py via register_advanced_commands(bot, get_db).
"""
import asyncio

from rising_gaps import (
    find_rising_gaps,
    cross_reference_gaps,
    format_rising_gaps,
    detect_category_from_keyword,
)


def register_advanced_commands(bot, get_db):

    @bot.command(name="rising_gaps")
    async def rising_gaps_cmd(ctx, *, args: str = ""):
        """
        Find rising-low-competition keywords.

        Auto-detects category from your seed keyword.

        Usage:
          !rising_gaps                      → all categories, 14 days
          !rising_gaps 30                   → 30-day window
          !rising_gaps hip sway dance       → auto-detects EMOTE
          !rising_gaps crown                → auto-detects HAT
          !rising_gaps necklace             → auto-detects ACCESSORY
          !rising_gaps emote 30             → explicit category + window
        """
        days = 14
        category = None
        seed = ""
        explicit_cat = False

        tokens = (args or "").strip().split()
        valid_cats = ["emote", "hat", "hair", "face", "accessory",
                      "shirt", "pants", "jacket", "gear"]

        for t in tokens:
            tl = t.lower()
            try:
                days = int(t)
            except ValueError:
                if tl in valid_cats and not category:
                    category = tl
                    explicit_cat = True
                else:
                    seed = (seed + " " + t).strip()

        # Auto-detect category from seed if not explicitly set
        if not category and seed:
            detected = detect_category_from_keyword(seed)
            if detected:
                category = detected

        days = max(3, min(days, 60))
        cat_label = category or "all"

        if category and seed and not explicit_cat:
            hint = f"auto-detected **{category}**"
        else:
            hint = cat_label

        progress = await ctx.send(
            f"🌱 **Scanning rising gaps — {hint} ({days}d)...**"
        )

        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                result = find_rising_gaps(cur, days=days, category=category)
                if seed and result.get("candidates"):
                    result["candidates"] = cross_reference_gaps(
                        cur, seed.lower(), result["candidates"]
                    )
                return result
            finally:
                cur.close(); conn.close()

        try:
            result = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ Failed: `{e}`")
            return

        try:
            await progress.delete()
        except Exception:
            pass

        body = format_rising_gaps(result, seed=seed if seed else None)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i + 1900])
            await asyncio.sleep(0.3)
            
    @bot.command(name="momentum_debug")
    async def momentum_debug(ctx):
        """Diagnostic: what's actually in item_history."""
        progress = await ctx.send("🔍 **Running momentum debug...**")

        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT
                        COUNT(*) AS total_snaps,
                        COUNT(DISTINCT item_id) AS unique_items,
                        MIN(snapshot_at) AS earliest,
                        MAX(snapshot_at) AS latest,
                        EXTRACT(EPOCH FROM (MAX(snapshot_at) - MIN(snapshot_at)))/86400 AS days_span
                    FROM item_history
                """)
                r = cur.fetchone()

                cur.execute("""
                    SELECT COUNT(*) FROM (
                        SELECT item_id FROM item_history
                        GROUP BY item_id
                        HAVING COUNT(*) >= 2
                    ) sub
                """)
                multi_snap_items = cur.fetchone()[0] or 0

                cur.execute("""
                    SELECT COUNT(*) FROM (
                        SELECT item_id FROM item_history
                        GROUP BY item_id
                        HAVING MAX(favorite_count) - MIN(favorite_count) > 5
                    ) sub
                """)
                growing_items = cur.fetchone()[0] or 0

                return r, multi_snap_items, growing_items
            finally:
                cur.close(); conn.close()

        try:
            r, multi_snap_items, growing_items = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ Debug failed: `{e}`")
            return

        try:
            await progress.delete()
        except Exception:
            pass

        msg = (
            f"**🔍 MOMENTUM DEBUG**\n"
            f"- Total snapshots: **{r[0]:,}**\n"
            f"- Unique items snapshotted: **{r[1]:,}**\n"
            f"- Items with 2+ snapshots: **{multi_snap_items:,}**\n"
            f"- Items with fav growth >5: **{growing_items:,}**\n"
            f"- Earliest snapshot: `{r[2]}`\n"
            f"- Latest snapshot: `{r[3]}`\n"
            f"- Time span (days): **{float(r[4] or 0):.2f}**"
        )
        await ctx.send(msg)
