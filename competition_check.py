"""
competition_check.py — Deep competition analysis for any phrase.
"""
import re

TOKEN_RE = re.compile(r"[a-z]{3,}")

CATEGORY_NAMES = {
    2: "T-Shirt", 8: "Hat", 11: "Shirt", 12: "Pants", 17: "Head",
    18: "Face", 19: "Gear", 41: "Hair", 42: "Face Acc", 43: "Neck Acc",
    44: "Shoulder Acc", 45: "Front Acc", 46: "Back Acc", 47: "Waist Acc",
    61: "Emote", 64: "3D T-Shirt", 65: "3D Shirt", 66: "3D Pants",
    67: "3D Jacket", 68: "3D Sweater", 69: "3D Shorts",
    70: "3D Shoe L", 71: "3D Shoe R", 72: "3D Dress",
}


def analyze_competition(cur, phrase):
    phrase_lower = phrase.lower().strip()
    tokens = [t for t in TOKEN_RE.findall(phrase_lower) if len(t) >= 2]
    if not tokens:
        return None

    cur.execute("""
        SELECT COUNT(*) FROM items
        WHERE LOWER(name) LIKE %s AND favorite_count > 5
    """, (f"%{phrase_lower}%",))
    exact_count = int(cur.fetchone()[0] or 0)

    tok_conditions = " AND ".join(["LOWER(name) LIKE %s"] * len(tokens))
    tok_patterns = [f"%{t}%" for t in tokens]
    cur.execute(f"""
        SELECT COUNT(*) FROM items
        WHERE {tok_conditions} AND favorite_count > 5
    """, tuple(tok_patterns))
    total_items = int(cur.fetchone()[0] or 0)

    cur.execute("""
        SELECT asset_type_id, COUNT(*) FROM items
        WHERE LOWER(name) LIKE %s AND favorite_count > 5
        GROUP BY asset_type_id
        ORDER BY COUNT(*) DESC
    """, (f"%{phrase_lower}%",))
    by_category = {}
    for atype, cnt in cur.fetchall():
        by_category[atype or 0] = int(cnt)

    cur.execute("""
        SELECT favorite_count FROM items
        WHERE LOWER(name) LIKE %s AND favorite_count > 5
        ORDER BY favorite_count
    """, (f"%{phrase_lower}%",))
    favs = [r[0] for r in cur.fetchall() if r[0]]
    if favs:
        fs = sorted(favs)
        n = len(fs)
        favs_dist = {
            "min": fs[0], "p25": fs[n // 4], "median": fs[n // 2],
            "p75": fs[(n * 3) // 4], "max": fs[-1],
        }
    else:
        favs_dist = {"min": 0, "p25": 0, "median": 0, "p75": 0, "max": 0}

    cur.execute("""
        SELECT id, name, favorite_count, price, creator_name, asset_type_id
        FROM items
        WHERE LOWER(name) LIKE %s AND favorite_count > 5
        ORDER BY favorite_count DESC LIMIT 5
    """, (f"%{phrase_lower}%",))
    top = []
    for r in cur.fetchall():
        top.append({
            "id": r[0], "name": r[1], "favs": r[2] or 0,
            "price": r[3] or 0, "creator": r[4],
            "asset_type_id": r[5] or 0,
        })

    if exact_count == 0:
        verdict = "🥇 FIRST MOVER — 0 items use this phrase"
        tier = "gold"
    elif exact_count < 5:
        verdict = f"🥈 UNTAPPED — only {exact_count} items"
        tier = "strong"
    elif exact_count < 20:
        verdict = f"🥉 NICHE — {exact_count} items (healthy)"
        tier = "viable"
    elif exact_count < 100:
        verdict = f"⚠️ COMPETITIVE — {exact_count} items"
        tier = "risky"
    else:
        verdict = f"❌ SATURATED — {exact_count} items"
        tier = "dead"

    gap_cats = []
    for cat_id in by_category.keys():
        if cat_id == 0:
            continue
        gap_cats.append({
            "asset_type_id": cat_id,
            "name": CATEGORY_NAMES.get(cat_id, f"Type {cat_id}"),
            "count": by_category[cat_id],
        })
    gap_cats.sort(key=lambda x: x["count"])

    return {
        "phrase": phrase,
        "tokens": tokens,
        "exact_count": exact_count,
        "total_items": total_items,
        "by_category": by_category,
        "favs_distribution": favs_dist,
        "top_competitors": top,
        "saturation_verdict": verdict,
        "saturation_tier": tier,
        "gap_categories": gap_cats,
    }


def format_competition_report(data):
    if not data:
        return "# 🔍 COMPETITION CHECK\n\n_No data._"

    lines = [f"# 🔍 COMPETITION: `{data['phrase']}`\n"]
    lines.append("## 📊 SNAPSHOT")
    lines.append(f"- **Exact phrase match:** {data['exact_count']:,} items")
    lines.append(f"- **Any token match:** {data['total_items']:,} items")
    lines.append(f"- **Verdict:** {data['saturation_verdict']}\n")

    if data["favs_distribution"]["median"] > 0:
        d = data["favs_distribution"]
        lines.append("## 📈 FAVOURITES DISTRIBUTION")
        lines.append(f"- min: **{d['min']:,}** · p25: **{d['p25']:,}** · "
                     f"median: **{d['median']:,}** · p75: **{d['p75']:,}** · "
                     f"max: **{d['max']:,}**\n")

    if data["by_category"]:
        lines.append("## 📁 BY CATEGORY")
        for atype, count in list(data["by_category"].items())[:8]:
            cat_name = CATEGORY_NAMES.get(atype, f"Type {atype}") if atype else "Unknown"
            lines.append(f"- **{cat_name}**: {count:,} items")
        lines.append("")

    if data["gap_categories"]:
        lines.append("## 🕳️ GAP OPPORTUNITY BY CATEGORY")
        for cat in data["gap_categories"][:5]:
            lines.append(f"- **{cat['name']}**: only {cat['count']} items")
        lines.append("")

    if data["top_competitors"]:
        lines.append("## 🥊 TOP COMPETITORS")
        for i, c in enumerate(data["top_competitors"], 1):
            cat = CATEGORY_NAMES.get(c["asset_type_id"], "Unknown")
            lines.append(
                f"**{i}. `{c['name'][:55]}`** — {c['favs']:,} favs · "
                f"R${c['price']} · {cat}"
            )
        lines.append("")

    return "\n".join(lines)
