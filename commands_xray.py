"""
commands_xray.py — Market introspection commands.

Commands:
    !xray                — full market snapshot dashboard
    !early [days]        — early winners list only
    !patterns [family]   — top statistical patterns by lift ratio
    !failures [family]   — words that correlate with low-fav items

Family argument:
    emote | hair | headwear | face | accessory | clothing | bundle | gear
    OR "all" / "*" / "every" for cross-catalog mining
"""
import asyncio
import discord
from bot_core import get_db
from market_xray import build_xray, format_xray
from pattern_forge import (
    mine_patterns, mine_failure_patterns,
    format_patterns, format_failure_patterns,
)
from early_winners import find_early_winners, format_early_winners


_ALL_TOKENS = {"all", "*", "every", "any", ""}


def _resolve_family(raw):
    f = (raw or "").lower().strip()
    if f in _ALL_TOKENS:
        return None
    return f


def register_xray_commands(bot, get_db):

    @bot.command(name="xray")
    async def xray_cmd(ctx):
        progress = await ctx.send("🩻 **Rendering full market X-ray...**")

        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                return build_xray(cur)
            finally:
                cur.close(); conn.close()

        try:
            data = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ X-ray failed: `{e}`")
            return

        try: await progress.delete()
        except Exception: pass

        body = format_xray(data)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900])
            await asyncio.sleep(0.3)

    @bot.command(name="early")
    async def early_cmd(ctx, days: int = 14):
        days = max(3, min(int(days), 30))
        progress = await ctx.send(f"⚡ **Scanning for early winners (last {days}d)...**")

        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                return find_early_winners(cur, days=days)
            finally:
                cur.close(); conn.close()

        try:
            results = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ Failed: `{e}`")
            return

        try: await progress.delete()
        except Exception: pass

        body = format_early_winners(results, days=days)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900])
            await asyncio.sleep(0.3)

    @bot.command(name="patterns")
    async def patterns_cmd(ctx, family: str = "emote"):
        target = _resolve_family(family)
        label = "all categories" if target is None else target
        progress = await ctx.send(f"🧪 **Mining statistical patterns in `{label}`...**")

        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                return mine_patterns(cur, family=target, min_sample=25, top_n=25)
            finally:
                cur.close(); conn.close()

        try:
            results = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ Pattern mining failed: `{e}`")
            return

        try: await progress.delete()
        except Exception: pass

        body = format_patterns(results, label)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900])
            await asyncio.sleep(0.3)

    @bot.command(name="failures")
    async def failures_cmd(ctx, family: str = "emote"):
        target = _resolve_family(family)
        label = "all categories" if target is None else target
        progress = await ctx.send(f"⚠️ **Mining failure patterns in `{label}`...**")

        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                return mine_failure_patterns(cur, family=target, min_sample=25, top_n=15)
            finally:
                cur.close(); conn.close()

        try:
            results = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ Failure mining failed: `{e}`")
            return

        try: await progress.delete()
        except Exception: pass

        body = format_failure_patterns(results)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900])
            await asyncio.sleep(0.3)
