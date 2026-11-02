"""commands_astra.py — !link and !outcome (Astra Phase 3)."""
import discord


def register_astra_commands(bot, get_db):

    @bot.command(name="link")
    async def link_cmd(ctx, run_id: int, item_id: int):
        """Link a VANTA run to the uploaded asset and snapshot the baseline."""
        from creator_memory import link_run
        conn = get_db(); cur = conn.cursor()
        try:
            res = link_run(cur, run_id, item_id,
                           heuristic_version="astra-fit-v1")
            conn.commit()
            if not res.get("ok"):
                return await ctx.send(f"❌ {res.get('error', 'link failed')}")
            await ctx.send(
                f"🔗 Linked run **{run_id}** to `{item_id}` "
                f"({res.get('name', '?')[:60]}).\n"
                f"Baseline captured: {res['baseline_favorites']}♥ · "
                f"{res['baseline_sales']} recorded sales.\n"
                f"Track it with `!outcome {run_id}`.")
        except Exception as e:
            if "does not exist" in str(e).lower():
                await ctx.send(
                    "Linking needs the Astra outcome tables. Apply "
                    "`migrations/2026-11-02_astra_outcomes.sql` first.")
            else:
                await ctx.send(f"❌ Link failed: `{type(e).__name__}`")
        finally:
            cur.close(); conn.close()

    @bot.command(name="rename")
    async def rename_cmd(ctx, run_id: int, item_id: int):
        """Link a run to an existing item that was just renamed."""
        from creator_memory import link_run
        conn = get_db(); cur = conn.cursor()
        try:
            res = link_run(cur, run_id, item_id,
                           heuristic_version="astra-fit-v1")
            conn.commit()
            if not res.get("ok"):
                return await ctx.send(f"❌ {res.get('error', 'link failed')}")
            await ctx.send(
                "Baseline captured for rename. Tracking D7/D30 favorites "
                "from this exact moment forward.\n"
                f"Run **{run_id}** → `{item_id}` "
                f"({res.get('name', '?')[:60]}) · baseline "
                f"{res['baseline_favorites']}♥ · "
                f"{res['baseline_sales']} recorded sales.")
        except Exception as e:
            if "does not exist" in str(e).lower():
                await ctx.send(
                    "Rename tracking needs the Astra outcome tables. Apply "
                    "`migrations/2026-11-02_astra_outcomes.sql` first.")
            else:
                await ctx.send(f"❌ Rename link failed: `{type(e).__name__}`")
        finally:
            cur.close(); conn.close()

    @bot.command(name="outcome")
    async def outcome_cmd(ctx, run_id: int):
        """Report favorites and units gained since the linked launch."""
        from creator_memory import outcome_report
        conn = get_db(); cur = conn.cursor()
        try:
            data = outcome_report(cur, run_id)
            if not data.get("found"):
                return await ctx.send(
                    f"No linked outcome for run **{run_id}**. "
                    f"Use `!link {run_id} <item_id>` after uploading the item.")
            await ctx.send(data["message"])
            if data.get("d7_favorites") is None:
                await ctx.send(
                    "_No D7 snapshot yet; the delta uses the latest snapshot. "
                    "Snapshots fill via `!snapshot_now` / the scheduler._")
        except Exception as e:
            if "does not exist" in str(e).lower():
                await ctx.send(
                    "Outcome tables are missing. Apply "
                    "`migrations/2026-11-02_astra_outcomes.sql` first.")
            else:
                await ctx.send(f"❌ Outcome lookup failed: `{type(e).__name__}`")
        finally:
            cur.close(); conn.close()
