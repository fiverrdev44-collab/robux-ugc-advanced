"""
recovery_brain.py — Post-launch failure detection + intelligent keyword classification.

NEW in this version:
- classify_keyword_health() — weighs supply AND demand (never calls saturated "weak")
- compute_velocity() — favs/day from item age
- find_pivot_keywords() — finds low-supply/high-demand alternatives from smart_pipeline
- classify_competition_batch() — batch-classify keyword competition data
- All original functions preserved (detect_failure_mode, format_recovery_report, etc.)
"""
import os
import re
import time
import requests
from datetime import datetime, timezone


FAILURE_THRESHOLDS = {
    "discover_failure":   {"severity": "critical", "fixable": True,  "window_hours": 48},
    "ctr_failure":        {"severity": "high",     "fixable": True,  "window_hours": 120},
    "content_mismatch":   {"severity": "high",     "fixable": True,  "window_hours": 168},
    "price_failure":      {"severity": "medium",   "fixable": True,  "window_hours": 336},
    "velocity_failure":   {"severity": "medium",   "fixable": True,  "window_hours": 336},
    "age_failure":        {"severity": "high",     "fixable": False, "window_hours": 0},
}

RECOVERY_PROTOCOLS = {
    "discover_failure": {
        "step_1": "EDIT TITLE within 2 hours. Highest-search-volume token to FIRST position.",
        "step_2": "EDIT DESCRIPTION in same window. First 100 chars = primary keyword.",
        "step_3": "Do NOT change price yet.",
        "step_4": "Wait 48h. If favs still <10, escalate to ctr_failure.",
        "expected_result": "Freshness boost re-triggers. ~60% recovery if within 48h.",
        "do_not": "Do not re-upload. Roblox flags duplicates.",
    },
    "ctr_failure": {
        "step_1": "EDIT TITLE. Every token must be a real search term.",
        "step_2": "EDIT DESCRIPTION. Add 3-5 secondary keywords.",
        "step_3": "Do NOT change price.",
        "step_4": "Wait 72h. If still under winner_median*0.15, escalate.",
        "expected_result": "Search-rank re-evaluation. 40-60% favs lift.",
        "do_not": "Space edits 72h apart or boost dies.",
    },
    "content_mismatch": {
        "step_1": "EDIT DESCRIPTION only. First 2 sentences match what buyer sees.",
        "step_2": "Do NOT change title.",
        "step_3": "Wait 7 days.",
        "step_4": "If sales still <favs*0.02, escalate to price_failure.",
        "expected_result": "Sales-favs ratio climbs to 2-5% within a week.",
        "do_not": "Don't change price yet.",
    },
    "price_failure": {
        "step_1": "EDIT PRICE. Drop to category sweet spot.",
        "step_2": "EDIT DESCRIPTION in SAME edit. Add urgency copy.",
        "step_3": "Do NOT change title.",
        "step_4": "Wait 72h. If sales still 0, pivot audience.",
        "expected_result": "3-5% favs→sales conversion within 48h.",
        "do_not": "Don't drop below category floor.",
    },
    "velocity_failure": {
        "step_1": "Cross-promote: launch a SECOND item in same vibe cluster.",
        "step_2": "Related-items algorithm surfaces both together.",
        "step_3": "Do NOT edit the original.",
        "step_4": "If 14 days sales <50, kill.",
        "expected_result": "Both items lift 20-40% over 2 weeks.",
        "do_not": "Do not lower price.",
    },
    "age_failure": {
        "step_1": "KILL. Do not edit.",
        "step_2": "Launch a variant with different tokens.",
        "step_3": "Do NOT re-upload same asset.",
        "step_4": "Different vibe cluster.",
        "expected_result": "New item gets clean sample.",
        "do_not": "Don't waste time on age-failed items.",
    },
}

EDIT_RULES = [
    "Max 1 edit per 72h per item.",
    "Title edits > description edits in re-rank strength.",
    "Price edits throttled harder — max 1 per 7 days.",
    "Editing a ranking item RESETS velocity counter.",
    "Edits do NOT reset the 30-day age penalty.",
]

ESCALATION_LADDER = {
    "hour_0_48": "Edit title + description.",
    "hour_48_120": "If no lift: edit title again with different primary token.",
    "hour_120_336": "If still no lift: price drop + description urgency.",
    "hour_336_720": "If still no lift: launch cross-promo item.",
    "hour_720_plus": "KILL. Launch v2 with different tokens.",
}


# ============================================================
# 🧠 NEW — KEYWORD HEALTH CLASSIFICATION (SUPERCOMPUTER LAYER)
# ============================================================
def classify_keyword_health(comp_count, median_favs, median_age_days=None):
    """
    Classify a keyword using BOTH supply and demand (never supply alone).

    Returns (bucket, emoji, reasoning).

    Buckets:
      GOLD        — low supply, high demand
      OPPORTUNITY — moderate supply, high demand
      SATURATED   — high supply, high demand (NOT WEAK — high demand!)
      WEAK        — low supply, low demand
      DEAD        — essentially no demand
      NEUTRAL     — everything else
    """
    comp = comp_count or 0
    favs = median_favs or 0

    # Velocity note (informational)
    vel_note = ""
    if median_age_days and median_age_days > 0:
        vel = favs / median_age_days
        vel_note = f" (~{vel:.1f} favs/day)"

    if favs < 15:
        return ("DEAD", "🔴",
                f"Only {favs:,} median favs{vel_note} — no meaningful demand")
    if comp < 20 and favs >= 150:
        return ("GOLD", "🟢",
                f"Only {comp} competitors with {favs:,} median favs{vel_note} — rare opportunity")
    if comp < 50 and favs >= 80:
        return ("OPPORTUNITY", "🔵",
                f"{comp} competitors, {favs:,} median favs{vel_note} — strong entry point")
    if comp >= 50 and favs >= 80:
        return ("SATURATED", "🟡",
                f"{comp} competitors, {favs:,} median favs{vel_note} — HIGH DEMAND but saturated")
    if comp < 20 and favs < 50:
        return ("WEAK", "🟠",
                f"Only {comp} competitors but just {favs:,} median favs{vel_note} — low demand")
    return ("NEUTRAL", "⚪",
            f"{comp} competitors, {favs:,} median favs{vel_note}")


def compute_velocity(favs, age_days):
    """Favorites per day since creation. Returns float or 0."""
    if not age_days or age_days <= 0:
        return 0.0
    return (favs or 0) / age_days


def classify_competition_batch(competition_data):
    """
    Classify a list of competitor keyword entries.
    competition_data: list of dicts like
      [{"keyword": "spice", "comp": 59, "median_favs": 101, "median_price": 58}, ...]

    Returns:
      {
        "classifications": [
           {"keyword": ..., "bucket": ..., "emoji": ..., "reasoning": ..., "supply": ..., "median_favs": ...},
           ...
        ],
        "seed": <first entry classification or None>,
        "best_pivot": <best alternative (lowest supply with favs>=80)> or None,
      }
    """
    if not competition_data:
        return {"classifications": [], "seed": None, "best_pivot": None}

    classifications = []
    for d in competition_data:
        kw = d.get("keyword") or d.get("seed") or "?"
        comp = d.get("comp") or d.get("competitors") or 0
        favs = d.get("median_favs") or d.get("median") or 0
        age = d.get("median_age_days")
        bucket, emoji, reasoning = classify_keyword_health(comp, favs, age)
        classifications.append({
            "keyword": kw,
            "supply": comp,
            "median_favs": favs,
            "bucket": bucket,
            "emoji": emoji,
            "reasoning": reasoning,
        })

    seed = classifications[0] if classifications else None

    # Find best pivot: lowest supply with favs >= 80, and not the seed
    candidates = [c for c in classifications[1:]
                  if c["median_favs"] >= 80 and c["supply"] > 0]
    candidates.sort(key=lambda c: c["supply"])
    best_pivot = candidates[0] if candidates else None

    return {
        "classifications": classifications,
        "seed": seed,
        "best_pivot": best_pivot,
    }


def find_pivot_keywords(competition_data, min_median_favs=80, max_pivots=3):
    """
    Return up to max_pivots alternative keywords that beat the seed on
    supply-vs-demand tradeoff.

    Rules: pivot must have median_favs >= min_median_favs AND lower supply
    than the seed. Sorted by supply ascending.
    """
    if not competition_data or len(competition_data) < 2:
        return []
    seed = competition_data[0]
    seed_supply = seed.get("comp") or seed.get("competitors") or 9999

    candidates = []
    for d in competition_data[1:]:
        favs = d.get("median_favs") or d.get("median") or 0
        supply = d.get("comp") or d.get("competitors") or 9999
        if favs >= min_median_favs and supply < seed_supply:
            candidates.append({
                "keyword": d.get("keyword") or d.get("seed") or "?",
                "supply": supply,
                "median_favs": favs,
                "advantage": seed_supply - supply,
            })
    candidates.sort(key=lambda c: (-c["advantage"], c["supply"]))
    return candidates[:max_pivots]


def format_keyword_classifications(classification_result):
    """Render classify_competition_batch() output as Discord markdown."""
    if not classification_result:
        return "(no keyword data)"
    lines = []
    seed = classification_result.get("seed")
    if seed:
        lines.append(f"**SEED:** {seed['emoji']} `{seed['keyword']}` — "
                     f"**{seed['bucket']}** "
                     f"(supply={seed['supply']}, median_favs={seed['median_favs']})")
        lines.append(f"> {seed['reasoning']}")
        lines.append("")
    lines.append("**ALL KEYWORDS:**")
    for c in classification_result.get("classifications", []):
        lines.append(f"{c['emoji']} `{c['keyword']}` — {c['bucket']} "
                     f"· supply={c['supply']} · median_favs={c['median_favs']}")
    pivot = classification_result.get("best_pivot")
    if pivot:
        lines.append("")
        lines.append(f"**🎯 BEST PIVOT:** {pivot['emoji']} `{pivot['keyword']}` "
                     f"(supply={pivot['supply']}, median_favs={pivot['median_favs']})")
        lines.append(f"> {pivot['reasoning']}")
    return "\n".join(lines)


# ============================================================
# FAILURE DETECTION (unchanged logic)
# ============================================================
def detect_failure_mode(item_stats):
    favs = item_stats.get("favs", 0) or 0
    sales = item_stats.get("sales", 0) or 0
    age = item_stats.get("age_days", 0) or 0
    wm = item_stats.get("winner_median_favs", 1000) or 1000

    if age > 30 and favs < wm * 0.3:
        mode = "age_failure"
    elif favs < 10 and age <= 3 and sales == 0:
        mode = "discover_failure"
    elif favs < wm * 0.1 and age <= 7:
        mode = "ctr_failure"
    elif favs > 20 and sales < favs * 0.01:
        mode = "content_mismatch"
    elif favs > 100 and sales == 0:
        mode = "price_failure"
    elif 0 < sales < 10 and age > 3:
        mode = "velocity_failure"
    else:
        return {"failure_mode": "healthy", "severity": "none",
                "message": "Item is within expected range."}

    proto = RECOVERY_PROTOCOLS.get(mode, {})
    thr = FAILURE_THRESHOLDS.get(mode, {})
    return {
        "failure_mode": mode,
        "severity": thr.get("severity", "unknown"),
        "fixable": thr.get("fixable", False),
        "recovery_window_hours": thr.get("window_hours", 0),
        "protocol": proto,
        "edit_rules": EDIT_RULES,
        "escalation": ESCALATION_LADDER,
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }


def format_recovery_report(diagnosis, item_stats=None, show_sales=False):
    if not diagnosis:
        return "(no diagnosis)"
    mode = diagnosis.get("failure_mode")
    if mode == "healthy":
        return f"✅ **{diagnosis.get('message', 'Item is healthy.')}**"

    lines = [f"# 🚨 FAILURE AUTOPSY — `{mode.upper()}`",
             f"**Severity:** {diagnosis.get('severity','?').upper()}",
             f"**Fixable:** {'YES' if diagnosis.get('fixable') else 'NO — kill it'}",
             f"**Recovery window:** {diagnosis.get('recovery_window_hours',0)} hours",
             ""]

    if item_stats:
        lines.append("**Detected stats:**")
        lines.append(f"- Favs: {item_stats.get('favs', 0):,}")
        if show_sales:
            lines.append(f"- Sales: {item_stats.get('sales', 0):,}")
        lines.append(f"- Price: R${item_stats.get('price', 0)}")
        lines.append(f"- Age: {item_stats.get('age_days', 0):.1f} days")
        lines.append(f"- Winner median in niche: {item_stats.get('winner_median_favs',0):,} favs")
        lines.append("")

    proto = diagnosis.get("protocol", {})
    if proto:
        lines.append("## 🛠️ RECOVERY PROTOCOL")
        for key in ("step_1", "step_2", "step_3", "step_4"):
            if proto.get(key):
                lines.append(f"**{key.upper()}:** {proto[key]}")
        lines.append("")
        if proto.get("expected_result"):
            lines.append(f"**📊 Expected result:** {proto['expected_result']}")
            lines.append("")
        if proto.get("do_not"):
            lines.append(f"**🚫 DO NOT:** {proto['do_not']}")
            lines.append("")

    if diagnosis.get("edit_rules"):
        lines.append("## ⏱️ EDIT THROTTLE RULES")
        for r in diagnosis["edit_rules"][:4]:
            lines.append(f"- {r}")
        lines.append("")

    if diagnosis.get("escalation"):
        lines.append("## 🪜 ESCALATION LADDER")
        for k, v in diagnosis["escalation"].items():
            lines.append(f"- **{k.replace('_', ' ')}:** {v}")

    return "\n".join(lines)


# ============================================================
# SALES & LIVE FETCH (unchanged)
# ============================================================
def fetch_user_sales(cookie, user_id, max_pages=3):
    if not cookie or not user_id:
        return []
    url = (f"https://economy.roblox.com/v2/users/{user_id}/transactions"
           f"?transactionType=Sale&limit=100")
    headers = {"Cookie": f".ROBLOSECURITY={cookie}",
               "User-Agent": "Mozilla/5.0",
               "Accept": "application/json"}
    all_sales, cursor = [], ""
    for _ in range(max_pages):
        request_url = f"{url}&cursor={cursor}" if cursor else url
        try:
            resp = requests.get(request_url, headers=headers, timeout=10)
            if resp.status_code != 200:
                break
            data = resp.json()
            all_sales.extend(data.get("data", []))
            cursor = data.get("nextPageCursor")
            if not cursor:
                break
        except Exception:
            break
        time.sleep(1.6)
    return all_sales


def enrich_item_stats_with_sales(item_stats, sales_list):
    item_id = item_stats.get("id")
    price = item_stats.get("price", 0)
    count = len([s for s in sales_list if s.get("id") == item_id]) if sales_list else 0
    item_stats["sales"] = count
    item_stats["_has_sales_data"] = True
    return item_stats


def fetch_item_from_roblox(item_id, cookie=None):
    if not item_id:
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    if cookie:
        headers["Cookie"] = f".ROBLOSECURITY={cookie}"

    details_url = f"https://economy.roblox.com/v2/assets/{item_id}/details"
    fav_url = (f"https://catalog.roblox.com/v1/catalog/items/"
               f"{item_id}/details?itemType=Asset")

    try:
        r1 = requests.get(details_url, headers=headers, timeout=10)
        if r1.status_code != 200:
            print(f"[live-fetch] details failed: HTTP {r1.status_code}", flush=True)
            return None
        d = r1.json()
    except Exception as e:
        print(f"[live-fetch] details exception: {e}", flush=True)
        return None

    favs = 0
    try:
        r2 = requests.get(fav_url, headers=headers, timeout=10)
        if r2.status_code == 200:
            favs = r2.json().get("favoriteCount") or 0
    except Exception as e:
        print(f"[live-fetch] favs exception: {e}", flush=True)

    creator_obj = d.get("Creator") or {}
    creator_name = creator_obj.get("Name") if isinstance(creator_obj, dict) else None

    return {
        "id": int(item_id),
        "name": (d.get("Name") or "")[:500],
        "description": (d.get("Description") or "")[:5000],
        "price": d.get("PriceInRobux") or 0,
        "favorite_count": favs,
        "total_sales": d.get("Sales") or 0,
        "creator_name": (creator_name or "")[:200],
        "asset_type_id": d.get("AssetTypeId") or 0,
    }


def save_item_to_db(cur, item):
    if not item:
        return False
    try:
        cur.execute("""
            INSERT INTO items (id, name, favorite_count, price, total_sales,
                               description, creator_name, asset_type_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                favorite_count = EXCLUDED.favorite_count,
                total_sales = EXCLUDED.total_sales,
                price = EXCLUDED.price,
                description = EXCLUDED.description,
                name = EXCLUDED.name,
                asset_type_id = EXCLUDED.asset_type_id,
                fetched_at = CURRENT_TIMESTAMP
        """, (
            item["id"], item["name"], item["favorite_count"],
            item["price"], item["total_sales"], item["description"],
            item["creator_name"], item["asset_type_id"],
        ))
        return True
    except Exception as e:
        print(f"[save-item] {e}", flush=True)
        return False


def save_item_and_created_at(cur, item, item_id):
    try:
        url = f"https://www.roblox.com/marketplace/productinfo?assetId={item_id}"
        r = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        })
        if r.status_code == 200:
            data = r.json()
            created_str = data.get("Created")
            if created_str:
                cur.execute(
                    "UPDATE items SET created_at = %s WHERE id = %s",
                    (created_str, item_id)
                )
    except Exception as e:
        print(f"[created-at] {e}", flush=True)


def fetch_created_date_live(item_id, cookie=None):
    if not item_id:
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    if cookie:
        headers["Cookie"] = f".ROBLOSECURITY={cookie}"
    try:
        url = f"https://economy.roblox.com/v2/assets/{item_id}/details"
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        created_raw = data.get("Created")
        if not created_raw:
            return None
        created_str = created_raw.replace("Z", "").split(".")[0]
        return datetime.fromisoformat(created_str)
    except Exception:
        return None
