"""
tag_generator.py — sales-weighted SEO tag generator.

FILLS TO 45:
  - Two-signal tags (2+ independent sources) rank highest
  - Single-signal tags fill the remaining slots
  - Category-wide pool guarantees enough candidates
  - Relevance gate rejects API fields + English junk

Signal pools:
  1. Name-matched top sellers (tags + words)
  2. Live Roblox for keyword (tags + words)
  3. Search suggestions matching name (phrases + words)
  4. Category-wide top sellers (words, 3+ appearances)
  5. Aesthetic siblings (name-matching only)
  6. Color siblings
  7. Name words (base boost)
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
    "the","and","for","with","you","your","from","that","this","into",
    "over","under","will","can","are","has","how","its","our","all",
    "have","had","was","were","been","being","get","got","make","made",
    "more","most","some","any","every","each","other","another","such",
    "only","very","just","also","than","then","them","they","their",
    "there","here","when","what","where","which","while","who","whom",
    "whose","why","yes","not","but","nor","yet","so","if","or","as",
    "at","by","in","on","of","to","up","down","out","off","new","old",
    "one","two","three","four","five","six","seven","eight","nine","ten",
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
    "creatorname","creatortype","salestypefilter","subcategory",
    "category","assettype","assetid","itemtype","itemid",
    "favoritecount","favorited","favourite","favorites",
    "snapshot","snapshots","updated","contained","tall","break",
    "quality","enjoy","using","please","hope","guys","folks",
    "really","actually","basically","literally","honestly",
    "gonna","wanna","gotta","kinda","sorta",
    "lol","lmao","omg","wtf","tbh","imo","idk",
    "yeah","yep","nope","okay","even","better",
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
    "favorite","favorited","bookmarked","hand","head","foot",
    "arm","leg","body","skin","eye","eyes","mouth","nose",
    "ear","ears","hair","finger","toe","chest","back",
    "hello","goodbye","welcome","thanks","thank",
    "girl","boy","man","woman","person","people","child",
    "kid","friend","family","guy","guys",
    "anywhere","everywhere","somewhere","nowhere",
    "always","never","sometimes","often","usually",
    "floating","hanging","standing","sitting","walking",
    "running","jumping","falling","rising","shining",
    "friendly","excited","confused","matching","contained",
}


def _detect_accessory_subtype(name):
    if not name:
        return None
    n = (name or "").lower()
    for hint in sorted(_ACCESSORY_SUBTYPE_HINTS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(hint)}\b", n):
            return _ACCESSORY_SUBTYPE_HINTS[hint]
    return None


def _is_valid_word(w):
    """Shape check + English block."""
    if not w:
        return False
    if not (3 <= len(w) <= 25):
        return False
    if any(c in w for c in "0123456789@#_"):
        return False
    if w in _ENGLISH_BLOCK:
        return False
    if not re.search(r"[aeiou]", w):
        return False
    if w.endswith("ly") and len(w) > 4:
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
            if _is_valid_word(tok) and tok not in seen:
                seen.add(tok); out.append(tok)
        elif len(parts) == 2:
            if all(_is_valid_word(p) or p in _ENGLISH_BLOCK for p in parts):
                if not all(p in _ENGLISH_BLOCK for p in parts):
                    if tok not in seen:
                        seen.add(tok); out.append(tok)
    return out


def _extract_words_from_text(text):
    t = (text or "").lower()
    return [w for w in set(re.findall(r"[a-z]{4,}", t)) if _is_valid_word(w)]


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
    rows = _fetch_live_items(keyword, family=family, subtype=subtype, limit=30)
    if not rows:
        return Counter(), Counter(), 0

    tag_weight = Counter()
    tag_appearances = Counter()
    word_weight = Counter()

    for name, desc, favs in rows:
        weight = 1 + ((favs or 0) / 1000.0)
        tags = _extract_tags_from_description(desc)
        for tag in set(tags):
            tag_weight[tag] += weight
            tag_appearances[tag] += 1
        text = f"{name or ''} {desc or ''}"
        for w in _extract_words_from_text(text):
            word_weight[w] += weight

    live_tags = Counter({
        tag: score for tag, score in tag_weight.items()
        if tag_appearances[tag] >= 2
    })
    live_words = Counter({
        w: score for w, score in word_weight.items()
        if score >= 2.0
    })
    return live_tags, live_words, len(rows)


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
    """Top sellers matching THIS item's name words."""
    if not name_words:
        return Counter(), Counter()
    fam_sql, fam_params = _family_sql(family, subtype)
    patterns = [f"%{w}%" for w in name_words[:4]]

    cur.execute(f"""
        select name, description, favorite_count
        from items
        where lower(name) like any(%s)
          and favorite_count > 100
          and description is not null
          and length(trim(description)) > 30
          {fam_sql}
        order by favorite_count desc
        limit 100
    """, [patterns] + fam_params)

    rows = cur.fetchall()
    tag_weight = Counter()
    tag_appearances = Counter()
    word_weight = Counter()

    for name, desc, favs in rows:
        weight = 1 + ((favs or 0) / 1000.0)
        tags = _extract_tags_from_description(desc)
        for tag in set(tags):
            tag_weight[tag] += weight
            tag_appearances[tag] += 1
        text = f"{name or ''} {desc or ''}"
        for w in _extract_words_from_text(text):
            word_weight[w] += weight

    tag_block = Counter({
        tag: score for tag, score in tag_weight.items()
        if tag_appearances[tag] >= 2
    })
    return tag_block, word_weight


def _mine_category_wide_words(cur, family, subtype=None, limit=300):
    """
    Top sellers across the WHOLE family (no name filter).
    Requires 3+ appearances — this kills one-off noise but ensures
    we always have enough candidates to fill 45 tags.
    """
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
    word_appearances = Counter()

    for name, desc, favs in rows:
        text = f"{name or ''} {desc or ''}"
        weight = 1 + ((favs or 0) / 1000.0)
        for w in _extract_words_from_text(text):
            word_weight[w] += weight
            word_appearances[w] += 1

    return Counter({
        w: score for w, score in word_weight.items()
        if word_appearances[w] >= 3
    })


def _mine_search_demand(cur, name_words):
    if not name_words:
        return Counter(), Counter()
    patterns = [f"%{w}%" for w in name_words[:4]]

    cur.execute("""
        select suggestion
        from search_suggestions
        where suggestion ilike any(%s)
        limit 400
    """, (patterns,))

    rows = cur.fetchall()
    phrase_weight = Counter()
    word_weight = Counter()

    for row in rows:
        s = (row[0] or "").lower().strip()
        if not s or len(s) > 35:
            continue
        if any(x in s for x in ["http", "www", ".com"]):
            continue
        parts = re.findall(r"[a-z]{3,}", s)
        if parts and all(p in _ENGLISH_BLOCK for p in parts):
            continue

        if _is_valid_word(s) or " " in s:
            phrase_weight[s] += 3.0
        for w in re.findall(r"[a-z]{3,}", s):
            if _is_valid_word(w):
                word_weight[w] += 1.0

    return phrase_weight, word_weight


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

    top_tags = Counter()
    top_words = Counter()
    live_tags = Counter()
    live_words = Counter()
    live_count = 0
    search_phrases = Counter()
    search_words = Counter()
    category_wide = Counter()

    conn = get_db(); cur = conn.cursor()
    try:
        try:
            top_tags, top_words = _mine_top_seller_tags(
                cur, name_words, detected_family, accessory_subtype)
            print(f"[tag_generator] top-seller: {len(top_tags)} tags · "
                  f"{len(top_words)} words", flush=True)
        except Exception as e:
            print(f"[tag_generator] top_seller failed: {e}", flush=True)

        try:
            search_phrases, search_words = _mine_search_demand(cur, name_words)
            print(f"[tag_generator] search: {len(search_phrases)} phrases · "
                  f"{len(search_words)} words", flush=True)
        except Exception as e:
            print(f"[tag_generator] demand failed: {e}", flush=True)

        # Always mine category-wide — provides the filler pool
        try:
            category_wide = _mine_category_wide_words(
                cur, detected_family, accessory_subtype, limit=300)
            print(f"[tag_generator] category-wide: {len(category_wide)} words",
                  flush=True)
        except Exception as e:
            print(f"[tag_generator] category-wide failed: {e}", flush=True)
    finally:
        cur.close(); conn.close()

    # Live fallback when DB thin
    if len(top_tags) + len(top_words) < MIN_DB_TAGS:
        live_kw = None
        sorted_words = sorted(name_words, key=len, reverse=True)
        if sorted_words:
            live_kw = sorted_words[0]
        if live_kw and len(live_kw) >= 3:
            try:
                live_tags, live_words, live_count = _mine_live_tags(
                    live_kw, detected_family, accessory_subtype)
                print(f"[tag_generator] live: {live_count} items · "
                      f"{len(live_tags)} tags · {len(live_words)} words",
                      flush=True)
            except Exception as e:
                print(f"[tag_generator] live failed: {e}", flush=True)

    aesthetic = _find_aesthetic_matches(name_words)
    colors = _color_matches(name_words)

    # ── SCORING: signal-weighted sum + multi-source bonus ──
    # Each source contributes to `combined` (weighted score) and
    # `source_count` (how many pools the tag appeared in).
    combined = Counter()
    source_count = Counter()

    signal_pools = [
        (top_tags, 1.5),
        (top_words, 1.0),
        (live_tags, 1.8),
        (live_words, 1.2),
        (search_phrases, 1.5),
        (search_words, 1.0),
        (category_wide, 0.4),
        (aesthetic, 1.2),
        (colors, 1.0),
    ]

    for pool, weight in signal_pools:
        for tag, score in pool.items():
            combined[tag] += score * weight
            source_count[tag] += 1

    for w in name_words:
        combined[w] += 5.0
        source_count[w] += 1

    # Multi-source bonus — tags appearing in 2+ pools get boosted
    for tag, cnt in source_count.items():
        if cnt >= 2:
            combined[tag] += 30.0 * (cnt - 1)

    name_word_set = set(name_words)

    def _is_acceptable(tag):
        if not _is_valid_word(tag):
            return False
        if len(tag) > 25:
            return False
        if tag in name_word_set:
            return True
        # Require 2+ source appearances OR category-wide presence
        # (which itself requires 3+ item appearances)
        if source_count[tag] >= 2:
            return True
        if tag in category_wide and category_wide[tag] >= 3.0:
            return True
        # Single-signal tags from name-matched sources still pass
        if tag in top_tags or tag in top_words:
            return True
        if tag in live_tags or tag in live_words:
            return True
        if tag in search_phrases or tag in search_words:
            return True
        if tag in aesthetic or tag in colors:
            return True
        return False

    filtered = {
        tag: score for tag, score in combined.items()
        if _is_acceptable(tag)
    }

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
            "top_seller_tags": len(top_tags),
            "top_seller_words": len(top_words),
            "search_phrases":  len(search_phrases),
            "search_words":    len(search_words),
            "category_wide":   len(category_wide),
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
        f"**📊 Signals mined (2+ sources = bonus weight):**\n"
        f"• Live Roblox top sellers: {live_str}\n"
        f"    – tag blocks: **{src.get('live_tag_blocks', 0)}**\n"
        f"    – word mining: **{src.get('live_words', 0)}**\n"
        f"• DB top-seller tags: **{src.get('top_seller_tags', 0)}**\n"
        f"• DB top-seller words: **{src.get('top_seller_words', 0)}**\n"
        f"• Search phrases: **{src.get('search_phrases', 0)}**\n"
        f"• Search words: **{src.get('search_words', 0)}**\n"
        f"• Category-wide: **{src.get('category_wide', 0)}**\n"
        f"• Aesthetic siblings: **{src['aesthetic']}**\n"
        f"• Color siblings: **{src['colors']}**\n"
        f"• Name words: **{src['name_words']}**\n"
        f"\n_Every tag traces to real data. 2+ source agreement = stronger signal._"
    )

    return chunks
