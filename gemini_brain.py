"""
gemini_brain.py — 2-pass hybrid AI layer for the Roblox UGC bot.

Pass 1 (extract_keywords): casual description -> structured intent JSON.
Database query happens in the bot, building an allow-list of REAL keywords.
Pass 2 (synthesize_hybrid): intent + real DB data -> titles + strategy.
verify_titles(): hard gate — every word in every title must be in the allow-list.

Rule: DB is truth. Gemini interprets, never invents.
"""

import os
import re
import json
import google.generativeai as genai

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

_configured = False
_model = None

# Small universal whitelist so titles can contain glue words + numbers safely.
STOPWORDS = {
    "a", "an", "the", "of", "and", "or", "for", "to", "in", "on", "with",
    "my", "your", "at", "by", "is", "it", "as",
}


def _ensure():
    """Lazy-init Gemini client. Returns True if usable."""
    global _configured, _model
    if _configured:
        return _model is not None
    _configured = True

    if not GEMINI_API_KEY:
        print("[gemini] GEMINI_API_KEY not set")
        return False

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        _model = genai.GenerativeModel(MODEL_NAME)
        print(f"[gemini] configured model={MODEL_NAME}")
        return True
    except Exception as e:
        print(f"[gemini] configure failed: {e}")
        _model = None
        return False


def is_available() -> bool:
    return _ensure()


def _generate(prompt: str, json_mode: bool = False, temperature: float = 0.7):
    """Single call wrapper with error swallowing so bot never crashes."""
    if not _ensure():
        return None
    try:
        cfg = {"temperature": temperature}
        if json_mode:
            cfg["response_mime_type"] = "application/json"
        resp = _model.generate_content(prompt, generation_config=cfg)
        return (resp.text or "").strip()
    except Exception as e:
        print(f"[gemini] generate failed: {e}")
        return None


# ---------------------------------------------------------------------------
# PASS 1 — Extraction
# ---------------------------------------------------------------------------
_EXTRACT_PROMPT = """You are a keyword extraction engine for Roblox UGC item titles.

The user describes an item they want to create in casual language.
Extract structured search intent. Return ONLY valid JSON matching this schema:

{
  "primary":     ["..."],
  "synonyms":    ["..."],
  "style":       ["..."],
  "vibe":        ["..."],
  "colors":      ["..."],
  "references":  ["..."],
  "search_terms":["..."]
}

Rules:
- Lowercase. Single words or short 2-word phrases only.
- No punctuation, emojis, or sentences.
- 2-8 entries per field. Empty array [] if not applicable.
- "search_terms" = the 10-15 most important words/phrases to look up
  in a Roblox item database. This is the field that matters most.
- Do NOT invent Roblox item names or brand names. Only extract intent.
- Never output anything except the JSON object.

User description: {desc}
"""


def extract_keywords(casual_description: str) -> dict:
    """Pass 1. Returns a dict of structured intent, or {} on failure."""
    if not casual_description or not casual_description.strip():
        return {}

    prompt = _EXTRACT_PROMPT.format(desc=casual_description.strip())
    raw = _generate(prompt, json_mode=True, temperature=0.3)
    if not raw:
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # try to salvage a JSON block
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
        except Exception:
            return {}

    # Normalize: ensure all keys exist and are lists of clean strings
    keys = ["primary", "synonyms", "style", "vibe",
            "colors", "references", "search_terms"]
    clean = {}
    for k in keys:
        val = data.get(k, [])
        if isinstance(val, str):
            val = [val]
        if not isinstance(val, list):
            val = []
        clean[k] = [str(v).lower().strip() for v in val if str(v).strip()]
    return clean


def all_terms(intent: dict) -> list:
    """Flatten every extracted term into one deduped list."""
    seen, out = set(), []
    for k in ("primary", "synonyms", "style", "vibe",
              "colors", "references", "search_terms"):
        for t in intent.get(k, []):
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return out


# ---------------------------------------------------------------------------
# PASS 2 — Synthesis
# ---------------------------------------------------------------------------
_SYNTH_PROMPT = """You are a top Roblox UGC strategist. You write item titles that rank.

You will receive:
1. The creator's casual description of what they want to make.
2. An ALLOW-LIST of real keywords pulled from an actual Roblox item database.
3. Top 10 real competing items with their favourite counts and prices.
4. Market stats (item count, price min/avg/max).

RULES — READ CAREFULLY:
- Titles may ONLY use words from the ALLOW-LIST (plus tiny glue words:
  a, an, the, of, and, or, for, to, in, on, with, my, your, numbers).
- Do NOT invent keywords, brands, or item names.
- Do NOT fabricate prices or stats. Only use numbers you were given.
- Use your own knowledge for: Roblox algorithm behaviour, meme/TikTok culture,
  anime/K-pop context, upload timing, price psychology, aesthetic trends.
- Be specific, deep, and strategic. No generic filler.

Return ONLY valid JSON matching this schema:
{
  "titles":           ["title 1", "title 2", "title 3"],
  "diagnosis":        "what the market currently looks like and why",
  "price_reasoning":  "recommended price band and reasoning",
  "seo_description":  "2-3 sentence Roblox item description, keyword-rich",
  "killer_keywords":  ["..."],
  "verdict":          "go / no-go and why",
  "algo_tip":         "specific Roblox algorithm insight",
  "trend_analysis":   "what is rising or dying in this niche",
  "cultural_relevance":"meme/anime/K-pop/TikTok context"
}

INPUT:
USER DESCRIPTION:
{desc}

ALLOW-LIST ({allow_count} keywords):
{allow_list}

TOP COMPETING ITEMS:
{top_items}

MARKET STATS:
{market_stats}
"""


def synthesize_hybrid(casual_description: str,
                      allow_list: list,
                      top_items: list,
                      market_stats: dict) -> dict:
    """Pass 2. Returns structured strategy dict, or {} on failure."""
    if not allow_list:
        return {}

    top_lines = []
    for it in top_items[:10]:
        name = (it.get("name") or "")[:80]
        favs = it.get("favourite_count") or 0
        price = it.get("price")
        price_s = f"R${price}" if price not in (None, 0) else "free/unknown"
        top_lines.append(f"- {name} | favs={favs} | price={price_s}")

    stats_lines = [
        f"- items matched: {market_stats.get('count', 0)}",
        f"- price min: {market_stats.get('price_min')}",
        f"- price avg: {market_stats.get('price_avg')}",
        f"- price max: {market_stats.get('price_max')}",
        f"- total sales (matched): {market_stats.get('total_sales', 0)}",
    ]

    prompt = _SYNTH_PROMPT.format(
        desc=casual_description.strip(),
        allow_count=len(allow_list),
        allow_list=", ".join(allow_list),
        top_items="\n".join(top_lines) or "(none)",
        market_stats="\n".join(stats_lines),
    )

    raw = _generate(prompt, json_mode=True, temperature=0.85)
    if not raw:
        return {}

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Verification — the hard gate
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list:
    return _TOKEN_RE.findall((text or "").lower())


def verify_titles(titles: list, allow_list: list):
    """
    Returns (valid_titles, rejected_list).

    valid_titles -> list of titles where every meaningful token is either:
        - in the allow-list (as substring for plurals), or
        - in STOPWORDS, or
        - a pure number.
    rejected_list -> list of (title, [bad_words]).
    """
    allow_set = {t.lower().strip() for t in allow_list if t and t.strip()}
    valid, rejected = [], []

    for title in titles or []:
        if not isinstance(title, str) or not title.strip():
            continue
        bad = []
        for tok in _tokens(title):
            if tok in STOPWORDS:
                continue
            if tok.isdigit():
                continue
            if tok in allow_set:
                continue
            # plural / suffix tolerance against allow-list entries
            if any(tok.startswith(a) or a.startswith(tok)
                   for a in allow_set if len(a) >= 4):
                continue
            bad.append(tok)

        if bad:
            rejected.append((title, bad))
        else:
            valid.append(title)

    return valid, rejected


# ---------------------------------------------------------------------------
# Free-form Q&A
# ---------------------------------------------------------------------------
_ASK_PROMPT = """You are a Roblox UGC market strategist embedded in a Discord bot.
Answer the user's question using your knowledge of:
- Roblox UGC algorithm and discoverability
- Meme, TikTok, anime, and K-pop culture
- Pricing psychology and upload timing
- Aesthetic movements and trend cycles

If the user asks for numbers, stats, or specific item names you were not given,
say plainly that you cannot verify that and suggest using the data commands.
Be concrete, deep, and strategic. No filler. No disclaimers about being an AI.
Keep it under 1,800 characters unless the question clearly needs more.

QUESTION:
{q}
"""


def ask_ai(question: str) -> str:
    if not question or not question.strip():
        return ""
    out = _generate(_ASK_PROMPT.format(q=question.strip()),
                    json_mode=False, temperature=0.8)
    return out or ""
