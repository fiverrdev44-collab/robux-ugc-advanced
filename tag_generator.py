"""
tag_generator.py — sales-weighted SEO tag generator.

HYBRID approach:
  1. Live Roblox (top sellers by keyword) — mines tag blocks AND words
  2. DB top sellers (name-based) — mines tag blocks
  3. DB recent winners (last 90d) — mines tag blocks
  4. DB family-wide fallback — mines common words from top items
  5. Real search suggestions — real demand signals
  6. Aesthetic + color siblings — static lookup

FIXES in this version:
  - Extended _ENGLISH_BLOCK + new _JUNK_WORDS set blocks API field
    names (creatorname, salestypefilter, subcategory, etc.) that leak
    from Roblox data dumps into descriptions.
  - Vowel check rejects consonant-only garbage.
  - Family-wide fallback for thin name-based mining.
"""
import os
import re
import requests
from collections import Counter
from bot_core import get_db
from convergence_engine import ASSET_TO_FAMILY, FAMILIES


ROBLOX_SEARCH_URL = "https://catalog.roblox.com/v1/search/items/details"
MIN_DB_TAGS = 12

ACCESSORY_IDS = [43, 44, 45, 46, 47]

SUBTYPE_LABELS = {
    43: "neck", 44: "shoulder", 45: "front", 46: "back", 47: "waist",
}

_ACCESSORY_SUBTYPE_HINTS = {
    "back": 46, "backpack": 46, "bookbag": 46,
    "wing": 46, "wings": 46, "cape": 46, "cloak": 46,
    "tail": 46, "tails": 46, "quiver": 46, "satchel": 46,
    "antenna": 46, "antennae": 46, "jetpack": 46,
    "neck": 43, "necklace": 43, "chain": 43, "choker": 43,
    "pendant": 43, "collar": 43, "scarf": 43, "bandana": 43,
    "bowtie": 43, "lanyard": 43, "medallion": 43,
    "shoulder": 44, "parrot": 44, "buddy": 44, "companion": 44,
    "mouse": 44, "rat": 44,
    "front": 45, "chest": 45, "apron": 45, "sash": 45,
    "brooch": 45, "chestplate": 45, "bib": 45,
    "waist": 47, "belt": 47, "hip": 47, "fanny": 47,
    "pouch": 47, "kimono": 47,
}


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
    "back":     ["back", "backpack", "wings", "cape", "tail", "quiver", "satchel"],
    "waist":    ["waist", "belt", "tail", "skirt", "shorts"],
    "classic":  ["shirt", "tshirt", "t-shirt", "pants", "jacket", "hoodie",
                 "sweater", "sweatshirt", "classic"],
    "tops":     ["tank", "tank top", "crop", "crop top", "blouse", "camisole"],
    "gear":     ["sword", "staff", "wand", "bow", "shield", "gear"],
}


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


COLOR_SIBLINGS = {
    "black": ["dark", "noir", "shadow", "midnight", "onyx", "void"],
    "white": ["cream", "ivory", "snow", "pearl", "angelic", "pure"],
    "red":   ["crimson", "cherry", "ruby", "scarlet", "wine", "berry"],
    "pink":  ["rose", "hot pink", "blush", "magenta", "fuchsia",
              "bubblegum", "flamingo", "sakura"],
    "purple": ["lavender", "violet", "lilac", "mauve", "plum", "grape"],
    "blue":  ["cyan", "sky", "ocean", "sapphire", "ice", "aqua",
              "denim", "baby blue"],
    "green": ["mint", "emerald", "sage", "lime", "forest", "olive", "matcha"],
    "yellow": ["gold", "lemon", "butter", "mustard", "honey", "sunshine"],
    "orange": ["peach", "coral", "tangerine", "apricot", "rust", "amber"],
    "brown": ["chocolate", "caramel", "mocha", "tan", "coffee", "earth"],
    "silver": ["chrome", "metallic", "platinum", "steel", "gray", "grey"],
    "gold": ["yellow", "golden", "amber", "gilded", "luxury", "royal"],
    "gray": ["grey", "silver", "smoke", "ash", "storm", "fog"],
    "grey": ["gray", "silver", "smoke", "ash", "storm", "fog"],
}


_ENGLISH_BLOCK = {
    # Articles / glue
    "the","and","for","with","you","your","from","that","this","into",
    "over","under","will","can","are","has","how","its","our","all",
    "have","had","was","were","been","being","get","got","make","made",
    "more","most","some","any","every","each","other","another","such",
    "only","very","just","also","than","then","them","they","their",
    "there","here","when","what","where","which","while","who","whom",
    "whose","why","yes","not","but","nor","yet","so","if","or","as",
    "at","by","in","on","of","to","up","down","out","off","new","old",
    "one","two","three","four","five","six","seven","eight","nine","ten",
    # Generic UGC
    "model","models","item","items","shop","store","group","community",
    "communities","join","follow","visit","check","click","link","links",
    "http","https","www","com","net","org","roblox","catalog","asset",
    "assets","id","page","site","website","created","creator","creators",
    "buy","buying","sell","selling","sold","sale","price","prices",
    "cost","free","paid","cheap","expensive","discount","promo",
    "promotion","version","edition","style","styled","type","kinds",
    "kind","sort","something","anything","nothing","everything",
    "anyone","someone","everyone","nobody","somebody","anybody",
    "everybody","would","could","should","still","many","much","less",
    # Meta / API field names (Roblox data leaks)
    "creatorname","creatortype","salestypefilter","subcategory",
    "category","assettype","assetid","itemtype","itemid",
    "favoritecount","favorited","favourite","favorites",
    "snapshot","snapshots","updated","contained","tall","break",
    "quality","enjoy","using","please","hope","guys","folks",
    "really","actually","basically","literally","honestly",
    "gonna","wanna","gotta","kinda","sorta",
    "lol","lmao","omg","wtf","tbh","imo","idk",
    "yeah","yep","nope","okay","even","better",
    # Generic verbs (conjugated)
    "want","wants","wanted","wanting","need","needs","needed","needing",
    "make","makes","making","give","gives","gave","given","giving",
    "take","takes","took","taken","taking","come","comes","came",
    "coming","go","goes","went","gone","going","get","gets","getting",
    "see","sees","saw","seen","seeing","use","uses","used","using",
    "user","users","work","works","worked","working","play","plays",
    "played","playing","stop","stops","stopped","stopping","start",
    "starts","started","starting","find","finds","found","finding",
    "keep","keeps","kept","keeping","call","calls","called","calling",
    "try","tries","tried","trying","ask","asks","asked","asking",
    "put","puts","putting","say","says","said","saying","tell","tells",
    "told","telling","show","shows","showed","shown","showing",
    "leave","leaves","left","leaving","let","lets","letting",
    "seem","seems","seemed","seeming","sound","sounds","sounded",
    "sounding","turn","turns","turned","turning","help","helps",
    "helped","helping","walk","walks","walked","walking","run","runs",
    "ran","running","believe","believes","believed","believing",
    "happen","happens","happened","happening","talk","talks","talked",
    "talking","move","moves","moved","moving","live","lives","lived",
    "living","think","thinks","thought","thinking","feel","feels",
    "felt","feeling","love","loves","loved","loving","hate","hates",
    "hated","hating","like","likes","liked","liking","look","looks",
    "looked","looking","know","knows","knew","known","knowing",
}


# Words that never belong in a tag block, regardless of source.
_JUNK_WORDS = {
    # Roblox API fields (belt-and-suspenders with _ENGLISH_BLOCK)
    "creatorname", "creatortype", "salestypefilter", "subcategory",
    "category", "assettype", "assetid", "itemtype", "itemid",
    "favoritecount", "favorited", "favourite", "favorites",
    "snapshot", "snapshots", "updated", "created",
    # Description meta
    "contained", "tall", "better", "break", "quality", "enjoy",
    "using", "please", "hope", "guys", "folks", "everyone",
    "really", "actually", "basically", "literally", "honestly",
    "gonna", "wanna", "gotta", "kinda", "sorta",
    "lol", "lmao", "omg", "wtf", "tbh", "imo", "idk",
    "yeah", "yep", "nope", "okay",
    # Generic verbs
    "want", "wants", "wanted", "need", "needs", "needed",
    "make", "makes", "made", "give", "gives", "gave",
    "take", "takes", "took", "come", "comes", "came",
    "look", "looks", "know", "knows", "feel", "feels",
    "tell", "tells", "show", "shows", "leave", "leaves",
    # Popularity fillers
    "popular", "viral", "trending", "trend", "trendy",
    "amazing", "awesome", "epic", "great", "wonderful",
    "fantastic", "perfect", "special",
    # Random one-off junk
    "panini", "meanie", "nervy",
}

# Words must be at least 4 chars and contain a vowel
_MIN_WORD_LEN = 4


def _detect_accessory_subtype(name):
    if not name:
        return None
    n = (name or "").lower()
    for hint in sorted(_ACCESSORY_SUBTYPE_HINTS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(hint)}\b", n):
            return _ACCESSORY_SUBTYPE_HINTS[hint]
    return None


def _is_tag_shaped(tok):
    if not tok:
        return False
    if not (3 <= len(tok) <= 20):
        return False
    if tok in _ENGLISH_BLOCK or tok in _JUNK_WORDS:
        return False
    if not re.match(r"^[a-z][a-z'’\- ]*$", tok):
        return False
    if tok.count("-") > 1:
        return False
    if re.search(r"[a-z]-[a-z]-[a-z]", tok):
        return False
    if not re.search(r"[aeiou]", tok):
        return False
    return True


def _extract_tags_from_description(desc):
    d = (desc or "").lower()
    if not d:
        return []

    tag_section = ""
    for marker in ["tags:", "tag:", "keywords:", "search terms:",
                   "search:", "tag -"]:
        if marker in d:
            idx = d.index(marker) + len(marker)
            tag_section = d[idx:idx + 3000]
            break

    if not tag_section:
        return []

    raw_tokens = re.split(r"[_,|;\n]+", tag_section)
    out = []
    seen = set()
    for raw in raw_tokens:
        tok = raw.strip().strip("'’\"-•·*#.,:;!?()[]{}")
        parts = tok.split()
        if not parts:
            continue
        if len(parts) == 1:
            if _is_tag_shaped(tok) and tok not in seen:
                seen.add(tok); out.append(tok)
        elif len(parts) == 2:
            if not all(p in _ENGLISH_BLOCK for p in parts):
                if all(_is_tag_shaped(p) or p in _ENGLISH_BLOCK for p in parts):
                    if tok not in seen:
                        seen.add(tok); out.append(tok)
    return out


def _extract_words_from_text(text):
    """Extract clean words from name+description for tag mining."""
    t = (text or "").lower()
    out = []
    for w in re.findall(r"[a-z]{4,}", t):
        if len(w) > 20:
            continue
        if w in _ENGLISH_BLOCK or w in _JUNK_WORDS:
            continue
        # Must contain a vowel (rejects consonant-only garbage)
        if not re.search(r"[aeiou]", w):
            continue
        # Reject 4-letter words that start with 3 consonants (yffs, etc.)
        if len(w) == 4 and not re.search(r"[aeiou]", w[:2]):
            continue
        out.append(w)
    return out


def _family_to_roblox_category(family, subtype=None):
    if subtype:
        return {43: 5, 44: 9, 45: 7, 46: 8, 47: 6}.get(subtype)
    if not family:
        return None
    if family == "accessory":
        return None
    return {
        "hair": 12, "face": 13, "neck": 5, "shoulder": 9,
        "front": 7, "back": 8, "waist": 6,
    }.get(family)


def _fetch_live_items(keyword, family=None, subtype=None, limit=30):
    try:
        cookie = (os.getenv("ROBLOSECURITY_COOKIE_1")
                  or os.getenv("ROBLOSECURITY_COOKIE"))
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; UGCBot/1.0)",
            "Accept": "application/json",
        }
        if cookie:
            headers["Cookie"] = f".ROBLOSECURITY={cookie}"

        params = {"Keyword": keyword, "Limit": min(limit, 30), "SortType": 3}
        cat = _family_to_roblox_category(family, subtype)
        if cat:
            params["Category"] = cat

        r = requests.get(ROBLOX_SEARCH_URL, params=params,
                         headers=headers, timeout=15)
        if r.status_code != 200:
            print(f"[tag_generator] live HTTP {r.status_code}", flush=True)
            return []

        data = (r.json() or {}).get("data", []) or []
        if not data:
            return []

        out = []
        conn = get_db(); cur = conn.cursor()
        try:
            for item in data:
                item_id = item.get("id")
                name = (item.get("name") or "").strip()
                if not item_id or not name:
                    continue
                desc = (item.get("description") or "").strip()
                favs = item.get("favoriteCount") or 0
                price = item.get("price") or 0
                atype = item.get("assetType") or 0
                creator = item.get("creatorName") or ""

                # Loose family filter — accept if we know it matches OR
                # if the type is unknown (0/missing).
                if subtype:
                    if atype and atype != subtype:
                        continue
                elif family == "accessory" and not subtype:
                    if atype and atype not in ACCESSORY_IDS:
                        continue
                elif family and family != "accessory":
                    if atype:
                        item_family = ASSET_TO_FAMILY.get(atype)
                        if item_family and item_family != family:
                            continue

                try:
                    cur.execute("""
                        insert into items (id, name, description, favorite_count,
                                           price, asset_type_id, creator_name, fetched_at)
                        values (%s, %s, %s, %s, %s, %s, %s, now())
                        on conflict (id) do update set
                            description = excluded.description,
                            favorite_count = excluded.favorite_count,
                            price = excluded.price,
                            fetched_at = now()
                    """, (item_id, name, desc, favs, price, atype, creator))
                except Exception:
                    pass

                out.append((name, desc, favs))
            conn.commit()
        finally:
            cur.close(); conn.close()

        print(f"[tag_generator] live: {len(out)} items for '{keyword}'", flush=True)
        return out
    except Exception as e:
        print(f"[tag_generator] live fetch failed: {e}", flush=True)
        return []


def _mine_live_tags(keyword, family, subtype=None):
    """
    HYBRID live mining — extracts BOTH:
      1. Tag blocks (from descriptions with 'tags:' sections)
      2. Common words from name+description (weighted by favs)
    Returns (tag_block_counter, word_counter, item_count).
    """
    rows = _fetch_live_items(keyword, family=family, subtype=subtype, limit=30)
    if not rows:
        return Counter(), Counter(), 0

    tag_weight = Counter()
    tag_appearances = Counter()
    word_weight = Counter()

    for name, desc, favs in rows:
        weight = 1 + ((favs or 0) / 1000.0)

        # Source 1: explicit tag blocks
        tags = _extract_tags_from_description(desc)
        for tag in set(tags):
            tag_weight[tag] += weight
            tag_appearances[tag] += 1

        # Source 2: words from name + description
        text = f"{name or ''} {desc or ''}"
        for w in set(_extract_words_from_text(text)):
            word_weight[w] += weight

    # Tag blocks: require 2+ appearances
    live_tag_block = Counter({
        tag: score for tag, score in tag_weight.items()
        if tag_appearances[tag] >= 2
    })

    # Word mining: keep words that appear in at least 2-3 live items
    live_words = Counter({
        w: score for w, score in word_weight.items()
        if score >= 2.0
    })

    return live_tag_block, live_words, len(rows)


def _detect_category(name, explicit_family=None):
    if explicit_family == "accessory":
        return "accessory"
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


def _family_sql(family, subtype=None):
    if family == "accessory":
        if subtype:
            return " and asset_type_id = %s", [subtype]
        return " and asset_type_id in (43, 44, 45, 46, 47)", []
    ids = FAMILIES.get(family)
    if not ids:
        return "", []
    ph = ",".join(["%s"] * len(ids))
    return f" and asset_type_id in ({ph})", list(ids)


def _mine_top_seller_tags(cur, name_words, family, subtype=None):
    if not name_words:
        return Counter()
    fam_sql, fam_params = _family_sql(family, subtype)
    patterns = [f"%{w}%" for w in name_words[:4]]

    cur.execute(f"""
        select description, favorite_count
        from items
        where lower(name) like any(%s)
          and favorite_count > 500
          and description is not null
          and length(trim(description)) > 30
          and lower(description) like '%%tags:%%'
          {fam_sql}
        order by favorite_count desc
        limit 60
    """, [patterns] + fam_params)

    rows = cur.fetchall()
    tag_weight = Counter()
    tag_appearances = Counter()
    for desc, favs in rows:
        tags = _extract_tags_from_description(desc)
        if not tags:
            continue
        weight = 1 + ((favs or 0) / 1000.0)
        for tag in set(tags):
            tag_weight[tag] += weight
            tag_appearances[tag] += 1

    return Counter({
        tag: score for tag, score in tag_weight.items()
        if tag_appearances[tag] >= 2
    })


def _mine_recent_winners(cur, name_words, family, subtype=None):
    if not name_words:
        return Counter()
    fam_sql, fam_params = _family_sql(family, subtype)
    patterns = [f"%{w}%" for w in name_words[:4]]

    cur.execute(f"""
        select description, favorite_count
        from items
        where lower(name) like any(%s)
          and favorite_count > 100
          and created_at > now() - interval '90 days'
          and description is not null
          and length(trim(description)) > 30
          and lower(description) like '%%tags:%%'
          {fam_sql}
        order by favorite_count desc
        limit 40
    """, [patterns] + fam_params)

    rows = cur.fetchall()
    tag_weight = Counter()
    tag_appearances = Counter()
    for desc, favs in rows:
        tags = _extract_tags_from_description(desc)
        if not tags:
            continue
        weight = (1 + ((favs or 0) / 500.0)) * 1.5
        for tag in set(tags):
            tag_weight[tag] += weight
            tag_appearances[tag] += 1

    return Counter({
        tag: score for tag, score in tag_weight.items()
        if tag_appearances[tag] >= 2
    })


def _mine_family_wide_tags(cur, family, subtype=None, limit=200):
    """DB family-wide fallback — mines common words from top items."""
    if not family:
        return Counter()
    fam_sql, fam_params = _family_sql(family, subtype)

    cur.execute(f"""
        select name, description, favorite_count
        from items
        where favorite_count > 50
          and favorite_count < 500000
          {fam_sql}
        order by favorite_count desc
        limit %s
    """, fam_params + [limit])

    rows = cur.fetchall()
    word_weight = Counter()
    for name, desc, favs in rows:
        text = f"{name or ''} {desc or ''}"
        weight = 1 + ((favs or 0) / 1000.0)
        for w in set(_extract_words_from_text(text)):
            word_weight[w] += weight

    return word_weight


def _mine_search_demand(cur, name_words):
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
    for row in rows:
        s = (row[0] or "").lower().strip()
        if not s or len(s) > 30:
            continue
        if any(x in s for x in ["http", "www", ".com"]):
            continue
        # Skip single-word suggestions that are junk
        parts = re.findall(r"[a-z]{3,}", s)
        if parts and all(p in _ENGLISH_BLOCK or p in _JUNK_WORDS for p in parts):
            continue
        tag_weight[s] += 3.0
        for w in re.findall(r"[a-z]{3,}", s):
            if w in _ENGLISH_BLOCK or w in _JUNK_WORDS:
                continue
            if not re.search(r"[aeiou]", w):
                continue
            tag_weight[w] += 0.5

    return tag_weight


def _find_aesthetic_matches(name_words):
    matched = []
    for word in name_words:
        for fam_name, members in AESTHETIC_FAMILIES.items():
            if word in members:
                matched.append(fam_name)
    if not matched:
        return Counter()
    tags = Counter()
    for fam in set(matched):
        for member in AESTHETIC_FAMILIES[fam]:
            tags[member] += 2.0
    return tags


def _color_matches(name_words):
    tags = Counter()
    for w in name_words:
        for sib in COLOR_SIBLINGS.get(w, []):
            tags[sib] += 1.5
    return tags


def generate_tags(item_name, family=None, max_tags=45):
    if not item_name or not item_name.strip():
        return {"error": "Item name required."}

    if family and family != "accessory":
        try:
            from category_configs import to_convergence_family
            family = to_convergence_family(family)
        except Exception:
            pass

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

    accessory_subtype = None
    if detected_family == "accessory":
        accessory_subtype = _detect_accessory_subtype(item_name)

    # ── DB mining ──
    top_sellers = Counter()
    recent_winners = Counter()
    search_demand = Counter()
    family_wide = Counter()
    live_tags = Counter()
    live_words = Counter()
    live_count = 0

    conn = get_db(); cur = conn.cursor()
    try:
        try:
            top_sellers = _mine_top_seller_tags(
                cur, name_words, detected_family, accessory_subtype)
        except Exception as e:
            print(f"[tag_generator] top_seller failed: {e}", flush=True)
        try:
            recent_winners = _mine_recent_winners(
                cur, name_words, detected_family, accessory_subtype)
        except Exception as e:
            print(f"[tag_generator] recent failed: {e}", flush=True)
        try:
            search_demand = _mine_search_demand(cur, name_words)
        except Exception as e:
            print(f"[tag_generator] demand failed: {e}", flush=True)

        if len(top_sellers) + len(recent_winners) < 8:
            try:
                family_wide = _mine_family_wide_tags(
                    cur, detected_family, accessory_subtype, limit=200)
                print(f"[tag_generator] family-wide: {len(family_wide)} words",
                      flush=True)
            except Exception as e:
                print(f"[tag_generator] family-wide failed: {e}", flush=True)
    finally:
        cur.close(); conn.close()

    # ── LIVE FALLBACK ──
    db_total = len(top_sellers) + len(recent_winners) + len(family_wide)
    if db_total < MIN_DB_TAGS * 2:
        live_kw = None
        sorted_words = sorted(name_words, key=len, reverse=True)
        if sorted_words:
            live_kw = sorted_words[0]

        if live_kw and len(live_kw) >= 3:
            try:
                result = _mine_live_tags(
                    live_kw, detected_family, accessory_subtype)
                if isinstance(result, tuple) and len(result) == 3:
                    live_tags, live_words, live_count = result
                print(f"[tag_generator] live: {live_count} items · "
                      f"{len(live_tags)} tag-block tags · "
                      f"{len(live_words)} word tags", flush=True)
            except Exception as e:
                print(f"[tag_generator] live mining failed: {e}", flush=True)

    aesthetic = _find_aesthetic_matches(name_words)
    colors = _color_matches(name_words)

    combined = Counter()
    for source, mult in [
        (live_tags, 1.8),
        (live_words, 1.4),
        (search_demand, 1.2),
        (recent_winners, 1.0),
        (top_sellers, 0.7),
        (family_wide, 0.4),
        (aesthetic, 1.2),
        (colors, 1.0),
    ]:
        for tag, weight in source.items():
            combined[tag] += weight * mult

    for w in name_words:
        combined[w] += 5.0

    junk = {"http", "https", "www", "com", "roblox", "catalog", "store",
            "shop", "join", "group", "the", "and", "for", "you", "your",
            "with", "from", "this", "that", "have", "will", "can", "all",
            "our", "its", "new", "best", "top", "buy", "get", "any"}
    junk = junk | _JUNK_WORDS
    filtered = {
        tag: score for tag, score in combined.items()
        if tag not in junk
        and tag not in _ENGLISH_BLOCK
        and 3 <= len(tag) <= 25
        and not any(c in tag for c in "0123456789@#")
        and re.search(r"[aeiou]", tag)
    }

    # ── RELEVANCE GATE ──
    FILLER_ANCHORS = {
        "cute", "cool", "nice", "best", "top", "new", "hot", "trendy",
        "viral", "aesthetic", "chibi", "soft", "pretty", "sweet",
        "amazing", "awesome", "epic", "lovely", "chill", "smooth",
        "fancy", "flashy", "silly", "goofy",
    }
    GENERIC_AESTHETICS = {
        "cute", "soft", "sweet", "pretty", "adorable", "lovely",
        "nice", "cool",
    }

    name_roots = set()
    for w in name_words:
        if w in FILLER_ANCHORS:
            continue
        name_roots.add(w)
        if len(w) >= 5:
            name_roots.add(w[:4])
        if len(w) >= 4:
            name_roots.add(w[:3])

    aesthetic_set = set(aesthetic.keys())
    color_set = set(colors.keys())

    relax_gate = (
        len(family_wide) > 30
        or len(live_tags) + len(live_words) > 20
    )

    def _is_relevant(tag):
        if tag in _ENGLISH_BLOCK or tag in _JUNK_WORDS:
            return False

        if relax_gate:
            if tag in FILLER_ANCHORS:
                return False
            return True

        if not name_roots:
            if tag in aesthetic_set and tag not in GENERIC_AESTHETICS:
                return True
            return tag in color_set

        if tag in name_roots:
            return True

        parts = tag.split()
        if len(parts) >= 2:
            hits = 0
            for part in parts:
                for r in name_roots:
                    if len(r) >= 4 and (r in part or part in r):
                        hits += 1
                        break
            if hits >= 2:
                return True
            if tag in color_set:
                return True
            if tag in aesthetic_set and tag not in GENERIC_AESTHETICS:
                return True
            return False

        for r in name_roots:
            if len(r) >= 4 and (r in tag or tag in r):
                return True
        if tag in aesthetic_set and tag not in GENERIC_AESTHETICS:
            return True
        if tag in color_set:
            return True
        return False

    filtered = {t: s for t, s in filtered.items() if _is_relevant(t)}

    ranked = sorted(filtered.items(), key=lambda x: x[1], reverse=True)
    final_tags = [tag for tag, _ in ranked[:max_tags]]

    return {
        "item_name": item_name,
        "family": detected_family,
        "subtype": accessory_subtype,
        "subtype_label": SUBTYPE_LABELS.get(accessory_subtype),
        "tags": final_tags,
        "sources": {
            "live_roblox":     live_count,
            "live_tag_blocks": len(live_tags),
            "live_words":      len(live_words),
            "search_demand":   len(search_demand),
            "recent_winners":  len(recent_winners),
            "top_sellers":     len(top_sellers),
            "family_wide":     len(family_wide),
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

    subtype_str = ""
    if result.get("subtype_label"):
        subtype_str = f" · `{result['subtype_label']}`"

    chunks.append(
        f"# 🏷️ TAGS — `{result['item_name'][:60]}`\n"
        f"_Category detected: `{result['family']}`{subtype_str} · "
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

    live_str = f"**{src['live_roblox']}**"
    if src['live_roblox'] > 0:
        live_str += " 🔥 (live Roblox)"

    chunks.append(
        f"**📊 Sources mined:**\n"
        f"• Live Roblox top sellers: {live_str}\n"
        f"    – tag blocks: **{src.get('live_tag_blocks', 0)}**\n"
        f"    – word mining: **{src.get('live_words', 0)}**\n"
        f"• Search demand (real queries): **{src['search_demand']}**\n"
        f"• Recent winners (last 90d): **{src['recent_winners']}**\n"
        f"• Top sellers (DB, all time): **{src['top_sellers']}**\n"
        f"• Family-wide (fallback): **{src.get('family_wide', 0)}**\n"
        f"• Aesthetic siblings: **{src['aesthetic']}**\n"
        f"• Color siblings: **{src['colors']}**\n"
        f"• Name words: **{src['name_words']}**\n"
        f"\n_Every tag traces to real data. No hallucination._"
    )

    return chunks
