"""
gemini_brain.py — Hybrid AI for Roblox UGC. SMART EDITION.

New in this version:
- verify_titles() correctly handles bigram allow-list entries (fixes "arm pump" rejection)
- mine_title_patterns() extracts structural patterns from DB winners
- synthesize_hybrid() receives competitor titles so AI avoids duplicates and finds gaps
- generate_fallback_titles() — programmatic title generator when AI fails or under-delivers
- Prompt is 3x more specific about title construction rules
"""
import os
import re
import json
import time
import base64
from collections import Counter
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

GLUE_WORDS = {"a","an","the","of","and","or","for","to","in","on","with",
              "my","your","at","by","is","it","as"}

# Core item type words — always allowed in titles
ITEM_TYPE_WORDS = {
    "emote","dance","hat","beanie","crown","cap","hair","face","mask","shirt",
    "pants","jacket","shoes","wing","wings","tail","ears","horn","horns",
    "glasses","necklace","chain","backpack","sword","pet","bag","scarf",
    "bandana","beret","visor","lens","head","snapback","bonnet","balaclava",
}


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


# ============================================================
# TOKEN HELPERS
# ============================================================
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text):
    return _TOKEN_RE.findall((text or "").lower())


# ============================================================
# PASS 1 — EXTRACTION
# ============================================================
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
  "specific_moves": ["..."],
  "title_verbs":  ["..."]
}}

RULES:
- Lowercase. No punctuation. Single words or short 2-word phrases.
- If description mentions a dance / movement / animation -> item_type = "emote"
- "specific_moves" = EXACT body movements described (e.g. "hip sway", "arm pump",
  "side step"). These are the SELLING POINTS. Every move should be 1-2 words.
- "title_verbs" = action verbs that describe the movement (sway, pump, groove,
  bounce, flow, glide, twist, wave). These are high-value title tokens.
- "search_terms" = 10-15 BEST words to search a Roblox DB.
- "references" = memes, songs, characters, celebrities, viral moments.
- DO NOT invent brand names or Roblox item names.
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
            "search_terms","specific_moves","title_verbs"]
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
              "search_terms","specific_moves","title_verbs"):
        for t in intent.get(k, []):
            if t and t not in seen:
                seen.add(t); out.append(t)
    return out


# ============================================================
# PASS 1.5 — BRIDGE
# ============================================================
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


# ============================================================
# TITLE PATTERN MINING — new pass
# ============================================================
def mine_title_patterns(top_items):
    """
    Analyze top competitor titles and extract structural patterns.
    Returns a dict of {patterns: [...], avoid_words: [...], common_lengths: [...]}
    """
    if not top_items:
        return {"patterns": [], "avoid_words": [], "common_lengths": []}

    patterns = Counter()
    word_counter = Counter()
    lengths = []

    for it in top_items:
        name = (it.get("name") or "").strip()
        if not name: continue
        toks = _tokens(name)
        if not toks: continue
        lengths.append(len(toks))

        # Word frequency
        for t in toks:
            if len(t) >= 3:
                word_counter[t] += 1

        # Pattern = structure of the title (e.g. "noun verb noun")
        # Simplify: token count signature
        signature = f"{len(toks)}-word"
        patterns[signature] += 1

    # Common lengths
    common_lengths = []
    if lengths:
        length_counter = Counter(lengths)
        common_lengths = [l for l, _ in length_counter.most_common(3)]

    # Words that appear more than 40% of the time are probably generic — avoid
    total = len(top_items)
    avoid_words = [w for w, c in word_counter.most_common(10) if c / total > 0.4]

    return {
        "patterns": [p for p, _ in patterns.most_common(5)],
        "avoid_words": avoid_words,
        "common_lengths": common_lengths,
        "top_words": [w for w, _ in word_counter.most_common(15)],
    }


# ============================================================
# PASS 2 — SYNTHESIS (SMART EDITION)
# ============================================================
_SYNTH_PROMPT = """You are the world's #1 Roblox UGC naming strategist. Your titles have generated millions of favourites. You see the market in ways other creators can't.

=== YOUR WEAPONS ===
1. HARD DATA — real competitor titles, favs, prices from the DB (only source of truth)
2. ROBLOX ALGORITHM KNOWLEDGE — ranking systems, CTR thresholds, velocity targets
3. CULTURE BRAIN — TikTok, anime, memes, K-pop, viral moments
4. USER'S SPECIFIC MOVES — the exact description they gave you

=== TITLE CONSTRUCTION RULES (NON-NEGOTIABLE) ===
1. Every title MUST be 3-5 tokens. Two-word titles are FORBIDDEN.
   Six+ word titles are FORBIDDEN. The verifier rejects both.
2. Every title MUST end with the item type word (emote, hat, hair, dance, etc.)
   OR contain it naturally. e.g. "Hip Sway Arm Pump Dance" not "Hip Sway Arm Pump".
3. Every title MUST be UNIQUE. No title repeats another title's exact word order.
4. At least 3 titles MUST include the user's SPECIFIC_MOVES words.
5. Allow-list bigrams like "hip sway" mean BOTH "hip" and "sway" are usable as
   individual tokens in titles.
6. Titles may ONLY use words from the allow-list + glue words + item type words.
7. NEVER use stopwords like "a", "the", "and" as fillers to pad length.

=== TITLE ARCHETYPES (use these structures) ===
- MOVE + TYPE:              "Hip Sway Dance"
- MOVE + MOVE + TYPE:       "Hip Sway Arm Pump Emote"
- STYLE + MOVE + TYPE:      "TikTok Hip Sway Dance"
- TREND + MOVE + TYPE:      "Viral Hip Sway Emote"
- MOVE + MOVE + MOVE + TYPE:"Hip Sway Arm Pump Dance"
- EMOTION + MOVE + TYPE:    "Chill Hip Sway Dance"

=== WHAT WINNERS DO (from data) ===
{title_pattern_insights}

=== WHAT COMPETITORS ARE NAMING (avoid these exact titles) ===
{competitor_titles}

=== YOUR TASK ===
Generate 10 titles TOTAL, grouped into 4 strategic buckets:
- SAFE (3): mirror what top competitors do, but cleaner
- DIFFERENTIATED (3): same keywords, unique angle — MUST use a different first word than SAFE
- LONGTAIL (2): 4-5 tokens packed with keywords
- VIRAL (2): meme/trend/sound hook

Each title must feel hand-written, not keyword-stuffed.

=== OUTPUT — ONLY JSON ===

{{
  "titles_safe": ["...", "...", "..."],
  "titles_differentiated": ["...", "...", "..."],
  "titles_longtail": ["...", "..."],
  "titles_viral": ["...", "..."],
  "search_diagnosis": "2-3 sentences on which of user's words exist in catalog vs bridged",
  "positioning": "3-4 sentences on how to position against competitors",
  "market_diagnosis": "3-4 sentences on saturation, winners, losers, CTR signals",
  "winner_blueprint": "3-4 sentences on what top 10% do that bottom 50% don't",
  "marketplace_algorithm_playbook": "5-6 sentences with CTR thresholds and velocity targets",
  "ranking_factor_breakdown": "4-5 sentences on which ranking factors matter most",
  "sale_velocity_plan": "3-4 sentences with hour 1/6/24 sales targets",
  "price_elasticity_call": "2-3 sentences with exact price + why",
  "saturation_verdict": "2-3 sentences on whether to enter, pivot, or wait",
  "launch_window_math": "2-3 sentences with exact day/hour (Georgia GMT+4)",
  "trend_intel": "3-4 sentences on trend lifecycle and exit window",
  "discovery_path": "2-3 sentences on the buyer journey",
  "seo_description": "3-4 sentences copy-paste ready for Roblox",
  "killer_keywords": ["10-15 highest-value keywords from allow-list"],
  "cross_promotion_play": "2-3 sentences on related items to launch",
  "social_playbook": "3-4 sentences on TikTok/YouTube promotion",
  "risk_analysis": "3-4 sentences on what could kill this item",
  "expected_performance": "3-4 sentences with realistic numbers",
  "cultural_ammo": "3-4 sentences on cultural context to weaponize",
  "verdict": "GO / CONDITIONAL GO / NO-GO — one-line reason",
  "bonus_plays": ["2-3 additional item ideas"]
}}

=== INPUT ===

DESCRIPTION: {desc}
ITEM TYPE: {item_type}
TREND SOURCE: {trend_source}
SPECIFIC MOVES: {specific_moves}

ALLOW-LIST ({allow_count} tokens):
{allow_list}

TOP COMPETING ITEMS (name | favs | price):
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

    # --- Competitor titles (for duplicate avoidance) ---
    competitor_titles = []
    top_lines = []
    for it in top_items[:10]:
        name = (it.get("name") or "")[:90]
        favs = it.get("favourite_count") or 0
        price = it.get("price")
        price_s = f"R${price}" if price not in (None, 0) else "free/unknown"
        top_lines.append(f"- {name} | favs={favs:,} | price={price_s}")
        if name: competitor_titles.append(name)

    # --- Title pattern mining ---
    try:
        patterns = mine_title_patterns(top_items)
        insight_lines = []
        if patterns.get("common_lengths"):
            insight_lines.append(f"- Winning titles cluster at {patterns['common_lengths']} tokens long")
        if patterns.get("top_words"):
            insight_lines.append(f"- Words that appear most in winners: {', '.join(patterns['top_words'][:10])}")
        if patterns.get("avoid_words"):
            insight_lines.append(f"- Overused words to avoid: {', '.join(patterns['avoid_words'][:5])}")
        title_pattern_insights = "\n".join(insight_lines) or "(not enough data)"
    except Exception:
        title_pattern_insights = "(pattern mining unavailable)"

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
        desc=casual_description.strip(),
        item_type=item_type,
        trend_source=trend_source,
        specific_moves=sm,
        allow_count=len(allow_list),
        allow_list=", ".join(allow_list),
        top_items="\n".join(top_lines) or "(none)",
        market_stats="\n".join(stats_lines),
        winner_blueprint=wb,
        algo_context=ac,
        search_diagnostics="\n".join(diag_lines) or "(none)",
        gap_analysis="\n".join(gap_lines) or "(none)",
        title_pattern_insights=title_pattern_insights,
        competitor_titles="\n".join(f"- {t}" for t in competitor_titles) or "(none)")

    raw = _generate(prompt, json_mode=True, temperature=0.95, max_tokens=8192)
    if not raw: return {}
    try: return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m: return {}
        try: return json.loads(m.group(0))
        except Exception: return {}


# ============================================================
# VERIFICATION — FIXED: handles bigram allow-list entries
# ============================================================
def verify_titles(titles, allow_list):
    """
    Hard gate. Rejects:
    - words not in allow-list
    - titles <3 tokens or >6 tokens
    - titles with duplicate consecutive tokens
    - duplicate titles (case-insensitive)
    Bigrams in allow-list are auto-split so individual tokens pass
    (e.g. "hip sway" allow-list entry means both "hip" and "sway" pass).
    """
    # Expand allow-list: split bigrams into singles + keep original
    allow_set = set()
    for t in allow_list or []:
        if not t: continue
        t = t.lower().strip()
        allow_set.add(t)
        parts = t.split()
        if len(parts) > 1:
            for p in parts:
                if len(p) >= 3:
                    allow_set.add(p)
    # Item type words always allowed
    for w in ITEM_TYPE_WORDS:
        allow_set.add(w)

    valid, rejected = [], []
    seen_lower = set()

    for title in titles or []:
        if not isinstance(title, str) or not title.strip():
            continue

        toks = _tokens(title)

        # Length gate: 3-6 tokens
        if len(toks) < 3:
            rejected.append((title, [f"too short ({len(toks)} words)"]))
            continue
        if len(toks) > 6:
            rejected.append((title, [f"too long ({len(toks)} words)"]))
            continue

        # Duplicate consecutive
        if any(toks[i] == toks[i+1] for i in range(len(toks)-1)):
            rejected.append((title, ["consecutive dup"]))
            continue

        # Cross-group dedup
        t_lower = title.lower().strip()
        if t_lower in seen_lower:
            rejected.append((title, ["duplicate title"]))
            continue

        # Allow-list gate
        bad = []
        for tok in toks:
            if tok in STOPWORDS: continue
            if tok.isdigit(): continue
            if tok in allow_set: continue
            # Prefix matching only if allow-list word is 4+ chars
            if any(tok.startswith(a) or a.startswith(tok)
                   for a in allow_set if len(a) >= 4):
                continue
            bad.append(tok)

        if bad:
            rejected.append((title, bad))
        else:
            seen_lower.add(t_lower)
            valid.append(title)

    return valid, rejected


# ============================================================
# FALLBACK TITLE GENERATOR — programmatic, no AI needed
# ============================================================
def generate_fallback_titles(allow_list, specific_moves, item_type,
                              top_items, needed=10):
    """
    Generate titles programmatically when AI fails or under-delivers.
    Uses allow-list + specific_moves + item_type word.
    Cross-references competitor titles to avoid exact duplicates.
    Returns list of title dicts (grouped by strategy).
    """
    # Type word (defaults to "emote" for emotes)
    type_word = "emote"
    it_lower = (item_type or "").lower()
    type_candidates = {
        "emote": ["emote", "dance"],
        "hair": ["hair"],
        "hat": ["hat", "beanie", "cap"],
        "face": ["face", "mask"],
        "shirt": ["shirt"],
        "pants": ["pants"],
        "jacket": ["jacket"],
    }
    for candidate in type_candidates.get(it_lower, [it_lower]):
        if candidate in allow_list or candidate in ITEM_TYPE_WORDS:
            type_word = candidate
            break

    # Move tokens — split bigrams into individual tokens
    move_tokens = []
    for m in (specific_moves or []):
        for t in _tokens(m):
            if len(t) >= 3 and t not in move_tokens:
                move_tokens.append(t)

    # Allow-list tokens (filter out stopwords)
    allow_tokens = []
    for a in (allow_list or []):
        for t in _tokens(a):
            if len(t) >= 3 and t not in GLUE_WORDS and t not in allow_tokens:
                allow_tokens.append(t)

    # Prioritize: moves first, then allow-list tokens excluding type word
    move_set = set(move_tokens)
    other_tokens = [t for t in allow_tokens
                    if t not in move_set and t != type_word][:10]

    # If we don't have enough tokens, bail
    if not move_tokens and not other_tokens:
        return []

    # Existing titles to avoid duplicates
    existing = set()
    for it in (top_items or []):
        n = (it.get("name") or "").lower().strip()
        if n: existing.add(n)

    # Build candidates
    candidates = []

    # Safe: move + type
    for m1 in move_tokens[:4]:
        candidates.append(("safe", f"{m1.capitalize()} {type_word.capitalize()}"))

    # Safe: move + move + type
    if len(move_tokens) >= 2:
        for i in range(min(3, len(move_tokens))):
            m1 = move_tokens[i]
            m2 = move_tokens[(i+1) % len(move_tokens)]
            candidates.append(("safe", f"{m1.capitalize()} {m2.capitalize()} {type_word.capitalize()}"))

    # Differentiated: other_token + move + type
    for o in other_tokens[:4]:
        for m in move_tokens[:2]:
            candidates.append(("diff", f"{o.capitalize()} {m.capitalize()} {type_word.capitalize()}"))

    # Differentiated: move + other + type
    for m in move_tokens[:2]:
        for o in other_tokens[:3]:
            candidates.append(("diff", f"{m.capitalize()} {o.capitalize()} {type_word.capitalize()}"))

    # Longtail: style + move + move + type
    if len(move_tokens) >= 2 and other_tokens:
        for o in other_tokens[:2]:
            m1 = move_tokens[0]
            m2 = move_tokens[1]
            candidates.append(("longtail", f"{o.capitalize()} {m1.capitalize()} {m2.capitalize()} {type_word.capitalize()}"))

    # Viral: trendy + move + type
    trendy_words = ["viral", "tiktok", "trend", "hype"]
    for tw in trendy_words:
        if tw in allow_tokens:
            for m in move_tokens[:2]:
                candidates.append(("viral", f"{tw.capitalize()} {m.capitalize()} {type_word.capitalize()}"))

    # Filter duplicates and existing
    seen = set()
    filtered = []
    for group, title in candidates:
        tl = title.lower().strip()
        if tl in seen or tl in existing:
            continue
        toks = _tokens(title)
        if len(toks) < 3 or len(toks) > 6:
            continue
        seen.add(tl)
        filtered.append((group, title))

    # Group into buckets
    buckets = {"safe": [], "diff": [], "longtail": [], "viral": []}
    for group, title in filtered:
        if len(buckets[group]) < 4:
            buckets[group].append(title)

    return {
        "titles_safe": buckets["safe"][:3],
        "titles_differentiated": buckets["diff"][:3],
        "titles_longtail": buckets["longtail"][:2],
        "titles_viral": buckets["viral"][:2],
    }


def fallback_title_payload(allow_list, specific_moves, item_type, top_items):
    """Generate a fallback-only synthesis payload when AI fails completely."""
    fallback = generate_fallback_titles(allow_list, specific_moves,
                                        item_type, top_items, needed=10)
    return {
        "titles_safe": fallback.get("titles_safe", []),
        "titles_differentiated": fallback.get("titles_differentiated", []),
        "titles_longtail": fallback.get("titles_longtail", []),
        "titles_viral": fallback.get("titles_viral", []),
        "search_diagnosis": "(fallback mode — AI unavailable)",
        "positioning": "Fallback titles generated from DB allow-list. Verify manually before launching.",
        "market_diagnosis": "Fallback mode — no AI synthesis available.",
        "verdict": "CONDITIONAL — review titles manually",
    }


# ============================================================
# VISION
# ============================================================
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


# ============================================================
# FREE-FORM Q&A
# ============================================================
_ASK_PROMPT = """You are a helpful assistant inside a Roblox UGC bot.
Answer directly. If Roblox UGC related, go deep and tactical. Under 1,800 chars.

QUESTION: {q}
"""


def ask_ai(question):
    if not question or not question.strip(): return ""
    return _generate(_ASK_PROMPT.format(q=question.strip()),
                     json_mode=False, temperature=0.8, max_tokens=2048) or ""
