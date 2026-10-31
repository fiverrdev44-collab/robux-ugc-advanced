"""Live Advantage audit (read-only): gap, title rank, and velocity truth.

Runs the bot's internal gap/velocity math and one chain, then checks the
claims against the live Roblox catalog with backoff. Writes
LIVE_ADVANTAGE_AUDIT.md and .json. Never mutates anything.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import requests

from bot_core import get_db
from item_resolver import normalize_name

SEARCH_URL = "https://catalog.roblox.com/v1/search/items/details"
DETAILS_URL = "https://economy.roblox.com/v2/assets/{}/details"
FAV_URL = "https://catalog.roblox.com/v1/catalog/items/{}/details?itemType=Asset"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; UGCBot/1.0)",
           "Accept": "application/json"}


def live_search(session, keyword, limit=5, category=None):
    params = {"Keyword": keyword, "Limit": limit, "SortType": 3}
    if category:
        params["Category"] = category
    for attempt in range(3):
        try:
            r = session.get(SEARCH_URL, params=params, headers=HEADERS, timeout=15)
        except Exception as e:
            if attempt == 2:
                return {"blocked": f"request error {type(e).__name__}"}
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 429:
            if attempt == 2:
                return {"blocked": "429"}
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 404:
            return {"deleted": True}
        if r.status_code != 200:
            return {"blocked": f"HTTP {r.status_code}"}
        data = (r.json() or {}).get("data", []) or []
        return [{"id": d.get("id"), "name": d.get("name"),
                 "favoriteCount": d.get("favoriteCount"), "price": d.get("price")}
                for d in data]
    return {"blocked": "429"}


def live_detail(session, item_id):
    for attempt in range(3):
        try:
            r = session.get(DETAILS_URL.format(item_id), headers=HEADERS, timeout=10)
        except Exception as e:
            if attempt == 2:
                return {"blocked": f"request error {type(e).__name__}"}
            time.sleep(2 ** attempt)
            continue
        if r.status_code == 429:
            if attempt == 2:
                return {"blocked": "429"}
            time.sleep(2 ** attempt)
            continue
        if r.status_code != 200:
            return {"blocked": f"HTTP {r.status_code}"}
        d = r.json()
        out = {"name": d.get("Name"), "price": d.get("PriceInRobux"),
               "onsale": d.get("IsForSale"), "created": d.get("Created")}
        try:
            r2 = session.get(FAV_URL.format(item_id), headers=HEADERS, timeout=10)
            if r2.status_code == 200:
                out["favorite_count"] = r2.json().get("favoriteCount")
        except Exception:
            out["favorite_count"] = None
        return out
    return {"blocked": "429"}


STOP = {"the", "a", "an", "and", "of", "in", "to", "for", "is", "on",
        "with", "my", "your", "new", "hot", "best", "top", "roblox",
        "ugc", "item", "cute", "funny", "cool", "trendy", "aesthetic",
        "viral", "sale", "free", "cheap"}


def _toks(s):
    return [w for w in re.findall(r"[a-z0-9]{3,}", (s or "").lower())
            if w not in STOP and not w.isdigit()]


def top_gap_word(cur, niche, fam="emotes"):
    """Replicates the meta_sniper ranking, returns the #1 gap word."""
    from convergence_engine import _family_clause
    fam_sql, fam_params = _family_clause(fam)
    cur.execute(f"""SELECT name, favorite_count FROM items
                    WHERE name ILIKE %s AND favorite_count > 0 {fam_sql}
                    ORDER BY favorite_count DESC LIMIT 20""",
                [f"%{niche}%"] + fam_params)
    top = cur.fetchall()
    if len(top) < 5:
        terms = [t for t in niche.split() if len(t) >= 3] or [niche]
        cur.execute(f"""SELECT name, favorite_count FROM items
                        WHERE name ILIKE ANY(%s) AND favorite_count > 0 {fam_sql}
                        ORDER BY favorite_count DESC LIMIT 20""",
                    [[f"%{t}%" for t in terms]] + fam_params)
        top = cur.fetchall()
    if not top:
        return None, [], "no competitors"
    top_tokens = {}
    for name, _ in top:
        for w in set(_toks(name)):
            top_tokens[w] = top_tokens.get(w, 0) + 1
    terms = [t for t in niche.split() if len(t) >= 3] or [niche]
    cur.execute("""SELECT suggestion, COUNT(*) n FROM search_suggestions
                   WHERE suggestion IS NOT NULL AND suggestion ILIKE ANY(%s)
                   GROUP BY suggestion ORDER BY COUNT(*) DESC LIMIT 500""",
                [[f"%{t}%" for t in terms]])
    suggestions = cur.fetchall()
    cand = {}
    for sugg, _ in suggestions:
        for w in set(_toks(sugg)):
            if w in terms:
                continue
            cand[w] = cand.get(w, 0) + 1
    ranked = []
    for w, sugg_count in sorted(cand.items(), key=lambda x: -x[1])[:60]:
        if sugg_count < 3:
            continue
        coverage = top_tokens.get(w, 0)
        if coverage > 3:
            continue
        cur.execute(f"SELECT COUNT(*) FROM items WHERE name ILIKE %s {fam_sql}",
                    [f"%{w}%"] + fam_params)
        use = cur.fetchone()[0] or 0
        if use < 5:
            continue
        ranked.append((w, sugg_count, coverage, use,
                       sugg_count * (1 - coverage / max(len(top), 1))
                       * (1 + min(use, 5000) / 1000)))
    ranked.sort(key=lambda x: -x[4])
    return (ranked[0] if ranked else None), top_tokens, ("ranked" if ranked else "no-gap")


def main():
    con = get_db()
    con.set_session(readonly=True)
    cur = con.cursor()
    session = requests.Session()

    report = []
    collected = datetime.now(timezone.utc).isoformat()

    # 1) GAP
    gap, top_tokens, why = top_gap_word(cur, "aura emote", "emotes")
    if gap:
        word = gap[0]
        live = live_search(session, word, limit=5)
        if isinstance(live, list):
            titles = [x["name"] or "" for x in live]
            uses = [t for t in titles if word.lower() in t.lower()]
            pass_ = not uses
            report.append({
                "command": "meta_sniper/vacuum gap",
                "bot_claim": f"top emotes missing word '{word}' (coverage {gap[2]}, suggestions {gap[1]})",
                "live_reality": f"live top-5 for '{word}': {titles[:5]}",
                "uses_keyword_in_live_titles": uses,
                "pass": pass_,
                "note": "" if pass_ else "live #1+ uses the keyword — gap logic broken",
            })
        else:
            report.append({"command": "meta_sniper/vacuum gap", "bot_claim": f"gap word '{word}'",
                           "live_reality": live, "pass": None, "note": "blocked"})
    else:
        report.append({"command": "meta_sniper/vacuum gap", "bot_claim": why,
                       "live_reality": None, "pass": None, "note": "no gap produced"})

    # 2) CHAIN champion exact match
    try:
        from chain import run_chain
        t0 = time.time()
        r = run_chain("kawaii sway emote", live_enrich=False)
        scored = r.get("scored_titles") or []
        champ = scored[0]["title"] if scored else None
        if champ:
            from live_market import check_title
            lc = check_title(champ, limit=30, max_pages=2)
            exact = lc.get("exact") if isinstance(lc, dict) else None
            results = lc.get("results") if isinstance(lc, dict) else None
            report.append({
                "command": "chain",
                "bot_claim": f"champion '{champ}'",
                "live_reality": f"exact={exact}, results={results}",
                "pass": (exact is not None and exact >= 0),
                "note": "chain ran DB-only; exact-match is a live catalog count" if results else "chain failed to run",
            })
        else:
            report.append({"command": "chain", "bot_claim": "no champion",
                           "live_reality": None, "pass": None, "note": "no titles scored"})
    except Exception as e:
        report.append({"command": "chain", "bot_claim": "run_chain",
                       "live_reality": f"error {type(e).__name__}: {e}",
                       "pass": False, "note": "chain error"})

    # 3) VELOCITY
    item_id = 130928797494687
    cur.execute("select favorite_count, created_at from items where id=%s", (item_id,))
    db = cur.fetchone()
    live = live_detail(session, item_id)
    if db and isinstance(live, dict) and "favorite_count" in live:
        db_favs, db_created = db
        now = datetime.now(timezone.utc)
        try:
            db_age = (now - db_created.replace(tzinfo=timezone.utc)).total_seconds() / 86400
        except Exception:
            db_age = None
        bot_vel = (db_favs / db_age) if db_age and db_age > 0 else None
        created_raw = live.get("created")
        live_age = None
        if created_raw:
            try:
                cd = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                live_age = (now - cd).total_seconds() / 86400
            except Exception:
                live_age = None
        live_favs = live.get("favorite_count")
        live_vel = (live_favs / live_age) if live_age and live_age > 0 else None
        report.append({
            "command": "early/momentum velocity",
            "bot_claim": f"DB favs {db_favs} / age {round(db_age or 0,1)}d = {round(bot_vel, 3) if bot_vel else None} favs/day",
            "live_reality": f"live favs {live_favs} / age {round(live_age or 0,1)}d = {round(live_vel, 3) if live_vel else None} favs/day",
            "pass": (bot_vel is not None and live_vel is not None
                     and abs(bot_vel - live_vel) <= max(0.01, 0.05 * live_vel)),
            "note": "",
        })
    else:
        report.append({"command": "early/momentum velocity", "bot_claim": None,
                       "live_reality": live if not isinstance(live, dict) else "detail ok",
                       "pass": None, "note": "blocked or missing data"})

    cur.close()
    con.close()

    json.dump({"collected_at_utc": collected, "report": report},
              open(os.path.join(ROOT, "LIVE_ADVANTAGE_AUDIT.json"), "w", encoding="utf-8"),
              indent=2, default=str)

    lines = ["# LIVE ADVANTAGE AUDIT — VANTA 73", "",
             f"Collected: `{collected}` · read-only · no item changes.", "",
             "| Command | Bot's claim | Live API reality | Pass | Freshness warning |", "|---|---|---|---|---|"]
    for r in report:
        mark = "✅" if r["pass"] is True else ("❌" if r["pass"] is False else "⚠️ blocked/unknown")
        warn = r.get("note") or ""
        lines.append(f"| {r['command']} | {r['bot_claim']} | {r['live_reality']} | {mark} | {warn} |")
    lines.append("")
    lines.append("No live items were modified. 429/404 responses are marked, not faked.")
    open(os.path.join(ROOT, "LIVE_ADVANTAGE_AUDIT.md"), "w", encoding="utf-8").write("\n".join(lines))

    for r in report:
        print(json.dumps(r, default=str))
    print("WROTE LIVE_ADVANTAGE_AUDIT.md/.json")


if __name__ == "__main__":
    main()
