"""
convergence_live.py — Stage B of the convergence pipeline.

Read-only live Roblox marketplace verification for a bounded shortlist of niche
keywords. Reuses live_market's catalog search endpoint and its Retry-After-aware
GET helper. No database writes, no account-changing requests, no broad rescans.

Each result records: sampled result count (and whether it was capped), how many
results are in the correct asset category, exact-title vs conceptual matches,
top competitors (name/favorites/price/asset type/creator), and a verification
timestamp.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from live_market import SEARCH_URL, _get_with_backoff
from convergence_engine import FAMILIES

# Accessory covers the five sub-types; the engine aggregates them.
_EXPECTED_ASSET_TYPES = dict(FAMILIES)
_EXPECTED_ASSET_TYPES["accessory"] = [43, 44, 45, 46, 47]

CACHE_TTL_SECONDS = 300
_CACHE = {}
_CACHE_LOCK = threading.Lock()

# Circuit breaker: short cooldown after a 429/5xx so a burst of failures stops
# issuing requests instead of hammering the endpoint.
CIRCUIT_BREAK_COOLDOWN = 30.0
_CIRCUIT = {"open_until": 0.0}
_CIRCUIT_LOCK = threading.Lock()


def _circuit_open():
    with _CIRCUIT_LOCK:
        return time.time() < _CIRCUIT["open_until"]


def _trip_circuit(seconds=None):
    seconds = max(1.0, float(seconds or CIRCUIT_BREAK_COOLDOWN))
    with _CIRCUIT_LOCK:
        _CIRCUIT["open_until"] = max(_CIRCUIT["open_until"], time.time() + seconds)


def _reset_circuit():
    with _CIRCUIT_LOCK:
        _CIRCUIT["open_until"] = 0.0


def _expected_asset_types(family):
    if not family or family == "all":
        return None
    return _EXPECTED_ASSET_TYPES.get(str(family).lower())


def _tokens(text):
    stop = {"the", "and", "for", "with", "your", "you", "a", "an", "of", "in",
            "on", "to", "my", "is", "it", "as", "at", "by", "emote", "dance",
            "animation", "hat", "hair", "item", "ugc", "pose", "style"}
    import re
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in stop and len(w) >= 3]


def _cache_get(key):
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry and (time.time() - entry["ts"]) <= CACHE_TTL_SECONDS:
            return entry["value"]
    return None


def _cache_put(key, value):
    with _CACHE_LOCK:
        _CACHE[key] = {"ts": time.time(), "value": value}


def clear_cache():
    with _CACHE_LOCK:
        _CACHE.clear()


def verify_niche(keyword, family=None, limit=30, max_pages=2, timeout=12,
                 use_cache=True):
    """Read-only live search for one niche keyword. Returns a sanitized dict."""
    keyword = (keyword or "").strip()
    if not keyword:
        return {"ok": False, "error": "empty keyword", "keyword": keyword}

    cache_key = (str(family).lower(), keyword.lower())
    if use_cache:
        cached = _cache_get(cache_key)
        if cached is not None:
            cached = dict(cached)
            cached["cached"] = True
            return cached

    if _circuit_open():
        return {"ok": False, "error": "circuit open (rate limited)",
                "keyword": keyword, "cached": False}

    expected = _expected_asset_types(family)
    rows, pages, cursor = [], 0, None
    try:
        while pages < max_pages:
            params = {"Keyword": keyword, "Limit": limit,
                      "SortType": "Relevance"}
            if cursor:
                params["Cursor"] = cursor
            r = _get_with_backoff(SEARCH_URL, params, max_attempts=2,
                                  timeout=timeout)
            pages += 1
            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")
                _trip_circuit(retry_after)
                if rows:
                    break
                return {"ok": False, "error": "rate limited (429)",
                        "retry_after": retry_after,
                        "keyword": keyword, "cached": False}
            if r.status_code >= 500:
                _trip_circuit()
                if rows:
                    break
                return {"ok": False, "error": f"server error {r.status_code}",
                        "keyword": keyword, "cached": False}
            if r.status_code != 200:
                if rows:
                    break
                return {"ok": False, "error": f"HTTP {r.status_code}",
                        "keyword": keyword, "cached": False}
            data = r.json()
            batch = data.get("data") or []
            rows.extend(batch)
            cursor = data.get("nextPageCursor")
            if not cursor:
                break
    except Exception as e:
        if not rows:
            return {"ok": False, "error": type(e).__name__,
                    "keyword": keyword, "cached": False}

    capped = bool(cursor)
    kw_low = keyword.lower()
    q_tokens = set(_tokens(keyword))

    # Only correct-category results count as competitors / evidence.
    category_rows = rows
    if expected is not None:
        category_rows = [x for x in rows
                         if (x.get("assetType") or 0) in expected]
    correct = len(category_rows)

    exact = 0
    conceptual = 0
    competitors = []
    for x in category_rows:
        atype = x.get("assetType")
        name = (x.get("name") or "").strip()
        if name.lower() == kw_low:
            exact += 1
        if q_tokens & set(_tokens(name)):
            conceptual += 1
        competitors.append({
            "name": name[:48],
            "favorites": int(x.get("favoriteCount") or 0),
            "price": int(x.get("price") or 0),
            "asset_type_id": int(atype or 0),
            "creator": (x.get("creatorName") or "")[:40],
        })
    competitors.sort(key=lambda c: c["favorites"], reverse=True)

    result = {
        "ok": True,
        "cached": False,
        "keyword": keyword,
        "family": family or "all",
        "sampled_results": len(rows),
        "pages": pages,
        "capped": capped,
        "category_correct": correct,
        "category_mismatched": (len(rows) - correct) if expected is not None else None,
        "exact_title_matches": exact,
        "conceptual_matches": conceptual,
        "top_competitors": competitors[:3],
        "verification_timestamp": datetime.now(timezone.utc).isoformat(),
        "sample_note": (
            f"first {limit * max_pages} results sampled"
            + (" (capped before catalog exhausted)" if capped else "")
        ),
    }
    if use_cache:
        _cache_put(cache_key, result)
    return result


def verify_shortlist(keywords, family=None, max_workers=3, timeout=12,
                     max_pages=2, limit=30, use_cache=True):
    """Bounded, concurrency-limited live verification of a shortlist."""
    keywords = [k for k in (keywords or []) if k]
    out = {}
    if not keywords:
        return out
    failures = 0
    with ThreadPoolExecutor(max_workers=max(1, min(int(max_workers), 5))) as ex:
        futures = [(k, ex.submit(verify_niche, k, family, limit, max_pages,
                                 timeout, use_cache))
                   for k in keywords]
        for k, fut in futures:
            try:
                res = fut.result()
            except Exception as e:
                res = {"ok": False, "error": type(e).__name__, "keyword": k,
                       "cached": False}
            if not res.get("ok"):
                failures += 1
                res["skipped"] = failures > 3
            out[k] = res
    return out


# ────────────────────────────────────────────────────────────────────
# Report (10 evidence-backed fields)
# ────────────────────────────────────────────────────────────────────

_FAMILY_LABEL = {"emotes": "Emotes", "hair": "Hair", "headwear": "Headwear",
                 "face": "Face", "neck": "Neck Accessories",
                 "shoulder": "Shoulder Accessories", "front": "Front",
                 "back": "Back", "waist": "Waist", "tops": "Tops",
                 "classic": "Classic Clothing", "clothing": "Clothing",
                 "gear": "Gear", "accessory": "Accessories", "all": "All"}


def _asset_label(atype):
    from competition_check import CATEGORY_NAMES
    return CATEGORY_NAMES.get(atype, f"Type {atype}")


def _confidence(candidate, live):
    score = candidate.get("score", 0)
    reasons = []
    if candidate.get("velocity_measured"):
        reasons.append("measured velocity")
    if candidate.get("recent"):
        reasons.append("fresh supply")
    if candidate.get("freshness") == "none":
        reasons.append("no historical observations")
    elif candidate.get("stale"):
        reasons.append("stale history")
    if live is None:
        level = "low"; reasons.append("no live verification")
    elif not live.get("ok"):
        level = "low"; reasons.append(f"live check failed ({live.get('error')})")
    elif live.get("category_correct", 0) == 0:
        level = "low"; reasons.append("no correct-category live results")
    elif live.get("exact_title_matches", 0) > 0:
        level = "medium"; reasons.append("exact title already exists")
    elif score >= 55:
        level = "medium"; reasons.append("moderate evidence")
    else:
        level = "low"; reasons.append("insufficient evidence")
    return level, "; ".join(reasons) or "no justification"


def format_recommendation(candidate, live=None):
    kw = candidate.get("keyword", "?")
    lines = [f"### 🎯 `{kw}`"]
    # 1. actionable concept
    lines.append(f"• **Niche/concept:** `{kw}`")
    # 2. database evidence
    vel = (f"{candidate['velocity']}/d" if candidate.get("velocity_measured")
           else "unavailable (insufficient history)")
    lines.append(
        f"• **Database evidence:** median {candidate.get('median_favs')}♥ · "
        f"supply {candidate.get('supply')} (favs>5, sampled) · "
        f"recent {candidate.get('recent')} · velocity {vel} · "
        f"concentration {int(candidate.get('concentration', 0)*100)}%"
    )
    # 3. live evidence
    if live is None:
        lines.append("• **Live evidence:** not verified")
    elif not live.get("ok"):
        lines.append(f"• **Live evidence:** unavailable ({live.get('error')})")
    else:
        lines.append(
            f"• **Live evidence:** {live['sampled_results']} sampled results · "
            f"{live['category_correct']} correct-category · "
            f"{live['exact_title_matches']} exact-title · "
            f"{live['conceptual_matches']} conceptual · "
            f"({live.get('sample_note')}) · verified "
            f"{live.get('verification_timestamp', '?')[:19]}"
        )
    # 4. competitor examples
    if live and live.get("ok") and live.get("top_competitors"):
        lines.append("• **Competitor examples:**")
        for c in live["top_competitors"]:
            lines.append(
                f"  - `{c['name']}` — {c['favorites']:,}♥ · R${c['price']} · "
                f"{_asset_label(c['asset_type_id'])}"
            )
    else:
        lines.append("• **Competitor examples:** none verified")
    # 5. competition assessment
    if live and live.get("ok"):
        lines.append(
            f"• **Competition:** {live['exact_title_matches']} exact-title · "
            f"{live['conceptual_matches']} conceptual matches "
            f"(sampled, not total)"
        )
    else:
        lines.append("• **Competition:** unknown (live check incomplete)")
    # 6. momentum
    lines.append(f"• **Momentum:** velocity {vel}")
    # 7. completeness/freshness
    fresh = {"none": "no history", "stale": "stale history",
             "recent": "recent history"}.get(candidate.get("freshness"),
                                             "recent history")
    lines.append(
        f"• **Completeness/freshness:** {fresh} · "
        f"velocity {'measured' if candidate.get('velocity_measured') else 'unmeasured'}"
    )
    # 8-10. confidence + risks + recommendation
    level, why = _confidence(candidate, live)
    lines.append(f"• **Confidence:** {level} ({why})")
    risks = []
    if not candidate.get("velocity_measured"):
        risks.append("no measured growth history")
    if candidate.get("concentration", 0) > 0.5:
        risks.append("creator concentration high")
    if live and live.get("ok") and live.get("capped"):
        risks.append("live sample capped")
    if live and live.get("ok") and live.get("category_mismatched"):
        risks.append(f"{live['category_mismatched']} live results in wrong category")
    lines.append(f"• **Risks:** {'; '.join(risks) if risks else 'none identified'}")
    lines.append(
        f"• **Recommendation:** "
        f"{'investigate further' if level in ('medium', 'low') and live and live.get('ok') else 'do not pursue without more evidence'}"
    )
    return "\n".join(lines)


def format_report(detailed, verified, family="all"):
    family = family or "all"
    label = _FAMILY_LABEL.get(str(family).lower(), str(family))
    candidates = (detailed or {}).get("shortlist") or (detailed or {}).get("candidates") or []
    gated = (detailed or {}).get("gated") or []

    lines = [f"# 🎯 CONVERGENCE — {label}\n"]
    lines.append("_Database discovery + live marketplace verification. "
                 "Nothing here proves profitability — favorites and autocomplete "
                 "are not sales._\n")

    if not candidates:
        lines.append("## No qualifying opportunities")
        lines.append("No candidate met the minimum evidence standard "
                     "(measured velocity or fresh supply, non-generic).")
        if gated:
            lines.append("\n**Gated (rejected) candidates:**")
            for g in gated[:8]:
                lines.append(f"• `{g['keyword']}` — {g['reason']}")
        lines.append("")
        lines.append("_Honest insufficient-evidence result; no recommendations "
                     "were forced._")
        return "\n".join(lines)

    lines.append(f"## Shortlist ({len(candidates)} candidates)")
    for c in candidates:
        live = verified.get(c["keyword"])
        lines.append(format_recommendation(c, live))
        lines.append("")

    if gated:
        lines.append("## Gated out (not recommended)")
        for g in gated[:8]:
            lines.append(f"• `{g['keyword']}` — {g['reason']} (score {g.get('score')})")
        lines.append("")

    lines.append("_Sampled marketplace results are not a complete catalog count; "
                 "search-suggestion occurrences are not verified demand._")
    return "\n".join(lines)
