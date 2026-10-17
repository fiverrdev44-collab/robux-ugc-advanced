"""
momentum.py — Trend velocity engine. Finds keywords accelerating before peak.
"""
import re
from collections import defaultdict
from datetime import timedelta

TOKEN_RE = re.compile(r"[a-z]{3,}")
STOP = {"the","a","an","of","and","or","for","to","in","on","with","my","your",
        "is","it","as","at","by","from","new","old","roblox","ugc","free","item"}


def _tokens(text):
    return [t for t in TOKEN_RE.findall((text or "").lower()) if t not in STOP]


def find_momentum_keywords(cur, days=7, min_items=3, top_n=50):
    cur.execute(f"""
        SELECT i.id, LOWER(i.name), h.favorite_count, h.snapshot_at
        FROM item_history h JOIN items i ON i.id = h.item_id
        WHERE h.snapshot_at > NOW() - INTERVAL '{days * 3} days'
          AND h.favorite_count > 0
        ORDER BY h.item_id, h.snapshot_at
    """)
    rows = cur.fetchall()
    if not rows: return []

    item_snaps = defaultdict(list)
    for iid, name, favs, snap in rows:
        item_snaps[iid].append((snap, favs, name))

    now = max(r[3] for r in rows)
    cutoff = now - timedelta(days=days)

    v_now = defaultdict(float); v_prev = defaultdict(float)
    items_now = defaultdict(set); items_prev = defaultdict(set)

    for iid, snaps in item_snaps.items():
        snaps.sort()
        if len(snaps) < 2: continue
        name = snaps[0][2]
        words = set(_tokens(name))
        recent = [s for s in snaps if s[0] >= cutoff]
        older = [s for s in snaps if s[0] < cutoff]
        vn = ((recent[-1][1] - recent[0][1]) / max(1, (recent[-1][0]-recent[0][0]).days)) if len(recent) >= 2 else 0
        vp = ((older[-1][1] - older[0][1]) / max(1, (older[-1][0]-older[0][0]).days)) if len(older) >= 2 else 0
        for w in words:
            if vn > 0: v_now[w] += vn; items_now[w].add(iid)
            if vp > 0: v_prev[w] += vp; items_prev[w].add(iid)

    scored = []
    for w, vn in v_now.items():
        if len(items_now[w]) < min_items: continue
        vp = v_prev.get(w, 0)
        ratio = (vn/vp) if vp > 0 else (999.0 if vn > 0 else 0)
        scored.append({"word": w, "velocity_now": round(vn,1),
                       "velocity_prev": round(vp,1),
                       "momentum_ratio": round(ratio,2),
                       "item_count": len(items_now[w])})

    scored.sort(key=lambda x: x["velocity_now"] * min(x["momentum_ratio"], 10),
                reverse=True)
    return scored[:top_n]


def format_momentum_report(keywords, title="🚀 TREND MOMENTUM"):
    if not keywords:
        return f"# {title}\n\n_No momentum data yet. Run the snapshot job more._"
    lines = [f"# {title}", "", "_Keywords accelerating RIGHT NOW._\n"]
    for i, k in enumerate(keywords[:20], 1):
        d = "🚀" if k["momentum_ratio"] > 2 else "📈" if k["momentum_ratio"] > 1.2 else "➡️"
        lines.append(f"{i}. {d} **`{k['word']}`** — velocity **{k['velocity_now']:.0f}** favs/day · "
                     f"momentum **{k['momentum_ratio']:.1f}x** · {k['item_count']} items")
    return "\n".join(lines)
