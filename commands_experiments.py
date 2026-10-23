"""commands_experiments.py — applied/ignored/measure commands."""
import asyncio


def register_experiment_commands(bot, get_db):
    @bot.command(name="applied", aliases=["apply_rec"])
    async def applied_cmd(ctx, rec_id: int):
        """Mark a recommendation as applied and start the 7-day measurement."""
        def _do():
            conn = get_db(); cur = conn.cursor()
            try:
                from experiments import mark_applied
                row, err = mark_applied(cur, rec_id)
                conn.commit()
                return row, err
            finally:
                cur.close(); conn.close()

        row, err = await asyncio.to_thread(_do)
        if err:
            return await ctx.send(f"❌ Experiment `#{rec_id}`: {err}")
        await ctx.send(
            f"✅ **Experiment #{row['id']} applied.**\n"
            f"Measuring on **{row['measure_at']:%Y-%m-%d %H:%M UTC}**.\n"
            f"_Run `!experiments` after that date._"
        )

    @bot.command(name="ignored", aliases=["skip_rec"])
    async def ignored_cmd(ctx, rec_id: int):
        """Mark a recommendation as ignored."""
        def _do():
            conn = get_db(); cur = conn.cursor()
            try:
                from experiments import mark_ignored
                row, err = mark_ignored(cur, rec_id)
                conn.commit()
                return row, err
            finally:
                cur.close(); conn.close()

        row, err = await asyncio.to_thread(_do)
        if err:
            return await ctx.send(f"❌ Experiment `#{rec_id}`: {err}")
        await ctx.send(f"⏭️ Experiment `#{rec_id}` marked ignored.")

    @bot.command(name="experiments", aliases=["labs", "results"])
    async def experiments_cmd(ctx, limit: int = 10):
        """Show recommendation outcomes and measure anything due."""
        limit = max(1, min(limit, 25))

        def _do():
            conn = get_db(); cur = conn.cursor()
            try:
                from experiments import measure_due, summary, format_summary
                measured = measure_due(cur)
                conn.commit()
                data = summary(cur, limit=limit)
                return measured, data, format_summary(data)
            finally:
                cur.close(); conn.close()

        measured, data, body = await asyncio.to_thread(_do)
        if measured:
            body = f"_Measured {measured} due experiment(s)._\n\n" + body
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900])
            await asyncio.sleep(0.2)
