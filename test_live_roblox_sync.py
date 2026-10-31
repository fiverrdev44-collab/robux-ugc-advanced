"""Live Marketplace sync audit (read-only).

Samples up to 3 owned items and 5 trending items, fetches their current
live Roblox data with backoff, and compares it to the local database.
Writes LIVE_MARKET_AUDIT.md and LIVE_MARKET_AUDIT.json. Never mutates anything.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from bot_core import get_db
from item_resolver import normalize_name

DETAILS_URL = "https://economy.roblox.com/v2/assets/{}/details"
FAV_URL = "https://catalog.roblox.com/v1/catalog/items/{}/details?itemType=Asset"


def _live_detail(session, item_id):
    """Return live name/price/favs/onsale for an asset, or a status marker."""
    for attempt in range(3):
        try:
            r = session.get(DETAILS_URL.format(item_id), timeout=10)
        except Exception as e:
            if attempt == 2:
                return {"blocked": f"request error: {type(e).__name__}"}
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 429:
            if attempt == 2:
                return {"blocked": "Roblox API 429"}
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 404:
            return {"deleted": True}
        if r.status_code != 200:
            return {"blocked": f"HTTP {r.status_code}"}
        d = r.json()
        out = {
            "name": (d.get("Name") or "")[:500],
            "price": d.get("PriceInRobux"),
            "onsale": d.get("IsForSale"),
        }
        try:
            r2 = session.get(FAV_URL.format(item_id), timeout=10)
            if r2.status_code == 200:
                out["favorite_count"] = r2.json().get("favoriteCount")
        except Exception:
            out["favorite_count"] = None
        return out
    return {"blocked": "Roblox API 429"}


def main():
    con = get_db()
    con.set_session(readonly=True)
    cur = con.cursor()
    try:
        cur.execute("SET statement_timeout='20s'")
        cur.execute("""
            select id, name, price, favorite_count, asset_type_id
            from items where creator_name ilike '%eroseris%'
            order by coalesce(favorite_count, 0) desc
            limit 3
        """)
        owned = cur.fetchall()
        cur.execute("""
            select id, name, price, favorite_count, asset_type_id
            from items
            where favorite_count > 0 and favorite_status = 'known'
              and asset_type_id in (61, 8, 41, 42, 43, 44, 45, 46, 47)
            order by favorite_count desc
            limit 5
        """)
        trending = cur.fetchall()
    finally:
        cur.close()
        con.close()

    seen = set()
    sample = []
    for row in owned + trending:
        if row[0] in seen:
            continue
        seen.add(row[0])
        sample.append(row)

    import requests
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; UGCBot/1.0)",
        "Accept": "application/json",
    })

    rows = []
    collected = datetime.now(timezone.utc).isoformat()
    for item_id, name, price, favs, atype in sample:
        live = _live_detail(session, item_id)
        if "blocked" in live or "deleted" in live:
            rows.append({
                "item_id": item_id, "db_name": name, "db_price": price,
                "db_favs": favs, "db_status": "unknown (no field)",
                "live_name": None, "live_price": None, "live_favs": None,
                "live_status": live.get("blocked") or "deleted",
                "name_match": None, "price_match": None, "favs_match": None,
                "note": live.get("blocked") or "deleted by API",
            })
            continue
        name_match = normalize_name(live.get("name") or "") == normalize_name(name)
        price_match = (int(live.get("price") or 0) == int(price or 0))
        favs_match = (int(live.get("favorite_count") or 0) == int(favs or 0))
        live_onsale = live.get("onsale")
        stale_flags = []
        if not name_match:
            stale_flags.append("name")
        if not price_match:
            stale_flags.append("price")
        if not favs_match:
            stale_flags.append("favs")
        if live_onsale is False and (price or 0) > 0:
            stale_flags.append("offsale-but-db-has-price")
        note = ""
        if stale_flags:
            note = "⚠️ Data may be stale (Live vs DB mismatch: " + ", ".join(stale_flags) + ")"
        rows.append({
            "item_id": item_id, "db_name": name, "db_price": price,
            "db_favs": favs, "db_status": "unknown (no field)",
            "live_name": live.get("name"), "live_price": live.get("price"),
            "live_favs": live.get("favorite_count"),
            "live_status": ("onsale" if live_onsale is True
                            else "offsale" if live_onsale is False else "unknown"),
            "name_match": name_match, "price_match": price_match,
            "favs_match": favs_match,
            "note": note,
        })
        time.sleep(1.5)

    json_path = os.path.join(ROOT, "LIVE_MARKET_AUDIT.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"collected_at_utc": collected, "rows": rows}, f, indent=2)

    md = [
        "# LIVE MARKET AUDIT — VANTA 73",
        "",
        f"Collected: `{collected}` · read-only · no item changes.",
        "",
        "| Item ID | Field | DB value | Live Roblox value | Match? | Note |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        if "live_name" in r and r["live_name"] is not None:
            for field, dbv, lv, m in (
                ("Name", r["db_name"], r["live_name"], r["name_match"]),
                ("Price", r["db_price"], r["live_price"], r["price_match"]),
                ("Favs", r["db_favs"], r["live_favs"], r["favs_match"]),
                ("Status", r["db_status"], r["live_status"], "n/a"),
            ):
                mark = "✅" if m in (True,) else ("❌" if m is False else "—")
                md.append(f"| `{r['item_id']}` | {field} | `{dbv}` | `{lv}` | {mark} | {r['note']} |")
        else:
            md.append(f"| `{r['item_id']}` | — | — | — | ❌ | {r['note']} |")
    md.append("")
    md.append("No live items were modified. 429/404 responses are marked, not faked.")
    md_path = os.path.join(ROOT, "LIVE_MARKET_AUDIT.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    for r in rows:
        print(json.dumps(r, default=str))
    print("WROTE", md_path, json_path)


if __name__ == "__main__":
    main()
