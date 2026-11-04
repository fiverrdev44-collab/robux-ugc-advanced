"""
emote_title_engine.py — Emote Reference Title Engine.

Grounded, deterministic title generation for Roblox emotes (asset type 61).

Rules baked in:
* The creator's text description is the only source of truth for what the
  emote does. Titles are built from description words only (plus the generic
  category word "Emote"); no movement is invented.
* Banned platform words (viral/trending/tiktok/youtube) are stripped, and every
  title is re-validated with the existing ASTRA checks
  (product_understanding.validate_title, family="emotes") immediately before it
  is returned.
* Research uses the database plus a bounded, read-only live Roblox search.
  A 429/outage is reported as incomplete verification; no marketplace data is
  invented.
* Optional TikTok URL metadata is public caption/hashtags only. No video is
  downloaded and no paid service is used.
"""
import re

import requests

BANNED = ("viral", "trending", "tiktok", "youtube")
PLATFORM_BANNED = set(BANNED)
STOPWORDS = {
    "the", "and", "for", "with", "your", "you", "a", "an", "of", "in", "on",
    "to", "my", "our", "is", "it", "as", "at", "by", "that", "this", "which",
    "who", "what", "when", "where", "how", "why", "from", "into", "over",
    "under", "while", "then", "than", "very", "really", "just", "like",
    "emote", "emotes", "roblox", "ugc", "new", "best", "cute", "cool",
    "it's", "its", "be", "are", "was", "were", "has", "have", "had", "do",
    "does", "did", "so", "up", "down", "out", "about", "around", "through",
}

MOTION_HINT = re.compile(
    r"\b(dance|dances|dancing|float|floats|floating|sway|sways|swaying|"
    r"spin|spins|spinning|flip|flips|flipping|wave|waves|waving|kick|kicks|"
    r"walk|walks|walking|run|runs|running|jump|jumps|jumping|sit|sits|"
    r"sitting|pose|poses|posing|lean|leans|leaning|stance|struts?|"
    r"moonwalks?|idle)\b",
    re.IGNORECASE,
)

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def strip_banned(text):
    """Remove banned platform words (case-insensitive, word boundaries)."""
    out = str(text or "")
    for word in BANNED:
        out = re.sub(rf"\b{re.escape(word)}\b", " ", out, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", out).strip()


def _has_banned(text):
    from astra import contains_banned_platform
    return contains_banned_platform(text)


def extract_keywords(text, limit=8):
    """Ordered, unique description words: no stopwords, no banned terms."""
    out, seen = [], set()
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9']{2,}", str(text or "")):
        low = tok.lower()
        if low in STOPWORDS or low in PLATFORM_BANNED or low in seen:
            continue
        if _has_banned(low):
            continue
        seen.add(low)
        out.append(low)
        if len(out) >= limit:
            break
    return out


def fetch_tiktok_meta(url, timeout=8):
    """Best-effort public caption/hashtags. Never blocks the workflow."""
    if not url:
        return {"ok": False, "error": "no url"}
    if "tiktok.com" not in url.lower():
        return {"ok": False, "error": "not a tiktok url"}
    try:
        resp = requests.get(
            url, timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; VANTA/1.0)"},
            allow_redirects=True)
        if resp.status_code != 200:
            return {"ok": False, "error": f"HTTP {resp.status_code}"}
        html = (resp.text or "")[:250000]
        caption = ""
        for prop in ("og:description", "og:title", "description"):
            m = re.search(
                rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']*)',
                html, re.IGNORECASE)
            if m:
                caption = m.group(1)
                break
        caption = strip_banned(_unescape(caption))[:300]
        tags = [strip_banned(t) for t in
                re.findall(r"#([A-Za-z0-9_]{2,30})", html)[:12]]
        tags = [t for t in tags if t and not _has_banned(t)][:8]
        return {"ok": True, "caption": caption, "hashtags": tags}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


def _unescape(text):
    import html
    return html.unescape(text or "")


def research_db(keywords):
    """Read-only DB sample of existing emotes matching the keywords."""
    pats = [f"%{k.lower()}%" for k in keywords if k]
    if not pats:
        return {"ok": True, "matches": 0, "sampled": 0,
                "note": "no keywords to query"}
    conn = None
    cur = None
    try:
        from bot_core import get_research_db
        conn = get_research_db()
        cur = conn.cursor()
        cur.execute("""
            select name, favorite_count, price
            from items
            where asset_type_id = 61
              and favorite_count > 0
              and lower(name) like any(%s)
            order by favorite_count desc
            limit 200
        """, (pats,))
        rows = cur.fetchall() or []
        examples = [{"name": (r[0] or "")[:60],
                     "favorites": int(r[1] or 0),
                     "price": int(r[2] or 0)} for r in rows[:5]]
        return {"ok": True, "matches": len(rows), "sampled": len(rows),
                "top_examples": examples,
                "note": "database matches (favorites>0), sampled — not total supply"}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__,
                "note": "database research unavailable"}
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            if conn:
                conn.close()
        except Exception:
            pass


def research_live(keywords, max_keywords=2):
    """Bounded read-only live Roblox search for emote (asset type 61)."""
    from convergence_live import verify_niche
    out = []
    for kw in list(keywords)[:max_keywords]:
        r = verify_niche(kw, family="emotes", max_pages=1)
        out.append({
            "keyword": kw,
            "ok": bool(r.get("ok")),
            "error": r.get("error"),
            "sampled_results": r.get("sampled_results"),
            "category_correct": r.get("category_correct"),
            "category_mismatched": r.get("category_mismatched"),
            "exact_title_matches": r.get("exact_title_matches"),
            "conceptual_matches": r.get("conceptual_matches"),
            "top_competitors": (r.get("top_competitors") or [])[:3],
            "verification_timestamp": r.get("verification_timestamp"),
        })
    return out


def _title(words):
    return " ".join(w.capitalize() for w in words if w)


def _candidates(description, keywords):
    """Five strategies, each built only from description words."""
    kws = [k for k in keywords if k]
    if not kws:
        kws = [w for w in re.findall(r"[A-Za-z]{3,}", strip_banned(description))
               if w.lower() not in STOPWORDS]
    if not kws:
        kws = ["original"]
    k0 = kws[0]
    k1 = kws[1] if len(kws) > 1 else k0
    k2 = kws[2] if len(kws) > 2 else k1
    k3 = kws[3] if len(kws) > 3 else k2

    raw = [
        ("Search", _title([k0, "Emote"])),
        ("Branding", _title([k0, k1, "Emote"])),
        ("Aesthetic", _title([k1, k2, "Emote"])),
        ("Community", _title([k0, k3, "Emote"])),
        ("Balanced", _title([k0, k1, k2, "Emote"])),
    ]
    # Deduplicate; extend with other grounded combinations if needed.
    out, seen = [], set()
    extras = [
        _title([k2, k0, "Emote"]),
        _title([k3, k0, "Emote"]),
        _title([k0, k2, "Emote"]),
        _title([k1, k0, "Emote"]),
        _title([k0, k1, k2, k3, "Emote"]),
    ]
    for strategy, title in raw:
        low = title.lower()
        if title and low not in seen:
            seen.add(low)
            out.append({"strategy": strategy, "title": title})
    for title in extras:
        if len(out) >= 5:
            break
        if title and title.lower() not in seen:
            seen.add(title.lower())
            out.append({"strategy": "Grounded", "title": title})
    return out[:5]


def _validate_title(description, title):
    from product_understanding import validate_title
    clean = strip_banned(title).strip()
    if not clean or _has_banned(clean):
        return None
    ok, _why = validate_title(description, clean, family="emotes")
    return clean if ok else None


def _fallback_titles(description, keywords):
    phrase = strip_banned(description).strip().rstrip(".")
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9']{2,}", phrase)
             if w.lower() not in STOPWORDS and not _has_banned(w)]
    out = []
    if words:
        out.append(_title(words[:5] + ["Emote"]))
        out.append(_title(words[:3] + ["Emote"]))
        out.append(_title(words[:2] + ["Emote"]))
        out.append(_title(words[-2:] + ["Emote"]))
    out.extend(_title([k, "Emote"]) for k in keywords[:5])
    return out


def generate(description, url=None, *, db_fn=None, live_fn=None, meta_fn=None):
    """Return validated titles, description, experiment, and research evidence."""
    raw_description = strip_banned(description).strip()
    keywords = extract_keywords(raw_description)
    meta = (meta_fn or fetch_tiktok_meta)(url) if url else {
        "ok": False, "error": "no url provided"}
    meta_keywords = []
    if meta.get("ok"):
        meta_keywords = extract_keywords(
            " ".join([meta.get("caption") or ""] + list(meta.get("hashtags") or [])))
    research_keywords = []
    seen = set()
    for k in keywords + meta_keywords:
        if k and k not in seen:
            seen.add(k)
            research_keywords.append(k)

    db = (db_fn or research_db)(research_keywords[:5])
    live = (live_fn or research_live)(research_keywords[:2])

    candidates = _candidates(raw_description, keywords)
    validated, seen_titles = [], set()
    for c in candidates:
        title = _validate_title(raw_description, c["title"])
        if title and title.lower() not in seen_titles:
            seen_titles.add(title.lower())
            validated.append({"strategy": c["strategy"], "title": title,
                              "validation": "passed"})

    # Ensure 5 when possible, using description-grounded fallbacks.
    if len(validated) < 5:
        for title in _fallback_titles(raw_description, keywords):
            if len(validated) >= 5:
                break
            clean = _validate_title(raw_description, title)
            if clean and clean.lower() not in seen_titles:
                seen_titles.add(clean.lower())
                validated.append({"strategy": "Grounded",
                                  "title": clean, "validation": "passed"})

    # Final ASTRA gate immediately before output: drop anything that fails.
    final = []
    for t in validated:
        from product_understanding import validate_title
        ok, why = validate_title(raw_description, t["title"], family="emotes")
        if ok and not _has_banned(t["title"]):
            final.append(t)
    final = final[:5]
    for i, t in enumerate(final):
        t["recommended"] = (i == 0)
    recommended = final[0]["title"] if final else None

    live_ok = bool(live) and all(r.get("ok") for r in live)
    live_error = next((r.get("error") for r in live if not r.get("ok")), None)

    return {
        "description": _build_description(raw_description, keywords),
        "titles": final,
        "recommended": recommended,
        "experiment": _build_experiment(final, live_ok, live_error),
        "keywords": keywords,
        "research_keywords": research_keywords,
        "research": {
            "db": db,
            "live": live,
            "live_ok": live_ok,
            "live_error": live_error,
            "tiktok": meta,
        },
        "banned_removed": sorted(
            {w for w in BANNED if w in str(description or "").lower()}),
    }


def _build_description(description, keywords):
    core = strip_banned(description).strip().rstrip(".")
    if not core:
        core = "A new emote concept"
    else:
        core = core[0].upper() + core[1:]
    parts = [f"{core}."]
    if keywords:
        parts.append("Built around " + ", ".join(keywords[:3]) + ".")
    parts.append("Try it in-game and tell us how it feels.")
    return " ".join(parts)


def _build_experiment(titles, live_ok, live_error):
    names = [t["title"] for t in titles[:2]]
    if len(names) == 2:
        plan = (f"Launch two variants — \"{names[0]}\" and \"{names[1]}\" — for "
                f"7 days, then keep the stronger by favorites and units.")
    elif names:
        plan = (f"Launch \"{names[0]}\" for 7 days and compare favorites and "
                f"units against your current control.")
    else:
        plan = "No validated titles were produced; do not launch yet."
    if live_ok:
        plan += " Live Roblox verification completed."
    else:
        plan += (" Live verification is incomplete"
                 + (f" ({live_error})" if live_error else "")
                 + "; sample data was not treated as complete market evidence.")
    return plan


def format_report(result):
    """Render the engine result for Discord (no banned words)."""
    titles = result.get("titles") or []
    rec = result.get("recommended")
    research = result.get("research") or {}
    db = research.get("db") or {}
    live = research.get("live") or []
    tiktok = research.get("tiktok") or {}

    lines = ["# 🎭 EMOTE TITLE ENGINE", ""]
    if rec:
        lines.append(f"## Recommended title\n**{rec}**")
    else:
        lines.append("## Recommended title\n_No title passed validation._")
    lines.append("")

    lines.append("## 5 validated titles")
    if titles:
        for i, t in enumerate(titles, 1):
            tag = "recommended" if t.get("recommended") else "alternative"
            lines.append(f"{i}. **{t['title']}** — {t['strategy']} ({tag})")
    else:
        lines.append("_No validated titles._")
    lines.append("")

    lines.append("## Final description")
    lines.append(result.get("description") or "(unavailable)")
    lines.append("")

    lines.append("## Suggested launch experiment")
    lines.append(result.get("experiment") or "(unavailable)")
    lines.append("")

    lines.append("## Evidence")
    if db.get("ok"):
        lines.append(
            f"- Database: {db.get('matches', 0)} emote name matches "
            f"(sampled, not total supply).")
        for ex in (db.get("top_examples") or [])[:3]:
            lines.append(
                f"  - `{ex['name']}` — {ex['favorites']:,}♥ · R${ex['price']}")
    else:
        lines.append(f"- Database: unavailable ({db.get('error', 'error')}).")

    if live:
        for r in live:
            if r.get("ok"):
                lines.append(
                    f"- Live `{r['keyword']}`: {r.get('category_correct', 0)} "
                    f"correct-category (asset 61) · "
                    f"{r.get('exact_title_matches', 0)} exact · "
                    f"{r.get('conceptual_matches', 0)} conceptual · "
                    f"verified {str(r.get('verification_timestamp'))[:19]}")
            else:
                lines.append(
                    f"- Live `{r['keyword']}`: **incomplete** "
                    f"({r.get('error') or 'no response'}) — no marketplace "
                    f"data was invented.")
    else:
        lines.append("- Live: not run (no research keywords).")

    if tiktok.get("ok"):
        lines.append("- TikTok reference: public caption/hashtags read; "
                     "the description remains the source of truth.")
    elif tiktok.get("error") and tiktok.get("error") != "no url provided":
        lines.append(f"- TikTok reference: unavailable ({tiktok['error']}); "
                     f"used the description only.")
    lines.append("- Titles are validated against ASTRA immediately before "
                 "output; favorites are not sales.")
    return "\n".join(lines)
