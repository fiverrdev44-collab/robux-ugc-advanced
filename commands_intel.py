"""
commands_intel.py — All intel commands in one file.
Loaded by discord_ugc_bot.py via register_intel_commands(bot, get_db, ASSET_TYPE_NAMES).
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
    detect_failure_mode,
    format_recovery_report,
    fetch_user_sales,
    enrich_item_stats_with_sales,
    fetch_item_from_roblox,
    save_item_to_db,
    save_item_and_created_at,
    fetch_created_date_live,
)


def register_intel_commands(bot, get_db, ASSET_TYPE_NAMES):

    # =========================================================
    # !momentum_debug
    # =========================================================
    @bot.command(name="momentum_debug")
    async def momentum_debug(ctx):
        progress = await ctx.send("🔍 **Running momentum debug...**")

        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT
                        COUNT(*) AS total_snaps,
                        COUNT(DISTINCT item_id) AS unique_items,
                        MIN(snapshot_at) AS earliest,
                        MAX(snapshot_at) AS latest,
                        EXTRACT(EPOCH FROM (MAX(snapshot_at) - MIN(snapshot_at)))/86400 AS days_span
                    FROM item_history
                """)
                r = cur.fetchone()

                cur.execute("""
                    SELECT COUNT(*) FROM (
                        SELECT item_id FROM item_history
                        GROUP BY item_id
                        HAVING COUNT(*) >= 2
                    ) sub
                """)
                multi_snap_items = cur.fetchone()[0] or 0

                cur.execute("""
                    SELECT COUNT(*) FROM (
                        SELECT item_id FROM item_history
                        GROUP BY item_id
                        HAVING MAX(favorite_count) - MIN(favorite_count) > 5
                    ) sub
                """)
                growing_items = cur.fetchone()[0] or 0

                return r, multi_snap_items, growing_items
            finally:
                cur.close(); conn.close()

        try:
            r, multi_snap_items, growing_items = await asyncio.to_thread(_run)
        except Exception as e:
            await progress.edit(content=f"❌ Debug failed: `{e}`")
            return

        try: await progress.delete()
        except Exception: pass

        msg = (
            f"**🔍 MOMENTUM DEBUG**\n"
            f"- Total snapshots: **{r[0]:,}**\n"
            f"- Unique items snapshotted: **{r[1]:,}**\n"
            f"- Items with 2+ snapshots: **{multi_snap_items:,}**\n"
            f"- Items with fav growth >5: **{growing_items:,}**\n"
            f"- Earliest snapshot: `{r[2]}`\n"
            f"- Latest snapshot: `{r[3]}`\n"
            f"- Time span (days): **{float(r[4] or 0):.2f}**"
        )
        await ctx.send(msg)

    # =========================================================
    # !momentum
    # =========================================================
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
            await progress.edit(
                content="📊 No momentum data yet.\n"
                        "Need 2+ days of `item_history` snapshots.\n"
                        "Run `!snapshot_now` or wait for the daily scheduler."
            )
            return

        try: await progress.delete()
        except Exception: pass

        body = format_momentum_report(words, title=f"🚀 MOMENTUM (last {days}d)")
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900]); await asyncio.sleep(0.3)

    # =========================================================
    # !predict
    # =========================================================
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

    # =========================================================
    # !oracle
    # =========================================================
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

    # =========================================================
    # !nextwave
    # =========================================================
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

    # =========================================================
    # !opportunities
    # =========================================================
    @bot.command(name="opportunities")
    async def opportunities_cmd(ctx):
        progress = await ctx.send("📅 **Scanning today's best plays...**")

        def _run():
            conn = get_db(); cur = conn.cursor()
            try:
                plays = build_daily_feed(cur, top_n=5)
                try:
                    nw = find_next_wave_opportunities(cur, top_n=5)
                except Exception:
                    nw = []
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
    # !autopsy — with SMART PIPELINE (live enrich)
    # =========================================================
    @bot.command(name="autopsy")
    async def autopsy(ctx, item_id: int, *, notes: str = ""):
        progress = await ctx.send(f"🔬 **Autopsying item `{item_id}`...**")
        cookie = os.getenv("ROBLOSECURITY_COOKIE_1") or os.getenv("ROBLOSECURITY_COOKIE")
        user_id = os.getenv("ROBLOX_USER_ID")

        # ── Fetch item + age ─────────────────────────────────
        row = None
        try:
            conn = get_db(); cur = conn.cursor()
            cur.execute("""
                SELECT id, name, favorite_count, total_sales, price,
                       asset_type_id, creator_name, description, created_at,
                       EXTRACT(EPOCH FROM (NOW() - COALESCE(created_at, fetched_at)))/86400 AS age_days
                FROM items WHERE id = %s
            """, (item_id,))
            row = cur.fetchone()

            await progress.edit(
                content=f"🔍 Refreshing `{item_id}` live from Roblox..."
            )
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
                           EXTRACT(EPOCH FROM (NOW() - COALESCE(created_at, fetched_at)))/86400 AS age_days
                    FROM items WHERE id = %s
                """, (item_id,))
                fresh = cur.fetchone()
                if fresh:
                    row = fresh

            if not row:
                await progress.edit(
                    content=f"❌ Item `{item_id}` not found in DB or Roblox. "
                            f"Check the ID is correct."
                )
                cur.close(); conn.close()
                return

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
                    except Exception:
                        pass

            name_words = [w for w in re.findall(r"[a-z]{3,}", (name or "").lower())][:4]
            if not name_words:
                await progress.edit(content="❌ Item name is empty.")
                cur.close(); conn.close()
                return

            patterns = [f"%{w}%" for w in name_words]
            cur.execute("""
                SELECT favorite_count FROM items
                WHERE favorite_count > 50 AND LOWER(name) LIKE ANY(%s)
                ORDER BY favorite_count DESC LIMIT 500
            """, (patterns,))
            favs_list = [r[0] for r in cur.fetchall() if r[0]]
            cur.close(); conn.close()

            winner_median_favs = 0
            if favs_list:
                sorted_f = sorted(favs_list, reverse=True)
                cutoff = max(1, len(sorted_f) // 10)
                winner_median_favs = sorted_f[cutoff - 1]

            item_stats = {
                "id": iid,
                "favs": favs or 0,
                "sales": sales_public or 0,
                "price": price or 0,
                "age_days": float(age_days or 0),
                "winner_median_favs": winner_median_favs,
                "category": atype,
            }
        except Exception as e:
            try:
                await progress.edit(content=f"❌ Autopsy failed: `{e}`")
            except Exception:
                pass
            return

        # Silent sales
        if cookie and user_id:
            try:
                sales_list = await asyncio.to_thread(fetch_user_sales, cookie, user_id, 3)
                item_stats = enrich_item_stats_with_sales(item_stats, sales_list)
                print(f"[autopsy] internal sales: {item_stats.get('sales', 0)}", flush=True)
            except Exception as e:
                print(f"[autopsy] sales fetch failed: {e}", flush=True)

        diagnosis = detect_failure_mode(item_stats)
        try: await progress.delete()
        except Exception: pass

        header = (
            f"# 🩺 AUTOPSY — `{name[:60]}`\n"
            f"**Creator:** {creator or '?'} · **Item ID:** `{iid}`\n"
            f"**Type:** {ASSET_TYPE_NAMES.get(atype, atype)}\n"
            f"**Age:** {item_stats['age_days']:.1f} days"
        )
        await ctx.send(header)

        body = format_recovery_report(diagnosis, item_stats, show_sales=False)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900]); await asyncio.sleep(0.3)

        # ── 10 recovery titles ───────────────────────────────
        try:
            from gemini_brain import is_available, extract_keywords, _generate, verify_titles
        except Exception:
            return

        if not is_available():
            return

        ai_msg = await ctx.send("🧠 **Generating 10 recovery titles + descriptions...**")

        intent = extract_keywords(name or "dance emote")
        allow_list, top_items, stats = [], [], {}
        try:
            from discord_ugc_bot import _build_allow_list
            def _run_allow():
                return _build_allow_list(intent, 60, None)
            allow_list, top_items, stats = await asyncio.to_thread(_run_allow)
        except Exception as e:
            print(f"[autopsy] allow-list failed: {e}", flush=True)

        if not allow_list:
            allow_list = list(set(
                [w.lower() for w in re.findall(r"[a-z]{4,}", name or "")]
                + ["emote", "dance", "sway", "hip", "groove", "flow",
                   "freestyle", "bounce", "tiktok", "viral", "smooth"]
            ))

        recovery_prompt = f"""You are the #1 Roblox UGC naming strategist. A creator's item is FAILING. Fix it with new titles.

=== THE FAILING ITEM ===
Current name: {name}
Creator description: {desc or '(none)'}
Current favs: {item_stats['favs']}
Current sales: {item_stats['sales']}
Price: R${item_stats['price']}
Age: {item_stats['age_days']:.1f} days
Winner median in niche: {item_stats['winner_median_favs']:,} favs

FAILURE MODE: {diagnosis['failure_mode']}

=== YOUR JOB ===
Return 10 NEW titles and 3 descriptions as JSON.

RULES — NON-NEGOTIABLE:
1. Every title MUST be 3-5 words.
2. Every title MUST start with a SEARCHABLE noun or verb.
   NEVER start with an adjective (Chill, Groovy, Smooth, Cool, Cute).
3. Every title MUST end with "Emote", "Dance", or "Freestyle".
4. Use ONLY these allow-list words + glue + item-type words:
   {', '.join(allow_list[:60])}
5. Every title MUST be UNIQUE.

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
  "primary_keyword": "best first word",
  "edit_reasoning": "2-3 sentences",
  "what_was_wrong": "1-2 sentences"
}}
"""

        try:
            raw = await asyncio.to_thread(
                _generate, recovery_prompt, True, 0.9, 6000, "gemini"
            )
            data = {}
            if raw:
                try:
                    data = json.loads(raw)
                except Exception:
                    m = re.search(r"\{.*\}", raw, re.DOTALL)
                    data = json.loads(m.group(0)) if m else {}

            if not data:
                await ai_msg.edit(content="⚠️ AI returned nothing. Try again in 2 min.")
                return

            all_groups = {
                "🟢 SAFE (search-first)":           data.get("titles_safe") or [],
                "🎯 DIFFERENTIATED (unique angle)": data.get("titles_differentiated") or [],
                "🔎 LONG-TAIL SEO (4+ keywords)":   data.get("titles_longtail") or [],
                "🔥 VIRAL (meme/TikTok hook)":      data.get("titles_viral") or [],
            }

            verified_groups = {}
            for gname, gtitles in all_groups.items():
                v, r = verify_titles(gtitles, allow_list)
                if v:
                    verified_groups[gname] = v

            lines = ["# 🧠 10 RECOVERY TITLES\n"]

            if verified_groups:
                for gname, titles in verified_groups.items():
                    lines.append(f"**{gname}**")
                    for t in titles:
                        lines.append(f"• `{t}`")
                    lines.append("")
            else:
                lines.append("⚠️ Titles failed verification. Fallback picks:")
                lines.append("• `Hip Sway Dance Emote`")
                lines.append("• `Hip Sway Freestyle`")
                lines.append("• `Sway Dance Emote`")
                lines.append("")

            lines.append("---\n")
            lines.append("## 📝 3 DESCRIPTIONS\n")

            if data.get("description_seo"):
                lines.append("**🎯 SEO (recommended)**")
                lines.append(f"```\n{data['description_seo'][:400]}\n```")
                lines.append("")
            if data.get("description_hype"):
                lines.append("**🔥 Hype**")
                lines.append(f"```\n{data['description_hype'][:300]}\n```")
                lines.append("")
            if data.get("description_short"):
                lines.append("**⚡ Short**")
                lines.append(f"```\n{data['description_short'][:200]}\n```")
                lines.append("")

            if data.get("primary_keyword"):
                lines.append(f"## 🎯 LEAD WITH: `{data['primary_keyword']}`")
                lines.append("")
            if data.get("what_was_wrong"):
                lines.append("## ❌ What Was Wrong")
                lines.append(data["what_was_wrong"])
                lines.append("")
            if data.get("edit_reasoning"):
                lines.append("## ✅ Strategy")
                lines.append(data["edit_reasoning"])

            body = "\n".join(lines)
            try:
                await ai_msg.edit(content=body[:1900])
            except Exception:
                pass
            if len(body) > 1900:
                for i in range(1900, len(body), 1900):
                    await ctx.send(body[i:i+1900])
                    await asyncio.sleep(0.3)

            # ── SMART PIPELINE (live enrich + cascade) ──
            try:
                from smart_pipeline import run_full_pipeline
                pipeline_ai_titles = []
                for k in ("titles_safe", "titles_differentiated",
                          "titles_longtail", "titles_viral"):
                    pipeline_ai_titles.extend(data.get(k) or [])

                cat_ids = [atype] if atype else None

                pipeline_msg = await ctx.send(
                    "🧬 **Running smart pipeline...**\n"
                    "_Live-enriching thin data · cascading to alternatives_"
                )

                def _pipeline_autopsy():
                    conn3 = get_db(); cur3 = conn3.cursor()
                    try:
                        return run_full_pipeline(
                            cur3, name or "dance emote",
                            intent=None, item_type="emote",
                            category_asset_ids=cat_ids,
                            ai_titles=pipeline_ai_titles,
                            live_enrich=True,
                        )
                    finally:
                        cur3.close(); conn3.close()

                pr = await asyncio.to_thread(_pipeline_autopsy)
                if pr and pr.get("report"):
                    pbody = pr["report"]
                    for i in range(0, len(pbody), 1900):
                        await ctx.send(pbody[i:i+1900])
                        await asyncio.sleep(0.3)

                try: await pipeline_msg.delete()
                except Exception: pass
            except Exception as pe:
                print(f"[autopsy] smart pipeline failed: {pe}", flush=True)

        except Exception as e:
            print(f"[autopsy] AI recovery failed: {e}", flush=True)
            try:
                await ai_msg.edit(content=f"⚠️ Recovery failed: `{e}`")
            except Exception:
                pass
