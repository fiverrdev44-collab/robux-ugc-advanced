"""Avatar Background (asset type 92) market research from observed catalog data.

No competitor sales, impressions, CTR, image-pixel analysis or search volume is
inferred. All ranking evidence derives from the items and item_history tables.
"""
from collections import Counter
from datetime import datetime, timezone
from math import isfinite
import re

ASSET_TYPE = 92
MAX_SCAN = 1500
THEME_PATTERNS = {
    "celestial / space": r"\\b(?:celestial|galaxy|space|cosmic|starry|nebula|planet|moon|stars?)\\b",
    "fantasy / magical": r"\\b(?:fantasy|magic|magical|enchanted|fairy|castle|wizard|dragon)\\b",
    "cozy / interiors": r"\\b(?:cozy|cosy|bedroom|library|room|cafe|home|fireplace)\\b",
    "city / cyber": r"\\b(?:cyber|neon|city|urban|street|nightlife|futuristic|scifi|sci.fi)\\b",
    "nature / landscapes": r"\\b(?:forest|nature|mountain|lake|ocean|beach|sunset|garden|river|waterfall)\\b",
    "gothic / dark": r"\\b(?:goth|gothic|dark|void|horror|haunted|graveyard|shadow)\\b",
    "cute / pastel": r"\\b(?:cute|kawaii|pastel|pink|soft|bunny|heart|plush)\\b",
    "anime / illustration": r"\\b(?:anime|manga|cartoon|illustrated|chibi|2d)\\b",
    "luxury / royal": r"\\b(?:luxury|golden|royal|palace|marble|diamond|rich)\\b",
    "minimal / abstract": r"\\b(?:minimal|simple|abstract|gradient|geometric|solid|plain)\\b",
}


def bounded_options(days=7, limit=12):
    return max(1, min(int(days), 30)), max(1, min(int(limit), 20))


def themes_for(title):
    text = str(title or "").lower()
    return [label for label, pattern in THEME_PATTERNS.items()
            if re.search(pattern, text)] or ["other / unclassified"]


def rank_items(items, observations, now=None, days=7):
    """Pure, deterministic classification; never equate favorites/age with growth.

    items: dicts with id,name,created_at,favorite_count,price,creator_name.
    observations: mapping id -> (first_at,last_at,first_favs,last_favs,n).
    """
    now = now or datetime.now(timezone.utc)
    result = []
    for raw in items:
        item = dict(raw)
        created = item.get("created_at")
        if isinstance(created, datetime):
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age = max((now - created).total_seconds() / 86400, 0.0)
        else:
            age = None
        if age is None or age > days + 0.01:
            continue
        iid = int(item["id"])
        favs = max(0, int(item.get("favorite_count") or 0))
        record = observations.get(iid)
        measured = False
        velocity = None
        delta = None
        observed_hours = None
        latest_age_hours = None
        if record:
            first_at, last_at, first_favs, last_favs, n = record
            if first_at and last_at and int(n or 0) >= 2:
                if first_at.tzinfo is None:
                    first_at = first_at.replace(tzinfo=timezone.utc)
                if last_at.tzinfo is None:
                    last_at = last_at.replace(tzinfo=timezone.utc)
                observed_hours = (last_at - first_at).total_seconds() / 3600
                latest_age_hours = (now - last_at).total_seconds() / 3600
                # Require at least six hours and a recent last observation.
                if observed_hours >= 6 and 0 <= latest_age_hours <= 48:
                    measured = True
                    delta = int(last_favs) - int(first_favs)
                    velocity = round(delta * 24 / observed_hours, 2)
                    favs = max(0, int(last_favs))
        age_proxy = round(favs / max(age or 0, 0.5), 2)
        label = ("MEASURED GROWTH" if measured and delta > 0 else
                 "MEASURED FLAT/DECLINE" if measured else
                 "AGE-ADJUSTED ONLY")
        result.append({
            "id": iid, "name": str(item.get("name") or "Untitled")[:80],
            "price": item.get("price"), "creator": str(item.get("creator_name") or "?")[:60],
            "favs": favs, "age_days": age, "age_proxy": age_proxy,
            "velocity": velocity, "delta": delta, "measured": measured,
            "label": label, "themes": themes_for(item.get("name")),
            "observed_hours": observed_hours,
        })
    result.sort(key=lambda x: (
        0 if x["measured"] and x["delta"] > 0 else 1 if x["measured"] else 2,
        -(x["velocity"] or 0) if x["measured"] else -x["age_proxy"],
        -x["favs"], x["id"]))
    return result


def query_backgrounds(cur, days=7, max_scan=MAX_SCAN):
    """Read-only; returns capped recent items, history, and true catalog coverage."""
    cur.execute("SELECT COUNT(*) FROM items WHERE asset_type_id = %s",
                (ASSET_TYPE,))
    total = int(cur.fetchone()[0] or 0)
    cur.execute("""
        SELECT COUNT(*) FROM items WHERE asset_type_id = %s
          AND created_at >= NOW() - make_interval(days => %s)
    """, (ASSET_TYPE, days))
    recent_count = int(cur.fetchone()[0] or 0)
    cur.execute("""
        SELECT id, name, created_at, favorite_count, price, creator_name
        FROM items
        WHERE asset_type_id = %s
          AND created_at >= NOW() - make_interval(days => %s)
        ORDER BY created_at DESC, id DESC LIMIT %s
    """, (ASSET_TYPE, days, max_scan))
    items = [
        dict(zip(("id", "name", "created_at", "favorite_count",
                  "price", "creator_name"), row))
        for row in cur.fetchall()
    ]
    observations = {}
    if items:
        ids = [x["id"] for x in items]
        cur.execute("""
            SELECT item_id, MIN(snapshot_at), MAX(snapshot_at),
                   (array_agg(favorite_count ORDER BY snapshot_at ASC))[1],
                   (array_agg(favorite_count ORDER BY snapshot_at DESC))[1],
                   COUNT(*)
            FROM item_history
            WHERE item_id = ANY(%s)
              AND snapshot_at >= NOW() - make_interval(days => %s)
              AND favorite_count IS NOT NULL
            GROUP BY item_id
        """, (ids, days))
        observations = {int(row[0]): tuple(row[1:]) for row in cur.fetchall()}
    return total, recent_count, items, observations


def build_report(cur, days=7, limit=12, now=None):
    days, limit = bounded_options(days, limit)
    total, recent_count, items, observations = query_backgrounds(cur, days)
    if not total:
        return (
            "🌌 **AVATAR BACKGROUNDS — NO VERIFIED CATALOG DATA**\n"
            "VANTA has 0 items with asset_type_id=92 in its database. "
            "Background discovery/API coverage must be verified first. "
            "I won't substitute hats, emotes, or title keyword matches.\n"
            "_No CTR, sales, or competitive trend is measurable yet._"
        )
    ranked = rank_items(items, observations, now=now, days=days)
    measured = [x for x in ranked if x["measured"]]
    rising = [x for x in measured if x["delta"] > 0]
    theme_counts = Counter(t for x in ranked for t in x["themes"]
                           if t != "other / unclassified")
    creator_counts = Counter(x["creator"] for x in ranked
                             if x["creator"] != "?")
    prices = sorted(float(x["price"]) for x in ranked
                    if x["price"] is not None and float(x["price"]) >= 0)
    capped = recent_count > len(items)
    confidence = ("INSUFFICIENT" if len(ranked) < 5 or len(measured) < 3
                  else "LIMITED" if len(measured) < 10 or capped else "OBSERVATIONAL")
    lines = [
        f"🌌 **BACKGROUND MARKET INTELLIGENCE — {days}D**",
        f"Asset type **92 ONLY** · catalog {total} · new {recent_count} · "
        f"sampled {len(ranked)}{' (CAPPED)' if capped else ''}",
        f"📈 Measured with >=6h snapshots: **{len(measured)}** · "
        f"growing: **{len(rising)}** · evidence: **{confidence}**",
        "_Measured growth is favorites gained per day between snapshots; "
        "age-adjusted favorites are NOT measured growth._",
        "",
        f"**Top {min(limit, len(ranked))} recent listings**",
    ]
    for i, x in enumerate(ranked[:limit], 1):
        if x["measured"]:
            signal = f"{x['velocity']:+.1f} ♥/day observed ({x['delta']:+} ♥)"
        else:
            signal = f"{x['age_proxy']:.1f} ♥/day since listing (proxy)"
        lines.append(
            f"{i}. **{x['name']}** — {x['favs']:,} ♥ · "
            f"{x['age_days']:.1f}d old · {signal}\n"
            f"   {', '.join(x['themes'])} · "
            f"[View item](https://www.roblox.com/catalog/{x['id']})"
        )
    lines += ["", "**Design and competition signals (TITLE-ONLY)**"]
    if theme_counts:
        lines.append("Observed themes: " + " · ".join(
            f"{key} ({v})" for key, v in theme_counts.most_common(6)))
    else:
        lines.append("Themes: insufficient title information.")
    if prices:
        lines.append(f"Sample price range: R$ {min(prices):g}–{max(prices):g}; "
                     f"median R$ {prices[len(prices)//2]:g}.")
    if creator_counts:
        lines.append("Creators with multiple sampled listings: " +
                     (", ".join(f"{k} ({v})" for k, v in creator_counts.most_common(3)
                                if v > 1) or "none in sample"))
    lines += [
        "", "**Creative interpretation**",
        "Use observed themes as research starting points; compare actual artwork, "
        "avatar silhouette visibility, mobile cropping, and originality before designing.",
        "_Titles do not reveal an image's composition. A visual review is NOT included. "
        "Roblox does not provide competitor impressions, clicks, conversion or sales "
        "here; this report cannot estimate or promise CTR._",
    ]
    if confidence == "INSUFFICIENT":
        lines.append("⚠️ Too few recent measured items for a defensible breakout "
                     "or underserved-niche claim. Collect further snapshots.")
    return "\n".join(lines)
