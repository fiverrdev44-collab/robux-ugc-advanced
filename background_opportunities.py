"""Bounded AssetType 92 opportunity evidence for Avatar Background artwork.

Descriptive listing supply and *measured* favorites changes only. This module
does not estimate sales, search impressions, organic CTR or conversion.
Existing DB connection only; no extra Roblox HTTP calls or database writes.
"""
import re
from datetime import datetime, timezone
from statistics import median

from background_intelligence import observations, scene_phrase, _short_text, _is_untrusted_instruction

_MAX_LISTINGS = 160
_MAX_HISTORY = 500
_NOISE = {
    "a", "an", "and", "are", "at", "background", "avatar", "ugc", "roblox",
    "the", "with", "that", "this", "through", "behind", "inside", "against",
    "from", "into", "peeking", "looking", "under", "over", "scene", "photo",
    "image", "left", "right", "top", "bottom", "dark", "horror",
    "made", "source", "filmmaker", "photopea", "style", "render",
}


def _tokens(text):
    return [t for t in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if len(t) >= 3 and t not in _NOISE]


def scene_angles(vision, notes="", max_angles=6):
    """Use the creator's identified scene plus observed features; never invent."""
    o = observations(vision)
    anchor = scene_phrase(vision, notes)
    # Prefer an explicit descriptive location pair (e.g., security office),
    # rather than a fragment such as "blue security" from creator notes.
    sources = [str(notes or "")[:320], o["search_description"],
               o["visual_summary"]]
    location = None
    for source in sources:
        if _is_untrusted_instruction(source):
            continue
        match = re.search(
            r"\b([a-z]{3,20}\s+(?:office|room|hallway|corridor|forest|"
            r"street|garden|beach|shrine|castle|station))\b",
            source.lower())
        if match:
            location = match.group(1)
            break
    seeds = [location] if location else []
    if anchor and anchor != location:
        seeds.append(anchor)
    for detail in o["distinctive_features"][:4]:
        if detail and not _is_untrusted_instruction(detail):
            words = _tokens(detail)
            if len(words) >= 2:
                seeds.append(" ".join(words[:2]))
    creator = str(notes or "")[:320].lower()
    # A franchise is a creator-identified search angle, not permission to use IP.
    if re.search(r"\bfnaf\b|five nights at freddy", creator) and anchor:
        seeds.append("fnaf " + anchor)
    if len(seeds) < 2 and o["search_description"]:
        words = _tokens(o["search_description"])
        if len(words) >= 2:
            seeds.append(" ".join(words[:2]))
    out, seen = [], set()
    for seed in seeds:
        phrase = " ".join(_tokens(_short_text(seed, 70))[:3])
        if len(phrase.split()) < 2 or phrase in seen:
            continue
        seen.add(phrase)
        out.append(phrase)
        if len(out) >= max(1, min(max_angles, 8)):
            break
    return out


def _date(value):
    if value is None or not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _history_gains(rows):
    """First/last valid observations >=12h apart; never lifetime favs/age."""
    groups = {}
    for raw in rows[:_MAX_HISTORY]:
        try:
            ident, favs, dt = int(raw[0]), int(raw[1]), _date(raw[2])
        except (IndexError, TypeError, ValueError):
            continue
        if dt is not None and favs >= 0:
            groups.setdefault(ident, []).append((dt, favs))
    gains = {}
    for ident, pairs in groups.items():
        pairs.sort(key=lambda p: p[0])
        distinct = []
        for p in pairs:
            if not distinct or p[0] != distinct[-1][0]:
                distinct.append(p)
            else:
                distinct[-1] = p
        if len(distinct) < 2:
            continue
        days = (distinct[-1][0] - distinct[0][0]).total_seconds() / 86400
        if days < 0.5:
            continue
        gains[ident] = {
            "observations": len(distinct), "days": round(days, 2),
            "favorite_delta": distinct[-1][1] - distinct[0][1],
            "favorites_per_day": round((distinct[-1][1] - distinct[0][1]) / days, 2),
        }
    return gains


def analyze_stored_backgrounds(cur, vision, notes="", now=None):
    """Two bounded parameterized SELECTs, strictly AssetType 92.

    A zero match in this non-exhaustive sample is UNKNOWN, never a proven gap.
    """
    angles = scene_angles(vision, notes)
    if not angles:
        return {"status": "insufficient_scene", "angles": [], "rows_scanned": 0}
    query_tokens = []
    for angle in angles:
        for token in _tokens(angle):
            if token not in query_tokens:
                query_tokens.append(token)
    patterns = ["%" + t + "%" for t in query_tokens[:9]]
    cur.execute("""
        SELECT id, name, favorite_count, price, created_at
        FROM items
        WHERE asset_type_id = 92 AND LOWER(name) LIKE ANY(%s)
        ORDER BY favorite_count DESC NULLS LAST, id DESC
        LIMIT %s
    """, (patterns, _MAX_LISTINGS))
    raw_items = cur.fetchall() or []
    items = []
    for raw in raw_items:
        try:
            ident = int(raw[0])
        except (ValueError, TypeError, IndexError):
            continue
        name = _short_text(raw[1], 90)
        if not name or _is_untrusted_instruction(name):
            continue
        try:
            fav = max(0, int(raw[2] or 0))
        except (ValueError, TypeError):
            fav = 0
        try:
            price = max(0, int(raw[3] or 0))
        except (ValueError, TypeError):
            price = 0
        items.append({"id": ident, "name": name, "favorites": fav,
                      "price": price, "created": _date(raw[4]),
                      "terms": set(_tokens(name))})
    changes = {}
    # Only inspect known AssetType 92 IDs from the bounded first query.
    if items:
        cur.execute("""
            SELECT item_id, favorite_count, snapshot_at
            FROM item_history
            WHERE item_id = ANY(%s)
              AND favorite_count IS NOT NULL
              AND snapshot_at >= NOW() - INTERVAL '14 days'
            ORDER BY item_id, snapshot_at
            LIMIT %s
        """, ([x["id"] for x in items], _MAX_HISTORY))
        changes = _history_gains(cur.fetchall() or [])
    now = now or datetime.now(timezone.utc)
    results, related_ids = [], set()
    for phrase in angles:
        words = set(_tokens(phrase))
        matches = [it for it in items if words.issubset(it["terms"])]
        related_ids.update(it["id"] for it in matches)
        recent = sum(1 for it in matches if it["created"]
                     and 0 <= (now - it["created"]).days <= 30)
        gains = [changes[it["id"]]["favorite_delta"] for it in matches
                 if it["id"] in changes]
        movers = sum(1 for gain in gains if gain > 0)
        count = len(matches)
        results.append({
            "phrase": phrase, "sample_matches": count,
            "recent_30d": recent, "measured_items": len(gains),
            "measured_positive": movers,
            "median_favorites": round(median(it["favorites"] for it in matches))
                                if matches else None,
            "sample_status": (
                "no_match_not_proven_gap" if count == 0 else
                "busy_in_sample" if count >= 10 else
                "active_favorite_sample" if movers else
                "listed_no_measured_growth"),
        })
    related = [
        {"name": it["name"], "favorites": it["favorites"],
         "price": it["price"], "measured": changes.get(it["id"])}
        for it in items if it["id"] in related_ids
    ][:5]
    return {
        "status": "ok", "family": "backgrounds", "asset_type_id": 92,
        "rows_scanned": len(items), "capped": len(raw_items) >= _MAX_LISTINGS,
        "history_capped": len(changes) >= _MAX_HISTORY,
        "angles": results, "related": related,
        "scope": "bounded, incomplete stored titles; no sales/CTR verification",
    }


def lookup_background_opportunities(vision, notes="", db_factory=None):
    """Fail-soft wrapper for the existing bot Postgres connection."""
    if db_factory is None:
        from bot_core import get_db
        db_factory = get_db
    try:
        conn = db_factory()
        try:
            cur = conn.cursor()
            try:
                return analyze_stored_backgrounds(cur, vision, notes)
            finally:
                cur.close()
        finally:
            conn.close()
    except Exception as exc:
        print("[background-opportunities] " + type(exc).__name__, flush=True)
        return {"status": "unavailable", "reason": type(exc).__name__,
                "rows_scanned": 0, "angles": []}


def format_opportunity_evidence(market, limit=5):
    """Discord-safe evidence block; no 'high CTR' or fake validation."""
    m = market if isinstance(market, dict) else {}
    status = m.get("status")
    lines = ["## 🔎 BACKGROUND OPPORTUNITY RESEARCH",
             "_Same-category AssetType 92 stored listings; descriptive research, "
             "not verified customer demand or organic CTR._"]
    if status != "ok":
        lines.append("• Stored background evidence " +
                     ("insufficient" if status == "insufficient_scene"
                      else "unavailable") + "; no gap asserted.")
        return "\n".join(lines)
    lines.append("• Scanned " + str(m.get("rows_scanned", 0)) +
                 " matching stored titles (bounded" +
                 (", capped" if m.get("capped") else "") + ").")
    for x in m.get("angles", [])[:limit]:
        count = x["sample_matches"]
        if count == 0:
            verdict = "not found in sample; demand unknown"
        elif x["sample_status"] == "busy_in_sample":
            verdict = "many listed; look for visual differentiation"
        elif x["measured_positive"]:
            verdict = "measured favorite growth on " + str(x["measured_positive"]) + " items"
        else:
            verdict = "listed; repeat demand not established"
        lines.append("• " + x["phrase"] + ": " + str(count) +
                     " matching title(s), " + str(x["recent_30d"]) +
                     " recent; " + verdict)
    lines.append("• This is a LIMITED title sample, not a complete catalog "
                 "or sales dataset. Empty phrases are exploratory, not validated gaps.")
    lines.append("• Choose a visible, relatively distinct hook alongside a "
                 "recognizable scene anchor; validate the name and rights.")
    return "\n".join(lines)
