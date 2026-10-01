"""
gemini_brain.py — Hybrid AI for Roblox UGC. ALGO-AWARE EDITION.
"""
import os
import re
import json
import time
import base64
from google import genai
from google.genai import types

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")
OPENROUTER_VISION_MODEL = os.getenv("OPENROUTER_VISION_MODEL",
    "inclusionai/ling-3.0-flash-vl:free")

_client = None
_openrouter_client = None
_configured = False

STOPWORDS = {"a","an","the","of","and","or","for","to","in","on","with",
             "my","your","at","by","is","it","as"}


def _ensure():
    global _client, _openrouter_client, _configured
    if _configured:
        return _client is not None or _openrouter_client is not None
    _configured = True
    if GEMINI_API_KEY:
        try:
            _client = genai.Client(api_key=GEMINI_API_KEY)
            print(f"[gemini] model={MODEL_NAME}")
        except Exception as e:
            print(f"[gemini] fail: {e}"); _client = None
    if OPENROUTER_API_KEY:
        try:
            from openai import OpenAI
            _openrouter_client = OpenAI(api_key=OPENROUTER_API_KEY,
                                        base_url="https://openrouter.ai/api/v1")
            print(f"[openrouter] model={OPENROUTER_MODEL}")
        except Exception as e:
            print(f"[openrouter] fail: {e}"); _openrouter_client = None
    return _client is not None or _openrouter_client is not None


def is_available():
    return _ensure()


def _gemini_generate(prompt, json_mode=False, temperature=0.7,
                     max_tokens=8192, max_retries=4):
    if not _client: return None
    for attempt in range(max_retries):
        try:
            cfg = types.GenerateContentConfig(temperature=temperature,
                                              max_output_tokens=max_tokens)
            if json_mode: cfg.response_mime_type = "application/json"
            resp = _client.models.generate_content(model=MODEL_NAME,
                                                    contents=prompt, config=cfg)
            text = (resp.text or "").strip()
            if text: return text
        except Exception as e:
            err = str(e)
            if any(x in err for x in ["429","RESOURCE_EXHAUSTED","quota",
                                       "API key not valid","PERMISSION_DENIED"]):
                return None
            if not any(x in err for x in ["503","UNAVAILABLE","high demand",
                                           "overloaded","500","INTERNAL","timeout"]):
                return None
        if attempt < max_retries - 1:
            time.sleep(2 + attempt * 2)
    return None


def _openrouter_generate(prompt, json_mode=False, temperature=0.7,
                         max_tokens=8192, max_retries=3):
    if not _openrouter_client: return None
    for attempt in range(max_retries):
        try:
            kwargs = {"model": OPENROUTER_MODEL,
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": temperature, "max_tokens": max_tokens, "timeout": 90}
            if json_mode: kwargs["response_format"] = {"type": "json_object"}
            resp = _openrouter_client.chat.completions.create(**kwargs)
            text = (resp.choices[0].message.content or "").strip()
            if text: return text
        except Exception as e:
            if not any(x in str(e) for x in ["503","UNAVAILABLE","429","overloaded","500","timeout"]):
                return None
        if attempt < max_retries - 1:
            time.sleep(2 + attempt * 2)
    return None


def _generate(prompt, json_mode=False, temperature=0.7,
              max_tokens=8192, prefer="gemini"):
    if not _ensure(): return None
    if _client is not None:
        out = _gemini_generate(prompt, json_mode, temperature, max_tokens)
        if out: return out
    if _openrouter_client is not None:
        out = _openrouter_generate(prompt, json_mode, temperature, max_tokens)
        if out: return out
    return None


_EXTRACT_PROMPT = """You are an elite keyword extraction engine for Roblox UGC.

Extract structured intent for a DB search. Return ONLY JSON:

{{
  "item_type":    "<emote|hair|hat|face|neck|shoulder|front|back|waist|shirt|pants|jacket|shoes|3d_clothing|bundle|gear|unknown>",
  "primary":      ["..."],
  "synonyms":     ["..."],
  "style":        ["..."],
  "vibe":         ["..."],
  "colors":       ["..."],
  "references":   ["..."],
  "trend_source": "<tiktok|youtube|anime|game|meme|music|movie|kpop|other|none>",
  "search_terms": ["..."],
  "specific_moves": ["..."]
}}

RULES:
- Lowercase. No punctuation.
- If description mentions a dance / movement -> item_type = "emote"
- "specific_moves" = exact body movements (e.g. "hip sway", "arm pump"). These MUST appear in title ideas.
- Output ONLY JSON.

CREATOR'S DESCRIPTION: {desc}
"""


def extract_keywords(casual_description):
    if not casual_description or not casual_description.strip(): return {}
    prompt = _EXTRACT_PROMPT.format(desc=casual_description.strip())
    raw = _generate(prompt, json_mode=True, temperature=0.25, max_tokens=1024)
    if not raw: return {}
    try: data = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m: return {}
        try: data = json.loads(m.group(0))
        except Exception: return {}

    keys = ["primary","synonyms","style","vibe","colors","references",
            "search_terms","specific_moves"]
    clean = {}
    for k in keys:
        val = data.get(k, [])
        if isinstance(val, str): val = [val]
        if not isinstance(val, list): val = []
        clean[k] = [str(v).lower().strip() for v in val if str(v).strip()]
    clean["item_type"] = str(data.get("item_type", "unknown")).lower().strip()
    clean["trend_source"] = str(data.get("trend_source", "none")).lower().strip()
    return clean


def all_terms(intent):
    seen, out = set(), []
    for k in ("primary","synonyms","style","vibe","colors","references",
              "search_terms","specific_moves"):
        for t in intent.get(k, []):
            if t and t not in seen:
                seen.add(t); out.append(t)
    return out


_EXPAND_PROMPT = """You are a Roblox UGC DB search expert.

ORIGINAL INTENT: {intent_json}
FAILED TERMS: {failed_terms}
DB VOCAB SAMPLE: {db_vocab_sample}

Return ONLY JSON:
{{"expanded_terms": ["..."], "reasoning": "one-line"}}
"""


def expand_search_terms(intent, db_vocab_sample, failed_terms):
    if not failed_terms:
        return {"expanded_terms": [], "reasoning": "no failed terms"}
    intent_json = json.dumps({k: v for k, v in intent.items() if k != "search_terms"}, indent=2)
    prompt = _EXPAND_PROMPT.format(
        intent_json=intent_json, failed_terms=", ".join(failed_terms),
        db_vocab_sample=", ".join(db_vocab_sample[:400]))
    raw = _generate(prompt, json_mode=True, temperature=0.6, max_tokens=1024)
    if not raw: return {"expanded_terms": [], "reasoning": "ai returned nothing"}
    try: data = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
    terms = data.get("expanded_terms", [])
    if isinstance(terms, str): terms = [terms]
    return {"expanded_terms": [str(t).lower().strip() for t in terms if str(t).strip()][:30],
            "reasoning": str(data.get("reasoning", ""))[:200]}


_SYNTH_PROMPT = """You are the world's #1 Roblox UGC strategist.

WEAPONS:
1. HARD DATA (only source of truth)
2. ROBLOX ALGORITHM KNOWLEDGE (given below)
3. YOUR CULTURE BRAIN (TikTok, anime, memes)
4. USER'S SPECIFIC MOVES (never ignore)

RULES:
1. Titles may ONLY use ALLOW-LIST words + glue (a/an/the/of/and/or/for/to/in/on/with/my/your/numbers).
2. Do NOT invent keywords, brands, or stats.
3. Be OPINIONATED. Specific recommendations only.
4. NO thumbnail advice. Roblox sets default thumbnails.
5. At least 2 of 10 titles MUST include the user's SPECIFIC_MOVES.
6. Titles max 5 tokens.
7. Reference SPECIFIC numbers from algo knowledge.
8. If saturated, say so bluntly and pivot.
9. Use WINNER vs LOSER diff to justify every recommendation.

OUTPUT — ONLY JSON:

{{
  "titles_safe": ["title 1", "title 2", "title 3"],
  "titles_differentiated": ["title 1", "title 2", "title 3"],
  "titles_longtail": ["title 1", "title 2"],
  "titles_viral": ["title 1", "title 2"],
  "search_diagnosis": "2-3 sentences",
  "positioning": "3-4 sentences",
  "market_diagnosis": "3-4 sentences",
  "winner_blueprint": "3-4 sentences referencing top 10% patterns",
  "marketplace_algorithm_playbook": "5-6 sentences with CTR thresholds and velocity targets",
  "ranking_factor_breakdown": "4-5 sentences on which factors matter most",
  "sale_velocity_plan": "3-4 sentences with hour 1/6/24 targets",
  "price_elasticity_call": "2-3 sentences with exact price + why",
  "saturation_verdict": "2-3 sentences",
  "launch_window_math": "2-3 sentences with exact day/hour",
  "trend_intel": "3-4 sentences",
  "discovery_path": "2-3 sentences buyer journey",
  "seo_description": "3-4 sentences copy-paste",
  "killer_keywords": ["10-15 keywords"],
  "cross_promotion_play": "2-3 sentences",
  "social_playbook": "3-4 sentences",
  "risk_analysis": "3-4 sentences",
  "expected_performance": "3-4 sentences",
  "cultural_ammo": "3-4 sentences",
  "verdict": "GO / CONDITIONAL GO / NO-GO — one-line",
  "bonus_plays": ["2-3 additional ideas"]
}}

--- INPUT ---

DESCRIPTION: {desc}
ITEM TYPE: {item_type}
TREND SOURCE: {trend_source}
SPECIFIC MOVES: {specific_moves}

ALLOW-LIST ({allow_count}):
{allow_list}

TOP COMPETING ITEMS:
{top_items}

MARKET STATS:
{market_stats}

{winner_blueprint}

{algo_context}

SEARCH DIAGNOSTICS:
{search_diagnostics}

GAP ANALYSIS:
{gap_analysis}
"""


def synthesize_hybrid(casual_description, allow_list, top_items, market_stats,
                      item_type="unknown", trend_source="none",
                      search_diagnostics=None, gap_analysis=None,
                      specific_moves=None, winner_analysis=None,
                      algo_context=None):
    if not allow_list: return {}

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
        f"- avg favourites: {market_stats.get('avg_favs', 0):,}",
        f"- median favourites: {market_stats.get('median_favs', 0):,}",
        f"- winner threshold (top 10%): {market_stats.get('winner_favs', 0):,} favs",
    ]

    diag = search_diagnostics or {}
    diag_lines = [
        f"- direct matches: {diag.get('direct_matches', 0):,}",
        f"- bridge used: {'YES' if diag.get('expansion_used') else 'no'}",
    ]
    if diag.get("expanded_terms"):
        diag_lines.append(f"- bridged terms: {', '.join(diag['expanded_terms'][:15])}")

    gap_lines = []
    if gap_analysis:
        if gap_analysis.get("golden"):
            gap_lines.append("GOLDEN GAPS:")
            for g in gap_analysis["golden"][:8]:
                gap_lines.append(f"- {g['word']} | comp={g['comp']} | median_favs={g['median_favs']}")

    sm = ", ".join(specific_moves) if specific_moves else "(none)"

    wb = "(unavailable)"
    if winner_analysis:
        try:
            from winner_analysis import format_winner_blueprint
            wb = format_winner_blueprint(winner_analysis)
        except Exception: pass

    ac = algo_context or "(unavailable)"

    prompt = _SYNTH_PROMPT.format(
        desc=casual_description.strip(), item_type=item_type,
        trend_source=trend_source, specific_moves=sm,
        allow_count=len(allow_list), allow_list=", ".join(allow_list),
        top_items="\n".join(top_lines) or "(none)",
        market_stats="\n".join(stats_lines),
        winner_blueprint=wb, algo_context=ac,
        search_diagnostics="\n".join(diag_lines) or "(none)",
        gap_analysis="\n".join(gap_lines) or "(none)")

    raw = _generate(prompt, json_mode=True, temperature=0.9, max_tokens=8192)
    if not raw: return {}
    try: return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m: return {}
        try: return json.loads(m.group(0))
        except Exception: return {}


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text):
    return _TOKEN_RE.findall((text or "").lower())


def verify_titles(titles, allow_list):
    allow_set = {t.lower().strip() for t in allow_list if t and t.strip()}
    valid, rejected = [], []
    for title in titles or []:
        if not isinstance(title, str) or not title.strip(): continue
        toks = _tokens(title)
        if len(toks) > 7 or len(toks) < 2:
            rejected.append((title, [f"length={len(toks)}"])); continue
        if any(toks[i] == toks[i+1] for i in range(len(toks)-1)):
            rejected.append((title, ["consecutive dup"])); continue
        bad = []
        for tok in toks:
            if tok in STOPWORDS: continue
            if tok.isdigit(): continue
            if tok in allow_set: continue
            if any(tok.startswith(a) or a.startswith(tok)
                   for a in allow_set if len(a) >= 4): continue
            bad.append(tok)
        if bad: rejected.append((title, bad))
        else: valid.append(title)
    return valid, rejected


_VISION_PROMPT = """Analyze 1-4 images of the same UGC item. Return ONLY JSON:

{{
  "visual_colors": ["..."],
  "visual_style": ["..."],
  "visual_mood": ["..."],
  "item_type_visual": "<emote|hair|hat|face|neck|shoulder|front|back|waist|shirt|pants|jacket|shoes|3d_clothing|bundle|gear|unknown>",
  "distinctive_features": ["..."],
  "search_description": "one sentence",
  "title_color_match": "<YES|NO|PARTIAL>",
  "visual_summary": "2-3 sentences",
  "likely_aesthetic": ["..."],
  "likely_trend_source": "<tiktok|youtube|anime|game|meme|music|movie|kpop|other|none>",
  "likely_trend_context": "2-3 sentences",
  "vibe_references": ["..."],
  "ip_reference_warning": "<NONE or warning>",
  "target_audience": "2-3 sentences",
  "color_psychology": "1-2 sentences",
  "composition_notes": "1-2 sentences"
}}

CREATOR'S DESCRIPTION: {desc}
"""


def _parse_vision_result(raw):
    if not raw: return {}
    try: data = json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m: return {}
        try: data = json.loads(m.group(0))
        except Exception: return {}
    for k in ("visual_colors","visual_style","visual_mood","distinctive_features",
              "likely_aesthetic","vibe_references"):
        val = data.get(k, [])
        if isinstance(val, str): val = [val]
        if not isinstance(val, list): val = []
        data[k] = [str(v).lower().strip() for v in val if str(v).strip()]
    for k in ("item_type_visual","search_description","title_color_match",
              "visual_summary","likely_trend_source","likely_trend_context",
              "ip_reference_warning","target_audience","color_psychology",
              "composition_notes"):
        data[k] = str(data.get(k, "")).strip()
    data["item_type_visual"] = data["item_type_visual"].lower() or "unknown"
    data["title_color_match"] = data["title_color_match"].upper() or "?"
    return data


def analyze_image_for_ugc(images, user_description=""):
    if not _ensure() or not images: return {}
    images = images[:4]
    prompt_text = _VISION_PROMPT.format(desc=(user_description or "").strip() or "(none)")

    if _client is not None:
        try:
            parts = []
            for i, img in enumerate(images, 1):
                parts.append(f"Image {i}:")
                parts.append(types.Part.from_bytes(data=img["bytes"], mime_type=img["mime"]))
            parts.append(prompt_text)
            cfg = types.GenerateContentConfig(temperature=0.3, max_output_tokens=1500,
                                              response_mime_type="application/json")
            resp = _client.models.generate_content(model=MODEL_NAME, contents=parts, config=cfg)
            raw = (resp.text or "").strip()
            if raw:
                result = _parse_vision_result(raw)
                if result: return result
        except Exception as e:
            print(f"[vision] gemini failed: {e}")

    if _openrouter_client is not None:
        try:
            content = []
            for i, img in enumerate(images, 1):
                content.append({"type": "text", "text": f"Image {i}:"})
                b64 = base64.b64encode(img["bytes"]).decode("utf-8")
                content.append({"type": "image_url",
                                "image_url": {"url": f"data:{img['mime']};base64,{b64}"}})
            content.append({"type": "text", "text": prompt_text})
            resp = _openrouter_client.chat.completions.create(
                model=OPENROUTER_VISION_MODEL,
                messages=[{"role": "user", "content": content}],
                temperature=0.3, max_tokens=1500, timeout=90)
            raw = (resp.choices[0].message.content or "").strip()
            if raw: return _parse_vision_result(raw)
        except Exception as e:
            print(f"[vision] openrouter failed: {e}")
    return {}


_ASK_PROMPT = """You are a helpful assistant inside a Roblox UGC bot.
Answer directly. If Roblox UGC related, go deep and tactical. Under 1,800 chars.

QUESTION: {q}
"""


def ask_ai(question):
    if not question or not question.strip(): return ""
    return _generate(_ASK_PROMPT.format(q=question.strip()),
                     json_mode=False, temperature=0.8, max_tokens=2048) or ""
