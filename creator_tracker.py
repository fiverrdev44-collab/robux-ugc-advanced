"""creator_tracker.py — monitor verified UGC creators on the marketplace.

Uses the public catalog search endpoint, which returns, per item:
  creatorTargetId · creatorType · creatorHasVerifiedBadge
  favoriteCount · price · itemCreatedUtc · assetType

Only creators flagged verified are added to the tracking queue. Scans are
throttled and resumable, so the 100GB box can chew through the cohort over
hours without tripping rate limits.
"""
import os
import random
import time
from datetime import datetime, timedelta, timezone

import requests

from safe_roblox import get as safe_get, shared_circuit_open
from execution_policy import _parse_retry_after
from creator_identity import (
    has_composite_creator_pk,
    is_known_creator_type,
    normalize_creator_type,
    stored_creator_type,
)

SEARCH_URL = "https://catalog.roblox.com/v1/search/items/details"
PAGE_SIZE = 30
DELAY = 1.0          # seconds between requests — be polite
MAX_PAGES = 2        # 60 items per creator per run
MAX_REQUESTS = 150   # hard budget per batch, so one run can't dig a hole


class RateLimited(Exception):
    """Raised when Roblox keeps rejecting us — stop the batch, resume later."""


def _headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }


def _cookie_values():
    """All configured .ROBLOSECURITY cookies, primary first."""
    values = []
    for i in range(1, 6):
        raw = os.getenv(f"ROBLOSECURITY_COOKIE_{i}")
        if raw and raw.strip() and raw.strip() not in values:
            values.append(raw.strip())
    raw = os.getenv("ROBLOSECURITY_COOKIE")
    if raw and raw.strip() and raw.strip() not in values:
        values.append(raw.strip())
    return values


def _session(cookie=None):
    s = requests.Session()
    s.headers.update(_headers())
    if cookie:
        s.cookies[".ROBLOSECURITY"] = cookie
    return s


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _to_item(d):
    badge = d.get("creatorHasVerifiedBadge")
    return {
        "id": d.get("id"),
        "name": (d.get("name") or "")[:500],
        "description": (d.get("description") or "")[:5000],
        "favorite_count": d.get("favoriteCount"),
        "price": d.get("price") or 0,
        "creator_name": (d.get("creatorName") or "")[:200],
        "creator_id": d.get("creatorTargetId"),
        # Missing type/verification stays missing; never default to User/False.
        "creator_type": normalize_creator_type(d.get("creatorType")),
        "creator_verified": badge if isinstance(badge, bool) else None,
        "asset_type_id": d.get("assetType") or 0,
        "created_at": _parse_time(d.get("itemCreatedUtc")),
    }


LAST_ERROR = None
LAST_ERROR_KIND = None
LAST_RETRY_AFTER = None


def _get_json(s, params):
    """One logical request through the shared catalog-search protection.

    Returns parsed JSON only on a valid 200 response. Failure details are
    exposed through LAST_ERROR_KIND / LAST_ERROR / LAST_RETRY_AFTER so callers
    can distinguish completion from a failure without treating it as empty
    data. 429 still raises RateLimited for backward compatibility.
    """
    global LAST_ERROR, LAST_ERROR_KIND, LAST_RETRY_AFTER
    LAST_ERROR = None
    LAST_ERROR_KIND = None
    LAST_RETRY_AFTER = None
    if shared_circuit_open("catalog_search"):
        LAST_ERROR = "circuit open"
        LAST_ERROR_KIND = "deferred"
        return None
    try:
        resp = safe_get(
            "catalog_search", SEARCH_URL, params=params, session=s, timeout=15)
    except Exception as e:
        LAST_ERROR = f"request failed: {type(e).__name__}"
        LAST_ERROR_KIND = ("timeout" if "timeout" in type(e).__name__.lower()
                           else "unavailable")
        print(f"[creator-tracker] request failed: {type(e).__name__}",
              flush=True)
        return None

    code = resp.status_code or 0
    if code == 200:
        data = resp.json()
        if not isinstance(data, dict):
            LAST_ERROR = "invalid JSON response"
            LAST_ERROR_KIND = "invalid_response"
            return None
        return data
    if code == 0 and resp.error == "circuit open":
        LAST_ERROR = "circuit open"
        LAST_ERROR_KIND = "deferred"
        return None
    if code == 429:
        LAST_ERROR = "rate limited (429)"
        LAST_ERROR_KIND = "rate_limited"
        LAST_RETRY_AFTER = _parse_retry_after(
            resp.headers.get("Retry-After"))
        raise RateLimited()
    LAST_ERROR = f"HTTP {code}"
    LAST_ERROR_KIND = ("timeout" if "timeout" in str(resp.error or "").lower()
                       else "unavailable")
    print(f"[creator-tracker] HTTP {code}", flush=True)
    return None


def search_creator(s, creator_id, creator_type=None, pages=MAX_PAGES):
    """Return the creator's recent catalog items for a verified typed identity."""
    ctype = normalize_creator_type(creator_type)
    if ctype is None or not is_known_creator_type(ctype):
        return []
    items = []
    cursor = None
    for _ in range(max(1, pages)):
        params = {
            "CreatorTargetId": creator_id,
            "CreatorType": ctype,
            "Limit": PAGE_SIZE,
            "SortType": 3,  # recently updated first
        }
        if cursor:
            params["Cursor"] = cursor
        data = _get_json(s, params)
        if not data:
            break
        items.extend(_to_item(d) for d in data.get("data") or [])
        cursor = data.get("nextPageCursor")
        if not cursor:
            break
        time.sleep(DELAY)
    return items


DISCOVERY_KEYWORDS = (
    "emote", "dance", "aura", "hip sway", "kpop", "idle", "animation",
    "hair", "wig", "beanie", "hat", "crown", "cap",
    "glasses", "mask", "face", "eyelash", "eyebrow",
    "wings", "backpack", "necklace", "chain", "scarf", "tail",
    "shirt", "pants", "dress", "jacket", "shoes", "hoodie",
    "sword", "staff", "shield", "wand",
)


def verify_creator_badge(s, creator_id, creator_type=None):
    """Live badge check. Returns True/False/None (None = unknown/failed)."""
    ctype = normalize_creator_type(creator_type)
    if not is_known_creator_type(ctype):
        return None
    if ctype == "Group":
        url = f"https://groups.roblox.com/v1/groups/{creator_id}"
        endpoint = "groups"
    else:
        url = f"https://users.roblox.com/v1/users/{creator_id}"
        endpoint = "users"
    try:
        resp = safe_get(endpoint, url, session=s, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json() or {}
        if "hasVerifiedBadge" in data:
            return bool(data.get("hasVerifiedBadge"))
        return None
    except Exception:
        return None


def discover_verified(s, keywords=DISCOVERY_KEYWORDS, pages=1):
    """Bootstrap: pull popular items and keep the verified creators."""
    found = {}
    for kw in keywords:
        cursor = None
        for _ in range(max(1, pages)):
            params = {"Keyword": kw, "Limit": PAGE_SIZE, "SortType": 2}
            if cursor:
                params["Cursor"] = cursor
            data = _get_json(s, params)
            if not data:
                break
            for d in data.get("data") or []:
                ctype = normalize_creator_type(d.get("creatorType"))
                cid = d.get("creatorTargetId")
                if (d.get("creatorHasVerifiedBadge") and cid
                        and is_known_creator_type(ctype)):
                    found[(int(cid), ctype)] = (
                        d.get("creatorName") or "?")
            cursor = data.get("nextPageCursor")
            if not cursor:
                break
            time.sleep(DELAY)
        time.sleep(DELAY)
    return found


# ── Database side ───────────────────────────────────────────────

def ensure_creators(cur, creators, session=None):
    """creators: {(id, type): name}. Types are stored explicitly.

    Unknown types are stored as ``unknown`` and are never scanned. The
    composite conflict target is used when the F-07 migration is applied; the
    legacy single-column conflict target is retained only for pre-migration
    deployments and cannot distinguish User/Group collisions.
    """
    added = 0
    composite = has_composite_creator_pk(cur)
    for (cid, ctype), name in creators.items():
        ctype = normalize_creator_type(ctype)
        if ctype is None:
            ctype = "unknown"
        if composite:
            cur.execute("""
                SELECT 1 FROM tracked_creators
                WHERE creator_type = %s AND creator_id = %s
            """, (ctype, cid))
        else:
            cur.execute(
                "SELECT 1 FROM tracked_creators WHERE creator_id = %s", (cid,))
        if cur.fetchone():
            continue
        verified = True
        if session is not None and is_known_creator_type(ctype):
            checked = verify_creator_badge(session, cid, ctype)
            if checked is False:
                continue
            if checked is None:
                verified = True  # catalog flag already said verified
            time.sleep(0.5)
        elif not is_known_creator_type(ctype):
            verified = False
        if composite:
            cur.execute("""
                INSERT INTO tracked_creators (creator_id, creator_type,
                                              creator_name, verified,
                                              last_scanned, type_provenance)
                VALUES (%s, %s, %s, %s, NULL, 'catalog')
                ON CONFLICT (creator_type, creator_id) DO NOTHING
            """, (cid, ctype, name, verified))
        else:
            cur.execute("""
                INSERT INTO tracked_creators (creator_id, creator_type,
                                              creator_name, verified,
                                              last_scanned)
                VALUES (%s, %s, %s, %s, NULL)
                ON CONFLICT (creator_id) DO NOTHING
            """, (cid, ctype, name, verified))
        added += cur.rowcount or 0
    return added


def pick_batch(cur, limit=10, stale_hours=6):
    cur.execute("""
        SELECT creator_id, creator_type, creator_name
        FROM tracked_creators
        WHERE verified IS TRUE
          AND creator_type IN ('User', 'Group')
          AND (last_scanned IS NULL
               OR last_scanned < NOW() - (%s || ' hours')::interval)
        ORDER BY last_scanned NULLS FIRST
        LIMIT %s
    """, (stale_hours, limit))
    return cur.fetchall()


def _items_has_creator_type(cur):
    try:
        cur.execute(
            "select 1 from information_schema.columns "
            "where table_schema = current_schema() "
            "and table_name = 'items' and column_name = 'creator_type'")
        return cur.fetchone() is not None
    except Exception:
        return False


def upsert_items(cur, items):
    has_type = _items_has_creator_type(cur)
    inserted = 0
    for it in items:
        if not it.get("id"):
            continue
        verified = it.get("creator_verified")  # None means unknown
        creator_type = it.get("creator_type")  # None means unknown
        favorite_status = ("known" if it.get("favorite_count") is not None
                           else "missing")
        if has_type:
            cur.execute("""
                INSERT INTO items (id, name, description, favorite_count,
                                   price, creator_name, creator_id,
                                   creator_type, creator_verified,
                                   asset_type_id, created_at, fetched_at,
                                   favorite_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        CURRENT_TIMESTAMP, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    favorite_count = EXCLUDED.favorite_count,
                    favorite_status = CASE
                        WHEN EXCLUDED.favorite_count IS NULL THEN 'missing'
                        ELSE 'known' END,
                    price = EXCLUDED.price,
                    creator_name = COALESCE(NULLIF(EXCLUDED.creator_name, ''),
                                            items.creator_name),
                    creator_id = COALESCE(EXCLUDED.creator_id, items.creator_id),
                    creator_type = COALESCE(EXCLUDED.creator_type,
                                            items.creator_type),
                    creator_verified = COALESCE(EXCLUDED.creator_verified,
                                                items.creator_verified),
                    asset_type_id = EXCLUDED.asset_type_id,
                    fetched_at = CURRENT_TIMESTAMP
            """, (
                it["id"], it["name"], it["description"], it["favorite_count"],
                it["price"], it["creator_name"], it.get("creator_id"),
                creator_type, verified, it["asset_type_id"],
                it.get("created_at"), favorite_status,
            ))
        else:
            cur.execute("""
                INSERT INTO items (id, name, description, favorite_count,
                                   price, creator_name, creator_id,
                                   creator_verified, asset_type_id,
                                   created_at, fetched_at, favorite_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        CURRENT_TIMESTAMP, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    favorite_count = EXCLUDED.favorite_count,
                    favorite_status = CASE
                        WHEN EXCLUDED.favorite_count IS NULL THEN 'missing'
                        ELSE 'known' END,
                    price = EXCLUDED.price,
                    creator_name = COALESCE(NULLIF(EXCLUDED.creator_name, ''),
                                            items.creator_name),
                    creator_id = COALESCE(EXCLUDED.creator_id, items.creator_id),
                    creator_verified = COALESCE(EXCLUDED.creator_verified,
                                                items.creator_verified),
                    asset_type_id = EXCLUDED.asset_type_id,
                    fetched_at = CURRENT_TIMESTAMP
            """, (
                it["id"], it["name"], it["description"], it["favorite_count"],
                it["price"], it["creator_name"], it.get("creator_id"),
                verified, it["asset_type_id"], it.get("created_at"),
                favorite_status,
            ))
        inserted += 1
    return inserted


def mark_scanned(cur, creator_id, creator_type):
    ctype = normalize_creator_type(creator_type)
    if not is_known_creator_type(ctype):
        return 0
    cur.execute("""
        UPDATE tracked_creators
        SET last_scanned = CURRENT_TIMESTAMP
        WHERE creator_type = %s AND creator_id = %s
    """, (ctype, creator_id))
    return cur.rowcount or 0


COOLDOWN_KEY = "crawl_cooldown_until"


def _cooldown_remaining(cur):
    try:
        cur.execute(
            "SELECT pattern_value FROM creator_patterns WHERE pattern_key = %s",
            (COOLDOWN_KEY,),
        )
        row = cur.fetchone()
        if not row:
            return 0
        until = datetime.fromisoformat(row[0])
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return max(0, int((until - datetime.now(timezone.utc)).total_seconds()))
    except Exception:
        return 0


def _set_cooldown(cur, minutes=10):
    until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    try:
        cur.execute("""
            INSERT INTO creator_patterns (pattern_key, pattern_value, updated_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (pattern_key) DO UPDATE SET
                pattern_value = EXCLUDED.pattern_value,
                updated_at = CURRENT_TIMESTAMP
        """, (COOLDOWN_KEY, until.isoformat()))
        cur.connection.commit()
    except Exception:
        pass


DISCOVERY_OFFSET_KEY = "creator_discovery_offset"
DISCOVERY_PER_RUN = 6


def _next_discovery_keywords(cur, count=DISCOVERY_PER_RUN):
    """Rotate the discovery keyword list so one run sends a few searches
    instead of the full 34-keyword burst that trips Roblox's rate limiter."""
    keywords = list(DISCOVERY_KEYWORDS)
    offset = 0
    try:
        cur.execute(
            "SELECT pattern_value FROM creator_patterns WHERE pattern_key = %s",
            (DISCOVERY_OFFSET_KEY,),
        )
        row = cur.fetchone()
        if row:
            offset = int(row[0]) % len(keywords)
    except Exception:
        pass
    chunk = [keywords[(offset + i) % len(keywords)]
             for i in range(min(count, len(keywords)))]
    try:
        cur.execute("""
            INSERT INTO creator_patterns (pattern_key, pattern_value, updated_at)
            VALUES (%s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (pattern_key) DO UPDATE SET
                pattern_value = EXCLUDED.pattern_value,
                updated_at = CURRENT_TIMESTAMP
        """, (DISCOVERY_OFFSET_KEY,
              str((offset + len(chunk)) % len(keywords))))
        cur.connection.commit()
    except Exception:
        cur.connection.rollback()
    return chunk


def run_batch(cur, limit=10):
    """Scan one batch.

    Returns (creators_scanned, items_upserted, new_creators, note) where note
    explains a zero result (HTTP error, rate limit) or is None.
    """
    global LAST_ERROR
    LAST_ERROR = None

    remaining = _cooldown_remaining(cur)
    if remaining > 0:
        return 0, 0, 0, f"cooling down for {remaining // 60}m {remaining % 60}s"

    cookies = _cookie_values()
    s = _session(cookies[0] if cookies else None)

    # Scan tracked creators first. Discovery is a 34-search burst and used to
    # run on every batch, so a single 429 meant no creator was ever scanned.
    batch = pick_batch(cur, limit)
    new_creators = 0
    if not batch:
        keywords = _next_discovery_keywords(cur)
        try:
            discovered = discover_verified(s, keywords=keywords)
        except RateLimited:
            _set_cooldown(cur, 5)
            print("[creator-tracker] rate limited during discovery — stopping",
                  flush=True)
            return 0, 0, 0, "rate limited — cooling down 5m"

        new_creators = ensure_creators(cur, discovered, s)
        cur.connection.commit()
        batch = pick_batch(cur, limit)
        if not batch:
            note = None
            if not new_creators and not discovered:
                note = LAST_ERROR or "no verified creators returned by search"
            return 0, 0, new_creators, note

    scanned = 0
    upserted = 0
    budget = MAX_REQUESTS

    for cid, ctype, _name in batch:
        try:
            items = search_creator(s, cid, ctype)
        except RateLimited:
            _set_cooldown(cur, 5)
            print("[creator-tracker] rate limited — cooling down 5m, "
                  "no cookie rotation", flush=True)
            return (scanned, upserted, new_creators,
                    "rate limited — cooling down 5m")
        upserted += upsert_items(cur, items)
        mark_scanned(cur, cid, ctype)
        cur.connection.commit()
        scanned += 1
        budget -= MAX_PAGES + 1
        if budget <= 0:
            print("[creator-tracker] request budget reached — pausing", flush=True)
            break
        time.sleep(DELAY + random.uniform(0, 0.8))

    return scanned, upserted, new_creators, LAST_ERROR


# ── Project ORACLE helpers (additive; existing tracker untouched) ──

def filter_recent_assets(items, max_age_days=30, now=None):
    """Keep assets whose real creation timestamp is within the window (UTC)."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_age_days)
    out = []
    for it in items:
        created = it.get("created_at")
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created >= cutoff:
            out.append(it)
    return out


def search_creator_complete(s, creator_id, creator_type=None, max_pages=10):
    """Paginated creator search with an explicit completion contract.

    Compatibility keys (creator_id, creator_type, items, pages, truncated)
    are preserved. ``status`` is one of complete, partial, rate_limited,
    deferred, timeout, unavailable, invalid_response, page_cap_reached.
    Valid pages are always returned even when the final page fails.
    """
    ctype = normalize_creator_type(creator_type)
    if not is_known_creator_type(ctype):
        return {
            "creator_id": creator_id, "creator_type": None, "items": [],
            "pages": 0, "truncated": False, "complete": False,
            "status": "unavailable", "error": "unknown creator type",
            "retry_after": None, "partial": False,
        }
    items = []
    cursor = None
    pages = 0
    max_pages = max(1, int(max_pages))
    status = "complete"
    error = None
    retry_after = None
    while pages < max_pages:
        params = {
            "CreatorTargetId": creator_id,
            "CreatorType": ctype,
            "Limit": PAGE_SIZE,
            "SortType": 3,
        }
        if cursor:
            params["Cursor"] = cursor
        try:
            data = _get_json(s, params)
        except RateLimited:
            status = "rate_limited"
            error = LAST_ERROR or "rate limited (429)"
            retry_after = LAST_RETRY_AFTER
            break
        if data is None:
            status = LAST_ERROR_KIND or "unavailable"
            error = LAST_ERROR or status
            retry_after = LAST_RETRY_AFTER
            break
        if not isinstance(data, dict) or not isinstance(
                data.get("data"), list):
            status = "invalid_response"
            error = "response data is not a list"
            break
        for d in (data.get("data") or []):
            item = _to_item(d)
            item["creator_id"] = creator_id
            # Keep missing favorites as None (never coerce to zero).
            item["favorites"] = d.get("favoriteCount")
            items.append(item)
        pages += 1
        cursor = data.get("nextPageCursor")
        if not cursor:
            status = "complete"
            break
        if pages < max_pages:
            time.sleep(DELAY)
    else:
        if cursor:
            status = "page_cap_reached"
            error = "page cap reached with remaining pages"
    complete = status == "complete"
    if status not in ("complete", "last_page"):
        complete = False
    return {
        "creator_id": creator_id,
        "creator_type": ctype,
        "items": items,
        "pages": pages,
        "truncated": bool(cursor) and pages >= max_pages,
        "complete": complete,
        "partial": bool(items) and not complete,
        "status": status,
        "error": error,
        "retry_after": retry_after,
    }
