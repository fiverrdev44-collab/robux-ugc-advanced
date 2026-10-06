"""
market_xray.py — One-shot market state snapshot across the entire UGC catalog.

Produces a single dashboard of the current Roblox UGC market using real data:
  - Catalog totals + coverage
  - Category breakdown
  - Hottest niches (top favs/day last 30 days)
  - Coldest niches (highest new-item supply, lowest demand)
  - Whitespace count (search terms with almost no items)
  - Cross-category arbitrage signals
  - Concentration extremes (monopolized vs fragmented)
  - Hidden gems (high favs/day, low competitors)

All pure SQL on data already in the DB. No predictions.
"""
import re
from collections import defaultdict

from category_configs import (
    CATEGORY_FAMILIES,
    ABSTRACT_ENGLISH_BLOCK,
    get_concept_vocab,
)


def _count_items(cur, asset_ids=None, min_favs=0):
    if asset_ids:
        cur.execute(
            "SELECT COUNT(*) FROM items WHERE favorite_count > %s AND asset_type_id = ANY(%s)",
            (int(min_favs), list(asset_ids))
        )
    else:
        cur.execute(
            "SELECT COUNT(*) FROM items WHERE favorite_count > %s",
            (int(min_favs),)
        )
    return cur.fetchone()[0] or 0


def catalog_health(cur):
    out = {}
    try:
        cur.execute("SELECT COUNT(*), COUNT(description), AVG(favorite_count), MAX(favorite_count) FROM items")
        r = cur.fetchone()
        out["total"] = int(r[0] or 0)
        out["with_desc"] = int(r[1] or 0)
        out["avg_favs"] = int(r[2] or 0)
        out["max_favs"] = int(r[3] or 0)
    except Exception as e:
        print(f"[xray] catalog_health: {e}", flush=True)
    try:
        cur.execute("SELECT COUNT(DISTINCT suggestion) FROM search_suggestions")
        out["search_terms"] = int(cur.fetchone()[0] or 0)
    except Exception:
        out["search_terms"] = 0
    try:
        cur.execute("SELECT COUNT(DISTINCT creator_name) FROM items WHERE creator_name IS NOT NULL AND creator_name <> ''")
        out["creators"] = int(cur.fetchone()[0] or 0)
    except Exception:
        out["creators"] = 0
    return out


def category_breakdown(cur):
    out = []
    for family, cfg in CATEGORY_FAMILIES.items():
        asset_ids = cfg.get("asset_type_ids") or []
        if not asset_ids:
            continue
        try:
            cur.execute("""
                SELECT COUNT(*),
                       COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY favorite_count), 0),
                       COUNT(*) FILTER (WHERE favorite_count > 1000)
                FROM items
                WHERE asset_type_id = ANY(%s)
            """, (list(asset_ids),))
            r = cur.fetchone()
            out.append({
                "family": family,
                "label": cfg.get("label", family),
                "count": int(r[0] or 0),
                "median_favs": int(r[1] or 0),
                "winners": int(r[2] or 0),
            })
        except Exception as e:
            print(f"[xray] category {family}: {e}", flush=True)
    out.sort(key=lambda c: -c["count"])
    return out


def hottest_niches(cur, days=30, limit=10):
    try:
        cur.execute("""
            SELECT LOWER(name), favorite_count,
                   EXTRACT(EPOCH FROM (NOW() - created_at))/86400 AS age_days
            FROM items
            WHERE created_at IS NOT NULL
              AND created_at >= NOW() - INTERVAL '%s days'
              AND favorite_count > 20
            LIMIT 3000
        """, (int(days),))
        rows = cur.fetchall()
    except Exception as e:
        print(f"[xray] hottest: {e}", flush=True)
        return []

    word_rates = defaultdict(lambda: {"total_rate": 0.0, "count": 0, "max_rate": 0.0})
    token_re = re.compile(r"[a-z]{4,}")

    for name, favs, age in rows:
        try:
            age_f = float(age or 0)
            if age_f <= 0.1:
                continue
            rate = (favs or 0) / age_f
        except Exception:
            continue
        seen = set()
        for w in token_re.findall((name or "").lower()):
            if w in seen or w in ABSTRACT_ENGLISH_BLOCK:
                continue
            seen.add(w)
            word_rates[w]["total_rate"] += rate
            word_rates[w]["count"] += 1
            word_rates[w]["max_rate"] = max(word_rates[w]["max_rate"], rate)

    results = []
    for w, s in word_rates.items():
        if s["count"] < 3:
            continue
        results.append({
            "word": w,
            "sample": s["count"],
            "avg_rate": round(s["total_rate"] / s["count"], 2),
            "max_rate": round(s["max_rate"], 2),
        })
    results.sort(key=lambda r: -r["avg_rate"])
    return results[:limit]


def coldest_niches(cur, weeks=4, limit=10):
    try:
        cur.execute("""
            SELECT LOWER(name), created_at
            FROM items
            WHERE created_at IS NOT NULL
              AND created_at >= NOW() - INTERVAL '%s weeks'
            LIMIT 5000
        """, (int(weeks),))
        rows = cur.fetchall()
    except Exception as e:
        print(f"[xray] coldest: {e}", flush=True)
        return []

    word_counts = defaultdict(int)
    token_re = re.compile(r"[a-z]{4,}")
    for name, _ in rows:
        seen = set()
        for w in token_re.findall((name or "").lower()):
            if w in seen or w in ABSTRACT_ENGLISH_BLOCK:
                continue
            seen.add(w)
            word_counts[w] += 1

    results = [{"word": w, "new_items": c} for w, c in word_counts.items() if c >= 5]
    results.sort(key=lambda r: -r["new_items"])
    return results[:limit]


def whitespace_count(cur, max_supply=3):
    try:
        cur.execute("""
            SELECT DISTINCT suggestion FROM search_suggestions
            WHERE LENGTH(suggestion) BETWEEN 4 AND 40
            LIMIT 3000
        """)
        suggestions = [r[0] for r in cur.fetchall() if r[0]]
    except Exception as e:
        print(f"[xray] whitespace fetch: {e}", flush=True)
        return {"total_terms": 0, "whitespace_terms": 0, "top": []}

    count = 0
    top = []
    for s in suggestions:
        s = (s or "").strip().lower()
        if not s:
            continue
        try:
            cur.execute(
                "SELECT COUNT(*) FROM items WHERE LOWER(name) LIKE %s AND favorite_count > 5",
                (f"%{s}%",)
            )
            supply = cur.fetchone()[0] or 0
        except Exception:
            continue
        if supply <= max_supply:
            count += 1
            if len(top) < 10:
                top.append({"term": s, "supply": supply})

    return {"total_terms": len(suggestions), "whitespace_terms": count, "top": top}


def arbitrage_signals(cur, limit=6):
    signals = []
    families = [(k, v) for k, v in CATEGORY_FAMILIES.items() if v.get("asset_type_ids")]
    for src_key, src_cfg in families:
        try:
            cur.execute("""
                SELECT LOWER(name), favorite_count FROM items
                WHERE asset_type_id = ANY(%s) AND favorite_count > 200
                LIMIT 3000
            """, (list(src_cfg["asset_type_ids"]),))
            rows = cur.fetchall()
        except Exception:
            continue
        word_favs = defaultdict(lambda: {"count": 0, "total": 0})
        token_re = re.compile(r"[a-z]{4,}")
        for name, favs in rows:
            for w in set(token_re.findall((name or "").lower())):
                if w in ABSTRACT_ENGLISH_BLOCK:
                    continue
                word_favs[w]["count"] += 1
                word_favs[w]["total"] += favs or 0
        for tgt_key, tgt_cfg in families:
            if tgt_key == src_key:
                continue
            tgt_vocab = get_concept_vocab(tgt_key)
            for w, s in word_favs.items():
                if s["count"] < 3:
                    continue
                if tgt_vocab and w not in tgt_vocab:
                    continue
                try:
                    cur.execute(
                        "SELECT COUNT(*) FROM items WHERE asset_type_id = ANY(%s) AND LOWER(name) LIKE %s",
                        (list(tgt_cfg["asset_type_ids"]), f"%{w}%")
                    )
                    tgt_supply = cur.fetchone()[0] or 0
                except Exception:
                    continue
                if tgt_supply > 3:
                    continue
                avg_favs = s["total"] / s["count"]
                signals.append({
                    "word": w,
                    "source": src_key,
                    "target": tgt_key,
                    "source_supply": s["count"],
                    "source_avg_favs": int(avg_favs),
                    "target_supply": tgt_supply,
                })
    signals.sort(key=lambda x: (-x["source_avg_favs"], x["target_supply"]))
    return signals[:limit]


def concentration_extremes(cur, limit=5):
    try:
        cur.execute("""
            SELECT creator_name, COUNT(*) AS items, SUM(favorite_count) AS favs
            FROM items
            WHERE creator_name IS NOT NULL AND creator_name <> ''
              AND favorite_count > 100
            GROUP BY creator_name
            ORDER BY favs DESC
            LIMIT %s
        """, (int(limit),))
        top = [
            {"creator": r[0][:30], "items": int(r[1]), "favs": int(r[2] or 0)}
            for r in cur.fetchall()
        ]
    except Exception as e:
        print(f"[xray] concentration top: {e}", flush=True)
        top = []
    return top


def hidden_gems(cur, days=30, min_rate=15, max_supply=30, limit=8):
    try:
        cur.execute("""
            SELECT id, name, creator_name, favorite_count,
                   EXTRACT(EPOCH FROM (NOW() - created_at))/86400 AS age_days
            FROM items
            WHERE created_at IS NOT NULL
              AND created_at >= NOW() - INTERVAL '%s days'
              AND favorite_count > 30
            ORDER BY favorite_count DESC
            LIMIT 500
        """, (int(days),))
        rows = cur.fetchall()
    except Exception as e:
        print(f"[xray] hidden gems: {e}", flush=True)
        return []

    gems = []
    for item_id, name, creator, favs, age in rows:
        try:
            age_f = float(age or 0)
            if age_f <= 0.1:
                continue
            rate = (favs or 0) / age_f
        except Exception:
            continue
        if rate < min_rate:
            continue
        tokens = re.findall(r"[a-z]{4,}", (name or "").lower())
        if not tokens:
            continue
        keyword = tokens[0]
        try:
            cur.execute(
                "SELECT COUNT(*) FROM items WHERE LOWER(name) LIKE %s AND favorite_count > 5",
                (f"%{keyword}%",)
            )
            supply = cur.fetchone()[0] or 0
        except Exception:
            continue
        if supply > max_supply:
            continue
        gems.append({
            "id": item_id,
            "name": (name or "")[:50],
            "creator": (creator or "")[:24],
            "favs": int(favs or 0),
            "rate": round(rate, 1),
            "supply": supply,
        })
    gems.sort(key=lambda g: -g["rate"])
    return gems[:limit]


def build_xray(cur):
    return {
        "health": catalog_health(cur),
        "categories": category_breakdown(cur),
        "hottest": hottest_niches(cur),
        "coldest": coldest_niches(cur),
        "whitespace": whitespace_count(cur),
        "arbitrage": arbitrage_signals(cur),
        "concentration_top": concentration_extremes(cur),
        "gems": hidden_gems(cur),
    }


def format_xray(x):
    if not x:
        return "(no xray data)"
    h = x.get("health") or {}
    lines = []
    lines.append("```")
    lines.append("╔══════════════════════════════════════════════════════════╗")
    lines.append("║        ROBLOX UGC MARKET X-RAY — LIVE STATE              ║")
    lines.append("╚══════════════════════════════════════════════════════════╝")
    lines.append("```")
    lines.append("")

    desc_pct = round(100 * h.get("with_desc", 0) / max(h.get("total", 1), 1), 1)
    lines.append("## 📊 CATALOG HEALTH")
    lines.append(f"• Items tracked: **{h.get('total', 0):,}**")
    lines.append(f"• Descriptions: **{h.get('with_desc', 0):,}** ({desc_pct}%)")
    lines.append(f"• Creators indexed: **{h.get('creators', 0):,}**")
    lines.append(f"• Search terms known: **{h.get('search_terms', 0):,}**")
    lines.append(f"• Avg favs per item: **{h.get('avg_favs', 0):,}**")
    lines.append(f"• Max favs any item: **{h.get('max_favs', 0):,}**")
    lines.append("")

    cats = x.get("categories") or []
    if cats:
        lines.append("## 🏷️ CATEGORY BREAKDOWN")
        for c in cats[:8]:
            lines.append(
                f"• **{c['label']}** — {c['count']:,} items · "
                f"median {c['median_favs']:,} favs · {c['winners']:,} winners (1k+)"
            )
        lines.append("")

    hot = x.get("hottest") or []
    if hot:
        lines.append("## 🔥 HOTTEST NICHES (favs/day, last 30 days)")
        for i, w in enumerate(hot[:8], 1):
            lines.append(
                f"{i}. `{w['word']}` — avg **{w['avg_rate']}/day** · "
                f"peak **{w['max_rate']}/day** · {w['sample']} items sampled"
            )
        lines.append("")

    cold = x.get("coldest") or []
    if cold:
        lines.append("## 🧊 COLDEST NICHES (new items piling up, last 4 weeks)")
        for i, w in enumerate(cold[:6], 1):
            lines.append(f"{i}. `{w['word']}` — **{w['new_items']}** new items")
        lines.append("")

    ws = x.get("whitespace") or {}
    if ws.get("whitespace_terms", 0) > 0:
        lines.append("## 🕳️ WHITESPACE (search terms with ≤3 items)")
        lines.append(
            f"• **{ws['whitespace_terms']:,}** of {ws.get('total_terms', 0):,} "
            f"search terms have almost no supply"
        )
        for t in (ws.get("top") or [])[:5]:
            lines.append(f"   - `{t['term']}` — supply: {t['supply']}")
        lines.append("")

    arb = x.get("arbitrage") or []
    if arb:
        lines.append("## 🔀 CROSS-CATEGORY ARBITRAGE")
        for i, s in enumerate(arb[:5], 1):
            lines.append(
                f"{i}. `{s['word']}` — proven in **{s['source']}** "
                f"({s['source_avg_favs']:,} avg favs, {s['source_supply']} items) · "
                f"only **{s['target_supply']}** in **{s['target']}**"
            )
        lines.append("")

    gems = x.get("gems") or []
    if gems:
        lines.append("## 💎 HIDDEN GEMS (high velocity, low competition)")
        for g in gems[:6]:
            lines.append(
                f"• `{g['name']}` — **{g['rate']}/day** · "
                f"{g['favs']:,} favs · keyword supply: {g['supply']} · by {g['creator']}"
            )
        lines.append("")

    conc = x.get("concentration_top") or []
    if conc:
        lines.append("## 🏛️ TOP CREATORS (by total favs)")
        for i, c in enumerate(conc[:5], 1):
            lines.append(f"{i}. `{c['creator']}` — {c['items']} items · {c['favs']:,} favs")
        lines.append("")

    lines.append("---")
    lines.append("_All facts. No predictions. No scores. Read the numbers, then decide._")
    return "\n".join(lines)
