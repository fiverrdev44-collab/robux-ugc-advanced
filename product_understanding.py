"""product_understanding.py — one structured understanding for every command.

Attributes carry their source: user, api, visual, inferred, unknown. The emote
rule is enforced here: a static image (including Roblox-generated thumbnails)
never yields motion; only creator-provided preview descriptions/metadata can.
Static accessories never carry motion requirements.
"""
import re

SOURCE_USER = "user"
SOURCE_API = "api"
SOURCE_VISUAL = "visual"
SOURCE_INFERRED = "inferred"
SOURCE_UNKNOWN = "unknown"

FAMILY_KEYWORDS = {
    "headwear": ("hat", "beanie", "cap", "beret", "crown", "visor", "headphones",
                 "helmet", "hood", "head accessory"),
    "face": ("mask", "glasses", "eyewear", "makeup", "face"),
    "neck": ("necklace", "chain", "choker", "scarf", "neck"),
    "shoulder": ("shoulder", "pauldron", "shoulder accessory"),
    "front": ("chest", "front accessory", "brooch"),
    "back": ("wings", "cape", "backpack", "tail", "back accessory"),
    "waist": ("waist", "belt", "waistband"),
    "hair": ("hair", "bangs", "ponytail", "braids"),
    "clothing": ("shirt", "pants", "jacket", "dress", "skirt", "clothing",
                 "outfit", "layered", "classic"),
    "emotes": ("emote", "dance", "pose", "idle", "animation", "moonwalk",
               "sway", "kick"),
    "backgrounds": ("background", "avatar background", "backdrop"),
}

MOTION_TOKENS = {
    "dance", "pose", "idle", "float", "sway", "kick", "walk", "run", "spin",
    "flip", "sit", "wave", "shake", "jump", "fall", "death", "strut", "lean",
    "stance", "moonwalk", "dancing", "posing", "swaying", "floating", "kicking", "jumping", "sitting", "waving", "spinning", "flipping", "falling", "walking", "running", "stancing", "strutting", "leaning", "moonwalking",
}

COLOR_WORDS = {
    "blue", "red", "green", "yellow", "purple", "pink", "black", "white",
    "brown", "beige", "gray", "grey", "orange", "gold", "silver", "cyan",
    "magenta", "pastel", "neon",
}

DETAIL_WORDS = {
    "ears", "eyes", "stripes", "horns", "tail", "wings", "paws", "teeth",
    "fangs", "ribbon", "bow", "stars", "glow", "spikes", "fur", "fluffy",
    "texture", "sign", "fence", "planks", "chain", "zipper", "pockets",
}

STATIC_FAMILIES = {"headwear", "face", "neck", "shoulder", "front", "back",
                   "waist", "hair", "clothing", "backgrounds"}
SCENE_FAMILIES = {"backgrounds"}


def _tokens(text):
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def classify_family(text):
    toks = set(_tokens(text))
    if {"background", "backgrounds", "backdrop"} & toks:
        return "backgrounds", 100
    best, score = None, 0
    for fam, words in FAMILY_KEYWORDS.items():
        hits = 0
        for w in words:
            if " " in w:
                if w in (text or "").lower():
                    hits += 2
            elif w in toks:
                hits += 1
        if hits > score:
            best, score = fam, hits
    return best, score


def motion_allowed(family):
    return family == "emotes"


def _attr(value, source, note=""):
    return {"value": value, "source": source, "note": note}


def from_text(text, explicit_family=None):
    """Understand a product from user text (highest-priority source)."""
    family, score = classify_family(text)
    family_source = SOURCE_USER if family else SOURCE_UNKNOWN
    if explicit_family:
        family, family_source = explicit_family, SOURCE_USER
    toks = _tokens(text)
    colors = sorted({t for t in toks if t in COLOR_WORDS})
    details = sorted({t for t in toks if t in DETAIL_WORDS})
    motion = sorted({t for t in toks if t in MOTION_TOKENS}) \
        if motion_allowed(family) else []
    unknowns = []
    if not family:
        unknowns.append("product family not stated")
    if not colors:
        unknowns.append("colors not stated")
    return {
        "family": family or "unknown",
        "family_source": family_source,
        "colors": [_attr(c, SOURCE_USER) for c in colors],
        "details": [_attr(d, SOURCE_USER) for d in details],
        "motion": [_attr(m, SOURCE_USER) for m in motion],
        "constraints": [text[:300]] if text else [],
        "unknowns": unknowns,
        "motion_required": bool(motion),
    }


def from_image(vision, text="", image_kind="attachment"):
    """Understand from an image + optional user text.

    image_kind: 'thumbnail' (Roblox-generated), 'attachment' (user image), or
    'preview' (creator-provided animation preview description).
    A static image never yields motion for emotes.
    """
    base = from_text(text)
    v = vision or {}
    vfam = (v.get("item_type_visual") or "").lower()
    family_map = {"hat": "headwear", "hair": "hair", "face": "face",
                  "neck": "neck", "shoulder": "shoulder", "front": "front",
                  "back": "back", "waist": "waist", "emote": "emotes",
                   "shirt": "clothing", "pants": "clothing",
                   "jacket": "clothing", "3d_clothing": "clothing",
                   "bundle": "clothing", "gear": "back",
                   "background": "backgrounds",
                   "avatar background": "backgrounds"}
    if base["family"] == "unknown" and vfam:
        base["family"] = family_map.get(vfam, "unknown")
        base["family_source"] = SOURCE_VISUAL

    motion = []
    thumbnail_blocked = (base["family"] == "emotes"
                         and image_kind in ("thumbnail", "attachment"))
    if base["family"] == "emotes":
        if thumbnail_blocked:
            base["unknowns"].append(
                "movement cannot be inferred from a static image; use the "
                "creator's preview/metadata")
        elif image_kind == "preview" and v.get("motion"):
            motion = [_attr(m, SOURCE_VISUAL) for m in v.get("motion") or []]
    base["motion"] = motion
    base["motion_required"] = bool(motion)
    base["thumbnail_blocked"] = thumbnail_blocked

    colors = [c.get("name") if isinstance(c, dict) else str(c)
              for c in (v.get("visual_colors") or [])]
    if colors and not base["colors"]:
        base["colors"] = [_attr(c, SOURCE_VISUAL) for c in colors if c]
    feats = v.get("distinctive_features") or []
    if feats and not base["details"]:
        base["details"] = [_attr(f, SOURCE_VISUAL) for f in feats]
    return base


def merge(user_text, api_family=None, vision=None, image_kind="attachment"):
    """User text overrides API/visual inferences; API overrides vision."""
    u = from_image(vision or {}, user_text, image_kind=image_kind)
    if api_family and u["family"] == "unknown":
        u["family"] = api_family
        u["family_source"] = SOURCE_API
    if u["family"] in STATIC_FAMILIES:
        # Static accessories never carry motion requirements.
        u["motion"] = []
        u["motion_required"] = False
    return u


def to_prompt_block(u):
    def fmt(items):
        return ", ".join(f"{i['value']}({i['source']})" for i in items) or "none"
    motion = fmt(u["motion"]) if motion_allowed(u["family"]) else "none (static)"
    return (
        "PRODUCT UNDERSTANDING (authoritative)\n"
        f"- family: {u['family']} ({u['family_source']})\n"
        f"- colors: {fmt(u['colors'])}\n"
        f"- details: {fmt(u['details'])}\n"
        f"- motion: {motion}\n"
        f"- unknowns: {', '.join(u['unknowns']) or 'none'}\n"
    )


def validate_title(concept, title, family=None, understanding=None):
    """Platform guard + identity lock; no motion checks for static families."""
    from astra import contains_banned_platform, identity_lock_ok
    fam = (understanding or {}).get("family") or family
    if contains_banned_platform(title):
        return False, "platform word"
    if motion_allowed(fam) and not identity_lock_ok(concept, title):
        return False, "motion swapped"
    if fam in STATIC_FAMILIES and fam not in SCENE_FAMILIES:
        toks = set(_tokens(title))
        if toks & MOTION_TOKENS:
            return False, "static accessory must not claim motion"
    return True, ""
