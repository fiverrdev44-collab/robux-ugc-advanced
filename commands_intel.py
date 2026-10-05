"""
commands_intel.py — All intel commands. Category-aware autopsy.
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
    # !autopsy — CATEGORY-AWARE SUPERCOMPUTER EDITION
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

            # ── Detect category family ──────────────────────
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

        # ── KEYWORD INTELLIGENCE ────────────────────────────
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
                        intel_lines.append("## 🚀 DB-ONLY PIVOT (may also be saturated)")
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

        # ── CREATIVE PIVOT EXPANSION (category-aware) ───────
        creative_pivot_result = None
        try:
            from creative_pivot import find_creative_pivots, format_creative_pivot_report
            if name_words:
                await ctx.send(
                    "🚀 **Expanding creatively — AI + search data + learned keywords...**"
                )

                def _run_pivot():
                    c2 = get_db(); cur2 = c2.cursor()
                    try:
                        return find_creative_pivots(
                            seed_words=name_words,
                            item_type=family,
                            cur=cur2,
                            cookie=cookie,
                            max_candidates=25,
                            live_verify_top_n=3,
                        )
                    finally:
                        cur2.close(); c2.close()

                creative_pivot_result = await asyncio.to_thread(_run_pivot)
                cp_body = format_creative_pivot_report(creative_pivot_result)
                for i in range(0, len(cp_body), 1900):
                    await ctx.send(cp_body[i:i+1900]); await asyncio.sleep(0.3)
        except Exception as cpe:
            print(f"[autopsy] creative pivot failed: {cpe}", flush=True)

        # ── AI helpers ──────────────────────────────────────
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
            try:
                from discord_ugc_bot import _build_allow_list
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

        # Inject creative pivot keywords into allow_list
        if creative_pivot_result and creative_pivot_result.get("top_pivots"):
            for p in creative_pivot_result["top_pivots"]:
                kw = p.get("keyword")
                if kw and kw not in allow_list:
                    allow_list.append(kw)

        # Build category-aware prompt
        type_words_str = ", ".join(cfg["type_words"][:5])
        archetypes_str = "\n".join(f"  - {a}" for a in cfg["title_archetypes"][:5])

        intel_block = "(no keyword intelligence available)"
        try:
            from gemini_brain import format_keyword_intel_for_prompt
            if deep_intel:
                intel_block = format_keyword_intel_for_prompt(deep_intel)
        except Exception:
            pass

        creative_block = ""
        pivot_hint = ""
        if creative_pivot_result and creative_pivot_result.get("top_pivots"):
            creative_block = "\n=== 🚀 CREATIVE PIVOTS (use these!) ===\n"
            for i, p in enumerate(creative_pivot_result["top_pivots"][:5], 1):
                live = f" · LIVE {p['live_emoji']} {p['live_bucket']}" if p.get("live_bucket") else ""
                creative_block += (
                    f"{i}. {p['emoji']} `{p['keyword']}` — {p['bucket']} "
                    f"(supply={p['supply']}, median_favs={p['median_favs']}){live}\n"
                )
            best = creative_pivot_result["top_pivots"][0]["keyword"]
            creative_block += f"\n>>> USE `{best}` as primary token in at least 3 titles. <<<\n"

        recovery_prompt = f"""You are the #1 Roblox UGC naming strategist. A creator's item is FAILING. Fix it.

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
{pivot_hint}{creative_block}
=== SHAPE RULE FOR THIS CATEGORY ===
{cfg['shape_rule']}

=== EXAMPLE TITLE STRUCTURES ===
{archetypes_str}

=== CRITICAL RULES (NON-NEGOTIABLE) ===
1. NEVER call a high-competition keyword "weak". High competition = SATURATED = HIGH DEMAND.
   "WEAK" is RESERVED ONLY for keywords with median_favs < 50.
2. If any seed is SATURATED, say so explicitly using the word "SATURATED".
3. USE THE CREATIVE PIVOT KEYWORD in at least 3 titles.
4. Every title MUST be 3-5 words.
5. Every title MUST start with a SEARCHABLE noun or verb.
6. Every title MUST end with one of: {type_words_str}
7. Use ONLY these allow-list words + glue + type words:
   {', '.join(allow_list[:80])}
8. Every title MUST be UNIQUE.

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
  "primary_keyword": "best first word — MUST be the creative pivot",
  "edit_reasoning": "3-4 sentences referencing the pivot.",
  "what_was_wrong": "3-4 sentences. Use SATURATED, not weak."
}}
"""

        try:
            raw = await asyncio.to_thread(
                _generate, recovery_prompt, True, 0.9, 6000, "gemini"
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

            all_groups = {
                "🟢 SAFE (search-first)":           data.get("titles_safe") or [],
                "🎯 DIFFERENTIATED (unique angle)": data.get("titles_differentiated") or [],
                "🔎 LONG-TAIL SEO (4+ keywords)":   data.get("titles_longtail") or [],
                "🔥 VIRAL (meme/TikTok hook)":      data.get("titles_viral") or [],
            }

            verified_groups = {}
            for gname, gtitles in all_groups.items():
                v, r = verify_titles(gtitles, allow_list)
                if v: verified_groups[gname] = v

            lines = ["# 🧠 10 RECOVERY TITLES\n"]
            if verified_groups:
                for gname, titles in verified_groups.items():
                    lines.append(f"**{gname}**")
                    for t in titles:
                        lines.append(f"• `{t}`")
                    lines.append("")
            else:
                lines.append("⚠️ Titles failed verification.")

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

            # ── SMART PIPELINE ──
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
                    c3 = get_db(); cur3 = c3.cursor()
                    try:
                        pipeline_intent = dict(intent)
                        if creative_pivot_result and creative_pivot_result.get("top_pivots"):
                            pipeline_intent["search_terms"] = list(
                                set(pipeline_intent.get("search_terms", []))
                                | {p["keyword"] for p in creative_pivot_result["top_pivots"]}
                            )
                        return run_full_pipeline(
                            cur3, name or "ugc item",
                            intent=pipeline_intent, item_type=family,
                            category_asset_ids=cat_ids,
                            ai_titles=pipeline_ai_titles,
                            live_enrich=True,
                        )
                    finally:
                        cur3.close(); c3.close()

                pr = await asyncio.to_thread(_pipeline_autopsy)
                if pr and pr.get("report"):
                    pbody = pr["report"]
                    for i in range(0, len(pbody), 1900):
                        await ctx.send(pbody[i:i+1900]); await asyncio.sleep(0.3)

                try: await pipeline_msg.delete()
                except Exception: pass
            except Exception as pe:
                print(f"[autopsy] smart pipeline failed: {pe}", flush=True)

        except Exception as e:
            print(f"[autopsy] AI recovery failed: {e}", flush=True)
            try: await ai_msg.edit(content=f"⚠️ Recovery failed: `{e}`")
            except Exception: pass
