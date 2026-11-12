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
from execution_policy import RobloxScheduler, default_scheduler
from safe_roblox import (
    shared_circuit_open,
    trip_shared_circuit,
    reset_for_tests as reset_shared_for_tests,
)

# Accessory covers the five sub-types; the engine aggregates them.
_EXPECTED_ASSET_TYPES = dict(FAMILIES)
_EXPECTED_ASSET_TYPES["accessory"] = [43, 44, 45, 46, 47]

CACHE_TTL_SECONDS = 300
_CACHE = {}
_CACHE_LOCK = threading.Lock()

_SCHEDULER = None
_SCHEDULER_LOCK = threading.Lock()


def _get_scheduler():
    """Central endpoint-aware scheduler for catalog searches.

    The scheduler owns the single retry loop, so every physical retry attempt
    re-acquires a pacing token; it also provides concurrency control, in-flight
    dedup and the circuit breaker. Conservative pacing (30/min, 2 concurrent)
    reflects the historical HTTP 429 incidents.
    """
    global _SCHEDULER
    with _SCHEDULER_LOCK:
        if _SCHEDULER is None:
            _SCHEDULER = RobloxScheduler(
                request_fn=lambda url, params=None, headers=None, timeout=12:
                _get_with_backoff(url, params, max_attempts=1, timeout=timeout))
            _SCHEDULER.configure(
                "catalog_search", rate_per_min=30, max_concurrency=2,
                cache_ttl=0, max_retries=1, circuit_threshold=1,
                circuit_cooldown=30.0)
        return _SCHEDULER

# Circuit breaker: short cooldown after a 429/5xx so a burst of failures stops
# issuing requests instead of hammering the endpoint.
CIRCUIT_BREAK_COOLDOWN = 30.0
_CIRCUIT = {"open_until": 0.0}
_CIRCUIT_LOCK = threading.Lock()


def _circuit_open():
    if shared_circuit_open("catalog_search"):
        return True
    s = _SCHEDULER
    return bool(s is not None and s.is_circuit_open("catalog_search"))


def _parse_retry_after(value):
    """Parse a Retry-After header into seconds (numeric or HTTP-date)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return max(0.0, float(s))
    except (TypeError, ValueError):
        pass
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        if dt is not None:
            return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def _trip_circuit(seconds=None):
    trip_shared_circuit(seconds)
    s = _SCHEDULER
    if s is not None:
        s.trip("catalog_search", seconds)


def _reset_circuit():
    s = _SCHEDULER
    if s is not None:
        s.reset()
    reset_shared_for_tests()
    try:
        default_scheduler().reset()
    except Exception:
        pass


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
            return entry["value"], max(0.0, time.time() - entry["ts"])
    return None


def _cache_put(key, value):
    with _CACHE_LOCK:
        _CACHE[key] = {"ts": time.time(), "value": value}


def _cache_key(keyword, family, limit, max_pages):
    """Cache identity includes category, keyword, page size, and page depth."""
    return (str(family).lower(), str(keyword).lower(), int(limit),
            int(max_pages))


def _cached_result(keyword, family, limit, max_pages, use_cache=True):
    """Return cached evidence only; never performs a network request."""
    if not use_cache:
        return None
    cached_entry = _cache_get(_cache_key(keyword, family, limit, max_pages))
    if cached_entry is None:
        return None
    cached, age = cached_entry
    cached = dict(cached)
    cached["cached"] = True
    cached["cache_age_seconds"] = round(age, 1)
    cached["observed_at"] = cached.get("verification_timestamp")
    return cached


def clear_cache():
    with _CACHE_LOCK:
        _CACHE.clear()
    if _SCHEDULER is not None:
        _SCHEDULER.reset()


def verify_niche(keyword, family=None, limit=30, max_pages=2, timeout=12,
                 use_cache=True):
    """Read-only live search for one niche keyword. Returns a sanitized dict."""
    keyword = (keyword or "").strip()
    if not keyword:
        return {"ok": False, "error": "empty keyword", "keyword": keyword}

    cache_key = _cache_key(keyword, family, limit, max_pages)
    cached = _cached_result(keyword, family, limit, max_pages, use_cache)
    if cached is not None:
        return cached

    if _circuit_open():
        return {"ok": False, "error": "circuit open (rate limited)",
                "keyword": keyword, "cached": False, "deferred": True,
                "retry_after": None, "circuit_open": True,
                "attempted": False, "skipped": True, "status": "deferred"}

    expected = _expected_asset_types(family)
    is_background = expected == [92]
    # Search with category context because the catalog endpoint's keyword
    # search does not provide a reliably supported AssetType 92 server filter.
    # Exact post-filtering below remains mandatory.
    search_keyword = (
        keyword if not is_background or "background" in keyword.lower()
        else f"{keyword} background"
    )
    rows, pages, cursor = [], 0, None
    rate_limit_meta = None
    try:
        while pages < max_pages:
            params = {"Keyword": search_keyword, "Limit": limit,
                      "SortType": "Relevance"}
            if cursor:
                params["Cursor"] = cursor
            r = _get_scheduler().request(
                "catalog_search", SEARCH_URL, params=params, timeout=timeout)
            pages += 1
            status = r.status or 0
            if not r.ok:
                if (getattr(r, "deferred", False)
                        and "circuit" in str(getattr(r, "error", "")).lower()):
                    return {
                        "ok": False,
                        "error": r.error or "circuit open (rate limited)",
                        "keyword": keyword,
                        "cached": False,
                        "deferred": True,
                        "retry_after": getattr(r, "retry_after", None),
                        "circuit_open": True,
                        "attempted": False,
                        "skipped": True,
                        "status": "deferred",
                    }
                if status == 429:
                    # Preserve the scheduler's original retry/defer evidence.
                    retry_after = (r.retry_after if r.retry_after is not None
                                   else (r.headers or {}).get("Retry-After"))
                    rate_limit_meta = {"deferred": bool(r.deferred),
                                       "retry_after": retry_after}
                    if rows:
                        break
                    return {"ok": False,
                            "error": r.error or "rate limited (429)",
                            "retry_after": retry_after,
                            "deferred": bool(r.deferred),
                            "keyword": keyword, "cached": False}
                if status >= 500:
                    if rows:
                        break
                    return {"ok": False, "error": f"server error {status}",
                            "keyword": keyword, "cached": False}
                if status:
                    if rows:
                        break
                    return {"ok": False, "error": f"HTTP {status}",
                            "keyword": keyword, "cached": False}
                if rows:
                    break
                return {"ok": False, "error": r.error or "request failed",
                        "keyword": keyword, "cached": False}
            data = r.data or {}
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

    # Only unambiguous correct-category results count as competitors.
    # API responses can contain assetType or assetTypeId; missing types
    # must NEVER be counted as genuine category matches.
    def _item_asset_type(item):
        try:
            return int(item.get("assetType") or item.get("assetTypeId") or 0)
        except (TypeError, ValueError):
            return 0

    category_rows = rows
    if expected is not None:
        category_rows = [x for x in rows
                         if _item_asset_type(x) in expected]
    correct = len(category_rows)

    exact = 0
    conceptual = 0
    competitors = []
    for x in category_rows:
        atype = _item_asset_type(x)
        name = (x.get("name") or "").strip()
        if name.lower() == kw_low:
            exact += 1
        related = bool(q_tokens & set(_tokens(name)))
        if related:
            conceptual += 1
        competitors.append({
            "name": name[:48],
            "favorites": int(x.get("favoriteCount") or 0),
            "price": int(x.get("price") or 0),
            "asset_type_id": int(atype or 0),
            "creator": (x.get("creatorName") or "")[:40],
            "related": related,
        })
    # Concept-related competitors first, then by popularity.
    competitors.sort(key=lambda c: (not c["related"], -c["favorites"]))

    result = {
        "ok": True,
        "cached": False,
        "keyword": keyword,
        "family": family or "all",
        "search_keyword": search_keyword,
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
    if rate_limit_meta:
        # Partial results were returned, but the rate-limit evidence is kept.
        result.update(rate_limit_meta)
    result["observed_at"] = result["verification_timestamp"]
    result["cache_age_seconds"] = 0.0
    if use_cache:
        _cache_put(cache_key, result)
    return result


def verify_shortlist(keywords, family=None, max_workers=3, timeout=12,
                     max_pages=2, limit=30, use_cache=True):
    """Bounded, circuit-aware live verification of a shortlist.

    At most ``max_workers`` new requests are in flight. Once the shared circuit
    is known to be open, remaining candidates are resolved from cache or
    returned as deferred without issuing another request. Already-running
    futures are allowed to finish; no new ones are submitted.
    """
    keywords = [k for k in (keywords or []) if k]
    out = {}
    if not keywords:
        return out
    workers = max(1, min(int(max_workers), 5))
    index = 0

    def _cache_only_or_deferred(k):
        """Resolve without ever invoking a network-capable verification."""
        cached = _cached_result(k, family, limit, max_pages, use_cache)
        if cached is not None:
            cached["status"] = "cached"
            cached["attempted"] = False
            cached["skipped"] = False
            return cached
        return {
            "ok": False,
            "error": "circuit open (rate limited)",
            "keyword": k,
            "cached": False,
            "deferred": True,
            "skipped": True,
            "attempted": False,
            "status": "deferred",
            "retry_after": None,
            "circuit_open": True,
        }

    def _with_status(res, attempted):
        if res.get("cached"):
            res["status"] = "cached"
            res["attempted"] = False
            res["skipped"] = False
        elif res.get("circuit_open"):
            res["status"] = "deferred"
            res["attempted"] = False
            res["skipped"] = True
        elif res.get("ok"):
            res["status"] = "verified"
            res["attempted"] = attempted
            res["skipped"] = False
        else:
            res["status"] = "failed"
            res["attempted"] = attempted
            res["skipped"] = False
        return res

    with ThreadPoolExecutor(max_workers=workers) as ex:
        while index < len(keywords):
            if _circuit_open():
                # Cache-only path. A circuit that expires immediately after
                # this check still must not trigger a new request.
                for k in keywords[index:]:
                    out[k] = _cache_only_or_deferred(k)
                break
            batch = keywords[index:index + workers]
            index += len(batch)
            futures = [(k, ex.submit(verify_niche, k, family, limit,
                                     max_pages, timeout, use_cache))
                       for k in batch]
            for k, fut in futures:
                try:
                    res = fut.result()
                except Exception as exc:
                    res = {"ok": False, "error": type(exc).__name__,
                           "keyword": k, "cached": False,
                           "deferred": False}
                out[k] = _with_status(res, attempted=True)
    return out


# ────────────────────────────────────────────────────────────────────
# Report (10 evidence-backed fields)
# ────────────────────────────────────────────────────────────────────

_FAMILY_LABEL = {"emotes": "Emotes", "hair": "Hair", "headwear": "Headwear",
                 "backgrounds": "Avatar Backgrounds",
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
        level = "low"
        reasons.append("no correct-category matches in the observed sample")
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
        deferred = " · deferred" if live.get("deferred") else ""
        lines.append(
            f"• **Live evidence:** unavailable ({live.get('error')})"
            f"{deferred}")
    else:
        observed = (live.get("observed_at")
                    or live.get("verification_timestamp") or "?")[:19]
        if live.get("cached"):
            freshness = (f"cached evidence (age "
                         f"{live.get('cache_age_seconds', '?')}s; observed "
                         f"{observed})")
        else:
            freshness = f"verified {observed}"
        if live.get("search_keyword") and live.get("search_keyword") != kw:
            lines.append(f"• **Marketplace search:** `{live['search_keyword']}` "
                         "(category-context query; result types filtered locally)")
        lines.append(
            f"• **Live evidence:** {live['sampled_results']} sampled results · "
            f"{live['category_correct']} correct-category · "
            f"{live['exact_title_matches']} exact-title · "
            f"{live['conceptual_matches']} conceptual · "
            f"({live.get('sample_note')}) · {freshness}"
        )
    # 4. competitor examples (concept-related only)
    if live and live.get("ok"):
        related = [c for c in (live.get("top_competitors") or [])
                   if c.get("related")]
        if related:
            lines.append("• **Competitor examples (concept-related):**")
            for c in related:
                lines.append(
                    f"  - `{c['name']}` — {c['favorites']:,}♥ · R${c['price']} · "
                    f"{_asset_label(c['asset_type_id'])}"
                )
        else:
            lines.append("• **Competitor examples:** none concept-related "
                         "in the live sample")
    else:
        lines.append("• **Competitor examples:** none verified")
    # 5. competition assessment
    if live and live.get("ok"):
        if live.get("category_correct", 0) == 0:
            lines.append(
                "• **Competition:** 0 observed correct-category matches in "
                "the sampled results; this sample does not prove "
                "category-wide absence"
            )
        else:
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
    if live and live.get("ok") and live.get("category_correct", 0) == 0:
        risks.append("zero correct-category matches in sample; not proof of absence")
    lines.append(f"• **Risks:** {'; '.join(risks) if risks else 'none identified'}")
    # Recommendation must be negative when live verification finds no
    # correct-category results, regardless of the confidence level.
    if live is None or not live.get("ok"):
        verdict = "do not pursue without more evidence (live verification unavailable)"
    elif live.get("category_correct", 0) == 0:
        verdict = ("insufficient evidence — no correct-category matches in the "
                   "observed sample; this sample does not prove the category "
                   "has no competitors")
    elif live.get("exact_title_matches", 0) > 0:
        verdict = "investigate cautiously — exact title already exists live"
    elif level == "medium":
        verdict = "investigate further"
    else:
        verdict = "investigate with caution (limited evidence)"
    lines.append(f"• **Recommendation:** {verdict}")
    return "\n".join(lines)


def format_report(detailed, verified, family="all"):
    family = family or "all"
    label = _FAMILY_LABEL.get(str(family).lower(), str(family))
    candidates = (detailed or {}).get("shortlist") or (detailed or {}).get("candidates") or []
    gated = (detailed or {}).get("gated") or []
    try:
        display_limit = max(1, int((detailed or {}).get("limit") or 8))
    except (TypeError, ValueError):
        display_limit = 8

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
            for g in gated[:display_limit]:
                lines.append(f"• `{g['keyword']}` — {g['reason']}")
        lines.append("")
        if str(family).lower() == "backgrounds":
            lines.append(
                "Background niches need both recurring scene-keyword evidence "
                "and sufficient marketplace data. Individual early winners "
                "can exist even when no niche passes this stricter gate. "
                "Try `!early 7 backgrounds` to inspect measured item-level "
                "favorite growth, or `!xray` for category-wide DB coverage. "
                "Do not infer CTR, sales or a validated niche from favorites."
            )
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
        for g in gated[:display_limit]:
            lines.append(f"• `{g['keyword']}` — {g['reason']} (score {g.get('score')})")
        lines.append("")

    lines.append("_Sampled marketplace results are not a complete catalog count; "
                 "search-suggestion occurrences are not verified demand._")
    return "\n".join(lines)
