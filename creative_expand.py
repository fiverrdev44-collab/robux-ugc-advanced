"""
creative_expand.py — v4.
- Movement-shaped prompt (3 flavors: relaxed / energetic / character)
- Dual-source anchor (search_suggestions + learned_keywords) + fallback
- Isolated connections per query so one failure doesn't poison the others
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


# ── Anchor: pull from BOTH tables, isolated connections ───────
def _fetch_real_suggestions(seed: str, limit: int = 30) -> list[str]:
    words = [w for w in re.findall(r"\w+", seed.lower()) if w not in STOPWORDS]
    if not words:
        return []

    results, seen = [], set()
    clauses = " OR ".join(["suggestion ILIKE %s"] * len(words))
    params  = [f"%{w}%" for w in words]

    # Query 1 — search_suggestions (raw autocomplete)
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT DISTINCT suggestion FROM search_suggestions "
            f"WHERE {clauses} ORDER BY suggestion LIMIT %s",
            params + [limit]
        )
        for (s,) in cur.fetchall():
            if s and s.lower() not in seen:
                seen.add(s.lower()); results.append(s)
        cur.close()
    except Exception as e:
        log.warning("search_suggestions query failed: %s", e)
    finally:
        conn.close()

    # Query 2 — learned_keywords (validated top performers)
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT keyword FROM learned_keywords "
            f"WHERE {clauses} ORDER BY score DESC LIMIT %s",
            params + [limit]
        )
        for (kw,) in cur.fetchall():
            if kw and kw.lower() not in seen:
                seen.add(kw.lower()); results.append(kw)
        cur.close()
    except Exception as e:
        log.warning("learned_keywords query failed: %s", e)
    finally:
        conn.close()

    # Query 3 — fallback: if too thin, pull top suggestions overall
    if len(results) < 10:
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT suggestion FROM search_suggestions "
                "ORDER BY suggestion LIMIT %s",
                (limit - len(results),)
            )
            for (s,) in cur.fetchall():
                if s and s.lower() not in seen:
                    seen.add(s.lower()); results.append(s)
            cur.close()
        except Exception as e:
            log.warning("fallback query failed: %s", e)
        finally:
            conn.close()

    return results[:limit]


# ── Demand + supply scoring ───────────────────────────────────
def _demand_score(concept: str) -> int:
    words = [w for w in re.findall(r"\w+", concept.lower())
             if w not in STOPWORDS and len(w) >= 3]
    if not words:
        return 0
    conn = _conn()
    try:
        cur = conn.cursor()
        clauses = " OR ".join(["suggestion ILIKE %s"] * len(words))
        params  = [f"%{w}%" for w in words]
        cur.execute(
            f"SELECT COUNT(DISTINCT suggestion) FROM search_suggestions "
            f"WHERE {clauses}", params
        )
        val = cur.fetchone()[0] or 0
        cur.close()
        return val
    except Exception as e:
        log.warning("demand check failed for %s: %s", concept, e)
        return 0
    finally:
        conn.close()


def _supply_score(concept: str) -> int:
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM items "
            "WHERE name ILIKE %s AND favorite_count > 5",
            (f"%{concept}%",)
        )
        val = cur.fetchone()[0] or 0
        cur.close()
        return val
    except Exception as e:
        log.warning("supply check failed for %s: %s", concept, e)
        return 0
    finally:
        conn.close()


# ── Movement-shaped prompt ────────────────────────────────────
PROMPT = """You are a Roblox UGC emote strategist.

Seed: "{seed}"

Real Roblox search phrases for reference:
{examples}

Generate {n} concepts for a Roblox EMOTE.

CRITICAL: every concept must describe a MOVEMENT or ACTION.
Reject anything that is only a vibe, person-type, or aesthetic tag.

Spread across these 3 flavors (~7 each):
1. RELAXED — chill, mellow, soft, lazy, smooth
2. ENERGETIC — bouncy, snappy, hyped, poppy, glitchy
3. CHARACTER — swaggy, confident, sassy, smooth, cool

Rules:
- 1-3 words each
- Kid-style — what a 12yo types into Roblox search
- Must be a movement/action phrase, not just a mood tag
- Do NOT recombine the seed words
- Each concept distinct in feel, not just wording

GOOD: chill bounce · snappy step · swag walk · glitch hop · smooth slide
BAD:  mall goth · sigma glare · viral beat · main character  ← not movements

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
            seen.add(c); out.append(c)
    return out


# ── Public API ────────────────────────────────────────────────
def expand_with_validation(seed: str, n: int = 20) -> dict:
    examples = _fetch_real_suggestions(seed, limit=30)
    block = "\n".join(f"- {e}" for e in examples) or "(none found)"
    raw = _call_gemini(PROMPT.format(seed=seed, n=n, examples=block))
    concepts = _parse(raw) if raw else []

    results, discarded = [], []
    for c in concepts:
        d = _demand_score(c)
        s = _supply_score(c)
        row = {"concept": c, "demand": d, "supply": s}
        if d == 0:
            row["verdict"] = "hallucinated"; discarded.append(row)
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

    return {"results": results, "discarded": discarded,
            "examples": examples, "raw": raw or ""}


def get_creative_seeds(seed_text: str, max_seeds: int = 8,
                       category: str | None = None) -> list[str]:
    """
    For smart_pipeline. `category` is accepted for future propagation
    but not used in v4 — kept so brainstorm integration doesn't need
    to change signatures later.
    """
    data = expand_with_validation(seed_text, n=20)
    good = [r["concept"] for r in data["results"]
            if r["verdict"] in ("gold", "opportunity")]
    return good[:max_seeds]
