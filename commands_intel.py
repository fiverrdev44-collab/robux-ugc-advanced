"""
commands_intel.py — All intel commands in one file.
Loaded by discord_ugc_bot.py via register_intel_commands(bot, get_db, ASSET_TYPE_NAMES).
"""
import os
import re
import json
import asyncio

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
)


def register_intel_commands(bot, get_db, ASSET_TYPE_NAMES):

    @bot.command(name="momentum")
    async def momentum_cmd(ctx, days: int = 7):
        days = max(3, min(days, 30))
        try:
            conn = get_db(); cur = conn.cursor()
            words = find_momentum_keywords(cur, days=days, min_items=2, top_n=30)
            cur.close(); conn.close()
        except Exception as e:
            await ctx.send(f"❌ Failed: `{e}`"); return
        if not words:
            await ctx.send("📊 No momentum data yet.\nNeed 2+ days of `item_history` snapshots.")
            return
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
        try:
            conn = get_db(); cur = conn.cursor()
            pred = predict_success(cur, words)
            cur.close(); conn.close()
        except Exception as e:
            await ctx.send(f"❌ Failed: `{e}`"); return
        if not pred:
            await ctx.send("❌ Not enough data."); return
        body = format_prediction(pred, idea)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900]); await asyncio.sleep(0.3)

    @bot.command(name="oracle")
    async def oracle_cmd(ctx, *, keyword: str = ""):
        if not keyword.strip():
            await ctx.send("Usage: `!oracle dance`"); return
        kw = keyword.strip().lower().split()[0]
        try:
            conn = get_db(); cur = conn.cursor()
            f = forecast_trend(cur, kw)
            cur.close(); conn.close()
        except Exception as e:
            await ctx.send(f"❌ Failed: `{e}`"); return
        if not f:
            await ctx.send(f"❌ Not enough data for `{kw}`."); return
        body = format_oracle_forecast(f)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900]); await asyncio.sleep(0.3)

    @bot.command(name="nextwave")
    async def nextwave_cmd(ctx):
        progress = await ctx.send("🌊 **Scanning for next-wave keywords...**")
        try:
            conn = get_db(); cur = conn.cursor()
            ranked = find_next_wave_opportunities(cur, top_n=10)
            cur.close(); conn.close()
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
        try:
            conn = get_db(); cur = conn.cursor()
            plays = build_daily_feed(cur, top_n=5)
            try:
                next_wave = find_next_wave_opportunities(cur, top_n=5)
            except Exception:
                next_wave = []
            cur.close(); conn.close()
        except Exception as e:
            await progress.edit(content=f"❌ Failed: `{e}`"); return
        try: await progress.delete()
        except Exception: pass
        body = format_daily_feed(plays, next_wave)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900]); await asyncio.sleep(0.3)

    @bot.command(name="autopsy")
    async def autopsy(ctx, item_id: int, *, notes: str = ""):
        progress = await ctx.send(f"🔬 **Autopsying item `{item_id}`...**")
        cookie = os.getenv("ROBLOSECURITY_COOKIE_1") or os.getenv("ROBLOSECURITY_COOKIE")
        user_id = os.getenv("ROBLOX_USER_ID")

        try:
            conn = get_db(); cur = conn.cursor()
            cur.execute("""
                SELECT id, name, favorite_count, total_sales, price,
                       asset_type_id, creator_name,
                       EXTRACT(EPOCH FROM (NOW() - COALESCE(created_at, fetched_at)))/86400 AS age_days
                FROM items WHERE id = %s
            """, (item_id,))
            row = cur.fetchone()

            # If item is not in DB, fetch it live from Roblox
            if not row:
                await progress.edit(
                    content=f"🔍 Item `{item_id}` not in DB — fetching live from Roblox..."
                )
                live = await asyncio.to_thread(
                    fetch_item_from_roblox, item_id, cookie
                )
                if not live:
                    await progress.edit(
                        content=(f"❌ Item `{item_id}` not found in DB or Roblox. "
                                 f"Check the ID is correct.")
                    )
                    cur.close(); conn.close()
                    return

                save_item_to_db(cur, live)
                conn.commit()

                try:
                    await asyncio.to_thread(
                        save_item_and_created_at, cur, live, item_id
                    )
                    conn.commit()
                except Exception as e:
                    print(f"[autopsy] created_at fetch failed: {e}", flush=True)

                # Re-fetch from DB now that it's inserted
                cur.execute("""
                    SELECT id, name, favorite_count, total_sales, price,
                           asset_type_id, creator_name,
                           EXTRACT(EPOCH FROM (NOW() - COALESCE(created_at, fetched_at)))/86400 AS age_days
                    FROM items WHERE id = %s
                """, (item_id,))
                row = cur.fetchone()
                if not row:
                    await progress.edit(
                        content=f"❌ Failed to save item `{item_id}`."
                    )
                    cur.close(); conn.close()
                    return

            (iid, name, favs, sales_public, price, atype, creator, age) = row

            name_words = [w for w in re.findall(r"[a-z]{3,}", (name or "").lower())][:4]
            if not name_words:
                await progress.edit(content="❌ Item name is empty.")
                cur.close(); conn.close(); return

            patterns = [f"%{w}%" for w in name_words]
            cur.execute("""SELECT favorite_count FROM items
                           WHERE favorite_count > 50 AND LOWER(name) LIKE ANY(%s)
                           ORDER BY favorite_count DESC LIMIT 500""", (patterns,))
            favs_list = [r[0] for r in cur.fetchall() if r[0]]
            cur.close(); conn.close()

            winner_median_favs = 0
            if favs_list:
                sorted_f = sorted(favs_list, reverse=True)
                cutoff = max(1, len(sorted_f) // 10)
                winner_median_favs = sorted_f[cutoff - 1]

            item_stats = {"id": iid, "favs": favs or 0, "sales": sales_public or 0,
                          "price": price or 0, "age_days": float(age or 0),
                          "winner_median_favs": winner_median_favs, "category": atype}
        except Exception as e:
            try: await progress.edit(content=f"❌ Autopsy failed: `{e}`")
            except Exception: pass
            return

        if cookie and user_id:
            try:
                sales_list = await asyncio.to_thread(fetch_user_sales, cookie, user_id, 3)
                item_stats = enrich_item_stats_with_sales(item_stats, sales_list)
                print(f"[autopsy] internal sales for {item_id}: {item_stats.get('sales',0)}", flush=True)
            except Exception as e:
                print(f"[autopsy] silent sales fetch failed: {e}", flush=True)

        diagnosis = detect_failure_mode(item_stats)
        try: await progress.delete()
        except Exception: pass

        header = (f"# 🩺 AUTOPSY — `{name[:60]}`\n"
                  f"**Creator:** {creator or '?'} · **Item ID:** `{iid}`\n"
                  f"**Type:** {ASSET_TYPE_NAMES.get(atype, atype)}")
        await ctx.send(header)

        body = format_recovery_report(diagnosis, item_stats, show_sales=False)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i+1900]); await asyncio.sleep(0.3)

        try:
            from gemini_brain import is_available, _generate
        except Exception:
            return

        if is_available() and diagnosis.get("fixable"):
            try:
                ai_msg = await ctx.send("🧠 **AI is writing recovery titles...**")
                recovery_prompt = f"""A Roblox UGC creator's item is failing. Write recovery titles.

ITEM: {name}
INTERNAL STATS (do NOT echo these to user):
- favs: {item_stats['favs']}
- sales: {item_stats['sales']}
- price: R${item_stats['price']}
- age: {item_stats['age_days']:.1f} days

FAILURE MODE: {diagnosis['failure_mode']}

Return ONLY JSON:
{{
  "recovery_titles": ["3 new title options"],
  "recovery_description": "full replacement description",
  "edit_reasoning": "1-2 sentences — do NOT mention sales numbers"
}}

RULES:
- Titles 3-5 words.
- First word = highest-value token.
- Do NOT mention sales, revenue, or R$ amounts.
- Output ONLY JSON.
"""
                raw = await asyncio.to_thread(_generate, recovery_prompt, True, 0.7, 2048, "gemini")
                if raw:
                    try: data = json.loads(raw)
                    except Exception:
                        m = re.search(r"\{.*\}", raw, re.DOTALL)
                        data = json.loads(m.group(0)) if m else {}
                    if data:
                        lines = ["## 🧠 AI RECOVERY TITLES\n"]
                        for i, t in enumerate(data.get("recovery_titles", []), 1):
                            lines.append(f"**{i}.** `{t}`")
                        lines.append("")
                        if data.get("recovery_description"):
                            lines.append("## 📝 REPLACEMENT DESCRIPTION")
                            lines.append(data["recovery_description"]); lines.append("")
                        if data.get("edit_reasoning"):
                            lines.append(f"**Why:** {data['edit_reasoning']}")
                        try: await ai_msg.edit(content="\n".join(lines)[:1900])
                        except Exception: pass
                    else:
                        try: await ai_msg.delete()
                        except Exception: pass
            except Exception as e:
                print(f"[autopsy] AI recovery failed: {e}", flush=True)
