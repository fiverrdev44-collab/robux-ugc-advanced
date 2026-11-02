"""
commands_advanced.py — Advanced analytics commands.
Loaded by discord_ugc_bot.py via register_advanced_commands(bot, get_db).

FIX: family parser accepts BOTH convergence_engine AND category_configs
     family names (headwear, accessory, clothing now work).
ADDED: !converge_debug — diagnostic for stuck scans.
"""
import asyncio

from rising_gaps import (
    find_rising_gaps,
    cross_reference_gaps,
    format_rising_gaps,
    detect_category_from_keyword,
)


def _resolve_family_prefix(text):
    """
    Parse optional "family:keyword" prefix. Returns (family, keyword).
    Accepts both convergence_engine names (emotes, hair, tops) and
    category_configs names (emote, headwear, accessory, clothing).
    """
    from convergence_engine import FAMILIES as _CONV
    from category_configs import CATEGORY_FAMILIES as _CAT

    if not text or ":" not in text:
        return None, text
    maybe_fam, _, rest = text.partition(":")
    fm = maybe_fam.strip().lower()
    if fm in _CONV or fm in _CAT:
        return fm, rest.strip()
    return None, text


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
        """Manually trigger a favorites snapshot from the bot server."""
        progress = await ctx.send("📸 **Running snapshot from the Oracle bot server...**")

        def _run():
            # Do NOT reload the module — reloading bypasses the run lock
            # and can start a second snapshot while one is still running.
            from snapshot import snapshot_top_items
            return snapshot_top_items()

        try:
            ok = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ Snapshot failed: `{e}`")
            return

        if ok is False:
            await progress.edit(
                content="⚠️ **A snapshot is already running** — skipped this trigger."
            )
            return

        try:
            await progress.edit(
                content="✅ **Snapshot complete!** Check the bot logs if anything looks off."
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
            return await ctx.send(
                f"No convergence found for {label}.\n"
                f"Run `!converge_debug movement` to see why."
            )

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
    # 🔬 CONVERGE DEBUG — shows exactly why a keyword fails
    # ────────────────────────────────────────────────────────

    @bot.command(name="converge_debug")
    async def converge_debug_cmd(ctx, *, keyword: str = ""):
        """Diagnose a single keyword. Usage: !converge_debug movement"""
        from convergence_engine import _score_keyword, _family_clause, FAMILIES

        if not keyword.strip():
            return await ctx.send("Usage: `!converge_debug movement`")

        kw = keyword.strip().split()[0]
        family = "emotes"

        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                # 1. Family clause check
                fam_sql, fam_params = _family_clause(family)

                # 2. Raw supply query (no gate)
                from convergence_engine import _kw_pattern
                pat = _kw_pattern(kw)
                is_phrase = " " in kw.strip()
                match_op = "ilike" if is_phrase else "~*"

                cur.execute(f"""
                    select count(*),
                           coalesce(percentile_cont(0.5) within group
                                    (order by favorite_count), 0)
                    from items
                    where name {match_op} %s and favorite_count > 5
                    {fam_sql}
                """, [pat] + fam_params)
                raw = cur.fetchone()
                raw_supply = raw[0] or 0
                raw_median = float(raw[1] or 0)

                # 3. Demand check
                cur.execute(
                    f"select count(*) from search_suggestions "
                    f"where suggestion {match_op} %s",
                    (pat,)
                )
                raw_demand = cur.fetchone()[0] or 0

                # 4. Full score (may pass or reject)
                scored = _score_keyword(cur, kw, family,
                                        min_median=10, min_demand=0,
                                        debug=True)

                # 5. Family context
                fam_ids = FAMILIES.get(family, [])

                # 6. Total emote items in DB
                cur.execute("""
                    select count(*) from items
                    where asset_type_id = 61 and favorite_count > 5
                """)
                total_emotes = cur.fetchone()[0] or 0

                return {
                    "family_sql": fam_sql,
                    "family_ids": fam_ids,
                    "raw_supply": raw_supply,
                    "raw_median": raw_median,
                    "raw_demand": raw_demand,
                    "scored": scored,
                    "total_emotes": total_emotes,
                    "pat": pat,
                    "match_op": match_op,
                }
            finally:
                cur.close(); conn.close()

        try:
            d = await asyncio.to_thread(_run)
        except Exception as e:
            return await ctx.send(f"❌ {e}")

        lines = [
            f"# 🔬 DEBUG — `{kw}` in `{family}`\n",
            f"**Family SQL:** `{d['family_sql'] or '(none)'}`",
            f"**Family IDs:** `{d['family_ids']}`",
            f"**Pattern:** `{d['pat']}` via `{d['match_op']}`",
            f"**Total emote items in DB:** {d['total_emotes']:,}",
            "",
            "**Raw queries (before gates):**",
            f"• Supply: **{d['raw_supply']}** items",
            f"• Median favs: **{d['raw_median']}**",
            f"• Demand: **{d['raw_demand']}** search hits",
            "",
        ]

        if d["scored"]:
            s = d["scored"]
            lines.append("**✅ PASSES with min_median=10, min_demand=0:**")
            lines.append(f"• Final score: **{s['score']}**")
            lines.append(f"• Supply: {s['supply']}")
            lines.append(f"• Demand: {s['demand']}")
            lines.append(f"• Median: {s['avg_favs']}")
            lines.append(f"• Recent: {s['recent']}")
        else:
            lines.append("**❌ REJECTED even with loosest gates**")
            lines.append("Check Server 2 logs for the `[conv-debug]` rejection reason.")

        body = "\n".join(lines)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900])

    # ────────────────────────────────────────────────────────
    # 🔨 DESC FORGE
    # ────────────────────────────────────────────────────────

    @bot.command(name="desc_forge")
    async def desc_forge_cmd(ctx, *, args: str = ""):
        """Mine top descriptions in a niche, generate one that fits."""
        if not args.strip():
            return await ctx.send(
                "**Usage:** `!desc_forge <keyword>` or `!desc_forge <family>:<keyword>`\n"
                "Families: `emote`, `emotes`, `hair`, `headwear`, `hat`, "
                "`face`, `accessory`, `clothing`, `gear`"
            )

        from desc_forge import forge_description, format_forge

        family, keyword = _resolve_family_prefix(args.strip())

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

        try:
            champ = ((result.get("scored_titles") or [{}])[0]
                     .get("title") if result.get("scored_titles") else None)
            if champ:
                from live_market import check_title, format_check
                live = await asyncio.to_thread(check_title, champ)
                live_body = format_check(live)
                if live_body:
                    await ctx.send(live_body[:1900])
                try:
                    from astra import algorithmic_fit_heuristic
                    h = algorithmic_fit_heuristic(
                        live.get("top") or [], champ,
                        asset_type=None,
                        exact_count=live.get("exact") or 0,
                        checked=live.get("results") or 0,
                        results_count=live.get("total")
                        or live.get("results") or 0,
                        ok=bool(live.get("ok")))
                    if h.get("available"):
                        c = h["components"]
                        await ctx.send(
                            f"**Algorithmic Fit Heuristic (not a prediction):** "
                            f"{h['score']}/100 — relevance {c['relevance']}, "
                            f"fit {c['product_fit']}, motion {c['motion_fit']}, "
                            f"differentiation {c['differentiation']}, "
                            f"retrieval {h['checked']}/{h['result_count']}")
                    else:
                        await ctx.send(
                            "**Algorithmic Fit Heuristic:** unavailable "
                            "(live evidence failed)")
                except Exception as he:
                    print(f"[chain] rankability failed: {he}", flush=True)
        except Exception as e:
            print(f"[chain] live marketplace check failed: {e}", flush=True)

    # ────────────────────────────────────────────────────────
    # 🔗 CHAIN
    # ────────────────────────────────────────────────────────

    @bot.command(name="chain")
    async def chain_cmd(ctx, *, args: str = ""):
        """!chain <concept> | !chain variant <id> [theme] | !chain emotes:<concept>"""
        if not args.strip():
            return await ctx.send(
                "**Usage:**\n"
                "  `!chain <concept>` — new item\n"
                "  `!chain variant <item_id>` — variant of a winner\n"
                "  `!chain variant <item_id> <theme>` — variant + theme\n"
                "  `!chain emotes:<concept>` — family scoped\n"
            )

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
            family, concept = _resolve_family_prefix(concept)

        mode_label = "VARIANT" if parent_id else "NEW"
        interactive = getattr(ctx, "vanta_state", None) is not None
        eta = "~30-60s" if parent_id else ("~20-45s" if interactive else "~60-120s")
        progress = await ctx.send(f"🔗 Running chain [{mode_label}]... ({eta})")

        def _run():
            # Conversational runs stay DB-only: live enrichment is the stage
            # that hangs on 429 backoff and blows the chat timeout.
            return run_chain(concept, family=family, parent_id=parent_id,
                             live_enrich=not interactive)

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

    # ────────────────────────────────────────────────────────
    # 🏷️ TAGS
    # ────────────────────────────────────────────────────────

    @bot.command(name="tags")
    async def tags_cmd(ctx, *, args: str = ""):
        """Generate 45 sales-triggering tags. !tags <name> or !tags emotes:<name>"""
        if not args.strip():
            return await ctx.send(
                "**Usage:** `!tags <item name>`\n"
                "Example: `!tags Cute Kawaii Kitty Beanie`\n"
                "With category: `!tags emotes:Smooth Hip Sway Dance`"
            )

        from tag_generator import generate_tags, format_tags

        family, item_name = _resolve_family_prefix(args.strip())

        progress = await ctx.send(f"🏷️ Generating tags for `{item_name[:60]}`...")

        def _run():
            return generate_tags(item_name, family=family, max_tags=45)

        try:
            result = await asyncio.to_thread(_run)
        except Exception as e:
            return await progress.edit(content=f"❌ {e}")

        if result.get("error"):
            return await progress.edit(content=f"❌ {result['error']}")

        chunks = format_tags(result)

        try:
            await progress.delete()
        except Exception:
            pass

        for chunk in chunks:
            for i in range(0, len(chunk), 1900):
                await ctx.send(chunk[i:i+1900])
                await asyncio.sleep(0.2)
