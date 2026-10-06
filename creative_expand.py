"""
creative_expand.py — Category-aware AI fan-out + demand gate.

Public API (unchanged):
  expand_with_validation(anchor, n=20, ...) -> dict
  get_creative_seeds(seed, max_seeds=8, ...) -> list

NEW: item_type and category_asset_ids are first-class params.
When not passed, defaults to emote for backward compat.
"""
import os
import re
import json
from collections import Counter

from category_configs import (
    get_category_config,
    detect_family_from_intent,
    get_filler_block,
)

SUPPLY_UNDERSERVED = 50
SUPPLY_SATURATED = 200


# ============================================================
# DB helpers
# ============================================================
def _fetch_real_suggestions(cur, seed, limit=30):
    """Pull real Roblox search suggestions related to the seed.
    Uses BOTH tables (search_suggestions.suggestion + learned_keywords.keyword)."""
    if not cur or not seed:
        return []
    words = [w for w in re.findall(r"[a-z]{3,}", (seed or "").lower())]
    if not words:
        return []
    patterns = [f"%{w}%" for w in words[:4]]
    out = []
    try:
        cur.execute("""
            SELECT DISTINCT suggestion FROM search_suggestions
            WHERE LOWER(suggestion) LIKE ANY(%s)
            LIMIT %s
        """, (patterns, limit))
        out.extend([r[0] for r in cur.fetchall() if r[0]])
    except Exception as e:
        print(f"[creative_expand] search_suggestions failed: {e}", flush=True)
    try:
        # GROUP BY keyword instead of DISTINCT — allows ORDER BY MAX(score)
        cur.execute("""
            SELECT keyword, MAX(score) AS s
            FROM learned_keywords
            WHERE LOWER(keyword) LIKE ANY(%s)
            GROUP BY keyword
            ORDER BY s DESC
            LIMIT %s
        """, (patterns, limit))
        out.extend([r[0] for r in cur.fetchall() if r[0]])
    except Exception as e:
        print(f"[creative_expand] learned_keywords failed: {e}", flush=True)
    seen, final = set(), []
    for s in out:
        k = (s or "").lower().strip()
        if k and k not in seen:
            seen.add(k)
            final.append(k)
    return final[:limit]


def _classify_concept(cur, concept, category_asset_ids=None):
    """Return (demand, supply) for a single concept."""
    demand, supply = 0, 0
    word = (concept or "").lower().strip()
    if not word or not cur:
        return demand, supply
    try:
        cur.execute("""
            SELECT COUNT(DISTINCT suggestion) FROM search_suggestions
            WHERE LOWER(suggestion) LIKE %s
        """, (f"%{word}%",))
        demand = cur.fetchone()[0] or 0
    except Exception:
        pass
    try:
        if category_asset_ids:
            cur.execute("""
                SELECT COUNT(*) FROM items
                WHERE LOWER(name) LIKE %s
                  AND favorite_count > 5
                  AND asset_type_id = ANY(%s)
            """, (f"%{word}%", list(category_asset_ids)))
        else:
            cur.execute("""
                SELECT COUNT(*) FROM items
                WHERE LOWER(name) LIKE %s AND favorite_count > 5
            """, (f"%{word}%",))
        supply = cur.fetchone()[0] or 0
    except Exception:
        pass
    return demand, supply


def _verdict(demand, supply):
    if demand == 0:
        return "hallucinated"
    if supply == 0:
        return "gold"
    if supply < SUPPLY_UNDERSERVED:
        return "opportunity"
    if supply < SUPPLY_SATURATED:
        return "contested"
    return "saturated"


# ============================================================
# Prompt builder — category-aware
# ============================================================
def _build_prompt(seed, real_phrases, config, n=20):
    bucket_text = "\n".join(
        f"  - {b['name']}: {b['vibe']}" for b in config["buckets"]
    )
    bucket_names = [b["name"] for b in config["buckets"]]
    archetypes = "\n".join(f"  - {a}" for a in config["title_archetypes"][:6])
    filler = list(config["filler_block"])[:20]
    return f"""You are a Roblox UGC creative concept generator for the '{config['label']}' category.

ANCHOR (what the item is):
{seed}

REAL ROBLOX SEARCHES that players are typing right now (inspiration, not copy):
{', '.join(real_phrases[:30]) if real_phrases else '(no real search data)'}

=== YOUR JOB ===
Generate exactly {n} CONCEPTS. Each concept is 1-3 words.
Distribute across these buckets:
{bucket_text}

=== SHAPE RULE ===
{config['shape_rule']}

=== EXAMPLE TITLE STRUCTURES (for reference, do NOT copy these) ===
{archetypes}

=== FORBIDDEN ===
- Do NOT invent brand names or IP names.
- Do NOT include the item-type word itself (e.g. don't include "hair" in the concept).
- Do NOT use filler words: {', '.join(filler)}
- Do NOT repeat concepts.
- Do NOT generate generic single-word adjectives (cool, nice, awesome, good).
- Every concept MUST be something a real player would type into Roblox search.

=== OUTPUT — ONLY JSON ===
{{
  "concepts": [
    {{"concept": "...", "bucket": "<one of: {', '.join(bucket_names)}>"}},
    ...
  ]
}}
"""


# ============================================================
# Public API
# ============================================================
def expand_with_validation(anchor, n=20, item_type="emote",
                            category_asset_ids=None, db_factory=None):
    """
    AI fan-out + demand gate.
    Returns {"anchor":..., "results":[{concept,bucket,demand,supply,verdict},...],
             "buckets":[...], "family": "..."}
    """
    config = get_category_config(item_type)
    family = config["label"]

    if db_factory is None:
        try:
            from bot_core import get_db as db_factory
        except Exception:
            db_factory = None

    conn = None
    cur = None
    try:
        if db_factory is not None:
            conn = db_factory()
            cur = conn.cursor()

        real_phrases = _fetch_real_suggestions(cur, anchor, limit=30)
        prompt = _build_prompt(anchor, real_phrases, config, n=n)

        try:
            from gemini_brain import _generate
            raw = _generate(prompt, json_mode=True, temperature=0.95,
                            max_tokens=1000)
        except Exception as e:
            print(f"[creative_expand] generate failed: {e}", flush=True)
            return {"anchor": anchor, "results": [], "buckets": config["buckets"],
                    "family": family}

        if not raw:
            return {"anchor": anchor, "results": [], "buckets": config["buckets"],
                    "family": family}

        try:
            data = json.loads(raw)
        except Exception:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            data = json.loads(m.group(0)) if m else {}

        concepts = data.get("concepts") or []
        results = []
        seen = set()
        for c in concepts:
            concept = (c.get("concept") or "").lower().strip()
            if not concept or concept in seen:
                continue
            seen.add(concept)
            demand, supply = _classify_concept(cur, concept, category_asset_ids)
            verdict = _verdict(demand, supply)
            if verdict == "hallucinated":
                continue
            results.append({
                "concept": concept,
                "bucket": c.get("bucket") or "UNKNOWN",
                "demand": demand,
                "supply": supply,
                "verdict": verdict,
            })

        return {
            "anchor": anchor,
            "results": results,
            "buckets": config["buckets"],
            "family": family,
        }
    finally:
        if cur is not None:
            try: cur.close()
            except Exception: pass
        if conn is not None:
            try: conn.close()
            except Exception: pass


def get_creative_seeds(seed, max_seeds=8, item_type="emote",
                        category_asset_ids=None, db_factory=None):
    """Return top N concept strings, ranked by verdict + demand."""
    data = expand_with_validation(seed, n=20, item_type=item_type,
                                    category_asset_ids=category_asset_ids,
                                    db_factory=db_factory)
    rank = {"gold": 0, "opportunity": 1, "contested": 2, "saturated": 3}
    sorted_r = sorted(data.get("results") or [],
                       key=lambda r: (rank.get(r["verdict"], 9), -r["demand"]))
    return [r["concept"] for r in sorted_r[:max_seeds]]
