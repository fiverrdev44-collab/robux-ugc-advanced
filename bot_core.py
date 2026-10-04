"""
bot_core.py — shared state, config, helpers.
All command modules import from here.
"""
import os
import re
import math
import psycopg2
from collections import Counter, defaultdict

DATABASE_URL = os.getenv("DATABASE_URL")

STOP_WORDS = {
    "the","a","an","and","of","in","to","for","is","on","that","by","with",
    "from","as","it","at","be","or","no","not","but","all","are","was","were",
    "they","them","his","her","my","your","its","i","you","he","she","we","me",
    "us","our","new","one","if","so","up","out","just","can","also","do","get",
    "has","had","have","did","more","some","like","this","will","use","used",
    "very","much","many","make","made","would","could","should","may","might",
    "must","shall","than","then","there","here","when","where","why","how",
    "what","who","which","am","been","being","having",
    "http","https","www","com","net","org","roblox","catalog","category",
    "subcategory","creatorname","creator","keyword","keywords","group",
    "assetid","assettype","itemtype","item","id","href","link","url",
    "library","bundles","bundle","store","shop","search","results","page",
    "assets","asset","limited","unique","ugc","robux","free",
    "sale","sell","selling","buy","purchase","check",
    "community","join","follow","discord","twitter","instagram",
    "youtube","tiktok","social","socials","click","below","above",
    "version","update","updated","reupload","reuploaded","original","credit",
    "credits","inspired","based","similar","style","styles","design","designed",
    "really","actually","literally","basically","super","still","even",
    "ever","never","always","sometimes","maybe",
    "emoji","emojis","emoticon","emoticons","twemoji","twemojis"
}

SLANG_WORDS = {"rizz","skibidi","griddy","sigma","gyatt","mewing","ohio","fanum","sus","based","cringe","goat","slay","vibe","aura","flex","yeet","poggers","bruh","cap","bet","bussin","ratio"}
COLOR_WORDS = {"black","white","pink","blue","red","green","purple","yellow","orange","gold","silver","brown","beige","gray","grey","neon","cyan","magenta","crimson","aqua"}
STYLE_WORDS = {"emo","goth","y2k","pastel","kawaii","grunge","cyber","coquette","anime","dark","fluffy","preppy","streetwear","academia","vkei","harajuku","cottagecore","fairycore","vintage","retro","gothic","aesthetic","cottage","boho","hipster","punk","scene","soft"}
ITEM_WORDS = {"hat","beanie","crown","cap","hoodie","shirt","shoes","wing","wings","tail","ears","horn","horns","glasses","mask","necklace","chain","backpack","headphones","emote","dance","hair","face","pants","jacket","sword","pet","bag","purse","scarf","bandana","beret","visor","lens","ear","head","snapback","bonnet","balaclava"}

EMOTE_KEYWORDS_HINT = {
    "dance", "emote", "animation", "animate", "floss", "griddy", "wave", "dab",
    "shuffle", "moonwalk", "spin", "flip", "kick", "pose", "salute", "clap",
    "korean", "kpop", "k-pop", "gangnam", "russian", "renegade", "salsa",
    "ballet", "hiphop", "hip-hop", "breakdance", "twirl", "cartwheel",
    "greeting", "hello", "goodbye", "peace", "handshake", "hug",
    "sing", "rap", "beatbox", "meme", "fortnite", "skibidi", "sigma",
    "loop", "idle", "sit", "crouch", "sleep", "meditate",
    "cry", "laugh", "smile", "silly", "rage", "cheer", "victory",
    "run", "walk", "jump", "swim", "fly", "float", "levitate",
    "cat", "dog", "bunny", "bear", "panda", "fox", "wolf", "dragon",
    "krumping", "shmoney", "harlem", "dougie", "stanky", "leg", "whip",
    "milky", "smooth", "spin", "kick", "bounce", "hype", "party"
}

ASSET_TYPE_NAMES = {
    2: "T-Shirt", 8: "Hat", 11: "Shirt", 12: "Pants", 17: "Head",
    18: "Face", 19: "Gear", 41: "Hair", 42: "Face Acc", 43: "Neck Acc",
    44: "Shoulder Acc", 45: "Front Acc", 46: "Back Acc", 47: "Waist Acc",
    61: "Emote", 64: "3D T-Shirt", 65: "3D Shirt", 66: "3D Pants",
    67: "3D Jacket", 68: "3D Sweater", 69: "3D Shorts",
    70: "3D Shoe L", 71: "3D Shoe R", 72: "3D Dress",
}

FILLER_WORDS = {
    "troll", "funny", "meme", "memes", "lol", "sus", "sussy", "cringe",
    "goofy", "silly", "epic", "hype", "viral", "trending", "trend",
    "popular", "best", "top", "new", "old", "roblox", "ugc",
    "avatar", "outfit", "character", "got", "get", "make", "made",
    "use", "used", "has", "have",
}

MIN_PRICE = 5
MAX_PRICE = 10000


def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        sslmode='require',
        connect_timeout=10,
        options='-c statement_timeout=20000',
    )


def rollback_quietly(cur):
    try: cur.connection.rollback()
    except Exception: pass


def get_db_stats(cur):
    table_map = {
        "discovered": "discovered_items", "analyzed": "items",
        "snapshots": "item_history", "suggestions": "search_suggestions",
        "learned": "learned_keywords", "consultations": "saved_consultations",
    }
    stats = {}
    for key, table in table_map.items():
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            stats[key] = cur.fetchone()[0] or 0
        except Exception:
            rollback_quietly(cur)
            stats[key] = 0
    return stats


def extract_words(text):
    if not text: return []
    text = re.sub(r'http\S+|www\.\S+', ' ', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    words = re.findall(r"[a-zA-Z]+", text.lower())
    return [w for w in words if len(w) > 3 and w not in STOP_WORDS]


def word_boundary_pattern(word):
    return r'\m' + re.escape(word) + r'\M'


def matches_seed(text, seed):
    return re.search(r'\b' + re.escape(seed) + r'\b', text) is not None


def is_emote_word(cur, word):
    if word in EMOTE_KEYWORDS_HINT:
        return True
    try:
        pattern = word_boundary_pattern(word)
        cur.execute("""
            SELECT COUNT(*) FROM items
            WHERE name ~* %s AND asset_type_id = 61 AND favorite_count > 0
        """, (pattern,))
        count = cur.fetchone()[0] or 0
        return count >= 3
    except Exception:
        rollback_quietly(cur)
        return False


def classify_word(word):
    w = word.lower().strip()
    if w in SLANG_WORDS: return "slang"
    if w in COLOR_WORDS: return "color"
    if w in STYLE_WORDS: return "style"
    if w in ITEM_WORDS: return "item"
    if w in EMOTE_KEYWORDS_HINT: return "emote"
    if w.isdigit(): return "number"
    return "unknown"


def analyze_opportunity(cur, kw):
    """Big market scan. Returns dict of keywords, adjacent, styles, etc."""
    kw_words = [w for w in kw.lower().split() if len(w) >= 2]
    pattern = word_boundary_pattern(kw)
    is_emote_seed = any(is_emote_word(cur, w) for w in kw_words)

    all_items = []
    try:
        if is_emote_seed:
            cur.execute("""
                SELECT id, LOWER(name), COALESCE(LOWER(description), ''), 
                       favorite_count, price, creator_name
                FROM items
                WHERE (name ~* %s OR COALESCE(description, '') ~* %s)
                  AND favorite_count > 0
                  AND (asset_type_id = 61 OR asset_type_id IS NULL OR asset_type_id = 0)
                LIMIT 2000
            """, (pattern, pattern))
            all_items = cur.fetchall()
            if len(all_items) < 15:
                cur.execute("""
                    SELECT id, LOWER(name), COALESCE(LOWER(description), ''), 
                           favorite_count, price, creator_name
                    FROM items
                    WHERE (name ~* %s OR COALESCE(description, '') ~* %s)
                      AND favorite_count > 0 LIMIT 2000
                """, (pattern, pattern))
                all_items = cur.fetchall()
        else:
            cur.execute("""
                SELECT id, LOWER(name), COALESCE(LOWER(description), ''), 
                       favorite_count, price, creator_name
                FROM items
                WHERE (name ~* %s OR COALESCE(description, '') ~* %s)
                  AND favorite_count > 0 LIMIT 2000
            """, (pattern, pattern))
            all_items = cur.fetchall()
    except Exception as e:
        print(f"Exact phrase query failed: {e}", flush=True)
        rollback_quietly(cur)
        all_items = []

    used_fallback = False
    if len(all_items) < 15 and len(kw_words) > 1:
        combined = {}
        for w in kw_words:
            try:
                p = word_boundary_pattern(w)
                if is_emote_seed:
                    cur.execute("""
                        SELECT id, LOWER(name), COALESCE(LOWER(description), ''), 
                               favorite_count, price, creator_name
                        FROM items
                        WHERE (name ~* %s OR COALESCE(description, '') ~* %s)
                          AND favorite_count > 0
                          AND (asset_type_id = 61 OR asset_type_id IS NULL OR asset_type_id = 0)
                        LIMIT 2000
                    """, (p, p))
                else:
                    cur.execute("""
                        SELECT id, LOWER(name), COALESCE(LOWER(description), ''), 
                               favorite_count, price, creator_name
                        FROM items
                        WHERE (name ~* %s OR COALESCE(description, '') ~* %s)
                          AND favorite_count > 0 LIMIT 2000
                    """, (p, p))
                for row in cur.fetchall():
                    combined[row[0]] = row
            except Exception:
                rollback_quietly(cur)
        if combined and len(combined) > len(all_items):
            all_items = list(combined.values())
            used_fallback = True

    if not all_items:
        return None

    suggs = []
    try:
        cur.execute("""
            SELECT DISTINCT suggestion FROM search_suggestions 
            WHERE suggestion LIKE %s OR seed_keyword LIKE %s LIMIT 500
        """, (f"%{kw}%", f"%{kw}%"))
        for s in [r[0] for r in cur.fetchall()]:
            s = s.strip().lower()
            if not s or len(s) < 3 or len(s) > 40: continue
            if s in STOP_WORDS: continue
            if any(junk in s for junk in ["twee", "emoji", "emoticon"]): continue
            suggs.append(s)
        suggs = list(set(suggs))[:60]
    except Exception:
        rollback_quietly(cur)

    stats = defaultdict(lambda: {"favs": 0, "count": 0})

    for _, name, desc, favs, price, creator in all_items:
        for s in suggs:
            if matches_seed(name, s):
                stats[s]["favs"] += favs or 0
                stats[s]["count"] += 1

    for _, name, _, favs, _, _ in all_items:
        name_words = name.split()
        for i in range(len(name_words) - 1):
            bigram = f"{name_words[i]} {name_words[i+1]}"
            if 3 < len(bigram) < 40:
                stats[bigram]["favs"] += favs or 0
                stats[bigram]["count"] += 1

    seed_set = set(kw_words)
    single_counter = Counter()
    single_favs = defaultdict(int)
    for _, name, _, favs, _, _ in all_items:
        for w in set(extract_words(name)):
            if w in seed_set: continue
            single_counter[w] += 1
            single_favs[w] += favs or 0
    for w, count in single_counter.items():
        if w in stats: continue
        stats[w]["favs"] = single_favs[w]
        stats[w]["count"] = count

    min_occur = 1 if used_fallback and len(all_items) < 30 else 2
    top_keywords = []
    for s, data in stats.items():
        if data["count"] < min_occur: continue
        af = data["favs"] / data["count"]
        top_keywords.append((s, af, data["count"], af / math.log1p(data["count"])))
    top_keywords.sort(key=lambda x: x[3], reverse=True)
    top_keywords = top_keywords[:50]

    adjacent_counter = Counter()
    for _, name, desc, favs, _, _ in all_items:
        for w in set(extract_words(name)):
            if w not in seed_set and not matches_seed(w, kw):
                adjacent_counter[w] += 1
    adjacent = [w for w, c in adjacent_counter.most_common(60) if c >= 3]

    desc_counter = Counter()
    for _, _, desc, _, _, _ in all_items:
        desc_counter.update(extract_words(desc))
    desc_only = [w for w, c in desc_counter.most_common(60)
                 if w not in seed_set and w not in adjacent and c >= 2]

    prices = [p for _, _, _, _, p, _ in all_items if p and MIN_PRICE <= p <= MAX_PRICE]
    median_price = sorted(prices)[len(prices) // 2] if prices else 0
    top_items = sorted(all_items, key=lambda x: x[3] or 0, reverse=True)[:30]
    top_prices = [p for _, _, _, _, p, _ in top_items if p and MIN_PRICE <= p <= MAX_PRICE]
    best_price = sorted(top_prices)[len(top_prices) // 2] if top_prices else median_price

    creators = [c for _, _, _, _, _, c in all_items if c]
    unique_creators = len(set(creators))
    top_creator_counts = Counter(creators).most_common(1)
    top_creator_share = (top_creator_counts[0][1] / len(all_items) * 100) if top_creator_counts else 0

    total_competitors = len(all_items)
    if total_competitors < 20: saturation = "🟢 Low — untapped!"
    elif total_competitors < 100: saturation = "🟡 Medium — healthy"
    elif total_competitors < 500: saturation = "🟠 High — competitive"
    else: saturation = "🔴 Saturated — hard to rank"

    style_words = ["gothic","cute","emo","y2k","pastel","kawaii","grunge","cyber","coquette","anime","dark","light","fluffy","cyberpunk","retro","vintage","aesthetic","preppy","streetwear","cottagecore","fairycore","academia"]
    style_counts = Counter()
    for _, name, desc, _, _, _ in all_items:
        text = f"{name} {desc}"
        for style in style_words:
            if re.search(r'\b' + style + r'\b', text):
                style_counts[style] += 1
    top_styles = style_counts.most_common(8)
    study_items = sorted(all_items, key=lambda x: x[3] or 0, reverse=True)[:5]

    return {
        "seed": kw, "total_matches": len(all_items),
        "top_keywords": top_keywords, "adjacent": adjacent,
        "description_keywords": desc_only, "median_price": median_price,
        "best_price": best_price, "unique_creators": unique_creators,
        "top_creator_share": round(top_creator_share, 1),
        "saturation": saturation, "top_styles": top_styles,
        "study_items": study_items,
        "used_fallback": used_fallback,
        "is_emote_seed": is_emote_seed,
    }


# ── DB analysis helpers ──────────────────────────────────────
def _analyze_word(cur, word):
    pattern = word_boundary_pattern(word)
    cur.execute(f"""
        SELECT COUNT(*), AVG(favorite_count),
               AVG(CASE WHEN price BETWEEN {MIN_PRICE} AND {MAX_PRICE} THEN price END),
               PERCENTILE_CONT(0.5) WITHIN GROUP (
                   ORDER BY CASE WHEN price BETWEEN {MIN_PRICE} AND {MAX_PRICE} THEN price END)
        FROM items WHERE (name ~* %s OR COALESCE(description, '') ~* %s)
          AND favorite_count > 0
    """, (pattern, pattern))
    row = cur.fetchone()
    avg_price = row[2] or 0
    median_price = row[3] or avg_price
    return {"word": word, "count": row[0] or 0, "avg_favs": row[1] or 0,
            "avg_price": median_price or avg_price or 0}


def _analyze_combo(cur, words):
    if len(words) < 2:
        return {"count": 0, "avg_favs": 0, "avg_price": 0}
    conditions = " AND ".join(["name ~* %s"] * len(words))
    patterns = [word_boundary_pattern(w) for w in words]
    cur.execute(f"""SELECT COUNT(*), AVG(favorite_count),
                           AVG(CASE WHEN price BETWEEN {MIN_PRICE} AND {MAX_PRICE} THEN price END)
                    FROM items WHERE {conditions} AND favorite_count > 0""", tuple(patterns))
    row = cur.fetchone()
    return {"count": row[0] or 0, "avg_favs": row[1] or 0, "avg_price": row[2] or 0}


def _get_adjacent_for(cur, word, limit=15):
    pattern = word_boundary_pattern(word)
    cur.execute("""SELECT name FROM items WHERE name ~* %s AND favorite_count > 100 LIMIT 200""", (pattern,))
    rows = cur.fetchall()
    counter = Counter()
    for (name,) in rows:
        for w in set(extract_words(name)):
            if w != word and not matches_seed(w, word):
                counter[w] += 1
    return [w for w, c in counter.most_common(limit * 2) if c >= 2][:limit]


def _find_alternatives(cur, modifier, item_type, limit=6):
    pattern = word_boundary_pattern(item_type)
    cur.execute("""SELECT name FROM items WHERE name ~* %s AND favorite_count > 100 LIMIT 200""", (pattern,))
    rows = cur.fetchall()
    counter = Counter()
    for (name,) in rows:
        for w in set(extract_words(name)):
            if w != item_type and not matches_seed(w, item_type):
                counter[w] += 1
    alternatives = []
    for w, c in counter.most_common(30):
        if w == modifier.lower() or c < 2: continue
        try:
            stats = _analyze_word(cur, w)
        except Exception:
            rollback_quietly(cur)
            continue
        if stats["avg_favs"] > 1000:
            alternatives.append({"word": w, "count": c, "avg_favs": stats["avg_favs"]})
        if len(alternatives) >= limit: break
    return alternatives


def smart_verdict(word_stats, combo_stats):
    total_usage = sum(w["count"] for w in word_stats)
    top_avg = max((w["avg_favs"] for w in word_stats), default=0)
    combo_count = combo_stats["count"] if combo_stats else 0

    if total_usage == 0:
        return ("🟡", "EARLY BIRD", "None of these words appear in my database yet.")
    if combo_count == 0 and total_usage > 0:
        if top_avg > 50000:
            return ("🔥", "FIRST-MOVER GOLDMINE", f"No item combines these words — but individually they're proven winners (top word averages {top_avg:,.0f} favs).")
        elif top_avg > 10000:
            return ("🟢", "UNTAPPED COMBO", "No combo exists yet, but words have solid demand.")
        return ("🟡", "UNTESTED", "No item combines these words.")
    if combo_count < 10:
        if combo_stats["avg_favs"] > 10000:
            return ("🔥", "JACKPOT", f"Only **{combo_count}** items — averaging **{combo_stats['avg_favs']:,.0f}** favs.")
        return ("🟢", "UNTAPPED NICHE", f"Only {combo_count} items exist.")
    if combo_count < 50: return ("🟡", "SWEET SPOT", f"{combo_count} items — proven demand.")
    if combo_count < 200: return ("🟠", "COMPETITIVE", f"{combo_count} items.")
    return ("🔴", "SATURATED", f"{combo_count} items.")


def build_strategy(verdict, word_stats, combo_stats, adjacent, alternatives, data):
    emoji, label, _ = verdict
    lines = []
    if emoji == "🔥":
        lines = ["**ATTACK NOW.** Rare opportunity.", "• Design an exceptional item",
                 "• Use the exact combo in title"]
        if data: lines.append(f"• Price around **{data['best_price']} R$**")
        lines.append("• Upload ASAP")
    elif emoji == "🟢":
        lines = ["**GREEN LIGHT.** Solid opportunity.", "• Use top 2 keywords in title"]
        if alternatives: lines.append(f"• Add `{alternatives[0]['word']}` for reach")
        if data: lines.append(f"• Price between **{data['median_price']}–{data['best_price']} R$**")
    elif emoji == "🟡":
        lines = ["**TEST IT.** Moderate signal.", "• Add modifiers", "• Study rivals"]
    elif emoji == "🟠":
        lines = ["**DIFFERENTIATE.** Crowded but winnable.", "• Add unique style combo"]
        if alternatives: lines.append(f"• Try `{alternatives[0]['word']}` instead")
    else:
        lines = ["**PIVOT.** Too saturated."]
        if alternatives: lines.append(f"• Switch to `{alternatives[0]['word']}`")
    return "\n".join(lines)


def get_timing_intelligence(cur, keyword):
    pattern = word_boundary_pattern(keyword)
    cur.execute("""SELECT created_at FROM items WHERE name ~* %s 
                   AND favorite_count > 1000 AND created_at IS NOT NULL LIMIT 200""", (pattern,))
    rows = cur.fetchall()
    if not rows or len(rows) < 5: return None
    day_counts = Counter(); hour_counts = Counter()
    for (ts,) in rows:
        try:
            if isinstance(ts, str): continue
            day_counts[ts.strftime("%A")] += 1
            hour_counts[ts.hour] += 1
        except Exception: continue
    if not day_counts: return None
    return {"best_day": day_counts.most_common(1)[0][0],
            "best_hours": [f"{h}:00" for h, _ in hour_counts.most_common(3)]}


def get_launch_window(cur, keyword):
    pattern = word_boundary_pattern(keyword)
    cur.execute("SELECT item_id FROM items WHERE name ~* %s AND favorite_count > 0 LIMIT 200", (pattern,))
    ids = [r[0] for r in cur.fetchall()]
    if not ids: return "🟢 No trend data — safe to launch anytime"
    cur.execute("""SELECT MAX(snapshot_at) - MIN(snapshot_at), AVG(favorite_count),
                          MAX(favorite_count), MIN(favorite_count)
                   FROM item_history WHERE item_id = ANY(%s)""", (ids,))
    row = cur.fetchone()
    if not row or not row[0]: return "🟢 Launch ASAP for first-mover advantage"
    growth = (row[2] or 0) - (row[3] or 0)
    if growth > 5000: return "🔥 **HOT NOW** — launch within 48h"
    elif growth > 500: return "📈 **Rising** — launch within 1-2 weeks"
    elif growth > 0: return "➡️ **Steady** — launch anytime"
    return "📉 **Cooling** — consider pivot or variant"


def get_niche_graph(cur, keyword, depth=1, top_per_level=8):
    return {"level_1": _get_adjacent_for(cur, keyword, limit=top_per_level), "level_2": {}}


def get_creator_dominance(cur, keyword):
    pattern = word_boundary_pattern(keyword)
    cur.execute("""SELECT creator_name, COUNT(*), SUM(favorite_count)
                   FROM items WHERE name ~* %s AND favorite_count > 0 AND creator_name IS NOT NULL
                   GROUP BY creator_name ORDER BY 3 DESC LIMIT 5""", (pattern,))
    return cur.fetchall()


def generate_ab_titles(idea, words, combo_stats, alternatives, adjacent, data):
    titles = []
    if combo_stats and combo_stats["count"] > 0:
        titles.append({"title": " ".join(w.capitalize() for w in words)[:80],
                       "strategy": "Proven combo", "predicted": "🟢 High",
                       "why": f"Matches {combo_stats['count']} existing items"})
    else:
        titles.append({"title": " ".join(w.capitalize() for w in words)[:80],
                       "strategy": "First-mover", "predicted": "🟡 Medium",
                       "why": "No existing combo"})
    if alternatives:
        alt = alternatives[0]["word"]
        rest = " ".join(w.capitalize() for w in words[1:]) if len(words) > 1 else ""
        titles.append({"title": f"{alt.capitalize()} {rest}".strip()[:80],
                       "strategy": "Proven alternative", "predicted": "🟢 High",
                       "why": f"`{alt}` averages {alternatives[0]['avg_favs']:,.0f} favs"})
    if adjacent and len(adjacent) >= 2:
        titles.append({"title": f"{words[0].capitalize()} {words[-1].capitalize()} – {adjacent[0].capitalize()} {adjacent[1].capitalize()}"[:80],
                       "strategy": "Long-tail SEO", "predicted": "🟢 High",
                       "why": "Targets 4 keywords"})
    return titles


def _compute_roi(data, combo_stats, word_stats):
    if not data: return None
    combo_count = combo_stats["count"] if combo_stats else 0
    best_price = data.get("best_price", 0) or 100
    top_avg = max((w["avg_favs"] for w in word_stats), default=0)
    if combo_count > 0 and combo_stats["avg_favs"] > 0:
        expected_favs = combo_stats["avg_favs"] * 0.4
    elif top_avg > 0:
        expected_favs = top_avg * 0.15
    else:
        expected_favs = 0
    favs_per_sale = 30 if best_price < 100 else 100 if best_price < 300 else 200
    expected_sales = expected_favs / favs_per_sale if favs_per_sale > 0 else 0
    expected_revenue = expected_sales * best_price * 0.7
    if combo_count < 10: conf = "🟢 High"
    elif combo_count < 50: conf = "🟡 Medium"
    elif combo_count < 200: conf = "🟠 Low"
    else: conf = "🔴 Very Low"
    return {"expected_favs": int(expected_favs), "expected_sales": int(expected_sales),
            "expected_revenue": int(expected_revenue), "confidence": conf, "best_price": best_price}


def _assess_risk(word_stats, combo_stats, data, trend_data):
    risks = []
    combo_count = combo_stats["count"] if combo_stats else 0
    if combo_count > 200:
        risks.append(("🔴", "Market saturation", "Try niche modifier"))
    elif combo_count > 50:
        risks.append(("🟠", "Medium competition", "Differentiate or undercut by 15%"))
    if combo_count == 0 and word_stats:
        top_avg = max(w["avg_favs"] for w in word_stats)
        if top_avg < 5000:
            risks.append(("🔴", "Unproven demand", "Test with a cheaper variant first"))
    if trend_data and trend_data.get("avg_growth") is not None:
        g = trend_data["avg_growth"]
        if g < -50: risks.append(("🔴", "Fading trend", "Pivot"))
        elif g < 0: risks.append(("🟡", "Slightly declining", "Move fast"))
    if data and data["top_creator_share"] > 25:
        risks.append(("🟠", f"Creator dominance ({data['top_creator_share']}%)", "Study their design"))
    if data and data["median_price"] > 0 and data["best_price"] > data["median_price"] * 2:
        risks.append(("🟡", "Price sensitivity", "Price below median"))
    if not risks:
        risks.append(("🟢", "No major risks detected", "Solid opportunity — execute cleanly"))
    return risks


def _get_trend_signal(cur, word):
    pattern = word_boundary_pattern(word)
    cur.execute("SELECT item_id FROM items WHERE name ~* %s AND favorite_count > 0 LIMIT 100", (pattern,))
    ids = [r[0] for r in cur.fetchall()]
    if not ids: return None
    cur.execute("""SELECT AVG(growth), COUNT(*) FROM (
                       SELECT item_id, MAX(favorite_count) - MIN(favorite_count) AS growth
                       FROM item_history WHERE item_id = ANY(%s)
                       GROUP BY item_id HAVING COUNT(*) >= 2) sub""", (ids,))
    row = cur.fetchone()
    if not row or row[0] is None: return None
    return {"avg_growth": row[0], "tracked": row[1]}


def _generate_portfolio(cur, seed, alternatives, adjacent, data):
    portfolio = [{"angle": "Flagship", "idea": seed, "why": "Core concept"}]
    last_word = seed.split()[-1] if len(seed.split()) > 1 else seed
    for alt in alternatives[:2]:
        portfolio.append({"angle": "Alternative", "idea": f"{alt['word']} {last_word}",
                          "why": f"Proven ({alt['avg_favs']:,.0f} avg favs)"})
    for adj in adjacent[:2]:
        if len(adj) > 3 and adj not in seed and classify_word(adj) not in ("slang", "number"):
            portfolio.append({"angle": "Adjacent", "idea": f"{adj} {last_word}",
                              "why": "Natural keyword extension"})
    return portfolio[:5]


def _analyze_rivals(cur, seed, top_n=3):
    pattern = word_boundary_pattern(seed)
    cur.execute("""SELECT id, name, favorite_count, price, creator_name
                   FROM items WHERE name ~* %s AND favorite_count > 0
                   ORDER BY favorite_count DESC LIMIT %s""", (pattern, top_n))
    return cur.fetchall()


def _optimize_price(data, combo_stats, word_stats):
    if not data: return []
    median = data.get("median_price", 0) or 100
    best = data.get("best_price", 0) or median
    return [
        {"name": "🟢 Aggressive", "price": int(median * 0.7),
         "pro": "Undercut competitors.", "con": "Lower margin."},
        {"name": "🎯 Sweet Spot", "price": int(best),
         "pro": "Matches best-sellers.", "con": "Standard competition."},
        {"name": "💎 Premium", "price": int(best * 1.5),
         "pro": "Max per-sale profit.", "con": "Slower sales."}
    ]


def _make_design_brief(idea, word_stats, adjacent, data):
    lines = [f"**Concept:** {idea.title()}"]
    colors_in_idea = [w for w in idea.split() if classify_word(w) == "color"]
    if colors_in_idea:
        lines.append(f"**Color:** {', '.join(colors_in_idea)}")
    else:
        colors = [w for w in adjacent if classify_word(w) == "color"][:2]
        if colors: lines.append(f"**Suggested color:** {', '.join(colors)}")
    styles_in_idea = [w for w in idea.split() if classify_word(w) == "style"]
    if styles_in_idea: lines.append(f"**Style:** {', '.join(styles_in_idea)}")
    if data and data.get("top_styles"):
        top = [s for s, _ in data["top_styles"][:3]]
        lines.append(f"**Popular styles:** {', '.join(top)}")
    if adjacent:
        details = [w for w in adjacent if classify_word(w) not in ("color", "style", "slang")][:5]
        if details: lines.append(f"**Details:** {', '.join(details)}")
    return "\n".join(lines)


def build_full_report(session, verdict, roi, risks, pricing, portfolio, design, timing, window, ab_titles, graph, dominance):
    from datetime import datetime
    emoji, label, explanation = verdict
    lines = ["=" * 60, f"UGC CONSULTATION REPORT — {session.seed.upper()}",
             f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", "=" * 60, "",
             f"VERDICT: {emoji} {label}", explanation]
    for w in session.word_stats:
        lines.append(f"  {w['word']}: {w['count']} items, avg {w['avg_favs']:,.0f} favs")
    if session.combo_stats:
        lines.append(f"COMBO: {session.combo_stats['count']} items")
    for icon, risk, mit in risks:
        lines.append(f"  {icon} {risk} → {mit}")
    if roi:
        lines.extend([f"  Expected favs: {roi['expected_favs']:,}",
                      f"  Expected revenue: {roi['expected_revenue']:,} R$"])
    if pricing:
        for p in pricing:
            lines.append(f"  {p['name']} — {p['price']} R$")
    if portfolio:
        for i, item in enumerate(portfolio, 1):
            lines.append(f"  {i}. [{item['angle']}] {item['idea']}")
    if ab_titles:
        for t in ab_titles:
            lines.append(f'  "{t["title"]}"')
    if design:
        for line in design.split("\n"):
            lines.append(f"  {line}")
    if timing:
        lines.append(f"  Best day: {timing['best_day']}")
    if window: lines.append(f"LAUNCH WINDOW: {window}")
    if dominance:
        for creator, cnt, total_favs in dominance:
            lines.append(f"  {creator}: {cnt} items")
    lines.extend(["", "=" * 60, "END OF REPORT", "=" * 60])
    return "\n".join(lines)


# ── User profile helpers ─────────────────────────────────────
def get_or_create_profile(cur, discord_id, username):
    cur.execute("""INSERT INTO user_profiles (discord_id, username, last_active)
                   VALUES (%s, %s, CURRENT_TIMESTAMP)
                   ON CONFLICT (discord_id) DO UPDATE SET
                       username = EXCLUDED.username, last_active = CURRENT_TIMESTAMP
                   RETURNING total_consultations, first_seen""", (discord_id, username))
    row = cur.fetchone()
    return {"total_consultations": row[0] or 0, "first_seen": row[1]}


def increment_consultations(cur, discord_id):
    cur.execute("UPDATE user_profiles SET total_consultations = total_consultations + 1 WHERE discord_id = %s", (discord_id,))


def save_consultation(cur, discord_id, seed, verdict, report_text):
    emoji, label, _ = verdict
    cur.execute("""INSERT INTO saved_consultations (discord_id, seed, verdict_label, verdict_emoji, full_report)
                   VALUES (%s, %s, %s, %s, %s)""", (discord_id, seed, label, emoji, report_text))


def get_past_consultations(cur, discord_id, limit=5):
    cur.execute("""SELECT seed, verdict_label, verdict_emoji, created_at
                   FROM saved_consultations WHERE discord_id = %s
                   ORDER BY created_at DESC LIMIT %s""", (discord_id, limit))
    return cur.fetchall()


def add_to_watchlist(cur, discord_id, keyword, baseline_favs=0):
    cur.execute("""INSERT INTO watchlist (discord_id, keyword, baseline_favs)
                   VALUES (%s, %s, %s) ON CONFLICT (discord_id, keyword) DO NOTHING
                   RETURNING id""", (discord_id, keyword, baseline_favs))
    return cur.fetchone() is not None
