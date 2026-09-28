"""
gemini_brain.py — Elite 2-pass hybrid AI for Roblox UGC domination.

Pass 1 (extract_keywords): casual description -> structured intent JSON.
Pass 2 (synthesize_hybrid): intent + DB data + Gemini's culture brain -> strategy.
verify_titles(): hard gate — every title word must exist in DB allow-list.

Rule: Database = truth. Gemini = strategist. Never mix them.
"""

import os
import re
import json
import google.generativeai as genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

_configured = False
_model = None

STOPWORDS = {
    "a", "an", "the", "of", "and", "or", "for", "to", "in", "on", "with",
    "my", "your", "at", "by", "is", "it", "as",
}


def _ensure():
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


def _generate(prompt: str, json_mode: bool = False,
              temperature: float = 0.7, max_tokens: int = 8192):
    if not _ensure():
        return None
    try:
        cfg = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if json_mode:
            cfg["response_mime_type"] = "application/json"
        resp = _model.generate_content(prompt, generation_config=cfg)
        return (resp.text or "").strip()
    except Exception as e:
        print(f"[gemini] generate failed: {e}")
        return None


# =========================================================================
# PASS 1 — EXTRACTION
# =========================================================================
_EXTRACT_PROMPT = """You are an elite keyword extraction engine for Roblox UGC.

The creator describes what they want to make in casual language.
Extract structured intent for a database search. Return ONLY valid JSON:

{
  "item_type":    "<one of: emote|hair|hat|face|neck|shoulder|front|back|waist|shirt|pants|jacket|shoes|3d_clothing|bundle|gear|unknown>",
  "primary":      ["..."],
  "synonyms":     ["..."],
  "style":        ["..."],
  "vibe":         ["..."],
  "colors":       ["..."],
  "references":   ["..."],
  "trend_source": "<one of: tiktok|youtube|anime|game|meme|music|movie|kpop|other|none>",
  "search_terms": ["..."]
}

RULES:
- Lowercase. Single words or short 2-word phrases. No punctuation.
- item_type is CRITICAL — determines which catalog category we search.
- If description mentions a dance / movement / animation -> item_type = "emote"
- If it mentions clothing / accessory -> pick the specific category.
- "references" = memes, songs, characters, celebrities, viral moments.
- "trend_source" = where the creator saw it (yt -> youtube, etc.).
- "search_terms" = the 10-15 BEST words to look up in a Roblox item DB.
- DO NOT invent brand names or Roblox item names.
- Output ONLY the JSON object.

CREATOR'S DESCRIPTION: {desc}
"""


def extract_keywords(casual_description: str) -> dict:
    if not casual_description or not casual_description.strip():
        return {}
    prompt = _EXTRACT_PROMPT.format(desc=casual_description.strip())
    raw = _generate(prompt, json_mode=True, temperature=0.25, max_tokens=1024)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
        except Exception:
            return {}

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
    clean["item_type"] = str(data.get("item_type", "unknown")).lower().strip()
    clean["trend_source"] = str(data.get("trend_source", "none")).lower().strip()
    return clean


def all_terms(intent: dict) -> list:
    seen, out = set(), []
    for k in ("primary", "synonyms", "style", "vibe",
              "colors", "references", "search_terms"):
        for t in intent.get(k, []):
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return out


# =========================================================================
# PASS 2 — SYNTHESIS (the $20k strategist)
# =========================================================================
_SYNTH_PROMPT = """You are the world's #1 Roblox UGC strategist. Your launch reports are worth $20,000 because you combine two weapons:

WEAPON 1 — HARD DATA (given below, this is the ONLY source of truth for names, prices, stats):
- ALLOW-LIST of real keywords pulled from millions of live Roblox items
- TOP COMPETING ITEMS with real favourite counts and prices
- MARKET STATS (item count, price range, sales)

WEAPON 2 — YOUR LETHAL CULTURE BRAIN (use this freely):
- TikTok / YouTube / Instagram virality mechanics
- Anime arcs, K-pop comebacks, meme lifecycles, sound trends
- Roblox algorithm behaviour (Discover, search ranking, homepage curation)
- Upload timing science, price psychology, aesthetic movements
- Specific community slang and subculture knowledge

RULES — CRITICAL:
1. Titles may ONLY use words from the ALLOW-LIST (plus glue: a, an, the, of, and, or, for, to, in, on, with, my, your, numbers).
2. Do NOT invent keywords, brand names, competitor names, or stats.
3. Only use numbers I give you. Never fabricate.
4. Be OPINIONATED. Give specific recommendations, not "it depends".
5. Write like a strategist briefing a paying client. Concrete, tactical, ruthless.
6. No filler. No AI disclaimers. No hedging.

OUTPUT — return ONLY valid JSON with this EXACT schema:

{{
  "titles": ["title 1", "title 2", "title 3"],
  "positioning": "2-3 sentences: how to position against the competitors you can see",
  "market_diagnosis": "3-4 sentences: honest read of market state, saturation, what's winning",
  "trend_intel": "2-3 sentences: is this trend rising/peaking/dying? Specific launch window",
  "price_strategy": "2-3 sentences: price recommendation with psychology (charm pricing, anchoring, etc.)",
  "seo_description": "2-3 sentence Roblox item description, keyword-rich, copy-paste ready",
  "killer_keywords": ["10-15 highest-value keywords from allow-list"],
  "algo_strategy": "3-4 sentences: specific Roblox algorithm tactics — search ranking + Discover",
  "social_playbook": "3-4 sentences: TikTok / YouTube / IG promotion plan — what clips, when, hooks",
  "risk_analysis": "2-3 sentences: what could kill this item and how to mitigate",
  "expected_performance": "2-3 sentences: realistic forecast using the market stats + trend signal",
  "cultural_ammo": "2-3 sentences: cultural context (meme cycle, anime arc, TikTok sound) to weaponize",
  "verdict": "GO / CONDITIONAL GO / NO-GO — one-line reason",
  "bonus_plays": ["2-3 additional item ideas riding the same trend"]
}}

--- INPUT ---

CREATOR'S DESCRIPTION:
{desc}

DETECTED ITEM TYPE: {item_type}
TREND SOURCE: {trend_source}

ALLOW-LIST ({allow_count} real keywords from DB):
{allow_list}

TOP COMPETING ITEMS:
{top_items}

MARKET STATS:
{market_stats}
"""


def synthesize_hybrid(casual_description, allow_list, top_items, market_stats,
                      item_type="unknown", trend_source="none"):
    if not allow_list:
        return {}

    top_lines = []
    for it in top_items[:10]:
        name = (it.get("name") or "")[:90]
        favs = it.get("favourite_count") or 0
        price = it.get("price")
        price_s = f"R${price}" if price not in (None, 0) else "free/unknown"
        top_lines.append(f"- {name} | favs={favs:,} | price={price_s}")

    stats_lines = [
        f"- items matched: {market_stats.get('count', 0):,}",
        f"- price min: R${market_stats.get('price_min', 0)}",
        f"- price avg: R${market_stats.get('price_avg', 0)}",
        f"- price max: R${market_stats.get('price_max', 0)}",
        f"- total sales (matched): {market_stats.get('total_sales', 0):,}",
    ]

    prompt = _SYNTH_PROMPT.format(
        desc=casual_description.strip(),
        item_type=item_type,
        trend_source=trend_source,
        allow_count=len(allow_list),
        allow_list=", ".join(allow_list),
        top_items="\n".join(top_lines) or "(none)",
        market_stats="\n".join(stats_lines),
    )

    raw = _generate(prompt, json_mode=True, temperature=0.85, max_tokens=8192)
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


# =========================================================================
# VERIFICATION — hard gate
# =========================================================================
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list:
    return _TOKEN_RE.findall((text or "").lower())


def verify_titles(titles: list, allow_list: list):
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
            if any(tok.startswith(a) or a.startswith(tok)
                   for a in allow_set if len(a) >= 4):
                continue
            bad.append(tok)
        if bad:
            rejected.append((title, bad))
        else:
            valid.append(title)
    return valid, rejected


# =========================================================================
# FREE-FORM Q&A
# =========================================================================
_ASK_PROMPT = """You are a Roblox UGC market strategist embedded in a Discord bot.
Answer using your knowledge of:
- Roblox UGC algorithm, discoverability, and search ranking
- TikTok / YouTube / anime / K-pop / meme culture
- Pricing psychology and upload timing
- Aesthetic movements and trend cycles

If asked about specific numbers or item names you weren't given, say so
and suggest using the data commands. Be concrete, opinionated, tactical.
No filler. No AI disclaimers. Under 1,800 characters unless depth is needed.

QUESTION:
{q}
"""


def ask_ai(question: str) -> str:
    if not question or not question.strip():
        return ""
    out = _generate(_ASK_PROMPT.format(q=question.strip()),
                    json_mode=False, temperature=0.8, max_tokens=2048)
    return out or ""
