"""astra.py — Rankability heuristic, platform-name guard, identity lock,
provider JSON config, and the Astra output structure.

All scores here are explicitly heuristic (never probabilities). When live
evidence is unavailable the heuristic returns unavailable, not a number.
"""
import re
import unicodedata

MOTION_TOKENS = {
    "pose", "dance", "idle", "float", "sway", "kick", "walk", "run",
    "spin", "flip", "sit", "wave", "shake", "jump", "fall", "death",
    "strut", "lean", "stance", "moonwalk",
}

BANNED_PLATFORM_WORDS = ("tiktok", "youtube", "viral", "trending")


def _squash(text):
    """NFKC + keep only alphanumerics so T.i.k.T.o.k becomes tiktok."""
    norm = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[^a-z0-9]+", "", norm)


def contains_banned_platform(text):
    squashed = _squash(text)
    return any(word in squashed for word in BANNED_PLATFORM_WORDS)


def _tokens(text):
    norm = unicodedata.normalize("NFKC", text or "").lower()
    return set(re.findall(r"[a-z0-9]+", norm))


def _motions(text):
    return _tokens(text) & MOTION_TOKENS


def identity_lock_ok(concept, title):
    """Reject titles that swap the requested motion for a different one."""
    concept_motions = _motions(concept)
    if not concept_motions:
        return True
    foreign = _motions(title) - concept_motions
    return not foreign


def provider_json_config(provider):
    """Provider-specific structured-output configuration."""
    p = (provider or "").lower()
    if p in ("gemini", "google"):
        return {"response_mime_type": "application/json"}
    if p in ("deepseek", "openrouter", "openai-compatible"):
        return {"response_format": {"type": "json_object"}}
    return {}


def rankability_heuristic(results, concept, asset_type=None,
                          exact_count=0, checked=None, ok=True):
    """Heuristic 0–100 rankability score with explicit components.

    Returns available=False when live evidence is missing/failed.
    """
    if not ok or results is None:
        return {"available": False, "label": "heuristic",
                "not_probability": True,
                "reason": "live evidence unavailable"}
    results = list(results)
    checked = int(checked if checked is not None else len(results))
    if checked <= 0:
        return {"available": False, "label": "heuristic",
                "not_probability": True, "reason": "no sampled results"}

    concept_tokens = _tokens(concept)
    concept_motions = _motions(concept)

    relevance_hits = 0
    fit_hits = 0
    motion_hits = 0
    fit_known = 0
    for r in results:
        name_tokens = _tokens(r.get("name") or "")
        if concept_tokens & name_tokens:
            relevance_hits += 1
        atype = r.get("assetType") or r.get("asset_type_id")
        if asset_type is not None and atype is not None:
            fit_known += 1
            if int(atype) == int(asset_type):
                fit_hits += 1
        if concept_motions and (_motions(r.get("name") or "") & concept_motions):
            motion_hits += 1

    relevance = relevance_hits / checked
    product_fit = (fit_hits / fit_known) if fit_known else 0.5
    motion_fit = (motion_hits / checked) if concept_motions else 0.5
    # Modest penalty for exact competitors; zero exact is not rewarded blindly.
    differentiation = max(0.35, 1.0 - 0.12 * max(0, int(exact_count)))
    coverage = min(1.0, checked / 30.0)

    score = 100.0 * (
        0.30 * relevance + 0.25 * product_fit + 0.20 * motion_fit +
        0.15 * differentiation + 0.10 * coverage
    )
    return {
        "available": True, "score": round(score, 1), "label": "heuristic",
        "not_probability": True,
        "components": {
            "relevance": round(relevance, 3),
            "product_fit": round(product_fit, 3),
            "motion_fit": round(motion_fit, 3),
            "differentiation": round(differentiation, 3),
            "coverage": round(coverage, 3),
        },
        "checked": checked,
        "exact_count": int(exact_count),
        "note": "Heuristic only; exact=0 is not proof of an open market.",
    }


def to_three_sentences(text):
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", (text or "").strip())
             if p.strip()]
    if len(parts) >= 3:
        return " ".join(parts[:3]), True
    return (text or "").strip(), False


def format_astra(analysis, titles, description, brief):
    """Astra output: analysis, titled angles, 3-sentence description, brief."""
    desc, ok = to_three_sentences(description)
    lines = ["# ASTRA OUTPUT", "", "## Analysis Summary",
             f"- Culture: {analysis.get('culture', 'not available')}",
             f"- Buyer intent: {analysis.get('buyer_intent', 'not available')}",
             f"- Keyword plan: {analysis.get('keyword_plan', 'not available')}",
             f"- Evidence limits: {analysis.get('evidence_limits', 'not available')}",
             "", "## Titles"]
    for t in list(titles)[:5]:
        lines.append(f"- **{t.get('title', '')}** — {t.get('angle', 'candidate')}")
    lines += ["", "## Description",
              desc if desc else "(description unavailable)"]
    if not ok:
        lines.append("_(description did not reach exactly 3 sentences; review needed)_")
    lines += ["", "## Preview / Experiment Brief",
              f"- Showcase: {brief.get('showcase', 'not specified')}",
              f"- Experiment: {brief.get('experiment', 'not specified')}"]
    return "\n".join(lines)
