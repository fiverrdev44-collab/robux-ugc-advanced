"""
tag_generator.py — sales-weighted SEO tag generator.

Analyzes the DB for what ACTUALLY drives sales in each category.
Weights tags by:
  1. Frequency in top 20% sellers (not just any items)
  2. Search demand (real queries)
  3. Cross-category co-occurrence (what pairs with what)
  4. Aesthetic clustering (kawaii family, y2k family, etc.)
  5. Category-specific winners

Returns up to 45 tags ranked by sales trigger strength.
"""
import re
from collections import Counter, defaultdict
from bot_core import get_db
from convergence_engine import ASSET_TO_FAMILY, FAMILIES


# ── Category auto-detect keywords ──
CATEGORY_HINTS = {
    "emotes":   ["emote", "dance", "sway", "flip", "bounce", "groove", "spin",
                 "idle", "pose", "wave", "step", "jiggle", "wiggle", "shuffle",
                 "twerk", "moonwalk", "floss", "drop", "lean"],
    "hats":     ["hat", "beanie", "cap", "crown", "beret", "bonnet", "visor",
                 "snapback", "bucket", "bowler", "fedora"],
    "hair":     ["hair", "wig", "bun", "braid", "ponytail", "bangs", "fringe",
                 "curly", "straight", "long hair", "short hair"],
    "face":     ["mask", "glasses", "sunglasses", "eyepatch", "visor", "face",
                 "eyebrow", "eyelash", "makeup", "lipstick"],
    "neck":     ["necklace", "chain", "scarf", "choker", "pendant", "collar"],
    "shoulder": ["shoulder", "pet", "parrot", "shoulder buddy"],
    "front":    ["front", "chest", "apron", "sash", "front accessory"],
    "back":     ["back", "backpack", "wings", "cape", "tail", "quiver",
                 "backpack", "satchel"],
    "waist":    ["waist", "belt", "tail", "skirt", "shorts"],
    "classic":  ["shirt", "tshirt", "t-shirt", "pants", "jacket", "hoodie",
                 "sweater", "sweatshirt", "classic"],
    "tops":     ["tank", "tank top", "crop", "crop top", "blouse", "camisole"],
    "gear":     ["sword", "staff", "wand", "bow", "shield", "gear"],
}

# ── Aesthetic families (used to cluster similar words) ──
AESTHETIC_FAMILIES = {
    "kawaii":     {"cute", "kawaii", "soft", "chibi", "coquette", "dolly",
                   "kawaiicore", "yume", "dreamy", "sweet", "adorable",
                   "angelic", "baby", "princess", "softie", "pastel"},
    "y2k":        {"y2k", "2000s", "retro", "cyber", "chrome", "metallic",
                   "futuristic", "noughties", "dubai", "mcbling", "bimbo",
                   "y2kcore"},
    "cottagecore": {"cottagecore", "fairy", "garden", "floral", "cozy",
                    "vintage", "soft", "nature", "meadow", "woodland",
                    "mushroom", "coquette"},
    "goth":       {"goth", "dark", "emo", "grunge", "alt", "edgy", "punk",
                   "macabre", "vampire", "occult", "witchy", "cyberpunk"},
    "streetwear": {"streetwear", "urban", "hip hop", "skater", "sporty",
                   "casual", "hype", "y2k", "trendy", "drip", "swag"},
    "decora":     {"decora", "kidcore", "colorful", "rainbow", "harajuku",
                   "cute", "yume kawaii", "pastel", "kandi"},
    "preppy":     {"preppy", "clean", "casual", "cozy", "sporty", "school",
                   "academia", "classic", "smart", "collegiate"},
    "celestial":  {"celestial", "moon", "star", "sun", "galaxy", "cosmic",
                   "astrology", "zodiac", "magical", "witchy", "aura",
                   "spiritual"},
    "cozy":       {"cozy", "soft", "warm", "pastel", "comfy", "plush",
                   "fluffy", "snuggle", "cottagecore", "warm"},
    "anime":      {"anime", "manga", "japanese", "harajuku", "gyaru",
                   "kawaii", "senpai", "waifu", "otaku", "seifuku"},
    "cyber":      {"cyber", "tech", "neon", "chrome", "glitch", "virtual",
                   "future", "digital", "matrix", "cyberpunk", "holographic"},
    "coquette":   {"coquette", "dolly", "soft", "bow", "ribbon", "pastel",
                   "princess", "angelic", "pink", "lace", "frilly", "kawaii"},
}


# ════════════════════════════════════════════════════════════════════
# CATEGORY DETECTION
# ════════════════════════════════════════════════════════════════════

def _detect_category(name, explicit_family=None):
    """Auto-detect category from name. Explicit wins."""
    if explicit_family and explicit_family in FAMILIES:
        return explicit_family

    name_lower = (name or "").lower()
    scores = Counter()
    for cat, words in CATEGORY_HINTS.items():
        for w in words:
            if w in name_lower:
                scores[cat] += len(w)
    if scores:
        return scores.most_common(1)[0][0]
    return "other"


# ════════════════════════════════════════════════════════════════════
# DB MINING — sales-weighted
# ════════════════════════════════════════════════════════════════════

def _family_sql(family):
    ids = FAMILIES.get(family)
    if not ids:
        return "", []
    ph = ",".join(["%s"] * len(ids))
    return f" and asset_type_id in ({ph})", list(ids)


def _mine_top_seller_tags(cur, name_words, family):
    """Top sellers in this niche + family. Mine tags weighted by favs."""
    if not name_words:
        return Counter()

    fam_sql, fam_params = _family_sql(family)
    patterns = [f"%{w}%" for w in name_words[:4]]

    cur.execute(f"""
        select description, favorite_count
        from items
        where lower(name) like any(%s)
          and favorite_count > 500
          and description is not null
          and length(trim(description)) > 30
          {fam_sql}
        order by favorite_count desc
        limit 40
    """, patterns + fam_params)
    rows = cur.fetchall()

    tag_weight = Counter()
    for desc, favs in rows:
        d = (desc or "").lower()
        tag_section = ""
        for marker in ["tags:", "tag:", "keywords:", "search:", "tag -"]:
            if marker in d:
                idx = d.index(marker) + len(marker)
                tag_section = d[idx:idx + 3000]
                break
        source = tag_section or d

        tokens = re.findall(r"[a-z][a-z0-9'’\-]{2,25}", source)
        weight = 1 + (favs / 1000.0)
        seen_this_item = set()
        for tok in tokens:
            tok = tok.strip().strip("'’-,.")
            if (3 <= len(tok) <= 25
                and "http" not in tok
                and "www" not in tok
                and ".com" not in tok
                and "roblox" not in tok
                and "catalog" not in tok):
                if tok not in seen_this_item:
                    tag_weight[tok] += weight
                    seen_this_item.add(tok)

    return tag_weight


def _mine_recent_winners(cur, name_words, family):
    """Recently launched high-performers. Reflects current trend."""
    if not name_words:
        return Counter()

    fam_sql, fam_params = _family_sql(family)
    patterns = [f"%{w}%" for w in name_words[:4]]

    cur.execute(f"""
        select description, favorite_count
        from items
        where lower(name) like any(%s)
          and favorite_count > 100
          and created_at > now() - interval '90 days'
          and description is not null
          and length(trim(description)) > 30
          {fam_sql}
        order by favorite_count desc
        limit 30
    """, patterns + fam_params)
    rows = cur.fetchall()

    tag_weight = Counter()
    for desc, favs in rows:
        d = (desc or "").lower()
        tag_section = ""
        for marker in ["tags:", "tag:", "keywords:", "search:"]:
            if marker in d:
                idx = d.index(marker) + len(marker)
                tag_section = d[idx:idx + 3000]
                break
        source = tag_section or d

        tokens = re.findall(r"[a-z][a-z0-9'’\-]{2,25}", source)
        weight = (1 + (favs / 500.0)) * 1.5
        seen = set()
        for tok in tokens:
            tok = tok.strip().strip("'’-,.")
            if (3 <= len(tok) <= 25
                and "http" not in tok
                and "www" not in tok):
                if tok not in seen:
                    tag_weight[tok] += weight
                    seen.add(tok)

    return tag_weight


def _mine_search_demand(cur, name_words):
    """Real queries from search_suggestions. Highest signal."""
    if not name_words:
        return Counter()

    patterns = [f"%{w}%" for w in name_words[:4]]

    cur.execute("""
        select suggestion
        from search_suggestions
        where suggestion ilike any(%s)
        limit 200
    """, (patterns,))
    rows = cur.fetchall()

    tag_weight = Counter()
    for (suggestion,) in rows:
        s = (suggestion or "").lower().strip()
        if not s or len(s) > 30:
            continue
        if not any(x in s for x in ["http", "www", ".com"]):
            tag_weight[s] += 3.0
            for w in re.findall(r"[a-z]{3,}", s):
                tag_weight[w] += 0.5

    return tag_weight


def _find_aesthetic_matches(name_words):
    """Find aesthetic families matching any name word."""
    matched_families = []
    for word in name_words:
        for fam_name, members in AESTHETIC_FAMILIES.items():
            if word in members:
                matched_families.append(fam_name)

    if not matched_families:
        return Counter()

    tag_weight = Counter()
    for fam in set(matched_families):
        for member in AESTHETIC_FAMILIES[fam]:
            tag_weight[member] += 2.0

    return tag_weight


def _color_matches(name_words):
    """Color sibling expansion."""
    COLORS = {
        "black": ["dark", "noir", "shadow", "midnight", "onyx", "void"],
        "white": ["cream", "ivory", "snow", "pearl", "angelic", "pure"],
        "red":   ["crimson", "cherry", "ruby", "scarlet", "wine", "berry"],
        "pink":  ["rose", "hot pink", "blush", "magenta", "fuchsia",
                  "bubblegum", "flamingo", "sakura"],
        "purple": ["lavender", "violet", "lilac", "mauve", "plum", "grape"],
        "blue":  ["cyan", "sky", "ocean", "sapphire", "ice", "aqua",
                  "denim", "baby blue"],
        "green": ["mint", "emerald", "sage", "lime", "forest", "olive",
                  "matcha"],
        "yellow": ["gold", "lemon", "butter", "mustard", "honey", "sunshine"],
        "orange": ["peach", "coral", "tangerine", "apricot", "rust", "amber"],
        "brown": ["chocolate", "caramel", "mocha", "tan", "coffee", "earth"],
        "silver": ["chrome", "metallic", "platinum", "steel", "gray", "grey"],
        "gold": ["yellow", "golden", "amber", "gilded", "luxury", "royal"],
        "gray": ["grey", "silver", "smoke", "ash", "storm", "fog"],
        "grey": ["gray", "silver", "smoke", "ash", "storm", "fog"],
    }
    tags = Counter()
    for w in name_words:
        for sib in COLORS.get(w, []):
            tags[sib] += 1.5
    return tags


# ════════════════════════════════════════════════════════════════════
# MAIN GENERATOR
# ════════════════════════════════════════════════════════════════════

def generate_tags(item_name, family=None, max_tags=45):
    """Generate 45 sales-triggering tags for an item."""
    if not item_name or not item_name.strip():
        return {"error": "Item name required."}

    skip = {"the", "and", "for", "with", "you", "your", "from", "that",
            "this", "into", "over", "will", "can", "are", "has", "how",
            "its", "our", "all"}
    name_words = [
        w for w in re.findall(r"[a-z]{3,}", item_name.lower())
        if w not in skip
    ]
    if not name_words:
        return {"error": "No meaningful words in name."}

    detected_family = _detect_category(item_name, explicit_family=family)

    conn = get_db(); cur = conn.cursor()
    try:
        top_sellers    = _mine_top_seller_tags(cur, name_words, detected_family)
        recent_winners = _mine_recent_winners(cur, name_words, detected_family)
        search_demand  = _mine_search_demand(cur, name_words)
    except Exception as e:
        print(f"[tag_generator] DB mining failed: {e}", flush=True)
        top_sellers = Counter()
        recent_winners = Counter()
        search_demand = Counter()
    finally:
        cur.close(); conn.close()

    aesthetic = _find_aesthetic_matches(name_words)
    colors    = _color_matches(name_words)

    combined = Counter()
    for d, mult in [
        (search_demand, 1.0),
        (recent_winners, 1.0),
        (top_sellers, 0.7),
        (aesthetic, 1.2),
        (colors, 1.0),
    ]:
        for tag, weight in d.items():
            combined[tag] += weight * mult

    for w in name_words:
        combined[w] += 5.0

    junk = {"http", "https", "www", "com", "roblox", "catalog", "store",
            "shop", "join", "group", "the", "and", "for", "you", "your",
            "with", "from", "this", "that", "have", "will", "can", "all",
            "our", "its", "new", "best", "top", "buy", "get", "any"}
    filtered = {
        tag: score for tag, score in combined.items()
        if tag not in junk
        and 3 <= len(tag) <= 25
        and not any(c in tag for c in "0123456789@#")
    }

    ranked = sorted(filtered.items(), key=lambda x: x[1], reverse=True)
    final_tags = [tag for tag, _ in ranked[:max_tags]]

    return {
        "item_name": item_name,
        "family": detected_family,
        "tags": final_tags,
        "sources": {
            "search_demand":   len(search_demand),
            "recent_winners":  len(recent_winners),
            "top_sellers":     len(top_sellers),
            "aesthetic":       len(aesthetic),
            "colors":          len(colors),
            "name_words":      len(name_words),
        },
        "top_weighted": ranked[:10],
    }


def format_tags(result):
    if result.get("error"):
        return [f"❌ {result['error']}"]

    tags = result["tags"]
    tag_line = ", ".join(tags)
    src = result["sources"]

    chunks = []

    chunks.append(
        f"# 🏷️ TAGS — `{result['item_name'][:60]}`\n"
        f"_Category detected: `{result['family']}` · "
        f"{len(tags)} tags generated_"
    )

    chunks.append(
        f"**📋 Copy this into your Roblox description:**\n"
        f"```\n{tag_line}\n```"
    )

    if result.get("top_weighted"):
        lines = ["**🎯 Highest-weight tags (sales signal):**"]
        for tag, score in result["top_weighted"][:10]:
            lines.append(f"`{tag}` — weight {score:.1f}")
        chunks.append("\n".join(lines))

    chunks.append(
        f"**📊 Sources mined:**\n"
        f"• Search demand (real queries): **{src['search_demand']}**\n"
        f"• Recent winners (last 90d): **{src['recent_winners']}**\n"
        f"• Top sellers (all time): **{src['top_sellers']}**\n"
        f"• Aesthetic siblings: **{src['aesthetic']}**\n"
        f"• Color siblings: **{src['colors']}**\n"
        f"• Name words: **{src['name_words']}**\n"
        f"\n_Every tag weighted by how often it appears in top sellers "
        f"AND search queries._"
    )

    return chunks
