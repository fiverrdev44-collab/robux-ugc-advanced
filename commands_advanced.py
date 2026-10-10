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
        """Find rising-low-competition keywords."""
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
        progress = await ctx.send("📸 **Running snapshot from Render's IP...**")

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
                content="✅ **Snapshot complete!** Check Render logs."
            )
        except Exception:
            pass

    # ────────────────────────────────────────────────────────
    # creative_expand — TEST COMMANDS
    # ────────────────────────────────────────────────────────

    @bot.command(name="creative")
    async def creative_cmd(ctx, *, seed: str = ""):
        """AI fan-out + DB demand gate."""
        if not seed.strip():
            await ctx.send("Usage: `!creative <description or seed keywords>`")
            return

        progress = await ctx.send(f"🧠 **Fanning out on** `{seed}`...")

        def _run():
            from creative_expand import expand_with_validation
            return expand_with_validation(seed, n=20)

        try:
            data = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ Failed: `{e}`")
            return

        results   = data.get("results", [])
        discarded = data.get("discarded", [])
        examples  = data.get("examples", [])

        emoji = {"gold": "🟢", "opportunity": "🔵",
                 "contested": "🟡", "saturated": "🔴"}

        lines = [f"**Creative expansion for** `{seed}`"]
        lines.append(f"_anchored on {len(examples)} real search phrases_\n")

        if results:
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
        else:
            lines.append("⚠️ **Zero concepts passed the gate.**")

        if discarded:
            lines.append(f"\n**🚫 Discarded (0 demand) — {len(discarded)}:**")
            for r in discarded[:8]:
                lines.append(f"  · `{r['concept']}`")
            if len(discarded) > 8:
                lines.append(f"  _...and {len(discarded) - 8} more_")

        lines.append("\n🟢 gold · 🔵 opportunity · 🟡 contested · 🔴 saturated")

        body = "\n".join(lines)
        for i in range(0, len(body), 1900):
            if i == 0:
                await progress.edit(content=body[i:i + 1900])
            else:
                await ctx.send(body[i:i + 1900])
            await asyncio.sleep(0.2)

    @bot.command(name="creative_raw")
    async def creative_raw_cmd(ctx, *, seed: str = ""):
        """Debug: show anchor phrases + raw AI output."""
        if not seed.strip():
            await ctx.send("Usage: `!creative_raw <description or seed keywords>`")
            return

        progress = await ctx.send(f"🔬 **Raw AI fan-out on** `{seed}`...")

        def _run():
            from creative_expand import (
                _fetch_real_suggestions, _call_gemini, _parse, PROMPT
            )
            examples = _fetch_real_suggestions(seed, limit=30)
            block = "\n".join(f"- {e}" for e in examples) or "(none found)"
            prompt = PROMPT.format(seed=seed, n=20, examples=block)
            raw = _call_gemini(prompt)
            parsed = _parse(raw) if raw else []
            return examples, raw, parsed

        try:
            examples, raw, parsed = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ Failed: `{e}`")
            return

        chunks = []

        anchor = f"**🎯 Anchor examples ({len(examples)}) — real Roblox searches:**\n"
        if examples:
            anchor += "\n".join(f"· `{e}`" for e in examples[:15])
            if len(examples) > 15:
                anchor += f"\n_...and {len(examples) - 15} more_"
        else:
            anchor += "_none_"
        chunks.append(anchor)

        raw_block = "**🤖 Raw Gemini output:**\n```\n"
        raw_block += (raw or "<empty>")[:900]
        raw_block += "\n```"
        chunks.append(raw_block)

        parsed_block = f"**📋 Parsed concepts ({len(parsed)}):**\n"
        if parsed:
            parsed_block += "\n".join(f"· `{c}`" for c in parsed)
        else:
            parsed_block += "_nothing parsed_"
        chunks.append(parsed_block)

        first = True
        for chunk in chunks:
            if first:
                try:
                    await progress.edit(content=chunk[:1900])
                except Exception:
                    await ctx.send(chunk[:1900])
                first = False
            else:
                await ctx.send(chunk[:1900])
            await asyncio.sleep(0.3)

    # ────────────────────────────────────────────────────────
    # 🎯 CONVERGENCE
    # ────────────────────────────────────────────────────────

    @bot.command(name="converge")
    async def converge_cmd(ctx, family: str = "all", limit: int = 10):
        """!converge | !converge emotes | !converge all_families"""
        from convergence_engine import scan_convergence, scan_all_families, FAMILIES

        if family == "all_families":
            await ctx.send("🧠 Scanning all categories...")
            try:
                data = await asyncio.to_thread(scan_all_families, 3)
            except Exception as e:
                return await ctx.send(f"❌ {e}")

            for fam, rows in data.items():
                if not rows:
                    continue
                lines = [f"**🎯 `{fam}`**"]
                for i, r in enumerate(rows, 1):
                    snipe = " 🔥" if (r["recent"] == 0 and 5 <= r["supply"] <= 30 and r["velocity"] > 1) else ""
                    lines.append(
                        f"`{r['score']}` **{r['keyword']}**{snipe} — "
                        f"vel {r['velocity']}/d · supply {r['supply']} · recent {r['recent']}"
                    )
                await ctx.send("\n".join(lines)[:1900])
            return

        if family != "all" and family not in FAMILIES:
            valid = ", ".join(FAMILIES.keys())
            return await ctx.send(
                f"❌ Unknown family `{family}`.\n"
                f"Valid: `all`, `all_families`, {valid}"
            )

        label = f"`{family}`" if family != "all" else "all categories"
        await ctx.send(f"🧠 Convergence scan — {label}...")

        try:
            rows = await asyncio.to_thread(scan_convergence, family, limit)
        except Exception as e:
            return await ctx.send(f"❌ {e}")

        if not rows:
            return await ctx.send(f"No convergence found for {label}.")

        lines = [f"**🎯 CONVERGENCE — {label}**\n"
                 "_Weighted: demand · velocity · supply · freshness · competition_\n"]

        for i, r in enumerate(rows, 1):
            snipe = " 🔥 SNIPE ZONE" if (r["recent"] == 0 and 5 <= r["supply"] <= 30 and r["velocity"] > 1) else ""
            lines.append(
                f"**#{i}  [{r['score']}]**  `{r['keyword']}`{snipe}\n"
                f"  📈 demand {r['demand']} · ⚡ vel {r['velocity']}/d\n"
                f"  📦 supply {r['supply']} · 🆕 recent {r['recent']} · "
                f"🎯 avg {r['avg_favs']}♥ · 👑 top {int(r['concentration']*100)}%"
            )

        out = "\n".join(lines)
        for chunk in [out[i:i+1900] for i in range(0, len(out), 1900)]:
            await ctx.send(chunk)

    # ────────────────────────────────────────────────────────
    # 🔨 DESC FORGE
    # ────────────────────────────────────────────────────────

    @bot.command(name="desc_forge")
    async def desc_forge_cmd(ctx, *, args: str = ""):
        """Mine top descriptions in a niche, generate one that fits."""
        if not args.strip():
            return await ctx.send(
                "**Usage:** `!desc_forge <keyword>` or `!desc_forge <family>:<keyword>`"
            )

        from convergence_engine import FAMILIES
        from desc_forge import forge_description, format_forge

        family = None
        keyword = args.strip()
        if ":" in keyword:
            maybe_fam, _, rest = keyword.partition(":")
            if maybe_fam.strip().lower() in FAMILIES:
                family = maybe_fam.strip().lower()
                keyword = rest.strip()

        progress = await ctx.send(f"🔨 Mining top descriptions for `{keyword}`...")

        def _run():
            return forge_description(keyword, family=family)

        try:
            result = await asyncio.to_thread(_run)
        except Exception as e:
            return await progress.edit(content=f"❌ {e}")

        chunks = format_forge(result)

        try:
            await progress.delete()
        except Exception:
            pass

        for chunk in chunks:
            for i in range(0, len(chunk), 1900):
                await ctx.send(chunk[i:i+1900])
                await asyncio.sleep(0.2)

    # ────────────────────────────────────────────────────────
    # 🔗 CHAIN
    # ────────────────────────────────────────────────────────

    @bot.command(name="chain")
    async def chain_cmd(ctx, *, args: str = ""):
        """
        !chain <concept>                     — new item
        !chain variant <parent_item_id>      — variant of existing winner
        !chain variant <id> <theme>          — variant with theme
        !chain emotes:<concept>              — family scoped
        """
        if not args.strip():
            return await ctx.send(
                "**Usage:**\n"
                "  `!chain <concept>` — new item\n"
                "  `!chain variant <item_id>` — variant of a winner\n"
                "  `!chain variant <item_id> <theme>` — variant + theme\n"
                "  `!chain emotes:<concept>` — family scoped\n"
            )

        from convergence_engine import FAMILIES
        from chain import run_chain, format_chain

        tokens = args.strip().split()
        parent_id = None
        concept = None
        family = None

        if tokens and tokens[0].lower() == "variant":
            if len(tokens) < 2 or not tokens[1].isdigit():
                return await ctx.send(
                    "**Variant syntax:** `!chain variant <item_id> [theme]`\n"
                    "Example: `!chain variant 121930221694467 neon`"
                )
            parent_id = int(tokens[1])
            concept = " ".join(tokens[2:]) if len(tokens) > 2 else "variant"
        else:
            concept = args.strip()
            if ":" in concept:
                maybe_fam, _, rest = concept.partition(":")
                if maybe_fam.strip().lower() in FAMILIES:
                    family = maybe_fam.strip().lower()
                    concept = rest.strip()

        mode_label = "VARIANT" if parent_id else "NEW"
        progress = await ctx.send(f"🔗 Running chain [{mode_label}]... (~20s)")

        def _run():
            return run_chain(concept, family=family, parent_id=parent_id)

        try:
            result = await asyncio.to_thread(_run)
        except Exception as e:
            return await progress.edit(content=f"❌ Chain failed: `{e}`")

        if result.get("error"):
            return await progress.edit(content=f"❌ {result['error']}")

        chunks = format_chain(result)

        try:
            await progress.delete()
        except Exception:
            pass

        for chunk in chunks:
            for i in range(0, len(chunk), 1900):
                await ctx.send(chunk[i:i+1900])
                await asyncio.sleep(0.2)
