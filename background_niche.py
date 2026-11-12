"""Conservative scene-phrase filter for background opportunity discovery.

This gate applies ONLY to background niche recommendations, not to user-provided
concepts, image analysis, title generation, or other asset families.

A background scene is not established by a broad color/pattern ("white",
"plaid") or category label ("background"). Demand and growth still need
independent evidence before any recommendation.
"""
import re

SCENE_ANCHORS = frozenset({
    "alley", "arcade", "arena", "aurora", "beach", "bedroom", "bridge",
    "cabin", "cafe", "castle", "cave", "city", "classroom", "clouds",
    "coast", "courtyard", "desert", "diner", "dock", "dungeon", "factory",
    "field", "forest", "galaxy", "garden", "harbor", "heaven", "hill",
    "hills", "horizon", "house", "island", "jungle", "lake", "library",
    "market", "moon", "mountain", "mountains", "nebula", "ocean", "office",
    "palace", "park", "planet", "portal", "rainforest", "river", "road",
    "rooftop", "room", "ruins", "school", "shrine", "sky", "space",
    "station", "street", "sunset", "temple", "theater", "tower", "tunnel",
    "valley", "village", "void", "waterfall", "woodland",
})
CATEGORY_WORDS = frozenset({
    "avatar", "avatars", "background", "backgrounds", "backdrop",
    "backdrops", "ugc", "roblox", "image", "picture", "scene",
})
NOISE_WORDS = frozenset({
    "plaid", "white", "black", "plain", "simple", "basic", "generic",
    "new", "best", "latest", "popular", "cheap", "free", "classic",
})


def scene_phrase(keyword):
    """True for a descriptive, anchored two-to-four-token scene niche.

    No claim is made that this catches every possible visual scene: unfamiliar
    themes are skipped rather than promoted as evidence-backed recommendations.
    """
    words = re.findall(r"[a-z]+", (keyword or "").lower())
    if not 2 <= len(words) <= 4:
        return False
    if any(w in CATEGORY_WORDS for w in words):
        return False
    if len(set(words)) < 2:
        return False
    if not any(w in SCENE_ANCHORS for w in words):
        return False
    if all(w in SCENE_ANCHORS or w in NOISE_WORDS for w in words):
        # "white city" is useful, whereas "white" is not; if a scene anchor
        # and a modifier coexist, keep the phrase.
        return any(w in SCENE_ANCHORS for w in words) and any(
            w not in SCENE_ANCHORS for w in words
        ) or len(set(words) & SCENE_ANCHORS) >= 2
    return True
