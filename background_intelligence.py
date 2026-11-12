"""Avatar Background artwork intelligence: grounded, low-cost decision support.

Pure helpers only; callers handle image IO, AI and live API budget. AI vision
descriptions are observations to verify, not proof of an on-platform claim.
"""
import re
from background_niche import SCENE_ANCHORS
from product_understanding import validate_title

_SOURCE_MAX = 220
_FILLER = {
    "a", "an", "and", "the", "with", "at", "in", "on", "of", "for", "by",
    "is", "it", "to", "from", "my", "your", "our", "their", "avatar",
    "background", "backgrounds", "scene", "roblox", "ugc", "beautiful",
    "awesome", "stunning", "viral", "trending", "popular", "picture",
    "image", "this", "that", "style", "featuring", "has", "have", "there",
}
_BAD_SCENE_PARTS = {
    "ignore", "instructions", "assistant", "developer", "system", "prompt",
    "token", "password", "secret", "key", "execute", "javascript", "python",
}
_SCENE_FALLBACKS = ("shrine", "forest", "city", "space", "sky", "garden",
                    "portal", "room", "street", "beach", "cave", "castle")
_ALLOWED_OBS = (
    "visual_summary", "search_description", "composition_notes",
    "visual_colors", "visual_style", "distinctive_features",
    "visual_mood", "ip_reference_warning", "scene_focal_point",
    "avatar_clearance_notes", "ground_horizon_notes",
    "mobile_readability_notes", "depth_layers_notes",
    "lighting_notes",
)


def _short_text(value, max_chars=_SOURCE_MAX):
    """Treat model output as untrusted data: bound length and strip markup."""
    if isinstance(value, (list, dict)):
        return ""
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()
    return re.sub(r"\s+", " ", value).replace("\`", "")[:max_chars]


def _items(value, limit=4):
    if not isinstance(value, (list, tuple)):
        value = [value] if isinstance(value, str) else []
    return [_short_text(v, 54) for v in value[:limit] if _short_text(v, 54)]


def _is_untrusted_instruction(text):
    words = set(re.findall(r"[a-z]+", (text or "").lower()))
    return bool(words & _BAD_SCENE_PARTS)


def observations(vision):
    """Bound and normalize selected fields only, never accept arbitrary JSON."""
    v = vision if isinstance(vision, dict) else {}
    out = {}
    for key in _ALLOWED_OBS:
        out[key] = (_items(v.get(key))
                    if key in ("visual_colors", "visual_style",
                               "distinctive_features", "visual_mood")
                    else _short_text(v.get(key)))
    return out


def scene_phrase(vision, notes=""):
    """A conservative two- or three-word phrase, NOT a demand prediction."""
    o = observations(vision)
    # Prefer creator notes, then visual description, and never guess a place
    # that neither the creator nor the vision provider mentioned.
    candidates = [_short_text(notes, 300), o["search_description"],
                  o["visual_summary"]] + o["distinctive_features"]
    for text in candidates:
        if _is_untrusted_instruction(text):
            continue
        toks = re.findall(r"[a-z]+", text.lower())
        for i, tok in enumerate(toks):
            if tok not in SCENE_ANCHORS and tok not in _SCENE_FALLBACKS:
                continue
            previous = (toks[i - 1] if i else "")
            following = (toks[i + 1] if i + 1 < len(toks) else "")
            if previous and previous not in _FILLER and len(previous) > 2:
                return f"{previous} {tok}"
            if following and following not in _FILLER and len(following) > 2:
                return f"{tok} {following}"
            return tok
    return None


def grounded_concept(vision, notes=""):
    """Conservative input for !chain; never claim visual facts are verified."""
    o = observations(vision)
    # Creator notes have priority; model annotations are clearly separated.
    user = _short_text(notes, 260)
    summary = o["visual_summary"]
    if _is_untrusted_instruction(summary):
        summary = ""
    features = [x for x in o["distinctive_features"]
                if not _is_untrusted_instruction(x)][:4]
    descriptors = [x for x in o["visual_colors"][:3] + o["visual_style"][:2]
                   if not _is_untrusted_instruction(x)]
    parts = []
    if user:
        parts.append(user)
    if summary:
        parts.append("AI image observations (check against artwork): " + summary)
    if features:
        parts.append("Reported visible details: " + ", ".join(features))
    if descriptors:
        parts.append("Reported colors/style: " + ", ".join(descriptors))
    return ". ".join(parts)[:580].strip(" .")


def candidate_titles(vision, notes="", limit=6):
    """Grounded candidate names; no CTR or uniqueness scoring fabricated."""
    o = observations(vision)
    seed = scene_phrase(vision, notes)
    if not seed:
        return []
    seed_words = seed.title()
    candidates = [
        f"{seed_words} Background",
        f"{seed_words} Avatar Background",
    ]
    features = o["distinctive_features"]
    for f in features[:4]:
        if _is_untrusted_instruction(f):
            continue
        words = [w for w in re.findall(r"[a-z]+", f.lower())
                 if w not in _FILLER and w not in _BAD_SCENE_PARTS]
        if not words:
            continue
        # A feature-based title must keep the original scene identity.
        prefix = " ".join(words[:2]).title()
        if prefix.lower() not in seed.lower() and len(prefix.split()) <= 2:
            candidates.append(f"{prefix} {seed_words} Background")
    seen, out = set(), []
    for title in candidates:
        if len(title.split()) > 7 or len(title) > 65:
            continue
        key = title.casefold()
        if key in seen:
            continue
        ok, _ = validate_title(notes, title, family="backgrounds")
        if not ok:
            continue
        seen.add(key)
        out.append(title)
        if len(out) >= max(1, min(limit, 8)):
            break
    return out


def format_background_dossier(vision, notes="", image_quality=None,
                              live=None, include_titles=True):
    """A readable audit with unknowns and externally measured facts separated."""
    o = observations(vision)
    parts = ["# 🌌 BACKGROUND ARTWORK INTELLIGENCE",
             "_AI image interpretation; verify details against your artwork. "
             "No measured CTR, impressions, conversion, or sales are inferred._"]
    parts.append("**Scene identity**")
    parts.append(
        "• " + (o["visual_summary"] or
                 "Not established; supply a clearer image or creator notes.")
    )
    phrase = scene_phrase(vision, notes)
    parts.append(f"• Searchable scene anchor: \`{phrase}\` (descriptive only)"
                 if phrase else "• Scene anchor unavailable; avoid guessing a niche.")
    parts.append("**Visual design**")
    parts.append("• Palette: " + (", ".join(o["visual_colors"]) or "not verified"))
    parts.append("• Style: " + (", ".join(o["visual_style"]) or "not verified"))
    parts.append("• Distinctive features: " + (
        ", ".join(o["distinctive_features"]) or "not verified"))
    for label, key in (
        ("Focal point", "scene_focal_point"),
        ("Avatar clearance", "avatar_clearance_notes"),
        ("Ground/horizon", "ground_horizon_notes"),
        ("Mobile cropping", "mobile_readability_notes"),
        ("Depth layers", "depth_layers_notes"),
        ("Lighting", "lighting_notes"),
    ):
        parts.append(f"• {label}: {o[key] or 'not determined—check manually'}")
    parts.append("**Export / publishing checks**")
    if isinstance(image_quality, dict):
        dims = (f"{image_quality.get('width') or '?'}×"
                f"{image_quality.get('height') or '?'}")
        fmt = image_quality.get("format") or "unknown"
        parts.append(f"• Image: {dims} · {fmt} · " +
                     ("format and dimensions passed" if image_quality.get("ok")
                      else "needs export review"))
        for err in (image_quality.get("errors") or [])[:4]:
            parts.append("• Fix: " + _short_text(err, 160))
        for warning in (image_quality.get("warnings") or [])[:3]:
            parts.append("• Note: " + _short_text(warning, 160))
    else:
        parts.append("• Upload source dimensions/alpha could not be validated.")
    parts.append("• Preview with a centered avatar on mobile and desktop; "
                 "an image alone cannot verify final Roblox crop.")
    if include_titles:
        titles = candidate_titles(vision, notes)
        parts.append("**Title experiments (not CTR predictions)**")
        if titles:
            parts.extend("• " + t for t in titles[:6])
        else:
            parts.append("• No defensible title without a clearly identified scene.")
    parts.append("**Background-only live marketplace sample**")
    if not live:
        parts.append("• Not checked. No competitor or demand claim.")
    elif not live.get("ok"):
        parts.append("• Unavailable (" +
                     _short_text(live.get("error") or "unknown", 80) +
                     "). Do not interpret a failed request as zero competitors.")
    else:
        count = int(live.get("category_correct") or 0)
        sampled = int(live.get("sampled_results") or 0)
        parts.append(f"• {count} verified AssetType 92 items in "
                     f"{sampled} sampled search results.")
        parts.append("• Sampled competitor counts do not prove full-category "
                     "absence, demand, sales, or title CTR.")
        for row in (live.get("top_competitors") or [])[:3]:
            parts.append("• " + _short_text(row.get("name"), 85) +
                         " (verified background listing)")
    ip_warning = o["ip_reference_warning"]
    if ip_warning and ip_warning.upper() != "NONE":
        parts.append("**IP/trademark caution:** " + ip_warning +
                     " — avoid protected names without authorization.")
    parts.append("**Launch measurement:** compare clear, truthful titles; "
                 "record favorites at D1/D7/D14, and sales from your own ledger. "
                 "Only calculate CTR if you have real impressions and clicks.")
    return "\n".join(parts)


def discord_chunks(text, limit=1800):
    """Split at line boundaries where possible; never exceed Discord limits."""
    lines = (text or "").split("\n")
    out, cur = [], ""
    for line in lines:
        while len(line) > limit:
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:limit])
            line = line[limit:]
        candidate = f"{cur}\n{line}" if cur else line
        if len(candidate) > limit:
            out.append(cur)
            cur = line
        else:
            cur = candidate
    if cur:
        out.append(cur)
    return out
