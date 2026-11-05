"""
emote_title_engine.py — Emote Reference Title Engine.

Pipeline:
1. Ground the request in the creator's description (the only source of truth
   for what the emote does).
2. Generate five titles with the project's existing free-text AI
   (gemini_brain._generate), keeping a deterministic generator as fallback.
3. Reject titles that invent movement, use protected performer/brand names,
   contain banned platform words, or use mechanical wording ("Made/Based").
4. Rank all candidates with a transparent listing-quality heuristic built from
   database + live Roblox evidence. No CTR or sales predictions are produced.
5. Validate every surviving title with the existing ASTRA checks immediately
   before output.

TikTok references are optional: only a bounded, host-validated public HTML GET
is used for caption/hashtags. No video is downloaded or analysed.
"""
import html as _html
import json
import re
from urllib.parse import urlsplit

from astra import MOTION_TOKENS, contains_banned_platform

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
    "made", "make", "based", "inspired", "using", "use", "used",
}
# Unlicensed performers/brands that must never appear in a title. Proper-noun
# extraction below also catches capitalised references not in this list.
KNOWN_PROTECTED = {
    "jabbawockeez", "kinjaz", "les twins", "world of dance",
}
MECHANICAL_WORDS = {"made", "based", "inspired"}

MAX_TIKTOK_BYTES = 512 * 1024
TIKTOK_HOST_SUFFIX = ".tiktok.com"


def strip_banned(text):
    out = str(text or "")
    for word in BANNED:
        out = re.sub(rf"\b{re.escape(word)}\b", " ", out, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", out).strip()


def _has_banned(text):
    return contains_banned_platform(text)


def _tokens(text):
    norm = _html.unescape(str(text or "")).lower()
    return set(re.findall(r"[a-z0-9']+", norm))


def _motions(text):
    return _tokens(text) & MOTION_TOKENS


def motion_grounded(description, title):
    """Reject any movement in a title that the description did not state."""
    return not (_motions(title) - _motions(description))


def extract_protected_names(text):
    """Find performer/brand references that must not be copied into titles."""
    text = str(text or "")
    protected = set()
    low = text.lower()
    for name in KNOWN_PROTECTED:
        if name in low:
            protected.add(name)
    ref = re.compile(
        r"(?i:inspired by|based on|in the style of|styled after|"
        r"referenced to|reference to)\s+"
        r"([A-Z][\w'&-]*(?:\s+[A-Z][\w'&-]*){0,3})")
    for m in ref.finditer(text):
        protected.add(m.group(1).lower())
    # Capitalised proper nouns that are not the first word of a sentence.
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        words = sentence.split()
        for word in words[1:]:
            clean = re.sub(r"[^\w'&-]", "", word)
            if re.match(r"^[A-Z][A-Za-z0-9'&-]{2,}$", clean):
                protected.add(clean.lower())
    return protected


def _protected_tokens(protected):
    tokens = set()
    for name in protected or ():
        tokens.update(re.findall(r"[a-z0-9']+", name.lower()))
    return tokens


def extract_keywords(text, limit=8, exclude=None):
    """Ordered, unique description words: no stopwords, banned, or protected."""
    protected_tokens = _protected_tokens(exclude)
    out, seen = [], set()
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9']{2,}", str(text or "")):
        low = tok.lower()
        if low in STOPWORDS or low in PLATFORM_BANNED or low in protected_tokens:
            continue
        if low in seen or _has_banned(low):
            continue
        seen.add(low)
        out.append(low)
        if len(out) >= limit:
            break
    return out


# ── Secure optional TikTok metadata ────────────────────────────────

def validate_tiktok_url(url):
    """Validate a TikTok reference without making network requests."""
    if not isinstance(url, str) or not url or len(url) > 2048:
        return None, "invalid url"
    if any(ord(ch) < 33 or ord(ch) == 127 for ch in url):
        return None, "invalid url"
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port
    except ValueError:
        return None, "malformed url"
    if parts.scheme.lower() != "https":
        return None, "https required"
    if parts.username or parts.password:
        return None, "credentials not allowed"
    if not (host == "tiktok.com" or host.endswith(TIKTOK_HOST_SUFFIX)):
        return None, "not a tiktok host"
    if port not in (None, 443):
        return None, "non-standard port"
    return host, None


def fetch_tiktok_meta(url, timeout=8, session=None):
    """Metadata fetching disabled to avoid SSRF/DNS rebinding.

    Preserve the validated URL as optional reference context, never
    claim to have read its caption or watched its video. Description-only
    generation continues without network I/O or paid APIs.
    """
    if not url:
        return {"ok": False, "error": "no url"}
    _host, err = validate_tiktok_url(url)
    if err:
        return {"ok": False, "error": err}
    return {
        "ok": False,
        "reference_valid": True,
        "error": "TikTok metadata fetching disabled for outbound safety",
    }

# ── Research ───────────────────────────────────────────────────────

def research_db(keywords):
    pats = [f"%{k.lower()}%" for k in keywords if k]
    if not pats:
        return {"ok": True, "matches": 0, "sampled": 0,
                "note": "no keywords to query"}
    conn = cur = None
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
        examples = [{"name": (r[0] or "")[:60], "favorites": int(r[1] or 0),
                     "price": int(r[2] or 0)} for r in rows[:8]]
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
    from convergence_live import verify_niche
    out = []
    for kw in list(keywords)[:max_keywords]:
        r = verify_niche(kw, family="emotes", max_pages=1)
        out.append({
            "keyword": kw, "ok": bool(r.get("ok")), "error": r.get("error"),
            "sampled_results": r.get("sampled_results"),
            "category_correct": r.get("category_correct"),
            "category_mismatched": r.get("category_mismatched"),
            "exact_title_matches": r.get("exact_title_matches"),
            "conceptual_matches": r.get("conceptual_matches"),
            "top_competitors": (r.get("top_competitors") or [])[:5],
            "verification_timestamp": r.get("verification_timestamp"),
        })
    return out


# ── Generation ─────────────────────────────────────────────────────

AI_PROMPT = """You are VANTA's Roblox emote title engine.

CREATOR DESCRIPTION (the ONLY source of truth for what the emote does):
\"\"\"{description}\"\"\"

Verified keywords: {keywords}
Protected references (must NOT appear): {protected}

Write exactly 5 distinct Roblox emote titles, one per strategy:
Search, Branding, Aesthetic, Community, Balanced.

RULES:
- Only use what the description states. Never invent movement, effects, colours, or facts.
- Never name performers or brands (if the description says "inspired by X", never write X).
- Never use: viral, trending, tiktok, youtube.
- Never use "Made", "Based", or "Inspired" in a title.
- Natural product-style names, 2-6 words, Title Case.
- Each title must be meaningfully different from the others.

Return ONLY JSON:
{{"titles":[{{"strategy":"Search","title":"..."}}, ...]}}
"""


def _default_generate(prompt, **kwargs):
    from gemini_brain import _generate
    return _generate(prompt, **kwargs)


def ai_titles(description, keywords, protected, generate_fn=None):
    prompt = AI_PROMPT.format(
        description=strip_banned(description)[:1200],
        keywords=", ".join(keywords[:10]) or "none",
        protected=", ".join(sorted(protected)) or "none")
    fn = generate_fn or _default_generate
    try:
        raw = fn(prompt, json_mode=True, temperature=0.8, max_tokens=900)
    except Exception:
        return []
    if not raw:
        return []
    data = None
    try:
        data = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:
                data = None
    rows = data.get("titles") if isinstance(data, dict) else data
    out = []
    for row in rows or []:
        if isinstance(row, dict):
            title = str(row.get("title") or "").strip().strip('"')
            strategy = str(row.get("strategy") or "AI")[:24]
        else:
            title = str(row or "").strip().strip('"')
            strategy = "AI"
        if title:
            out.append({"strategy": strategy, "title": title})
    return out[:8]


def _title(words):
    return " ".join(w.capitalize() for w in words if w)


def _candidates(description, keywords):
    """Deterministic fallback: only description words + the category word."""
    kws = [k for k in keywords if k] or [
        w for w in re.findall(r"[A-Za-z]{3,}", strip_banned(description))
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
        ("Grounded", _title([k2, k0, "Emote"])),
        ("Grounded", _title([k3, k1, "Emote"])),
        ("Grounded", _title([k0, k2, "Emote"])),
        ("Grounded", _title([k0, k1, k2, k3, "Emote"])),
    ]
    out, seen = [], set()
    for strategy, title in raw:
        low = title.lower()
        if title and low not in seen:
            seen.add(low)
            out.append({"strategy": strategy, "title": title})
    return out


def _validate_candidate(description, title, protected):
    clean = strip_banned(title).strip().strip('"').strip()
    if not clean:
        return None, "empty"
    if _has_banned(clean):
        return None, "platform word"
    if re.search(r"\b(made|based|inspired)\b", clean, re.IGNORECASE):
        return None, "mechanical wording"
    if protected and any(p and p in clean.lower() for p in protected):
        return None, "protected performer/brand"
    if _tokens(clean) & _protected_tokens(protected):
        return None, "protected performer/brand"
    if not motion_grounded(description, clean):
        return None, "invented movement"
    ok, why = validate_title(description, clean)
    if not ok:
        return None, why
    return clean, None


def validate_title(description, title):
    from product_understanding import validate_title as _vt
    return _vt(description, title, family="emotes")


def _too_similar(a, b):
    ta = {t for t in _tokens(a) if t != "emote"}
    tb = {t for t in _tokens(b) if t != "emote"}
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    return len(ta & tb) / len(ta | tb) >= 0.8


def gather_candidates(description, keywords, protected, generate_fn=None):
    ai = ai_titles(description, keywords, protected, generate_fn)
    merged = list(ai) + _candidates(description, keywords)
    out, rejected = [], []
    for c in merged:
        clean, why = _validate_candidate(description, c["title"], protected)
        if not clean:
            rejected.append({"title": c["title"], "reason": why})
            continue
        if any(_too_similar(clean, v["title"]) for v in out):
            rejected.append({"title": clean, "reason": "too similar"})
            continue
        out.append({"strategy": c.get("strategy") or "AI", "title": clean,
                    "validation": "passed"})
        if len(out) >= 5:
            break
    return out[:5], rejected


# ── Marketplace-aware ranking ──────────────────────────────────────

def _title_tokens(title):
    return {t for t in _tokens(title) if t not in {"emote", "emotes"}}


def _natural_score(title):
    words = re.findall(r"[A-Za-z0-9']+", title)
    n = len(words)
    if n < 2:
        return 0.2
    content = [w.lower() for w in words if w.lower() not in {"emote"}]
    n_content = len(content)
    if n_content <= 1:
        base = 0.55          # "<one word> Emote" is too generic
    elif 2 <= n <= 5:
        base = 1.0
    elif n == 6:
        base = 0.7
    else:
        base = 0.4
    dupes = n_content - len(set(content))
    return max(0.0, min(1.0, base - 0.2 * dupes))


def _search_score(title, description, keywords):
    tt = _title_tokens(title)
    if not tt:
        return 0.0
    desc = set(_tokens(description)) | set(keywords)
    return len(tt & desc) / len(tt)


def _competitor_names(db, live):
    names = []
    for ex in (db.get("top_examples") or []):
        names.append((ex.get("name") or "").lower())
    for r in (live or []):
        for c in (r.get("top_competitors") or []):
            names.append((c.get("name") or "").lower())
    return [n for n in names if n]


def _differentiation_score(title, names):
    if not names:
        return 0.5  # unknown, not invented
    tl = title.lower().strip()
    tt = _title_tokens(title)
    if any(n == tl for n in names):
        return 0.05
    best = 0.0
    for n in names:
        nt = _title_tokens(n)
        if nt:
            best = max(best, len(tt & nt) / max(1, len(tt | nt)))
    return max(0.05, 1.0 - 0.9 * best)


def _retrieval_score(db, live):
    """Source availability only; a successful request is NOT strong evidence."""
    db_ok = bool(db.get("ok"))
    live_ok = bool(live) and all(r.get("ok") for r in live)
    if db_ok and live_ok:
        return 1.0
    if live_ok:
        return 0.75
    if db_ok:
        return 0.6
    return 0.0


def _market_context_score(title, db, live):
    """Title-specific textual proximity to observed emote listings.

    This is a context/relevance proxy, NOT search demand, sales or CTR.
    Similarity to existing titles is also penalized separately under
    differentiation. An empty successful API response scores zero.
    """
    tokens = _title_tokens(title)
    if not tokens:
        return 0.0
    names = []
    if db.get("ok"):
        names.extend(ex.get("name") or "" for ex in db.get("top_examples") or [])
    for r in live or []:
        if r.get("ok"):
            names.extend(c.get("name") or "" for c in r.get("top_competitors") or []
                         if c.get("asset_type_id") in (61, "61"))
    similarities = []
    for name in names:
        other = _title_tokens(name)
        if other:
            similarities.append(len(tokens & other) / len(tokens | other))
    return max(similarities, default=0.0)


def rank_titles(titles, description, keywords, db, live):
    """Transparent heuristic; brief-fit is NOT verified search demand."""
    names = _competitor_names(db, live)
    retrieval = _retrieval_score(db, live)
    for t in titles:
        brief_fit = _search_score(t["title"], description, keywords)
        market_context = _market_context_score(t["title"], db, live)
        title_evidence = retrieval * market_context
        comps = {
            "accuracy": 1.0,  # eligibility/ASTRA gate, not a measured probability
            "natural": round(_natural_score(t["title"]), 3),
            "brief_fit": round(brief_fit, 3),
            "search": round(brief_fit, 3),  # backwards-compatible internal alias
            "differentiation": round(_differentiation_score(t["title"], names), 3),
            "market_context": round(market_context, 3),
            "retrieval": round(retrieval, 3),
            "evidence": round(title_evidence, 3),
        }
        score = 100 * (0.25 * comps["accuracy"] + 0.20 * comps["natural"]
                       + 0.25 * comps["brief_fit"]
                       + 0.15 * comps["differentiation"]
                       + 0.15 * comps["evidence"])
        t["score"] = round(score, 1)
        t["components"] = comps
        t["evidence_quality"] = (
            "incomplete" if retrieval < 1.0 else
            "sampled, relevant" if market_context > 0 else "sampled, no relevant matches"
        )
    titles.sort(key=lambda t: (t["score"], t["components"]["brief_fit"],
                               t["components"]["differentiation"]),
                reverse=True)
    for i, t in enumerate(titles):
        t["recommended"] = (i == 0)
    return titles

# ── Entry point ────────────────────────────────────────────────────

def generate(description, url=None, *, db_fn=None, live_fn=None,
             meta_fn=None, generate_fn=None):
    raw_description = strip_banned(description).strip()
    protected = extract_protected_names(description)
    keywords = extract_keywords(raw_description, exclude=protected)

    meta = (meta_fn or fetch_tiktok_meta)(url) if url else {
        "ok": False, "error": "no url provided"}
    meta_keywords = []
    if meta.get("ok"):
        meta_keywords = extract_keywords(
            " ".join([meta.get("caption") or ""]
                     + list(meta.get("hashtags") or [])), exclude=protected)
    research_keywords, seen = [], set()
    for k in keywords + meta_keywords:
        if k and k not in seen:
            seen.add(k)
            research_keywords.append(k)

    db = (db_fn or research_db)(research_keywords[:5])
    live = (live_fn or research_live)(research_keywords[:2])

    titles, rejected = gather_candidates(
        raw_description, keywords, protected, generate_fn=generate_fn)

    # Fill to five from deterministic, grounded combinations if needed.
    if len(titles) < 5:
        for c in _candidates(raw_description, keywords):
            if len(titles) >= 5:
                break
            clean, why = _validate_candidate(raw_description, c["title"], protected)
            if not clean:
                rejected.append({"title": c["title"], "reason": why})
                continue
            if any(_too_similar(clean, t["title"]) for t in titles):
                continue
            titles.append({"strategy": c["strategy"], "title": clean,
                           "validation": "passed"})

    # Final ASTRA gate immediately before output.
    final = []
    for t in titles:
        ok, _why = validate_title(raw_description, t["title"])
        if ok and not _has_banned(t["title"]):
            final.append(t)

    ranked = rank_titles(final[:5], raw_description, keywords, db, live)
    live_ok = bool(live) and all(r.get("ok") for r in live)
    live_error = next((r.get("error") for r in live if not r.get("ok")), None)

    return {
        "description": _build_description(raw_description, keywords,
                                          protected=protected,
                                          title=ranked[0]["title"] if ranked else None),
        "titles": ranked,
        "recommended": ranked[0]["title"] if ranked else None,
        "experiment": _build_experiment(ranked, live_ok, live_error),
        "keywords": keywords,
        "research_keywords": research_keywords,
        "protected_names": sorted(protected),
        "rejected": rejected[:10],
        "research": {
            "db": db, "live": live, "live_ok": live_ok,
            "live_error": live_error, "tiktok": meta,
        },
        "banned_removed": sorted(
            {w for w in BANNED if w in str(description or "").lower()}),
    }


def _build_description(description, keywords, protected=None, title=None):
    """Public copy from validated title and safe themes, never the raw brief."""
    blocked = _protected_tokens(protected)
    safe_terms = [
        k.lower() for k in (keywords or [])
        if k.lower() not in blocked
        and k.lower() not in STOPWORDS
        and k.lower() not in MECHANICAL_WORDS
        and not _has_banned(k)
    ][:4]
    validated_title, _why = _validate_candidate(
        description, title or "Original Emote", protected)
    display_title = validated_title or "This Emote"
    theme = " ".join(safe_terms) if safe_terms else "your chosen style"
    body = (f"Meet {display_title}, an emote centered on {theme}. "
            "Add it to your collection and favorite it if it fits your style.")
    if _has_banned(body) or (_tokens(body) & blocked):
        return ("Discover a new emote for your avatar. "
                "Add it to your collection and favorite it if it fits your style.")
    return body


def _build_experiment(titles, live_ok, live_error):
    rec = titles[0]["title"] if titles else None
    if not rec:
        return "No validated titles were produced; do not launch yet."
    plan = (
        f"For \"{rec}\", pre-register an observational launch window "
        "(e.g., 14 days). Record the publication/title-change time, "
        "daily sale units (if verified), favorites, price, and available "
        "exposure metrics. Compare against a comparable pre-change period "
        "or similar unchanged listings if available; document confounders. "
        "Roblox Marketplace viewer assignment is not controlled here, so "
        "this is NOT a randomized A/B test and does not establish causality."
    )
    if not live_ok:
        plan += (" Live competitor verification is incomplete"
                 + (f" ({live_error})" if live_error else "")
                 + "; avoid claims about verified demand.")
    return plan

def format_report(result):
    titles = result.get("titles") or []
    rec = result.get("recommended")
    research = result.get("research") or {}
    db = research.get("db") or {}
    live = research.get("live") or []
    tiktok = research.get("tiktok") or {}

    lines = ["# 🎭 EMOTE TITLE ENGINE", ""]
    lines.append("## Recommended title")
    lines.append(f"**{rec}**" if rec else "_No title passed validation._")
    lines.append("")

    lines.append("## Ranked titles (heuristics, not measured search demand/CTR/sales)")
    if titles:
        for i, t in enumerate(titles, 1):
            tag = "recommended" if t.get("recommended") else "alternative"
            c = t.get("components") or {}
            lines.append(
                f"{i}. **{t['title']}** — {t['strategy']} ({tag}) · "
                f"score {t.get('score')} "
                f"[brief-fit {c.get('brief_fit')} · natural {c.get('natural')} · "
                f"diff {c.get('differentiation')} · "
                f"market-context {c.get('market_context')} · "
                f"retrieval {c.get('retrieval')} · "
                f"title-evidence {c.get('evidence')}]")
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
        lines.append(f"- Database: {db.get('matches', 0)} emote name matches "
                     f"(sampled, not total supply).")
        for ex in (db.get("top_examples") or [])[:3]:
            lines.append(f"  - `{ex['name']}` — {ex['favorites']:,}♥ · "
                         f"R${ex['price']}")
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
                    f"data was invented; confidence is reduced.")
    else:
        lines.append("- Live: not run (no research keywords).")
    if tiktok.get("ok"):
        lines.append("- TikTok reference: optional public metadata supplied; the "
                     "description remains the source of truth.")
    elif tiktok.get("error") and tiktok.get("error") != "no url provided":
        lines.append(f"- TikTok reference: not used ({tiktok['error']}); "
                     f"description-only.")
    if result.get("protected_names"):
        lines.append("- Protected performer/brand references were excluded "
                     "from titles.")
    if result.get("rejected"):
        lines.append(f"- {len(result['rejected'])} candidate(s) rejected for "
                     "unsafe/inaccurate wording before output.")
    lines.append("- Titles are validated with ASTRA immediately before output; "
                 "favorites are not sales.")
    return "\n".join(lines)
