"""commands_visibility.py — search visibility coverage and collection."""
import asyncio


def register_visibility_commands(bot, get_db):
    @bot.command(name="visibility")
    async def visibility_cmd(ctx):
        """Show search visibility coverage and freshness."""
        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                from search_visibility import coverage, format_coverage
                return format_coverage(coverage(cur))
            finally:
                cur.close(); conn.close()

        try:
            body = await asyncio.to_thread(_run)
        except Exception as e:
            return await ctx.send(f"❌ Visibility report failed: `{type(e).__name__}`")
        await ctx.send(body[:1900])

    @bot.command(name="visibility_seed")
    async def visibility_seed_cmd(ctx, limit: int = 50):
        """Seed visibility queries from live search suggestions."""
        limit = max(1, min(limit, 200))

        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                from search_visibility import seed_queries
                added = seed_queries(cur, limit=limit)
                conn.commit()
                return added
            finally:
                cur.close(); conn.close()

        try:
            added = await asyncio.to_thread(_run)
        except Exception as e:
            return await ctx.send(f"❌ Visibility seed failed: `{type(e).__name__}`")
        await ctx.send(f"✅ Seeded visibility queries: **{added}**")

    @bot.command(name="visibility_run")
    async def visibility_run_cmd(ctx, limit: int = 20):
        """Collect up to N due search-visibility queries now."""
        limit = max(1, min(limit, 100))

        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                from search_visibility import collect
                done = collect(cur, limit=limit)
                conn.commit()
                return done
            finally:
                cur.close(); conn.close()

        try:
            done = await asyncio.to_thread(_run)
        except Exception as e:
            return await ctx.send(f"❌ Visibility run failed: `{type(e).__name__}`")
        await ctx.send(f"✅ Collected **{done}** visibility query run(s).")
