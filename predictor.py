"""
predictor.py — Success probability scoring before you build.
"""
import re

STOP = {"the","a","an","of","and","or","for","to","in","on","with","my","your"}


def _tokens(text):
    return [t for t in re.findall(r"[a-z]{3,}", (text or "").lower())
            if t not in STOP]


def predict_success(cur, idea_terms):
    if not idea_terms: return None
    patterns = [f"%{t}%" for t in idea_terms if len(t) >= 3]
    if not patterns: return None

    cur.execute("""
        SELECT id, LOWER(name), favorite_count, price, asset_type_id,
               EXTRACT(EPOCH FROM (NOW() - created_at))/86400 AS age_days
        FROM items WHERE favorite_count > 0
          AND (LOWER(name) LIKE ANY(%s) OR LOWER(COALESCE(description,'')) LIKE ANY(%s))
        LIMIT 2000
    """, (patterns, patterns))
    rows = cur.fetchall()

    if not rows:
        return {"probability": 0, "verdict": "NO DATA",
                "reason": "No items match.", "factors": {}}

    comp = len(rows)
    f1 = 25 if comp < 30 else 22 if comp < 100 else 15 if comp < 300 else 8 if comp < 1000 else 2

    favs_sorted = sorted([r[2] for r in rows], reverse=True)
    winner_favs = favs_sorted[max(0, len(favs_sorted)//10)]
    f2 = 20 if winner_favs > 100000 else 18 if winner_favs > 50000 else 14 if winner_favs > 10000 else 10 if winner_favs > 3000 else 4

    ages = [r[5] for r in rows if r[5] is not None]
    median_age = 999
    if ages:
        median_age = sorted(ages)[len(ages)//2]
        f3 = 15 if median_age < 30 else 12 if median_age < 90 else 8 if median_age < 180 else 3
    else:
        f3 = 6

    cur.execute("""
        SELECT COUNT(*) FROM items WHERE favorite_count > 0
          AND created_at > NOW() - INTERVAL '7 days'
          AND (LOWER(name) LIKE ANY(%s) OR LOWER(COALESCE(description,'')) LIKE ANY(%s))
    """, (patterns, patterns))
    recent = cur.fetchone()[0] or 0
    f4 = 15 if recent < 5 else 12 if recent < 15 else 6 if recent < 40 else 1

    cur.execute("""
        SELECT creator_name, COUNT(*) FROM items
        WHERE favorite_count > 0 AND creator_name IS NOT NULL
          AND (LOWER(name) LIKE ANY(%s) OR LOWER(COALESCE(description,'')) LIKE ANY(%s))
        GROUP BY creator_name ORDER BY 2 DESC LIMIT 1
    """, (patterns, patterns))
    top = cur.fetchone()
    conc_str = "0%"
    if top and top[1] > 0:
        conc = top[1] / len(rows)
        conc_str = f"{conc*100:.0f}%"
        f5 = 15 if conc < 0.15 else 10 if conc < 0.30 else 5 if conc < 0.50 else 1
    else:
        f5 = 10

    prices = [r[3] for r in rows if r[3] and 5 <= r[3] <= 10000]
    price_str = "N/A"
    if prices:
        median_price = sorted(prices)[len(prices)//2]
        price_str = f"R${median_price}"
        f6 = 10 if 30 <= median_price <= 120 else 5 if median_price < 30 else 7
    else:
        f6 = 5

    total = f1 + f2 + f3 + f4 + f5 + f6
    verdict = ("🟢 GOLDEN" if total >= 80 else "🟢 STRONG" if total >= 65 else
               "🟡 VIABLE" if total >= 50 else "🟠 RISKY" if total >= 35 else "🔴 AVOID")

    return {
        "probability": total, "verdict": verdict,
        "factors": {
            "competition_density":  {"score": f1, "max": 25, "raw": comp},
            "demand_signal":        {"score": f2, "max": 20, "raw": f"{winner_favs:,} favs"},
            "market_freshness":     {"score": f3, "max": 15, "raw": f"{int(median_age)}d" if ages else "?"},
            "recent_launch_rate":   {"score": f4, "max": 15, "raw": f"{recent} in 7d"},
            "creator_concentration":{"score": f5, "max": 15, "raw": conc_str},
            "price_room":           {"score": f6, "max": 10, "raw": price_str},
        },
    }


def format_prediction(pred, idea):
    if not pred: return "❌ Could not predict."
    lines = [f"# 🔮 SUCCESS PREDICTOR — `{idea}`", "",
             f"## {pred['verdict']} — **{pred['probability']}% probability**", "",
             "### Factor Breakdown"]
    for name, f in pred["factors"].items():
        bar_len = int(f["score"] / f["max"] * 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        lines.append(f"**{name.replace('_',' ').title()}** — `{f['score']:>2}/{f['max']:<2}` {bar}  _raw: {f['raw']}_")
    lines.append("")
    p = pred["probability"]
    if p >= 80: lines.append("**VERDICT:** Attack immediately.")
    elif p >= 65: lines.append("**VERDICT:** Strong. Launch within 7 days.")
    elif p >= 50: lines.append("**VERDICT:** Viable but needs differentiation.")
    elif p >= 35: lines.append("**VERDICT:** Risky. Only if you differentiate hard.")
    else: lines.append("**VERDICT:** Skip.")
    return "\n".join(lines)
