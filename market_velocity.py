"""
market_velocity.py — Velocity, trajectory, and creator concentration.

Three factual signals that normal creators cannot compute:
  1. compute_velocity()      — favs/day of recent items in a niche
  2. compute_trajectory()    — is competition heating up or cooling down
  3. compute_concentration() — is the niche dominated by a few creators

All pure SQL. No predictions. No scores. Just facts.
"""
from collections import defaultdict


def _kw_like(kw):
    return f"%{kw.lower().strip()}%"


def compute_velocity(cur, keyword, days=90, asset_ids=None, min_favs=5, limit=10):
    """
    For items matching keyword created in last `days`, compute favs/day.
    Returns dict with sample_size, avg_favs_per_day, top movers.
    """
    if cur is None or not keyword or len(keyword) < 3:
        return {}

    sql = """
        SELECT id, name, favorite_count, creator_name, created_at,
               EXTRACT(EPOCH FROM (NOW() - created_at))/86400 AS age_days
        FROM items
        WHERE LOWER(name) LIKE %s
          AND created_at IS NOT NULL
          AND created_at >= NOW() - INTERVAL '%s days'
          AND favorite_count > %s
    """
    params = [_kw_like(keyword), int(days), int(min_favs)]

    if asset_ids:
        sql += " AND asset_type_id = ANY(%s)"
        params.append(list(asset_ids))

    sql += " ORDER BY favorite_count DESC LIMIT 500"

    try:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
    except Exception as e:
        print(f"[velocity] query failed for '{keyword}': {e}", flush=True)
        return {}

    if not rows:
        return {
            "keyword": keyword, "sample_size": 0,
            "avg_favs_per_day": 0.0, "top_movers": [],
        }

    movers = []
    total_rate = 0.0
    valid = 0
    for item_id, name, favs, creator, created_at, age_days in rows:
        try:
            age = float(age_days or 0)
            if age <= 0.1:
                continue
            rate = (favs or 0) / age
            movers.append({
                "id": item_id,
                "name": (name or "")[:60],
                "creator": (creator or "")[:40],
                "favs": favs or 0,
                "age_days": round(age, 1),
                "favs_per_day": round(rate, 2),
            })
            total_rate += rate
            valid += 1
        except Exception:
            continue

    movers.sort(key=lambda m: -m["favs_per_day"])

    return {
        "keyword": keyword,
        "sample_size": valid,
        "avg_favs_per_day": round(total_rate / valid, 2) if valid else 0.0,
        "top_movers": movers[:limit],
    }


def compute_trajectory(cur, keyword, weeks=4, asset_ids=None):
    """
    New items launched per week for this keyword. Direction = heating/cooling.
    """
    if cur is None or not keyword or len(keyword) < 3:
        return {}

    sql = """
        SELECT DATE_TRUNC('week', created_at)::date AS wk, COUNT(*) AS cnt
        FROM items
        WHERE LOWER(name) LIKE %s
          AND created_at IS NOT NULL
          AND created_at >= NOW() - INTERVAL '%s weeks'
    """
    params = [_kw_like(keyword), int(weeks)]

    if asset_ids:
        sql += " AND asset_type_id = ANY(%s)"
        params.append(list(asset_ids))

    sql += " GROUP BY wk ORDER BY wk"

    try:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
    except Exception as e:
        print(f"[trajectory] query failed for '{keyword}': {e}", flush=True)
        return {}

    if not rows:
        return {"keyword": keyword, "weeks": [], "direction": "FLAT", "pct_change": 0}

    weekly = [{"week": str(wk), "count": int(cnt or 0)} for wk, cnt in rows]

    if len(weekly) < 2:
        return {
            "keyword": keyword, "weeks": weekly,
            "direction": "UNKNOWN", "pct_change": 0,
        }

    first = weekly[0]["count"] or 1
    last = weekly[-1]["count"]
    pct = round(100 * (last - first) / max(first, 1), 1)

    if pct >= 50:
        direction = "HEATING"
    elif pct <= -30:
        direction = "COOLING"
    else:
        direction = "STABLE"

    return {
        "keyword": keyword,
        "weeks": weekly,
        "direction": direction,
        "pct_change": pct,
    }


def compute_concentration(cur, keyword, asset_ids=None, top_n=100):
    """
    Take top N items in a niche by favs. How many creators own them?
    High concentration = a few studios dominate. Low = fragmented opportunity.
    """
    if cur is None or not keyword or len(keyword) < 3:
        return {}

    inner = """
        SELECT creator_name, favorite_count
        FROM items
        WHERE LOWER(name) LIKE %s
          AND favorite_count > 0
    """
    params = [_kw_like(keyword)]

    if asset_ids:
        inner += " AND asset_type_id = ANY(%s)"
        params.append(list(asset_ids))

    inner += " ORDER BY favorite_count DESC LIMIT %s"
    params.append(int(top_n))

    sql = f"""
        SELECT creator_name, COUNT(*) AS items, SUM(favorite_count) AS favs
        FROM ({inner}) sub
        WHERE creator_name IS NOT NULL AND creator_name <> ''
        GROUP BY creator_name
        ORDER BY items DESC
    """

    try:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
    except Exception as e:
        print(f"[concentration] query failed for '{keyword}': {e}", flush=True)
        return {}

    if not rows:
        return {"keyword": keyword, "creator_count": 0, "top_creators": [], "verdict": "EMPTY"}

    total_items = sum(int(r[1] or 0) for r in rows)
    total_creators = len(rows)

    top3 = rows[:3]
    top3_items = sum(int(r[1] or 0) for r in top3)
    top3_share = round(100 * top3_items / max(total_items, 1), 1)

    if total_creators <= 5 or top3_share >= 60:
        verdict = "MONOPOLIZED"
    elif top3_share >= 40:
        verdict = "CONCENTRATED"
    else:
        verdict = "FRAGMENTED"

    return {
        "keyword": keyword,
        "creator_count": total_creators,
        "top3_share": top3_share,
        "top_creators": [
            {"creator": r[0][:40], "items": int(r[1]), "favs": int(r[2] or 0)}
            for r in top3
        ],
        "verdict": verdict,
    }


def build_niche_intel(cur, keywords, asset_ids=None, days=90, weeks=4):
    """
    Run all 3 features on each keyword. Returns a compact dict for prompt injection.
    """
    out = {"keywords": [], "velocity": {}, "trajectory": {}, "concentration": {}}

    for kw in keywords[:4]:
        kw = (kw or "").lower().strip()
        if len(kw) < 3:
            continue
        out["keywords"].append(kw)
        out["velocity"][kw] = compute_velocity(cur, kw, days=days, asset_ids=asset_ids)
        out["trajectory"][kw] = compute_trajectory(cur, kw, weeks=weeks, asset_ids=asset_ids)
        out["concentration"][kw] = compute_concentration(cur, kw, asset_ids=asset_ids)

    return out


def format_niche_intel_for_prompt(intel):
    """Render build_niche_intel() output as a text block for AI prompts."""
    if not intel or not intel.get("keywords"):
        return "(no market intel available)"

    lines = ["=== NICHE VELOCITY (favs/day of recent items) ==="]
    for kw in intel["keywords"]:
        v = intel["velocity"].get(kw) or {}
        if v.get("sample_size", 0) > 0:
            lines.append(
                f"- {kw}: avg {v['avg_favs_per_day']} favs/day "
                f"across {v['sample_size']} recent items"
            )
            for m in (v.get("top_movers") or [])[:3]:
                lines.append(
                    f"    • `{m['name']}` — {m['favs_per_day']} favs/day "
                    f"({m['favs']:,} favs, {m['age_days']}d old)"
                )
        else:
            lines.append(f"- {kw}: no recent items found")

    lines.append("")
    lines.append("=== SATURATION TRAJECTORY (new items per week) ===")
    for kw in intel["keywords"]:
        t = intel["trajectory"].get(kw) or {}
        if t.get("weeks"):
            week_str = " → ".join(f"{w['count']}" for w in t["weeks"])
            lines.append(
                f"- {kw}: {week_str}  [{t['direction']}, {t['pct_change']:+.0f}%]"
            )
        else:
            lines.append(f"- {kw}: no launch history")

    lines.append("")
    lines.append("=== CREATOR CONCENTRATION (top 100 items) ===")
    for kw in intel["keywords"]:
        c = intel["concentration"].get(kw) or {}
        if c.get("creator_count", 0) > 0:
            top3 = ", ".join(f"{x['creator']} ({x['items']})" for x in c["top_creators"])
            lines.append(
                f"- {kw}: {c['creator_count']} creators · top 3 own {c['top3_share']}% "
                f"[{c['verdict']}] · {top3}"
            )
        else:
            lines.append(f"- {kw}: no creators found")

    return "\n".join(lines)
