"""live_market.py — one-shot live Roblox marketplace cross-check.

Used to verify that a generated title is not already an exact catalog name and
to show what the live search returns. It is a first-page sample (30 results),
not a full catalog count.
"""
import re
import time

import requests

SEARCH_URL = "https://catalog.roblox.com/v1/search/items/details"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


CONCEPT_STOP = {
    "the", "and", "for", "with", "your", "you", "a", "an", "of", "in",
    "on", "to", "my", "is", "it", "as", "at", "by", "emote", "dance",
    "animation", "hat", "hair", "item", "ugc",
}


def _tokens(text):
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in CONCEPT_STOP and len(w) >= 2]


def _get_with_backoff(url, params, max_attempts=3):
    """GET with exponential backoff that honours Retry-After on 429."""
    resp = None
    for attempt in range(max_attempts):
        resp = requests.get(url, params=params, headers=HEADERS, timeout=12)
        if resp.status_code != 429:
            return resp
        if attempt == max_attempts - 1:
            return resp
        wait = 2 ** attempt
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                wait = float(retry_after)
            except (TypeError, ValueError):
                pass
        time.sleep(min(max(wait, 1.0), 60.0))
    return resp


def fetch_csrf_token(session, url):
    """Fetch an X-CSRF-TOKEN for POST endpoints.

    The catalog search used here is a GET and does not need CSRF; this helper
    exists for any future POST call that requires it.
    """
    resp = session.post(url, headers=HEADERS, timeout=12)
    return resp.headers.get("X-CSRF-TOKEN")


def check_title(title, limit=30, max_pages=10):
    title = (title or "").strip()
    if not title:
        return None
    rows, pages, cursor = [], 0, None
    try:
        while pages < max_pages:
            params = {"Keyword": title, "Limit": limit,
                      "SortType": "Relevance"}
            if cursor:
                params["Cursor"] = cursor
            r = _get_with_backoff(SEARCH_URL, params)
            pages += 1
            if r.status_code == 429:
                if rows:
                    break
                return {"ok": False, "error": "rate limited (429)"}
            if r.status_code != 200:
                if rows:
                    break
                return {"ok": False, "error": f"HTTP {r.status_code}"}
            data = r.json()
            rows.extend(data.get("data") or [])
            cursor = data.get("nextPageCursor")
            if not cursor:
                break
    except Exception as e:
        if not rows:
            return {"ok": False, "error": type(e).__name__}

    capped = bool(cursor)
    exact = [x for x in rows
             if (x.get("name") or "").strip().lower() == title.lower()]
    q_tokens = set(_tokens(title))
    top10 = rows[:10]
    related = sum(
        1 for x in top10
        if q_tokens & set(_tokens(x.get("name") or ""))
    )
    top = sorted(rows, key=lambda x: x.get("favoriteCount") or 0,
                 reverse=True)[:3]
    return {
        "ok": True,
        "title": title,
        "results": len(rows),
        "pages": pages,
        "capped": capped,
        "exact": len(exact),
        "related": related,
        "related_n": len(top10),
        "top": [
            {
                "name": (x.get("name") or "")[:48],
                "favorites": int(x.get("favoriteCount") or 0),
                "price": int(x.get("price") or 0),
            }
            for x in top
        ],
    }


def format_check(result):
    if not result:
        return None
    if not result.get("ok"):
        return (
            "## 🌐 LIVE MARKETPLACE CHECK\n"
            f"_Unavailable: {result.get('error', 'unknown')}_"
        )
    lines = [
        "## 🌐 LIVE MARKETPLACE CHECK",
        f"• Query: `{result['title']}`",
        f"• Scanned: **{result['results']}** live results across "
        f"**{result['pages']}** page(s)"
        + (" (capped)" if result.get("capped") else ""),
        f"• Exact-name matches: **{result['exact']}**",
        f"• Related results: **{result['related']}/{result['related_n']}** "
        f"share a concept word",
    ]
    for item in result.get("top", []):
        lines.append(
            f"• `{item['name']}` — **{item['favorites']:,}♥** · "
            f"R${item['price']}"
        )
    if result["results"] == 0:
        lines.append("⚠️ **No live results — demand is not proven.**")
    elif result["exact"] == 0 and result["related"] < max(3, result["related_n"] // 2):
        lines.append("⚠️ **0 exact matches, but live results are weakly related — "
                     "do not treat this as proven demand.**")
    if result["exact"] > 0:
        lines.append(
            "⚠️ **Exact name already exists in live search.** "
            "Do not call this title unique."
        )
    lines.append(
        "_Sampled live search (up to 10 pages or cap), not a full catalog count. "
        "0 exact matches is evidence, not proof of uniqueness."
        + (" Results were capped before the catalog was exhausted."
           if result.get("capped") else "") + "_"
    )
    return "\n".join(lines)
