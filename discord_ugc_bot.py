import os
import threading
import asyncio
import io
import time
import discord
from discord.ext import commands
from datetime import datetime
import psycopg2
import math
import re
from flask import Flask
from collections import Counter, defaultdict

TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

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

EMOTE_KEYWORDS_HINT = {"dance", "emote", "floss", "griddy", "wave", "dab", "shuffle",
                       "moonwalk", "spin", "flip", "kick", "pose", "salute", "clap"}

MIN_PRICE = 5
MAX_PRICE = 10000


def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode='require')


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


async def safe_send(ctx, embed=None, content=None, label=""):
    for attempt in range(2):
        try:
            if embed is not None:
                await ctx.send(embed=embed)
            else:
                await ctx.send(content)
            return True
        except discord.HTTPException as e:
            print(f"⚠️ HTTP error {label} ({attempt+1}): {e}", flush=True)
            if attempt == 0:
                await asyncio.sleep(3)
                continue
            return False
        except Exception as e:
            print(f"❌ Failed {label}: {e}", flush=True)
            return False
    return False


def extract_words(text):
    if not text:
        return []
    text = re.sub(r'http\S+|www\.\S+', ' ', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    words = re.findall(r"[a-zA-Z]+", text.lower())
    return [w for w in words if len(w) > 3 and w not in STOP_WORDS]


def word_boundary_pattern(word):
    return r'\m' + re.escape(word) + r'\M'


def matches_seed(text, seed):
    return re.search(r'\b' + re.escape(seed) + r'\b', text) is not None


def classify_word(word):
    w = word.lower().strip()
    if w in SLANG_WORDS: return "slang"
    if w in COLOR_WORDS: return "color"
    if w in STYLE_WORDS: return "style"
    if w in ITEM_WORDS: return "item"
    if w in EMOTE_KEYWORDS_HINT: return "emote"
    if w.isdigit(): return "number"
    return "unknown"


# ============================================================
# SMART OPPORTUNITY ANALYSIS — multi-word fallback + single-word extraction
# ============================================================
def analyze_opportunity(cur, kw):
    """Smart analysis:
       1. Try exact phrase
       2. If < 15 matches and multi-word, try each word individually
       3. Extract keywords from suggestions + bigrams + single words
    """
    kw_words = [w for w in kw.lower().split() if len(w) >= 2]
    pattern = word_boundary_pattern(kw)

    # ---- STEP 1: Try exact phrase ----
    all_items = []
    try:
        cur.execute("""
            SELECT id, LOWER(name), COALESCE(LOWER(description), ''), 
                   favorite_count, price, creator_name
            FROM items
            WHERE (name ~* %s OR COALESCE(description, '') ~* %s)
              AND favorite_count > 0
            LIMIT 2000
        """, (pattern, pattern))
        all_items = cur.fetchall()
    except Exception as e:
        print(f"Exact phrase query failed: {e}", flush=True)
        rollback_quietly(cur)
        all_items = []

    # ---- STEP 2: Multi-word fallback — combine individual word matches ----
    used_fallback = False
    if len(all_items) < 15 and len(kw_words) > 1:
        combined = {}
        for w in kw_words:
            try:
                p = word_boundary_pattern(w)
                cur.execute("""
                    SELECT id, LOWER(name), COALESCE(LOWER(description), ''), 
                           favorite_count, price, creator_name
                    FROM items
                    WHERE (name ~* %s OR COALESCE(description, '') ~* %s)
                      AND favorite_count > 0
                    LIMIT 2000
                """, (p, p))
                for row in cur.fetchall():
                    combined[row[0]] = row
            except Exception as e:
                print(f"Word '{w}' query failed: {e}", flush=True)
                rollback_quietly(cur)
        if combined and len(combined) > len(all_items):
            all_items = list(combined.values())
            used_fallback = True

    if not all_items:
        return None

    # ---- STEP 3: Get search suggestions ----
    suggs = []
    try:
        cur.execute("""
            SELECT DISTINCT suggestion FROM search_suggestions 
            WHERE suggestion LIKE %s OR seed_keyword LIKE %s LIMIT 500
        """, (f"%{kw}%", f"%{kw}%"))
        candidates = [r[0] for r in cur.fetchall()]
        for s in candidates:
            s = s.strip().lower()
            if not s or len(s) < 3 or len(s) > 40: continue
            if s in STOP_WORDS: continue
            if any(junk in s for junk in ["twee", "emoji", "emoticon"]): continue
            suggs.append(s)
        suggs = list(set(suggs))[:60]
    except Exception as e:
        print(f"Suggestions query failed: {e}", flush=True)
        rollback_quietly(cur)

    # ---- STEP 4: Build keyword stats from multiple sources ----
    stats = defaultdict(lambda: {"favs": 0, "count": 0})

    # Source A: Suggestions matched against titles
    for _, name, desc, favs, price, creator in all_items:
        for s in suggs:
            if matches_seed(name, s):
                stats[s]["favs"] += favs or 0
                stats[s]["count"] += 1

    # Source B: Bigrams from titles
    for _, name, _, favs, _, _ in all_items:
        name_words = name.split()
        for i in range(len(name_words) - 1):
            bigram = f"{name_words[i]} {name_words[i+1]}"
            if 3 < len(bigram) < 40:
                stats[bigram]["favs"] += favs or 0
                stats[bigram]["count"] += 1

    # Source C: Single words from titles (NEW)
    seed_set = set(kw_words)
    single_word_counter = Counter()
    single_word_favs = defaultdict(int)
    for _, name, _, favs, _, _ in all_items:
        for w in set(extract_words(name)):
            if w in seed_set:
                continue
            single_word_counter[w] += 1
            single_word_favs[w] += favs or 0

    # Merge single words into stats (bigrams take precedence)
    for w, count in single_word_counter.items():
        if w in stats:
            continue
        stats[w]["favs"] = single_word_favs[w]
        stats[w]["count"] = count

    # ---- STEP 5: Rank keywords ----
    # For multi-word fallback: relax threshold
    min_occur = 1 if used_fallback and len(all_items) < 30 else 2
    top_keywords = []
    for s, data in stats.items():
        if data["count"] < min_occur: continue
        af = data["favs"] / data["count"]
        top_keywords.append((s, af, data["count"], af / math.log1p(data["count"])))
    top_keywords.sort(key=lambda x: x[3], reverse=True)
    top_keywords = top_keywords[:50]

    # ---- STEP 6: Adjacent keywords ----
    adjacent_counter = Counter()
    for _, name, desc, favs, _, _ in all_items:
        for w in set(extract_words(name)):
            if w not in seed_set and not matches_seed(w, kw):
                adjacent_counter[w] += 1
    adjacent = [w for w, c in adjacent_counter.most_common(60) if c >= 3]

    # ---- STEP 7: Description keywords ----
    desc_counter = Counter()
    for _, _, desc, _, _, _ in all_items:
        desc_counter.update(extract_words(desc))
    desc_only = [w for w, c in desc_counter.most_common(60)
                 if w not in seed_set and w not in adjacent and c >= 2]

    # ---- STEP 8: Prices ----
    prices = [p for _, _, _, _, p, _ in all_items if p and MIN_PRICE <= p <= MAX_PRICE]
    median_price = sorted(prices)[len(prices) // 2] if prices else 0
    top_items = sorted(all_items, key=lambda x: x[3] or 0, reverse=True)[:30]
    top_prices = [p for _, _, _, _, p, _ in top_items if p and MIN_PRICE <= p <= MAX_PRICE]
    best_price = sorted(top_prices)[len(top_prices) // 2] if top_prices else median_price

    # ---- STEP 9: Creator stats ----
    creators = [c for _, _, _, _, _, c in all_items if c]
    unique_creators = len(set(creators))
    top_creator_counts = Counter(creators).most_common(1)
    top_creator_share = (top_creator_counts[0][1] / len(all_items) * 100) if top_creator_counts else 0

    total_competitors = len(all_items)
    if total_competitors < 20: saturation = "🟢 Low — untapped!"
    elif total_competitors < 100: saturation = "🟡 Medium — healthy"
    elif total_competitors < 500: saturation = "🟠 High — competitive"
    else: saturation = "🔴 Saturated — hard to rank"

    # ---- STEP 10: Style patterns ----
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
    }


class MultiViewPaginator(discord.ui.View):
    def __init__(self, data):
        super().__init__(timeout=300)
        self.data = data
        self.view_mode = "keywords"
        self.page = 0
        self.per_page = 8
        self.rebuild_buttons()

    def build_embed(self):
        d = self.data
        seed = d["seed"]
        if self.view_mode == "keywords":
            items = d["top_keywords"]
            max_page = max(0, (len(items) - 1) // self.per_page)
            self.page = min(self.page, max_page)
            start = self.page * self.per_page
            chunk = items[start:start + self.per_page]
            embed = discord.Embed(title=f"🎯 Keywords for `{seed}`",
                                  description=f"Showing **{start+1}–{min(start+self.per_page, len(items))}** of **{len(items)}**.",
                                  color=0x00ff88)
            for i, (w, af, c, sc) in enumerate(chunk, start + 1):
                embed.add_field(name=f"{i}. {w}",
                                value=f"Score: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Comp: **{c:,}**",
                                inline=False)
            embed.set_footer(text=f"Page {self.page+1}/{max_page+1}")
        elif self.view_mode == "adjacent":
            adjs = d["adjacent"]
            embed = discord.Embed(title=f"🔗 Adjacent Keywords for `{seed}`",
                                  description="Words alongside your seed.", color=0x66ccff)
            if adjs:
                half = (len(adjs) + 1) // 2
                left = " · ".join(f"`{w}`" for w in adjs[:half])
                right = " · ".join(f"`{w}`" for w in adjs[half:])
                if left: embed.add_field(name="\u200b", value=left, inline=True)
                if right: embed.add_field(name="\u200b", value=right, inline=True)
            else:
                embed.add_field(name="No adjacent keywords", value="Try a broader seed.", inline=False)
        elif self.view_mode == "description":
            descs = d["description_keywords"]
            embed = discord.Embed(title=f"📝 Hidden Description Keywords for `{seed}`",
                                  description="SEO words buried in descriptions.", color=0xaa66ff)
            if descs:
                half = (len(descs) + 1) // 2
                left = " · ".join(f"`{w}`" for w in descs[:half])
                right = " · ".join(f"`{w}`" for w in descs[half:])
                if left: embed.add_field(name="\u200b", value=left, inline=True)
                if right: embed.add_field(name="\u200b", value=right, inline=True)
            else:
                embed.add_field(name="No description keywords", value="Try a different seed.", inline=False)
        elif self.view_mode == "market":
            embed = discord.Embed(title=f"💰 Market Info for `{seed}`",
                                  description="Competitive intelligence.", color=0xffaa00)
            embed.add_field(name="💰 Price",
                            value=f"Median: **{d['median_price']} R$**\nBest: **{d['best_price']} R$**",
                            inline=True)
            embed.add_field(name="📊 Health",
                            value=f"Comp: **{d['total_matches']}**\n{d['saturation']}",
                            inline=True)
            embed.add_field(name="👥 Creators",
                            value=f"Unique: **{d['unique_creators']}**\nTop: **{d['top_creator_share']}%**",
                            inline=True)
            if d["top_styles"]:
                styles_str = "\n".join(f"`{s}` — {c} items" for s, c in d["top_styles"])
                embed.add_field(name="🎨 Styles", value=styles_str, inline=False)
            if d["study_items"]:
                study_str = "\n".join(f"`{iid}` — {name[:45]} ({favs:,} favs)"
                                      for iid, name, _, favs, _, _ in d["study_items"])
                embed.add_field(name="👀 Study These", value=study_str, inline=False)
        return embed

    def rebuild_buttons(self):
        self.clear_items()
        d = self.data
        kw_btn = discord.ui.Button(label=f"🎯 Keywords ({len(d['top_keywords'])})",
                                   style=discord.ButtonStyle.success if self.view_mode == "keywords" else discord.ButtonStyle.secondary, row=1)
        kw_btn.callback = self.set_keywords; self.add_item(kw_btn)
        adj_btn = discord.ui.Button(label=f"🔗 Adjacent ({len(d['adjacent'])})",
                                    style=discord.ButtonStyle.success if self.view_mode == "adjacent" else discord.ButtonStyle.secondary, row=1)
        adj_btn.callback = self.set_adjacent; self.add_item(adj_btn)
        desc_btn = discord.ui.Button(label=f"📝 Description ({len(d['description_keywords'])})",
                                     style=discord.ButtonStyle.success if self.view_mode == "description" else discord.ButtonStyle.secondary, row=1)
        desc_btn.callback = self.set_description; self.add_item(desc_btn)
        market_btn = discord.ui.Button(label="💰 Market",
                                       style=discord.ButtonStyle.success if self.view_mode == "market" else discord.ButtonStyle.secondary, row=1)
        market_btn.callback = self.set_market; self.add_item(market_btn)
        if self.view_mode == "keywords":
            total = len(d["top_keywords"])
            max_page = max(0, (total - 1) // self.per_page)
            first = discord.ui.Button(label="⏮️", style=discord.ButtonStyle.secondary, row=0, disabled=(self.page == 0))
            first.callback = self.first_page; self.add_item(first)
            prev = discord.ui.Button(label="◀️", style=discord.ButtonStyle.primary, row=0, disabled=(self.page == 0))
            prev.callback = self.prev_page; self.add_item(prev)
            ind = discord.ui.Button(label=f"Page {self.page+1}/{max_page+1}",
                                    style=discord.ButtonStyle.secondary, row=0, disabled=True)
            self.add_item(ind)
            nxt = discord.ui.Button(label="▶️", style=discord.ButtonStyle.primary, row=0, disabled=(self.page >= max_page))
            nxt.callback = self.next_page; self.add_item(nxt)
            last = discord.ui.Button(label="⏭️", style=discord.ButtonStyle.secondary, row=0, disabled=(self.page >= max_page))
            last.callback = self.last_page; self.add_item(last)

    async def set_keywords(self, i):
        self.view_mode = "keywords"; self.page = 0; self.rebuild_buttons()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def set_adjacent(self, i):
        self.view_mode = "adjacent"; self.rebuild_buttons()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def set_description(self, i):
        self.view_mode = "description"; self.rebuild_buttons()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def set_market(self, i):
        self.view_mode = "market"; self.rebuild_buttons()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def first_page(self, i):
        self.page = 0; self.rebuild_buttons()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def prev_page(self, i):
        self.page = max(0, self.page - 1); self.rebuild_buttons()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def next_page(self, i):
        total = len(self.data["top_keywords"])
        max_page = max(0, (total - 1) // self.per_page)
        self.page = min(max_page, self.page + 1); self.rebuild_buttons()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def last_page(self, i):
        total = len(self.data["top_keywords"])
        max_page = max(0, (total - 1) // self.per_page)
        self.page = max_page; self.rebuild_buttons()
        await i.response.edit_message(embed=self.build_embed(), view=self)


class SimplePaginator(discord.ui.View):
    def __init__(self, keyword, items, title_prefix, color, per_page=10):
        super().__init__(timeout=180)
        self.keyword = keyword; self.items = items
        self.title_prefix = title_prefix; self.color = color
        self.per_page = per_page; self.page = 0
        self.max_page = max(0, (len(items) - 1) // per_page)
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        first = discord.ui.Button(label="⏮️", style=discord.ButtonStyle.secondary, disabled=(self.page == 0))
        first.callback = self.first_page; self.add_item(first)
        prev = discord.ui.Button(label="◀️", style=discord.ButtonStyle.primary, disabled=(self.page == 0))
        prev.callback = self.prev_page; self.add_item(prev)
        ind = discord.ui.Button(label=f"Page {self.page+1}/{self.max_page+1}",
                                style=discord.ButtonStyle.secondary, disabled=True)
        self.add_item(ind)
        nxt = discord.ui.Button(label="▶️", style=discord.ButtonStyle.primary, disabled=(self.page >= self.max_page))
        nxt.callback = self.next_page; self.add_item(nxt)
        last = discord.ui.Button(label="⏭️", style=discord.ButtonStyle.secondary, disabled=(self.page >= self.max_page))
        last.callback = self.last_page; self.add_item(last)

    def build_embed(self):
        start = self.page * self.per_page
        end = start + self.per_page
        chunk = self.items[start:end]
        embed = discord.Embed(title=f"{self.title_prefix}: `{self.keyword}`",
                              description=f"Showing **{start+1}–{min(end, len(self.items))}** of **{len(self.items)}**.",
                              color=self.color)
        for i, (w, af, c, sc) in enumerate(chunk, start + 1):
            embed.add_field(name=f"{i}. {w}",
                            value=f"Score: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Comp: **{c:,}**",
                            inline=False)
        embed.set_footer(text=f"Page {self.page+1} of {self.max_page+1}")
        return embed

    async def first_page(self, i):
        self.page = 0; self.rebuild()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def prev_page(self, i):
        self.page = max(0, self.page - 1); self.rebuild()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def next_page(self, i):
        self.page = min(self.max_page, self.page + 1); self.rebuild()
        await i.response.edit_message(embed=self.build_embed(), view=self)
    async def last_page(self, i):
        self.page = self.max_page; self.rebuild()
        await i.response.edit_message(embed=self.build_embed(), view=self)


def _analyze_word(cur, word):
    pattern = word_boundary_pattern(word)
    cur.execute(f"""
        SELECT 
            COUNT(*), 
            AVG(favorite_count),
            AVG(CASE WHEN price BETWEEN {MIN_PRICE} AND {MAX_PRICE} THEN price END),
            PERCENTILE_CONT(0.5) WITHIN GROUP (
                ORDER BY CASE WHEN price BETWEEN {MIN_PRICE} AND {MAX_PRICE} THEN price END
            )
        FROM items WHERE (name ~* %s OR COALESCE(description, '') ~* %s)
          AND favorite_count > 0
    """, (pattern, pattern))
    row = cur.fetchone()
    avg_price = row[2] or 0
    median_price = row[3] or avg_price
    return {
        "word": word, "count": row[0] or 0,
        "avg_favs": row[1] or 0,
        "avg_price": median_price or avg_price or 0,
    }


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


def find_matching_items(cur, words, limit=5):
    if not words: return []
    conditions = " OR ".join(["name ~* %s"] * len(words))
    patterns = [word_boundary_pattern(w) for w in words]
    cur.execute(f"""SELECT id, name, favorite_count, price FROM items
                    WHERE ({conditions}) AND favorite_count > 500
                    ORDER BY favorite_count DESC LIMIT %s""",
                tuple(patterns) + (limit,))
    return cur.fetchall()


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
        return ("🟡", "UNTESTED", "No item combines these words. Could be sleeper hit OR dead demand.")
    if combo_count < 10:
        if combo_stats["avg_favs"] > 10000:
            return ("🔥", "JACKPOT", f"Only **{combo_count}** items — but they average **{combo_stats['avg_favs']:,.0f}** favs.")
        return ("🟢", "UNTAPPED NICHE", f"Only {combo_count} items exist.")
    if combo_count < 50: return ("🟡", "SWEET SPOT", f"{combo_count} items — proven demand.")
    if combo_count < 200: return ("🟠", "COMPETITIVE", f"{combo_count} items. Need a clear edge.")
    return ("🔴", "SATURATED", f"{combo_count} items. Too crowded.")


def build_strategy(verdict, word_stats, combo_stats, adjacent, alternatives, data):
    emoji, label, _ = verdict
    lines = []
    if emoji == "🔥":
        lines = ["**ATTACK NOW.** Rare opportunity.", "• Design an exceptional item",
                 "• Use the exact combo in title"]
        if data: lines.append(f"• Price around **{data['best_price']} R$**")
        lines.append("• Upload ASAP — window won't last")
    elif emoji == "🟢":
        lines = ["**GREEN LIGHT.** Solid opportunity.", "• Use top 2 keywords in title"]
        if alternatives: lines.append(f"• Add `{alternatives[0]['word']}` for reach")
        if data: lines.append(f"• Price between **{data['median_price']}–{data['best_price']} R$**")
    elif emoji == "🟡":
        lines = ["**TEST IT.** Moderate signal.", "• Add specific modifiers",
                 "• Study top 3 rivals"]
    elif emoji == "🟠":
        lines = ["**DIFFERENTIATE.** Crowded but winnable.", "• Add unique style combo"]
        if alternatives: lines.append(f"• Try `{alternatives[0]['word']}` instead")
    else:
        lines = ["**PIVOT.** Too saturated."]
        if alternatives: lines.append(f"• Switch to `{alternatives[0]['word']}`")
    return "\n".join(lines)


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
                       "why": "No existing combo, but individual words have demand"})
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
        if g < -50: risks.append(("🔴", "Fading trend", "Pivot to a rising keyword"))
        elif g < 0: risks.append(("🟡", "Slightly declining", "Move fast"))
    if data and data["top_creator_share"] > 25:
        risks.append(("🟠", f"Creator dominance ({data['top_creator_share']}%)", "Study their design"))
    if data and data["median_price"] > 0 and data["best_price"] > data["median_price"] * 2:
        risks.append(("🟡", "Price sensitivity", "Price below median"))
    # ALWAYS ensure at least one
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


class GuideNav(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)
        self.choice = None

    def _disable_all(self):
        for c in self.children:
            try: c.disabled = True
            except Exception: pass

    async def _handle(self, interaction: discord.Interaction, choice: str):
        self.choice = choice
        self._disable_all()
        try:
            await interaction.response.edit_message(view=self)
        except discord.errors.InteractionResponded:
            pass
        except Exception as e:
            print(f"⚠️ Interaction edit failed: {e}", flush=True)
            try: await interaction.response.defer()
            except Exception: pass
        self.stop()

    @discord.ui.button(label="▶ Continue", style=discord.ButtonStyle.success, row=0)
    async def cont(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle(interaction, "continue")

    @discord.ui.button(label="⏭ Skip to Strategy", style=discord.ButtonStyle.secondary, row=0)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle(interaction, "skip")

    @discord.ui.button(label="⏹ Stop", style=discord.ButtonStyle.danger, row=0)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle(interaction, "stop")


async def ask_nav(ctx, prompt, timeout=600):
    nav = GuideNav()
    try:
        msg = await ctx.send(prompt, view=nav)
    except Exception as e:
        print(f"⚠️ Nav send failed: {e}", flush=True)
        return "continue"
    try:
        await asyncio.wait_for(nav.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            for c in nav.children: c.disabled = True
            await msg.edit(view=nav)
        except Exception: pass
        return "continue"
    return nav.choice or "continue"


# ============================================================
# GUIDE — isolated queries so one failure doesn't kill the guide
# ============================================================
@bot.command(name="guide")
async def guide(ctx, *, idea: str = None):
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    discord_id = ctx.author.id
    username = str(ctx.author)

    try:
        conn = get_db(); cur = conn.cursor()
        profile = get_or_create_profile(cur, discord_id, username)
        past = get_past_consultations(cur, discord_id, limit=3)
        stats = get_db_stats(cur)
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        print(f"Setup error: {e}", flush=True)
        profile = {"total_consultations": 0, "first_seen": None}
        past = []
        stats = {"discovered": 0, "analyzed": 0, "snapshots": 0,
                 "suggestions": 0, "learned": 0, "consultations": 0}

    greeting = ""
    if profile["total_consultations"] > 0:
        greeting = f"👋 Welcome back, **{ctx.author.display_name}**. Consultation **#{profile['total_consultations'] + 1}**.\n\n"

    db_status = (
        f"```\n"
        f"┌─ LIVE DATABASE ──────────────┐\n"
        f"│ 🔍 IDs Discovered   {stats['discovered']:>10,} │\n"
        f"│ 📦 Items Analyzed   {stats['analyzed']:>10,} │\n"
        f"│ 📊 History Snapshots{stats['snapshots']:>10,} │\n"
        f"│ 💬 Search Suggestions{stats['suggestions']:>9,} │\n"
        f"│ 🧠 Learned Keywords {stats['learned']:>10,} │\n"
        f"└──────────────────────────────┘\n"
        f"```"
    )

    if not idea:
        await safe_send(ctx, discord.Embed(
            title="🧠 Elite UGC Consultation",
            description=(f"{greeting}{db_status}\n"
                         "**4 sections** — buttons control the pace.\n\n"
                         "**What's your UGC idea?**\n"
                         "*Examples: `korean dance` · `y2k cyber visor` · `transparent beanie`*"),
            color=0x00aaff), "Intake")
        try:
            msg = await bot.wait_for("message", check=check, timeout=600)
            idea = msg.content.strip().lower()
        except asyncio.TimeoutError:
            await ctx.send("⏰ Timed out.")
            return

    if idea in ("cancel", "exit", "stop"):
        await ctx.send("❌ Cancelled.")
        return

    idea_clean = re.sub(r'[^a-z0-9\s]', '', idea.lower()).strip()
    words = [w for w in idea_clean.split() if len(w) >= 2]
    if not words:
        await ctx.send("❌ Need at least one real word.")
        return

    # ---- SECTION 1 ----
    classifications = [classify_word(w) for w in words]
    icons = {"slang": "⚡", "color": "🎨", "style": "✨", "item": "🧢",
             "emote": "💃", "number": "🔢", "unknown": "❔"}
    understanding = "\n".join(f"{icons[c]} `{w}` — **{c}**" for w, c in zip(words, classifications))

    await safe_send(ctx, discord.Embed(
        title=f"📖 Section 1/4 — Understanding `{idea_clean}`",
        description=(f"{db_status}\n**Parsing {len(words)} components:**\n\n"
                     f"{understanding}\n\n*Scanning {stats['analyzed']:,} items...*"),
        color=0x00aaff), "S1")
    await asyncio.sleep(0.3)

    progress = await ctx.send("🔄 Loading market data...")
    word_stats, combo_stats, opportunity_data = [], None, None
    adjacent, rivals, dominance, alternatives, portfolio = [], [], [], [], []
    trend_data, timing, launch_window = {}, None, "N/A"
    graph = {"level_1": [], "level_2": {}}
    desc_keywords, gap_keywords = [], []
    risks, pricing, roi, ab_titles, design = [], [], None, [], ""
    total_items = 0
    total_described = 0

    conn = None; cur = None
    try:
        conn = get_db(); cur = conn.cursor()

        # --- Each query isolated ---
        try:
            word_stats = [_analyze_word(cur, w) for w in words]
        except Exception as e:
            print(f"Word stats failed: {e}", flush=True)
            rollback_quietly(cur)

        try:
            combo_stats = _analyze_combo(cur, words) if len(words) >= 2 else None
        except Exception as e:
            print(f"Combo stats failed: {e}", flush=True)
            rollback_quietly(cur)
            combo_stats = None

        # Analyse LAST word — but with smart fallback
        try:
            await progress.edit(content="🔄 Analyzing keywords (with multi-word fallback)...")
        except Exception: pass
        try:
            opportunity_data = analyze_opportunity(cur, words[-1] if len(words) == 1 else idea_clean)
            # If empty and multi-word, try last word only
            if (not opportunity_data or not opportunity_data.get("top_keywords")) and len(words) > 1:
                opportunity_data = analyze_opportunity(cur, words[-1])
        except Exception as e:
            print(f"Opportunity failed: {e}", flush=True)
            rollback_quietly(cur)
            opportunity_data = None

        try:
            adjacent = _get_adjacent_for(cur, words[-1], limit=25)
        except Exception as e:
            print(f"Adjacent failed: {e}", flush=True)
            rollback_quietly(cur)
            adjacent = []

        try:
            await progress.edit(content="🔄 Loading rivals + trends...")
        except Exception: pass

        try:
            rivals = _analyze_rivals(cur, words[-1], top_n=3)
        except Exception as e:
            print(f"Rivals failed: {e}", flush=True)
            rollback_quietly(cur)
            rivals = []

        try:
            trend_data = _get_trend_signal(cur, words[-1]) or {}
        except Exception as e:
            print(f"Trend failed: {e}", flush=True)
            rollback_quietly(cur)
            trend_data = {}

        try:
            timing = get_timing_intelligence(cur, words[-1])
        except Exception as e:
            print(f"Timing failed: {e}", flush=True)
            rollback_quietly(cur)
            timing = None

        try:
            launch_window = get_launch_window(cur, words[-1])
        except Exception as e:
            print(f"Launch window failed: {e}", flush=True)
            rollback_quietly(cur)
            launch_window = "N/A"

        try:
            graph = get_niche_graph(cur, words[-1], top_per_level=12)
        except Exception as e:
            print(f"Graph failed: {e}", flush=True)
            rollback_quietly(cur)
            graph = {"level_1": [], "level_2": {}}

        try:
            dominance = get_creator_dominance(cur, words[-1])
        except Exception as e:
            print(f"Dominance failed: {e}", flush=True)
            rollback_quietly(cur)
            dominance = []

        # Descriptions + Gaps
        try:
            await progress.edit(content="🔄 Loading descriptions + gaps...")
        except Exception: pass
        pattern = word_boundary_pattern(words[-1])

        try:
            cur.execute("SELECT COUNT(*) FROM items WHERE description IS NOT NULL AND description != ''")
            total_described = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM items")
            total_items = cur.fetchone()[0] or 0
        except Exception as e:
            print(f"Desc diag failed: {e}", flush=True)
            rollback_quietly(cur)

        try:
            cur.execute("""SELECT name, COALESCE(description, ''), favorite_count FROM items 
                           WHERE name ~* %s AND description IS NOT NULL AND description != ''
                           AND favorite_count > 0 LIMIT 1000""", (pattern,))
            desc_rows = cur.fetchall()
            if desc_rows:
                dc = Counter(); df = defaultdict(int)
                for name, desc, favs in desc_rows:
                    for w in set(extract_words(desc)):
                        dc[w] += 1; df[w] += favs or 0
                for w, count in dc.most_common(50):
                    if count < 2: continue
                    af = df[w] / count
                    desc_keywords.append((w, af, count, af / math.log1p(count)))
        except Exception as e:
            print(f"Desc keywords failed: {e}", flush=True)
            rollback_quietly(cur)

        try:
            cur.execute("""SELECT name, COALESCE(description, ''), favorite_count FROM items 
                           WHERE (name ~* %s OR COALESCE(description, '') ~* %s) 
                           AND favorite_count > 50 LIMIT 1000""", (pattern, pattern))
            gap_rows = cur.fetchall()
            if gap_rows:
                gs = defaultdict(lambda: {"favs": 0, "count": 0})
                for name, desc, favs in gap_rows:
                    for w in set(extract_words(f"{name} {desc}")):
                        if w == words[-1]: continue
                        gs[w]["favs"] += (favs or 0); gs[w]["count"] += 1
                for w, s in gs.items():
                    if s["count"] < 2 or s["count"] > 20: continue
                    af = s["favs"] / s["count"]
                    if af < 500: continue
                    gap_keywords.append((w, af, s["count"]))
                gap_keywords.sort(key=lambda x: x[1], reverse=True)
                gap_keywords = gap_keywords[:25]
        except Exception as e:
            print(f"Gaps failed: {e}", flush=True)
            rollback_quietly(cur)

        try:
            if len(words) >= 2 and word_stats and word_stats[0]["count"] < 100:
                alternatives = _find_alternatives(cur, words[0], words[-1], limit=8)
        except Exception as e:
            print(f"Alternatives failed: {e}", flush=True)
            rollback_quietly(cur)

        try:
            portfolio = _generate_portfolio(cur, idea_clean, alternatives, adjacent, opportunity_data)
        except Exception as e:
            print(f"Portfolio failed: {e}", flush=True)

        try:
            risks = _assess_risk(word_stats, combo_stats, opportunity_data, trend_data)
        except Exception as e:
            print(f"Risks failed: {e}", flush=True)
            risks = [("🟢", "Analysis unavailable", "Solid opportunity — proceed")]

        try:
            pricing = _optimize_price(opportunity_data, combo_stats, word_stats)
        except Exception as e:
            print(f"Pricing failed: {e}", flush=True)

        try:
            roi = _compute_roi(opportunity_data, combo_stats, word_stats)
        except Exception as e:
            print(f"ROI failed: {e}", flush=True)

        try:
            ab_titles = generate_ab_titles(idea_clean, words, combo_stats, alternatives, adjacent, opportunity_data)
        except Exception as e:
            print(f"A/B titles failed: {e}", flush=True)

        try:
            design = _make_design_brief(idea_clean, word_stats, adjacent, opportunity_data)
        except Exception as e:
            print(f"Design failed: {e}", flush=True)

        try:
            increment_consultations(cur, discord_id)
            conn.commit()
        except Exception: pass

    except Exception as e:
        print(f"Outer scan error: {e}", flush=True)
        import traceback
        traceback.print_exc()
    finally:
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass

    try: await progress.delete()
    except Exception: pass
    await asyncio.sleep(0.3)

    # ---- PULSE ----
    pulse = discord.Embed(title="📊 Section 1 — Market Pulse",
                          description="Real data per word:", color=0x66ccff)
    for i, w in enumerate(word_stats, 1):
        if w["count"] == 0: status = "❌ Not in DB"
        elif w["count"] < 10: status = f"🟡 Rare ({w['count']})"
        elif w["count"] < 100: status = f"🟢 Niche ({w['count']})"
        elif w["count"] < 500: status = f"🟠 Popular ({w['count']})"
        else: status = f"🔴 Saturated ({w['count']})"
        price_display = f"{w['avg_price']:,.0f} R$" if w['avg_price'] > 0 else "—"
        pulse.add_field(name=f"{i}. `{w['word']}` — {status}",
                        value=f"Avg Favs: **{w['avg_favs']:,.0f}** · Median Price: **{price_display}**",
                        inline=False)
    if trend_data and trend_data.get("avg_growth") is not None:
        g = trend_data["avg_growth"]
        arrow = "📈" if g > 50 else "📉" if g < -50 else "➡️"
        pulse.add_field(name=f"{arrow} Trend",
                        value=f"**{g:+,.0f}** favs/snapshot ({trend_data.get('tracked', 0)} tracked)",
                        inline=False)
    await safe_send(ctx, pulse, "Pulse")

    choice = await ask_nav(ctx, "**Section 1 done.** See keywords + adjacent + description + gaps?")
    goto_strategy = False
    if choice == "stop":
        await ctx.send("⏹ Guide ended.")
        return
    if choice == "skip":
        goto_strategy = True
    else:
        await ctx.send("🔄 Loading Section 2...")
        await asyncio.sleep(0.3)

    # ---- SECTION 2 ----
    if not goto_strategy:
        # Top keywords
        if opportunity_data and opportunity_data.get("top_keywords"):
            kw_all = opportunity_data["top_keywords"][:15]
            fallback_note = ""
            if opportunity_data.get("used_fallback"):
                fallback_note = " *(multi-word fallback — searched each word separately)*"
            for page_start in range(0, len(kw_all), 8):
                chunk = kw_all[page_start:page_start + 8]
                kw_embed = discord.Embed(
                    title=f"🎯 Section 2 — Top Keywords ({page_start+1}–{page_start+len(chunk)})",
                    description=f"From **{opportunity_data['total_matches']}** items.{fallback_note}",
                    color=0x00ff88)
                for i, (w, af, c, sc) in enumerate(chunk, page_start + 1):
                    kw_embed.add_field(name=f"{i}. {w}",
                                       value=f"Score: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Comp: **{c:,}**",
                                       inline=False)
                await safe_send(ctx, kw_embed, "Kw")
                await asyncio.sleep(0.5)
        else:
            await safe_send(ctx, content="🎯 Section 2 — No top keywords found.", label="Kw-Empty")

        # Adjacent
        if adjacent:
            for page_start in range(0, len(adjacent), 30):
                chunk = adjacent[page_start:page_start + 30]
                adj_embed = discord.Embed(
                    title=f"🔗 Section 2 — Adjacent Keywords ({page_start+1}–{page_start+len(chunk)})",
                    description=f"Words that appear alongside your idea.",
                    color=0x66ccff)
                half = (len(chunk) + 1) // 2
                left = " · ".join(f"`{w}`" for w in chunk[:half])
                right = " · ".join(f"`{w}`" for w in chunk[half:])
                if left: adj_embed.add_field(name="\u200b", value=left, inline=True)
                if right: adj_embed.add_field(name="\u200b", value=right, inline=True)
                await safe_send(ctx, adj_embed, "Adj")
                await asyncio.sleep(0.5)

        # Description keywords
        if desc_keywords:
            for page_start in range(0, min(len(desc_keywords), 20), 8):
                chunk = desc_keywords[page_start:page_start + 8]
                desc_embed = discord.Embed(
                    title=f"📝 Section 2 — Hidden Description Keywords ({page_start+1}–{page_start+len(chunk)})",
                    description="SEO words buried in descriptions:",
                    color=0xaa66ff)
                for i, (w, af, c, sc) in enumerate(chunk, page_start + 1):
                    desc_embed.add_field(name=f"{i}. {w}",
                                         value=f"Score: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Used in **{c}** descs",
                                         inline=False)
                await safe_send(ctx, desc_embed, "Desc")
                await asyncio.sleep(0.5)
        else:
            if total_items > 0:
                diag_msg = (
                    f"**No descriptions found for this niche.**\n\n"
                    f"📊 Database-wide: **{total_described:,}** of **{total_items:,}** items have descriptions "
                    f"({(total_described/total_items*100):.1f}%).\n\n"
                    f"Items in this niche likely don't have descriptions on Roblox yet. "
                    f"Run the **enricher** workflow more times."
                )
            else:
                diag_msg = "**No descriptions found.** Run the enricher to populate item descriptions."
            await safe_send(ctx, discord.Embed(
                title="📝 Section 2 — Hidden Description Keywords",
                description=diag_msg, color=0xaa66ff), "Desc-Empty")

        # Gaps
        if gap_keywords:
            for page_start in range(0, len(gap_keywords), 8):
                chunk = gap_keywords[page_start:page_start + 8]
                gap_embed = discord.Embed(
                    title=f"🕳️ Section 2 — Market Gaps ({page_start+1}–{page_start+len(chunk)})",
                    description="High demand + low competition:",
                    color=0x00ffcc)
                for i, (w, af, c) in enumerate(chunk, page_start + 1):
                    gap_embed.add_field(name=f"{i}. {w}",
                                        value=f"AvgFav: **{af:,.0f}** | Used by **{c}** items — untapped!",
                                        inline=False)
                await safe_send(ctx, gap_embed, "Gaps")
                await asyncio.sleep(0.5)

        choice = await ask_nav(ctx, "**Section 2 done.** See diagnosis + risks + rivals + dominance?")
        if choice == "stop":
            await ctx.send("⏹ Guide ended.")
            return
        if choice == "skip":
            goto_strategy = True
        else:
            await ctx.send("🔄 Loading Section 3...")
            await asyncio.sleep(0.3)

    # ---- SECTION 3 ----
    verdict = smart_verdict(word_stats, combo_stats)

    if not goto_strategy:
        emoji, label, explanation = verdict
        color_map = {"🔥": 0xff2266, "🟢": 0x00ff88, "🟡": 0xffaa00, "🟠": 0xff6600, "🔴": 0xff2222}

        diag = discord.Embed(title=f"{emoji} Section 3 — Diagnosis: {label}",
                             description=f"━━━━━━━━━━━━━━━━━━━━━\n\n{explanation}",
                             color=color_map.get(emoji, 0x00aaff))
        if combo_stats and combo_stats["count"] > 0:
            diag.add_field(name="🎯 Combo Match",
                           value=f"**{combo_stats['count']}** items\nAvg Fav: **{combo_stats['avg_favs']:,.0f}**",
                           inline=False)
        await safe_send(ctx, diag, "Diag")
        await asyncio.sleep(0.5)

        risk_embed = discord.Embed(title="⚠️ Section 3 — Risks",
                                   description=f"**{len(risks)}** identified:", color=0xff8800)
        for icon, risk, mit in risks:
            risk_embed.add_field(name=f"{icon} {risk}", value=f"→ *{mit}*", inline=False)
        await safe_send(ctx, risk_embed, "Risks")
        await asyncio.sleep(0.5)

        if rivals:
            rival_embed = discord.Embed(title="🥊 Section 3 — Top Rivals",
                                        description="Study these before you build:", color=0xff3388)
            for iid, name, favs, price, creator in rivals:
                creator_str = f"by {creator}" if creator else "unknown"
                price_str = f"{price} R$" if price and price <= MAX_PRICE else "N/A"
                rival_embed.add_field(name=f"`{iid}` — {name[:55]}",
                                      value=f"**{favs:,}** favs · **{price_str}** · {creator_str}",
                                      inline=False)
            await safe_send(ctx, rival_embed, "Rivals")
            await asyncio.sleep(0.5)

        if dominance and len(dominance) > 1:
            dom_embed = discord.Embed(title="👑 Section 3 — Creator Dominance",
                                      description="Who owns this niche?", color=0xffcc00)
            for creator, cnt, total_favs in dominance[:5]:
                dom_embed.add_field(name=creator,
                                    value=f"**{cnt}** items · **{total_favs:,}** favs", inline=True)
            await safe_send(ctx, dom_embed, "Dom")
            await asyncio.sleep(0.5)

        choice = await ask_nav(ctx, "**Section 3 done.** See ROI + pricing + final package?")
        if choice == "stop":
            await ctx.send("⏹ Guide ended.")
            return
        await ctx.send("🔄 Loading final section...")
        await asyncio.sleep(0.3)

    # ---- SECTION 4 — 3 combined embeds ----
    try:
        combo = discord.Embed(
            title="💰 Section 4 — ROI, Pricing & Alternatives",
            color=0x00ff88
        )
        if alternatives:
            alt_lines = "\n".join(
                f"• `{a['word']}` — **{a['count']}** items, avg **{a['avg_favs']:,.0f}** favs"
                for a in alternatives[:5]
            )
            combo.add_field(name="🎨 Proven Alternatives",
                            value=alt_lines, inline=False)
        if graph.get("level_1"):
            combo.add_field(
                name="🕸️ Keyword Graph",
                value=" · ".join(f"`{w}`" for w in graph["level_1"][:10]),
                inline=False
            )
        if roi:
            combo.add_field(name="📈 Expected Favs",
                            value=f"**~{roi['expected_favs']:,}**", inline=True)
            combo.add_field(name="💸 Expected Sales",
                            value=f"**~{roi['expected_sales']:,}**", inline=True)
            combo.add_field(name="💎 Expected Revenue",
                            value=f"**~{roi['expected_revenue']:,} R$**\n({roi['confidence']})",
                            inline=True)
        if pricing:
            price_lines = "\n".join(
                f"{p['name']} — **{p['price']} R$** · *{p['pro']}*"
                for p in pricing
            )
            combo.add_field(name="💵 Pricing Options",
                            value=price_lines, inline=False)
        await safe_send(ctx, combo, "S4-1")
        await asyncio.sleep(1)

        design_embed = discord.Embed(
            title="✏️ Section 4 — Design Package",
            color=0x9966ff
        )
        if portfolio:
            port_lines = "\n".join(
                f"**{i}. [{item['angle']}]** `{item['idea']}`\n    *{item['why']}*"
                for i, item in enumerate(portfolio, 1)
            )
            design_embed.add_field(name="🎨 Portfolio Blueprint",
                                   value=port_lines, inline=False)
        if design:
            design_embed.add_field(name="📐 Design Brief",
                                   value=design, inline=False)
        if adjacent:
            design_embed.add_field(
                name="🔗 Title/Description Keywords",
                value=" · ".join(f"`{w}`" for w in adjacent[:10]),
                inline=False
            )
        if ab_titles:
            ab_lines = "\n\n".join(
                f"**{chr(64+i)}. {t['strategy']}** [{t['predicted']}]\n`{t['title']}`"
                for i, t in enumerate(ab_titles, 1)
            )
            design_embed.add_field(name="🅰️ Title Variants",
                                   value=ab_lines, inline=False)
        await safe_send(ctx, design_embed, "S4-2")
        await asyncio.sleep(1)

        final_embed = discord.Embed(
            title="🎯 Final Strategy & Launch Plan",
            color=0x00ffcc
        )
        if timing:
            final_embed.add_field(name="📅 Best Day",
                                  value=f"**{timing['best_day']}**", inline=True)
            final_embed.add_field(name="⏰ Best Hours",
                                  value=", ".join(timing["best_hours"]), inline=True)
        final_embed.add_field(name="🚀 Launch Window",
                              value=launch_window, inline=False)
        strategy = build_strategy(verdict, word_stats, combo_stats,
                                   adjacent, alternatives, opportunity_data)
        final_embed.add_field(name="🎯 Strategy",
                              value=strategy, inline=False)
        final_title = ab_titles[0]["title"] if ab_titles else " ".join(w.capitalize() for w in words)[:80]
        final_price = roi["best_price"] if roi else 100
        checklist_txt = (
            f"**Day 1 — Design**\n"
            f"☐ Model in Roblox Studio\n"
            f"☐ Reference top rivals\n"
            f"☐ Apply design keywords\n\n"
            f"**Day 2 — Upload**\n"
            f"☐ Title: `{final_title}`\n"
            f"☐ Price: **{final_price} R$**\n"
            f"☐ Full SEO description\n\n"
            f"**Day 3–7** — Track favourites daily\n"
            f"**Day 8–30** — Scale or pivot"
        )
        final_embed.add_field(name="✅ Launch Checklist",
                              value=checklist_txt, inline=False)
        await safe_send(ctx, final_embed, "S4-3")
    except Exception as e:
        print(f"❌ Section 4 error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        try:
            await ctx.send(f"⚠️ **Section 4 error:** `{e}`")
        except Exception:
            pass

    await ctx.send(
        f"🎉 **Done!** Guide complete for `{idea_clean}`.\n\n"
        f"👁️ Add `{words[-1]}` to **watchlist**? — reply `yes`\n"
        f"📄 Export **full report** as file? — reply `export`\n"
        f"⏹ End? — reply `no`"
    )

    try:
        msg = await bot.wait_for("message", check=check, timeout=300)
        reply = msg.content.strip().lower()

        if reply in ("yes", "y", "yup", "yeah", "ok", "sure"):
            try:
                conn = get_db(); cur = conn.cursor()
                added = add_to_watchlist(cur, discord_id, words[-1], baseline_favs=0)
                conn.commit(); cur.close(); conn.close()
                await ctx.send(f"✅ `{words[-1]}` added to watchlist." if added else f"ℹ️ Already on watchlist.")
            except Exception as e:
                await ctx.send(f"⚠️ Watchlist error: {e}")

        if reply == "export" or reply.startswith("export"):
            session_data = type("Session", (), {
                "seed": idea_clean, "words": words,
                "word_stats": word_stats, "combo_stats": combo_stats,
            })()
            report = build_full_report(session_data, verdict, roi, risks, pricing,
                                        portfolio, design, timing, launch_window,
                                        ab_titles, graph, dominance)
            try:
                conn = get_db(); cur = conn.cursor()
                save_consultation(cur, discord_id, idea_clean, verdict, report)
                conn.commit(); cur.close(); conn.close()
            except Exception: pass
            file = discord.File(io.BytesIO(report.encode("utf-8")),
                                filename=f"ugc_report_{idea_clean.replace(' ', '_')}.txt")
            try:
                await ctx.send("📄 **Report attached:**", file=file)
            except Exception as e:
                await ctx.send(f"⚠️ Attach failed: {e}")
    except asyncio.TimeoutError:
        pass


@bot.command(name="watchlist")
async def watchlist_cmd(ctx):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("""SELECT keyword, baseline_favs, added_at FROM watchlist
                       WHERE discord_id = %s ORDER BY added_at DESC LIMIT 20""", (ctx.author.id,))
        rows = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        await ctx.send(f"⚠️ DB error: {e}")
        return
    if not rows:
        await ctx.send("👁️ Your watchlist is empty. Add keywords during `!guide`.")
        return
    embed = discord.Embed(title=f"👁️ {ctx.author.display_name}'s Watchlist",
                          description=f"Tracking **{len(rows)}** keywords:", color=0x00aaff)
    for kw, baseline, added in rows:
        embed.add_field(name=f"`{kw}`", value=f"Added {added.strftime('%m/%d')}", inline=True)
    await ctx.send(embed=embed)


@bot.command(name="history")
async def history_cmd(ctx):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("""SELECT seed, verdict_label, verdict_emoji, created_at
                       FROM saved_consultations WHERE discord_id = %s
                       ORDER BY created_at DESC LIMIT 15""", (ctx.author.id,))
        rows = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        await ctx.send(f"⚠️ DB error: {e}")
        return
    if not rows:
        await ctx.send("📖 No consultation history yet. Run `!guide`.")
        return
    embed = discord.Embed(title=f"📖 {ctx.author.display_name}'s Consultation History",
                          description=f"**{len(rows)}** saved consultations:", color=0xffaa00)
    for seed, label, emoji, when in rows:
        embed.add_field(name=f"{emoji} `{seed}` — {label}",
                        value=when.strftime("%Y-%m-%d %H:%M"), inline=False)
    await ctx.send(embed=embed)


@bot.event
async def on_ready():
    print(f"✅ {bot.user} is online", flush=True)
    try:
        from database import setup_database
        setup_database()
        print("✅ Database tables verified/created.", flush=True)
    except Exception as e:
        print(f"⚠️ Table setup failed: {e}", flush=True)


@bot.command(name="dbtest")
async def dbtest(ctx):
    try:
        conn = get_db(); cur = conn.cursor()
        lines = []
        for table in ["discovered_items", "items", "item_history",
                      "search_suggestions", "learned_keywords",
                      "user_profiles", "saved_consultations", "watchlist"]:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]
                lines.append(f"✅ `{table}` — **{count:,}** rows")
            except Exception:
                rollback_quietly(cur)
                lines.append(f"❌ `{table}` — missing")
        try:
            cur.execute("SELECT COUNT(*) FROM items WHERE description IS NOT NULL AND description != ''")
            with_desc = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM items")
            total = cur.fetchone()[0] or 0
            lines.append(f"\n📝 Descriptions: **{with_desc:,}** of **{total:,}** items")
        except Exception:
            rollback_quietly(cur)
        cur.close(); conn.close()
        embed = discord.Embed(title="🔬 Database Diagnostic",
                              description="\n".join(lines), color=0x00ff88)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Connection failed: {e}")


@bot.command(name="scan_status")
async def scan_status(ctx):
    conn = get_db(); cur = conn.cursor()
    stats = get_db_stats(cur)
    cur.close(); conn.close()
    embed = discord.Embed(title="📡 Market Intelligence Status", color=0x00aaff)
    embed.add_field(name="🔍 IDs Discovered", value=f"**{stats['discovered']:,}**", inline=True)
    embed.add_field(name="📦 Items Analyzed", value=f"**{stats['analyzed']:,}**", inline=True)
    embed.add_field(name="📊 History Snapshots", value=f"**{stats['snapshots']:,}**", inline=True)
    embed.add_field(name="💬 Search Suggestions", value=f"**{stats['suggestions']:,}**", inline=True)
    embed.add_field(name="🧠 Learned Keywords", value=f"**{stats['learned']:,}**", inline=True)
    embed.add_field(name="📖 Past Consultations", value=f"**{stats['consultations']:,}**", inline=True)
    await ctx.send(embed=embed)


@bot.command(name="trends")
async def trends(ctx):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""SELECT name, description FROM items WHERE favorite_count > 0 
                   ORDER BY favorite_count DESC LIMIT 1000""")
    rows = cur.fetchall()
    cur.close(); conn.close()
    if not rows:
        await ctx.send("⚠️ No data yet.")
        return
    counter = Counter()
    for name, desc in rows:
        counter.update(extract_words(name))
        counter.update(extract_words(desc))
    embed = discord.Embed(title="📈 Top Trend Words",
                          description="Based on top 1,000 items.", color=0xffaa00)
    for i, (w, c) in enumerate(counter.most_common(15), 1):
        embed.add_field(name=f"{i}. {w}", value=f"Appears **{c}** times", inline=False)
    await ctx.send(embed=embed)


@bot.command(name="analyze")
async def analyze(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword.")
        return
    conn = get_db(); cur = conn.cursor()
    pattern = word_boundary_pattern(kw)
    cur.execute("""SELECT name, description, favorite_count FROM items 
                   WHERE (name ~* %s OR COALESCE(description, '') ~* %s) 
                   AND favorite_count > 0 LIMIT 2000""", (pattern, pattern))
    rows = cur.fetchall()
    if not rows:
        await ctx.send(f"⚠️ No data for `{kw}`.")
        cur.close(); conn.close(); return
    stats = defaultdict(lambda: {"favs": 0, "count": 0})
    for name, desc, favs in rows:
        for w in set(extract_words(f"{name} {desc}")):
            if w == kw: continue
            stats[w]["favs"] += (favs or 0)
            stats[w]["count"] += 1
    cur.execute("SELECT LOWER(name) FROM items WHERE favorite_count > 0")
    all_names = [r[0] for r in cur.fetchall()]
    word_list = [w for w, s in stats.items() if s["count"] >= 3]
    comp_map = defaultdict(int)
    for name in all_names:
        for w in word_list:
            if re.search(r'\b' + re.escape(w) + r'\b', name):
                comp_map[w] += 1
    results = []
    for w in word_list:
        s = stats[w]; af = s["favs"] / s["count"]
        c = comp_map.get(w, 1) or 1
        results.append((w, af, c, af / math.log1p(c)))
    cur.close(); conn.close()
    results.sort(key=lambda x: x[3], reverse=True)
    if not results:
        await ctx.send(f"⚠️ Not enough data for `{kw}`.")
        return
    view = SimplePaginator(kw, results, "🧠 Deep Analysis", 0x00ff88, per_page=10)
    embed = view.build_embed()
    embed.description = f"Analyzed **{len(rows)}** items."
    await ctx.send(embed=embed, view=view)


@bot.command(name="desc_analyze")
async def desc_analyze(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword.")
        return
    conn = get_db(); cur = conn.cursor()
    pattern = word_boundary_pattern(kw)
    cur.execute("""SELECT name, COALESCE(description, ''), favorite_count FROM items 
                   WHERE name ~* %s AND description IS NOT NULL AND description != ''
                   AND favorite_count > 0 LIMIT 1500""", (pattern,))
    rows = cur.fetchall()
    if not rows:
        await ctx.send(f"⚠️ No descriptions for `{kw}`.")
        cur.close(); conn.close(); return
    counter = Counter(); word_favs = defaultdict(int)
    for name, desc, favs in rows:
        for w in set(extract_words(desc)):
            counter[w] += 1
            word_favs[w] += favs or 0
    cur.execute("SELECT LOWER(name), COALESCE(LOWER(description), '') FROM items WHERE favorite_count > 0")
    all_rows = cur.fetchall()
    cur.close(); conn.close()
    word_list = [w for w, _ in counter.most_common(80)]
    comp_map = defaultdict(int)
    for name, desc in all_rows:
        text = f"{name} {desc}"
        for w in word_list:
            if re.search(r'\b' + re.escape(w) + r'\b', text):
                comp_map[w] += 1
    results = []
    for w, count in counter.most_common(80):
        if count < 2: continue
        avg_favs = word_favs[w] / count
        comp = comp_map.get(w, 1) or 1
        results.append((w, avg_favs, comp, avg_favs / math.log1p(comp)))
    results.sort(key=lambda x: x[3], reverse=True)
    if not results:
        await ctx.send(f"⚠️ Not enough data.")
        return
    view = SimplePaginator(kw, results, "📝 Hidden Description Keywords", 0xaa66ff, per_page=10)
    embed = view.build_embed()
    embed.description = f"Analyzed **{len(rows)}** descriptions."
    await ctx.send(embed=embed, view=view)


@bot.command(name="opportunity")
async def opportunity(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword.")
        return
    conn = get_db(); cur = conn.cursor()
    data = analyze_opportunity(cur, kw)
    cur.close(); conn.close()
    if not data:
        await ctx.send(f"⚠️ No data for `{kw}`.")
        return
    view = MultiViewPaginator(data)
    await ctx.send(embed=view.build_embed(), view=view)


@bot.command(name="emote")
async def emote(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword.")
        return
    conn = get_db(); cur = conn.cursor()
    data = analyze_opportunity(cur, kw)
    cur.close(); conn.close()
    if not data:
        await ctx.send(f"⚠️ No emote data for `{kw}`.")
        return
    view = MultiViewPaginator(data)
    await ctx.send(embed=view.build_embed(), view=view)


@bot.command(name="classic")
async def classic(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword.")
        return
    conn = get_db(); cur = conn.cursor()
    data = analyze_opportunity(cur, kw)
    cur.close(); conn.close()
    if not data:
        await ctx.send(f"⚠️ No classic data for `{kw}`.")
        return
    view = MultiViewPaginator(data)
    await ctx.send(embed=view.build_embed(), view=view)


@bot.command(name="gap")
async def gap(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword.")
        return
    conn = get_db(); cur = conn.cursor()
    pattern = word_boundary_pattern(kw)
    cur.execute("""SELECT name, COALESCE(description, ''), favorite_count FROM items 
                   WHERE (name ~* %s OR COALESCE(description, '') ~* %s) 
                   AND favorite_count > 50 LIMIT 2000""", (pattern, pattern))
    rows = cur.fetchall()
    if not rows:
        await ctx.send(f"⚠️ No data for `{kw}`.")
        cur.close(); conn.close(); return
    stats = defaultdict(lambda: {"favs": 0, "count": 0})
    for name, desc, favs in rows:
        for w in set(extract_words(f"{name} {desc}")):
            if w == kw: continue
            stats[w]["favs"] += (favs or 0)
            stats[w]["count"] += 1
    candidates = []
    for w, s in stats.items():
        if s["count"] < 2 or s["count"] > 20: continue
        af = s["favs"] / s["count"]
        if af < 500: continue
        candidates.append((w, af))
    if not candidates:
        await ctx.send(f"⚠️ No gaps for `{kw}`.")
        cur.close(); conn.close(); return
    cur.execute("SELECT LOWER(name) FROM items WHERE favorite_count > 0")
    all_names = [r[0] for r in cur.fetchall()]
    word_list = [c[0] for c in candidates]
    comp_map = defaultdict(int)
    for name in all_names:
        for w in word_list:
            if re.search(r'\b' + re.escape(w) + r'\b', name):
                comp_map[w] += 1
    gaps = []
    for w, af in candidates:
        c = comp_map.get(w, 0)
        if c < 50:
            gaps.append((w, af, c, af / math.log1p(max(c, 1))))
    cur.close(); conn.close()
    gaps.sort(key=lambda x: x[1], reverse=True)
    if not gaps:
        await ctx.send(f"⚠️ No gaps found.")
        return
    view = SimplePaginator(kw, gaps, "🕳️ Market Gaps", 0x00ffcc, per_page=10)
    await ctx.send(embed=view.build_embed(), view=view)


@bot.command(name="velocity")
async def velocity(ctx):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""SELECT item_id, MAX(favorite_count) - MIN(favorite_count), COUNT(*) 
                   FROM item_history GROUP BY item_id HAVING COUNT(*) >= 2 
                   ORDER BY 2 DESC LIMIT 50""")
    rows = cur.fetchall()
    if not rows:
        await ctx.send("⚠️ Not enough history. Run enricher 2+ times.")
        cur.close(); conn.close(); return
    items = []
    for iid, growth, snaps in rows:
        cur.execute("SELECT name, price FROM items WHERE id = %s", (iid,))
        r = cur.fetchone()
        name = r[0] if r else f"Item {iid}"
        price = r[1] if r else "?"
        items.append((name[:50], growth, price, growth))
    cur.close(); conn.close()
    embed = discord.Embed(title="🚀 Fastest Rising Items",
                          description=f"Top **{len(items)}** items.", color=0xff5500)
    for i, (name, growth, price, _) in enumerate(items[:10], 1):
        embed.add_field(name=f"{i}. {name}",
                        value=f"📈 +**{growth:,}** favs | 💰 {price} R$", inline=False)
    await ctx.send(embed=embed)


@bot.command(name="track")
async def track(ctx, item_id: int):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT name FROM items WHERE id = %s", (item_id,))
    m = cur.fetchone()
    cur.execute("""SELECT favorite_count, price, snapshot_at FROM item_history 
                   WHERE item_id = %s ORDER BY snapshot_at DESC LIMIT 15""", (item_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    if not rows:
        await ctx.send(f"⚠️ No history for `{item_id}`.")
        return
    title = m[0] if m else f"Item {item_id}"
    embed = discord.Embed(title=f"📊 Tracking: {title[:60]}", color=0x66ccff)
    for favs, price, when in rows:
        embed.add_field(name=f"🕐 {when.strftime('%m/%d %H:%M')}",
                        value=f"Favs: **{favs:,}** | Price: **{price} R$**", inline=False)
    await ctx.send(embed=embed)


app = Flask(__name__)


@app.route('/')
def health():
    return "OK", 200


def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port)


if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(TOKEN)
