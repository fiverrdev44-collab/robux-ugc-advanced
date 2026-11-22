"""Conservative creative name lanes for Roblox Avatar Backgrounds (AssetType 92).

These are editorial ideas, NOT CTR, ranking, uniqueness, trademark clearance,
copyright analysis, or proof an artist owns the image. No external services,
data writes or model requests. Do not reuse for emote movement naming.
"""
import re

# Named game/world references provided by a creator are *not* a permission
# signal. A few familiar aliases are covered, not every protected property.
_IP_PHRASES = (
    "bioshock", "rapture", "gmod", "garry's mod", "garrys mod",
    "gm flatgrass", "gm_flatgrass", "flatgrass", "flattywood",
    "oggy", "five nights at freddy", "fnaf", "fazbear", "freddy",
    "team fortress", "tf2", "dustbowl",
)
_OFFICIAL_CLAIMS = ("official", "licensed", "authorized", "certified",
                    "air force one")
_NOISE = {"background", "backgrounds", "avatar", "roblox", "ugc", "scene",
          "picture", "image", "the", "a", "an", "of", "and", "in", "on",
          "over", "under", "into", "through", "beyond", "across", "by",
          "for", "with", "from", "at", "to"}
_SCENE_NOUNS = {
    "room", "office", "house", "garden", "field", "fields", "meadow",
    "grassland", "city", "cityscape", "skyline", "shrine", "forest",
    "beach", "ocean", "sea", "sky", "horizon", "portal", "castle",
    "hall", "lobby", "studio", "jet", "plane", "aircraft", "runway",
    "tarmac", "street", "streetlight", "alley", "dungeon", "station",
    "mountain", "mountains", "lake", "bridge", "courtyard", "village",
    "temple", "cabin", "window", "lookout", "observatory", "sandbox",
    "world", "ruins", "desert", "arcade", "tower", "hangar",
}
# Only poetic descriptors that do NOT assert an additional character,
# building, animation, event, licensed identity, rarity or product attribute.
_STYLISTIC = {
    "quiet", "serene", "dreamy", "moody", "mysterious", "mystic",
    "cinematic", "atmospheric", "ethereal", "hidden", "forgotten",
    "lost", "endless", "open", "wide", "vast", "distant", "gentle",
    "still", "tranquil", "soft", "secret", "silent", "solitary",
    "beyond", "deep", "sunlit", "sunny", "afterglow", "azure",
    "overlook", "lookout", "vista", "vistas", "escape", "sanctuary",
    "paradise", "hideaway", "horizon", "glimpse", "little", "grand",
    "calm", "tranquility", "retro", "classic", "golden", "lush",
}
# A synonym may be used only when at least one of its source triggers is
# genuinely in the creator's details / visual description.
_CONTEXTUAL = {
    "grassland": {"grass", "grassy", "flatgrass", "field", "fields", "meadow"},
    "meadow": {"grass", "grassy", "grassland", "field", "fields"},
    "field": {"grass", "grassy", "fields", "grassland", "meadow"},
    "fields": {"grass", "grassy", "field", "grassland", "meadow"},
    "horizon": {"skyline", "horizon", "hills", "hill", "field", "fields",
                "grass", "grassy", "landscape"},
    "skyline": {"city", "cityscape", "skyscrapers", "buildings", "skyline"},
    "city": {"cityscape", "city", "skyline", "skyscrapers"},
    "sunken": {"underwater", "undersea", "submerged"},
    "underwater": {"underwater", "undersea", "submerged"},
    "skies": {"sky"},
    "shadows": {"dark", "shadow", "shadows"},
    "observatory": {"observation", "observation room", "lookout"},
    "lookout": {"window", "overlook", "panoramic", "observation"},
    "vista": {"window", "panoramic", "view", "overlooking", "skyline"},
    "glass": {"glass", "window", "panoramic"},
    "aircraft": {"aircraft", "jet", "plane", "airplane"},
    "jet": {"jet", "aircraft", "plane", "airplane"},
    "sandbox": {"sandbox", "gmod", "garry", "flatgrass"},
    "sunlit": {"sunny", "sunlight", "sun", "daylight"},
    "azure": {"blue", "sky", "ocean", "underwater"},
    "deep": {"underwater", "ocean", "sea", "deep"},
    "endless": {"open", "vast", "flat", "grass", "grassy", "field",
                "fields", "horizon"},
    "open": {"open", "field", "grass", "grassy", "sky"},
    "beyond": {"window", "overlooking", "view"},
    "vip": {"vip", "presidential", "limousine", "red carpet"},
    "arrival": {"arrival", "stairs", "staircase", "red carpet", "doorway"},
}

def words(value):
    return set(re.findall(r"[a-z0-9]+", str(value or "").casefold()))

def _phrase_present(phrase, value):
    escaped = re.escape(phrase).replace(r"\ ", r"\s+")
    return bool(re.search(r"(?<![a-z0-9])" + escaped + r"(?![a-z0-9])",
                          str(value or "").casefold()))

def brand_sensitive_title(title, creator_notes=""):
    """A conservative known-IP/affiliation name warning, not a legal opinion."""
    text = str(title or "").casefold().replace("_", " ")
    context = str(creator_notes or "").casefold().replace("_", " ")
    # Common standalone 'rapture' is only brand-sensitive in BioShock context.
    for phrase in _IP_PHRASES + _OFFICIAL_CLAIMS:
        if phrase == "rapture" and not (
                "bioshock" in context or "underwater city" in context):
            continue
        if _phrase_present(phrase.replace("_", " "), text):
            return phrase
    return None

def allowed_poetic_tokens(source):
    """Bounded imaginative language with scene-dependent synonyms."""
    w = words(source)
    extras = set(_STYLISTIC)
    for synonym, triggers in _CONTEXTUAL.items():
        if any(trigger in w or _phrase_present(trigger, source) for trigger in triggers):
            extras.add(synonym)
    # Subjective atmosphere can be suggested, but not arbitrary time-of-day.
    return extras

def creative_title_issues(title, scene_source, creator_notes=""):
    """Validate a model-proposed *background* title without being word-for-word.

    Preserve literal scene identity, allow safe metaphor/connective words and
    supported synonyms. Reject new props, people, settings and known IP names.
    No judgement about a user's rights to their artwork is made here.
    """
    if not isinstance(title, str) or not title.lower().endswith(" background"):
        return "not_background"
    parts = re.findall(r"[a-z0-9]+", title.lower())
    if len(parts) < 2 or len(parts) > 8 or len(title) > 65:
        return "length"
    if brand_sensitive_title(title, creator_notes):
        return "unlicensed_identity_or_affiliation"
    source = words(scene_source)
    supported = source | allowed_poetic_tokens(scene_source) | _NOISE
    unsupported = set(parts) - supported
    if unsupported:
        return "unsupported_scene_noun_or_claim"
    scene_nouns = set(parts) & _SCENE_NOUNS
    if not scene_nouns:
        return "no_recognizable_scene"
    # At least one concrete detail must be literal or a scene-conditioned
    # synonym, preventing purely atmospheric names with no useful subject.
    literal = (set(parts) - _STYLISTIC - _NOISE) & source
    conditional_noun = any(
        noun in _CONTEXTUAL and noun in allowed_poetic_tokens(scene_source)
        for noun in scene_nouns
    )
    if not literal and not conditional_noun:
        return "missing_grounded_subject"
    return None

def creative_lane_candidates(vision, notes=""):
    """A few original, scene-grounded names, no game/franchise branding.

    This complements, rather than replaces, creative model suggestions.
    Produces no invented entities or effects, and does not imply real-world CTR.
    """
    from background_intelligence import observations
    obs = observations(vision)
    source = " ".join([
        str(notes or "")[:300], obs["visual_summary"],
        obs["search_description"], *obs["distinctive_features"][:4],
    ])
    w = words(source)
    candidates = []

    def add(candidate):
        if (candidate not in candidates and
                creative_title_issues(candidate, source, notes) is None):
            candidates.append(candidate)

    if ("grass" in w or "grassy" in w or "grassland" in w or "field" in w):
        add("Open Grassland Background")
        if "green" in w or "hills" in w or "hill" in w:
            add("Endless Green Fields Background")
        if "hills" in w or "hill" in w:
            add("Grassland To The Horizon Background")
    if ("underwater" in w or "undersea" in w) and (
        "city" in w or "cityscape" in w or "skyline" in w):
        if "blue" in w:
            add("Deep Blue Underwater City Background")
        add("Sunken Skyline Background")
        if "window" in w:
            add("Underwater City Lookout Background")
            add("Beyond The Glass Underwater City Background")
    if {"sky", "blue"} <= w and w & {"grassy", "grass", "grassland", "field"}:
        add("Grassland Under Blue Skies Background")
    if "house" in w:
        if {"sunny", "cartoon"} <= w:
            add("Sunlit Cartoon House Background")
        if "purple" in w and "roof" in w:
            add("The Purple Roof House Background")
        if "sunny" in w:
            add("Sunny Little House Background")
        if "awning" in w or "awnings" in w:
            add("House With Striped Awnings Background")
    if ("aircraft" in w or "jet" in w or "plane" in w):
        if {"presidential", "arrival"} <= w:
            add("Presidential Jet Arrival Background")
        if {"red", "carpet", "arrival"} <= w:
            add("Red Carpet Jet Arrival Background")
        add("Ceremonial Aircraft Arrival Background")
        if "runway" in w:
            add("Jet On The Runway Background")
    if {"security", "office"}.issubset(w):
        add("Silent Security Office Background")
        add("Security Office Shadows Background")
    return candidates[:9]
