"""Category-specific read-only creator pattern research.

Relearn from currently stored catalog observations on each invocation. This
does not train an ML model, determine Roblox search weights, or infer sales.
"""
import re
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median

_STOP = {
    "the", "and", "for", "with", "from", "your", "you", "roblox", "ugc",
    "avatar", "background", "backgrounds", "emote", "emotes", "dance",
    "animation", "accessory", "hair", "hat", "shirt", "pants", "clothing",
    "new", "free", "limited", "viral", "trending", "official", "best",
    "scene", "image", "picture", "photo", "style", "cute", "cool",
    "fnaf", "freddy", "fazbear", "disney", "marvel", "minecraft", "pokemon",
    "sonic", "oggy", "tiktok", "youtube",
}
_SAMPLE_LIMIT = 1400
_HISTORY_ITEMS = 200
_HISTORY_LIMIT = 1200


def _tokens(name):
    return [w for w in re.findall(r"[a-z0-9]+", str(name or "").lower())
            if len(w) >= 3 and w not in _STOP]


def _date(value):
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _safe_name(value):
    name = re.sub(r"[\r\n@<>"+chr(96)+r"]", " ", str(value or ""))
    name = " ".join(name.split())[:50]
    return name if name and "ignore instructions" not in name.lower() else "(unnamed)"


def _growth(rows, ids):
    snapshots = defaultdict(dict)
    for row in list(rows or [])[:_HISTORY_LIMIT]:
        try:
            item_id, fav, stamp = int(row[0]), int(row[1]), _date(row[2])
        except (IndexError, TypeError, ValueError):
            continue
        if item_id in ids and fav >= 0 and stamp:
            snapshots[item_id][stamp] = fav
    out = {}
    for item_id, points in snapshots.items():
        ordered = sorted(points.items())
        if len(ordered) >= 2:
            days = (ordered[-1][0] - ordered[0][0]).total_seconds() / 86400
            if days >= .5:
                change = ordered[-1][1] - ordered[0][1]
                out[item_id] = (change, change / days, ordered[-1][0])
    return out


def _recurring_terms(creators):
    members = defaultdict(lambda: {"creators": set(), "items": set()})
    for ctype, cid, products in creators:
        for product in products:
            for term in set(_tokens(product["name"])):
                members[term]["creators"].add((ctype, cid))
                members[term]["items"].add(product["id"])
    patterns = [
        {"term": term, "creators": len(stats["creators"]), "items": len(stats["items"])}
        for term, stats in members.items()
        if len(stats["creators"]) >= 2 and len(stats["items"]) >= 3
    ]
    patterns.sort(key=lambda pattern: (-pattern["creators"], -pattern["items"], pattern["term"]))
    return patterns[:6]


def learn_from_rows(rows, family, history_rows=(), min_items=2, now=None):
    """Pure computation; never conflate similarly named User/Group creators."""
    now = _date(now) or datetime.now(timezone.utc)
    by_creator = defaultdict(list)
    observed = set()
    for row in list(rows or [])[:_SAMPLE_LIMIT]:
        try:
            item_id, name = int(row[0]), str(row[1] or "")[:100]
            ctype, cid = row[2], int(row[3])
            favorite = int(row[6]) if row[6] is not None else None
        except (IndexError, TypeError, ValueError):
            continue
        if item_id <= 0 or item_id in observed:
            continue
        observed.add(item_id)
        if not name or ctype not in ("User", "Group") or cid <= 0:
            continue
        by_creator[(ctype, cid)].append({
            "id": item_id, "name": name,
            "favorite": favorite, "display": _safe_name(row[4]),
            "created": _date(row[8]) if len(row) > 8 else None,
            "badge": row[5] if isinstance(row[5], bool) else None,
        })
    eligible = []
    for (ctype, cid), products in by_creator.items():
        measured = [p["favorite"] for p in products
                    if p["favorite"] is not None and p["favorite"] >= 0]
        if len(products) < min_items or len(measured) < min_items:
            continue
        eligible.append({
            "type": ctype, "id": cid,
            "name": products[0]["display"], "items": products,
            "median": median(measured),
            "badge": (True if any(p["badge"] is True for p in products) else
                      False if all(p["badge"] is False for p in products) else None),
        })
    eligible.sort(key=lambda x: (-x["median"], -len(x["items"]),
                                 x["type"], x["id"]))
    changes = _growth(history_rows, observed)
    info = {
        "family": family, "status": "insufficient",
        "confidence": "insufficient", "sample_items": len(observed),
        "sample_capped": len(rows or []) >= _SAMPLE_LIMIT,
        "eligible_creators": len(eligible),
        "measured_items": len(changes),
        "measured_positive": sum(change[0] > 0 for change in changes.values()),
        "leaders": [], "patterns": [],
        "emerging_leaders": [], "emerging_patterns": [],
        "top_median_favorites": None,
        "comparison_median_favorites": None,
        "causal": False, "sales_verified": False,
    }
    rising = []
    for (ctype, cid), products in by_creator.items():
        measured = [
            p for p in products
            if p["created"] and 0 <= (now - p["created"]).days < 60
            and p["id"] in changes
            and 0 <= (now - changes[p["id"]][2]).days < 7
        ]
        gaining = [p for p in measured if changes[p["id"]][0] > 0]
        if len(gaining) >= min_items and len(gaining) * 2 > len(measured):
            rising.append((median(changes[p["id"]][1] for p in measured),
                           ctype, cid, gaining))
    rising.sort(key=lambda row: (-row[0], row[1], row[2]))
    info["emerging_leaders"] = [
        {"name": products[0]["display"], "type": ctype, "id": cid,
         "items": len(products), "median_favorites_per_day": round(rate, 2)}
        for rate, ctype, cid, products in rising[:3]
    ]
    info["emerging_patterns"] = _recurring_terms(
        (ctype, cid, products) for _, ctype, cid, products in rising)
    if len(eligible) < 4:
        return info
    n_top = max(2, len(eligible) // 3)
    top, comparison = eligible[:n_top], eligible[n_top:]
    if len(comparison) < 2:
        return info
    info["top_median_favorites"] = round(median(x["median"] for x in top), 1)
    info["comparison_median_favorites"] = round(median(x["median"] for x in comparison), 1)
    info["leaders"] = [
        {"name": x["name"], "type": x["type"], "id": x["id"],
         "item_count": len(x["items"]), "median_favorites": round(x["median"], 1),
         "badge": x["badge"],
         "measured_positive": sum(p["id"] in changes and changes[p["id"]][0] > 0 for p in x["items"])}
        for x in top[:3]
    ]
    info["patterns"] = _recurring_terms(
        (creator["type"], creator["id"], creator["items"]) for creator in top)
    info["status"] = "observed"
    info["confidence"] = (
        "moderate" if len(eligible) >= 6 and len(observed) >= 24 else "limited")
    return info


def learn_category_creators(cur, family):
    """Read up to 1400 same-type catalog rows and limited 30d history."""
    from category_configs import get_category_config, resolve_family_name
    family = resolve_family_name(family)
    ids = [] if family == "generic" else (
        get_category_config(family).get("asset_type_ids") or [])
    if not ids:
        return {"family": family, "status": "insufficient",
                "confidence": "insufficient", "leaders": [], "patterns": []}
    cur.execute("""
        SELECT id, name, creator_type, creator_id, creator_name,
               creator_verified, favorite_count, price, created_at
        FROM items
        WHERE asset_type_id = ANY(%s)
          AND created_at >= NOW() - INTERVAL '540 days'
        ORDER BY created_at DESC NULLS LAST, id DESC
        LIMIT %s
    """, (list(ids), _SAMPLE_LIMIT))
    rows = cur.fetchall() or []
    history_ids = []
    for row in rows[:_HISTORY_ITEMS]:
        try:
            item_id = int(row[0])
        except (ValueError, TypeError, IndexError):
            continue
        if item_id > 0:
            history_ids.append(item_id)
    history = []
    if history_ids:
        cur.execute("""
            WITH ranked AS (
                SELECT item_id, favorite_count, snapshot_at,
                       row_number() OVER (PARTITION BY item_id ORDER BY snapshot_at ASC) AS first_rank,
                       row_number() OVER (PARTITION BY item_id ORDER BY snapshot_at DESC) AS last_rank
                FROM item_history
                WHERE item_id = ANY(%s)
                  AND snapshot_at >= NOW() - INTERVAL '30 days'
                  AND favorite_count IS NOT NULL
            )
            SELECT item_id, favorite_count, snapshot_at
            FROM ranked
            WHERE first_rank = 1 OR last_rank = 1
            ORDER BY item_id, snapshot_at
            LIMIT %s
        """, (history_ids, _HISTORY_LIMIT))
        history = cur.fetchall() or []
    return learn_from_rows(rows, family, history)


def lookup_creator_learning(family, db_factory=None):
    """Self-refreshes from the existing DB; fails soft; never writes."""
    if db_factory is None:
        from bot_core import get_db
        db_factory = get_db
    try:
        conn = db_factory()
        try:
            cur = conn.cursor()
            try:
                return learn_category_creators(cur, family)
            finally:
                cur.close()
        finally:
            conn.close()
    except Exception as exc:
        print("[category-creator-learning] " + type(exc).__name__, flush=True)
        return {"family": family, "status": "unavailable",
                "confidence": "unavailable", "leaders": [],
                "patterns": [], "reason": type(exc).__name__}


def emerging_title_terms(evidence, source):
    """Independent, recent creator patterns that are also present in the brief."""
    terms = set(_tokens(source))
    return [pattern for pattern in (evidence or {}).get("emerging_patterns", [])
            if pattern["term"] in terms][:3]


def format_emerging_creators(evidence, source=""):
    """Report an action with its observation and keep missing coverage explicit."""
    leaders = (evidence or {}).get("emerging_leaders") or []
    if not leaders:
        return ""
    leaders_text = ", ".join(
        f"{row['name']} ({row['type']}, {row['items']} gaining listings, "
        f"median +{row['median_favorites_per_day']:g} favorites/day)"
        for row in leaders
    )
    lines = ["**Who’s gaining ground in the sample**", leaders_text]
    patterns = (emerging_title_terms(evidence, source) if source else
                (evidence.get("emerging_patterns") or [])[:3])
    if patterns:
        examples = ", ".join(f"{p['term']} ({p['creators']} creators)" for p in patterns)
        lines.append(f"Recurring wording to test where it fits your item: {examples}.")
    lines.append("Growth comes from catalog favorite snapshots. Sales impact is unknown.")
    return "\n".join(lines)


def title_pattern_bonus(title, vision, evidence):
    """Minor observed cross-creator tie-breaker, not a rank/CTR prediction."""
    if not isinstance(evidence, dict):
        return 0
    from background_review import _source_words, _words
    title_words = _words(title)
    visible_words = _source_words(vision, "")
    recent = sum(p["term"] in title_words for p in
                 emerging_title_terms(evidence, " ".join(visible_words)))
    if recent:
        return min(6, recent * 3)
    if evidence.get("status") != "observed" or evidence.get("eligible_creators", 0) < 4:
        return 0
    qualified = [
        p for p in evidence.get("patterns", [])
        if p.get("creators", 0) >= 2 and p.get("term") in title_words
        and p.get("term") in visible_words
    ]
    return min(6, len(qualified) * 2)


def format_creator_learning(finding):
    f = finding if isinstance(finding, dict) else {}
    lines = [
        "## CATEGORY CREATOR PATTERN STUDY",
        "_Same-family catalog creators with known User/Group identity. "
        "Favorites are not sales; this is not a ranking algorithm._",
    ]
    emerging = format_emerging_creators(f)
    if emerging:
        lines.append(emerging)
    if f.get("status") != "observed":
        lines.append("• " + ("Creator evidence unavailable" if f.get("status") == "unavailable"
                            else "Too few repeat creators in the stored sample") +
                     "; no reliable winning title pattern inferred.")
        return "\n".join(lines)
    lines.append("• " + str(f.get("sample_items", 0)) +
                 " sampled category items · " + str(f["eligible_creators"]) +
                 " repeat creators · evidence: " + f["confidence"])
    for creator in f.get("leaders", [])[:3]:
        lines.append("• " + creator["name"] + " (" + creator["type"] + ", " +
                     str(creator["item_count"]) + " items, median " +
                     str(creator["median_favorites"]) + " favorites)" +
                     (" · verified badge observed" if creator["badge"] is True else ""))
    if f.get("patterns"):
        lines.append("• Words repeated across different top creators: " +
                     ", ".join(x["term"] + " (" + str(x["creators"]) + " creators)"
                               for x in f["patterns"][:4]))
    else:
        lines.append("• No cross-creator recurring title terms confirmed.")
    lines.append("• Measured 30d favorite growth: " +
                 str(f.get("measured_positive", 0)) + " positive / " +
                 str(f.get("measured_items", 0)) + " with usable snapshots.")
    lines.append("• Biased recent sample; creator reach, listing age and marketing "
                 "may explain differences. Do not copy individual titles.")
    return "\n".join(lines)
