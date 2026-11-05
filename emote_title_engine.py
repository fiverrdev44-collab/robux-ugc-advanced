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

Rate-limit coordination
-----------------------
``RobloxBatchClient`` hydrates item details by asset ID (POST batch); catalog
keyword search is a different endpoint and cannot be folded into an asset-ID
batch. Other modules (``live_market.check_title``, ``live_enrich``,
``creator_tracker``, ``enricher``) retain their own pacing. This engine uses
the shared convergence endpoint-aware scheduler, shortlists phrases in
PostgreSQL before live calls, and stops/defer on the first 429 rather than
spending more of the shared quota.
"""
import html as _html
import json
import re
from datetime import datetime, timezone
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

# Creator-instruction / filler words that are not product characteristics.
INSTRUCTION_WORDS = {
    "created", "create", "creating", "made", "make", "making", "new",
    "want", "wanted", "original", "memorable", "searchable", "premium",
    "inspired", "based", "using", "use", "used", "need", "needs", "looking",
    "idea", "ideas", "concept", "concepts", "design", "designs", "please",
    "help", "would", "could", "should", "give", "build", "building", "built",
    "designed", "roblox", "ugc", "im", "ive", "we", "i",
}
# Heads that turn adjacent modifiers into a useful marketplace phrase.
CONCEPT_HEADS = {
    "dance", "emote", "pose", "movement", "choreography", "performance",
    "style", "groove",
}

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


def _content_tokens(text, exclude=None):
    """Ordered content tokens with instructions/stopwords/protected removed."""
    protected_tokens = _protected_tokens(exclude)
    out = []
    for tok in re.findall(r"[A-Za-z][A-Za-z0-9']{2,}", str(text or "")):
        low = tok.lower()
        if (low in STOPWORDS or low in INSTRUCTION_WORDS
                or low in PLATFORM_BANNED or low in protected_tokens
                or _has_banned(low)):
            continue
        out.append(low)
    return out


def extract_keywords(text, limit=8, exclude=None):
    """Ordered, unique product words (no instructions, stopwords, protected)."""
    out, seen = [], set()
    for low in _content_tokens(text, exclude):
        if low in seen:
            continue
        seen.add(low)
        out.append(low)
        if len(out) >= limit:
            break
    return out


def extract_concepts(text, limit=12, exclude=None):
    """Multiword marketplace concepts grounded in the description.

    Example: "I created ... a mysterious, energetic street dance with a
    powerful hip-hop performance style" yields phrases such as
    "mysterious energetic street dance", "energetic street dance",
    "street dance", "hip hop dance", "mysterious dance".

    Only words from the description are used; no choreography is invented.
    """
    toks = _content_tokens(text, exclude)
    if not toks:
        return []
    concepts, seen = [], set()

    def add(words):
        phrase = " ".join(words).strip()
        if len(phrase) < 4 or phrase in seen:
            return
        seen.add(phrase)
        concepts.append(phrase)

    # Contiguous n-grams (most natural phrases first).
    for n in (3, 2):
        for i in range(len(toks) - n + 1):
            add(toks[i:i + n])

    # Modifier + head combinations within the same clause.
    for i, tok in enumerate(toks):
        if tok not in CONCEPT_HEADS:
            continue
        for k in (1, 2, 3):
            if i - k >= 0:
                add(toks[i - k:i + 1])
        for j in range(max(0, i - 4), i):
            add([toks[j], tok])

    # Known dance compounds, plus compound + head.
    joined = " ".join(toks)
    for comp in ("hip hop", "street dance"):
        if comp in joined:
            add(comp.split())
            for head in ("dance", "emote", "pose"):
                if head in toks and head not in comp.split():
                    add(comp.split() + [head])

    def rank(phrase):
        words = phrase.split()
        ends_head = 1 if words[-1] in CONCEPT_HEADS else 0
        has_head = 1 if any(w in CONCEPT_HEADS for w in words) else 0
        is_compound = 1 if phrase in ("hip hop", "street dance") else 0
        return (ends_head, is_compound, has_head, len(words))

    concepts.sort(key=rank, reverse=True)
    return concepts[:limit]


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

def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def research_db(concepts):
    """Shortlist high-value phrases against emote listings before live calls.

    Each phrase is matched only when ALL of its tokens occur in the item name
    (phrase evidence), and exact-phrase hits are counted separately. This is a
    read-only local sample, never total marketplace supply.
    """
    phrases = [p.strip().lower() for p in (concepts or []) if p and p.strip()]
    if not phrases:
        return {"ok": True, "matches": 0, "sampled": 0, "phrases": [],
                "live_shortlist": [], "note": "no concepts to query"}
    conn = cur = None
    try:
        from bot_core import get_research_db
        conn = get_research_db()
        cur = conn.cursor()
        stats = []
        all_exact = []
        for phrase in phrases[:5]:
            tokens = [t for t in phrase.split() if t]
            if not tokens:
                continue
            exact_pat = f"%{phrase}%"
            token_pats = [f"%{t}%" for t in tokens]
            cur.execute("""
                select count(*),
                       count(*) filter (where lower(name) like %s)
                from items
                where asset_type_id = 61
                  and favorite_count > 0
                  and lower(name) like all(%s)
            """, (exact_pat, token_pats))
            total, exact = cur.fetchone()
            stats.append({"phrase": phrase,
                          "token_matches": int(total or 0),
                          "exact_matches": int(exact or 0),
                          "tokens": len(tokens)})
            all_exact.append(exact_pat)

        examples = []
        if all_exact:
            cur.execute("""
                select name, favorite_count, price
                from items
                where asset_type_id = 61
                  and favorite_count > 0
                  and lower(name) like any(%s)
                order by favorite_count desc
                limit 8
            """, (all_exact,))
            examples = [{"name": (r[0] or "")[:60],
                         "favorites": int(r[1] or 0),
                         "price": int(r[2] or 0)} for r in (cur.fetchall() or [])]

        shortlist = sorted(
            [s for s in stats if s["token_matches"] > 0],
            key=lambda s: (s["tokens"], s["token_matches"]),
            reverse=True)
        if not shortlist:
            shortlist = sorted(stats, key=lambda s: s["tokens"], reverse=True)
        return {"ok": True,
                "matches": sum(s["token_matches"] for s in stats),
                "sampled": sum(s["token_matches"] for s in stats),
                "phrases": stats,
                "live_shortlist": [s["phrase"] for s in shortlist[:3]],
                "top_examples": examples,
                "note": ("database phrase matches (favorites>0), sampled — "
                         "not total supply")}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__,
                "phrases": [], "live_shortlist": [],
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


def research_live(phrases, max_queries=2):
    """Bounded live Roblox emote (asset type 61) keyword search.

    Stops after the first rate-limit/outage so optional verification is
    deferred instead of hammering the endpoint. Each record carries an honest
    checked_at timestamp; remaining phrases are listed on the deferred record.
    """
    from convergence_live import verify_niche
    wanted = [p for p in (phrases or []) if p][:max_queries]
    out = []
    for idx, phrase in enumerate(wanted):
        r = verify_niche(phrase, family="emotes", max_pages=1)
        rec = {
            "keyword": phrase,
            "ok": bool(r.get("ok")),
            "error": r.get("error"),
            "sampled_results": r.get("sampled_results"),
            "category_correct": r.get("category_correct"),
            "category_mismatched": r.get("category_mismatched"),
            "exact_title_matches": r.get("exact_title_matches"),
            "conceptual_matches": r.get("conceptual_matches"),
            "top_competitors": (r.get("top_competitors") or [])[:5],
            "checked_at": r.get("verification_timestamp") or _utc_now(),
        }
        out.append(rec)
        if not rec["ok"]:
            remaining = wanted[idx + 1:]
            rec["deferred"] = True
            if remaining:
                rec["deferred_phrases"] = remaining
            break
    return out


def title_db_exact(title):
    """Local check for an exact emote title before any live request."""
    conn = cur = None
    try:
        from bot_core import get_research_db
        conn = get_research_db()
        cur = conn.cursor()
        cur.execute("""
            select 1 from items
            where asset_type_id = 61 and lower(name) = lower(%s)
            limit 1
        """, (title,))
        return {"ok": True, "exact": cur.fetchone() is not None,
                "checked_at": _utc_now(), "source": "database"}
    except Exception as e:
        return {"ok": False, "exact": False, "error": type(e).__name__,
                "checked_at": _utc_now(), "source": "database"}
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


def verify_titles(titles, max_titles=2, db_fn=None, live_fn=None):
    """Verify the strongest final titles against actual Marketplace titles.

    Local database exact-title evidence is checked first. At most two titles
    are checked live; a rate limit/outage defers the rest and is reported as
    insufficient evidence.
    """
    out = []
    for t in list(titles or [])[:max_titles]:
        title = t["title"]
        local = (db_fn or title_db_exact)(title)
        if local.get("ok") and local.get("exact"):
            out.append({"title": title, "status": "exact",
                        "source": "database", "exact": True,
                        "similar": False, "conceptual": False,
                        "checked_at": local.get("checked_at"),
                        "error": None})
            continue
        r = (live_fn or _title_live_check)(title)
        if not r.get("ok"):
            out.append({"title": title, "status": "insufficient",
                        "source": "live", "exact": False, "similar": False,
                        "conceptual": False,
                        "checked_at": r.get("checked_at") or _utc_now(),
                        "error": r.get("error")})
            break
        exact = int(r.get("exact_title_matches") or 0) > 0
        competitors = [c for c in (r.get("top_competitors") or [])
                       if c.get("asset_type_id") in (61, "61")]
        tt = _title_tokens(title)
        similar = any(
            tt and _title_tokens(c.get("name") or "")
            and len(tt & _title_tokens(c.get("name") or ""))
            / max(1, len(tt | _title_tokens(c.get("name") or ""))) >= 0.5
            for c in competitors)
        conceptual = int(r.get("conceptual_matches") or 0) > 0
        status = ("exact" if exact else "similar" if similar
                  else "conceptual" if conceptual else "none")
        out.append({"title": title, "status": status, "source": "live",
                    "exact": exact, "similar": similar,
                    "conceptual": conceptual,
                    "checked_at": r.get("checked_at") or _utc_now(),
                    "error": None})
    return out


def _title_live_check(title):
    from convergence_live import verify_niche
    r = verify_niche(title, family="emotes", max_pages=1)
    return {
        "ok": bool(r.get("ok")),
        "error": r.get("error"),
        "exact_title_matches": r.get("exact_title_matches"),
        "conceptual_matches": r.get("conceptual_matches"),
        "top_competitors": r.get("top_competitors") or [],
        "checked_at": r.get("verification_timestamp") or _utc_now(),
    }


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


def gather_candidates(description, keywords, protected, concepts=None,
                      generate_fn=None):
    ai = ai_titles(description, concepts or keywords, protected, generate_fn)
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
    live_ok = (bool(live) and all(r.get("ok") for r in live)
               and not any(r.get("deferred") for r in live))
    if db_ok and live_ok:
        return 1.0
    if live_ok:
        return 0.75
    if db_ok:
        return 0.6
    return 0.0


def _keyword_context_score(title, db, live):
    """Informational keyword-sample similarity; never title verification."""
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


def _title_check_map(title_checks):
    return {c.get("title"): c for c in (title_checks or []) if c.get("title")}


def _verified_components(check):
    """(verified_similarity, verified_competition, verified?, status)."""
    status = (check or {}).get("status")
    if status == "exact":
        return 0.0, 0.0, 1.0, "exact"
    if status == "similar":
        return 0.3, 0.4, 1.0, "similar"
    if status == "conceptual":
        return 0.6, 0.6, 1.0, "conceptual"
    if status == "none":
        return 1.0, 1.0, 1.0, "none"
    return 0.5, 0.5, 0.0, "insufficient"


def rank_titles(titles, description, concepts, db, live, title_checks=None):
    """Transparent heuristic. Description overlap is NEVER market evidence.

    Components are kept separate: product accuracy, natural readability,
    semantic relevance, verified marketplace similarity, verified competition,
    evidence completeness, and unknown demand. The final score is a listing
    heuristic, not CTR or predicted sales, and is discounted when evidence is
    incomplete.
    """
    checks = _title_check_map(title_checks)
    retrieval = _retrieval_score(db, live)
    for t in titles:
        semantic = _search_score(t["title"], description, concepts)
        natural = _natural_score(t["title"])
        check = checks.get(t["title"])
        vsim, vcomp, verified, status = _verified_components(check)
        completeness = 0.5 * retrieval + 0.5 * verified
        kw_context = _keyword_context_score(t["title"], db, live)
        base = (0.25 * 1.0 + 0.20 * natural + 0.25 * semantic
                + 0.15 * vsim + 0.15 * vcomp)
        score = 100 * base * (0.6 + 0.4 * completeness)
        if status == "exact":
            score *= 0.5   # an existing exact title is a serious negative
        elif status == "similar":
            score *= 0.8
        comps = {
            "accuracy": 1.0,
            "product_accuracy": 1.0,
            "natural": round(natural, 3),
            "natural_readability": round(natural, 3),
            "search": round(semantic, 3),
            "brief_fit": round(semantic, 3),
            "semantic_relevance": round(semantic, 3),
            "differentiation": round(vsim, 3),
            "verified_similarity": round(vsim, 3),
            "verified_competition": round(vcomp, 3),
            "evidence": round(completeness, 3),
            "evidence_completeness": round(completeness, 3),
            "retrieval": round(retrieval, 3),
            "market_context": round(kw_context, 3),
            "keyword_sample_context": round(kw_context, 3),
            "unknown_demand": "unknown",
        }
        t["score"] = round(score, 1)
        t["components"] = comps
        t["title_check"] = check
        t["title_check_status"] = status
        t["evidence_status"] = (
            "verified" if completeness >= 0.99 else
            "partial" if completeness > 0 else "insufficient")
    titles.sort(key=lambda t: (t["score"], t["components"]["natural"],
                               t["components"]["semantic_relevance"]),
                reverse=True)
    for i, t in enumerate(titles):
        t["recommended"] = (i == 0)
    return titles

# ── Entry point ────────────────────────────────────────────────────

def generate(description, url=None, *, db_fn=None, live_fn=None,
             meta_fn=None, generate_fn=None, title_db_fn=None,
             title_live_fn=None):
    raw_description = strip_banned(description).strip()
    protected = extract_protected_names(description)
    keywords = extract_keywords(raw_description, exclude=protected)
    concepts = extract_concepts(raw_description, exclude=protected)

    meta = (meta_fn or fetch_tiktok_meta)(url) if url else {
        "ok": False, "error": "no url provided"}
    meta_concepts = []
    if meta.get("ok"):
        meta_concepts = extract_concepts(
            " ".join([meta.get("caption") or ""]
                     + list(meta.get("hashtags") or [])), exclude=protected)

    # Concepts first; single words are only a fallback so we never spend a
    # scarce live request on generic instructions such as "created".
    research_concepts, seen = [], set()
    for c in concepts + meta_concepts + keywords:
        if c and c not in seen:
            seen.add(c)
            research_concepts.append(c)

    db = (db_fn or research_db)(research_concepts[:5])
    live_shortlist = (db.get("live_shortlist")
                      or research_concepts[:2])[:2]
    live = (live_fn or research_live)(live_shortlist)

    titles, rejected = gather_candidates(
        raw_description, keywords, protected, concepts=concepts,
        generate_fn=generate_fn)

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

    initial = rank_titles(final[:5], raw_description, concepts, db, live)

    # Title-level verification: local DB first; live only if keyword research
    # was not already rate-limited. At most two titles are checked.
    live_limited = any(not r.get("ok") for r in live)
    if live_limited:
        deferred_live = lambda title: {
            "ok": False, "error": "deferred after rate limit",
            "checked_at": _utc_now()}
        checks = verify_titles(initial[:2], db_fn=title_db_fn,
                               live_fn=deferred_live)
    else:
        checks = verify_titles(initial[:2], db_fn=title_db_fn,
                               live_fn=title_live_fn)

    ranked = rank_titles(final[:5], raw_description, concepts, db, live,
                         title_checks=checks)
    live_ok = (bool(live) and all(r.get("ok") for r in live)
               and not any(r.get("deferred") for r in live))
    live_error = next((r.get("error") for r in live if not r.get("ok")), None)
    deferred = (any(r.get("deferred") for r in live)
                or any(c.get("status") == "insufficient" for c in checks))

    return {
        "description": _build_description(
            raw_description, concepts, protected=protected,
            title=ranked[0]["title"] if ranked else None),
        "titles": ranked,
        "recommended": ranked[0]["title"] if ranked else None,
        "experiment": _build_experiment(ranked, live_ok, live_error),
        "keywords": keywords,
        "concepts": concepts,
        "research_keywords": research_concepts,
        "title_checks": checks,
        "protected_names": sorted(protected),
        "rejected": rejected[:10],
        "research": {
            "db": db, "live": live, "live_ok": live_ok,
            "live_error": live_error, "live_deferred": deferred,
            "title_checks": checks, "tiktok": meta,
        },
        "banned_removed": sorted(
            {w for w in BANNED if w in str(description or "").lower()}),
    }


def _clean_descriptive_clause(description, protected=None):
    """Remove creator instructions/references; keep natural product copy."""
    text = str(description or "")
    text = re.sub(
        r"^\s*(?:i|we|he|she|they)\s+"
        r"(?:created|made|built|designed|want|wanted)\b[^.]*?\bemote\b[^.]*\.?\s*",
        " ", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\b(?:inspired by|based on|in the style of|styled after)\s+"
        r"[A-Z][\w'&-]*(?:\s+[A-Z][\w'&-]*){0,3}",
        " ", text)
    for name in sorted(protected or (), key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(name)}\b", " ", text, flags=re.IGNORECASE)
    for word in sorted(INSTRUCTION_WORDS | set(BANNED), key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(word)}\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[^\w]+", "", text)
    return text


def _build_description(description, concepts, protected=None, title=None):
    """Natural marketplace copy; never instructions or a keyword dump."""
    display_title = title or "This Emote"
    clause = _clean_descriptive_clause(description, protected)
    if clause and len(clause.split()) >= 3:
        body = (f"Meet {display_title}. {clause.rstrip('.')}. "
                "Add it to your collection and favorite it if it fits your style.")
    else:
        primary = (concepts or ["your chosen style"])[0]
        secondary = next((c for c in (concepts or [])[1:]
                          if c not in primary), None)
        theme = f"{primary} with {secondary}" if secondary else primary
        body = (f"Meet {display_title} — {theme}. "
                "Add it to your collection and favorite it if it fits your style.")
    if (_has_banned(body)
            or (_tokens(body) & _protected_tokens(protected))
            or re.search(r"\b(created|centered on|built around|inspired by|"
                         r"based on|extracted|keywords?)\b", body,
                         re.IGNORECASE)):
        body = ("Discover a new emote for your avatar. "
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

    lines.append("## Ranked titles (heuristic, not CTR/sales/measured demand)")
    if titles:
        for i, t in enumerate(titles, 1):
            tag = "recommended" if t.get("recommended") else "alternative"
            c = t.get("components") or {}
            lines.append(
                f"{i}. **{t['title']}** — {t['strategy']} ({tag}) · "
                f"score {t.get('score')} "
                f"[accuracy {c.get('product_accuracy')} · "
                f"natural {c.get('natural_readability')} · "
                f"semantic {c.get('semantic_relevance')} · "
                f"verified-sim {c.get('verified_similarity')} · "
                f"verified-comp {c.get('verified_competition')} · "
                f"evidence {c.get('evidence_completeness')}] · "
                f"market evidence: {t.get('evidence_status', 'insufficient')} · "
                f"demand: unknown")
    else:
        lines.append("_No validated titles._")
    lines.append("")

    lines.append("## Final description")
    lines.append(result.get("description") or "(unavailable)")
    lines.append("")

    lines.append("## Suggested launch experiment")
    lines.append(result.get("experiment") or "(unavailable)")
    lines.append("")

    lines.append("## Title-level verification")
    checks = result.get("title_checks") or research.get("title_checks") or []
    if checks:
        labels = {"exact": "exact title match",
                  "similar": "similar title",
                  "conceptual": "conceptual competitor",
                  "none": "no matching title in sample",
                  "insufficient": "insufficient live evidence"}
        for c in checks:
            lines.append(
                f"- `{c.get('title')}` — **{labels.get(c.get('status'), 'unknown')}**"
                f" · checked {str(c.get('checked_at'))[:19]}"
                + (f" ({c['error']})" if c.get("error") else ""))
    else:
        lines.append("- Not run (no validated titles or deferred by rate limit).")
    lines.append("")

    lines.append("## Evidence")
    lines.append(f"- Research concepts: {', '.join(result.get('concepts') or []) or 'none'}")
    if db.get("ok"):
        lines.append(f"- Database: {db.get('matches', 0)} phrase/token matches "
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
                    f"- Keyword sample `{r['keyword']}`: "
                    f"{r.get('category_correct', 0)} correct-category "
                    f"(asset 61) · {r.get('conceptual_matches', 0)} conceptual "
                    f"keyword matches (keyword-level, not candidate-title "
                    f"match) · checked {str(r.get('checked_at') or r.get('verification_timestamp'))[:19]}")
            else:
                lines.append(
                    f"- Keyword sample `{r['keyword']}`: **incomplete** "
                    f"({r.get('error') or 'no response'}) — no marketplace data "
                    f"was invented."
                    + (" Remaining optional verification was deferred."
                       if r.get("deferred") else ""))
    else:
        lines.append("- Live keyword research: not run.")
    if research.get("live_deferred"):
        lines.append("- Live verification was limited; evidence is incomplete "
                     "and no demand claim is made.")
    if tiktok.get("ok"):
        lines.append("- TikTok reference: optional public metadata supplied; the "
                     "description remains the source of truth.")
    elif tiktok.get("error") and tiktok.get("error") != "no url provided":
        lines.append(f"- TikTok reference: not used ({tiktok['error']}); "
                     f"description-only.")
    if result.get("protected_names"):
        lines.append("- Protected performer/brand references were excluded "
                     "from titles and public copy.")
    if result.get("rejected"):
        lines.append(f"- {len(result['rejected'])} candidate(s) rejected for "
                     "unsafe/inaccurate wording before output.")
    lines.append("- Titles are validated with ASTRA immediately before output; "
                 "favorites are not sales; demand is unknown.")
    return "\n".join(lines)
