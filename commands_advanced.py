"""
commands_advanced.py — Advanced analytics commands.
Loaded by discord_ugc_bot.py via register_advanced_commands(bot, get_db).
"""
import asyncio

from rising_gaps import find_rising_gaps, cross_reference_gaps, format_rising_gaps


def register_advanced_commands(bot, get_db):

    @bot.command(name="rising_gaps")
    async def rising_gaps_cmd(ctx, *, args: str = ""):
        """
        Find keywords that are RISING but still low-competition.
        Usage:
          !rising_gaps              → 14-day window
          !rising_gaps 30           → 30-day window
          !rising_gaps hip sway     → cross-reference with seed keyword
        """
        days = 14
        seed = ""

        args = (args or "").strip()
        if args:
            parts = args.split()
            # Try to parse first token as an integer
            try:
                days = int(parts[0])
                seed = " ".join(parts[1:]) if len(parts) > 1 else ""
            except ValueError:
                # No number, so the whole string is a seed
                seed = args

        days = max(3, min(days, 60))
        progress = await ctx.send(f"🌱 **Scanning for rising gaps ({days}d window)...**")

        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                result = find_rising_gaps(cur, days=days)
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
