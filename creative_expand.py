"""
creative_expand.py — v2: anchored AI + looser demand gate.
"""

import os
import re
import json
import logging
import psycopg2

log = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
DB_URL         = os.getenv("DATABASE_URL")

SUPPLY_UNDERSERVED = 50
SUPPLY_SATURATED   = 200

STOPWORDS = {"a", "an", "the", "and", "or", "of", "to", "for", "in", "on",
             "with", "emote", "dance", "animation", "motion"}


def _conn():
    return psycopg2.connect(DB_URL)


# ── Ground the AI in real search data ─────────────────────────
def _fetch_real_suggestions(seed: str, limit: int = 30) -> list[str]:
    """Pull real Roblox search phrases matching any seed word."""
    words = [w for w in re.findall(r"\w+", seed.lower()) if w not in STOPWORDS]
    if not words:
        return []
    try:
        with _conn() as c, c.cursor() as cur:
            # Match any seed word
            clauses = " OR ".join(["suggestion ILIKE %s"] * len(words))
            params = [f"%{w}%" for w in words]
            cur.execute(
                f"SELECT DISTINCT suggestion FROM search_suggestions "
                f"WHERE {clauses} ORDER BY suggestion LIMIT %s",
                params + [limit]
            )
            return [r[0] for r in cur.fetchall()]
    except Exception as e:
        log.warning("fetch_real_suggestions failed: %s", e)
        return []


# ── Demand gate — word-level matching ─────────────────────────
def _demand_score(concept: str) -> int:
    """How many suggestions match ANY meaningful word of the concept."""
    words = [w for w in re.findall(r"\w+", concept.lower())
             if w not in STOPWORDS and len(w) >= 3]
    if not words:
        return 0
    try:
        with _conn() as c, c.cursor() as cur:
            clauses = " OR ".join(["suggestion ILIKE %s"] * len(words))
            params = [f"%{w}%" for w in words]
            cur.execute(
                f"SELECT COUNT(DISTINCT suggestion) FROM search_suggestions "
                f"WHERE {clauses}",
                params
            )
            return cur.fetchone()[0] or 0
    except Exception as e:
        log.warning("demand check failed for %s: %s", concept, e)
        return 0


def _supply_score(concept: str) -> int:
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM items "
                "WHERE name ILIKE %s AND favorite_count > 5",
                (f"%{concept}%",)
            )
            return cur.fetchone()[0] or 0
    except Exception as e:
        log.warning("supply check failed for %s: %s", concept, e)
        return 0


# ── AI fan-out, now anchored ──────────────────────────────────
PROMPT = """You are a Roblox UGC emote strategist.

Seed: "{seed}"

Here are 30 REAL Roblox search phrases kids are typing right now
that relate to the seed:
{examples}

Generate {n} NEW concept keywords that:
- Sound like the real examples above (kid-style, short, punchy)
- Are 1-3 words
- Are ADJACENT to the seed (related mood / vibe / movement)
- Do NOT recombine the seed words
- No literary phrases, no music-journalist English

BAD: "hypnotic groove", "sophisticated sway" — too fancy, kids don't type this
GOOD: "aura dance", "mellow vibes", "chill bounce", "lazy wave"

Return JSON ONLY:
{{"concepts": ["concept one", "concept two", "..."]}}
"""


def _call_gemini(prompt: str) -> str | None:
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=GEMINI_API_KEY)
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=1000,
                temperature=0.95,
                top_p=0.95,
            ),
        )
        return resp.text
    except Exception as e:
        log.warning("gemini failed: %s", e)
        return None


def _parse(raw: str) -> list[str]:
    if not raw:
        return []
    txt = raw.strip()
    if txt.startswith("```"):
        txt = txt.split("```")[1]
        if txt.startswith("json"):
            txt = txt[4:]
        txt = txt.strip()
    try:
        data = json.loads(txt)
    except json.JSONDecodeError:
        s, e = txt.find("{"), txt.rfind("}")
        if s == -1 or e == -1:
            return []
        try:
            data = json.loads(txt[s:e+1])
        except Exception:
            return []
    out, seen = [], set()
    for c in data.get("concepts", []):
        if not isinstance(c, str):
            continue
        c = c.strip().lower()
        if 2 <= len(c) <= 40 and 1 <= len(c.split()) <= 3 and c not in seen:
            seen.add(c)
            out.append(c)
    return out


# ── Public API ────────────────────────────────────────────────
def expand_with_validation(seed: str, n: int = 20) -> dict:
    """
    Returns:
      {
        "results":    [...passing concepts...],
        "discarded":  [...hallucinated ones...],
        "examples":   [...real search phrases used as anchor...],
        "raw":        "...raw AI response..."
      }
    """
    examples = _fetch_real_suggestions(seed, limit=30)
    example_block = "\n".join(f"- {e}" for e in examples) if examples else "(no examples found — generate best guess)"
    prompt = PROMPT.format(seed=seed, n=n, examples=example_block)

    raw = _call_gemini(prompt)
    concepts = _parse(raw) if raw else []

    results, discarded = [], []
    for c in concepts:
        d = _demand_score(c)
        s = _supply_score(c)
        row = {"concept": c, "demand": d, "supply": s}

        if d == 0:
            row["verdict"] = "hallucinated"
            discarded.append(row)
        elif s == 0:
            row["verdict"] = "gold"; results.append(row)
        elif s < SUPPLY_UNDERSERVED:
            row["verdict"] = "opportunity"; results.append(row)
        elif s < SUPPLY_SATURATED:
            row["verdict"] = "contested"; results.append(row)
        else:
            row["verdict"] = "saturated"; results.append(row)

    prio = {"gold": 0, "opportunity": 1, "contested": 2, "saturated": 3}
    results.sort(key=lambda r: (prio[r["verdict"]], -r["demand"], r["supply"]))

    return {
        "results":   results,
        "discarded": discarded,
        "examples":  examples,
        "raw":       raw or "",
    }


def get_creative_seeds(seed_text: str, max_seeds: int = 8) -> list[str]:
    """For smart_pipeline: return just the good concept strings."""
    data = expand_with_validation(seed_text, n=20)
    good = [r["concept"] for r in data["results"]
            if r["verdict"] in ("gold", "opportunity")]
    return good[:max_seeds]
