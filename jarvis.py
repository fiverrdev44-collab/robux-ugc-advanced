"""jarvis.py — AI strategist for YOUR catalog."""
import re
import json
from collections import Counter
from gemini_brain import _generate, is_available
from monitoring_config import is_excluded
from portfolio_brain import _item_snapshot, _competitors, _classify_item


def _portfolio_conn(get_db):
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT item_id, name, asset_type_id FROM my_portfolio")
        return [
            {"id": r[0], "name": r[1], "asset_type_id": r[2]}
            for r in cur.fetchall() if not is_excluded(r[2])
        ]
    finally:
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass


def _collect_full_context(get_db):
    from post_monitor import get_pulse, get_recent_events
    portfolio = _portfolio_conn(get_db)
    if not portfolio:
        return None
    pulse = get_pulse(get_db, hours=24)
    events = get_recent_events(get_db, hours=24)

    items = []
    conn = get_db(); cur = conn.cursor()
    try:
        for p in pulse:
            snap = _item_snapshot(cur, p["item_id"])
            if not snap:
                continue
            comps = _competitors(cur, snap["name"], snap["asset_type_id"], cap=80)
            diag = _classify_item(snap, comps)
            top = comps[0] if comps else None
            items.append({
                **p,
                "verdict": diag.get("verdict"),
                "percentile": diag.get("percentile", 0),
                "niche_median_favs": diag.get("niche_median", 0),
                "niche_top10_favs": diag.get("niche_top10", 0),
                "niche_median_price": diag.get("niche_price_median", 0),
                "competitor_count": len(comps),
                "age_days": snap.get("age_days", 0),
                "top_competitor": (
                    {"name": top[0][:60], "favs": top[1] or 0, "price": top[2] or 0}
                    if top else None
                ),
            })
    finally:
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass
    return {"items": items, "events": events}


def _is_edit_viable(item):
    age = item.get("age_days", 0) or 0
    favs = item.get("favs", 0) or 0
    if age >= 30:
        return False, f"Age {age:.0f}d >= 30"
    if favs < 5:
        return False, f"Only {favs} favs"
    return True, ""


def _extract_patterns(items):
    if not items:
        return {}
    sellers = [i for i in items if (i.get("sales_24h") or 0) > 0]
    non_sellers = [i for i in items if (i.get("sales_24h") or 0) == 0 and i.get("favs", 0) > 20]

    def first_token(n):
        t = re.findall(r"[a-z]{4,}", (n or "").lower())
        return t[0] if t else None

    seller_t = [t for t in (first_token(i["name"]) for i in sellers) if t]
    loser_t = [t for t in (first_token(i["name"]) for i in non_sellers) if t]

    return {
        "total_items": len(items),
        "sellers": len(sellers),
        "winners": sum(1 for i in items if i.get("verdict") in ("WINNER", "STRONG", "ACCELERATING")),
        "dead": sum(1 for i in items if i.get("verdict") == "DEAD"),
        "edit_viable": sum(1 for i in items if _is_edit_viable(i)[0]),
        "kill_only": sum(1 for i in items if not _is_edit_viable(i)[0]),
        "total_rev_24h": sum(i.get("revenue_24h") or 0 for i in items),
        "total_sales_24h": sum(i.get("sales_24h") or 0 for i in items),
        "total_favs": sum(i.get("favs") or 0 for i in items),
        "avg_winner_price": round(sum(i["price"] for i in sellers if i.get("price")) / len(sellers)) if sellers else 0,
        "avg_loser_price": round(sum(i["price"] for i in non_sellers if i.get("price")) / len(non_sellers)) if non_sellers else 0,
        "seller_first_tokens": Counter(seller_t).most_common(5),
        "loser_first_tokens": Counter(loser_t).most_common(5),
    }


def _call_jarvis(items, events, patterns):
    lines = []
    for i in items:
        viable, reason = _is_edit_viable(i)
        v_str = "YES" if viable else f"NO ({reason})"
        lines.append(
            f"ITEM: {i['name'][:60]}\n"
            f"  Age {i.get('age_days', 0):.1f}d | Edit-viable: {v_str}\n"
            f"  {i.get('verdict')} · percentile {i.get('percentile')}%\n"
            f"  Favs {i['favs']} (+{i.get('fav_velocity', 0)}/24h) | "
            f"Sales24h {i.get('sales_24h', 0)} | Rev24h R${i.get('revenue_24h', 0)}\n"
            f"  Conv {i.get('conversion_pct', 0)}% | Price R${i['price']}\n"
            f"  Niche: {i.get('competitor_count', 0)} comps, med {i.get('niche_median_favs', 0)} favs, "
            f"top10 {i.get('niche_top10_favs', 0)}, med price R${i.get('niche_median_price', 0)}"
        )

    ev_lines = [f"  [{e['severity']}] {e['type']}: {e['message']}" for e in events[:15]]

    prompt = f"""You are JARVIS — elite Roblox UGC strategist.

=== ITEMS ({patterns['total_items']}) ===
{chr(10).join(lines)}

=== EVENTS ===
{chr(10).join(ev_lines) if ev_lines else '(none)'}

=== PATTERNS ===
- Sellers: {patterns['sellers']}/{patterns['total_items']} · Winners {patterns['winners']} · Dead {patterns['dead']}
- Edit-viable: {patterns['edit_viable']} | Kill-only: {patterns['kill_only']}
- 24h rev R${patterns['total_rev_24h']} · sales {patterns['total_sales_24h']}
- Avg price SELLING R${patterns['avg_winner_price']} vs NON-selling R${patterns['avg_loser_price']}
- Winning first-tokens: {patterns['seller_first_tokens']}
- Losing first-tokens: {patterns['loser_first_tokens']}

Return ONLY JSON:
{{
  "headline": "ONE sentence with the most important number.",
  "hero_item": {{"name": "...", "why": "2-3 sentences citing numbers", "next_move": "ONE action"}},
  "problem_items": [{{"name": "...", "diagnosis": "...", "edit_viable": true/false,
                     "reason_if_not_viable": "...", "action": "EXACT title or KILL + remix"}}],
  "portfolio_pattern": "2-3 sentences grounded in tokens + price data.",
  "next_launch": {{"concept": "...", "title": "...", "price": 58, "rationale": "..."}},
  "stop_doing": ["1-3 with numbers"],
  "double_down_on": ["1-3 with numbers"],
  "weekly_focus": "ONE specific goal"
}}

EDIT VS KILL: Edit-viable requires age < 30, favs >= 5, not already edited. Give EXACT title.
RULES: cite numbers, no predictions, no emojis, output ONLY JSON."""

    raw = _generate(prompt, json_mode=True, temperature=0.35, max_tokens=3000)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}


def run_jarvis(get_db):
    if not is_available():
        return {"error": "AI offline"}
    ctx = _collect_full_context(get_db)
    if not ctx or not ctx.get("items"):
        return {"error": "no_portfolio"}
    patterns = _extract_patterns(ctx["items"])
    advice = _call_jarvis(ctx["items"], ctx["events"], patterns)
    return {"items": ctx["items"], "events": ctx["events"],
            "patterns": patterns, "advice": advice}


def format_jarvis_report(data):
    if not data:
        return "# JARVIS\n\nNo data."
    if data.get("error"):
        if data["error"] == "no_portfolio":
            return "# JARVIS\n\n**No items.** Run `!portfolio sync`."
        return f"# JARVIS\n\n`{data['error']}`"

    p = data["patterns"]
    a = data.get("advice") or {}

    lines = ["```", "╔══════════════════════════════════════════════════════════╗",
             "║                    J A R V I S                           ║",
             "╚══════════════════════════════════════════════════════════╝", "```", ""]

    if a.get("headline"):
        lines.append(f"## 💬 {a['headline']}\n")

    lines.append("## 📊 LIVE NUMBERS")
    lines.append(f"• Items: **{p['total_items']}** · Selling: **{p['sellers']}** · Winners: **{p['winners']}** · Dead: **{p['dead']}**")
    lines.append(f"• Edit-viable: **{p['edit_viable']}** · Kill-only: **{p['kill_only']}**")
    lines.append(f"• 24h: **R${p['total_rev_24h']:,}** rev · **{p['total_sales_24h']}** sales · **{p['total_favs']:,}** favs")
    lines.append("")

    hero = a.get("hero_item") or {}
    if hero.get("name"):
        lines.append(f"## 🏆 HERO — `{hero['name'][:50]}`")
        if hero.get("why"): lines.append(f"**Why:** {hero['why']}")
        if hero.get("next_move"): lines.append(f"**Next:** {hero['next_move']}")
        lines.append("")

    for i, prob in enumerate(a.get("problem_items") or [], 1):
        lines.append(f"## ⚠️ PROBLEM {i} — `{prob.get('name', '?')[:50]}`")
        lines.append(f"_{prob.get('diagnosis', '')}_")
        if prob.get("edit_viable"):
            lines.append(f"✅ **EDIT** — {prob.get('action', '')}")
            lines.append("→ Wait 72h.")
        else:
            lines.append(f"❌ **KILL** — {prob.get('reason_if_not_viable', '')}")
            lines.append(f"→ {prob.get('action', '')}")
        lines.append("")

    if a.get("portfolio_pattern"):
        lines.append("## 🧠 PATTERN"); lines.append(a["portfolio_pattern"]); lines.append("")

    nl = a.get("next_launch") or {}
    if nl.get("concept"):
        lines.append("## 🚀 NEXT LAUNCH")
        lines.append(f"**{nl['concept']}**")
        if nl.get("title"): lines.append(f"Title: `{nl['title']}`")
        if nl.get("price"): lines.append(f"Price: R${nl['price']}")
        if nl.get("rationale"): lines.append(f"_{nl['rationale']}_")
        lines.append("")

    if a.get("stop_doing"):
        lines.append("## 🛑 STOP")
        for s in a["stop_doing"]: lines.append(f"• {s}")
        lines.append("")

    if a.get("double_down_on"):
        lines.append("## 🎯 DOUBLE DOWN")
        for d in a["double_down_on"]: lines.append(f"• {d}")
        lines.append("")

    if a.get("weekly_focus"):
        lines.append(f"## 📅 THIS WEEK\n**{a['weekly_focus']}**")

    return "\n".join(lines)
