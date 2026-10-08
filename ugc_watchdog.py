"""ugc_watchdog.py — Rule-based decisive analyst (clothing excluded)."""
import hashlib
from post_monitor import get_pulse, get_recent_events
from portfolio_brain import _item_snapshot, _competitors, _classify_item
from monitoring_config import is_excluded


def _decide_action(item, snap, diag, comps):
    age = snap.get("age_days", 0) or 0
    favs = snap.get("favs", 0) or 0
    price = snap.get("price", 0) or 0
    s24 = item.get("sales_24h", 0) or 0
    s6 = item.get("sales_6h", 0) or 0
    pct = diag.get("percentile", 0) or 0
    niche_med = diag.get("niche_median", 0) or 0
    niche_price = diag.get("niche_price_median", 0) or 0

    if age < 3:
        return "WAIT", f"Age {age:.1f}d — 72h needed."

    if s24 >= 3 and s6 >= 1:
        if pct >= 75:
            return "SCALE", f"Top {100-int(pct)}% · {s24}/24h. Make a themed remix."
        return "HOLD", f"Selling {s24}/24h. Do not edit."

    if s24 > 0 and s6 == 0 and age > 7:
        return "HOLD", f"Sold {s24} in 24h but 0 last 6h. Monitor 48h."

    if favs < 5 and age >= 7:
        return "KILL", f"Only {favs} favs after {age:.0f}d."

    if favs >= 30 and s24 == 0 and niche_price > 0:
        ratio = price / niche_price if niche_price else 1
        if ratio >= 1.3:
            return "PRICE", (
                f"{favs} favs, 0 sales. R${price} is {ratio:.1f}x "
                f"median R${niche_price}. Drop to R${int(niche_price)}."
            )
        return "EDIT", f"{favs} favs, 0 sales, price ok. Title is blocker. One edit."

    if 7 <= age <= 30 and favs >= 5 and s24 == 0:
        if pct < 30:
            return "EDIT", (
                f"Bottom {int(pct)}% ({favs} vs median {niche_med}). "
                f"One title edit. Wait 72h."
            )
        return "WAIT", f"At {int(pct)}%. Give 72h."

    if age > 30 and s24 == 0:
        return "REMIX", f"Age {age:.0f}d. Past edit window. Remix a winner."

    return "WAIT", "Monitoring."


def run_watchdog(get_db):
    from portfolio_tracker import get_portfolio
    from portfolio_brain import ensure_brain_tables

    conn = get_db(); cur = conn.cursor()
    try:
        ensure_brain_tables(cur)
        raw = get_portfolio(cur)
        portfolio = [p for p in raw if not is_excluded(p.get("asset_type_id"))]
    finally:
        cur.close(); conn.close()

    if not portfolio:
        return {"error": "no_portfolio"}

    pulse = get_pulse(get_db, hours=24)
    events = get_recent_events(get_db, hours=6)

    items = []
    conn = get_db(); cur = conn.cursor()
    try:
        for p in pulse:
            snap = _item_snapshot(cur, p["item_id"])
            if not snap:
                continue
            comps = _competitors(cur, snap["name"], snap["asset_type_id"], cap=80)
            diag = _classify_item(snap, comps)
            action, reason = _decide_action(p, snap, diag, comps)
            items.append({
                **p,
                "verdict": diag.get("verdict"),
                "percentile": diag.get("percentile", 0),
                "niche_median": diag.get("niche_median", 0),
                "niche_price": diag.get("niche_price_median", 0),
                "age_days": snap.get("age_days", 0),
                "action": action, "reason": reason,
            })
    finally:
        cur.close(); conn.close()

    priority = {"KILL": 0, "REMIX": 1, "EDIT": 2, "PRICE": 3,
                "SCALE": 4, "HOLD": 5, "WAIT": 6}
    items.sort(key=lambda i: (priority.get(i["action"], 9), -i.get("sales_24h", 0)))

    totals = {
        "items": len(items),
        "total_sales_24h": sum(i.get("sales_24h", 0) or 0 for i in items),
        "total_revenue_24h": sum(i.get("revenue_24h", 0) or 0 for i in items),
        "selling_count": sum(1 for i in items if (i.get("sales_24h", 0) or 0) > 0),
        "needs_action": sum(1 for i in items
                            if i["action"] in ("KILL", "REMIX", "EDIT", "PRICE")),
    }
    return {"items": items, "events": events, "totals": totals}


_EMOJI = {"SCALE": "🚀", "HOLD": "✅", "WAIT": "⏳", "EDIT": "✏️",
          "PRICE": "💰", "REMIX": "🔁", "KILL": "💀"}


def format_briefing(data):
    if not data:
        return "🩺 No data."
    if data.get("error") == "no_portfolio":
        return "🩺 No items. Run `!ugc sync`."

    t = data["totals"]; items = data["items"]
    lines = ["# 🩺 UGC WATCHDOG\n"]
    lines.append(f"**{t['items']}** · **{t['selling_count']}** selling · "
                 f"**{t['total_sales_24h']}** sales/24h · **R${t['total_revenue_24h']:,}**")
    if t["needs_action"]:
        lines.append(f"⚠️ **{t['needs_action']} need action**")
    lines.append("")

    urgent = [i for i in items if i["action"] in ("KILL", "REMIX", "EDIT", "PRICE")]
    if urgent:
        lines.append("## 🚨 ACTION REQUIRED")
        for i in urgent:
            lines.append(
                f"{_EMOJI.get(i['action'], '•')} **{i['action']}** — `{i['name'][:45]}`\n"
                f"   {i['reason']}\n"
            )

    healthy = [i for i in items if i["action"] in ("SCALE", "HOLD")]
    if healthy:
        lines.append("## ✅ HEALTHY")
        for i in healthy:
            lines.append(
                f"{_EMOJI.get(i['action'], '•')} `{i['name'][:45]}` — "
                f"{i.get('sales_24h', 0)}/24h · p{int(i.get('percentile', 0))}"
            )
        lines.append("")

    waiting = [i for i in items if i["action"] == "WAIT"]
    if waiting:
        lines.append("## ⏳ OBSERVING")
        for i in waiting:
            lines.append(
                f"⏳ `{i['name'][:45]}` — {i.get('favs', 0)} favs · "
                f"{i.get('age_days', 0):.1f}d"
            )
    return "\n".join(lines)


def compute_signature(data):
    if not data or data.get("error"):
        return "empty"
    parts = [
        f"{i['item_id']}:{i.get('sales_24h', 0)}:"
        f"{i.get('favs', 0) // 10}:{i['action']}"
        for i in sorted(data["items"], key=lambda x: x["item_id"])
    ]
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def should_alert(data, last_sig):
    if not data or data.get("error"):
        return False, last_sig
    sig = compute_signature(data)
    if sig == last_sig:
        return False, sig
    urgent = any(i["action"] in ("KILL", "REMIX", "EDIT", "PRICE")
                 for i in data["items"])
    sales = data["totals"]["total_sales_24h"] > 0
    return (urgent or sales), sig
