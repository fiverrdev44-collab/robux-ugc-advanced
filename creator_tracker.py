"""creator_tracker.py — monitor verified UGC creators on the marketplace.

Uses the public catalog search endpoint, which returns, per item:
  creatorTargetId · creatorType · creatorHasVerifiedBadge
  favoriteCount · price · itemCreatedUtc · assetType

Only creators flagged verified are added to the tracking queue. Scans are
throttled and resumable, so the 100GB box can chew through the cohort over
hours without tripping rate limits.
"""
import os
import time
from datetime import datetime, timezone

import requests

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


def _session():
    s = requests.Session()
    s.headers.update(_headers())
    cookie = os.getenv("ROBLOSECURITY_COOKIE_1") or os.getenv("ROBLOSECURITY_COOKIE")
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
    return {
        "id": d.get("id"),
        "name": (d.get("name") or "")[:500],
        "description": (d.get("description") or "")[:5000],
        "favorite_count": d.get("favoriteCount") or 0,
        "price": d.get("price") or 0,
        "creator_name": (d.get("creatorName") or "")[:200],
        "creator_id": d.get("creatorTargetId"),
        "creator_type": d.get("creatorType") or "User",
        "creator_verified": bool(d.get("creatorHasVerifiedBadge")),
        "asset_type_id": d.get("assetType") or 0,
        "created_at": _parse_time(d.get("itemCreatedUtc")),
    }


def _get_json(s, params):
    """One request with one polite retry on 429."""
    for attempt in range(2):
        try:
            r = s.get(SEARCH_URL, params=params, timeout=15)
        except Exception as e:
            print(f"[creator-tracker] request failed: {e}", flush=True)
            return None

        if r.status_code == 200:
            return r.json()
        if r.status_code == 429 and attempt == 0:
            try:
                wait = int(r.headers.get("Retry-After", 15))
            except (TypeError, ValueError):
                wait = 15
            time.sleep(min(max(wait, 5), 60))
            continue
        if r.status_code == 429:
            raise RateLimited()
        if r.status_code != 200:
            print(f"[creator-tracker] HTTP {r.status_code}", flush=True)
        return None
    return None


def search_creator(s, creator_id, creator_type="User", pages=MAX_PAGES):
    """Return the creator's recent catalog items."""
    items = []
    cursor = None
    for _ in range(max(1, pages)):
        params = {
            "CreatorTargetId": creator_id,
            "CreatorType": creator_type,
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


def discover_verified(s, keywords=("emote", "aura", "beanie", "hair", "wings")):
    """Bootstrap: pull popular items and keep the verified creators."""
    found = {}
    for kw in keywords:
        data = _get_json(s, {"Keyword": kw, "Limit": PAGE_SIZE, "SortType": 2})
        if not data:
            continue
        for d in data.get("data") or []:
            if d.get("creatorHasVerifiedBadge") and d.get("creatorTargetId"):
                found[(int(d["creatorTargetId"]),
                       d.get("creatorType") or "User")] = d.get("creatorName") or "?"
        time.sleep(DELAY)
    return found


# ── Database side ───────────────────────────────────────────────

def ensure_creators(cur, creators):
    """creators: {(id, type): name}"""
    added = 0
    for (cid, ctype), name in creators.items():
        cur.execute("""
            INSERT INTO tracked_creators (creator_id, creator_type, creator_name,
                                          verified, last_scanned)
            VALUES (%s, %s, %s, TRUE, NULL)
            ON CONFLICT (creator_id) DO NOTHING
        """, (cid, ctype, name))
        added += cur.rowcount or 0
    return added


def pick_batch(cur, limit=10, stale_hours=6):
    cur.execute("""
        SELECT creator_id, creator_type, creator_name
        FROM tracked_creators
        WHERE verified IS TRUE
          AND (last_scanned IS NULL
               OR last_scanned < NOW() - (%s || ' hours')::interval)
        ORDER BY last_scanned NULLS FIRST
        LIMIT %s
    """, (stale_hours, limit))
    return cur.fetchall()


def upsert_items(cur, items):
    inserted = 0
    for it in items:
        if not it.get("id"):
            continue
        cur.execute("""
            INSERT INTO items (id, name, description, favorite_count, price,
                               creator_name, creator_id, creator_verified,
                               asset_type_id, created_at, fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                favorite_count = EXCLUDED.favorite_count,
                price = EXCLUDED.price,
                creator_name = EXCLUDED.creator_name,
                creator_id = EXCLUDED.creator_id,
                creator_verified = EXCLUDED.creator_verified,
                asset_type_id = EXCLUDED.asset_type_id,
                fetched_at = CURRENT_TIMESTAMP
        """, (
            it["id"], it["name"], it["description"], it["favorite_count"],
            it["price"], it["creator_name"], it.get("creator_id"),
            it.get("creator_verified", False), it["asset_type_id"],
            it.get("created_at"),
        ))
        inserted += 1
    return inserted


def mark_scanned(cur, creator_id):
    cur.execute("""
        UPDATE tracked_creators
        SET last_scanned = CURRENT_TIMESTAMP
        WHERE creator_id = %s
    """, (creator_id,))


def run_batch(cur, limit=10):
    """Scan one batch. Returns (creators_scanned, items_upserted, discovered)."""
    s = _session()

    try:
        discovered = discover_verified(s)
    except RateLimited:
        print("[creator-tracker] rate limited during discovery — stopping", flush=True)
        return 0, 0, 0

    new_creators = ensure_creators(cur, discovered)
    cur.connection.commit()

    batch = pick_batch(cur, limit)
    if not batch:
        return 0, 0, new_creators

    scanned = 0
    upserted = 0
    budget = MAX_REQUESTS

    try:
        for cid, ctype, _name in batch:
            items = search_creator(s, cid, ctype or "User")
            upserted += upsert_items(cur, items)
            mark_scanned(cur, cid)
            cur.connection.commit()
            scanned += 1
            budget -= MAX_PAGES + 1
            if budget <= 0:
                print("[creator-tracker] request budget reached — pausing", flush=True)
                break
            time.sleep(DELAY)
    except RateLimited:
        print("[creator-tracker] rate limited — stopping batch early", flush=True)

    return scanned, upserted, new_creators
