"""
gemini_brain.py — Hybrid AI for Roblox UGC domination.
Primary: Gemini. Fallback: OpenRouter.
"""

import os
import re
import json
import time
from google import genai
from google.genai import types

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")

_client = None
_openrouter_client = None
_configured = False

STOPWORDS = {
    "a", "an", "the", "of", "and", "or", "for", "to", "in", "on", "with",
    "my", "your", "at", "by", "is", "it", "as",
}


def _ensure():
    global _client, _openrouter_client, _configured
    if _configured:
        return _client is not None or _openrouter_client is not None
    _configured = True

    # ---- Gemini ----
    if GEMINI_API_KEY:
        try:
            _client = genai.Client(api_key=GEMINI_API_KEY)
            print(f"[gemini] configured model={MODEL_NAME}")
        except Exception as e:
            print(f"[gemini] configure failed: {e}")
            _client = None
    else:
        print("[gemini] GEMINI_API_KEY not set")

    # ---- OpenRouter ----
    if OPENROUTER_API_KEY:
        try:
            from openai import OpenAI
            _openrouter_client = OpenAI(
                api_key=OPENROUTER_API_KEY,
                base_url="https://openrouter.ai/api/v1",
            )
            print(f"[openrouter] configured model={OPENROUTER_MODEL}")
        except Exception as e:
            print(f"[openrouter] configure failed: {e}")
            _openrouter_client = None
    else:
        print("[openrouter] OPENROUTER_API_KEY not set")

    return _client is not None or _openrouter_client is not None


def is_available() -> bool:
    return _ensure()


def _gemini_generate(prompt: str, json_mode: bool = False,
                     temperature: float = 0.7, max_tokens: int = 8192,
                     max_retries: int = 4):
    """Gemini call with auto-retry on transient errors."""
    if not _client:
        return None
    for attempt in range(max_retries):
        try:
            cfg = types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
            if json_mode:
                cfg.response_mime_type = "application/json"
            resp = _client.models.generate_content(
                model=MODEL_NAME, contents=prompt, config=cfg)
            text = (resp.text or "").strip()
            if text:
                return text
            fr = "unknown"
            if getattr(resp, "candidates", None):
                fr = getattr(resp.candidates[0], "finish_reason", "unknown")
            print(f"[gemini] empty response (attempt {attempt+1}), fr={fr}")
        except Exception as e:
            err = str(e)
            retryable = any(x in err for x in [
                "503", "UNAVAILABLE", "high demand",
                "429", "RESOURCE_EXHAUSTED", "overloaded",
                "500", "INTERNAL", "timeout", "Timeout",
            ])
            print(f"[gemini] attempt {attempt+1}/{max_retries} "
                  f"failed: {type(e).__name__}: {err[:180]}")
            if not retryable:
                return None
        if attempt < max_retries - 1:
            time.sleep(2 + attempt * 2)
    return None


def _openrouter_generate(prompt: str, json_mode: bool = False,
                         temperature: float = 0.7, max_tokens: int = 4096,
                         max_retries: int = 3):
    """OpenRouter call with auto-retry on transient errors."""
    if not _openrouter_client:
        return None
    for attempt in range(max_retries):
        try:
            kwargs = {
                "model": OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            resp = _openrouter_client.chat.completions.create(**kwargs)
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return text
            print(f"[openrouter] empty response (attempt {attempt+1})")
        except Exception as e:
            err = str(e)
            retryable = any(x in err for x in [
                "503", "UNAVAILABLE", "high demand",
                "429", "RESOURCE_EXHAUSTED", "overloaded",
                "500", "timeout",
            ])
            print(f"[openrouter] attempt {attempt+1}/{max_retries} "
                  f"failed: {type(e).__name__}: {err[:180]}")
            if not retryable:
                return None
        if attempt < max_retries - 1:
            time.sleep(2 + attempt * 2)
    return None


def _generate(prompt: str, json_mode: bool = False,
              temperature: float = 0.7, max_tokens: int = 8192,
              prefer: str = "gemini"):
    """
    Try Gemini first (with retries). If all fail, fall back to OpenRouter.
    """
    if not _ensure():
        return None

    # ---- TIER 1: Gemini ----
    if _client is not None:
        out = _gemini_generate(prompt, json_mode, temperature, max_tokens)
        if out:
            return out
        print("[fallback] Gemini exhausted — switching to OpenRouter")

    # ---- TIER 2: OpenRouter ----
    if _openrouter_client is not None:
        out = _openrouter_generate(prompt, json_mode, temperature,
                                    min(max_tokens, 4096))
        if out:
            return out
        print("[fallback] OpenRouter also exhausted")

    return None


# =========================================================================
# PASS 1 — EXTRACTION
# =========================================================================
_EXTRACT_PROMPT = """You are an elite keyword extraction engine for Roblox UGC.

The creator describes what they want to make in casual language.
Extract structured intent for a database search. Return ONLY valid JSON:

{{
  "item_type":    "<one of: emote|hair|hat|face|neck|shoulder|front|back|waist|shirt|pants|jacket|shoes|3d_clothing|bundle|gear|unknown>",
  "primary":      ["..."],
  "synonyms":     ["..."],
  "style":        ["..."],
  "vibe":         ["..."],
  "colors":       ["..."],
  "references":   ["..."],
  "trend_source": "<one of: tiktok|youtube|anime|game|meme|music|movie|kpop|other|none>",
  "search_terms": ["..."]
}}

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
    raw = _generate(prompt, json_mode=True, temperature=0.25,
                    max_tokens=1024, prefer="gemini")
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
# PASS 1.5 — BRIDGE
# =========================================================================
_EXPAND_PROMPT = """You are a Roblox UGC database search expert.

The creator's original intent did not return enough results in our catalog.
Your job: find ALTERNATIVE search terms that WILL match real Roblox items.

ORIGINAL INTENT:
{intent_json}

WORDS THAT FAILED (few/no matches in DB):
{failed_terms}

REAL WORDS THAT EXIST IN OUR DB (sample of the most common {vocab_size} catalog terms):
{db_vocab_sample}

RULES:
- Suggest 15-25 alternative search terms SEMANTICALLY SIMILAR to the failed terms,
  but LIKELY TO EXIST in a Roblox UGC catalog.
- Prefer words from the DB vocabulary sample whenever they fit the intent.
- Include: synonyms, related aesthetics, style words, item types, vibe words.
- Lowercase. Single words or short phrases. No punctuation.
- DO NOT include the failed terms themselves.
- Think: what would the items on Roblox ACTUALLY be called?

Return ONLY valid JSON:
{{"expanded_terms": ["...", "..."], "reasoning": "one-line explanation"}}

OUTPUT ONLY THE JSON.
"""


def expand_search_terms(intent: dict, db_vocab_sample: list, failed_terms: list) -> dict:
    if not failed_terms:
        return {"expanded_terms": [], "reasoning": "no failed terms"}

    intent_json = json.dumps({k: v for k, v in intent.items()
                              if k not in ("search_terms",)}, indent=2)
    vocab_str = ", ".join(db_vocab_sample[:400])

    prompt = _EXPAND_PROMPT.format(
        intent_json=intent_json,
        failed_terms=", ".join(failed_terms),
        vocab_size=len(db_vocab_sample),
        db_vocab_sample=vocab_str,
    )

    raw = _generate(prompt, json_mode=True, temperature=0.6,
                    max_tokens=1024, prefer="gemini")
    if not raw:
        return {"expanded_terms": [], "reasoning": "ai returned nothing"}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return {"expanded_terms": [], "reasoning": "parse failed"}
        try:
            data = json.loads(m.group(0))
        except Exception:
            return {"expanded_terms": [], "reasoning": "parse failed"}

    terms = data.get("expanded_terms", [])
    if isinstance(terms, str):
        terms = [terms]
    clean = [str(t).lower().strip() for t in terms if str(t).strip()]
    return {
        "expanded_terms": clean[:30],
        "reasoning": str(data.get("reasoning", ""))[:200],
    }


# =========================================================================
# PASS 2 — SYNTHESIS
# =========================================================================
_SYNTH_PROMPT = """You are the world's #1 Roblox UGC strategist. Your launch reports are worth $20,000 because you combine two weapons:

WEAPON 1 — HARD DATA (given below, this is the ONLY source of truth for names, prices, stats):
- ALLOW-LIST of real keywords pulled from millions of live Roblox items
- TOP COMPETING ITEMS with real favourite counts and prices
- MARKET STATS (item count, price range, sales, competition density)
- SEARCH DIAGNOSTICS (direct hits vs AI-bridged terms)

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
6. If SEARCH DIAGNOSTICS show "expansion used", it means the user's literal words
   don't exist in the catalog. EXPLAIN this in market_diagnosis and lean into
   the bridged terms as the real opportunity.
7. No filler. No AI disclaimers. No hedging.

OUTPUT — return ONLY valid JSON with this EXACT schema:

{{
  "titles": ["title 1", "title 2", "title 3"],
  "search_diagnosis": "2-3 sentences: which of the user's words actually exist in the catalog vs which had to be bridged, and what that reveals",
  "positioning": "2-3 sentences: how to position against the competitors you can see",
  "market_diagnosis": "3-4 sentences: honest read of saturation, winners, losers, and CTR signals (avg favs per item)",
  "trend_intel": "2-3 sentences: is this trend rising/peaking/dying? Specific launch window",
  "price_strategy": "2-3 sentences: price recommendation with psychology",
  "seo_description": "2-3 sentence Roblox item description, keyword-rich, copy-paste ready",
  "killer_keywords": ["10-15 highest-value keywords from allow-list"],
  "algo_strategy": "3-4 sentences: specific Roblox algorithm tactics",
  "social_playbook": "3-4 sentences: TikTok / YouTube / IG promotion plan",
  "risk_analysis": "2-3 sentences: what could kill this item and how to mitigate",
  "expected_performance": "2-3 sentences: realistic forecast",
  "cultural_ammo": "2-3 sentences: cultural context to weaponize",
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

SEARCH DIAGNOSTICS:
{search_diagnostics}
"""


def synthesize_hybrid(casual_description, allow_list, top_items, market_stats,
                      item_type="unknown", trend_source="none",
                      search_diagnostics=None):
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
        f"- avg favourites/item: {market_stats.get('avg_favs', 0):,}",
        f"- median favourites: {market_stats.get('median_favs', 0):,}",
        f"- winner threshold (top 10%): {market_stats.get('winner_favs', 0):,} favs",
        f"- winners in set (>10k favs): {market_stats.get('winner_count', 0):,}",
    ]

    diag = search_diagnostics or {}
    diag_lines = [
        f"- direct term matches: {diag.get('direct_matches', 0):,}",
        f"- bridge/expansion used: {'YES' if diag.get('expansion_used') else 'no'}",
    ]
    if diag.get("expanded_terms"):
        diag_lines.append(f"- bridged terms: {', '.join(diag['expanded_terms'][:15])}")
    if diag.get("reasoning"):
        diag_lines.append(f"- bridge reasoning: {diag['reasoning']}")
    if diag.get("failed_terms"):
        diag_lines.append(f"- failed user terms: {', '.join(diag['failed_terms'][:10])}")

    prompt = _SYNTH_PROMPT.format(
        desc=casual_description.strip(),
        item_type=item_type,
        trend_source=trend_source,
        allow_count=len(allow_list),
        allow_list=", ".join(allow_list),
        top_items="\n".join(top_lines) or "(none)",
        market_stats="\n".join(stats_lines),
        search_diagnostics="\n".join(diag_lines) or "(none)",
    )

    raw = _generate(prompt, json_mode=True, temperature=0.85,
                    max_tokens=8192, prefer="gemini")
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
# VERIFICATION
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
_ASK_PROMPT = """You are a helpful assistant inside a Roblox UGC bot.

Answer the user's question directly. If it's a general knowledge,
math, or common question, answer it normally in 1-3 sentences.
If it's specifically about Roblox UGC, market strategy, pricing,
uploading, trends, or the creator economy — go deep and tactical
using your full knowledge of the algorithm and internet culture.

No filler. No AI disclaimers. Under 1,800 characters.

QUESTION:
{q}
"""


def ask_ai(question: str) -> str:
    if not question or not question.strip():
        return ""
    out = _generate(_ASK_PROMPT.format(q=question.strip()),
                    json_mode=False, temperature=0.8,
                    max_tokens=2048, prefer="gemini")
    return out or ""
