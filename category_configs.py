"""
category_configs.py — Category-aware configuration shared across the whole stack.

Consumed by:
  - creative_expand.py
  - creative_pivot.py
  - commands_intel.py  (!autopsy)
  - commands_ai.py     (!brainstorm)
  - gemini_brain.py    (synthesis prompt)

Each family defines:
  asset_type_ids     — Roblox asset type IDs (universal constants)
  type_words         — valid item-type tokens (used by verify_titles)
  shape              — "movement" | "aesthetic" | "theme" | "creature" | "style"
  buckets            — creative-expand buckets {name, vibe}
  shape_rule         — instruction string for the AI
  title_archetypes   — example title structures
  filler_block       — words to exclude from concept generation
"""

# Roblox asset type IDs (universal):
#  8=Hat  41=HairAccessory  42=FaceAccessory
# 43=NeckAccessory  44=ShoulderAccessory  45=FrontAccessory
# 46=BackAccessory  47=WaistAccessory
# 61=EmoteAnimation
# 64=TShirtAccessory  65=ShirtAccessory  66=PantsAccessory
# 67=JacketAccessory  68=SweaterAccessory  69=ShortsAccessory
# 70=LeftShoeAccessory  71=RightShoeAccessory  72=DressSkirtAccessory
# 19=Gear

CATEGORY_FAMILIES = {
    "emote": {
        "label": "Emote / Dance",
        "asset_type_ids": [61],
        "aliases": ["emote", "dance", "animation", "anim"],
        "type_words": ["emote", "dance", "animation"],
        "shape": "movement",
        "shape_rule": (
            "Every concept MUST describe a movement or action. "
            "Verb-shaped or body-part + verb (e.g. 'hip sway', 'arm pump', 'bounce'). "
            "REJECT vibe-only tags, person types, and generic adjectives."
        ),
        "buckets": [
            {"name": "RELAXED",   "vibe": "chill, mellow, soft, lazy, smooth"},
            {"name": "ENERGETIC", "vibe": "bouncy, snappy, hyped, poppy, glitchy"},
            {"name": "CHARACTER", "vibe": "swaggy, confident, sassy, smooth, cool"},
        ],
        "title_archetypes": [
            "MOVE + TYPE:              \"Hip Sway Dance\"",
            "MOVE + MOVE + TYPE:       \"Hip Sway Arm Pump Emote\"",
            "STYLE + MOVE + TYPE:      \"TikTok Hip Sway Dance\"",
            "TREND + MOVE + TYPE:      \"Viral Hip Sway Emote\"",
            "MOVE + MOVE + MOVE + TYPE:\"Hip Sway Arm Pump Dance\"",
            "EMOTION + MOVE + TYPE:    \"Chill Hip Sway Dance\"",
        ],
        "filler_block": {
            "emote","dance","animation","anim","move","moves","the","and","for",
            "with","your","you","a","an","of","in","on","to","my","is","it","as",
            "at","by","roblox","tiktok","viral","trend","trendy","new","best",
        },
    },

    "hair": {
        "label": "Hair",
        "asset_type_ids": [41],
        "aliases": ["hair"],
        "type_words": ["hair"],
        "shape": "aesthetic",
        "shape_rule": (
            "Every concept MUST be a descriptive aesthetic word OR hairstyle word. "
            "Think adjective + style (e.g. 'pastel wavy', 'cyber punk', 'celestial braids'). "
            "REJECT pure color words, brand names, and character names."
        ),
        "buckets": [
            {"name": "SOFT",    "vibe": "pastel, kawaii, cozy, dreamy, gentle"},
            {"name": "EDGY",    "vibe": "grunge, cyber, gothic, punk, alt"},
            {"name": "FANTASY", "vibe": "celestial, royal, witchy, mythical, magical"},
        ],
        "title_archetypes": [
            "AESTHETIC + STYLE + HAIR: \"Pastel Wavy Hair\"",
            "THEME + STYLE + HAIR:     \"Cyber Punk Braids Hair\"",
            "STYLE + LENGTH + HAIR:    \"Fluffy Long Hair\"",
        ],
        "filler_block": {
            "hair","the","and","for","with","your","you","a","an","of","in","on",
            "to","my","is","it","as","at","by","roblox","tiktok","viral","new","best",
        },
    },

    "headwear": {
        "label": "Hat / Cap / Crown",
        "asset_type_ids": [8],
        "aliases": ["hat", "cap", "beanie", "crown", "beret", "snapback", "bonnet",
                    "headwear", "visor", "balaclava"],
        "type_words": ["hat", "cap", "beanie", "crown", "beret", "snapback",
                       "bonnet", "visor", "balaclava"],
        "shape": "theme",
        "shape_rule": (
            "Every concept MUST be a theme or aesthetic word that could precede a hat. "
            "Think adjective + theme (e.g. 'royal crown', 'cyber punk', 'cottagecore knit'). "
            "REJECT character names, IP references, and generic adjectives."
        ),
        "buckets": [
            {"name": "COZY",    "vibe": "cottagecore, soft, warm, pastel, knit"},
            {"name": "EDGY",    "vibe": "cyber, gothic, grunge, punk, tactical"},
            {"name": "FANTASY", "vibe": "royal, celestial, witchy, magical, ancient"},
            {"name": "STREET",  "vibe": "y2k, retro, urban, hiphop, skate"},
        ],
        "title_archetypes": [
            "THEME + TYPE:         \"Cyber Punk Hat\"",
            "AESTHETIC + TYPE:     \"Pastel Cozy Beanie\"",
            "THEME + THEME + TYPE: \"Royal Celestial Crown\"",
        ],
        "filler_block": {
            "hat","cap","beanie","crown","beret","the","and","for","with","your",
            "you","a","an","of","in","on","to","my","is","it","as","at","by",
            "roblox","tiktok","viral","new","best",
        },
    },

    "face": {
        "label": "Face Accessory",
        "asset_type_ids": [42, 76, 77],
        "aliases": ["face", "mask", "glasses", "eyebrow", "eyelash"],
        "type_words": ["face", "mask", "glasses", "eyebrow", "eyelash"],
        "shape": "theme",
        "shape_rule": (
            "Every concept MUST be a theme, aesthetic, or mood word for a face item. "
            "Think adjective + theme (e.g. 'kawaii blush', 'cyber visor', 'glowing eyes'). "
            "REJECT character names, IP references."
        ),
        "buckets": [
            {"name": "CUTE",     "vibe": "kawaii, soft, pastel, adorable, dreamy"},
            {"name": "EDGY",     "vibe": "gothic, cyber, dark, mysterious, punk"},
            {"name": "MYSTICAL", "vibe": "glowing, celestial, magical, ethereal, radiant"},
            {"name": "MEME",     "vibe": "funny, troll, meme, chaotic, silly"},
        ],
        "title_archetypes": [
            "THEME + TYPE:        \"Cyber Visor Mask\"",
            "AESTHETIC + TYPE:    \"Kawaii Blush Face\"",
            "THEME + TYPE + TYPE: \"Celestial Glow Mask\"",
        ],
        "filler_block": {
            "face","mask","glasses","the","and","for","with","your","you","a","an",
            "of","in","on","to","my","is","it","as","at","by","roblox","tiktok",
            "viral","new","best",
        },
    },

    "accessory": {
        "label": "Accessory (Neck/Shoulder/Back/Waist)",
        "asset_type_ids": [43, 44, 45, 46, 47],
        "aliases": ["neck", "shoulder", "front", "back", "waist", "chain",
                    "necklace", "wing", "wings", "tail", "backpack", "scarf",
                    "bag", "belt"],
        "type_words": ["chain", "necklace", "wing", "wings", "tail",
                       "backpack", "scarf", "bag", "belt", "sword"],
        "shape": "theme",
        "shape_rule": (
            "Every concept MUST be a theme, aesthetic, or texture word for an accessory. "
            "Think adjective + theme (e.g. 'celestial wings', 'chunky chain', 'y2k bag'). "
            "REJECT character names, IP references."
        ),
        "buckets": [
            {"name": "MINIMAL", "vibe": "simple, clean, sleek, subtle, elegant"},
            {"name": "BOLD",    "vibe": "chunky, oversized, statement, loud, vibrant"},
            {"name": "FANTASY", "vibe": "celestial, magical, mythical, ethereal, glowing"},
        ],
        "title_archetypes": [
            "THEME + TYPE:         \"Celestial Wings\"",
            "AESTHETIC + TYPE:     \"Chunky Chain\"",
            "THEME + AESTHETIC:    \"Y2K Butterfly Bag\"",
        ],
        "filler_block": {
            "chain","wing","wings","tail","backpack","scarf","bag","belt","the",
            "and","for","with","your","you","a","an","of","in","on","to","my",
            "is","it","as","at","by","roblox","tiktok","viral","new","best",
        },
    },

    "clothing": {
        "label": "Clothing (Shirt/Pants/Jacket/Shoes/Dress)",
        "asset_type_ids": [64, 65, 66, 67, 68, 69, 70, 71, 72],
        "aliases": ["shirt", "pants", "jacket", "shoes", "shorts", "sweater",
                    "dress", "skirt", "t-shirt", "tshirt", "clothing"],
        "type_words": ["shirt", "pants", "jacket", "shoes", "shorts", "sweater",
                       "dress", "skirt", "hoodie", "tee"],
        "shape": "style",
        "shape_rule": (
            "Every concept MUST be a fashion style, aesthetic, or theme word. "
            "Think adjective + style (e.g. 'y2k streetwear', 'gothic lolita', 'cottagecore'). "
            "REJECT character names, IP references, brand names."
        ),
        "buckets": [
            {"name": "STREETWEAR", "vibe": "urban, hiphop, oversized, graffiti, skate"},
            {"name": "FORMAL",     "vibe": "elegant, classy, luxe, royal, tailored"},
            {"name": "SPORTY",     "vibe": "athletic, gym, jock, runner, active"},
            {"name": "RETRO",      "vibe": "vintage, y2k, 80s, 90s, nostalgic"},
        ],
        "title_archetypes": [
            "STYLE + TYPE:          \"Y2K Streetwear Hoodie\"",
            "THEME + STYLE:         \"Gothic Lolita Dress\"",
            "AESTHETIC + TYPE:      \"Cottagecore Knit Sweater\"",
        ],
        "filler_block": {
            "shirt","pants","jacket","shoes","dress","skirt","the","and","for",
            "with","your","you","a","an","of","in","on","to","my","is","it",
            "as","at","by","roblox","tiktok","viral","new","best",
        },
    },

    "bundle": {
        "label": "Bundle / Character",
        "asset_type_ids": [],
        "aliases": ["bundle", "character", "avatar"],
        "type_words": ["bundle", "character"],
        "shape": "creature",
        "shape_rule": (
            "Every concept MUST be a creature, character archetype, or elemental theme. "
            "Think creature/element + adjective (e.g. 'shadow dragon', 'ice wolf', 'void knight'). "
            "REJECT brand names, real celebrities, existing Roblox items."
        ),
        "buckets": [
            {"name": "CREATURE",  "vibe": "dragon, wolf, fox, cat, kitsune, phoenix"},
            {"name": "CHARACTER", "vibe": "hero, villain, knight, mage, ninja, pirate"},
            {"name": "ELEMENTAL", "vibe": "fire, ice, storm, shadow, celestial, nature"},
        ],
        "title_archetypes": [
            "ELEMENT + CREATURE: \"Shadow Dragon\"",
            "THEME + CHARACTER:  \"Cyber Ninja\"",
            "ELEMENT + THEME:    \"Ice Paladin\"",
        ],
        "filler_block": {
            "bundle","character","avatar","the","and","for","with","your","you",
            "a","an","of","in","on","to","my","is","it","as","at","by","roblox",
            "tiktok","viral","new","best",
        },
    },

    "gear": {
        "label": "Gear",
        "asset_type_ids": [19],
        "aliases": ["gear", "tool", "weapon"],
        "type_words": ["sword", "staff", "bow", "shield", "wand", "axe"],
        "shape": "theme",
        "shape_rule": (
            "Every concept MUST be a theme or element word for a tool. "
            "Think theme + element (e.g. 'plasma sword', 'runic staff', 'crystal bow'). "
            "REJECT brand names, IP references."
        ),
        "buckets": [
            {"name": "FANTASY", "vibe": "enchanted, legendary, mythic, runic, ancient"},
            {"name": "SCIFI",   "vibe": "neon, cyber, plasma, quantum, hologram"},
            {"name": "SPORT",   "vibe": "training, combat, tactical, pro, championship"},
        ],
        "title_archetypes": [
            "THEME + TYPE:        \"Plasma Sword\"",
            "ELEMENT + TYPE:      \"Runic Staff\"",
            "THEME + THEME + TYPE:\"Ancient Crystal Bow\"",
        ],
        "filler_block": {
            "gear","tool","the","and","for","with","your","you","a","an","of","in",
            "on","to","my","is","it","as","at","by","roblox","tiktok","viral","new","best",
        },
    },
}

DEFAULT_FAMILY = "emote"


def _resolve_family(item_type_or_family):
    """Map a raw item_type string to a family key."""
    if not item_type_or_family:
        return DEFAULT_FAMILY
    key = str(item_type_or_family).lower().strip()
    if key in CATEGORY_FAMILIES:
        return key
    for fam_key, cfg in CATEGORY_FAMILIES.items():
        if key in cfg.get("aliases", []):
            return fam_key
    return DEFAULT_FAMILY


def detect_family_from_intent(intent):
    if not intent:
        return DEFAULT_FAMILY
    return _resolve_family(intent.get("item_type") or DEFAULT_FAMILY)


def detect_family_from_asset_type(asset_type_id):
    try:
        atid = int(asset_type_id)
    except Exception:
        return DEFAULT_FAMILY
    for fam_key, cfg in CATEGORY_FAMILIES.items():
        if atid in cfg.get("asset_type_ids", []):
            return fam_key
    return DEFAULT_FAMILY


def get_category_config(item_type_or_family):
    """Return the full config dict for a family (or an alias)."""
    return CATEGORY_FAMILIES[_resolve_family(item_type_or_family)]


def get_type_words_for(item_type_or_family):
    return set(get_category_config(item_type_or_family).get("type_words", []))


def get_filler_block(item_type_or_family):
    return set(get_category_config(item_type_or_family).get("filler_block", set()))


def get_all_type_words():
    """Union of every category's type words — used by verify_titles."""
    out = set()
    for cfg in CATEGORY_FAMILIES.values():
        out.update(cfg.get("type_words", []))
    return out


def get_category_label(item_type_or_family):
    return get_category_config(item_type_or_family).get("label", "UGC")
