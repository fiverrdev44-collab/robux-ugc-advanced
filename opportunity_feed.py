"""
opportunity_feed.py — Daily ranked opportunity feed.
"""
from momentum import find_momentum_keywords
from predictor import predict_success
from oracle import find_next_wave_opportunities


def build_daily_feed(cur, top_n=5):
    momentum = find_momentum_keywords(cur, days=7, min_items=2, top_n=60)
    if not momentum: return []

    plays = []
    for m in momentum[:30]:
        word = m["word"]
        if len(word) < 4: continue
        try:
            pred = predict_success(cur, [word])
        except Exception:
            continue
        if not pred or pred["probability"] < 40: continue
        combined = pred["probability"] * min(m["momentum_ratio"], 5)
        plays.append({
            "keyword": word, "combined_score": round(combined, 1),
            "probability": pred["probability"], "verdict": pred["verdict"],
            "momentum_ratio": m["momentum_ratio"], "velocity": m["velocity_now"],
            "item_count": m["item_count"],
        })
    plays.sort(key=lambda x: x["combined_score"], reverse=True)
    return plays[:top_n]


def format_daily_feed(plays, next_wave=None):
    lines = ["# 📅 DAILY OPPORTUNITY FEED", ""]
    if plays:
        lines.append("_Ranked by probability × momentum._\n")
        for i, p in enumerate(plays, 1):
            lines.append(f"## {i}. `{p['keyword']}` — {p['verdict']}\n"
                         f"**Success probability:** {p['probability']}% · "
                         f"**Momentum:** {p['momentum_ratio']:.1f}x · "
                         f"**Velocity:** {p['velocity']:.0f} favs/day · "
                         f"**Competitors:** {p['item_count']}\n")
    else:
        lines.append("_No plays found. Run the enricher + snapshot more._\n")

    if next_wave:
        lines.append("\n---\n## 🌊 NEXT WAVE (build these next)\n")
        for i, r in enumerate(next_wave[:5], 1):
            rides = ", ".join(f"`{x}`" for x in r["rides_on"])
            lines.append(f"**{i}. `{r['word']}`** — score **{r['combined_score']:,}**\n"
                         f"   · Only **{r['count']}** items · avg **{r['avg_favs']:,}** favs\n"
                         f"   · Rides on: {rides}\n")
    return "\n".join(lines)
