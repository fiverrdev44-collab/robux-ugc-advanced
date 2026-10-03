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

    @bot.command(name="snapshot_now")
    async def snapshot_now_cmd(ctx):
        """Manually trigger snapshot from the bot's own IP (Render)."""
        progress = await ctx.send("📸 **Running snapshot from Render's IP...**\n"
                                  "_Testing if the bot's own IP avoids rate limits..._")

        def _run():
            import importlib
            import snapshot as snap_mod
            importlib.reload(snap_mod)
            snap_mod.snapshot_top_items()
            return True

        try:
            await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ Snapshot failed: `{e}`")
            return

        try:
            await progress.edit(
                content="✅ **Snapshot complete!**\n"
                        "Check Render logs for the `Fetched X/Y` line.\n"
                        "If success > 80% → scale back to 1000 items."
            )
        except Exception:
            pass
