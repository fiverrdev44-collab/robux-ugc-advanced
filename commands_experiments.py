"""commands_experiments.py — applied/ignored/measure commands."""
import asyncio


def register_experiment_commands(bot, get_db):
    @bot.command(name="applied", aliases=["apply_rec"])
    async def applied_cmd(ctx, rec_id: str = "last"):
        """Mark a recommendation as applied. Use `last` for the newest one."""
        def _do():
            conn = get_db(); cur = conn.cursor()
            try:
                from experiments import mark_applied, mark_latest
                if rec_id.strip().lower() in ("last", "latest"):
                    row, err = mark_latest(cur)
                else:
                    try:
                        rid = int(rec_id)
                    except ValueError:
                        return None, "use a number or `last`"
                    row, err = mark_applied(cur, rid)
                conn.commit()
                return row, err
            finally:
                cur.close(); conn.close()

        row, err = await asyncio.to_thread(_do)
        if err:
            return await ctx.send(f"❌ Experiment `{rec_id}`: {err}")
        await ctx.send(
            f"✅ **Experiment #{row['id']} applied.**\n"
            f"Measuring on **{row['measure_at']:%Y-%m-%d %H:%M UTC}**.\n"
            f"_No ID needed next time: `!applied last`._"
        )

    @bot.command(name="ignored", aliases=["skip_rec"])
    async def ignored_cmd(ctx, rec_id: str = "last"):
        """Mark a recommendation as ignored. Use `last` for the newest one."""
        def _do():
            conn = get_db(); cur = conn.cursor()
            try:
                from experiments import mark_ignored, mark_latest_ignored
                if rec_id.strip().lower() in ("last", "latest"):
                    row, err = mark_latest_ignored(cur)
                else:
                    try:
                        rid = int(rec_id)
                    except ValueError:
                        return None, "use a number or `last`"
                    row, err = mark_ignored(cur, rid)
                conn.commit()
                return row, err
            finally:
                cur.close(); conn.close()

        row, err = await asyncio.to_thread(_do)
        if err:
            return await ctx.send(f"❌ Experiment `{rec_id}`: {err}")
        await ctx.send(f"⏭️ Experiment `#{row}` marked ignored.")

    @bot.command(name="experiments", aliases=["labs", "results"])
    async def experiments_cmd(ctx, limit: int = 10):
        """Show recommendation outcomes and measure anything due."""
        limit = max(1, min(limit, 25))

        def _do():
            conn = get_db(); cur = conn.cursor()
            try:
                from experiments import (auto_apply_changes, measure_due,
                                         summary, format_summary)
                from matched_experiments import evaluate_due, recent_lines
                auto_applied = auto_apply_changes(cur)
                measured = measure_due(cur)
                did_done = evaluate_due(cur)
                conn.commit()
                data = summary(cur, limit=limit)
                body = format_summary(data)
                extra = recent_lines(cur)
                if extra:
                    body += extra
                return auto_applied, measured, did_done, body
            finally:
                cur.close(); conn.close()

        auto_applied, measured, did_done, body = await asyncio.to_thread(_do)
        notes = []
        if auto_applied:
            notes.append(f"auto-applied {auto_applied} changed item(s)")
        if measured:
            notes.append(f"measured {measured} due experiment(s)")
        if did_done:
            notes.append(f"evaluated {did_done} matched comparison(s)")
        if notes:
            body = "_" + "; ".join(notes) + "._\n\n" + body
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900])
            await asyncio.sleep(0.2)
