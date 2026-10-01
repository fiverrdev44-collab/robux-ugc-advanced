"""
winner_analysis.py — Diff top 10% winners vs bottom 50% losers.
"""
import re
from collections import Counter

TOKEN_RE = re.compile(r"[a-z0-9]+")
STOP = {"the","a","an","of","and","or","for","to","in","on","with","my","your"}


def _tokens(text):
    return [t for t in TOKEN_RE.findall((text or "").lower())
            if len(t) >= 3 and t not in STOP]


def analyze_winners(cur, terms, top_n=40, min_favs=50):
    if not terms:
        return {}
    patterns = [f"%{t}%" for t in terms if len(t) >= 3]
    if not patterns:
        return {}

    cur.execute("""
        SELECT id, LOWER(name), COALESCE(LOWER(description), ''),
               favorite_count, price, creator_name, asset_type_id,
               EXTRACT(EPOCH FROM (NOW() - created_at))/86400 AS age_days
        FROM items WHERE favorite_count > %s
          AND (LOWER(name) LIKE ANY(%s) OR LOWER(description) LIKE ANY(%s))
        LIMIT 3000
    """, (min_favs, patterns, patterns))
    rows = cur.fetchall()
    if len(rows) < 10:
        return {"error": "not enough data"}

    rows_sorted = sorted(rows, key=lambda r: r[3] or 0, reverse=True)
    total = len(rows_sorted)
    winner_cutoff = max(1, total // 10)
    loser_start = total - max(1, total // 2)
    winners = rows_sorted[:winner_cutoff]
    losers = rows_sorted[loser_start:]

    def _stats(group):
        if not group: return {}
        favs = [r[3] or 0 for r in group]
        prices = [r[4] for r in group if r[4] and 5 <= r[4] <= 10000]
        name_lens = [len(_tokens(r[1])) for r in group]
        creators = Counter(r[5] for r in group if r[5])
        ages = [r[7] for r in group if r[7] is not None]
        return {
            "count": len(group),
            "median_favs": sorted(favs)[len(favs)//2] if favs else 0,
            "median_price": sorted(prices)[len(prices)//2] if prices else 0,
            "median_name_words": sorted(name_lens)[len(name_lens)//2] if name_lens else 0,
            "top_creator_share": creators.most_common(1)[0][1]/len(group) if creators else 0,
            "median_age_days": sorted(ages)[len(ages)//2] if ages else 0,
        }

    w_stats = _stats(winners)
    l_stats = _stats(losers)

    win_words = Counter()
    lose_words = Counter()
    for r in winners: win_words.update(set(_tokens(r[1])))
    for r in losers:  lose_words.update(set(_tokens(r[1])))

    winner_sig = []
    for w, c in win_words.most_common(30):
        lc = lose_words.get(w, 0)
        if c >= 3 and c > lc * 1.5:
            winner_sig.append({"word": w, "winners": c, "losers": lc,
                               "lift": round(c/max(lc,1),2)})

    loser_sig = []
    for w, c in lose_words.most_common(30):
        wc = win_words.get(w, 0)
        if c >= 5 and c > wc * 2:
            loser_sig.append({"word": w, "winners": wc, "losers": c})

    top_5 = [{"id": r[0], "name": r[1], "favs": r[3] or 0,
              "price": r[4], "creator": r[5], "type": r[6]} for r in winners[:5]]

    bigrams = Counter()
    for r in winners:
        toks = _tokens(r[1])
        for a, b in zip(toks, toks[1:]):
            bigrams[f"{a} {b}"] += 1
    winner_bigrams = [b for b, c in bigrams.most_common(10) if c >= 2]

    return {
        "total_items": total,
        "winner_stats": w_stats,
        "loser_stats": l_stats,
        "winner_signature_words": winner_sig[:15],
        "loser_signature_words": loser_sig[:10],
        "winner_bigrams": winner_bigrams,
        "top_5_winners": top_5,
    }


def format_winner_blueprint(w):
    if not w or w.get("error"):
        return "(winner analysis unavailable)"
    lines = ["=== WINNER vs LOSER ANALYSIS ===",
             f"Niche sample: {w['total_items']} items", ""]
    ws = w.get("winner_stats", {})
    ls = w.get("loser_stats", {})

    lines.append("WINNERS (top 10%):")
    lines.append(f"- Median favs: {ws.get('median_favs',0):,}")
    lines.append(f"- Median price: R${ws.get('median_price',0)}")
    lines.append(f"- Median title words: {ws.get('median_name_words',0)}")
    lines.append(f"- Top creator dominance: {ws.get('top_creator_share',0)*100:.1f}%")
    lines.append("")

    lines.append("LOSERS (bottom 50%):")
    lines.append(f"- Median favs: {ls.get('median_favs',0):,}")
    lines.append(f"- Median price: R${ls.get('median_price',0)}")
    lines.append(f"- Median title words: {ls.get('median_name_words',0)}")
    lines.append("")

    if w.get("winner_signature_words"):
        lines.append("WORDS WINNERS USE MORE (copy these):")
        for s in w["winner_signature_words"][:10]:
            lines.append(f"- '{s['word']}' — winners:{s['winners']} vs losers:{s['losers']} ({s['lift']}x)")
        lines.append("")

    if w.get("loser_signature_words"):
        lines.append("WORDS LOSERS USE MORE (avoid):")
        for s in w["loser_signature_words"][:8]:
            lines.append(f"- '{s['word']}' — losers:{s['losers']} vs winners:{s['winners']}")
        lines.append("")

    if w.get("winner_bigrams"):
        lines.append("WINNING BIGRAMS:")
        lines.append(", ".join(f"'{b}'" for b in w["winner_bigrams"]))
        lines.append("")

    if w.get("top_5_winners"):
        lines.append("STUDY THESE TOP 5:")
        for t in w["top_5_winners"]:
            lines.append(f"- {t['name'][:60]} | {t['favs']:,} favs | R${t['price']}")
        lines.append("")

    return "\n".join(lines)
