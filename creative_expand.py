"""
creative_expand.py — Step 1: standalone test.
Verifies AI fan-out + DB demand gate before wiring into brainstorm/autopsy.
"""

import os
import json
import logging
import psycopg2

log = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
DB_URL         = os.getenv("DATABASE_URL")

SUPPLY_UNDERSERVED = 50
SUPPLY_SATURATED   = 200


# ── DB helpers ──────────────────────────────────────────────
def _conn():
    return psycopg2.connect(DB_URL)


def _demand_score(concept: str) -> int:
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                "SELECT COUNT(DISTINCT suggestion) FROM search_suggestions "
                "WHERE suggestion ILIKE %s",
                (f"%{concept}%",)
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


# ── AI fan-out ──────────────────────────────────────────────
PROMPT = """You are a Roblox UGC emote strategist.

Seed description: "{seed}"

Generate {n} CONCEPT keywords that a human creator would associate with this emote's VIBE.

Rules:
- 1 to 3 words each
- Must be a phrase a kid would type into Roblox search
- ADJACENT concepts: mood, aesthetic, subculture, music genre, movement quality
- Do NOT recombine the seed words
- No invented words, no made-up slang

BAD (reject): "Rhythm Sway", "Step Dance", "Sway Step" — literal word shuffles
GOOD (aim for): "Hypnotic Groove", "Lo-fi Bop", "Chill Two-Step", "Mellow Bounce"

Return JSON ONLY, no markdown:
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


# ── Public API ──────────────────────────────────────────────
def expand_with_validation(seed: str, n: int = 20) -> list[dict]:
    raw = _call_gemini(PROMPT.format(seed=seed, n=n))
    concepts = _parse(raw)
    results = []
    for c in concepts:
        d = _demand_score(c)
        s = _supply_score(c)
        if d == 0:
            verdict = "hallucinated"
        elif s == 0:
            verdict = "gold"
        elif s < SUPPLY_UNDERSERVED:
            verdict = "opportunity"
        elif s < SUPPLY_SATURATED:
            verdict = "contested"
        else:
            verdict = "saturated"
        results.append({"concept": c, "demand": d, "supply": s, "verdict": verdict})

    results = [r for r in results if r["verdict"] != "hallucinated"]
    prio = {"gold": 0, "opportunity": 1, "contested": 2, "saturated": 3}
    results.sort(key=lambda r: (prio[r["verdict"]], -r["demand"], r["supply"]))
    return results
