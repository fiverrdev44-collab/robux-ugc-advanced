"""portfolio_brain.py — Comparative analysis for YOUR catalog."""
import re
from collections import Counter


def _percentile(values, p):
    if not values:
        return 0
    s = sorted(values)
    return s[max(0, min(len(s) - 1, int(len(s) * p)))]


def _tokens(name):
    return [t for t in re.findall(r"[a-z]{4,}", (name or "").lower())
            if t not in {"with", "this", "that", "from", "into"}]


def _item_snapshot(cur, item_id):
    try:
        cur.execute("""
            SELECT id, name, favorite_count, price, total_sales, asset_type_id,
                   created_at,
                   EXTRACT(EPOCH FROM (NOW() - COALESCE(created_at, fetched_at)))/86400 AS age_days
            FROM items WHERE id = %s
        """, (item_id,))
        row = cur.fetchone()
    except Exception:
        return None
    if not row:
        return None

    iid, name, favs, price, sales, atype, _, age_days = row
    age_days = float(age_days or 0)
    favs = favs or 0

    velocity_7d = velocity_prior_7d = accel = None
    try:
        cur.execute("""
            SELECT
              MAX(favorite_count) FILTER (WHERE snapshot_at >= NOW() - INTERVAL '7 days'),
              MIN(favorite_count) FILTER (WHERE snapshot_at >= NOW() - INTERVAL '7 days'),
              MAX(favorite_count) FILTER (WHERE snapshot_at BETWEEN NOW() - INTERVAL '14 days' AND NOW() - INTERVAL '7 days'),
              MIN(favorite_count) FILTER (WHERE snapshot_at BETWEEN NOW() - INTERVAL '14 days' AND NOW() - INTERVAL '7 days')
            FROM item_history WHERE item_id = %s
        """, (item_id,))
        h = cur.fetchone()
        if h and h[0] is not None and h[1] is not None:
            velocity_7d = (h[0] - h[1]) / 7.0
        if h and h[2] is not None and h[3] is not None:
            velocity_prior_7d = (h[2] - h[3]) / 7.0
        if velocity_7d is not None and velocity_prior_7d and velocity_prior_7d > 0:
            accel = round(velocity_7d / velocity_prior_7d, 2)
    except Exception:
        pass

    return {
        "id": iid, "name": name, "favs": favs, "price": price or 0,
        "sales": sales or 0, "asset_type_id": atype,
        "age_days": round(age_days, 1),
        "velocity_7d": round(velocity_7d, 2) if velocity_7d is not None else None,
        "acceleration": accel,
    }


def _competitors(cur, name, atype, cap=100):
    toks = _tokens(name)
    if not toks:
        return []
    key = toks[0]
    try:
        cur.execute("""
            SELECT name, favorite_count, price,
                   EXTRACT(EPOCH FROM (NOW() - created_at))/86400,
                   creator_name
            FROM items
            WHERE LOWER(name) LIKE %s AND asset_type_id = %s AND favorite_count > 5
            ORDER BY favorite_count DESC LIMIT %s
        """, (f"%{key}%", int(atype or 0), int(cap)))
        return cur.fetchall()
    except Exception:
        return []


def _classify_item(snap, comp_rows):
    if not snap:
        return {"verdict": "UNKNOWN", "action": "Fetch this item first."}

    age = snap["age_days"]
    favs = snap["favs"]
    rate = favs / age if age > 0 else 0
    accel = snap.get("acceleration")

    comp_favs = [c[1] or 0 for c in comp_rows if c[1] and c[1] > 5]
    comp_prices = [c[2] or 0 for c in comp_rows if c[2] and c[2] > 0]
    niche_med = _percentile(comp_favs, 0.5)
    niche_top = _percentile(comp_favs, 0.9)
    price_med = _percentile(comp_prices, 0.5) if comp_prices else 0

    percentile = 0
    if comp_favs:
        below = sum(1 for f in comp_favs if f < favs)
        percentile = round(100 * below / len(comp_favs), 1)

    verdict, action = "OBSERVING", "Wait 72h. Too early."

    if age >= 7 and rate < 1:
        verdict = "DEAD"
        action = f"Rate {rate:.2f}/day. Kill. Launch new from `!early 14`."
    elif age >= 7 and rate < 3 and percentile < 40:
        verdict = "UNDERPERFORMING"
        action = f"Percentile {percentile}%. One title edit, then wait 72h."
    elif percentile >= 90:
        verdict = "WINNER"
        action = "Top 10%. DO NOT EDIT. Make themed remixes."
    elif percentile >= 70:
        verdict = "STRONG"
        action = "Top 30%. Consider remix at slightly higher price."
    elif percentile >= 50:
        verdict = "AVERAGE"
        action = "At median. Wait 30 days or make a variant."
    elif percentile >= 25:
        verdict = "BELOW MEDIAN"
        action = "One title edit now. If no lift in 7 days, kill."

    if accel is not None:
        if accel >= 1.5 and verdict not in ("WINNER", "DEAD"):
            verdict = "ACCELERATING"
            action = f"Velocity {accel}x week-over-week. DO NOT TOUCH. Post TikTok."
        elif accel <= 0.5 and verdict in ("WINNER", "STRONG"):
            verdict = "DECELERATING"
            action = f"Velocity {accel}x. Cooling. Consider variant."

    return {
        "verdict": verdict, "action": action, "percentile": percentile,
        "niche_median": niche_med, "niche_top10": niche_top,
        "niche_price_median": price_med,
    }
