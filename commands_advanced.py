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

    # ────────────────────────────────────────────────────────
    # creative_expand — TEST COMMANDS (Step 1)
    # Remove after wiring into brainstorm/autopsy.
    # ────────────────────────────────────────────────────────

    @bot.command(name="creative")
    async def creative_cmd(ctx, *, seed: str = ""):
        """
        Test: AI fan-out + DB demand gate.
        Usage: !creative rhythm step sway dance
        """
        if not seed.strip():
            await ctx.send("Usage: `!creative <description or seed keywords>`")
            return

        progress = await ctx.send(f"🧠 **Fanning out on** `{seed}`...")

        def _run():
            from creative_expand import expand_with_validation
            return expand_with_validation(seed, n=20)

        try:
            results = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ Failed: `{e}`")
            return

        if not results:
            await progress.edit(
                content=f"❌ **Nothing passed the demand gate.**\n"
                        f"Either the AI returned junk, or every concept had 0 demand.\n"
                        f"Try `!creative_raw {seed}` to inspect raw output."
            )
            return

        emoji = {
            "gold": "🟢",
            "opportunity": "🔵",
            "contested": "🟡",
            "saturated": "🔴",
        }
        lines = [f"**Creative expansion for** `{seed}`\n"]
        for r in results[:15]:
            lines.append(
                f"{emoji.get(r['verdict'], '⚪')} **{r['concept']}** "
                f"— demand `{r['demand']}` / supply `{r['supply']}`"
            )

        counts = {}
        for r in results:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        summary = " · ".join(
            f"{emoji[k]}{v}" for k, v in counts.items() if k in emoji
        )

        lines.append(f"\n{summary}")
        lines.append("🟢 gold · 🔵 opportunity · 🟡 contested · 🔴 saturated")
        lines.append("_Hallucinated concepts (0 demand) auto-discarded._")

        await progress.edit(content="\n".join(lines))

    @bot.command(name="creative_raw")
    async def creative_raw_cmd(ctx, *, seed: str = ""):
        """
        Debug: show what the AI generated BEFORE the demand gate.
        Useful when !creative returns nothing or looks narrow.
        Usage: !creative_raw rhythm step sway dance
        """
        if not seed.strip():
            await ctx.send("Usage: `!creative_raw <description or seed keywords>`")
            return

        progress = await ctx.send(f"🔬 **Raw AI fan-out on** `{seed}`...")

        def _run():
            from creative_expand import _call_gemini, _parse, PROMPT
            raw = _call_gemini(PROMPT.format(seed=seed, n=20))
            parsed = _parse(raw) if raw else []
            return raw, parsed

        try:
            raw, parsed = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ Failed: `{e}`")
            return

        body = "**RAW Gemini output:**\n```\n"
        body += (raw or "<empty>")[:1200]
        body += "\n```\n\n**Parsed concepts (before demand gate):**\n"

        if parsed:
            body += "\n".join(f"• `{c}`" for c in parsed)
        else:
            body += "_nothing parsed — JSON likely malformed, check raw above_"

        body += f"\n\n_(used model: check Render logs or GEMINI_MODEL env)_"

        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i + 1900])
            await asyncio.sleep(0.3)

        try:
            await progress.delete()
        except Exception:
            pass
