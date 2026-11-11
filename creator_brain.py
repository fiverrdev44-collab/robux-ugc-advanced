"""creator_brain.py — systematic review of notable UGC creators.

Observational, not mystical: it studies the creators who already have a
track record in the database, measures what their items have in common,
and stores the findings so the rest of the bot can use them.

It does not scrape private data and it does not claim to know Roblox's
ranking weights. It reports what the cohort demonstrably does.
"""
import json
import re
from collections import Counter, defaultdict

from creator_identity import has_creator_type

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
    n = len(vals)
    if n == 0:
        return 0
    if n % 2:
        return vals[n // 2]
    return (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def build_cohort(cur, min_items=5, top_n=50, verified_only=False,
                 has_type=None):
    """Typed creators with a real track record, ranked by median favorites.

    Identity is ``(creator_type, creator_id)``. Unresolved historical rows are
    excluded rather than merged by display name or guessed as User.
    """
    if has_type is None:
        has_type = has_creator_type(cur)
    if not has_type:
        return []
    verified_clause = " AND i.creator_verified IS TRUE" if verified_only else ""
    cur.execute(f"""
        SELECT i.creator_type, i.creator_id,
               max(i.creator_name) AS display_name,
               count(*) AS n,
               percentile_cont(0.5) WITHIN GROUP (
                   ORDER BY i.favorite_count) AS med,
               max(i.favorite_count) AS top
        FROM items i
        WHERE i.creator_id IS NOT NULL
          AND i.creator_type IN ('User', 'Group')
          AND i.favorite_count > 0
          {verified_clause}
        GROUP BY i.creator_type, i.creator_id
        HAVING count(*) >= %s
        ORDER BY med DESC NULLS LAST
        LIMIT %s
    """, (min_items, top_n))
    return cur.fetchall()


def build_comparison_cohorts(cur, min_items=3, has_type=None):
    """Representative typed-creator segments, including nonverified/average.

    Not a success-only cohort: established vs emerging, verified vs
    nonverified, and top/average/underperformers by median favorites.
    Segments can overlap (e.g. a verified established creator).
    """
    if has_type is None:
        has_type = has_creator_type(cur)
    if not has_type:
        return None
    cur.execute("""
        SELECT i.creator_type, i.creator_id,
               max(i.creator_name) AS display_name,
               count(*) AS n,
               percentile_cont(0.5) WITHIN GROUP (
                   ORDER BY i.favorite_count) AS med,
               bool_or(coalesce(i.creator_verified, false)) AS verified
        FROM items i
        WHERE i.creator_id IS NOT NULL
          AND i.creator_type IN ('User', 'Group')
          AND i.favorite_count IS NOT NULL
        GROUP BY i.creator_type, i.creator_id
        HAVING count(*) >= %s
    """, (min_items,))
    rows = [(r[0], r[1], r[2], int(r[3] or 0), float(r[4] or 0), bool(r[5]))
            for r in (cur.fetchall() or [])]
    if not rows:
        return None

    ordered = sorted(rows, key=lambda r: r[4])
    n = len(ordered)
    if n < 3:
        bottom, middle, top = [], ordered, []
    else:
        third = max(1, n // 3)
        bottom = ordered[:third]
        top = ordered[-third:]
        middle = ordered[third:n - third]

    segments = {
        "established": [r for r in rows if r[3] >= 5],
        "emerging": [r for r in rows if r[3] < 5],
        "verified": [r for r in rows if r[5]],
        "nonverified": [r for r in rows if not r[5]],
        "top_performers": top,
        "average_performers": middle,
        "underperformers": bottom,
    }

    def summarize(rs):
        return {"creators": len(rs), "items": sum(r[3] for r in rs),
                "median_of_medians": round(_median([r[4] for r in rs]), 1)
                if rs else 0}

    return {
        "creators": n,
        "segments": {k: summarize(v) for k, v in segments.items()},
        "sampled_creators": {
            k: [r[2] for r in sorted(v, key=lambda x: -x[4])[:5]]
            for k, v in segments.items() if v},
        "sampled_identities": {
            k: [{"creator_type": r[0], "creator_id": r[1],
                 "display_name": r[2]}
                for r in sorted(v, key=lambda x: -x[4])[:5]]
            for k, v in segments.items() if v},
        "selection": {
            "population": (f"typed creators with >= {min_items} items and "
                           "non-null favorites"),
            "identity_key": "(creator_type, creator_id)",
            "unresolved": ("items with missing/unknown creator_type are "
                           "excluded from identity-specific segments"),
            "segments": ("established/emerging by item count; verified by "
                         "badge; top/average/underperformer by median-favorite "
                         "terciles"),
            "representative": False,
        },
    }


def identity_coverage(cur, min_favorites=0):
    """Count typed vs unresolved creator identities for disclosure."""
    try:
        cur.execute("""
            SELECT count(*) FILTER (WHERE creator_id IS NULL) AS missing_id,
                   count(*) FILTER (
                       WHERE creator_id IS NOT NULL
                         AND creator_type IN ('User', 'Group')) AS typed,
                   count(*) FILTER (
                       WHERE creator_id IS NOT NULL
                         AND (creator_type IS NULL
                              OR creator_type NOT IN ('User', 'Group')))
                       AS unresolved_type,
                   count(*) AS total
            FROM items
            WHERE favorite_count > %s
        """, (min_favorites,))
        row = cur.fetchone()
    except Exception:
        return None
    if not row:
        return None
    missing, typed, unresolved_type, total = (
        int(row[0] or 0), int(row[1] or 0), int(row[2] or 0), int(row[3] or 0))
    unresolved = missing + unresolved_type
    return {
        "total_items": total,
        "typed_items": typed,
        "unresolved_items": unresolved,
        "missing_creator_id": missing,
        "unresolved_creator_type": unresolved_type,
        "typed_coverage_pct": round(
            100.0 * typed / max(total, 1), 1),
    }


def learn(cur, min_items=5, top_n=50, verified_only=False, has_type=None):
    """Measure typed creator cohorts and return a findings dict."""
    if has_type is None:
        has_type = has_creator_type(cur)
    cohort = build_cohort(cur, min_items, top_n, verified_only=verified_only,
                          has_type=has_type)
    if not cohort:
        return None

    creator_types = [c[0] for c in cohort]
    creator_ids = [c[1] for c in cohort]
    verified_clause = " AND i.creator_verified IS TRUE" if verified_only else ""
    cur.execute(f"""
        SELECT lower(i.name), i.favorite_count, COALESCE(i.price, 0),
               EXTRACT(EPOCH FROM (NOW() - i.created_at)) / 86400.0 AS age_days
        FROM items i
        WHERE (i.creator_type, i.creator_id) IN (
            SELECT * FROM unnest(%s::text[], %s::bigint[])
        )
          AND i.favorite_count > 0
          AND i.created_at IS NOT NULL
          {verified_clause}
    """, (creator_types, creator_ids))
    rows = cur.fetchall()
    if not rows:
        return None

    titles = [r[0] or "" for r in rows]
    favs = [int(r[1] or 0) for r in rows]
    prices = [int(r[2] or 0) for r in rows if (r[2] or 0) > 0]
    ages = [float(r[3] or 0) for r in rows]

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

    try:
        comparison = build_comparison_cohorts(cur, has_type=has_type)
    except Exception:
        comparison = None
    coverage = identity_coverage(cur)

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
        "comparison": comparison,
        "comparison_selection": (comparison.get("selection")
                                 if comparison else None),
        "identity_coverage": coverage,
        "cohort_label": ("verified_only_success_cohort" if verified_only
                         else "success_top_median_favorites"),
        "cohort_mode": "success_top_median_favorites",
        "cohort_is_representative": False,
        "cohort_selection": (
            "verified typed creators with >= min_items items, ranked by "
            "median favorites, top_n; not representative"
            if verified_only else
            "all typed creators with >= min_items items, ranked by median "
            "favorites, top_n; success/survivorship-biased, not representative"),
        "causal": False,
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
        "cohort_label": findings.get("cohort_label",
                                     "success_top_median_favorites"),
        "cohort_is_representative": "false",
        "cohort_selection": findings.get("cohort_selection", ""),
        "comparison_selection": (
            json.dumps(findings.get("comparison_selection"))
            if findings.get("comparison_selection") else ""),
        "comparison": (json.dumps(findings.get("comparison"))
                       if findings.get("comparison") else ""),
        "identity_coverage": (
            json.dumps(findings.get("identity_coverage"))
            if findings.get("identity_coverage") else ""),
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
                    out.append((bits[0], int(bits[1]), float(bits[2])))
                except ValueError:
                    pass
        return out

    def _json(key):
        raw = stored.get(key, ("", None))[0]
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    return {
        "cohort_size": int(stored["cohort_size"][0]),
        "items": int(stored["items"][0]),
        "median_title_words": float(stored["median_title_words"][0]),
        "emoji_rate": float(stored["emoji_rate"][0]),
        "median_price": float(stored["median_price"][0]),
        "median_favs": float(stored["median_favs"][0]),
        "cadence_per_week": float(stored["cadence_per_week"][0]),
        "top_words": _pairs("top_words"),
        "top_bigrams": _pairs("top_bigrams"),
        "comparison": _json("comparison"),
        "comparison_selection": _json("comparison_selection"),
        "identity_coverage": _json("identity_coverage"),
        "cohort_label": stored.get(
            "cohort_label", ("success_top_median_favorites", None))[0],
        "cohort_mode": "success_top_median_favorites",
        "cohort_is_representative": False,
        "cohort_selection": stored.get("cohort_selection", ("", None))[0],
        "causal": False,
        "updated_at": stored["cohort_size"][1],
    }


def format_report(f):
    if not f:
        return None
    lines = [
        "# 🧠 CREATOR BRAIN — systematic review",
        f"_Primary **success cohort** (top median favorites): "
        f"**{f['cohort_size']}** creators · **{f['items']:,}** items · "
        f"median **{f['median_favs']:,}♥** per item_",
        "_This success cohort is not representative of all creators._",
        "",
        f"• Median title: **{f['median_title_words']} words** · "
        f"emoji in **{f['emoji_rate']}%** of items",
        f"• Median price: **R${f['median_price']}**",
        f"• Launch cadence: **{f['cadence_per_week']} items/week** per creator",
    ]
    comp = f.get("comparison")
    if comp and comp.get("segments"):
        s = comp["segments"]
        lines.append(
            f"• Comparison segments (broader convenience sample, **not "
            f"probability-representative**): established "
            f"{s['established']['creators']} · emerging "
            f"{s['emerging']['creators']} · verified "
            f"{s['verified']['creators']} · nonverified "
            f"{s['nonverified']['creators']} · top/mid/low "
            f"{s['top_performers']['creators']}/"
            f"{s['average_performers']['creators']}/"
            f"{s['underperformers']['creators']} creators")
    else:
        lines.append(
            "_Comparison summary unavailable in this cached study; do not "
            "read the success cohort as representative._")
    coverage = f.get("identity_coverage")
    if coverage:
        lines.append(
            f"• Typed creator identity coverage: "
            f"**{coverage.get('typed_coverage_pct', 0)}%** "
            f"({coverage.get('typed_items', 0):,}/"
            f"{coverage.get('total_items', 0):,} items); "
            f"**{coverage.get('unresolved_items', 0):,}** unresolved items "
            "were excluded from identity-specific comparisons.")
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
    lines.append(
        "_Observational associations, not causal effects. The success cohort "
        "is not a controlled or representative sample; comparison segments "
        "are a broader convenience sample, not probability-representative._"
    )
    return "\n".join(lines)
