"""
commands_intel.py — All intel commands. Category-aware autopsy.

VERDICT: multi-signal (sales + age + favs + velocity + percentile).
AUTOPSY: peer comparison + statistical ranking + tag merge + FINAL block.
DETERMINISM: pivot picked from data, tracked, consistency-checked.

Uses tag_generator.py for the tag block (not description_engine).
Title scoring runs via asyncio.to_thread (no heartbeat blocking).
"""
import os
import re
import json
import asyncio
from datetime import datetime

from momentum import find_momentum_keywords, format_momentum_report
from predictor import predict_success, format_prediction
from oracle import (forecast_trend, format_oracle_forecast,
                    find_next_wave_opportunities, format_next_wave)
from opportunity_feed import build_daily_feed, format_daily_feed
from recovery_brain import (
    detect_failure_mode, format_recovery_report,
    fetch_user_sales, enrich_item_stats_with_sales,
    fetch_item_from_roblox, save_item_to_db,
    save_item_and_created_at, fetch_created_date_live,
    classify_competition_batch, format_keyword_classifications,
)
from category_configs import (
    detect_family_from_asset_type, get_category_config,
)

from intel_common import (
    item_percentile,
    decide_verdict,
    classify_keyword,
    portfolio_context,
)


def _build_per_word_competition(cur, words, cap=6):
    result = []
    for w in words[:cap]:
        try:
            pattern = rf"\y{re.escape(w)}\y"
            cur.execute("""
                SELECT
                    COUNT(*) AS comp,
                    COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY favorite_count), 0) AS median_favs,
                    COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price), 0) AS median_price
                FROM items
                WHERE LOWER(name) ~* %s AND favorite_count > 5
            """, (pattern,))
            row = cur.fetchone()
            cur.execute("""
                SELECT count(*),
                       count(*) filter (where seed_keyword is distinct from %s),
                       coalesce(sum(search_volume) filter
                                (where seed_keyword is distinct from %s), 0)
                FROM search_suggestions
                WHERE suggestion ~* %s
            """, ("__db_mined__", "__db_mined__", pattern))
            demand_row = cur.fetchone() or (0, 0, 0)
            if row:
                demand_live = int(demand_row[1] or 0)
                demand_all = int(demand_row[0] or 0)
                result.append({
                    "keyword": w,
                    "comp": int(row[0] or 0),
                    "median_favs": int(row[1] or 0),
                    "median_price": int(row[2] or 0),
                    "demand": demand_live or demand_all,
                    "demand_live": demand_live,
                    "demand_volume": int(demand_row[2] or 0),
                    "demand_reliable": demand_live > 0,
                })
        except Exception as e:
            print(f"[autopsy] per-word query failed for '{w}': {e}", flush=True)
    return result


def register_intel_commands(bot, get_db, ASSET_TYPE_NAMES):

    @bot.command(name="momentum_debug")
    async def momentum_debug(ctx):
        """Show momentum engine diagnostics."""
        progress = await ctx.send("🔍 **Running momentum debug...**")

        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT COUNT(*), COUNT(DISTINCT item_id),
                           MIN(snapshot_at), MAX(snapshot_at),
                           EXTRACT(EPOCH FROM (MAX(snapshot_at) - MIN(snapshot_at)))/86400
                    FROM item_history
                """)
                r = cur.fetchone()
                cur.execute("""SELECT COUNT(*) FROM (
                    SELECT item_id FROM item_history GROUP BY item_id HAVING COUNT(*) >= 2
                ) sub""")
                multi = cur.fetchone()[0] or 0
                cur.execute("""SELECT COUNT(*) FROM (
                    SELECT item_id FROM item_history GROUP BY item_id
                    HAVING MAX(favorite_count) - MIN(favorite_count) > 5
                ) sub""")
                growing = cur.fetchone()[0] or 0
                return r, multi, growing
            finally:
                cur.close(); conn.close()

        try:
            r, multi, growing = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ Debug failed: `{e}`"); return
        try: await progress.delete()
        except Exception: pass

        await ctx.send(
            f"**🔍 MOMENTUM DEBUG**\n"
            f"- Total snapshots: **{r[0]:,}**\n"
            f"- Unique items: **{r[1]:,}**\n"
            f"- Items with 2+ snapshots: **{multi:,}**\n"
            f"- Items with fav growth >5: **{growing:,}**\n"
            f"- Earliest: `{r[2]}`\n"
            f"- Latest: `{r[3]}`\n"
            f"- Span (days): **{float(r[4] or 0):.2f}**"
        )

    @bot.command(name="momentum")
    async def momentum_cmd(ctx, days: int = 7):
        """Rank items by favorites momentum."""
        days = max(3, min(days, 30))
        progress = await ctx.send("🚀 **Scanning momentum...**")
        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                return find_momentum_keywords(cur, days=days, min_items=2, top_n=30)
            finally:
                cur.close(); conn.close()
        try:
            words = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ Failed: `{e}`"); return
        if not words:
            await progress.edit(content="📊 No momentum data yet.")
            return
        try: await progress.delete()
        except Exception: pass
        body = format_momentum_report(words, title=f"🚀 MOMENTUM (last {days}d)")
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900]); await asyncio.sleep(0.3)

    @bot.command(name="predict")
    async def predict_cmd(ctx, *, idea: str = ""):
        """Predict success for a free-form item idea."""
        if not idea.strip():
            await ctx.send("Usage: `!predict hip sway dance emote`"); return
        words = re.findall(r"[a-z]{3,}", idea.lower())
        if not words:
            await ctx.send("❌ Need at least one word."); return
        progress = await ctx.send("🎯 **Computing success probability...**")
        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                return predict_success(cur, words)
            finally:
                cur.close(); conn.close()
        try:
            pred = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ Failed: `{e}`"); return
        if not pred:
            await progress.edit(content="❌ Not enough data."); return
        try: await progress.delete()
        except Exception: pass
        body = format_prediction(pred, idea)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900]); await asyncio.sleep(0.3)

    @bot.command(name="oracle")
    async def oracle_cmd(ctx, *, keyword: str = ""):
        """Forecast a keyword's trend."""
        if not keyword.strip():
            await ctx.send("Usage: `!oracle dance`"); return
        kw = keyword.strip().lower().split()[0]
        progress = await ctx.send(f"🔮 **Forecasting `{kw}`...**")
        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                return forecast_trend(cur, kw)
            finally:
                cur.close(); conn.close()
        try:
            f = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ Failed: `{e}`"); return
        if not f:
            await progress.edit(content=f"❌ Not enough data for `{kw}`."); return
        try: await progress.delete()
        except Exception: pass
        body = format_oracle_forecast(f)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900]); await asyncio.sleep(0.3)

    @bot.command(name="nextwave")
    async def nextwave_cmd(ctx):
        """Find emerging next-wave keywords."""
        progress = await ctx.send("🌊 **Scanning for next-wave keywords...**")
        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                return find_next_wave_opportunities(cur, top_n=10)
            finally:
                cur.close(); conn.close()
        try:
            ranked = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ Failed: `{e}`"); return
        try: await progress.delete()
        except Exception: pass
        body = format_next_wave(ranked)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900]); await asyncio.sleep(0.3)

    @bot.command(name="opportunities")
    async def opportunities_cmd(ctx):
        """Show today's ranked opportunity feed."""
        progress = await ctx.send("📅 **Scanning today's best plays...**")
        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                plays = build_daily_feed(cur, top_n=5)
                try: nw = find_next_wave_opportunities(cur, top_n=5)
                except Exception: nw = []
                return plays, nw
            finally:
                cur.close(); conn.close()
        try:
            plays, next_wave = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ Failed: `{e}`"); return
        try: await progress.delete()
        except Exception: pass
        body = format_daily_feed(plays, next_wave)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900]); await asyncio.sleep(0.3)

    # =========================================================
    # !verdict
    # =========================================================
    @bot.command(name="verdict")
    async def verdict_cmd(ctx, item_id: int):
        """Multi-signal verdict: sales · age · favs · velocity · percentile."""
        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                # Refresh from Roblox first: the DB row is only as fresh as
                # the last snapshot/enrichment, and favorites move daily.
                try:
                    live = fetch_item_from_roblox(
                        item_id,
                        os.getenv("ROBLOSECURITY_COOKIE_1")
                        or os.getenv("ROBLOSECURITY_COOKIE"),
                    )
                    if live:
                        save_item_to_db(cur, live)
                        conn.commit()
                except Exception as e:
                    print(f"[verdict] live refresh failed: {e}", flush=True)

                cur.execute("""
                    select name, favorite_count, price,
                           extract(epoch from (now() - coalesce(created_at, fetched_at)))/86400.0
                    from items where id = %s
                """, (item_id,))
                r = cur.fetchone()
                if not r:
                    return None
                name, favs, price, age_days = r
                pct = item_percentile(cur, item_id)

                sales_info = None
                try:
                    from sales_listener import item_sales_summary
                    sales_info = item_sales_summary(name, days=30)
                except Exception as e:
                    print(f"[verdict] sales fetch failed: {e}", flush=True)

                opp = None
                try:
                    from opportunity_score import score_opportunity
                    opp = score_opportunity(cur, name, pct["family"])
                except Exception as e:
                    print(f"[verdict] opportunity failed: {e}", flush=True)

                sales_ci = None
                try:
                    from confidence import sales_history_ci
                    sales_ci = sales_history_ci(cur, name)
                except Exception as e:
                    print(f"[verdict] sales CI failed: {e}", flush=True)

                return {
                    "name": name, "favs": favs or 0, "price": price or 0,
                    "age_days": float(age_days or 0), "pct": pct,
                    "sales_30d": (sales_info["units"] if sales_info else 0),
                    "opportunity": opp, "sales_ci": sales_ci,
                }
            finally:
                cur.close(); conn.close()

        try:
            data = await asyncio.to_thread(_run)
        except Exception as e:
            return await ctx.send(f"❌ {e}")
        if not data or not data["pct"]:
            return await ctx.send(f"❌ Item `{item_id}` not found.")

        pct = data["pct"]
        verdict, emoji, reason = decide_verdict(
            pct["percentile"],
            age_days=data["age_days"],
            favs=data["favs"],
            velocity=pct["velocity"],
            total_sales=data["sales_30d"],
            sample_size=pct["sample_size"],
        )

        if verdict == "TOO_NEW":
            target_day = 30 if data["age_days"] >= 14 else 7
            actions = [
                f"Wait {max(1, int(target_day - data['age_days']))} more days",
                "Post 1 TikTok per day while you wait",
                f"Re-run `!verdict {item_id}` on day {target_day}",
            ]
        elif verdict == "DOUBLE_DOWN":
            actions = [
                f"Launch a variant within 7 days: `!chain variant {item_id} neon`",
                "Post 1 TikTok/day for 7 days",
                "Reply to every comment within 1h",
            ]
        elif verdict == "KEEP":
            actions = [
                "Post 3 TikToks this week (cross-post Shorts + Reels)",
                "Keep price; test -5 only if flat after 14 days",
                f"Re-run `!verdict {item_id}` in 14 days",
            ]
        elif verdict == "RENAME":
            actions = [
                f"Rename using a GOLD keyword from `!converge {pct['family']}`",
                "Change thumbnail first frame — motion, not static",
                "Re-post to TikTok with a 1.5s hook",
            ]
        else:
            actions = [
                "Stop investing in this item",
                f"Run `!converge {pct['family']}` for a fresh niche",
                "Reallocate content time to your top 2 performers",
            ]

        sales_line = ""
        if data["sales_30d"] > 0:
            sales_line = f" · 💰 {data['sales_30d']} sales (30d)"
        sci = data.get("sales_ci") or {}
        if sci.get("available"):
            u = sci["units_30d"]
            sales_line += (
                f" · 80% CI {u['lo']:g}–{u['hi']:g}/30d"
                f" ({sci.get('units_observed', 0)} observed/{sci.get('window_days', 90)}d)"
            )

        lines = [
            f"{emoji} **{data['name'][:60]}**",
            f"**{verdict.replace('_', ' ')}** — {pct['percentile']}th percentile "
            f"(better than {pct['percentile']}% of `{pct['family']}`)",
            f"_{data['age_days']:.1f}d old · {data['favs']}♥ · "
            f"{pct['velocity']}/day{sales_line}_\n",
            f"**Why:** {reason}\n",
        ]
        opp = data.get("opportunity")
        if opp:
            lines.append(
                f"**Name lane:** {opp.get('verdict')} · "
                f"demand {opp.get('demand_live', 0)} "
                f"({opp.get('demand_volume', 0):,} vol) · "
                f"supply {opp.get('supply', 0)} · "
                f"exact {opp.get('exact', 0)}\n"
            )
        lines.append("**3 actions:**")
        for i, a in enumerate(actions, 1):
            lines.append(f"{i}. {a}")

        try:
            from ugc_playbook import tactics_for
            tips = tactics_for(
                sales=data.get("sales_30d", 0),
                favs=data.get("favs", 0),
                age_days=data.get("age_days", 0),
                velocity=pct.get("velocity", 0),
            )
            lines.append("\n**📘 Playbook:**")
            for tip in tips:
                lines.append(f"• {tip}")
        except Exception as e:
            print(f"[verdict] playbook failed: {e}", flush=True)

        await ctx.send("\n".join(lines)[:1900])

    # =========================================================
    # !autopsy
    # =========================================================
    @bot.command(name="autopsy")
    async def autopsy(ctx, item_id: int, *, notes: str = ""):
        """Diagnose an item and generate verified recovery titles."""
        progress = await ctx.send(f"🔬 **Autopsying item `{item_id}`...**")
        cookie = os.getenv("ROBLOSECURITY_COOKIE_1") or os.getenv("ROBLOSECURITY_COOKIE")
        user_id = os.getenv("ROBLOX_USER_ID")

        row = None
        name_words = []
        competition_data = []
        family = "emote"
        pct_data = None
        portfolio_data = None

        try:
            conn = get_db(); cur = conn.cursor()
            cur.execute("""
                SELECT id, name, favorite_count, total_sales, price,
                       asset_type_id, creator_name, description, created_at,
                       EXTRACT(EPOCH FROM (NOW() - COALESCE(created_at, fetched_at)))/86400
                FROM items WHERE id = %s
            """, (item_id,))
            row = cur.fetchone()

            await progress.edit(content=f"🔍 Refreshing `{item_id}` live from Roblox...")
            live = await asyncio.to_thread(fetch_item_from_roblox, item_id, cookie)
            if live:
                save_item_to_db(cur, live)
                conn.commit()
                try:
                    await asyncio.to_thread(save_item_and_created_at, cur, live, item_id)
                    conn.commit()
                except Exception as e:
                    print(f"[autopsy] created_at fetch failed: {e}", flush=True)
                cur.execute("""
                    SELECT id, name, favorite_count, total_sales, price,
                           asset_type_id, creator_name, description, created_at,
                           EXTRACT(EPOCH FROM (NOW() - COALESCE(created_at, fetched_at)))/86400
                    FROM items WHERE id = %s
                """, (item_id,))
                fresh = cur.fetchone()
                if fresh: row = fresh

            if not row:
                await progress.edit(content=f"❌ Item `{item_id}` not found.")
                cur.close(); conn.close(); return

            (iid, name, favs, sales_public, price, atype,
             creator, desc, created_at, age_days) = row

            if not age_days or float(age_days) < 0.01:
                live_created = await asyncio.to_thread(
                    fetch_created_date_live, item_id, cookie
                )
                if live_created:
                    try:
                        age_days = (datetime.utcnow() - live_created.replace(tzinfo=None)).total_seconds() / 86400
                        cur.execute("UPDATE items SET created_at = %s WHERE id = %s",
                                    (live_created, item_id))
                        conn.commit()
                    except Exception: pass

            name_words = [w for w in re.findall(r"[a-z]{3,}", (name or "").lower())][:5]
            if not name_words:
                await progress.edit(content="❌ Item name is empty.")
                cur.close(); conn.close(); return

            family = detect_family_from_asset_type(atype)

            patterns = [f"%{w}%" for w in name_words]
            cur.execute("""
                SELECT favorite_count FROM items
                WHERE favorite_count > 50 AND LOWER(name) LIKE ANY(%s)
                ORDER BY favorite_count DESC LIMIT 500
            """, (patterns,))
            favs_list = [r[0] for r in cur.fetchall() if r[0]]

            winner_median_favs = 0
            if favs_list:
                sf = sorted(favs_list, reverse=True)
                cutoff = max(1, len(sf) // 10)
                winner_median_favs = sf[cutoff - 1]

            competition_data = _build_per_word_competition(cur, name_words, cap=6)

            try:
                pct_data = item_percentile(cur, item_id)
            except Exception as e:
                print(f"[autopsy] percentile failed: {e}", flush=True)
            try:
                portfolio_data = portfolio_context(cur, top_n=3)
            except Exception as e:
                print(f"[autopsy] portfolio failed: {e}", flush=True)

            cur.close(); conn.close()

            item_stats = {
                "id": iid, "favs": favs or 0, "sales": sales_public or 0,
                "price": price or 0, "age_days": float(age_days or 0),
                "winner_median_favs": winner_median_favs, "category": atype,
            }
        except Exception as e:
            try: await progress.edit(content=f"❌ Autopsy failed: `{e}`")
            except Exception: pass
            return

        if cookie and user_id:
            try:
                sales_list = await asyncio.to_thread(fetch_user_sales, cookie, user_id, 3)
                item_stats = enrich_item_stats_with_sales(item_stats, sales_list)
            except Exception as e:
                print(f"[autopsy] sales fetch failed: {e}", flush=True)

        # ── DETERMINISTIC PIVOT ──
        pivot_kw = None
        pivot_conf = 0.0
        pivot_reason = ""
        sales_30d = 0
        try:
            from intel_common import pick_pivot_from_data
            temp_niche = []
            try:
                conn_p = get_db(); cur_p = conn_p.cursor()
                try:
                    for w in name_words[:5]:
                        kw = classify_keyword(cur_p, w, family)
                        if kw:
                            temp_niche.append(kw)
                finally:
                    cur_p.close(); conn_p.close()
            except Exception as e:
                print(f"[autopsy] niche build failed: {e}", flush=True)

            print(f"[autopsy] pivot debug input: {temp_niche}", flush=True)

            if temp_niche:
                pivot_kw, pivot_conf, pivot_reason = pick_pivot_from_data(
                    temp_niche, None
                )
                print(f"[autopsy] pivot chosen: {pivot_kw} "
                      f"conf={pivot_conf} reason={pivot_reason}", flush=True)
        except Exception as e:
            print(f"[autopsy] pivot picker failed: {e}", flush=True)

        # ── DECISION LINE ─────────────────
        if pct_data:
            sales_30d = 0
            try:
                from sales_listener import item_sales_summary
                si = item_sales_summary(name, days=30)
                if si:
                    sales_30d = si["units"]
            except Exception as e:
                print(f"[autopsy] sales fetch failed: {e}", flush=True)

            verdict, v_emoji, v_reason = decide_verdict(
                pct_data["percentile"],
                age_days=item_stats["age_days"],
                favs=item_stats["favs"],
                velocity=pct_data["velocity"],
                total_sales=sales_30d,
                sample_size=pct_data["sample_size"],
            )

            if verdict == "TOO_NEW":
                target_day = 30 if item_stats["age_days"] >= 14 else 7
                acts = [
                    f"Wait {max(1, int(target_day - item_stats['age_days']))} more days",
                    "Post 1 TikTok per day while you wait",
                    f"Re-run `!autopsy {item_id}` on day {target_day}",
                ]
            elif verdict == "DOUBLE_DOWN":
                acts = ["Launch a **variant** within 7 days — same motion, new theme.",
                        "Post 1 TikTok/day for 7 days.",
                        "Reply to every comment within 1h."]
            elif verdict == "KEEP":
                acts = ["Post 3 TikToks this week (cross-post Shorts + Reels).",
                        "Keep price; test -5 only if flat after 14 days.",
                        f"Re-run `!autopsy {item_id}` in 14 days."]
            elif verdict == "RENAME":
                acts = [f"Rename using a **GOLD** keyword from `!converge {pct_data['family']}`.",
                        "Change thumbnail first frame — motion, not static.",
                        "Re-post to TikTok with a 1.5s hook."]
            else:
                acts = ["Stop investing in this item.",
                        f"Run `!converge {pct_data['family']}` for a snipe zone.",
                        "Reallocate content to your top-2 performers."]

            sales_line = f" · 💰 {sales_30d} sales (30d)" if sales_30d > 0 else ""

            dec_lines = [
                f"{v_emoji} **{name[:60]}** — **{verdict.replace('_', ' ')}**",
                f"{pct_data['percentile']}th percentile (better than {pct_data['percentile']}% of `{pct_data['family']}`)",
                f"_{pct_data['age_days']}d old · {favs}♥ · "
                f"{pct_data['velocity']}/day{sales_line} · {pct_data['sample_size']} peers_\n",
                f"**Why:** {v_reason}\n",
                "**3 actions:**",
            ]
            for i, a in enumerate(acts, 1):
                dec_lines.append(f"{i}. {a}")

            if portfolio_data and portfolio_data["winners"]:
                p = portfolio_data["winners"][0]
                dec_lines.append(
                    f"\n📊 **Your top performer:** _{p['name'][:40]}_ "
                    f"({p['velocity']}/day, `{p['family']}`)"
                )

            await ctx.send("\n".join(dec_lines)[:1900])

        # ── NICHE INTEL ────
        niche_intel = None
        try:
            from market_velocity import build_niche_intel, format_niche_intel_for_prompt
            if name_words:
                cat_ids = None
                try:
                    cat_ids = get_category_config(family).get("asset_type_ids") or None
                except Exception:
                    cat_ids = None

                def _run_niche():
                    conn = get_db(); cur = conn.cursor()
                    try:
                        return build_niche_intel(cur, name_words[:4], asset_ids=cat_ids)
                    finally:
                        cur.close(); conn.close()

                niche_intel = await asyncio.to_thread(_run_niche)

                if niche_intel:
                    body = format_niche_intel_for_prompt(niche_intel)
                    for i in range(0, len(body), 1900):
                        await ctx.send(body[i:i+1900])
                        await asyncio.sleep(0.3)
        except Exception as e:
            print(f"[autopsy] niche intel failed: {e}", flush=True)

        diagnosis = detect_failure_mode(item_stats)
        try: await progress.delete()
        except Exception: pass

        cfg = get_category_config(family)

        header = (
            f"# 🩺 AUTOPSY — `{name[:60]}`\n"
            f"**Creator:** {creator or '?'} · **Item ID:** `{iid}`\n"
            f"**Type:** {ASSET_TYPE_NAMES.get(atype, atype)} · "
            f"**Category family:** {cfg['label']}\n"
            f"**Age:** {item_stats['age_days']:.1f} days"
        )
        await ctx.send(header)

        body = format_recovery_report(diagnosis, item_stats, show_sales=False)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900]); await asyncio.sleep(0.3)

        # ── KEYWORD INTELLIGENCE ──
        fast_class = None
        deep_intel = None
        actual_bucket = None
        try:
            from gemini_brain import (
                is_available, extract_keywords, _generate,
                classify_keyword_intelligence, format_keyword_intel_for_prompt,
            )
            if competition_data:
                fast_class = classify_competition_batch(competition_data)
                seed_kw = (name_words[0] if name_words else "").lower()
                actual_bucket = next(
                    (c["bucket"] for c in fast_class
                     if str(c.get("keyword", "")).lower() == seed_kw),
                    None,
                )
                intel_msg = await ctx.send(
                    "🧬 **Keyword intelligence — supply × demand × velocity...**"
                )
                if is_available():
                    try:
                        deep_intel = await asyncio.to_thread(
                            classify_keyword_intelligence,
                            name_words[0] if name_words else "ugc",
                            competition_data, family,
                        )
                    except Exception as ie:
                        print(f"[autopsy] deep intel failed: {ie}", flush=True)

                intel_lines = ["# 🧬 KEYWORD INTELLIGENCE\n"]
                if fast_class and fast_class.get("classifications"):
                    intel_lines.append(format_keyword_classifications(fast_class))
                    intel_lines.append("")
                facts = []
                for cdata in competition_data:
                    facts.extend([
                        cdata.get("comp", 0), cdata.get("median_favs", 0),
                        cdata.get("demand", 0), cdata.get("demand_volume", 0),
                    ])
                facts.extend([
                    item_stats.get("favs", 0), item_stats.get("sales", 0),
                    item_stats.get("price", 0), item_stats.get("age_days", 0),
                    item_stats.get("winner_median_favs", 0),
                ])

                if deep_intel and deep_intel.get("diagnosis"):
                    from verification import verify_claims_text
                    diag_clean, diag_drops = verify_claims_text(
                        deep_intel["diagnosis"], facts, allow_small={7, 14, 30}
                    )
                    from verification import reconcile_bucket_text
                    diag_clean, bucket_drops = reconcile_bucket_text(
                        diag_clean, actual_bucket
                    )
                    intel_lines.append("## 🎯 DIAGNOSIS")
                    intel_lines.append(diag_clean or "(removed: unverifiable claims)")
                    if diag_drops or bucket_drops:
                        intel_lines.append(
                            f"_( {len(diag_drops) + len(bucket_drops)} "
                            f"unsupported claim(s) removed )_"
                        )
                    intel_lines.append("")
                    bp = deep_intel.get("best_pivot") or {}
                    if bp.get("keyword"):
                        def _vp():
                            conn_v = get_db(); cur_v = conn_v.cursor()
                            try:
                                from verification import verify_pivot
                                return verify_pivot(cur_v, bp, family)
                            finally:
                                cur_v.close(); conn_v.close()

                        vp, vp_reason = await asyncio.to_thread(_vp)
                        if vp:
                            deep_intel["best_pivot"] = vp
                            intel_lines.append(
                                "## 🚀 BEST PIVOT (verified against DB)"
                            )
                            intel_lines.append(
                                f"**`{vp['keyword']}`** — supply={vp['supply']}, "
                                f"median_favs={vp['median_favs']}, "
                                f"demand={vp['demand']} "
                                f"({vp.get('demand_volume', 0):,} vol), "
                                f"bucket={vp['bucket']}, "
                                f"visibility proxy (unvalidated)={vp['ctr_proxy']}/100"
                            )
                            why_clean, _ = verify_claims_text(
                                bp.get("why_better"),
                                [vp.get("supply", 0), vp.get("median_favs", 0),
                                 vp.get("demand", 0)],
                                allow_small={7, 14, 30},
                            )
                            if why_clean:
                                intel_lines.append(f"> {why_clean}")
                        else:
                            deep_intel["best_pivot"] = {}
                            intel_lines.append(
                                f"## 🚀 BEST PIVOT — REJECTED\n"
                                f"_AI proposed `{bp.get('keyword')}`; "
                                f"verification failed: {vp_reason}_"
                            )

                intel_body = "\n".join(intel_lines)
                try: await intel_msg.edit(content=intel_body[:1900])
                except Exception: pass
                if len(intel_body) > 1900:
                    for i in range(1900, len(intel_body), 1900):
                        await ctx.send(intel_body[i:i+1900]); await asyncio.sleep(0.3)
        except Exception as e:
            print(f"[autopsy] keyword intelligence block failed: {e}", flush=True)

        # ── AI helpers ──
        try:
            from gemini_brain import is_available, extract_keywords, _generate
        except Exception:
            return
        if not is_available():
            return

        ai_msg = await ctx.send("🧠 **Generating 10 recovery titles + descriptions...**")

        intent = extract_keywords(name or "ugc item")
        allow_list, top_items, stats = [], [], {}

        _build_allow_list = None
        try:
            from commands_ai import _build_allow_list
        except ImportError:
            _build_allow_list = None

        if _build_allow_list is not None:
            try:
                def _run_allow():
                    return _build_allow_list(intent, 60, None)
                allow_list, top_items, stats = await asyncio.to_thread(_run_allow)
            except Exception as e:
                print(f"[autopsy] allow-list failed: {e}", flush=True)

        if not allow_list:
            allow_list = list(set(
                [w.lower() for w in re.findall(r"[a-z]{4,}", name or "")]
                + list(cfg["type_words"])
                + ["viral", "trendy", "tiktok"]
            ))

        type_words_str = ", ".join(cfg["type_words"][:5])
        archetypes_str = "\n".join(f"  - {a}" for a in cfg["title_archetypes"][:5])

        intel_block = "(no keyword intelligence available)"
        try:
            from gemini_brain import format_keyword_intel_for_prompt
            if deep_intel:
                intel_block = format_keyword_intel_for_prompt(deep_intel)
        except Exception:
            pass

        niche_block = ""
        try:
            from market_velocity import format_niche_intel_for_prompt
            if niche_intel:
                niche_block = "\n=== 🚀 NICHE INTEL (velocity/trajectory/concentration) ===\n"
                niche_block += format_niche_intel_for_prompt(niche_intel)
                niche_block += "\n"
        except Exception:
            pass

        portfolio_block = ""
        if portfolio_data and portfolio_data.get("winners"):
            portfolio_block = "\n=== CREATOR'S OWN TOP PERFORMERS ===\n"
            for w in portfolio_data["winners"]:
                portfolio_block += (
                    f"  · {w['name'][:45]} — "
                    f"{w['velocity']}/day, family `{w['family']}`\n"
                )
            portfolio_block += (
                "New titles should match this vibe — proven style for "
                "this creator, not generic.\n"
            )

        bp = (deep_intel or {}).get("best_pivot") or {}
        bp_kw = (bp.get("keyword") or "").strip().lower()
        if bp_kw:
            pivot_kw = bp_kw
            pivot_conf = 0.0
            pivot_reason = (
                f"verified against DB · supply={bp.get('supply', 0)} · "
                f"median={bp.get('median_favs', 0)} · {bp.get('bucket', '?')}"
            )

        forbidden_first = []
        try:
            for c in (fast_class or {}).get("classifications", []):
                if c.get("bucket") in ("SATURATED", "DEAD"):
                    w = (c.get("keyword") or "").strip().lower()
                    if w and w not in forbidden_first:
                        forbidden_first.append(w)
        except Exception:
            pass

        hint_parts = []
        if bp_kw:
            hint_parts.append(
                f"\n=== MANDATORY STARTING TOKEN ===\n"
                f"At least 5 of the 10 titles MUST start with `{bp_kw}`.\n"
                f"`{bp_kw}` is the pivot that avoids the saturated tier.\n"
                f"Titles that don't start with `{bp_kw}` MUST start with a "
                f"low-competition word (supply < 50).\n"
            )
        if forbidden_first:
            hint_parts.append(
                f"\n=== FORBIDDEN AS FIRST TOKEN (NON-NEGOTIABLE) ===\n"
                f"NEVER start a title with any of: {', '.join(forbidden_first)}\n"
                f"These words are SATURATED. Using them as first token continues "
                f"the exact failure the item already has.\n"
                f"You may use them in positions 3-5 only if absolutely necessary.\n"
            )
        pivot_hint = "".join(hint_parts)

        recovery_prompt = f"""You're a Roblox UGC seller who fixes dead items. Talk like a blunt friend, not a consultant.

=== VOICE ===
Short sentences. Plain words. Say the number, then the move.
Never use "leverage", "signaling", "landscape", "optimal", "capture buyer intent",
"demonstrates", "vastly outperforms", "necessary to". No report-speak.

=== THE FAILING ITEM ===
Current name: {name}
Creator description: {desc or '(none)'}
Category family: {cfg['label']}
Current favs: {item_stats['favs']}
Current sales: {item_stats['sales']}
Price: R${item_stats['price']}
Age: {item_stats['age_days']:.1f} days
Winner median in niche: {item_stats['winner_median_favs']:,} favs

FAILURE MODE: {diagnosis['failure_mode']}

=== 🧠 KEYWORD INTELLIGENCE (AUTHORITATIVE) ===
{intel_block}
{niche_block}
{portfolio_block}
{pivot_hint}
=== SHAPE RULE FOR THIS CATEGORY ===
{cfg['shape_rule']}

=== EXAMPLE TITLE STRUCTURES ===
{archetypes_str}

=== CRITICAL RULES (NON-NEGOTIABLE) ===
1. NEVER call a high-competition keyword "weak". High competition = SATURATED = HIGH DEMAND.
   "WEAK" is RESERVED ONLY for keywords with median_favs < 50.
2. If any seed is SATURATED, say so explicitly using the word "SATURATED".
3. If a MANDATORY STARTING TOKEN is specified above, at least 5 of the 10 titles
   MUST start with that token.
4. If FORBIDDEN AS FIRST TOKEN words are listed, no title may start with any of them.
5. Every title MUST be 3-5 words.
6. Every title MUST end with one of: {type_words_str}
7. Use ONLY these allow-list words + glue + type words:
   {', '.join(allow_list[:80])}
8. Every title MUST be UNIQUE.
9. If CREATOR'S OWN TOP PERFORMERS are listed above, style-match them.

=== 10 TITLES — GROUP INTO 4 STRATEGIES ===
titles_safe (3), titles_differentiated (3), titles_longtail (2), titles_viral (2)

=== 3 DESCRIPTIONS ===
description_seo, description_hype, description_short
CUSTOMER-FACING ONLY. Never mention zero sales, no sales, failure, saturated,
algorithm, tags, "we", fixing, or guarantees. No "flex". 1-3 sentences.

=== OUTPUT — ONLY JSON ===
{{
  "titles_safe": ["...", "...", "..."],
  "titles_differentiated": ["...", "...", "..."],
  "titles_longtail": ["...", "..."],
  "titles_viral": ["...", "..."],
  "description_seo": "...",
  "description_hype": "...",
  "description_short": "...",
  "primary_keyword": "best first word — MUST be the mandatory starting token",
  "edit_reasoning": "2-3 short sentences. Why these titles work. Use only the verified bucket; never invent SATURATED.",
  "what_was_wrong": "2-3 short sentences. Use only the verified bucket; never invent SATURATED. No filler."
}}
"""

        try:
            raw = await asyncio.to_thread(
                _generate, recovery_prompt, True, 0.3, 6000, "gemini"
            )
            data = {}
            if raw:
                try: data = json.loads(raw)
                except Exception:
                    m = re.search(r"\{.*\}", raw, re.DOTALL)
                    data = json.loads(m.group(0)) if m else {}

            if not data:
                await ai_msg.edit(content="⚠️ AI returned nothing. Try again.")
                return

            try:
                from gemini_brain import _strip_promo_from_description
                for dk in ("description_seo", "description_hype", "description_short"):
                    if data.get(dk):
                        data[dk] = _strip_promo_from_description(data[dk])
            except Exception as e:
                print(f"[autopsy] promo filter failed: {e}", flush=True)

            all_groups = {
                "🟢 SAFE (search-first)":           data.get("titles_safe") or [],
                "🎯 DIFFERENTIATED (unique angle)": data.get("titles_differentiated") or [],
                "🔎 LONG-TAIL SEO (4+ keywords)":   data.get("titles_longtail") or [],
                "🔥 VIRAL (meme/TikTok hook)":      data.get("titles_viral") or [],
            }

            forbidden_first_set = {w.lower() for w in forbidden_first}

            def _deep_verify_groups():
                from verification import verify_titles_deep
                conn_v = get_db(); cur_v = conn_v.cursor()
                try:
                    out = {}
                    rejected_all = []
                    all_metrics = {}
                    for gname, gtitles in all_groups.items():
                        v, r, gmetrics = verify_titles_deep(
                            cur_v, gtitles, allow_list, family
                        )
                        all_metrics.update(gmetrics)
                        kept = []
                        for title in v:
                            first = (title.lower().split() or [""])[0]
                            if first in forbidden_first_set:
                                rejected_all.append(
                                    (gname, title,
                                     ["starts with a SATURATED keyword"])
                                )
                            else:
                                kept.append(title)
                        if kept:
                            out[gname] = kept
                        rejected_all.extend(
                            (gname, title, reasons) for title, reasons in r
                        )
                    return out, rejected_all, all_metrics
                finally:
                    cur_v.close(); conn_v.close()

            verified_groups = {}
            deep_rejected = []
            deep_metrics = {}
            verification_error = None
            try:
                verified_groups, deep_rejected, deep_metrics = (
                    await asyncio.to_thread(_deep_verify_groups)
                )
            except Exception as e:
                verification_error = type(e).__name__
                print(f"[autopsy] deep verification failed: {e}", flush=True)
                deep_rejected = []
                deep_metrics = {}

            claim_drops = []
            try:
                from verification import clean_text_fields, TITLE_FIELDS
                facts = [
                    item_stats.get("favs", 0), item_stats.get("sales", 0),
                    item_stats.get("price", 0), item_stats.get("age_days", 0),
                    item_stats.get("winner_median_favs", 0),
                    stats.get("count", 0), stats.get("avg_favs", 0),
                    stats.get("median_favs", 0), stats.get("price_avg", 0),
                ]
                for cdata in competition_data:
                    facts.extend([
                        cdata.get("comp", 0), cdata.get("median_favs", 0),
                        cdata.get("demand", 0), cdata.get("demand_volume", 0),
                    ])
                claim_drops = clean_text_fields(
                    data, facts, allow_small={7, 14, 30},
                    skip=set(TITLE_FIELDS) | {"primary_keyword"},
                )
                from verification import reconcile_bucket_text
                for bkey in ("saturation_verdict", "what_was_wrong", "edit_reasoning"):
                    cleaned_b, dropped_b = reconcile_bucket_text(
                        data.get(bkey), actual_bucket
                    )
                    if dropped_b:
                        data[bkey] = cleaned_b
                        claim_drops.extend(
                            {"field": bkey, "text": s, "unsupported": [],
                             "claim": "bucket mismatch"}
                            for s in dropped_b
                        )
                from verification import fix_descriptions
                fix_descriptions(data, name)
                if not data.get("edit_reasoning") and pivot_kw:
                    data["edit_reasoning"] = (
                        f"Verified pivot: `{pivot_kw}`. Keep the name 3–5 "
                        f"words and lead with that word."
                    )
                pk = data.get("primary_keyword")
                if pk:
                    from verification import allow_set, tokens, STOPWORDS
                    allowed = allow_set(allow_list)
                    toks = tokens(pk)
                    if not toks or any(
                        t not in allowed and t not in STOPWORDS
                        and not t.isdigit() and len(t) != 1
                        for t in toks
                    ):
                        data["primary_keyword"] = ""
            except Exception as e:
                print(f"[autopsy] claim check failed: {e}", flush=True)

            rejected_count = len(deep_rejected)

            lines = ["# 🧠 10 RECOVERY TITLES\n"]
            if verification_error:
                lines.append(
                    "⚠️ **Verification unavailable** — AI titles are withheld "
                    f"until the database check succeeds (`{verification_error}`).\n"
                )
            if claim_drops:
                lines.append(
                    f"_({len(claim_drops)} unsupported numeric claim(s) "
                    f"removed from the AI copy.)_\n"
                )
            if verified_groups:
                for gname, titles in verified_groups.items():
                    if not titles:
                        continue
                    lines.append(f"**{gname}**")
                    for t in titles:
                        lines.append(f"• `{t}`")
                    lines.append("")
                if rejected_count:
                    lines.append(
                        f"_({rejected_count} title(s) rejected by token, "
                        f"saturation, or forbidden-first-word checks.)_\n"
                    )
                    for gname, title, reasons in deep_rejected[:6]:
                        lines.append(
                            f"• ❌ `{title[:60]}` — "
                            f"{'; '.join(reasons)[:140]}"
                        )
                    lines.append("")
            elif not verification_error:
                lines.append("⚠️ All titles failed verification.")

            lines.append("---\n")
            lines.append("## 📝 3 DESCRIPTIONS\n")
            if data.get("description_seo"):
                lines.append("**🎯 SEO**")
                lines.append(f"```\n{data['description_seo'][:400]}\n```\n")
            if data.get("description_hype"):
                lines.append("**🔥 Hype**")
                lines.append(f"```\n{data['description_hype'][:300]}\n```\n")
            if data.get("description_short"):
                lines.append("**⚡ Short**")
                lines.append(f"```\n{data['description_short'][:200]}\n```\n")

            if data.get("primary_keyword"):
                lines.append(f"## 🎯 LEAD WITH: `{data['primary_keyword']}`\n")
            if data.get("what_was_wrong"):
                lines.append("## ❌ What Was Wrong")
                lines.append(data["what_was_wrong"] + "\n")
            if data.get("edit_reasoning"):
                lines.append("## ✅ Strategy")
                lines.append(data["edit_reasoning"])

            body = "\n".join(lines)
            try: await ai_msg.edit(content=body[:1900])
            except Exception: pass
            if len(body) > 1900:
                for i in range(1900, len(body), 1900):
                    await ctx.send(body[i:i+1900]); await asyncio.sleep(0.3)

            # PEER AUTOPSY
            try:
                from peer_autopsy import peer_autopsy
                peer_chunks = peer_autopsy(item_id, top_n=5)
                for chunk in peer_chunks:
                    for i in range(0, len(chunk), 1900):
                        await ctx.send(chunk[i:i+1900])
                        await asyncio.sleep(0.3)
            except Exception as e:
                print(f"[autopsy] peer autopsy failed: {e}", flush=True)

            # STATISTICAL RECOVERY RANKING (OFF EVENT LOOP)
            scored_recovery = []
            champion = None
            backup = None
            try:
                from title_scorer import score_titles_batch, pick_champion
                all_titles = []
                for titles in verified_groups.values():
                    all_titles.extend(titles)
                if all_titles:
                    scored_recovery = await asyncio.to_thread(
                        score_titles_batch, all_titles, family
                    )
                    for sc in scored_recovery:
                        opp = ((deep_metrics.get(sc["title"]) or {})
                               .get("opportunity") or {})
                        sc["opportunity"] = opp
                        sc["final_score"] = sc["score"]
                    from opportunity_score import lane_priority
                    scored_recovery.sort(
                        key=lambda x: (
                            lane_priority(x.get("opportunity")),
                            x["final_score"],
                        ),
                        reverse=True,
                    )
                    if pivot_kw:
                        pref = pivot_kw.lower()
                        scored_recovery.sort(
                            key=lambda x: (
                                lane_priority(x.get("opportunity")),
                                x["title"].lower().startswith(pref + " "),
                                x["final_score"],
                            ),
                            reverse=True,
                        )
                    champion, backup, _ = pick_champion(scored_recovery)
                    if champion:
                        pivot_kw = champion["title"].split()[0].lower()
                        pivot_conf = 0.0
                        pivot_reason = "lane leader from verified ranking"

                    stat_lines = ["# 📊 STATISTICAL RECOVERY RANKING\n",
                                  "_Real word-lift × search-demand from DB._\n"]
                    for i, sc in enumerate(scored_recovery[:5], 1):
                        opp = sc.get("opportunity") or {}
                        opp_part = (
                            f" · {opp.get('verdict')} · "
                            f"visibility {opp.get('ctr_proxy')}/100 (unvalidated)"
                            if opp else ""
                        )
                        stat_lines.append(
                            f"**#{i} `{sc['title']}`** — score "
                            f"**{sc.get('final_score', sc['score'])}**"
                            + (f" · gap {sc.get('visibility_gap', 0):.0f}"
                               if sc.get("visibility_gap", 0) >= 5 else "")
                            + opp_part
                            + (f" · unique" if sc['exact_matches'] == 0
                               else f" · {sc['exact_matches']} matches")
                        )
                        for b in sorted(sc["breakdown"],
                                        key=lambda x: x["contribution"],
                                        reverse=True)[:3]:
                            if b.get("no_data"):
                                continue
                            lift = b["lift"]
                            emoji = "🟢" if lift >= 2.5 else "🔵" if lift >= 1.5 \
                                    else "⚪" if lift >= 1.0 else "🟠" if lift >= 0.5 else "🔴"
                            vol = b.get("demand_volume", 0)
                            vol_str = f" · {vol:,} volume" if vol else ""
                            stat_lines.append(
                                f"   {emoji} `{b['word']}` lift {lift}× "
                                f"({b['sample']} items · {b['demand']} live"
                                f"{vol_str}) → +{b['contribution']}"
                            )
                        stat_lines.append("")

                    stat_body = "\n".join(stat_lines)
                    for i in range(0, len(stat_body), 1900):
                        await ctx.send(stat_body[i:i+1900])
                        await asyncio.sleep(0.3)
            except Exception as e:
                print(f"[autopsy] title scoring failed: {e}", flush=True)

            # COHORT EVIDENCE — comparable cohort, not a guarantee
            try:
                from confidence import build_confidence, format_confidence

                def _conf():
                    conn_c = get_db(); cur_c = conn_c.cursor()
                    try:
                        return build_confidence(
                            cur_c, family=family,
                            phrase=champion["title"] if champion else name,
                            price=price or 0,
                        )
                    finally:
                        cur_c.close(); conn_c.close()

                conf_data = await asyncio.to_thread(_conf)
                conf_body = format_confidence(conf_data)
                for i in range(0, len(conf_body), 1900):
                    await ctx.send(conf_body[i:i+1900])
                    await asyncio.sleep(0.3)
            except Exception as e:
                print(f"[autopsy] confidence failed: {e}", flush=True)

            # LIVE MARKETPLACE CHECK — verify the champion against Roblox
            try:
                if champion and champion.get("title"):
                    from live_market import check_title, format_check
                    live_result = await asyncio.to_thread(
                        check_title, champion["title"]
                    )
                    live_body = format_check(live_result)
                    if live_body:
                        await ctx.send(live_body[:1900])
            except Exception as e:
                print(f"[autopsy] live marketplace check failed: {e}", flush=True)

            # TAGS MERGE — uses tag_generator (not description_engine)
            merged_desc = None
            try:
                from tag_generator import generate_tags

                tag_seed = None
                if champion and champion.get("title"):
                    tag_seed = champion["title"]
                elif name:
                    tag_seed = name

                if tag_seed:
                    tag_result = await asyncio.to_thread(
                        generate_tags, tag_seed, family, 25
                    )
                    tags = (tag_result or {}).get("tags") or []

                    base_body = (data.get("description_seo") or "").strip()

                    if base_body and tags:
                        tag_line = ", ".join(tags)
                        merged_desc = f"{base_body}\n\ntags: {tag_line}"
                    elif base_body:
                        merged_desc = base_body
                    elif tags:
                        merged_desc = f"tags: {', '.join(tags)}"
            except Exception as e:
                print(f"[autopsy] tag merge failed: {e}", flush=True)

            if merged_desc:
                await ctx.send(
                    f"## ✨ New description + tags (copy-paste)\n```\n"
                    f"{merged_desc[:1500]}\n```"
                )

            # FINAL BLOCK
            final_lines = ["# ✅ FINAL — DO THIS FOR THIS ITEM"]
            kill = verdict == "KILL"
            too_new = verdict == "TOO_NEW"

            if kill:
                final_lines.append(
                    "**Let it go.** Don't rename it, don't re-upload it, don't touch "
                    "the price. A fresh title won't save a dead item."
                )
            elif too_new:
                final_lines.append(
                    "**Too early to call.** Leave it alone for now — editing this "
                    "early just resets the velocity counter."
                )

            if pivot_kw:
                label = ("**🎯 Pivot for the next upload:**" if kill
                         else "**🎯 Pivot:**")
                conf_txt = (f"confidence **{pivot_conf:.0%}**"
                            if pivot_conf > 0 else "verified against DB")
                final_lines.append(
                    f"{label} `{pivot_kw}` "
                    f"({conf_txt})\n"
                    f"  _Reason: {pivot_reason}_"
                )

            if champion:
                name_label = ("**1. Name for the new upload:**" if kill
                              else "**1. New name:**")
                final_lines.append(
                    f"{name_label} `{champion['title']}`  ← top-ranked candidate"
                )
                try:
                    from opportunity_score import lane_priority
                    if lane_priority(champion.get("opportunity")) == 0:
                        final_lines.append(
                            "**⚠️ Lane warning:** every surviving name is "
                            "SATURATED. Treat this as a test, not an open lane."
                        )
                except Exception:
                    pass
                if backup:
                    final_lines.append(
                        f"**2. Backup name:** `{backup['title']}`"
                    )
            else:
                final_lines.append(
                    "**1. New name:** none — no AI title passed verification."
                )

            if merged_desc:
                desc_label = ("**3. Description for the new upload:** (block above)"
                              if kill else "**3. Paste description** (from above block)")
                final_lines.append(desc_label)
            elif data.get("description_seo"):
                final_lines.append(
                    f"**3. Description:**\n```\n{data['description_seo'][:400]}\n```"
                )

            if item_stats.get("price"):
                final_lines.append(
                    f"**4. Price:** leave it at R${item_stats['price']}" if kill
                    else f"**4. Price:** keep at R${item_stats['price']} — "
                         f"test -5 after 14d if flat"
                )

            if kill:
                final_lines.append(
                    "**5. Today:** skip the rename. Start the new item with the "
                    "name above."
                )
            elif too_new:
                final_lines.append(
                    "**5. Today:** nothing. Judge it again on day 30."
                )
            else:
                final_lines.append(
                    "**5. Today:** rename it, swap the thumbnail to a motion frame, "
                    "post 1 TikTok."
                )
            final_lines.append(f"**6. In 14 days:** `!verdict {item_id}`")
            if kill:
                final_lines.append(
                    f"\n_Still want to fight for it? `!revive {item_id}` runs the "
                    "full rebuild — gaps, pivots, peer autopsy, 14-day plan._"
                )

            try:
                if not kill and not too_new:
                    rec_type = "rename" if champion else "keep"
                    rec_name = (champion.get("title") if champion else name)
                    rec_pivot = pivot_kw or ""
                    rec_price = item_stats.get("price") or 0
                    baseline_vel = (pct_data["velocity"] if pct_data
                                    else item_stats["favs"] /
                                    max(item_stats["age_days"], 1))
                    predicted = {
                        "champion_score": (champion.get("score")
                                           if champion else None),
                        "pivot": rec_pivot,
                        "verdict": verdict,
                    }
                    evidence = {
                        "verdict": verdict,
                        "percentile": (pct_data["percentile"]
                                       if pct_data else None),
                        "sample_size": (pct_data["sample_size"]
                                        if pct_data else None),
                        "source": "autopsy",
                    }

                    def _save_rec():
                        conn_r = get_db(); cur_r = conn_r.cursor()
                        try:
                            from experiments import create_recommendation
                            rid, created = create_recommendation(
                                cur_r, item_id, "autopsy", rec_type,
                                {
                                    "name": name,
                                    "price": item_stats.get("price") or 0,
                                    "favs": item_stats["favs"],
                                    "sales_30d": sales_30d,
                                    "velocity": baseline_vel,
                                    "age_days": item_stats["age_days"],
                                },
                                {
                                    "name": rec_name,
                                    "pivot": rec_pivot,
                                    "price": rec_price,
                                },
                                predicted=predicted,
                                evidence=evidence,
                            )
                            conn_r.commit()
                            return rid, created
                        finally:
                            cur_r.close(); conn_r.close()

                    rec_id, created = await asyncio.to_thread(_save_rec)
                    state = "new" if created else "existing"
                    final_lines.append(
                        f"\n**🧪 Experiment #{rec_id}** ({state}) — baseline "
                        f"{item_stats['favs']}♥ · {sales_30d} sales/30d · "
                        f"{baseline_vel:.2f}/day\n"
                        f"After you apply it: `!applied {rec_id}` · "
                        f"if you skip it: `!ignored {rec_id}`"
                    )
            except Exception as e:
                print(f"[autopsy] experiment save failed: {e}", flush=True)

            await ctx.send("\n".join(final_lines))

            # CONSISTENCY CHECK + SAVE
            if pivot_kw:
                try:
                    from pivot_history import consistency_check, save_recommendation
                    check = consistency_check(item_id, pivot_kw, pivot_conf)
                    if check:
                        _, check_msg = check
                        await ctx.send(f"## 🧠 Consistency check\n{check_msg}")

                    save_recommendation(
                        item_id,
                        pivot_kw,
                        pivot_conf,
                        pivot_reason,
                        (champion["title"] if champion else None),
                        None,
                    )
                except Exception as e:
                    print(f"[autopsy] consistency/save failed: {e}", flush=True)

        except Exception as e:
            print(f"[autopsy] AI recovery failed: {e}", flush=True)
            try: await ai_msg.edit(content=f"⚠️ Recovery failed: `{e}`")
            except Exception: pass

    # =========================================================
    # !revive — the long-shot full rebuild
    # =========================================================
    @bot.command(name="revive", aliases=["revive_item"])
    async def revive_cmd(ctx, item_id: int):
        """Full revive run: live stats, niche scan, variant chain, peer autopsy, 14-day plan."""
        progress = await ctx.send(
            "🧟 **REVIVE MODE** — this is the long one. Live stats, gap scan, "
            "then name scoring. Give it a few minutes."
        )
        cookie = os.getenv("ROBLOSECURITY_COOKIE_1") or os.getenv("ROBLOSECURITY_COOKIE")

        def _load():
            conn = get_db(); cur = conn.cursor()
            try:
                live = fetch_item_from_roblox(item_id, cookie)
                if live:
                    save_item_to_db(cur, live)
                    conn.commit()
                cur.execute("""
                    select name, favorite_count, price, asset_type_id,
                           total_sales,
                           extract(epoch from (now() - coalesce(created_at, fetched_at)))/86400.0
                    from items where id = %s
                """, (item_id,))
                return cur.fetchone()
            finally:
                cur.close(); conn.close()

        def _deep():
            """Heavy math: gap engine, convergence, velocity, forecast, predictor."""
            from gap_engine import run_gap_engine
            from convergence_engine import scan_convergence
            from market_velocity import build_niche_intel
            from oracle import forecast_trend
            from predictor import predict_success

            conn = get_db(); cur = conn.cursor()
            try:
                terms = [w for w in re.findall(r"[a-z]{3,}", (name or "").lower())][:5]
                try:
                    cat_ids = get_category_config(family).get("asset_type_ids") or None
                except Exception:
                    cat_ids = None

                gaps = (run_gap_engine(cur, terms, asset_ids=cat_ids)
                        if terms else {})
                conv = scan_convergence(family, limit=5) or []

                kw_list = [g.get("word") for g in (gaps.get("golden") or [])][:3]
                if not kw_list:
                    kw_list = [p.get("word") for p in (gaps.get("pivots") or [])][:3]
                if not kw_list:
                    kw_list = terms[:3]
                intel = build_niche_intel(cur, kw_list, asset_ids=cat_ids) if kw_list else {}

                forecasts = {}
                for kw in (intel or {}).get("keywords", [])[:3]:
                    try:
                        f = forecast_trend(cur, kw, days=14)
                        if f:
                            forecasts[kw] = f
                    except Exception:
                        pass

                pred = predict_success(cur, terms) if terms else None
                return {
                    "gaps": gaps, "conv": conv, "intel": intel,
                    "forecasts": forecasts, "pred": pred,
                }
            finally:
                cur.close(); conn.close()

        try:
            row = await asyncio.to_thread(_load)
        except Exception as e:
            return await progress.edit(content=f"❌ Live fetch failed: `{e}`")
        if not row:
            return await progress.edit(content=f"❌ Item `{item_id}` not found.")

        name, favs, price, atype, sales, age_days = row
        favs = favs or 0
        age_days = float(age_days or 0)
        family = detect_family_from_asset_type(atype)

        await progress.edit(content=(
            f"🧟 **REVIVING** `{(name or '?')[:60]}`\n"
            f"_{favs}♥ · R${price or 0} · {age_days:.0f}d · {family}_\n"
            "**Step 1/3** — niche + gap scan (the slow part)..."
        ))

        result = {}
        try:
            from chain import run_chain, format_chain
            result = await asyncio.wait_for(
                asyncio.to_thread(run_chain, name, family, item_id), timeout=900
            )
        except Exception as e:
            result = {"error": str(e)}

        if result.get("error"):
            await ctx.send(f"⚠️ Chain scan failed: `{result['error']}`")
        else:
            try:
                for ch in format_chain(result):
                    await ctx.send(ch[:1900])
                    await asyncio.sleep(0.2)
            except Exception as e:
                await ctx.send(f"⚠️ Couldn't render chain: `{e}`")

        await progress.edit(content=(
            f"🧟 **REVIVING** `{(name or '?')[:60]}`\n"
            "**Step 2/4** — deep scan: gaps, velocity, forecast..."
        ))

        deep = {}
        try:
            deep = await asyncio.to_thread(_deep)
        except Exception as e:
            await ctx.send(f"⚠️ Deep scan failed: `{e}`")

        gaps = deep.get("gaps") or {}
        conv = deep.get("conv") or []
        intel = deep.get("intel") or {}
        forecasts = deep.get("forecasts") or {}
        pred = deep.get("pred") or {}

        dlines = ["## 🧠 DEEP SCAN — gaps, velocity, forecast"]
        if gaps:
            dlines.append(
                f"Matched **{gaps.get('matched', 0)}** items in this niche · "
                f"golden **{len(gaps.get('golden') or [])}** · "
                f"sweet **{len(gaps.get('sweet') or [])}**"
            )
            for g in (gaps.get("golden") or [])[:4]:
                dlines.append(
                    f"🟢 `{g['word']}` — {g['comp']} comp · "
                    f"median {g['median_favs']:,}♥"
                )
            for g in (gaps.get("sweet") or [])[:3]:
                dlines.append(
                    f"🔵 `{g['word']}` — {g['comp']} comp · "
                    f"median {g['median_favs']:,}♥"
                )
            for pv in (gaps.get("pivots") or [])[:3]:
                dlines.append(
                    f"🎯 pivot `{pv['word']}` — {pv['comp']} comp · "
                    f"median {pv['median_favs']:,}♥"
                )
            for cb in (gaps.get("combo_gaps") or [])[:3]:
                dlines.append(
                    f"🧩 combo `{cb['combo']}` — {cb['comp']} items · "
                    f"median {cb['median_favs']:,}♥"
                )
        else:
            dlines.append("_No gap data — the name is too generic to split._")

        if conv:
            dlines.append("\n**Family convergence:**")
            try:
                from convergence_engine import format_brief
                for r in conv[:3]:
                    dlines.append(format_brief(r))
            except Exception:
                pass

        if intel.get("keywords"):
            dlines.append("\n**Velocity / trend / creator grip:**")
            for kw in intel["keywords"][:3]:
                v = (intel.get("velocity") or {}).get(kw) or {}
                tr = (intel.get("trajectory") or {}).get(kw) or {}
                cc = (intel.get("concentration") or {}).get(kw) or {}
                dlines.append(
                    f"`{kw}` — {v.get('avg_favs_per_day', 0)} favs/day "
                    f"({v.get('sample_size', 0)} items) · "
                    f"{tr.get('direction', '?')} "
                    f"{(tr.get('pct_change') or 0):+}% · "
                    f"top3 {cc.get('top3_share', 0)}%"
                )

        if forecasts:
            dlines.append("\n**14-day forecast:**")
            for kw, f in list(forecasts.items())[:3]:
                dlines.append(
                    f"`{kw}` — {f.get('trajectory', '?')} "
                    f"(accel {f.get('avg_acceleration', '?')}, "
                    f"supply {f.get('saturation', '?')})"
                )

        if pred and pred.get("probability") is not None:
            dlines.append(
                f"\n**Success model:** **{pred.get('probability')}%** — "
                f"{pred.get('verdict', '?')} · {pred.get('reason', '')}"
            )

        score = 10
        details = ["no gap +10"]
        if gaps.get("golden"):
            score = 35; details = ["golden gap +35"]
        elif gaps.get("sweet"):
            score = 25; details = ["sweet gap +25"]

        best_conv = max([(r or {}).get("score") or 0 for r in conv], default=0)
        add = min(25, round(best_conv / 4))
        score += add
        details.append(f"convergence +{add}")

        if pred.get("probability"):
            add = round(0.25 * pred["probability"])
            score += add
            details.append(f"model +{add}")

        dirs = [(t or {}).get("direction")
                for t in (intel.get("trajectory") or {}).values()]
        if "HEATING" in dirs:
            score += 15
            details.append("heating +15")

        if age_days >= 120 and favs < 50:
            score -= 10
            details.append("old & flat -10")

        own_velocity = favs / max(age_days, 1)
        if own_velocity < 0.2:
            score -= 10
            details.append(f"own velocity {own_velocity:.2f}/d -10")

        score = max(0, min(100, score))
        score_txt = ("niche is alive — go" if score >= 70
                     else "worth one cheap test" if score >= 45
                     else "niche is the problem — new concept")
        dlines.append(
            f"\n## 🧮 REVIVE SCORE — **{score}/100**\n"
            f"_{score_txt}_\n"
            f"`{' · '.join(details)}`"
        )

        dbody = "\n".join(dlines)
        for i in range(0, len(dbody), 1900):
            await ctx.send(dbody[i:i+1900])
            await asyncio.sleep(0.2)

        await progress.edit(content=(
            f"🧟 **REVIVING** `{(name or '?')[:60]}`\n"
            "**Step 3/4** — peer autopsy..."
        ))
        try:
            from peer_autopsy import peer_autopsy
            for ch in await asyncio.to_thread(peer_autopsy, item_id, 5):
                await ctx.send(ch[:1900])
                await asyncio.sleep(0.2)
        except Exception as e:
            await ctx.send(f"⚠️ Peer autopsy failed: `{e}`")

        await progress.edit(content=(
            f"🧟 **REVIVING** `{(name or '?')[:60]}`\n"
            "**Step 4/4** — writing the plan..."
        ))

        odds = "long shot" if age_days >= 120 and favs < 50 else "realistic"
        plan = [
            f"## 🧟 REVIVE PLAN — `{(name or '?')[:50]}`",
            f"_Odds: **{odds}** — {favs}♥ at {age_days:.0f}d, "
            f"{sales or 0} sales on record._",
            "",
            "**Day 0 (today)**",
            "1. Rename using the #1 title from the chain above.",
            "2. New thumbnail: motion frame, no text clutter.",
            "3. Paste the SEO description + tags from above.",
            "4. Price: hold. Drop 5 only if nothing moves in 7 days.",
            "",
            "**Days 1-7**",
            "5. Two TikToks a day: 1.5s hook, name on screen.",
            "6. Reply to every comment within an hour.",
            "7. Shout it in your group + Discord.",
            "",
            "**Day 7 checkpoint**",
            f"8. Re-run `!verdict {item_id}`. If favourites/day is still under "
            "0.5, stop spending time here.",
            "",
            "**Day 14**",
            f"9. `!verdict {item_id}` again. Still flat = let it die and launch "
            "the backup name as a new item.",
            "",
            "_Straight talk: a rename can't invent demand. If title, thumbnail "
            "and price don't move favourites in 7 days, the concept is the problem._",
        ]
        try:
            champ = ((result.get("scored_titles") or [{}])[0]
                     if not result.get("error") else {})
            rec_name = champ.get("title")
            if rec_name:
                rec_pivot = (result.get("best_niche_kw") or "")
                baseline_vel = favs / max(age_days, 1)

                def _save_revive_rec():
                    conn_r = get_db(); cur_r = conn_r.cursor()
                    try:
                        from experiments import create_recommendation
                        rid, created = create_recommendation(
                            cur_r, item_id, "revive", "revive",
                            {
                                "name": name,
                                "price": price or 0,
                                "favs": favs,
                                "sales_30d": 0,
                                "velocity": baseline_vel,
                                "age_days": age_days,
                            },
                            {
                                "name": rec_name,
                                "pivot": rec_pivot,
                                "price": price or 0,
                            },
                            predicted={
                                "revive_score": score,
                                "chain_score": champ.get("score"),
                            },
                            evidence={
                                "source": "revive",
                                "golden_gaps": len(gaps.get("golden") or []),
                                "sweet_gaps": len(gaps.get("sweet") or []),
                            },
                        )
                        conn_r.commit()
                        return rid, created
                    finally:
                        cur_r.close(); conn_r.close()

                rec_id, created = await asyncio.to_thread(_save_revive_rec)
                plan.insert(
                    len(plan) - 1,
                    f"**🧪 Experiment #{rec_id}** "
                    f"({'new' if created else 'existing'}) — baseline "
                    f"{favs}♥ · {baseline_vel:.2f}/day\n"
                    f"After rename: `!applied last` · "
                    f"after one week: `!experiments`",
                )
        except Exception as e:
            print(f"[revive] experiment save failed: {e}", flush=True)

        await ctx.send("\n".join(plan)[:1900])

    # =========================================================
    # !creator_brain — systematic review of the creator cohort
    # =========================================================
    @bot.command(name="creator_brain", aliases=["meta", "cohort"])
    async def creator_brain_cmd(ctx):
        """Study notable creators from your own data and show their patterns."""
        progress = await ctx.send("🧠 Studying the creator cohort...")

        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                from creator_brain import learn, save, load_findings
                cur.execute("SELECT count(*) FROM items WHERE creator_verified IS TRUE")
                has_verified = (cur.fetchone()[0] or 0) > 0
                findings = learn(cur, verified_only=has_verified)
                if findings:
                    save(cur, findings)
                    conn.commit()
                    return findings
                return load_findings(cur)
            finally:
                cur.close(); conn.close()

        try:
            findings = await asyncio.to_thread(_run)
        except Exception as e:
            return await progress.edit(content=f"❌ {e}")

        if not findings:
            return await progress.edit(
                content=("❌ Not enough creator history yet — each creator "
                         "needs at least 5 items with favorites.")
            )

        from creator_brain import format_report
        report = format_report(findings)
        if len(report) > 1900:
            await progress.edit(content=report[:1900])
            for i in range(1900, len(report), 1900):
                await ctx.send(report[i:i+1900])
                await asyncio.sleep(0.2)
        else:
            await progress.edit(content=report)

    # =========================================================
    # !verified_scan — crawl verified creators' catalogs
    # =========================================================
    @bot.command(name="verified_scan", aliases=["scan_verified"])
    async def verified_scan_cmd(ctx, limit: int = 10):
        """Monitor verified creators (throttled, resumable). Run again to continue."""
        limit = max(1, min(limit, 30))
        progress = await ctx.send(f"🔎 Scanning up to **{limit}** verified creators...")

        def _run():
            from creator_tracker import run_batch
            conn = get_db(); cur = conn.cursor()
            try:
                return run_batch(cur, limit=limit)
            finally:
                cur.close(); conn.close()

        try:
            scanned, upserted, discovered, note = await asyncio.to_thread(_run)
        except Exception as e:
            return await progress.edit(content=f"❌ {e}")

        lines = [
            "✅ **Verified creator scan**",
            f"• Creators scanned: **{scanned}**",
            f"• New verified creators found: **{discovered}**",
            f"• Marketplace items upserted: **{upserted}**",
        ]
        if note:
            lines.append(f"⚠️ Source said: `{note}`")
        elif scanned == 0 and discovered == 0:
            lines.append(
                "⚠️ Nothing returned — search may be throttled or the "
                "verified queue is empty."
            )
        lines.append("_Run `!verified_scan` again to continue the queue._")
        await progress.edit(content="\n".join(lines))
