"""
category_configs.py — Category-aware configuration shared across the stack.

NEW: concept_vocab per family — hard gate for creative_pivot candidates.
     Only words in the family's concept_vocab (plus its aliases) can be pivots.
"""

# Universal abstract English — should NEVER be a UGC concept
ABSTRACT_ENGLISH_BLOCK = {
    # Common verbs
    "check", "place", "places", "stay", "over", "make", "made", "take", "took",
    "give", "gave", "get", "got", "went", "gone", "come", "came", "say", "said",
    "see", "saw", "know", "knew", "think", "thought", "find", "found", "want",
    "need", "like", "love", "hate", "feel", "felt", "look", "looked", "seem",
    "sound", "call", "help", "play", "run", "walk", "turn", "start", "stop",
    "keep", "let", "put", "set", "tell", "ask", "try", "show", "leave",
    # Adverbs
    "still", "even", "just", "only", "also", "very", "much", "many", "most",
    "some", "any", "all", "every", "each", "both", "few", "more", "less",
    "other", "another", "such", "same", "again", "once", "always", "never",
    "often", "sometimes", "usually", "already", "yet", "soon", "later",
    "now", "then", "today", "tomorrow", "yesterday",
    # Adjectives (generic)
    "new", "old", "good", "bad", "big", "small", "long", "short", "high",
    "low", "right", "wrong", "true", "false", "full", "empty", "open",
    "closed", "free", "busy", "ready", "sure", "clear", "easy", "hard",
    "fast", "slow", "early", "late", "young", "hot", "cold", "warm", "dry",
    "wet", "safe", "sick", "well", "alive", "dead", "tired", "afraid",
    "alone", "together",
    # Generic nouns
    "world", "life", "way", "thing", "things", "man", "men", "woman", "women",
    "child", "children", "kid", "kids", "boy", "girl", "person", "people",
    "friend", "friends", "family", "home", "house", "work", "job", "school",
    "city", "country", "room", "door", "food", "water", "name", "word",
    "words", "number", "problem", "fact", "idea", "point", "case", "hand",
    "body", "foot", "kind", "sort", "type", "part", "end", "top", "bottom",
    "line", "area", "form", "level", "course", "moment", "reason", "result",
    "example", "group", "company", "party", "team", "game", "story", "book",
    "paper", "letter", "note", "list", "plan", "road", "street", "town",
    "state", "time", "money", "hour", "minute", "second", "day", "week",
    "month", "year", "night", "morning", "icecream",
}

# Roblox asset type IDs (universal):
#  8=Hat  41=HairAccessory  42=FaceAccessory
# 43=NeckAccessory  44=ShoulderAccessory  45=FrontAccessory
# 46=BackAccessory  47=WaistAccessory
# 61=EmoteAnimation
# 64-72 = Clothing family
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
            "REJECT vibe-only tags, person types, and generic adjectives. "
            "REJECT abstract English words like 'places', 'check', 'over', 'stay'."
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
        # Only these words can be pivots for emotes
        "concept_vocab": {
            # Movement verbs
            "sway","step","bounce","hop","jump","slide","spin","twirl","wave",
            "glide","strut","walk","run","pose","lean","swing","shake","roll",
            "pop","lock","drop","flip","kick","clap","snap","tap","shuffle",
            "bop","stomp","wiggle","shimmy","jiggle","bob","nod","twerk","grind",
            "groove","flow","drift","float","slither","crawl","march","prance",
            "skip","trot","leap","bound","dive","dash","sprint","dance",
            # Rhythm/mood words
            "chill","smooth","mellow","lazy","relaxed","hype","vibe","energy",
            "rhythm","beat","aura","snappy","bouncy","poppy","sassy","boss",
            "glitch","wild","fast","slow","soft","loose","tight","quick",
            "slick","fresh","crazy","epic","silly","goofy","funny","troll",
            "happy","sad","angry","shy","confident","humble","cute","cozy",
            "moody","fancy","flashy","subtle",
            # Style / music / trend
            "kpop","k-pop","hiphop","hip-hop","rap","pop","rock","edm","techno",
            "house","jazz","salsa","ballet","vogue","krump","breakdance",
            # Viral / meme
            "sigma","rizz","skibidi","gyatt","mewing","sus","ratio","goat",
            "slay","bussin","yeet","bruh","fanum","cap","aura","drip","flex",
            # Iconic moves
            "floss","griddy","dab","moonwalk","renegade","dougie","stanky",
            "robot","gangnam","shmoney",
            # Colors / elements (as modifiers)
            "neon","cyber","night","day","sun","moon","star","fire","ice",
            "party","club","disco","rave","festival",
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
        "concept_vocab": {
            # Hairstyles
            "wavy","curly","straight","braids","braid","bun","ponytail","pigtails",
            "bob","lob","pixie","bangs","fringe","layers","shag","mullet",
            "mohawk","afro","dreads","dreadlocks","twists","cornrows","spacebuns",
            "wolf","hime","scene","emo","fluffy","voluminous","messy","sleek",
            "long","short","medium","halfup",
            # Aesthetics
            "pastel","kawaii","cozy","dreamy","gentle","grunge","cyber","gothic",
            "punk","alt","celestial","royal","witchy","mythical","magical",
            "y2k","retro","vintage","elegant","cute","aesthetic","soft",
            "anime","manga","chibi","lolita","goth","fairy","angelic","demonic",
            "ethereal","glowing","sparkling","shimmer","holographic","iridescent",
            "pearl","crystal","diamond","silk","velvet","satin",
            # Colors as modifiers
            "pastel","neon","blonde","brunette","pink","purple","blue","green",
            "silver","golden","rose","lavender","mint","peach",
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
        "concept_vocab": {
            "cottagecore","cozy","warm","pastel","knit","wool","fluffy","soft",
            "cyber","gothic","grunge","punk","tactical","military","combat",
            "royal","celestial","witchy","magical","ancient","mythical","regal",
            "y2k","retro","urban","hiphop","skate","streetwear","vintage",
            "kawaii","anime","manga","fairy","angelic","demonic","glowing",
            "neon","holographic","iridescent","sparkle","crystal","diamond",
            "sporty","athletic","runner","jock","preppy","coquette","emo",
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
        "concept_vocab": {
            "kawaii","soft","pastel","adorable","dreamy","cute","coquette","sweet",
            "gothic","cyber","dark","mysterious","punk","grunge","emo","edgy",
            "glowing","celestial","magical","ethereal","radiant","mystical",
            "sparkling","shimmer","neon","holographic","iridescent",
            "funny","troll","meme","chaotic","silly","goofy","angry","shy",
            "blush","tear","sweat","star","heart","spade","crown",
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
        "concept_vocab": {
            "simple","clean","sleek","subtle","elegant","minimal","delicate",
            "chunky","oversized","statement","loud","vibrant","bold","heavy",
            "celestial","magical","mythical","ethereal","glowing","sparkle",
            "fairy","angelic","demonic","dragon","phoenix","serpent","skull",
            "crystal","diamond","pearl","holographic","iridescent","neon",
            "y2k","retro","vintage","grunge","cyber","gothic","punk",
            "kawaii","cute","coquette","pastel","soft","cozy",
        },
    },

    "clothing": {
        "label": "Clothing",
        "asset_type_ids": [64, 65, 66, 67, 68, 69, 70, 71, 72],
        "aliases": ["shirt", "pants", "jacket", "shoes", "shorts", "sweater",
                    "dress", "skirt", "t-shirt", "tshirt", "clothing"],
        "type_words": ["shirt", "pants", "jacket", "shoes", "shorts", "sweater",
                       "dress", "skirt", "hoodie", "tee"],
        "shape": "style",
        "shape_rule": (
            "Every concept MUST be a fashion style, aesthetic, or theme word. "
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
        "concept_vocab": {
            "streetwear","urban","hiphop","oversized","graffiti","skate","chunky",
            "elegant","classy","luxe","royal","tailored","formal","chic",
            "athletic","gym","jock","runner","active","sporty","track",
            "vintage","y2k","80s","90s","retro","nostalgic","throwback",
            "cottagecore","cozy","knit","fluffy","soft","pastel","kawaii",
            "grunge","cyber","gothic","punk","emo","alt","emo",
            "preppy","coquette","anime","manga","kpop",
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
        "concept_vocab": {
            "dragon","wolf","fox","cat","kitsune","phoenix","griffin","serpent",
            "demon","angel","fairy","elf","orc","goblin","troll","giant",
            "hero","villain","knight","mage","wizard","ninja","pirate","samurai",
            "warrior","archer","assassin","rogue","paladin","cleric","ranger",
            "fire","ice","storm","shadow","celestial","nature","void","arcane",
            "cyber","neon","plasma","quantum","hologram","crystal","void",
            "ghost","spirit","phantom","wraith","skeleton","zombie","vampire",
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
        "concept_vocab": {
            "enchanted","legendary","mythic","runic","ancient","sacred","cursed",
            "neon","cyber","plasma","quantum","hologram","photon","laser","ion",
            "training","combat","tactical","pro","championship","battle","war",
            "crystal","diamond","obsidian","meteor","starlight","moonlight",
            "fire","ice","storm","shadow","void","arcane","divine","demonic",
        },
    },
}

DEFAULT_FAMILY = "emote"


def _resolve_family(item_type_or_family):
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
    return CATEGORY_FAMILIES[_resolve_family(item_type_or_family)]


def get_type_words_for(item_type_or_family):
    return set(get_category_config(item_type_or_family).get("type_words", []))


def get_filler_block(item_type_or_family):
    return set(get_category_config(item_type_or_family).get("filler_block", set()))


def get_concept_vocab(item_type_or_family):
    return set(get_category_config(item_type_or_family).get("concept_vocab", set()))


def get_all_type_words():
    out = set()
    for cfg in CATEGORY_FAMILIES.values():
        out.update(cfg.get("type_words", []))
    return out


def get_category_label(item_type_or_family):
    return get_category_config(item_type_or_family).get("label", "UGC")
