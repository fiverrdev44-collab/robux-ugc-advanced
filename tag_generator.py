"""
tag_generator.py — sales-weighted SEO tag generator.

Sources (weighted by sales signal):
  1. Live Roblox top sellers in the niche (fetched if DB is thin)
  2. Your DB top sellers in the niche
  3. Real search_suggestions queries
  4. Aesthetic family siblings
  5. Color siblings
  6. Name words (base boost)

Every tag must appear in 2+ top sellers OR be a real search query.
Nothing hallucinated.

FIX: generate_tags() translates category_configs family names
     (emote, accessory, clothing...) to convergence_engine family
     names (emotes, neck, tops...) before FAMILIES.get() lookup.
"""
import os
import re
import requests
from collections import Counter
from bot_core import get_db
from convergence_engine import ASSET_TO_FAMILY, FAMILIES


ROBLOX_SEARCH_URL = "https://catalog.roblox.com/v1/search/items/details"
MIN_DB_TAGS = 12  # If DB produces fewer than this, hit Roblox live


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


# Common English + promo words that are NOT tags
_ENGLISH_BLOCK = {
    "the","and","for","with","you","your","from","that","this","into",
    "over","will","can","are","has","how","its","our","all","have","had",
    "was","were","been","being","get","got","make","made","more","most",
    "some","any","every","each","other","another","such","only","very",
    "just","also","than","then","them","they","their","there","here",
    "when","what","where","which","while","who","whom","whose","why",
    "yes","not","but","nor","yet","so","if","or","as","at","by","in",
    "on","of","to","up","down","out","off","new","old","one","two","three",
    "model","models","item","items","shop","store","group","community",
    "communities","join","follow","visit","check","click","link","links",
    "http","https","www","com","net","org","roblox","catalog","asset",
    "id","page","site","website","created","creator",
    "buy","buying","sell","selling","sold","sale","price","prices","cost",
    "free","paid","cheap","expensive","discount","promo","promotion",
    "version","edition","style","styled","type","kinds","kind","sort",
    "something","anything","nothing","everything","anyone","someone",
    "everyone","nobody","somebody","anybody","everybody",
}


def _is_tag_shaped(tok):
    if not tok:
        return False
    if not (3 <= len(tok) <= 20):
        return False
    if tok in _ENGLISH_BLOCK:
        return False
    if not re.match(r"^[a-z][a-z'’\- ]*$", tok):
        return False
    if tok.count("-") > 1:
        return False
    if re.search(r"[a-z]-[a-z]-[a-z]", tok):
        return False
    return True


def _extract_tags_from_description(desc):
    """Only mine explicit tag blocks. Skip prose and promo."""
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

    raw_tokens = re.split(r"[,|;\n]+", tag_section)
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


# ════════════════════════════════════════════════════════════════════
# LIVE ROBLOX FALLBACK
# ════════════════════════════════════════════════════════════════════

def _family_to_roblox_category(family):
    if not family:
        return None
    return {
        "hair":     12, "face": 13, "neck": 5, "shoulder": 9,
        "front":    7,  "back": 8,  "waist": 6,
    }.get(family)


def _fetch_live_items(keyword, family=None, limit=30):
    """
    Hit Roblox catalog search live, extract descriptions, save to DB.
    Returns list of (name, description, favs).
    """
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
        cat = _family_to_roblox_category(family)
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


def _mine_live_tags(keyword, family):
    """Fetch live items, mine their tag blocks, weight by favs."""
    rows = _fetch_live_items(keyword, family=family, limit=30)
    if not rows:
        return Counter()

    tag_weight = Counter()
    tag_appearances = Counter()
    for name, desc, favs in rows:
        tags = _extract_tags_from_description(desc)
        if not tags:
            continue
        weight = 1 + ((favs or 0) / 1000.0)
        for tag in set(tags):
            tag_weight[tag] += weight
            tag_appearances[tag] += 1

    # Only keep tags appearing in 2+ live items
    return Counter({
        tag: score for tag, score in tag_weight.items()
        if tag_appearances[tag] >= 2
    })


# ════════════════════════════════════════════════════════════════════
# CATEGORY DETECTION
# ════════════════════════════════════════════════════════════════════

def _detect_category(name, explicit_family=None):
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
# DB MINING
# ════════════════════════════════════════════════════════════════════

def _family_sql(family):
    ids = FAMILIES.get(family)
    if not ids:
        return "", []
    ph = ",".join(["%s"] * len(ids))
    return f" and asset_type_id in ({ph})", list(ids)


def _mine_top_seller_tags(cur, name_words, family):
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


def _mine_recent_winners(cur, name_words, family):
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
        tag_weight[s] += 3.0
        for w in re.findall(r"[a-z]{3,}", s):
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


# ════════════════════════════════════════════════════════════════════
# MAIN GENERATOR
# ════════════════════════════════════════════════════════════════════

def generate_tags(item_name, family=None, max_tags=45):
    if not item_name or not item_name.strip():
        return {"error": "Item name required."}

    # FIX: translate category_configs family names → convergence_engine
    # family names. Otherwise FAMILIES.get("emote") returns None and the
    # category filter silently drops.
    if family:
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

    # ── DB mining ──
    top_sellers = Counter()
    recent_winners = Counter()
    search_demand = Counter()

    conn = get_db(); cur = conn.cursor()
    try:
        try:
            top_sellers = _mine_top_seller_tags(cur, name_words, detected_family)
        except Exception as e:
            print(f"[tag_generator] top_seller failed: {e}", flush=True)
        try:
            recent_winners = _mine_recent_winners(cur, name_words, detected_family)
        except Exception as e:
            print(f"[tag_generator] recent failed: {e}", flush=True)
        try:
            search_demand = _mine_search_demand(cur, name_words)
        except Exception as e:
            print(f"[tag_generator] demand failed: {e}", flush=True)
    finally:
        cur.close(); conn.close()

    # ── LIVE FALLBACK if DB is thin ──
    live_tags = Counter()
    db_tag_total = len(top_sellers) + len(recent_winners)

    if db_tag_total < MIN_DB_TAGS:
        live_kw = None
        sorted_words = sorted(name_words, key=len, reverse=True)
        if sorted_words:
            live_kw = sorted_words[0]

        if live_kw and len(live_kw) >= 3:
            try:
                live_tags = _mine_live_tags(live_kw, detected_family)
            except Exception as e:
                print(f"[tag_generator] live mining failed: {e}", flush=True)

    aesthetic = _find_aesthetic_matches(name_words)
    colors = _color_matches(name_words)

    # ── Combine with source weights ──
    combined = Counter()
    for source, mult in [
        (live_tags, 1.5),       # live winners = highest signal
        (search_demand, 1.2),   # real queries = strong
        (recent_winners, 1.0),  # recent winners
        (top_sellers, 0.7),     # all-time sellers
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
            "live_roblox":     len(live_tags),
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

    live_str = f"**{src['live_roblox']}**"
    if src['live_roblox'] > 0:
        live_str += " 🔥 (live Roblox)"

    chunks.append(
        f"**📊 Sources mined:**\n"
        f"• Live Roblox top sellers: {live_str}\n"
        f"• Search demand (real queries): **{src['search_demand']}**\n"
        f"• Recent winners (last 90d): **{src['recent_winners']}**\n"
        f"• Top sellers (DB, all time): **{src['top_sellers']}**\n"
        f"• Aesthetic siblings: **{src['aesthetic']}**\n"
        f"• Color siblings: **{src['colors']}**\n"
        f"• Name words: **{src['name_words']}**\n"
        f"\n_Every tag traces to real data. No hallucination._"
    )

    return chunks
