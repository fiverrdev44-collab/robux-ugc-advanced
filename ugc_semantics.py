"""Category-identity gates shared by UGC creative and market evidence paths.

A marketplace keyword is a search observation, NOT proof that it describes a
creator's product. These conservative checks keep merchandise terms out of
emote naming and prevent unsupported identity changes. Explicit creator intent
may permit an aesthetic but never grants fabricated motion/appearance claims.
"""
import re

_APPAREL = {
    "streetwear", "hoodie", "hoodies", "jeans", "denim", "outfit",
    "outfits", "shirt", "shirts", "pants", "jacket", "jackets",
    "sweater", "sweaters", "clothing", "sneaker", "sneakers",
    "beanie", "beanies", "hat", "hats", "skirt", "skirts", "dress",
    "dresses", "socks", "uniform", "shirtless",
}
_MOTION = {
    "dance", "dancing", "emote", "emotes", "animation", "animations",
    "pose", "posing", "stance", "idle", "sway", "step", "steps", "spin", "flip",
    "jump", "bounce", "kick", "wave", "walk", "run", "clap",
    "twirl", "slide", "shuffle", "groove", "hiphop", "hip",
    "hop", "freestyle", "stomp", "robot", "pump", "rhythm",
}
_SEARCH_PSEUDO = {"viral", "trending", "tiktok", "youtube"}
_FOREIGN_DESCRIPTION = re.compile(
    r"\b(?:fortnite|item\s+shop|battle\s+pass|epic\s+games|"
    r"minecraft\s+marketplace)\b", re.I,
)


def _words(value):
    return set(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _family(family):
    from category_configs import resolve_family_name
    canonical = resolve_family_name(family) if family else ""
    return "emote" if canonical in ("emotes", "emote") else canonical


def is_off_family_word(word, family, concept=""):
    """Reject category-confused suggestions; allow explicit aesthetic *intent*."""
    fam = _family(family)
    ws = _words(word)
    source = _words(concept)
    if not ws:
        return True
    if ws & _SEARCH_PSEUDO:
        return True
    if fam == "emote":
        # User-authorized styling is different from DB-invented styling.
        if (ws & _APPAREL) - source:
            return True
    if fam == "backgrounds":
        if ws & (_APPAREL | _MOTION) and not ws.issubset(source):
            return True
    return False


def grounded_keyword(value, family, concept="", *, for_alternative=False):
    """Keywords for niche research must be family-safe; alternate names need
    stronger grounding than broad unscoped suggestion volumes."""
    ws = _words(value)
    if not ws or is_off_family_word(value, family, concept):
        return False
    if not for_alternative:
        return True
    fam = _family(family)
    if ws.issubset(_words(concept)):
        return True
    from category_configs import get_category_config
    vocab = set(get_category_config(fam).get("concept_vocab") or ())
    if fam == "emote":
        return bool(ws & _MOTION) and all(w in vocab or w in _MOTION for w in ws)
    return all(w in vocab for w in ws)


def title_is_grounded(concept, title, family):
    """Reject known off-family terms and unsupported product-type swapping.

    Does not predict search rank or prove whether a picture/motion shows a
    particular attribute. It is an additional structural safeguard.
    """
    fam = _family(family)
    candidate = _words(title)
    source = _words(concept)
    if not candidate:
        return False, "empty title"
    if is_off_family_word(title, fam, concept):
        return False, "unrelated category/garment/search-hype term"
    if fam == "emote":
        if not candidate & _MOTION:
            return False, "missing emote or movement identity"
        # Preserve explicitly named product identity (dance vs pose) unless
        # user deliberately included both. Motion details remain AI claims.
        # Keep the creator's actual requested motion noun, not a synonym
        # chosen only for a marketplace score.
        for noun, variants in (
            ("dance", {"dance", "dancing"}),
            ("pose", {"pose", "posing"}),
            ("stance", {"stance"}),
        ):
            if noun in source and not (candidate & variants):
                return False, noun + " identity replaced"
    if fam == "backgrounds":
        if not candidate & {"background", "backgrounds", "backdrop", "scene"}:
            return False, "missing avatar-background identity"
    return True, ""


def clean_creator_text_field(value, family, concept):
    """Drop ungrounded cross-domain paragraphs rather than silently rewriting
    misinformation. No links, arbitrary instructions or extra Roblox calls."""
    if not isinstance(value, str):
        return value
    if (is_off_family_word(value, family, concept)
            or re.search(r"\b(?:tiktok|youtube)\b", value, re.I)):
        return ""
    return value


def filter_intent_for_family(intent, family, concept):
    """Remove AI-expanded terms outside the stated product identity.

    Keep the user's own text intact; filter only fields inferred by AI.
    """
    if not isinstance(intent, dict):
        return intent
    out = dict(intent)
    for key in ("primary", "synonyms", "style", "vibe", "colors", "references",
                "specific_moves", "title_verbs", "search_terms"):
        value = out.get(key)
        if isinstance(value, list):
            out[key] = [
                entry for entry in value
                if isinstance(entry, str) and grounded_keyword(
                    entry, family, concept, for_alternative=True)
            ]
    return out


def sanitize_generated_strategy(synth, family, concept):
    """Final categorical editorial check on *all* AI suggestions, not only
    titles. Mutates only a local dict, never DB or user's existing listing."""
    if not isinstance(synth, dict):
        return synth
    for key in ("titles_safe", "titles_differentiated",
                "titles_longtail", "titles_viral"):
        if isinstance(synth.get(key), list):
            synth[key] = [
                t for t in synth[key]
                if isinstance(t, str)
                and title_is_grounded(concept, t, family)[0]
            ]
    if isinstance(synth.get("killer_keywords"), list):
        synth["killer_keywords"] = [
            kw for kw in synth["killer_keywords"]
            if isinstance(kw, str)
            and grounded_keyword(kw, family, concept, for_alternative=True)
        ]
    for key in ("bonus_plays",):
        if isinstance(synth.get(key), list):
            synth[key] = [
                t for t in synth[key] if isinstance(t, str)
                and not is_off_family_word(t, family, concept)
            ]
    for key in ("cross_promotion_play", "social_playbook", "cultural_ammo",
                "positioning", "winner_blueprint", "market_diagnosis",
                "search_diagnosis", "seo_description"):
        if key in synth:
            synth[key] = clean_creator_text_field(synth[key], family, concept)
    pivot = synth.get("best_pivot")
    if isinstance(pivot, dict) and not grounded_keyword(
            pivot.get("keyword"), family, concept, for_alternative=True):
        synth["best_pivot"] = {}
    return synth


def is_foreign_platform_description(name, description):
    """An externally sourced Fortnite description is not Roblox sales or
    product evidence, even if the same name appears in Roblox search."""
    return bool(_FOREIGN_DESCRIPTION.search(str(description or "")))
