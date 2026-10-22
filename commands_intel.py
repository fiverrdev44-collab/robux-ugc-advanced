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
            cur.execute("""
                SELECT
                    COUNT(*) AS comp,
                    COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY favorite_count), 0) AS median_favs,
                    COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price), 0) AS median_price
                FROM items
                WHERE LOWER(name) LIKE %s AND favorite_count > 5
            """, (f"%{w}%",))
            row = cur.fetchone()
            if row:
                result.append({
                    "keyword": w,
                    "comp": int(row[0] or 0),
                    "median_favs": int(row[1] or 0),
                    "median_price": int(row[2] or 0),
                })
        except Exception as e:
            print(f"[autopsy] per-word query failed for '{w}': {e}", flush=True)
    return result


def register_intel_commands(bot, get_db, ASSET_TYPE_NAMES):

    @bot.command(name="momentum_debug")
    async def momentum_debug(ctx):
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

                return {
                    "name": name, "favs": favs or 0, "price": price or 0,
                    "age_days": float(age_days or 0), "pct": pct,
                    "sales_30d": (sales_info["units"] if sales_info else 0),
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
            actions = [
                f"Wait {max(1, int(7 - data['age_days']))} more days",
                "Post 1 TikTok per day while you wait",
                f"Re-run `!verdict {item_id}` on day 7",
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
                f"Test price at R${max((data['price'] or 0) - 5, 45)}",
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

        lines = [
            f"{emoji} **{data['name'][:60]}**",
            f"**{verdict.replace('_', ' ')}** — top **{pct['percentile']}%** "
            f"of `{pct['family']}`",
            f"_{data['age_days']:.1f}d old · {data['favs']}♥ · "
            f"{pct['velocity']}/day{sales_line}_\n",
            f"**Why:** {reason}\n",
            "**3 actions:**",
        ]
        for i, a in enumerate(actions, 1):
            lines.append(f"{i}. {a}")

        await ctx.send("\n".join(lines)[:1900])

    # =========================================================
    # !autopsy
    # =========================================================
    @bot.command(name="autopsy")
    async def autopsy(ctx, item_id: int, *, notes: str = ""):
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
                acts = [
                    f"Wait {max(1, int(7 - item_stats['age_days']))} more days",
                    "Post 1 TikTok per day while you wait",
                    f"Re-run `!autopsy {item_id}` on day 7",
                ]
            elif verdict == "DOUBLE_DOWN":
                acts = ["Launch a **variant** within 7 days — same motion, new theme.",
                        "Post 1 TikTok/day for 7 days.",
                        "Reply to every comment within 1h."]
            elif verdict == "KEEP":
                acts = ["Post 3 TikToks this week (cross-post Shorts + Reels).",
                        f"Test price at R${max((price or 0) - 5, 45)}.",
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
                f"Top **{pct_data['percentile']}%** of `{pct_data['family']}`",
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
        try:
            from gemini_brain import (
                is_available, extract_keywords, _generate, verify_titles,
                classify_keyword_intelligence, format_keyword_intel_for_prompt,
            )
            if competition_data:
                fast_class = classify_competition_batch(competition_data)
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
                if deep_intel and deep_intel.get("diagnosis"):
                    intel_lines.append("## 🎯 DIAGNOSIS")
                    intel_lines.append(deep_intel["diagnosis"])
                    intel_lines.append("")
                    bp = deep_intel.get("best_pivot") or {}
                    if bp.get("keyword"):
                        intel_lines.append("## 🚀 BEST PIVOT (from DB, may also be saturated)")
                        intel_lines.append(
                            f"**`{bp.get('keyword')}`** — supply={bp.get('supply',0)}, "
                            f"median_favs={bp.get('median_favs',0)}, bucket={bp.get('bucket','?')}"
                        )
                        if bp.get("why_better"):
                            intel_lines.append(f"> {bp['why_better']}")

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
            from gemini_brain import is_available, extract_keywords, _generate, verify_titles
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
  "edit_reasoning": "2-3 short sentences. Why these titles work. Talk like a person.",
  "what_was_wrong": "2-3 short sentences. Say SATURATED if that's it. No filler."
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

            verified_groups = {}
            rejected_count = 0
            for gname, gtitles in all_groups.items():
                v, r = verify_titles(gtitles, allow_list)
                v_clean = []
                for t in v:
                    toks = t.lower().split()
                    if toks and toks[0] in forbidden_first_set:
                        rejected_count += 1
                        continue
                    v_clean.append(t)
                if v_clean:
                    verified_groups[gname] = v_clean

            lines = ["# 🧠 10 RECOVERY TITLES\n"]
            if verified_groups:
                for gname, titles in verified_groups.items():
                    lines.append(f"**{gname}**")
                    for t in titles:
                        lines.append(f"• `{t}`")
                    lines.append("")
                if rejected_count:
                    lines.append(
                        f"_({rejected_count} title(s) rejected for starting with "
                        f"a SATURATED keyword.)_\n"
                    )
            else:
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
                for k in ("titles_safe", "titles_differentiated",
                          "titles_longtail", "titles_viral"):
                    all_titles.extend(data.get(k) or [])
                if all_titles:
                    scored_recovery = await asyncio.to_thread(
                        score_titles_batch, all_titles, family
                    )
                    champion, backup, _ = pick_champion(scored_recovery)

                    stat_lines = ["# 📊 STATISTICAL RECOVERY RANKING\n",
                                  "_Real word-lift × search-demand from DB._\n"]
                    for i, sc in enumerate(scored_recovery[:5], 1):
                        stat_lines.append(
                            f"**#{i} `{sc['title']}`** — score **{sc['score']}**"
                            + (f" · gap {sc.get('visibility_gap', 0):.0f}"
                               if sc.get("visibility_gap", 0) >= 5 else "")
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
                            stat_lines.append(
                                f"   {emoji} `{b['word']}` lift {lift}× "
                                f"({b['sample']} items · {b['demand']} searches) "
                                f"→ +{b['contribution']}"
                            )
                        stat_lines.append("")

                    stat_body = "\n".join(stat_lines)
                    for i in range(0, len(stat_body), 1900):
                        await ctx.send(stat_body[i:i+1900])
                        await asyncio.sleep(0.3)
            except Exception as e:
                print(f"[autopsy] title scoring failed: {e}", flush=True)

            # TAGS MERGE — uses tag_generator (not description_engine)
            merged_desc = None
            try:
                from tag_generator import generate_tags

                tag_seed = None
                if champion and champion.get("title"):
                    tag_seed = champion["title"]
                elif data.get("titles_safe"):
                    tag_seed = data["titles_safe"][0]
                elif name:
                    tag_seed = name

                if tag_seed:
                    tag_result = await asyncio.to_thread(
                        generate_tags, tag_seed, family, 45
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
                final_lines.append(
                    f"{label} `{pivot_kw}` "
                    f"(confidence **{pivot_conf:.0%}**)\n"
                    f"  _Reason: {pivot_reason}_"
                )

            if champion:
                name_label = ("**1. Name for the new upload:**" if kill
                              else "**1. New name:**")
                final_lines.append(
                    f"{name_label} `{champion['title']}`  ← statistical winner"
                )
                if backup:
                    final_lines.append(
                        f"**2. Backup name:** `{backup['title']}`"
                    )
            elif data.get("titles_safe"):
                final_lines.append(f"**1. New name:** `{data['titles_safe'][0]}`")

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
                    "**5. Today:** nothing. Give it another week of traffic."
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
            "**Step 2/3** — peer autopsy..."
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
            "**Step 3/3** — writing the plan..."
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
        await ctx.send("\n".join(plan)[:1900])
