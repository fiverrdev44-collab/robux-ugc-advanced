"""Pure, category-grounded listing-copy quality gate. Not a CTR prediction."""
import re

GENERIC = (
    "perfect for your", "perfect for any", "next avatar look",
    "for your roblox avatar", "elevate", "enhance", "seamless",
    "ultimate", "designed for", "designed to", "stand out from",
    "bring your avatar to life", "take your avatar", "add a touch of",
    "you'll love", "must-have", "high-converting", "best selling",
    "aesthetic vibes", "matches every outfit", "matches any outfit",
    "chillin with friends", "experience this", "unlock your style",
    "scene for your avatar", "background for your avatar",
    "vibrant cartoon scene", "vibrant scene for", "perfect for cheerful",
    "made for every avatar", "complete your look", "looks great with any",
)
PROMO = ("join our", "join the group", "check out our", "shop now",
         "follow us", "subscribe", "more ugc", "visit our", "discord.gg")
UNSUPPORTED = {
    "animated", "interactive", "parallax", "glowing", "glows", "sparkling",
    "moving", "moves", "motion", "3d", "4k", "limited", "official",
    "exclusive", "rare", "guaranteed", "viral", "trending",
}
MOTION = {
    "move", "moves", "moving", "spin", "spins", "spinning",
    "flip", "flips", "flipping", "kick", "kicks", "kicking",
    "dance", "dances", "dancing", "sway", "sways", "swaying",
    "run", "runs", "running", "walk", "walks", "walking",
    "jump", "jumps", "jumping", "wave", "waves", "waving",
    "bounce", "bounces", "bouncing",
}
STOP = {
    "a", "an", "the", "and", "or", "for", "to", "from", "with", "of",
    "in", "on", "at", "your", "our", "this", "that", "my", "is", "it",
    "ugc", "roblox", "avatar", "background", "emote", "item", "scene",
    "create", "make", "research", "recommend", "prioritize", "title",
    "description", "live", "ctr", "high", "best", "premium",
}

def words(value):
    return set(re.findall(r"[a-z0-9]+", (value or "").lower()))

def fact_source(concept, max_chars=350):
    """Keep creator facts, not appended research and prompt instructions."""
    value = re.sub(r"\s+", " ", str(concept or "")).strip()
    value = re.sub(r"^(?:backgrounds?|emotes?|hair|hats?|accessory|face|back|neck|waist):", "", value, flags=re.I).strip()
    value = re.split(
        r"(?i)(?:\.\s+|\n)(?=(?:create|research|recommend|prioritize|analyze|compare|explain|write|generate|no invented|give)\b)",
        value, maxsplit=1
    )[0]
    return value[:max_chars].strip(" ,.;")

def _feature_phrases(concept, limit=3):
    """Use only literal creator-described features, without fabricating props."""
    value = fact_source(concept)
    if re.search(r"\bwith\b", value, re.I):
        value = re.split(r"\bwith\b", value, maxsplit=1, flags=re.I)[-1]
    out = []
    for chunk in re.split(r",|;|\s+and\s+", value, flags=re.I):
        part = re.sub(r"^(?:a|an|the)\s+", "", chunk.strip(" .!"), flags=re.I)
        if not 2 <= len(part.split()) <= 6:
            continue
        if any(re.search(r"\b" + re.escape(t) + r"\b", part, re.I)
               for t in ("recommend", "analyze", "research", "prompt", "title",
                         "marketplace", "compare", "ctr", "description", "command")):
            continue
        if part.casefold() not in [v.casefold() for v in out]:
            out.append(part)
        if len(out) >= limit:
            break
    return out

def style_guidance(family):
    """Only stylistic guidance, not copied competitor text or fake CTR claims."""
    fam = str(family or "").lower()
    if fam in ("background", "backgrounds"):
        category_rule = ("Name the actual scene and one or two visible landmarks. "
                         "Never imply static artwork is animated or interactive.")
    elif fam in ("emote", "emotes"):
        category_rule = ("Use only movements stated in creator-supplied descriptions "
                         "or previews, never guessed from a thumbnail.")
    else:
        category_rule = ("Describe explicitly supplied shape, texture and details. "
                         "Do not invent materials, fit, effects or movement.")
    return (
        "Write like a real individual Roblox creator: casual, clear, specific, "
        "and concise, not a chatbot or marketer. Write 2-3 natural short lines; "
        "an emoji is optional. Begin with the item and a distinctive true detail. "
        "Do not use forced calls to action, keyword lists or vague hype. "
        "Avoid 'perfect for your next avatar look', 'chillin with friends', "
        "'enhance', 'elevate', 'seamless', and 'designed for'. "
        "No claims of high CTR, ranking, sales or guaranteed popularity. "
        "Never copy competitor description wording. " + category_rule
    )

def _normalize(text):
    out = []
    for line in str(text or "").replace("\r", "\n").split("\n"):
        line = re.sub(r"[*#\x60]+", "", line).strip(" \t-")
        if not line or re.match(r"(?i)^(?:description|tags|keywords|seo)\s*:", line):
            continue
        out.append(line)
    return "\n".join(out[:4]).strip()[:420]

def rejection_reason(description, concept, family, title=""):
    text = _normalize(description)
    if len(text) < 22:
        return "too_short"
    low = text.casefold()
    if any(p in low for p in GENERIC):
        return "generic_template"
    if any(p in low for p in PROMO) or re.search(r"https?://|www\.|discord\.gg|@\w+|#[\w]+", text, re.I):
        return "promo"
    if re.search(r"(?i)\b(?:guaranteed|top[\s-]ranked|best[\s-]seller|high[\s-]ctr|proven sales)\b", text):
        return "unverified_performance"
    # Data coverage alone cannot distinguish a natural sentence from a feature
    # inventory. Stop accepting 'Features a ...' as a fresh sentence or
    # lowercase, mechanically assembled catalogue fragments.
    if re.search(r"(?im)(?:^|[.!?]\s+)(?:features?|includes?|contains?)\s+(?:an?\s+)?", text):
        return "feature_inventory"
    if re.search(r"(?m)^\s*[a-z]", text):
        return "uncapitalized_sentence"
    if re.search(r"(?m)[.!?]\s+[a-z]", text):
        return "uncapitalized_sentence"
    allowed = words(fact_source(concept) + " " + title)
    used = words(text)
    if str(family or "").lower() not in ("emote", "emotes"):
        if (used & MOTION) - allowed:
            return "unsupported_motion"
    for claim in UNSUPPORTED:
        if claim in used and claim not in allowed:
            return "unverified_feature:" + claim
    if len(text.split()) > 85:
        return "overlong"
    facts = words(fact_source(concept)) - STOP
    if len(facts) >= 3 and len(used & facts) < 2:
        return "missing_item_specifics"
    return None

def fallback_description(concept, family, title=""):
    """Short, factual fallback without invented item properties."""
    heading = re.sub(r"\s+", " ", str(title or "")).strip(" \n.;")[:85]
    source = fact_source(concept)
    if not heading:
        heading = " ".join(source.split()[:6]).strip(" .!,") or "Avatar item"
    parts = _feature_phrases(concept)
    if len(parts) >= 2:
        return (heading + "\n" + parts[0][0].upper() + parts[0][1:] +
                " and " + parts[1] + ".")[:320]
    if len(parts) == 1:
        return (heading + "\n" + parts[0][0].upper() + parts[0][1:] + ".")[:320]
    brief = source[:160].strip(" .!")
    if brief and brief.casefold() not in heading.casefold() and len(brief.split()) >= 3:
        return heading + "\n" + brief[0].upper() + brief[1:] + "."
    return heading

def polish_description(draft, concept, family, title=""):
    """Use grounded item details; reject generic or unsupported generated copy."""
    normalized = _normalize(draft)
    return (normalized if rejection_reason(normalized, concept, family, title) is None
            else fallback_description(concept, family, title))


def rewrite_prompt(draft, concept, family, title=""):
    """One optional *editorial* rewrite, never a live market-performance claim."""
    return (
        "You are writing a Roblox item description as an individual creator.\n"
        "Rewrite the draft into genuinely natural, engaging, specific listing copy.\n"
        "Do not polish the SAME template; find the distinctive hook in the facts.\n"
        "Use two natural sentences or two short lines; no required emoji.\n"
        "An everyday, slightly playful voice is welcome where it fits, but "
        "avoid marketer clichés and robotic feature inventories.\n"
        "Start with a strong subject/scene detail rather than 'Features a'.\n"
        "Do NOT end with 'for your avatar', a generic mood/vibe sentence, "
        "a CTA or claims of ranking, sales, CTR or popularity.\n"
        "No invented motion, special effects, materials, characters or props.\n"
        "Do not reuse descriptions from competitor listings.\n"
        "Keep only facts supported by CREATOR DETAILS. If something is "
        "unspecified, leave it out.\n"
        + style_guidance(family) + "\n"
        + "CATEGORY: " + str(family or "unknown") + "\n"
        + "ITEM TITLE (descriptive, not evidence of popularity): "
        + str(title or "")[:90] + "\n"
        + "CREATOR DETAILS: " + fact_source(concept) + "\n"
        + "WEAK DRAFT (rewrite, do not copy the phrasing): "
        + _normalize(draft)[:280] + "\n"
        + "Return only your final listing description."
    )


def finalize_description(draft, concept, family, title="", rewrite_fn=None):
    """One bounded model rewrite only when necessary, then a factual fallback.

    The model callback (if supplied) is invoked at most once. It is not an
    autonomous retry loop and returns no marketplace performance inference.
    """
    initial = rejection_reason(draft, concept, family, title)
    if initial is None:
        return {"text": _normalize(draft), "quality_status": "accepted",
                "initial_rejection": None, "rewrite_attempted": False}
    attempted = False
    if callable(rewrite_fn):
        attempted = True
        try:
            proposed = rewrite_fn(rewrite_prompt(draft, concept, family, title))
            if isinstance(proposed, str) and (
                rejection_reason(proposed, concept, family, title) is None
            ):
                return {"text": _normalize(proposed), "quality_status": "rewritten",
                        "initial_rejection": initial, "rewrite_attempted": True}
        except Exception:
            # The model and API can fail. This must remain a safe local fallback.
            pass
    return {"text": fallback_description(concept, family, title),
            "quality_status": "factual_fallback",
            "initial_rejection": initial, "rewrite_attempted": attempted}
