"""live_market.py — one-shot live Roblox marketplace cross-check.

Used to verify that a generated title is not already an exact catalog name and
to show what the live search returns. It is a first-page sample (30 results),
not a full catalog count.
"""
import requests

SEARCH_URL = "https://catalog.roblox.com/v1/search/items/details"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


def check_title(title, limit=30):
    title = (title or "").strip()
    if not title:
        return None
    try:
        r = requests.get(
            SEARCH_URL,
            params={"Keyword": title, "Limit": limit, "SortType": "Relevance"},
            headers=HEADERS,
            timeout=12,
        )
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}
    if r.status_code == 429:
        return {"ok": False, "error": "rate limited (429)"}
    if r.status_code != 200:
        return {"ok": False, "error": f"HTTP {r.status_code}"}
    try:
        rows = r.json().get("data", []) or []
    except Exception:
        return {"ok": False, "error": "bad JSON"}
    exact = [x for x in rows
             if (x.get("name") or "").strip().lower() == title.lower()]
    top = sorted(rows, key=lambda x: x.get("favoriteCount") or 0,
                 reverse=True)[:3]
    return {
        "ok": True,
        "title": title,
        "results": len(rows),
        "exact": len(exact),
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
        f"• First-page results: **{result['results']}** · "
        f"exact-name matches: **{result['exact']}**",
    ]
    for item in result.get("top", []):
        lines.append(
            f"• `{item['name']}` — **{item['favorites']:,}♥** · "
            f"R${item['price']}"
        )
    lines.append(
        "_First page of Roblox search, not a full catalog count._"
    )
    return "\n".join(lines)
