"""Avatar Backgrounds (Roblox AssetType 92) category support.

This module is intentionally read-only and deterministic. It never performs
marketplace requests, never treats favorites as sales, and reports insufficient
evidence when the bounded sample is too small.
"""
import re
import struct
from datetime import datetime, timezone
from pathlib import Path

ASSET_TYPE_ID = 92
CATEGORY = "backgrounds"
EXPECTED_WIDTH = 2560
EXPECTED_HEIGHT = 1440
MIN_SAMPLE = 20
DEFAULT_EARLY_CANDIDATE_LIMIT = 500
DEFAULT_EARLY_LIMIT = 10
MIN_EARLY_OBSERVATIONS = 2
ACCELERATION_OBSERVATIONS = 3
THUMBNAIL_ENDPOINT = "https://thumbnails.roblox.com/v1/assets"
SUPPORTED_FORMATS = {"JPEG", "PNG", "TGA", "BMP"}
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tga", ".bmp"}

STOPWORDS = {
    "the", "and", "for", "with", "your", "you", "a", "an", "of", "in", "on",
    "to", "my", "is", "it", "as", "at", "by", "roblox", "ugc", "avatar",
    "background", "backgrounds", "scene", "environment", "new", "best",
    "cute", "cool", "aesthetic", "viral", "trending", "original",
}


def _utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _percentile(values, q):
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


def _distribution(values):
    values = [float(v) for v in values if v is not None]
    if not values:
        return {"available": False, "sample_n": 0, "min": None,
                "median": None, "p75": None, "max": None}
    return {
        "available": True,
        "sample_n": len(values),
        "min": round(min(values), 2),
        "median": round(_percentile(values, 0.5), 2),
        "p75": round(_percentile(values, 0.75), 2),
        "max": round(max(values), 2),
    }


def _tokens(text):
    return [
        token for token in re.findall(r"[a-z]{4,}", (text or "").lower())
        if token not in STOPWORDS
    ]


def _rollback(cur):
    try:
        cur.connection.rollback()
    except Exception:
        try:
            cur.rollback()
        except Exception:
            pass


def _fetch_rows(cur, limit):
    try:
        cur.execute("""
            SELECT id, name, COALESCE(description, ''), price,
                   favorite_count, creator_id, creator_type, creator_name,
                   created_at
            FROM items
            WHERE asset_type_id = 92
            LIMIT %s
        """, (int(limit),))
        return cur.fetchall(), True
    except Exception:
        _rollback(cur)
        cur.execute("""
            SELECT id, name, COALESCE(description, ''), price,
                   favorite_count, NULL, NULL, creator_name, created_at
            FROM items
            WHERE asset_type_id = 92
            LIMIT %s
        """, (int(limit),))
        return cur.fetchall(), False


def analyze_market(cur, days=180, limit=500, now=None):
    """Return a bounded, read-only Avatar Backgrounds market snapshot."""
    now = now or datetime.now(timezone.utc)
    rows, has_identity_columns = _fetch_rows(cur, limit)
    ids = [row[0] for row in rows if row[0] is not None]

    prices = [row[3] for row in rows if row[3] and row[3] > 0]
    favorites = [row[4] for row in rows if row[4] is not None]
    ages = []
    for row in rows:
        created = _utc(row[8])
        if created:
            ages.append(max(0.0, (now - created).total_seconds() / 86400.0))

    creators = []
    identity_reliable = has_identity_columns
    for row in rows:
        creator_id, creator_type, creator_name = row[5], row[6], row[7]
        if has_identity_columns and creator_id is not None and creator_type:
            creators.append(f"{creator_type}:{creator_id}")
        elif creator_name:
            creators.append(f"name:{creator_name.lower()}")
            identity_reliable = False

    creator_counts = {}
    for key in creators:
        creator_counts[key] = creator_counts.get(key, 0) + 1
    top_creator_share = None
    if creators:
        top_creator_share = round(
            max(creator_counts.values()) / len(creators) * 100, 1)

    theme_counts = {}
    for row in rows:
        for token in set(_tokens(f"{row[1]} {row[2]}")):
            theme_counts[token] = theme_counts.get(token, 0) + 1
    themes = sorted(
        ({"theme": token, "items": count}
         for token, count in theme_counts.items()),
        key=lambda item: (-item["items"], item["theme"]),
    )[:12]

    velocity = _favorite_velocity(cur, ids, days=days)
    sample_n = len(rows)
    evidence_status = (
        "observed" if sample_n >= MIN_SAMPLE else "insufficient_evidence")

    limitations = [
        "Favorites are not sales; no CTR, revenue, demand volume, or "
        "conversion probability is inferred.",
        "Listing counts, prices, favorites, and ages are observed only from "
        "the stored sample, not a live marketplace scan.",
        "Favorite velocity requires at least two historical snapshots per "
        "item; otherwise it is reported as unavailable.",
    ]
    if not identity_reliable:
        limitations.append(
            "Creator concentration falls back to display names because "
            "reliable creator identity is unavailable; treat it as a lower "
            "bound.")
    if sample_n < MIN_SAMPLE:
        limitations.append(
            f"Only {sample_n} sampled item(s); {MIN_SAMPLE}+ are required "
            "before treating distributions as evidence.")

    return {
        "category": CATEGORY,
        "asset_type_id": ASSET_TYPE_ID,
        "generated_at": now.isoformat(),
        "sample_n": sample_n,
        "evidence_status": evidence_status,
        "listing_count": sample_n,
        "prices": _distribution(prices),
        "favorites": _distribution(favorites),
        "age_days": _distribution(ages),
        "creators": {
            "unique": len(creator_counts),
            "identity_reliable": identity_reliable,
            "top_creator_share_pct": top_creator_share,
        },
        "themes": themes,
        "favorite_velocity": velocity,
        "limitations": limitations,
    }


def _favorite_velocity(cur, ids, days=180):
    if not ids:
        return {"available": False, "reason": "no sampled items",
                "sample_n": 0, "median_per_day": None}
    try:
        cur.execute(f"""
            SELECT item_id, favorite_count, snapshot_at
            FROM item_history
            WHERE item_id = ANY(%s)
              AND snapshot_at >= NOW() - INTERVAL '{int(days)} days'
            ORDER BY item_id, snapshot_at
        """, (list(ids),))
        rows = cur.fetchall()
    except Exception:
        _rollback(cur)
        return {"available": False, "reason": "history query unavailable",
                "sample_n": 0, "median_per_day": None}

    series = {}
    for item_id, favs, snapshot in rows:
        if favs is None or snapshot is None:
            continue
        series.setdefault(item_id, []).append((snapshot, favs))

    rates = []
    for points in series.values():
        if len(points) < 2:
            continue
        points.sort()
        days_span = (points[-1][0] - points[0][0]).total_seconds() / 86400.0
        if days_span <= 0:
            continue
        rates.append((points[-1][1] - points[0][1]) / days_span)
    if not rates:
        return {
            "available": False,
            "reason": "insufficient historical snapshots",
            "sample_n": len(series),
            "median_per_day": None,
        }
    return {
        "available": True,
        "reason": "",
        "sample_n": len(rates),
        "median_per_day": round(_percentile(rates, 0.5), 3),
    }


def format_market_report(data, max_lines=18):
    if not data:
        return "No Avatar Background data available."
    lines = ["## Avatar Backgrounds — observed sample"]
    lines.append(
        f"• Sampled items: **{data.get('listing_count', 0)}**")
    lines.append(f"• Evidence status: **{data.get('evidence_status')}**")
    prices = data.get("prices") or {}
    if prices.get("available"):
        lines.append(
            f"• Price R$: median **{prices['median']}** "
            f"(range {prices['min']}–{prices['max']})")
    favorites = data.get("favorites") or {}
    if favorites.get("available"):
        lines.append(
            f"• Favorites: median **{favorites['median']}** "
            f"(range {favorites['min']}–{favorites['max']})")
    ages = data.get("age_days") or {}
    if ages.get("available"):
        lines.append(f"• Median age: **{ages['median']}** days")
    creators = data.get("creators") or {}
    if creators.get("unique"):
        lines.append(
            f"• Creators: **{creators['unique']}** observed · top share "
            f"**{creators.get('top_creator_share_pct')}%** · identity "
            f"{'reliable' if creators.get('identity_reliable') else 'name-only'}")
    velocity = data.get("favorite_velocity") or {}
    if velocity.get("available"):
        lines.append(
            f"• Favorite velocity: median **{velocity['median_per_day']}/day** "
            f"across {velocity['sample_n']} item(s)")
    else:
        lines.append(
            f"• Favorite velocity: unavailable ({velocity.get('reason')})")
    themes = data.get("themes") or []
    if themes:
        lines.append(
            "• Title/description themes: "
            + ", ".join(f"`{t['theme']}` ({t['items']})" for t in themes[:8]))
    lines.append(
        "_Favorites are not sales. No CTR, revenue, demand volume, or "
        "conversion probability is inferred._")
    return "\n".join(lines[:max_lines])


def _background_candidate_rows(cur, days, candidate_limit):
    cur.execute(f"""
        WITH candidates AS (
            SELECT id, name, creator_name, favorite_count, price, created_at,
                   EXTRACT(EPOCH FROM (NOW() - created_at))/86400 AS age_days,
                   asset_type_id
            FROM items
            WHERE asset_type_id = 92
              AND created_at IS NOT NULL
              AND created_at >= NOW() - INTERVAL '{int(days)} days'
            ORDER BY created_at DESC, id DESC
            LIMIT {int(candidate_limit)}
        )
        SELECT c.id, c.name, c.creator_name, c.favorite_count, c.price,
               c.age_days, c.created_at, c.asset_type_id,
               COUNT(h.id) AS observations
        FROM candidates c
        LEFT JOIN item_history h
               ON h.item_id = c.id
              AND h.favorite_count IS NOT NULL
              AND h.snapshot_at >= NOW() - INTERVAL '{int(days)} days'
        GROUP BY c.id, c.name, c.creator_name, c.favorite_count, c.price,
                 c.age_days, c.created_at, c.asset_type_id
        ORDER BY c.created_at DESC, c.id DESC
    """)
    return cur.fetchall() or []


def _background_history_rows(cur, item_ids, days):
    if not item_ids:
        return []
    cur.execute(f"""
        SELECT h.item_id, h.favorite_count, h.snapshot_at
        FROM item_history h
        JOIN items i ON i.id = h.item_id
        WHERE h.item_id = ANY(%s)
          AND i.asset_type_id = 92
          AND h.favorite_count IS NOT NULL
          AND h.snapshot_at >= NOW() - INTERVAL '{int(days)} days'
        ORDER BY h.item_id, h.snapshot_at, h.id
    """, (list(item_ids),))
    return cur.fetchall() or []


def _background_acceleration(points):
    if len(points) < ACCELERATION_OBSERVATIONS:
        return None
    rates = []
    for (t0, f0), (t1, f1) in zip(points, points[1:]):
        dt = (t1 - t0).total_seconds() / 86400.0
        if dt > 0:
            rates.append((f1 - f0) / dt)
    if len(rates) < 2:
        return None
    return rates[-1] - rates[0]


def _background_confidence(observations, observation_days, freshness_hours):
    if (observations >= ACCELERATION_OBSERVATIONS
            and observation_days >= 2.0
            and freshness_hours <= 24.0):
        return "high"
    if observations >= MIN_EARLY_OBSERVATIONS and freshness_hours <= 72.0:
        return "medium"
    return "low"


def _background_text_themes(items):
    counts = {}
    for item in items:
        for token in set(_tokens(item.get("name"))):
            counts[token] = counts.get(token, 0) + 1
    return [
        {"theme": token, "items": count}
        for token, count in sorted(
            counts.items(), key=lambda pair: (-pair[1], pair[0]))[:10]
    ]


def find_background_early_winners(cur, days=7, limit=DEFAULT_EARLY_LIMIT,
                                  candidate_limit=DEFAULT_EARLY_CANDIDATE_LIMIT,
                                  now=None):
    """Rank recently published backgrounds by measured favorite growth.

    ``days`` is both the publication window and the history window. The
    candidate set is deterministic (latest by created_at, then id) and bounded.
    Lifetime favorites divided by listing age is reported separately and is
    never used for ranking.
    """
    days = max(1, min(int(days), 30))
    limit = max(1, min(int(limit), 50))
    candidate_limit = max(1, min(int(candidate_limit), 2000))
    now = now or datetime.now(timezone.utc)
    result = {
        "category": CATEGORY,
        "asset_type_id": ASSET_TYPE_ID,
        "window_days": days,
        "candidate_limit": candidate_limit,
        "generated_at": now.isoformat(),
        "status": "ok",
        "ranked": [],
        "insufficient": [],
        "candidate_window": 0,
        "usable_history": 0,
        "coverage_pct": 0.0,
        "data_confidence": "low",
        "insufficient_count": 0,
        "non_growing_count": 0,
        "text_themes": [],
        "text_themes_label": "text-derived title keywords, not visual analysis",
        "visual_analysis": {
            "status": "not_analyzed",
            "reason": (
                "The approved thumbnail endpoint returns an image reference, "
                "but automated visual analysis is not enabled to avoid "
                "unbudgeted API/AI usage."),
            "thumbnail_endpoint": THUMBNAIL_ENDPOINT,
        },
        "method": (
            "Measured favorites change between the first and last valid "
            "item_history snapshots inside the window. Current favorites "
            "divided by listing age is reported separately as a lifetime "
            "average and is not used for ranking."),
    }

    try:
        rows = _background_candidate_rows(cur, days, candidate_limit)
    except Exception:
        _rollback(cur)
        result.update(status="unavailable", error="candidate query unavailable")
        return result

    rows = [row for row in rows if int(row[7] or 0) == ASSET_TYPE_ID]
    result["candidate_window"] = len(rows)
    if not rows:
        result["status"] = "no_recent_backgrounds"
        return result

    usable_ids = [
        row[0] for row in rows
        if int(row[8] or 0) >= MIN_EARLY_OBSERVATIONS
    ]
    histories = {}
    try:
        for item_id, favs, snapshot in _background_history_rows(
                cur, usable_ids, days):
            if item_id is None or favs is None or snapshot is None:
                continue
            histories.setdefault(item_id, []).append((snapshot, favs))
    except Exception:
        _rollback(cur)
        result["history_error"] = "history query unavailable"

    ranked = []
    insufficient = []
    non_growing = []
    usable_history = 0
    for row in rows:
        (item_id, name, creator, current_favs, price, age_days,
         created_at, _atype, _observations) = row
        points = sorted(
            histories.get(item_id, []), key=lambda point: point[0])
        if len(points) >= MIN_EARLY_OBSERVATIONS:
            usable_history += 1
        if len(points) < MIN_EARLY_OBSERVATIONS:
            insufficient.append({
                "id": item_id,
                "name": (name or "")[:120],
                "url": f"https://www.roblox.com/catalog/{item_id}",
                "creator": (creator or "")[:120],
                "current_favorites": (
                    int(current_favs) if current_favs is not None else None),
                "price": (int(price) if price is not None
                          and int(price) > 0 else None),
                "listing_age_days": round(float(age_days or 0), 2),
                "observations": len(points),
                "reason": "fewer than 2 valid favorite observations",
            })
            continue

        first_time, first_favs = points[0]
        last_time, last_favs = points[-1]
        observation_days = (last_time - first_time).total_seconds() / 86400.0
        if observation_days <= 0:
            insufficient.append({
                "id": item_id,
                "name": (name or "")[:120],
                "url": f"https://www.roblox.com/catalog/{item_id}",
                "creator": (creator or "")[:120],
                "current_favorites": (
                    int(current_favs) if current_favs is not None else None),
                "price": (int(price) if price is not None
                          and int(price) > 0 else None),
                "listing_age_days": round(float(age_days or 0), 2),
                "observations": len(points),
                "reason": "observation window has no positive duration",
            })
            continue

        measured_gain = int(last_favs) - int(first_favs)
        if measured_gain <= 0:
            non_growing.append({
                "id": item_id,
                "name": (name or "")[:120],
                "url": f"https://www.roblox.com/catalog/{item_id}",
                "measured_favorites_gained": measured_gain,
                "observations": len(points),
                "reason": "no positive measured favorite gain in the window",
            })
            continue

        age = float(age_days or 0)
        lifetime_per_day = None
        if current_favs is not None and age > 0:
            lifetime_per_day = float(current_favs) / age
        freshness_hours = max(
            0.0, (now - _utc(last_time)).total_seconds() / 3600.0)
        acceleration = _background_acceleration(points)
        confidence = _background_confidence(
            len(points), observation_days, freshness_hours)
        warnings = []
        if len(points) < ACCELERATION_OBSERVATIONS:
            warnings.append(
                "fewer than 3 observations; acceleration unavailable")
        if observation_days < 1.0:
            warnings.append("observation window under 1 day")
        if freshness_hours > 72.0:
            warnings.append("last snapshot older than 72h")
        if current_favs is None:
            warnings.append("current favorites unavailable")
        if price is None or int(price) <= 0:
            warnings.append("price unavailable or zero")
        if confidence != "high":
            warnings.append(f"{confidence} confidence")

        ranked.append({
            "id": item_id,
            "asset_type_id": ASSET_TYPE_ID,
            "name": (name or "")[:120],
            "url": f"https://www.roblox.com/catalog/{item_id}",
            "creator": (creator or "")[:120],
            "listing_age_days": round(age, 2),
            "price": (int(price) if price is not None
                      and int(price) > 0 else None),
            "current_favorites": (
                int(current_favs) if current_favs is not None else None),
            "last_observed_favorites": int(last_favs),
            "measured_favorites_gained": measured_gain,
            "measured_favs_per_day": round(
                measured_gain / observation_days, 2),
            "lifetime_favs_per_day": (
                round(lifetime_per_day, 2)
                if lifetime_per_day is not None else None),
            "observations": len(points),
            "observation_days": round(observation_days, 2),
            "observation_period": (
                f"{_utc(first_time):%Y-%m-%d %H:%M} → "
                f"{_utc(last_time):%Y-%m-%d %H:%M} UTC"),
            "observation_start": _utc(first_time).isoformat(),
            "observation_end": _utc(last_time).isoformat(),
            "snapshot_freshness_hours": round(freshness_hours, 1),
            "acceleration_favs_per_day": (
                round(acceleration, 2) if acceleration is not None else None),
            "confidence": confidence,
            "missing_data": warnings,
            "thumbnail_request_url": (
                f"{THUMBNAIL_ENDPOINT}?assetIds={int(item_id)}"
                "&size=768x432&format=Png&isCircular=false"),
            "visual_analysis": "not_analyzed",
        })

    ranked.sort(key=lambda item: (
        -item["measured_favs_per_day"],
        -(item["acceleration_favs_per_day"] or 0.0),
        item["snapshot_freshness_hours"],
        item["listing_age_days"],
        item["id"],
    ))
    ranked_total = len(ranked)
    result["ranked"] = ranked[:limit]
    result["ranked_total"] = ranked_total
    result["usable_history"] = usable_history
    result["coverage_pct"] = round(
        100.0 * usable_history / max(len(rows), 1), 1)
    result["insufficient_count"] = len(insufficient)
    result["non_growing_count"] = len(non_growing)
    result["insufficient"] = insufficient[:5]
    if (len(rows) >= 20 and result["coverage_pct"] >= 50.0):
        result["data_confidence"] = "high"
    elif len(rows) >= 5 and result["coverage_pct"] >= 20.0:
        result["data_confidence"] = "medium"
    else:
        result["data_confidence"] = "low"
    result["text_themes"] = _background_text_themes(result["ranked"])
    if not result["ranked"]:
        result["status"] = (
            "no_positive_growth" if non_growing else "insufficient_history")
    return result


def _early_price_label(price):
    if price is None or int(price) <= 0:
        return "price unavailable"
    return f"R${int(price)}"


def _early_creator_label(creator):
    if not creator:
        return "creator unavailable"
    return f"by `{creator}`"


def format_background_early_winners(data, days=None):
    if not data:
        return "No Avatar Background early-winner data available."
    window = days or data.get("window_days") or "?"
    status = data.get("status")
    if status == "unavailable":
        return (
            f"# ⚡ BACKGROUND EARLY WINNERS — last {window}d\n\n"
            f"❌ Data unavailable: `{data.get('error')}`. No ranking is "
            "claimed.")
    if status == "no_recent_backgrounds":
        return (
            f"# ⚡ BACKGROUND EARLY WINNERS — last {window}d\n\n"
            "No Avatar Backgrounds were published in this window with stored "
            "metadata. No ranking is claimed.")
    if status == "insufficient_history":
        return (
            f"# ⚡ BACKGROUND EARLY WINNERS — last {window}d\n\n"
            f"Candidates: **{data.get('candidate_window', 0)}** · usable "
            f"history: **0** · coverage **0%**.\n"
            "No background had at least two valid favorite observations in "
            "this window. No ranking is claimed. Try `!early 14 backgrounds` "
            "or wait for more snapshots.")
    if status == "no_positive_growth":
        return (
            f"# ⚡ BACKGROUND EARLY WINNERS — last {window}d\n\n"
            f"Candidates: **{data.get('candidate_window', 0)}** · usable "
            f"history: **{data.get('usable_history', 0)}** · coverage "
            f"**{data.get('coverage_pct', 0)}%**.\n"
            "No sampled background had a positive measured favorite gain in "
            "this window. No ranking is claimed.")

    lines = [f"# ⚡ BACKGROUND EARLY WINNERS — measured, last {window}d", ""]
    lines.append(
        f"• Candidate window: **{data.get('candidate_window', 0)}** recent "
        f"backgrounds · usable history: **{data.get('usable_history', 0)}** "
        f"· coverage **{data.get('coverage_pct', 0)}%** · data confidence "
        f"**{data.get('data_confidence', 'low').upper()}**")
    lines.append(
        "• Ranking uses measured favorite differences between the first and "
        "last valid snapshots. Lifetime favorites ÷ listing age is shown "
        "separately.")
    lines.append("")
    for index, item in enumerate(data.get("ranked", []), 1):
        name = (item.get("name") or "unnamed").replace("[", "(").replace(
            "]", ")")
        lines.append(
            f"**{index}. [{name}]({item['url']})** — "
            f"**{item['measured_favs_per_day']}/day measured**")
        lines.append(
            f"   +{item['measured_favorites_gained']} favs over "
            f"{item['observation_days']}d · {item['observations']} obs · "
            f"{item['snapshot_freshness_hours']}h fresh · "
            f"{item['observation_period']}")
        if item.get("acceleration_favs_per_day") is not None:
            lines.append(
                f"   Acceleration: {item['acceleration_favs_per_day']:+.2f} "
                "favs/day change")
        favorites = item.get("current_favorites")
        last_observed = item.get("last_observed_favorites")
        favorites_label = (
            f"{favorites:,} current favorites"
            if favorites is not None else "current favorites unavailable")
        if (favorites is not None and last_observed is not None
                and last_observed != favorites):
            favorites_label += f" (last obs {last_observed:,})"
        lifetime = item.get("lifetime_favs_per_day")
        lifetime_label = (
            f"lifetime avg {lifetime}/day"
            if lifetime is not None else "lifetime avg unavailable")
        lines.append(
            f"   {_early_price_label(item.get('price'))} · "
            f"{item.get('listing_age_days')}d old · "
            f"{_early_creator_label(item.get('creator'))} · "
            f"{favorites_label} · {lifetime_label}")
        warning = f"Confidence: **{item['confidence'].upper()}**"
        if item.get("missing_data"):
            warning += " · " + "; ".join(item["missing_data"])
        lines.append(f"   {warning}")
    if data.get("insufficient_count"):
        lines.append("")
        lines.append(
            f"_{data['insufficient_count']} candidate(s) had fewer than two "
            "valid observations and were not ranked._")
    if data.get("non_growing_count"):
        lines.append(
            f"_{data['non_growing_count']} candidate(s) had no positive "
            "measured gain and were not ranked._")
    if data.get("text_themes"):
        lines.append("")
        lines.append(
            "**Text-derived title themes (not visual analysis):** "
            + ", ".join(
                f"`{theme['theme']}` ({theme['items']})"
                for theme in data["text_themes"]))
    lines.append("")
    lines.append(
        "_Visual image analysis is not enabled; only source-file validation "
        "and text-derived themes are reported. No CTR, impression, or "
        "conversion data is inferred._")
    return "\n".join(lines)


def _image_bytes(source):
    if isinstance(source, (bytes, bytearray)):
        return bytes(source), None
    path = Path(source)
    return path.read_bytes(), path


def _result(path, fmt=None):
    return {
        "ok": False,
        "path": str(path) if path is not None else None,
        "format": fmt,
        "width": None,
        "height": None,
        "size_ok": False,
        "format_ok": False,
        "rgb": False,
        "alpha": None,
        "srgb": None,
        "errors": [],
        "warnings": [],
        "notes": [
            "Roblox applies edge fading automatically; do not add your own "
            "alpha fade.",
            "Avatar placement and cropping vary between surfaces.",
            "A local preview is not guaranteed to match Roblox's final "
            "rendering.",
        ],
    }


def _finalize(result):
    result["size_ok"] = (result["width"] == EXPECTED_WIDTH
                         and result["height"] == EXPECTED_HEIGHT)
    if not result["size_ok"]:
        result["errors"].append(
            f"image must be exactly {EXPECTED_WIDTH}x{EXPECTED_HEIGHT} "
            f"pixels (got {result['width']}x{result['height']})")
    if result["alpha"]:
        result["errors"].append(
            "image has an alpha channel; flatten to RGB with no alpha")
    if not result["rgb"]:
        result["errors"].append(
            "image is not flattened RGB; export a 24-bit RGB file")
    result["ok"] = not result["errors"]
    return result


def _validate_png(data, result):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        result["errors"].append("not a valid PNG signature")
        return result
    pos = 8
    width = height = None
    color_type = bit_depth = None
    has_trns = False
    has_srgb = False
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        chunk = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if chunk == b"IHDR" and len(body) >= 13:
            width, height, bit_depth, color_type = struct.unpack(
                ">IIBB", body[:10])
        elif chunk == b"tRNS":
            has_trns = True
        elif chunk == b"sRGB":
            has_srgb = True
        pos += 12 + length
        if chunk == b"IEND":
            break
    result.update(width=width, height=height)
    result["rgb"] = color_type == 2 and bit_depth == 8
    result["alpha"] = color_type in (4, 6) or has_trns
    result["srgb"] = has_srgb
    if not has_srgb:
        result["warnings"].append(
            "PNG has no sRGB chunk; embed an sRGB profile before upload")
    if color_type != 2 or bit_depth != 8:
        result["errors"].append(
            "PNG must be 8-bit truecolor RGB (color type 2), not palette, "
            "grayscale, or RGBA")
    return _finalize(result)


def _validate_jpeg(data, result):
    if not data.startswith(b"\xff\xd8"):
        result["errors"].append("not a valid JPEG signature")
        return result
    pos = 2
    width = height = None
    has_icc = False
    icc_srgb = False
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        if pos + 4 > len(data):
            break
        length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        body = data[pos + 4:pos + 2 + length]
        if marker in (0xC0, 0xC1, 0xC2) and len(body) >= 5:
            height, width = struct.unpack(">HH", body[1:5])
        if marker == 0xE2 and body.startswith(b"ICC_PROFILE"):
            has_icc = True
            if b"sRGB" in body or b"RGB " in body:
                icc_srgb = True
        pos += 2 + length
    result.update(width=width, height=height, rgb=True, alpha=False)
    result["srgb"] = True if not has_icc else icc_srgb
    if has_icc and not icc_srgb:
        result["warnings"].append(
            "JPEG ICC profile does not advertise sRGB; export sRGB")
    return _finalize(result)


def _validate_bmp(data, result):
    if not data.startswith(b"BM") or len(data) < 54:
        result["errors"].append("not a valid BMP header")
        return result
    header_size = struct.unpack("<I", data[14:18])[0]
    if header_size < 40:
        result["errors"].append("unsupported BMP header")
        return result
    width, height = struct.unpack("<ii", data[18:26])
    planes, bpp = struct.unpack("<HH", data[26:30])
    compression = struct.unpack("<I", data[30:34])[0]
    result.update(width=abs(width), height=abs(height))
    result["rgb"] = bpp == 24 and compression == 0
    result["alpha"] = bpp == 32
    result["srgb"] = None
    result["warnings"].append(
        "BMP has no sRGB tag; verify the export colour space is sRGB")
    if planes != 1 or compression != 0:
        result["errors"].append("BMP must be uncompressed BI_RGB")
    if bpp != 24:
        result["errors"].append("BMP must be 24-bit RGB (no alpha)")
    return _finalize(result)


def _validate_tga(data, result):
    if len(data) < 18:
        result["errors"].append("not a valid TGA header")
        return result
    image_type = data[2]
    width = struct.unpack("<H", data[12:14])[0]
    height = struct.unpack("<H", data[14:16])[0]
    bpp = data[16]
    descriptor = data[17]
    alpha_bits = descriptor & 0x0F
    result.update(width=width, height=height)
    result["rgb"] = image_type in (2, 10) and bpp == 24
    result["alpha"] = bpp == 32 or alpha_bits > 0
    result["srgb"] = None
    result["warnings"].append(
        "TGA has no sRGB tag; verify the export colour space is sRGB")
    if image_type not in (2, 10):
        result["errors"].append(
            "TGA must be uncompressed or RLE true-color (type 2 or 10)")
    if bpp != 24:
        result["errors"].append("TGA must be 24-bit RGB (no alpha)")
    if alpha_bits:
        result["errors"].append("TGA descriptor indicates alpha bits")
    return _finalize(result)


def validate_image(source):
    """Validate a background source file deterministically.

    ``source`` may be a path or raw bytes. The result always contains
    ``ok``, ``errors``, ``warnings``, and actionable notes.
    """
    try:
        data, path = _image_bytes(source)
    except Exception as exc:
        result = _result(source)
        result["errors"].append(f"cannot read image: {exc}")
        return result

    ext = path.suffix.lower() if path else ""
    if ext and ext not in SUPPORTED_EXTENSIONS:
        result = _result(path)
        result["errors"].append(
            f"unsupported extension {ext}; use JPG, PNG, TGA, or BMP")
        return result

    expected_format = {
        ".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG",
        ".tga": "TGA", ".bmp": "BMP",
    }.get(ext)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        result = _validate_png(data, _result(path, "PNG"))
    elif data.startswith(b"\xff\xd8"):
        result = _validate_jpeg(data, _result(path, "JPEG"))
    elif data.startswith(b"BM"):
        result = _validate_bmp(data, _result(path, "BMP"))
    elif len(data) >= 18 and data[2] in (2, 10):
        result = _validate_tga(data, _result(path, "TGA"))
    else:
        result = _result(path)
        result["errors"].append(
            "unrecognized image format; use JPG, PNG, TGA, or BMP")
    if expected_format and result["format"] != expected_format:
        result["errors"].append(
            f"extension {ext} does not match detected {result['format']} data")
        result["ok"] = False
    return result


def _title_case(text):
    return " ".join(
        word.capitalize() if word.islower() else word
        for word in str(text or "").strip().split()
    )


def build_creative_brief(theme, title=None):
    """Build a deterministic scene-design brief for an Avatar Background.

    The brief never adds movement, wearable-shape, sales, or revenue claims.
    Title suggestions preserve the supplied product identity.
    """
    theme = str(theme or "").strip() or "Original Scene"
    lowered = theme.lower()
    if "moon" in lowered or "night" in lowered or "star" in lowered:
        lighting = "cool moonlight with a soft key light and gentle rim"
        palette = "deep blues, silver, and muted violet"
        atmosphere = "quiet, nocturnal, and atmospheric"
    elif "neon" in lowered or "cyber" in lowered or "city" in lowered:
        lighting = "neon practicals with cyan/magenta rim light"
        palette = "magenta, cyan, and deep indigo"
        atmosphere = "electric, rain-slicked, and urban"
    elif "forest" in lowered or "garden" in lowered or "shrine" in lowered:
        lighting = "dappled natural light with warm lantern accents"
        palette = "moss green, warm amber, and stone grey"
        atmosphere = "serene, organic, and sheltered"
    elif "library" in lowered or "cozy" in lowered or "cabin" in lowered:
        lighting = "warm interior light with soft falloff"
        palette = "amber, brown, cream, and forest green"
        atmosphere = "intimate, calm, and inviting"
    elif "celestial" in lowered or "cloud" in lowered or "palace" in lowered:
        lighting = "soft celestial glow with a high key light"
        palette = "pearl white, pale gold, and sky blue"
        atmosphere = "airy, dreamlike, and spacious"
    else:
        lighting = "soft directional light with a clear focal hierarchy"
        palette = "balanced complementary colors with one accent hue"
        atmosphere = "coherent and readable at a glance"

    original = _title_case(title or theme)
    if "background" not in original.lower():
        primary_title = f"{original} Avatar Background"
    else:
        primary_title = original
    title_suggestions = [
        primary_title,
        f"{_title_case(theme)} Scene",
        f"{_title_case(theme)} Environment",
    ]
    description_suggestions = [
        f"An original {theme.lower()} scene designed as an avatar background.",
        "A clear focal scene with layered depth, a readable horizon, and "
        "space for the avatar in the centre and lower-middle.",
        f"Lighting: {lighting}. Palette: {palette}. Atmosphere: {atmosphere}.",
    ]
    return {
        "category": CATEGORY,
        "asset_type_id": ASSET_TYPE_ID,
        "source_theme": theme,
        "identity_preserved": bool(title),
        "environment_theme": theme,
        "composition": (
            "Place the primary scene focal point in the centre/lower-middle; "
            "keep the upper third readable for the avatar silhouette."),
        "lighting": lighting,
        "colour_palette": palette,
        "atmosphere": atmosphere,
        "avatar_placement": (
            "Leave a clear central/lower-middle zone for the avatar; avoid "
            "placing critical detail directly behind the avatar."),
        "ground_horizon": (
            "Establish a clear ground plane and horizon line; avoid ambiguous "
            "floating geometry near the edges."),
        "mobile_readability": (
            "Keep the focal subject large and high-contrast for narrow mobile "
            "crops."),
        "desktop_readability": (
            "Use layered depth and wide negative space for 16:9 desktop "
            "surfaces."),
        "title_suggestions": title_suggestions,
        "description_suggestions": description_suggestions,
        "image_requirements": {
            "width": EXPECTED_WIDTH,
            "height": EXPECTED_HEIGHT,
            "formats": sorted(SUPPORTED_FORMATS),
            "colour_space": "sRGB",
            "channels": "flattened RGB, no alpha",
            "edge_fade": "Roblox applies edge fading automatically",
            "preview": "local preview may not match final Roblox rendering",
        },
    }
