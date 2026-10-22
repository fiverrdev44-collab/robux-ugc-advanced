"""creator_brain.py — systematic review of notable UGC creators.

Observational, not mystical: it studies the creators who already have a
track record in the database, measures what their items have in common,
and stores the findings so the rest of the bot can use them.

It does not scrape private data and it does not claim to know Roblox's
ranking weights. It reports what the cohort demonstrably does.
"""
import re
from collections import Counter, defaultdict

STOP = {
    "the", "and", "for", "with", "your", "you", "this", "that", "from",
    "roblox", "ugc", "item", "items", "new", "best", "cute", "hot",
    "sale", "free", "limited", "rare", "code", "buy", "shop", "store",
}


def _tokens(text):
    return [w for w in re.findall(r"[a-z]{3,}", (text or "").lower())
            if w not in STOP]


def _median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return 0
    return vals[len(vals) // 2]


def build_cohort(cur, min_items=5, top_n=50, verified_only=False):
    """Creators with a real track record, ranked by median favorites."""
    verified_clause = " AND creator_verified IS TRUE" if verified_only else ""
    cur.execute(f"""
        SELECT lower(creator_name),
               count(*) AS n,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY favorite_count) AS med,
               max(favorite_count) AS top
        FROM items
        WHERE creator_name IS NOT NULL AND creator_name <> ''
          AND favorite_count > 0
          {verified_clause}
        GROUP BY 1
        HAVING count(*) >= %s
        ORDER BY med DESC NULLS LAST
        LIMIT %s
    """, (min_items, top_n))
    return cur.fetchall()


def learn(cur, min_items=5, top_n=50, verified_only=False):
    """Measure the cohort and return a findings dict."""
    cohort = build_cohort(cur, min_items, top_n, verified_only=verified_only)
    if not cohort:
        return None

    names = [c[0] for c in cohort]
    verified_clause = " AND creator_verified IS TRUE" if verified_only else ""
    cur.execute(f"""
        SELECT lower(creator_name), lower(name), favorite_count,
               COALESCE(price, 0),
               EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400.0 AS age_days
        FROM items
        WHERE lower(creator_name) = ANY(%s)
          AND favorite_count > 0
          AND created_at IS NOT NULL
          {verified_clause}
    """, (names,))
    rows = cur.fetchall()
    if not rows:
        return None

    titles = [r[1] or "" for r in rows]
    favs = [int(r[2] or 0) for r in rows]
    prices = [int(r[3] or 0) for r in rows if (r[3] or 0) > 0]
    ages = [float(r[4] or 0) for r in rows]

    word_items = defaultdict(list)      # word -> list of favs
    bigram_items = defaultdict(list)
    emoji_titles = 0
    for title, f in zip(titles, favs):
        if any(ord(ch) > 0x2000 for ch in title):
            emoji_titles += 1
        toks = _tokens(title)
        for w in set(toks):
            word_items[w].append(f)
        for a, b in set(zip(toks, toks[1:])):
            bigram_items[f"{a} {b}"].append(f)

    top_words = sorted(
        ((w, len(v), _median(v)) for w, v in word_items.items() if len(v) >= 3),
        key=lambda x: (-x[2], -x[1]),
    )[:20]
    top_bigrams = sorted(
        ((b, len(v), _median(v)) for b, v in bigram_items.items() if len(v) >= 3),
        key=lambda x: (-x[2], -x[1]),
    )[:10]

    span_weeks = max(max(ages, default=0) - min(ages, default=0), 1) / 7
    cadence = len(rows) / max(len(cohort) * span_weeks, 1)

    return {
        "cohort_size": len(cohort),
        "items": len(rows),
        "median_title_words": _median(len(_tokens(t)) for t in titles),
        "emoji_rate": round(100 * emoji_titles / len(rows), 1),
        "median_price": _median(prices),
        "median_favs": _median(favs),
        "cadence_per_week": round(cadence, 2),
        "top_words": top_words,
        "top_bigrams": top_bigrams,
    }


def save(cur, findings):
    if not findings:
        return
    rows = {
        "cohort_size": findings["cohort_size"],
        "items": findings["items"],
        "median_title_words": findings["median_title_words"],
        "emoji_rate": findings["emoji_rate"],
        "median_price": findings["median_price"],
        "median_favs": findings["median_favs"],
        "cadence_per_week": findings["cadence_per_week"],
        "top_words": " | ".join(f"{w}:{n}:{m}" for w, n, m in findings["top_words"]),
        "top_bigrams": " | ".join(f"{b}:{n}:{m}" for b, n, m in findings["top_bigrams"]),
    }
    for k, v in rows.items():
        cur.execute("""
            INSERT INTO creator_patterns (pattern_key, pattern_value, updated_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (pattern_key) DO UPDATE SET
                pattern_value = EXCLUDED.pattern_value,
                updated_at = CURRENT_TIMESTAMP
        """, (k, str(v)))


def load(cur):
    cur.execute("SELECT pattern_key, pattern_value, updated_at FROM creator_patterns")
    return {k: (v, ts) for k, v, ts in cur.fetchall()}


def load_findings(cur):
    """Rebuild a findings dict from the stored rows (for cached display)."""
    stored = load(cur)
    if "cohort_size" not in stored:
        return None

    def _pairs(key):
        out = []
        for part in stored.get(key, ("", None))[0].split(" | "):
            bits = part.split(":")
            if len(bits) == 3:
                try:
                    out.append((bits[0], int(bits[1]), int(bits[2])))
                except ValueError:
                    pass
        return out

    return {
        "cohort_size": int(stored["cohort_size"][0]),
        "items": int(stored["items"][0]),
        "median_title_words": int(stored["median_title_words"][0]),
        "emoji_rate": float(stored["emoji_rate"][0]),
        "median_price": int(stored["median_price"][0]),
        "median_favs": int(stored["median_favs"][0]),
        "cadence_per_week": float(stored["cadence_per_week"][0]),
        "top_words": _pairs("top_words"),
        "top_bigrams": _pairs("top_bigrams"),
        "updated_at": stored["cohort_size"][1],
    }


def format_report(f):
    if not f:
        return None
    lines = [
        "# 🧠 CREATOR BRAIN — systematic review",
        f"_Cohort: **{f['cohort_size']}** creators · **{f['items']:,}** items · "
        f"median **{f['median_favs']:,}♥** per item_",
        "",
        f"• Median title: **{f['median_title_words']} words** · "
        f"emoji in **{f['emoji_rate']}%** of items",
        f"• Median price: **R${f['median_price']}**",
        f"• Launch cadence: **{f['cadence_per_week']} items/week** per creator",
    ]
    if f["top_words"]:
        lines.append("\n**Words in their winners:**")
        for w, n, med in f["top_words"][:10]:
            lines.append(f"• `{w}` — {n} items · median {med:,}♥")
    if f["top_bigrams"]:
        lines.append("\n**Winning pairs:**")
        for b, n, med in f["top_bigrams"][:6]:
            lines.append(f"• `{b}` — {n} items · median {med:,}♥")
    if f.get("updated_at"):
        lines.append(f"\n_Last studied: {f['updated_at']} UTC_")
    lines.append(
        "\n_Reading: their titles are the control group. Copy the shape "
        "(length, one aesthetic word, type word last), not the exact words._"
    )
    return "\n".join(lines)
