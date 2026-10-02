"""
oracle.py — Forecast where trends go + find next-wave keywords.
"""
from collections import defaultdict, Counter
from momentum import _tokens


def forecast_trend(cur, keyword, days=14):
    pattern = f"%{keyword}%"
    cur.execute("""
        SELECT LOWER(name), favorite_count,
               EXTRACT(EPOCH FROM (NOW() - created_at))/86400 AS age_days
        FROM items WHERE favorite_count > 0 AND LOWER(name) LIKE %s LIMIT 1000
    """, (pattern,))
    rows = cur.fetchall()
    if len(rows) < 5:
        return None

    saturation = len(rows)
    ages = [r[2] for r in rows if r[2] is not None]
    median_age = sorted(ages)[len(ages) // 2] if ages else 999

    co = Counter()
    for name, _, _ in rows:
        for w in _tokens(name):
            if w != keyword:
                co[w] += 1

    cur.execute("""
        SELECT i.id, h.favorite_count, h.snapshot_at
        FROM item_history h JOIN items i ON i.id = h.item_id
        WHERE LOWER(i.name) LIKE %s AND h.snapshot_at > NOW() - INTERVAL '14 days'
        ORDER BY h.item_id, h.snapshot_at
    """, (pattern,))
    snaps = cur.fetchall()

    series = defaultdict(list)
    for iid, favs, when in snaps:
        series[iid].append((when, favs))

    accels = []
    for iid, s in series.items():
        s.sort()
        if len(s) < 3:
            continue
        mid = s[len(s) // 2][0]
        early = [x for x in s if x[0] < mid]
        late = [x for x in s if x[0] >= mid]
        if len(early) >= 2 and len(late) >= 2:
            ev = (early[-1][1] - early[0][1]) / max(1, (early[-1][0] - early[0][0]).days)
            lv = (late[-1][1] - late[0][1]) / max(1, (late[-1][0] - late[0][0]).days)
            if ev > 0:
                accels.append(lv / ev)
    avg_accel = sum(accels) / len(accels) if accels else 1.0

    if avg_accel > 2.0 and saturation < 200:
        trajectory = "🚀 ACCELERATING — enter now"
        verdict = "ENTER"
    elif avg_accel > 1.2 and saturation < 500:
        trajectory = "📈 RISING — enter within 7 days"
        verdict = "ENTER"
    elif avg_accel < 0.5:
        trajectory = "📉 DECAYING — exit or pivot"
        verdict = "EXIT"
    else:
        trajectory = "➡️ PEAKING — differentiate"
        verdict = "HOLD"

      # Filter: only suggest words that co-occur with keyword in EMOJI/EMOTE/AESTHETIC context
    # Reject generic words that just happen to appear alongside
    GENERIC_BLOCK = {
        "money", "potion", "jersey", "club", "game", "play", "item", "asset",
        "shop", "store", "buy", "sale", "free", "code", "gift", "reward",
        "user", "player", "group", "join", "follow", "like", "share",
    }

    next_words = []
    for w, c in co.most_common(50):
        if len(w) < 4:
            continue
        if w in GENERIC_BLOCK:
            continue

        # Only accept if the word itself passes a "relevance" test —
        # it must appear in at least 3 items that ALSO contain the main keyword
        cur.execute(
            """SELECT COUNT(*), COALESCE(AVG(favorite_count),0)
               FROM items WHERE LOWER(name) LIKE %s
                 AND LOWER(name) LIKE %s
                 AND favorite_count > 0""",
            (f"%{keyword}%", f"%{w}%")
        )
        wc, wfav = cur.fetchone()
        wc = int(wc or 0)
        wfav = float(wfav or 0)

        # Stricter: word must appear WITH keyword in 3+ items
        if wc and 3 <= wc <= 100 and wfav > 1000:
            next_words.append({
                "word": w,
                "count": wc,
                "avg_favs": int(wfav),
                "score": int(wfav / (1 + wc ** 0.5)),
            })
    next_words.sort(key=lambda x: x["score"], reverse=True)

    return {
        "keyword": keyword,
        "saturation": saturation,
        "median_age_days": int(median_age),
        "avg_acceleration": round(avg_accel, 2),
        "trajectory": trajectory,
        "verdict": verdict,
        "next_words": next_words[:8],
    }


def format_oracle_forecast(f):
    if not f:
        return "❌ Not enough data."
    lines = [
        f"# 🔮 ORACLE — `{f['keyword']}`",
        "",
        f"## {f['trajectory']}",
        f"**Verdict:** {f['verdict']}",
        f"**Saturation:** {f['saturation']} items",
        f"**Median age:** {f['median_age_days']} days",
        f"**Acceleration:** {f['avg_acceleration']}x",
        "",
    ]
    if f["next_words"]:
        lines.append("## 🎯 THE NEXT WAVE\n")
        for i, w in enumerate(f["next_words"], 1):
            lines.append(
                f"{i}. **`{w['word']}`** — only **{w['count']}** items · "
                f"avg **{w['avg_favs']:,}** favs · score **{w['score']:,}**"
            )
    return "\n".join(lines)


def find_next_wave_opportunities(cur, top_n=10):
    from momentum import find_momentum_keywords
    momentum = find_momentum_keywords(cur, days=7, min_items=2, top_n=15)
    if not momentum:
        return []

    all_next = defaultdict(lambda: {"score": 0, "from": [], "avg_favs": 0, "count": 999})
    for m in momentum[:10]:
        try:
            f = forecast_trend(cur, m["word"])
        except Exception:
            continue
        if not f or f["verdict"] == "EXIT":
            continue
        for nw in f["next_words"]:
            e = all_next[nw["word"]]
            e["score"] += nw["score"]
            e["from"].append(m["word"])
            e["avg_favs"] = max(e["avg_favs"], nw["avg_favs"])
            e["count"] = min(e["count"], nw["count"])

    ranked = [
        {"word": w, "combined_score": e["score"], "avg_favs": e["avg_favs"],
         "count": e["count"], "rides_on": e["from"][:3]}
        for w, e in all_next.items()
    ]
    ranked.sort(key=lambda x: x["combined_score"], reverse=True)
    return ranked[:top_n]


def format_next_wave(ranked):
    if not ranked:
        return "# 🌊 NEXT WAVE\n\n_No next-wave opportunities yet._"
    lines = [
        "# 🌊 NEXT WAVE OPPORTUNITIES",
        "",
        "_Keywords that will ride CURRENT momentum into the future._\n",
    ]
    for i, r in enumerate(ranked, 1):
        rides = ", ".join(f"`{x}`" for x in r["rides_on"])
        lines.append(
            f"**{i}. `{r['word']}`** — score **{r['combined_score']:,}**\n"
            f"   · Only **{r['count']}** items · avg **{r['avg_favs']:,}** favs\n"
            f"   · Rides on: {rides}\n"
        )
    return "\n".join(lines)
