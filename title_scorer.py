"""
title_scorer.py — statistical title scoring from real DB data.

FIXES in this version:
  - _words() now deduplicates tokens. Previously "Sway hip sway dance"
    counted sway's lift twice, inflating scores.
  - score_titles_batch reuses ONE DB connection (no pool exhaustion).
"""
import re
import math
from collections import Counter, defaultdict
from bot_core import get_db
from convergence_engine import FAMILIES


STOPWORDS = {"a", "an", "the", "of", "and", "or", "for", "to", "in", "on",
             "with", "my", "your", "at", "by", "is", "it", "as"}

MIN_SAMPLE = 5
CONFIDENCE_CAP = 30
CAT_MED_FLOOR = 25.0
LIFT_MIN = 0.1
LIFT_MAX = 5.0
BIGRAM_MAX = 5.0
VISIBILITY_WEIGHT = 0.4
VISIBILITY_CAP = 25.0


def _words(title):
    """Deduplicated, lowercase, stopword-filtered token list."""
    seen = set()
    out = []
    for w in re.findall(r"[a-z]{3,}", (title or "").lower()):
        if w in STOPWORDS or w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _cat_median(cur, family):
    if not family:
        return CAT_MED_FLOOR
    try:
        from category_configs import to_convergence_family
        fam = to_convergence_family(family)
    except Exception:
        fam = family
    ids = FAMILIES.get(fam)
    if not ids:
        return CAT_MED_FLOOR
    ph = ",".join(["%s"] * len(ids))
    cur.execute(f"""
        select percentile_cont(0.5) within group (order by favorite_count)
        from items
        where asset_type_id in ({ph}) and favorite_count > 5
    """, ids)
    r = cur.fetchone()
    val = float(r[0] or 0)
    if val < CAT_MED_FLOOR:
        return CAT_MED_FLOOR
    return val


def _fam_clause(family):
    if not family:
        return "", []
    try:
        from category_configs import to_convergence_family
        fam = to_convergence_family(family)
    except Exception:
        fam = family
    ids = FAMILIES.get(fam)
    if not ids:
        return "", []
    ph = ",".join(["%s"] * len(ids))
    return f" and asset_type_id in ({ph})", list(ids)


def compute_word_stats(cur, family=None):
    """Reuses caller's cursor — must be passed in."""
    cat_med = _cat_median(cur, family)
    fam_sql, fam_params = _fam_clause(family)

    cur.execute(f"""
        select name, favorite_count,
               (created_at > now() - interval '90 days') as is_recent
        from items
        where favorite_count > 5 {fam_sql}
    """, fam_params)
    rows = cur.fetchall()

    all_buckets = defaultdict(list)
    recent_buckets = defaultdict(list)
    total_recent = 0

    for name, favs, is_recent in rows:
        for w in set(_words(name)):
            all_buckets[w].append(favs or 0)
            if is_recent:
                recent_buckets[w].append(favs or 0)
        if is_recent:
            total_recent += 1

    out = {}
    for w, favs in all_buckets.items():
        if len(favs) < MIN_SAMPLE:
            continue
        favs.sort()
        med = favs[len(favs) // 2]
        lift = _clamp(med / cat_med, LIFT_MIN, LIFT_MAX)

        recent_share = (len(recent_buckets[w]) / max(total_recent, 1))
        overall_share = (len(favs) / max(len(rows), 1))
        freshness = recent_share / max(overall_share, 0.001)
        freshness = min(freshness, 3.0)

        out[w] = {
            "lift": round(lift, 2),
            "count": len(favs),
            "median_favs": med,
            "freshness": round(freshness, 2),
        }
    return out


def compute_search_demand(cur, words):
    if not words:
        return {}
    patterns = [rf"\y{re.escape(w)}\y" for w in words]
    cur.execute("""
        select suggestion from search_suggestions
        where suggestion ~* any(%s) limit 5000
    """, (patterns,))
    rows = cur.fetchall()

    demand = Counter()
    for (s,) in rows:
        sl = (s or "").lower()
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", sl):
                demand[w] += 1
    return dict(demand)


def _bigram_lift(cur, w1, w2, family):
    fam_sql, fam_params = _fam_clause(family)
    cur.execute(f"""
        select count(*),
               coalesce(percentile_cont(0.5) within group
                       (order by favorite_count), 0)
        from items
        where favorite_count > 5
          and lower(name) like %s
          and lower(name) like %s
          {fam_sql}
    """, [f"%{w1}%", f"%{w2}%"] + fam_params)
    cnt, med = cur.fetchone()
    if not cnt or cnt < 5:
        return 0.0
    raw = float(med or 0) / _cat_median(cur, family)
    return _clamp(raw, 0.0, BIGRAM_MAX)


def score_title(cur, title, family=None, word_stats=None, demand_map=None):
    """Score one title using caller's cursor. All DB access via `cur`."""
    words = _words(title)
    if not words:
        return {"title": title, "score": 0.0,
                "reasoning": "No words", "breakdown": []}

    if word_stats is None:
        word_stats = {}
    if demand_map is None:
        demand_map = compute_search_demand(cur, words)

    total = 0.0
    visibility_total = 0.0
    breakdown = []
    for w in words:
        st = word_stats.get(w, {})
        if not st:
            breakdown.append({
                "word": w, "lift": 1.0, "sample": 0,
                "demand": demand_map.get(w, 0), "freshness": 1.0,
                "contribution": 0.0, "visibility_gap": 0.0,
                "no_data": True,
            })
            continue

        lift = st.get("lift", 1.0)
        cnt = st.get("count", 0)
        fresh = st.get("freshness", 1.0)
        dem = demand_map.get(w, 0)

        dem_mult = 1 + math.log1p(dem) / 3.0
        conf = min(1.0, cnt / CONFIDENCE_CAP)
        fresh_mult = 1 + (fresh - 1) * 0.3

        contribution = lift * dem_mult * conf * fresh_mult
        total += contribution

        raw_gap = dem / (cnt + 1)
        visibility_gap = min(raw_gap, VISIBILITY_CAP)
        visibility_total += visibility_gap

        breakdown.append({
            "word": w, "lift": lift, "sample": cnt,
            "demand": dem, "freshness": fresh,
            "contribution": round(contribution, 2),
            "visibility_gap": round(visibility_gap, 2),
        })

    bigram_bonus = 0.0
    bigram_info = None
    if len(words) >= 2:
        for i, w1 in enumerate(words[:-1]):
            for w2 in words[i+1:]:
                bl = _bigram_lift(cur, w1, w2, family)
                if bl > 1.5:
                    bonus = bl * 0.6
                    if bonus > bigram_bonus:
                        bigram_bonus = bonus
                        bigram_info = f"{w1} {w2}"

    cur.execute("select count(*) from items where lower(name) = %s",
                (title.lower().strip(),))
    exact = cur.fetchone()[0] or 0

    unique_mult = 1.5 if exact == 0 else (1.0 if exact < 3 else 0.5)

    capped_visibility = min(visibility_total, VISIBILITY_CAP)
    combined = ((total + bigram_bonus) * unique_mult) + (capped_visibility * VISIBILITY_WEIGHT)

    return {
        "title": title,
        "score": round(combined, 2),
        "raw": round(total, 2),
        "bigram_bonus": round(bigram_bonus, 2),
        "bigram": bigram_info,
        "visibility_gap": round(capped_visibility, 2),
        "uniqueness_mult": unique_mult,
        "exact_matches": exact,
        "breakdown": breakdown,
    }


def score_titles_batch(titles, family=None):
    """ONE connection for the whole batch. Prevents pool exhaustion."""
    if not titles:
        return []
    conn = get_db(); cur = conn.cursor()
    try:
        word_stats = compute_word_stats(cur, family)
        all_words = set()
        for t in titles:
            all_words.update(_words(t))
        demand_map = compute_search_demand(cur, list(all_words))

        scored = [score_title(cur, t, family=family,
                              word_stats=word_stats,
                              demand_map=demand_map)
                  for t in titles]
    finally:
        cur.close(); conn.close()

    seen_keys = set()
    deduped = []
    for s in scored:
        key = tuple(sorted(_words(s["title"])))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(s)
    deduped.sort(key=lambda x: x["score"], reverse=True)
    return deduped


def format_report(s, show_all_words=False):
    gap_total = s.get("visibility_gap", 0)
    lines = [
        f"**`{s['title']}`** — score **{s['score']}**"
        + (f" · gap **{gap_total:.0f}**" if gap_total >= 5 else "")
        + (f" · unique" if s["exact_matches"] == 0
           else f" · {s['exact_matches']} exact")
    ]
    ranked = sorted(s["breakdown"], key=lambda x: x["contribution"], reverse=True)
    for b in ranked:
        if b.get("no_data"):
            lines.append(f"  ⚫ `{b['word']}` — no data ({b['demand']} searches) → +0.0")
            continue
        lift = b["lift"]
        if lift >= 2.5: emoji = "🟢"
        elif lift >= 1.5: emoji = "🔵"
        elif lift >= 1.0: emoji = "⚪"
        elif lift >= 0.5: emoji = "🟠"
        else: emoji = "🔴"
        gap = b.get("visibility_gap", 0)
        gap_str = f" · gap {gap:.0f}" if gap >= 5 else ""
        lines.append(
            f"  {emoji} `{b['word']}` lift {lift}× "
            f"({b['sample']} items · {b['demand']} searches{gap_str}) "
            f"→ +{b['contribution']}"
        )
    if s.get("bigram"):
        lines.append(f"  🎯 bigram `{s['bigram']}` → +{s['bigram_bonus']}")
    return "\n".join(lines)


def pick_champion(scored):
    if not scored:
        return None, None, None
    champion = scored[0]
    champ_first = _words(champion["title"])[0] if _words(champion["title"]) else ""
    backup = None
    for s in scored[1:]:
        ws = _words(s["title"])
        if ws and ws[0] != champ_first:
            backup = s
            break
    if backup is None and len(scored) > 1:
        backup = scored[1]
    wildcard = None
    for s in scored[2:]:
        ws = _words(s["title"])
        if ws and ws[0] != champ_first:
            wildcard = s
            break
    return champion, backup, wildcard
