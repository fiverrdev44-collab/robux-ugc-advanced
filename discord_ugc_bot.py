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
from gemini_brain import (
    extract_keywords,
    all_terms,
    synthesize_hybrid,
    verify_titles,
    ask_ai,
    is_available,
    expand_search_terms,
    analyze_image_for_ugc,
)
from algo_brain import build_algo_context
from winner_analysis import analyze_winners

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

    classifications = []
    icons = {"slang": "⚡", "color": "🎨", "style": "✨", "item": "🧢",
             "emote": "💃", "number": "🔢", "unknown": "❔"}
    try:
        conn_c = get_db(); cur_c = conn_c.cursor()
        for w in words:
            c = classify_word(w)
            if c == "unknown" and is_emote_word(cur_c, w):
                c = "emote"
            classifications.append(c)
        cur_c.close(); conn_c.close()
    except Exception:
        classifications = [classify_word(w) for w in words]

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

        try:
            await progress.edit(content="🔄 Analyzing keywords (emote-aware)...")
        except Exception: pass

        try:
            opportunity_data = analyze_opportunity(cur, idea_clean)
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

        try:
            await progress.edit(content="🔄 Loading descriptions + gaps...")
        except Exception: pass
        pattern = word_boundary_pattern(words[-1])

        try:
            cur.execute("SELECT COUNT(*) FROM items WHERE description IS NOT NULL AND description != ''")
            total_described = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM items")
            total_items = cur.fetchone()[0] or 0
        except Exception:
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

    if not goto_strategy:
        if opportunity_data and opportunity_data.get("top_keywords"):
            kw_all = opportunity_data["top_keywords"][:15]
            fallback_note = ""
            if opportunity_data.get("used_fallback"):
                fallback_note = " *(multi-word fallback)*"
            if opportunity_data.get("is_emote_seed"):
                fallback_note += " *(💃 emote-aware)*"
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

        if adjacent:
            for page_start in range(0, len(adjacent), 30):
                chunk = adjacent[page_start:page_start + 30]
                adj_embed = discord.Embed(
                    title=f"🔗 Section 2 — Adjacent Keywords ({page_start+1}–{page_start+len(chunk)})",
                    description="Words that appear alongside your idea.",
                    color=0x66ccff)
                half = (len(chunk) + 1) // 2
                left = " · ".join(f"`{w}`" for w in chunk[:half])
                right = " · ".join(f"`{w}`" for w in chunk[half:])
                if left: adj_embed.add_field(name="\u200b", value=left, inline=True)
                if right: adj_embed.add_field(name="\u200b", value=right, inline=True)
                await safe_send(ctx, adj_embed, "Adj")
                await asyncio.sleep(0.5)

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
                    f"Run the **enricher** workflow more times to fill them in."
                )
            else:
                diag_msg = "**No descriptions found.** Run the enricher."
            await safe_send(ctx, discord.Embed(
                title="📝 Section 2 — Hidden Description Keywords",
                description=diag_msg, color=0xaa66ff), "Desc-Empty")

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

    try:
        combo = discord.Embed(title="💰 Section 4 — ROI, Pricing & Alternatives",
                              color=0x00ff88)
        if alternatives:
            combo.add_field(name="🎨 Proven Alternatives",
                            value="\n".join(f"• `{a['word']}` — **{a['count']}** items, avg **{a['avg_favs']:,.0f}** favs"
                                            for a in alternatives[:5]),
                            inline=False)
        if graph.get("level_1"):
            combo.add_field(name="🕸️ Keyword Graph",
                            value=" · ".join(f"`{w}`" for w in graph["level_1"][:10]),
                            inline=False)
        if roi:
            combo.add_field(name="📈 Expected Favs", value=f"**~{roi['expected_favs']:,}**", inline=True)
            combo.add_field(name="💸 Expected Sales", value=f"**~{roi['expected_sales']:,}**", inline=True)
            combo.add_field(name="💎 Expected Revenue", value=f"**~{roi['expected_revenue']:,} R$**\n({roi['confidence']})", inline=True)
        if pricing:
            combo.add_field(name="💵 Pricing Options",
                            value="\n".join(f"{p['name']} — **{p['price']} R$** · *{p['pro']}*" for p in pricing),
                            inline=False)
        await safe_send(ctx, combo, "S4-1")
        await asyncio.sleep(1)

        design_embed = discord.Embed(title="✏️ Section 4 — Design Package", color=0x9966ff)
        if portfolio:
            design_embed.add_field(name="🎨 Portfolio Blueprint",
                                   value="\n".join(f"**{i}. [{item['angle']}]** `{item['idea']}`\n    *{item['why']}*"
                                                   for i, item in enumerate(portfolio, 1)),
                                   inline=False)
        if design:
            design_embed.add_field(name="📐 Design Brief", value=design, inline=False)
        if adjacent:
            design_embed.add_field(name="🔗 Title/Description Keywords",
                                   value=" · ".join(f"`{w}`" for w in adjacent[:10]), inline=False)
        if ab_titles:
            design_embed.add_field(name="🅰️ Title Variants",
                                   value="\n\n".join(f"**{chr(64+i)}. {t['strategy']}** [{t['predicted']}]\n`{t['title']}`"
                                                     for i, t in enumerate(ab_titles, 1)),
                                   inline=False)
        await safe_send(ctx, design_embed, "S4-2")
        await asyncio.sleep(1)

        final_embed = discord.Embed(title="🎯 Final Strategy & Launch Plan", color=0x00ffcc)
        if timing:
            final_embed.add_field(name="📅 Best Day", value=f"**{timing['best_day']}**", inline=True)
            final_embed.add_field(name="⏰ Best Hours", value=", ".join(timing["best_hours"]), inline=True)
        final_embed.add_field(name="🚀 Launch Window", value=launch_window, inline=False)
        final_embed.add_field(name="🎯 Strategy",
                              value=build_strategy(verdict, word_stats, combo_stats, adjacent, alternatives, opportunity_data),
                              inline=False)
        final_title = ab_titles[0]["title"] if ab_titles else " ".join(w.capitalize() for w in words)[:80]
        final_price = roi["best_price"] if roi else 100
        final_embed.add_field(name="✅ Launch Checklist",
                              value=(f"**Day 1 — Design**\n☐ Model in Roblox Studio\n☐ Reference rivals\n\n"
                                     f"**Day 2 — Upload**\n☐ Title: `{final_title}`\n☐ Price: **{final_price} R$**\n☐ Full SEO description\n\n"
                                     f"**Day 3–7** — Track favourites daily\n**Day 8–30** — Scale or pivot"),
                              inline=False)
        await safe_send(ctx, final_embed, "S4-3")
    except Exception as e:
        print(f"❌ Section 4 error: {e}", flush=True)
        try: await ctx.send(f"⚠️ **Section 4 error:** `{e}`")
        except Exception: pass

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
            session_data = type("Session", (), {"seed": idea_clean, "words": words,
                                                "word_stats": word_stats, "combo_stats": combo_stats})()
            report = build_full_report(session_data, verdict, roi, risks, pricing, portfolio, design,
                                        timing, launch_window, ab_titles, graph, dominance)
            try:
                conn = get_db(); cur = conn.cursor()
                save_consultation(cur, discord_id, idea_clean, verdict, report)
                conn.commit(); cur.close(); conn.close()
            except Exception: pass
            file = discord.File(io.BytesIO(report.encode("utf-8")),
                                filename=f"ugc_report_{idea_clean.replace(' ', '_')}.txt")
            try: await ctx.send("📄 **Report attached:**", file=file)
            except Exception as e: await ctx.send(f"⚠️ Attach failed: {e}")
    except asyncio.TimeoutError:
        pass


@bot.command(name="emote_status")
async def emote_status(ctx):
    try:
        conn = get_db(); cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM items WHERE asset_type_id = 61")
            emote_count = cur.fetchone()[0] or 0
        except Exception:
            rollback_quietly(cur); emote_count = 0
        try:
            cur.execute("SELECT COUNT(*) FROM items WHERE name ~* '\\mdance\\M|\\memote\\M|\\mfloss\\M|\\mgriddy\\M|\\mmoonwalk\\M'")
            kw_emote = cur.fetchone()[0] or 0
        except Exception:
            rollback_quietly(cur); kw_emote = 0
        try:
            cur.execute("SELECT COUNT(*) FROM items")
            total = cur.fetchone()[0] or 0
        except Exception:
            rollback_quietly(cur); total = 0
        cur.close(); conn.close()

        embed = discord.Embed(title="💃 Emote Coverage Diagnostic", color=0xff66aa)
        embed.add_field(name="By AssetTypeId (61)", value=f"**{emote_count:,}** items", inline=True)
        embed.add_field(name="By Title Keyword", value=f"**{kw_emote:,}** items", inline=True)
        embed.add_field(name="Total in DB", value=f"**{total:,}** items", inline=True)
        if emote_count == 0:
            embed.add_field(name="⚠️ No emotes detected",
                            value="Run the Daily Scanner workflow on GitHub. It may take a full scan to fetch emotes.",
                            inline=False)
        else:
            embed.add_field(name="✅ Emotes Detected",
                            value=f"You have **{emote_count:,}** emotes in the database. "
                                  f"Run the enricher to fill details.",
                            inline=False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Error: {e}")


@bot.command(name="watchlist")
async def watchlist_cmd(ctx):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("""SELECT keyword, baseline_favs, added_at FROM watchlist
                       WHERE discord_id = %s ORDER BY added_at DESC LIMIT 20""", (ctx.author.id,))
        rows = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        await ctx.send(f"⚠️ DB error: {e}"); return
    if not rows:
        await ctx.send("👁️ Your watchlist is empty."); return
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
        await ctx.send(f"⚠️ DB error: {e}"); return
    if not rows:
        await ctx.send("📖 No consultation history yet. Run `!guide`."); return
    embed = discord.Embed(title=f"📖 {ctx.author.display_name}'s Consultation History",
                          description=f"**{len(rows)}** saved:", color=0xffaa00)
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
                lines.append(f"✅ `{table}` — **{cur.fetchone()[0]:,}** rows")
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
        await ctx.send("⚠️ No data yet."); return
    counter = Counter()
    for name, desc in rows:
        counter.update(extract_words(name))
        counter.update(extract_words(desc))
    embed = discord.Embed(title="📈 Top Trend Words", color=0xffaa00)
    for i, (w, c) in enumerate(counter.most_common(15), 1):
        embed.add_field(name=f"{i}. {w}", value=f"Appears **{c}** times", inline=False)
    await ctx.send(embed=embed)


@bot.command(name="analyze")
async def analyze(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword."); return
    conn = get_db(); cur = conn.cursor()
    pattern = word_boundary_pattern(kw)
    cur.execute("""SELECT name, description, favorite_count FROM items 
                   WHERE (name ~* %s OR COALESCE(description, '') ~* %s) 
                   AND favorite_count > 0 LIMIT 2000""", (pattern, pattern))
    rows = cur.fetchall()
    if not rows:
        await ctx.send(f"⚠️ No data for `{kw}`."); cur.close(); conn.close(); return
    stats = defaultdict(lambda: {"favs": 0, "count": 0})
    for name, desc, favs in rows:
        for w in set(extract_words(f"{name} {desc}")):
            if w == kw: continue
            stats[w]["favs"] += (favs or 0); stats[w]["count"] += 1
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
        await ctx.send(f"⚠️ Not enough data."); return
    view = SimplePaginator(kw, results, "🧠 Deep Analysis", 0x00ff88, per_page=10)
    embed = view.build_embed()
    embed.description = f"Analyzed **{len(rows)}** items."
    await ctx.send(embed=embed, view=view)


@bot.command(name="desc_analyze")
async def desc_analyze(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword."); return
    conn = get_db(); cur = conn.cursor()
    pattern = word_boundary_pattern(kw)
    cur.execute("""SELECT name, COALESCE(description, ''), favorite_count FROM items 
                   WHERE name ~* %s AND description IS NOT NULL AND description != ''
                   AND favorite_count > 0 LIMIT 1500""", (pattern,))
    rows = cur.fetchall()
    if not rows:
        await ctx.send(f"⚠️ No descriptions for `{kw}`."); cur.close(); conn.close(); return
    counter = Counter(); word_favs = defaultdict(int)
    for name, desc, favs in rows:
        for w in set(extract_words(desc)):
            counter[w] += 1; word_favs[w] += favs or 0
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
        await ctx.send(f"⚠️ Not enough data."); return
    view = SimplePaginator(kw, results, "📝 Hidden Description Keywords", 0xaa66ff, per_page=10)
    embed = view.build_embed()
    embed.description = f"Analyzed **{len(rows)}** descriptions."
    await ctx.send(embed=embed, view=view)


@bot.command(name="opportunity")
async def opportunity(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword."); return
    conn = get_db(); cur = conn.cursor()
    data = analyze_opportunity(cur, kw)
    cur.close(); conn.close()
    if not data:
        await ctx.send(f"⚠️ No data for `{kw}`."); return
    view = MultiViewPaginator(data)
    await ctx.send(embed=view.build_embed(), view=view)


@bot.command(name="emote")
async def emote(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword."); return
    conn = get_db(); cur = conn.cursor()
    data = analyze_opportunity(cur, kw)
    cur.close(); conn.close()
    if not data:
        await ctx.send(f"⚠️ No emote data for `{kw}`."); return
    view = MultiViewPaginator(data)
    await ctx.send(embed=view.build_embed(), view=view)


@bot.command(name="classic")
async def classic(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword."); return
    conn = get_db(); cur = conn.cursor()
    data = analyze_opportunity(cur, kw)
    cur.close(); conn.close()
    if not data:
        await ctx.send(f"⚠️ No classic data for `{kw}`."); return
    view = MultiViewPaginator(data)
    await ctx.send(embed=view.build_embed(), view=view)


@bot.command(name="gap")
async def gap(ctx, *, keyword: str = ""):
    kw = (keyword or "").strip().lower()
    try:
        conn = get_db(); cur = conn.cursor()

        cur.execute("""
            SELECT name, favorite_count 
            FROM items 
            WHERE favorite_count > 50
              AND asset_type_id = 61
            LIMIT 5000
        """)
        rows = cur.fetchall()
        if not rows:
            await ctx.send("⚠️ No emote data in DB.")
            cur.close(); conn.close(); return

        stats = defaultdict(lambda: {"favs": 0, "count": 0})
        for name, favs in rows:
            for w in set(extract_words(name)):
                stats[w]["favs"] += (favs or 0)
                stats[w]["count"] += 1

        candidates = []
        for w, s in stats.items():
            if s["count"] < 3: continue
            if s["count"] > 100: continue
            af = s["favs"] / s["count"]
            if af < 500: continue
            candidates.append((w, af))

        if not candidates:
            await ctx.send("⚠️ No gaps found.")
            cur.close(); conn.close(); return

        word_list = [c[0] for c in candidates]
        patterns = [f"%{w}%" for w in word_list]
        cur.execute("""
            SELECT LOWER(name) FROM items 
            WHERE favorite_count > 0 
              AND LOWER(name) LIKE ANY(%s)
        """, (patterns,))
        matched_names = cur.fetchall()
        cur.close(); conn.close()

        comp_map = defaultdict(int)
        for (name,) in matched_names:
            for w in word_list:
                if re.search(r'\b' + re.escape(w) + r'\b', name):
                    comp_map[w] += 1

        gaps = []
        for w, af in candidates:
            c = comp_map.get(w, 0)
            if c < 1: continue
            if c > 50: continue
            score = af / math.log1p(c)
            if kw and kw not in w.lower():
                continue
            gaps.append((w, af, c, score))

        if not gaps and kw:
            for w, af in candidates:
                c = comp_map.get(w, 0)
                if c < 1 or c > 50: continue
                score = af / math.log1p(c)
                gaps.append((w, af, c, score))

        gaps.sort(key=lambda x: x[3], reverse=True)
        if not gaps:
            await ctx.send("⚠️ No gaps found."); return

        gaps = gaps[:30]
        title = f"filter: {kw}" if kw else "all emotes"
        view = SimplePaginator(title, gaps, "🕳️ Market Gaps", 0x00ffcc, per_page=10)
        await ctx.send(embed=view.build_embed(), view=view)
    except Exception as e:
        try:
            await ctx.send(f"❌ Error: {e}")
        except Exception:
            pass


@bot.command(name="velocity")
async def velocity(ctx, days: int = 30, limit: int = 15):
    days = max(1, min(days, 90))
    limit = max(1, min(limit, 25))
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute(f"""
            SELECT i.id, i.name, i.price, i.creator_name, i.asset_type_id,
                   MAX(h.favorite_count) - MIN(h.favorite_count) AS growth,
                   COUNT(h.*) AS snaps
            FROM items i
            JOIN item_history h ON h.item_id = i.id
            WHERE h.snapshot_at >= NOW() - INTERVAL '{days} days'
              AND i.favorite_count > 50
            GROUP BY i.id, i.name, i.price, i.creator_name, i.asset_type_id
            HAVING COUNT(h.*) >= 2
               AND MAX(h.favorite_count) - MIN(h.favorite_count) > 0
            ORDER BY growth DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        await ctx.send(f"❌ DB error: {e}")
        return

    if not rows:
        await ctx.send(
            f"⚠️ **No growth detected in the last {days} days.**\n\n"
            f"**Possible reasons:**\n"
            f"• Snapshot job hasn't run 2+ times yet\n"
            f"• Items have <2 snapshots\n"
            f"• Growth is real but tiny\n\n"
            f"**Try:** `!velocity 90` for a wider window\n"
            f"**Check:** `!scan_status` — History Snapshots count"
        )
        return

    embed = discord.Embed(
        title=f"🚀 Fastest Rising Items (last {days}d)",
        description=f"Top **{len(rows)}** by favorite growth · all categories",
        color=0xff5500)
    for i, (iid, name, price, creator, atype, growth, snaps) in enumerate(rows, 1):
        price_str = f"{price} R$" if price else "Free"
        type_name = ASSET_TYPE_NAMES.get(atype, f"Type {atype}")
        embed.add_field(
            name=f"{i}. {name[:50]}",
            value=(f"📈 **+{growth:,}** favs · 💰 {price_str} · `{type_name}`\n"
                   f"by {creator or '?'} · `{iid}`"),
            inline=False)
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
        await ctx.send(f"⚠️ No history for `{item_id}`."); return
    title = m[0] if m else f"Item {item_id}"
    embed = discord.Embed(title=f"📊 Tracking: {title[:60]}", color=0x66ccff)
    for favs, price, when in rows:
        embed.add_field(name=f"🕐 {when.strftime('%m/%d %H:%M')}",
                        value=f"Favs: **{favs:,}** | Price: **{price} R$**", inline=False)
    await ctx.send(embed=embed)


# =========================================================================
# AI COMMANDS
# =========================================================================

def _db_search(patterns):
    if not patterns:
        return []
    sql = """
        SELECT id, name, favorite_count, price, total_sales, description
        FROM items
        WHERE (lower(name) LIKE ANY(%s)
            OR lower(COALESCE(description, '')) LIKE ANY(%s))
          AND favorite_count > 5
        LIMIT 2500
    """
    try:
        conn = get_db(); cur = conn.cursor()
        try:
            cur.execute(sql, (patterns, patterns))
            return cur.fetchall()
        finally:
            cur.close(); conn.close()
    except Exception as e:
        print(f"[db-search] {e}", flush=True)
        return []


def _db_search_emote_only(patterns):
    if not patterns:
        return []
    sql = """
        SELECT id, name, favorite_count, price, total_sales, description
        FROM items
        WHERE (lower(name) LIKE ANY(%s)
            OR lower(COALESCE(description, '')) LIKE ANY(%s))
          AND (asset_type_id = 61 OR asset_type_id IS NULL OR asset_type_id = 0)
          AND favorite_count > 5
        LIMIT 2500
    """
    try:
        conn = get_db(); cur = conn.cursor()
        try:
            cur.execute(sql, (patterns, patterns))
            return cur.fetchall()
        finally:
            cur.close(); conn.close()
    except Exception as e:
        print(f"[db-search-emote] {e}", flush=True)
        return []


def _term_match_count(term):
    if not term or len(term) < 3:
        return 0
    try:
        conn = get_db(); cur = conn.cursor()
        try:
            cur.execute(
                """SELECT COUNT(*) FROM (
                     SELECT 1 FROM items
                     WHERE lower(name) LIKE %s
                        OR lower(COALESCE(description,'')) LIKE %s
                     LIMIT 500
                   ) sub""",
                (f"%{term}%", f"%{term}%")
            )
            return cur.fetchone()[0] or 0
        finally:
            cur.close(); conn.close()
    except Exception:
        return 0


_VOCAB_TYPE_TO_ASSET_ID = {
    "emote": 61,
}

_EMOTE_BRIDGE_SEEDS = [
    "emote", "dance", "animation", "gesture", "expression", "reaction",
    "floss", "griddy", "dab", "wave", "shuffle", "moonwalk", "renegade",
    "dougie", "stanky", "shmoney", "krump", "hiphop", "breakdance",
    "gangnam", "salsa", "ballet", "vogue", "twist", "robot",
    "spin", "twirl", "kick", "bounce", "jump", "pose", "salute", "clap",
    "cheer", "victory", "greeting", "hello", "goodbye", "hug", "kiss",
    "idle", "sit", "crouch", "sleep", "meditate", "levitate", "float",
    "laugh", "cry", "smile", "silly", "rage", "shy", "smug", "confused",
    "kpop", "korean", "anime", "naruto", "jojo", "goku", "gojo", "luffy",
    "sigma", "rizz", "skibidi", "gyatt", "mewing", "aura", "sus", "ratio",
    "goat", "slay", "bussin", "yeet", "bruh", "fanum", "cap",
    "tiktok", "trend", "trending", "viral", "meme", "loop", "hype",
    "party", "swag", "epic", "smooth", "groove", "sway",
    "r6", "r15",
    "cute", "emo", "edgy", "coquette", "preppy", "pastel", "cyber",
]


def _get_db_vocab_sample(item_type="unknown", limit=800):
    asset_filter = _VOCAB_TYPE_TO_ASSET_ID.get((item_type or "").lower())
    rows = []
    try:
        conn = get_db(); cur = conn.cursor()
        try:
            if asset_filter is not None:
                cur.execute(
                    "SELECT name FROM items "
                    "WHERE favorite_count > 50 AND asset_type_id = %s "
                    "LIMIT 20000",
                    (asset_filter,)
                )
                rows = cur.fetchall()
                if len(rows) < 500:
                    cur.execute(
                        "SELECT name FROM items "
                        "WHERE favorite_count > 50 "
                        "LIMIT 15000"
                    )
                    rows.extend(cur.fetchall())
            else:
                cur.execute(
                    "SELECT name FROM items "
                    "WHERE favorite_count > 50 "
                    "LIMIT 15000"
                )
                rows = cur.fetchall()
        finally:
            cur.close(); conn.close()
    except Exception as e:
        print(f"[vocab-sample] {e}", flush=True)
        rows = []

    counter = Counter()
    token_re = re.compile(r"[a-z]+")
    for (name,) in rows:
        for w in set(token_re.findall((name or "").lower())):
            if len(w) >= 3 and w not in STOP_WORDS:
                counter[w] += 1

    vocab = [w for w, _ in counter.most_common(limit)]

    if (item_type or "").lower() == "emote":
        existing = set(vocab)
        for w in _EMOTE_BRIDGE_SEEDS:
            if w not in existing:
                vocab.append(w)
                existing.add(w)

    return vocab


# ==============================================================
# SATURATION CHECK + GAP ALTERNATIVES  (THREAD-SAFE)
# ==============================================================
def _find_gap_alternatives(terms, top_n=5):
    """
    Thread-safe: opens its own DB connection. Do NOT pass a cursor in.
    """
    if not terms:
        return [], {}

    valid_terms = [t.lower().strip() for t in terms
                   if len(t.strip()) >= 3 and t.lower() not in FILLER_WORDS]
    if not valid_terms:
        return [], {}

    term_stats = {}
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        patterns = [f"%{t}%" for t in valid_terms]
        cur.execute("""
            SELECT LOWER(name), favorite_count FROM items
            WHERE LOWER(name) LIKE ANY(%s) AND favorite_count > 50
            LIMIT 5000
        """, (patterns,))
        rows = cur.fetchall()

        for t in valid_terms:
            term_stats[t] = {"comp": 0, "favs_sum": 0, "favs_count": 0}

        for name, favs in rows:
            for t in valid_terms:
                if re.search(r'\b' + re.escape(t) + r'\b', name):
                    term_stats[t]["comp"] += 1
                    term_stats[t]["favs_sum"] += favs or 0
                    term_stats[t]["favs_count"] += 1

        for t in valid_terms:
            s = term_stats[t]
            s["avg_favs"] = int(s["favs_sum"] / s["favs_count"]) if s["favs_count"] else 0
    except Exception as e:
        print(f"[gap-alts] term stats: {e}", flush=True)
        return [], term_stats
    finally:
        try:
            if cur: cur.close()
        except Exception: pass
        try:
            if conn: conn.close()
        except Exception: pass

    saturated = [t for t, s in term_stats.items() if s["comp"] > 200]
    if not saturated:
        return [], term_stats

    all_candidates = defaultdict(lambda: {"count": 0, "favs": 0})
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()

        for sat_term in saturated:
            pattern = word_boundary_pattern(sat_term)
            try:
                cur.execute("""
                    SELECT name, favorite_count FROM items
                    WHERE name ~* %s AND favorite_count > 100
                    LIMIT 1000
                """, (pattern,))
                rows = cur.fetchall()
            except Exception:
                try: cur.connection.rollback()
                except Exception: pass
                continue
            for name, favs in rows:
                for w in set(extract_words(name)):
                    if w in valid_terms or w in FILLER_WORDS:
                        continue
                    all_candidates[w]["count"] += 1
                    all_candidates[w]["favs"] += favs or 0

        filtered = []
        for w, s in all_candidates.items():
            if s["count"] < 2 or s["count"] > 50:
                continue
            avg = s["favs"] / s["count"]
            if avg < 500:
                continue
            filtered.append((w, avg, s["count"]))

        if not filtered:
            return [], term_stats

        candidate_words = [w for w, _, _ in filtered[:100]]
        comp_map = defaultdict(int)
        try:
            cpatterns = [f"%{w}%" for w in candidate_words]
            cur.execute("""
                SELECT LOWER(name) FROM items
                WHERE favorite_count > 0 AND LOWER(name) LIKE ANY(%s)
            """, (cpatterns,))
            matched = cur.fetchall()
            for (name,) in matched:
                for w in candidate_words:
                    if re.search(r'\b' + re.escape(w) + r'\b', name):
                        comp_map[w] += 1
        except Exception as e:
            print(f"[gap-alts] comp check: {e}", flush=True)

        alternatives = []
        for w, avg, cnt in filtered:
            comp = comp_map.get(w, 0)
            if comp < 1 or comp > 100:
                continue
            score = avg / math.log1p(comp)
            alternatives.append({
                "word": w,
                "avg_favs": int(avg),
                "count": cnt,
                "comp": comp,
                "score": int(score),
            })

        alternatives.sort(key=lambda x: x["score"], reverse=True)
        return alternatives[:top_n], term_stats
    except Exception as e:
        print(f"[gap-alts] phase 2: {e}", flush=True)
        return [], term_stats
    finally:
        try:
            if cur: cur.close()
        except Exception: pass
        try:
            if conn: conn.close()
        except Exception: pass


def _build_allow_list(intent, max_keywords=60, gap_words=None):
    """
    Builds the allow-list of words for title generation.
    Force-includes user's original terms AND gap_words at the top.
    """
    terms = all_terms(intent)
    if not terms:
        return [], [], {}

    is_emote = (intent.get("item_type") or "").lower() == "emote"

    rows_by_id = {}
    patterns = [f"%{t}%" for t in terms if len(t) >= 2]
    if patterns:
        if is_emote:
            for r in _db_search_emote_only(patterns):
                rows_by_id[r[0]] = r
        else:
            for r in _db_search(patterns):
                rows_by_id[r[0]] = r
    direct_count = len(rows_by_id)

    expanded_terms = []
    bridge_reasoning = ""
    failed_terms = []
    if direct_count < 50:
        try:
            failed_terms = [t for t in terms if len(t) >= 3 and _term_match_count(t) < 3]
            if failed_terms:
                detected_type = (intent.get("item_type") or "unknown").lower()
                db_vocab = _get_db_vocab_sample(detected_type, 800)
                if db_vocab:
                    exp = expand_search_terms(intent, db_vocab, failed_terms)
                    expanded_terms = exp.get("expanded_terms", [])
                    bridge_reasoning = exp.get("reasoning", "")
                    if expanded_terms:
                        p2 = [f"%{t}%" for t in expanded_terms if len(t) >= 2]
                        if p2:
                            for r in _db_search(p2):
                                rows_by_id[r[0]] = r
        except Exception as e:
            print(f"[bridge] failed: {e}", flush=True)

    rows = list(rows_by_id.values())
    if not rows:
        return [], [], {
            "direct_matches": 0,
            "expansion_used": bool(expanded_terms),
            "expanded_terms": expanded_terms,
            "failed_terms": failed_terms,
            "reasoning": bridge_reasoning,
        }

    word_stats = defaultdict(lambda: {"count": 0, "favs": 0})
    bigrams = {}
    token_re = re.compile(r"[a-z0-9]+")
    for r in rows:
        name = (r[1] or "").lower()
        favs = r[2] or 0
        toks = token_re.findall(name)
        seen = set()
        for t in toks:
            if len(t) >= 2 and t not in seen:
                word_stats[t]["count"] += 1
                word_stats[t]["favs"] += favs
                seen.add(t)
        for a, b in zip(toks, toks[1:]):
            bg = f"{a} {b}"
            bigrams[bg] = bigrams.get(bg, 0) + 1

    scored_words = []
    for w, s in word_stats.items():
        if w in FILLER_WORDS:
            continue
        if s["count"] < 2:
            continue
        avg = s["favs"] / s["count"]
        score = avg / math.log1p(s["count"])
        scored_words.append((w, avg, s["count"], score))

    scored_words.sort(key=lambda x: x[3], reverse=True)
    opportunity_keywords = scored_words[:40]
    unigrams = [w for w, _, _, _ in opportunity_keywords]

    force_include = []
    for t in terms:
        t_clean = (t or "").lower().strip()
        if len(t_clean) < 3:
            continue
        if t_clean in FILLER_WORDS:
            continue
        force_include.append(t_clean)
    for w in force_include:
        if w not in unigrams:
            unigrams.insert(0, w)

    if gap_words:
        for w in gap_words:
            if w not in unigrams and w not in FILLER_WORDS:
                unigrams.insert(0, w)

    top_bigrams = [b for b, _ in sorted(bigrams.items(), key=lambda x: -x[1])[:15]
                   if not any(part in FILLER_WORDS for part in b.split())]
    allow_list = unigrams[:max_keywords]
    allow_list += [b for b in top_bigrams if b not in allow_list]

    sane_rows = [r for r in rows
                 if not r[3] or MIN_PRICE <= r[3] <= MAX_PRICE]

    GENERIC_TERMS = {
        "cute", "kawaii", "pink", "red", "white", "black", "blue", "brown",
        "green", "yellow", "purple", "orange", "gold", "silver", "gray", "grey",
        "y2k", "pastel", "grunge", "emo", "preppy", "aesthetic", "soft", "dark",
        "playful", "whimsical", "fun", "sweet", "pretty", "beautiful",
        "cool", "nice", "small", "big", "tiny", "little",
    } | FILLER_WORDS
    strong_terms = [t for t in terms if len(t) >= 3 and t.lower() not in GENERIC_TERMS]

    primary_terms = sorted(strong_terms, key=len, reverse=True)[:3]

    def _has_primary(r):
        name = (r[1] or "").lower()
        return any(t in name for t in primary_terms)

    def _match_score(r):
        name = (r[1] or "").lower()
        return sum(1 for t in strong_terms if t in name)

    relevant_rows = [r for r in sane_rows if _has_primary(r) and _match_score(r) >= 2]
    if len(relevant_rows) < 5:
        relevant_rows = [r for r in sane_rows if _has_primary(r)]
    if len(relevant_rows) < 5:
        relevant_rows = [r for r in sane_rows if _match_score(r) >= 2]
    if len(relevant_rows) < 5:
        relevant_rows = sane_rows

    items_with_favs = [r for r in relevant_rows if (r[2] or 0) > 0]
    if items_with_favs:
        top_rows = sorted(items_with_favs, key=lambda r: (r[2] or 0), reverse=True)[:10]
    else:
        top_rows = sorted(relevant_rows, key=lambda r: (r[2] or 0), reverse=True)[:10]

    top_items = [
        {"name": r[1], "favourite_count": r[2] or 0,
         "price": r[3] or 0, "total_sales": r[4] or 0}
        for r in top_rows
    ]

    prices = [r[3] for r in sane_rows if r[3] and MIN_PRICE <= r[3] <= MAX_PRICE]
    prices_sorted = sorted(prices)
    price_median = prices_sorted[len(prices_sorted) // 2] if prices_sorted else 0

    favs = sorted([r[2] or 0 for r in rows], reverse=True)
    total = len(favs)
    avg_favs = round(sum(favs) / total) if total else 0
    median_favs = favs[total // 2] if total else 0
    winner_favs = favs[max(0, total // 10)] if total else 0
    winner_count = sum(1 for f in favs if f > 10000)
    loser_count = sum(1 for f in favs if f < 1000)

    stats = {
        "count": total,
        "price_min": min(prices) if prices else 0,
        "price_avg": price_median,
        "price_max": max(prices) if prices else 0,
        "total_sales": sum((r[4] or 0) for r in rows),
        "avg_favs": avg_favs,
        "median_favs": median_favs,
        "winner_favs": winner_favs,
        "winner_count": winner_count,
        "loser_count": loser_count,
        "direct_matches": direct_count,
        "expansion_used": bool(expanded_terms),
        "expanded_terms": expanded_terms[:15],
        "failed_terms": failed_terms[:10],
        "reasoning": bridge_reasoning,
        "opportunity_keywords": [
            {"word": w, "avg_favs": int(avg), "count": c, "score": int(sc)}
            for w, avg, c, sc in opportunity_keywords[:10]
        ],
    }
    return allow_list, top_items, stats


def _fmt_ai_result(synth, verified_groups, rejected, stats, item_type="unknown",
                   total_verified=0, total_rejected=0):
    lines = ["# 🧠 UGC STRATEGY REPORT"]
    if item_type and item_type != "unknown":
        lines.append(f"*Detected item type: **{item_type.upper()}***")
    if stats.get("expansion_used"):
        lines.append("*Search tier: **Tier 2** (AI bridged missing terms)*")
    else:
        lines.append("*Search tier: **Tier 1** (direct DB hits)*")
    lines.append("")

    lines.append("## 📝 New Titles — Grouped by Strategy\n")
    if verified_groups:
        for group_name, titles in verified_groups.items():
            lines.append(f"**{group_name}**")
            for t in titles:
                lines.append(f"• `{t}`")
            lines.append("")
    else:
        lines.append("⚠️ No titles passed verification.\n")
    if total_verified:
        lines.append(f"_Total verified: **{total_verified}** · rejected: **{total_rejected}**_\n")

    sections = [
        ("search_diagnosis",              "## 🔍 Search Diagnosis"),
        ("positioning",                   "## 🎯 Positioning"),
        ("market_diagnosis",              "## 📊 Market Diagnosis"),
        ("winner_blueprint",              "## 🏆 Winner Blueprint (top 10% vs bottom 50%)"),
        ("marketplace_algorithm_playbook","## 🧠 Marketplace Algorithm Playbook"),
        ("ranking_factor_breakdown",      "## 📐 Ranking Factor Breakdown"),
        ("sale_velocity_plan",            "## 📈 Sale Velocity Plan (homepage targets)"),
        ("price_elasticity_call",         "## 💰 Price Elasticity Call"),
        ("saturation_verdict",            "## ⚠️ Saturation Verdict"),
        ("launch_window_math",            "## ⏰ Launch Window Math"),
        ("trend_intel",                   "## 🌊 Trend Intelligence"),
        ("discovery_path",                "## 🧭 Discovery Path (buyer journey)"),
        ("seo_description",               "## 📝 SEO Description (copy-paste)"),
        ("cross_promotion_play",          "## 🔗 Cross-Promotion Play"),
        ("social_playbook",               "## 📱 Social Playbook"),
        ("risk_analysis",                 "## ⚠️ Risk Analysis"),
        ("expected_performance",          "## 📈 Expected Performance"),
        ("verdict",                       "## ⚖️ Verdict"),
    ]
    for key, header in sections:
        v = synth.get(key)
        if v:
            lines.append(header)
            lines.append(str(v))
            lines.append("")

    if synth.get("killer_keywords"):
        lines.append("## 🎯 Killer Keywords")
        lines.append(", ".join(f"`{k}`" for k in synth["killer_keywords"][:15]))
        lines.append("")

    if synth.get("bonus_plays"):
        lines.append("## 💎 Bonus Plays")
        for b in synth["bonus_plays"][:5]:
            lines.append(f"- {b}")
        lines.append("")

    lines.append("---")
    lines.append(
        f"_Data: **{stats.get('count', 0):,}** items · "
        f"avg favs **{stats.get('avg_favs', 0):,}** · "
        f"winner bar **{stats.get('winner_favs', 0):,}** · "
        f"avg price **R${stats.get('price_avg', 0)}**_"
    )
    return "\n".join(lines)


@bot.command(name="ai_status")
async def ai_status(ctx):
    if is_available():
        gmodel = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
        omodel = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
        has_or = bool(os.getenv("OPENROUTER_API_KEY", "").strip())
        lines = [
            "**🧠 AI Status: ONLINE**",
            f"• Primary: `Gemini` ({gmodel})",
            f"• Fallback: {'`OpenRouter` (' + omodel + ')' if has_or else '❌ not configured'}",
            "Commands: `!brainstorm`, `!rescue`, `!analyze_image`, `!ask`, `!ai_debug`",
        ]
        await ctx.send("\n".join(lines))
    else:
        await ctx.send(
            "**🧠 AI Status: OFFLINE**\n"
            "No AI provider configured. Check `GEMINI_API_KEY` "
            "and/or `OPENROUTER_API_KEY` on Render."
        )


@bot.command(name="brainstorm")
async def brainstorm(ctx, *, description: str = ""):
    if not description.strip():
        await ctx.send("Usage: `!brainstorm rasputin dance emote from youtube`")
        return
    if not is_available():
        await ctx.send("AI is offline. Run `!ai_status`.")
        return

    progress = await ctx.send("🧠 **Pass 1:** Extracting intent...")

    intent = extract_keywords(description)
    if not intent:
        await progress.edit(content="⚠️ Pass 1 failed — using keyword-only fallback...")
        words_raw = re.findall(r"[a-z]{3,}", description.lower())
        intent = {
            "primary": words_raw, "synonyms": [], "style": [], "vibe": [],
            "colors": [], "references": [], "search_terms": words_raw,
            "item_type": "unknown", "trend_source": "none",
        }

    item_type = intent.get("item_type", "unknown")
    trend_source = intent.get("trend_source", "none")
    terms = all_terms(intent)

    await progress.edit(
        content=(f"🧠 **Pass 1 done.**\n"
                 f"• Item type: **{item_type}**\n"
                 f"• Trend source: **{trend_source}**\n"
                 f"• Terms: `{', '.join(terms[:15])}`\n\n"
                 f"🔎 **Analyzing saturation...**")
    )

    gap_alternatives = []
    term_stats = {}
    try:
        gap_alternatives, term_stats = await asyncio.to_thread(
            _find_gap_alternatives, terms, 5
        )
    except Exception as e:
        print(f"[brainstorm] gap finder failed: {e}", flush=True)

    saturated_terms = [t for t, s in term_stats.items() if s.get("comp", 0) > 200]
    if saturated_terms:
        warn = ["⚠️ **Saturation Warning** — these keywords are heavily contested:"]
        for t in saturated_terms:
            s = term_stats[t]
            warn.append(
                f"• `{t}` — **{s['comp']:,}** competitors, "
                f"avg {s['avg_favs']:,} favs"
            )
        if gap_alternatives:
            warn.append("")
            warn.append("**🕳️ Gap alternatives** — lower comp, same demand:")
            for a in gap_alternatives:
                warn.append(
                    f"• `{a['word']}` — **{a['comp']}** competitors, "
                    f"avg **{a['avg_favs']:,}** favs (score {a['score']:,})"
                )
            warn.append("")
            warn.append("_Titles below mix your keywords with these gap words._")
        else:
            warn.append("")
            warn.append("_No gap alternatives found — niche is fully saturated or DB is thin._")
        try:
            await ctx.send("\n".join(warn))
        except Exception:
            pass

    gap_words = [a["word"] for a in gap_alternatives] if gap_alternatives else None

    await progress.edit(
        content=(f"🔎 **Tier 1:** Direct DB search"
                 f"{' with gap injection' if gap_words else ''}...")
    )

    try:
        allow_list, top_items, stats = await asyncio.to_thread(
            _build_allow_list, intent, 60, gap_words
        )
    except Exception as e:
        await progress.edit(content=f"❌ DB search failed: `{e}`")
        return

    if not allow_list:
        await progress.edit(
            content=("❌ **Nothing matched.**\n"
                     "Run the enricher more for this niche.")
        )
        return

    await progress.edit(
        content=(f"📊 Matched **{stats['count']:,}** real items.\n"
                 f"• Avg favs: **{stats.get('avg_favs', 0):,}**\n"
                 f"• Winner threshold: **{stats.get('winner_favs', 0):,}** favs\n\n"
                 f"🧠 **Pass 2:** AI strategist at work...")
    )

    if stats.get("opportunity_keywords"):
        opp_lines = ["**🕳️ Top opportunity keywords in your niche:**"]
        for kw in stats["opportunity_keywords"][:8]:
            opp_lines.append(
                f"• `{kw['word']}` — **{kw['count']}** items, "
                f"avg **{kw['avg_favs']:,}** favs"
            )
        try:
            await ctx.send("\n".join(opp_lines))
        except Exception:
            pass

    # Winner vs loser analysis + algo context
    winner_data = {}
    algo_ctx = ""
    try:
        def _run_winner():
            conn = get_db(); cur = conn.cursor()
            try:
                return analyze_winners(cur, terms, top_n=40)
            finally:
                cur.close(); conn.close()
        winner_data = await asyncio.to_thread(_run_winner)
    except Exception as e:
        print(f"[brainstorm] winner analysis failed: {e}", flush=True)

    try:
        algo_ctx = build_algo_context(intent)
    except Exception as e:
        print(f"[brainstorm] algo context failed: {e}", flush=True)

    specific_moves = intent.get("specific_moves", [])

    synth = None
    try:
        synth = await asyncio.to_thread(
            synthesize_hybrid, description, allow_list, top_items, stats,
            item_type, trend_source,
            {"direct_matches": stats.get("direct_matches", 0),
             "expansion_used": stats.get("expansion_used", False),
             "expanded_terms": stats.get("expanded_terms", []),
             "failed_terms": stats.get("failed_terms", []),
             "reasoning": stats.get("reasoning", "")},
            None,
            specific_moves,
            winner_data,
            algo_ctx,
        )
    except Exception as e:
        print(f"[brainstorm] synth failed: {e}", flush=True)
        synth = None

    if not synth:
        try:
            await progress.delete()
        except Exception:
            pass

        fallback_lines = ["⚠️ **AI returned nothing — showing raw market data only.**\n"]
        fallback_lines.append(f"**🎯 Terms:** `{', '.join(terms[:15])}`")
        fallback_lines.append(
            f"**📊 Matched:** {stats['count']:,} real items · "
            f"avg favs {stats.get('avg_favs', 0):,} · "
            f"winner bar {stats.get('winner_favs', 0):,}"
        )
        if top_items:
            fallback_lines.append("\n**🥊 Top competitors:**")
            for it in top_items[:5]:
                name = (it.get("name") or "")[:60]
                favs = it.get("favourite_count") or 0
                price = it.get("price") or 0
                fallback_lines.append(f"• `{name}` — {favs:,} favs · R${price}")
        if allow_list:
            kw_str = ", ".join(f"`{k}`" for k in allow_list[:20])
            fallback_lines.append(f"\n**🎯 Allow-list:**\n{kw_str}")
        body = "\n".join(fallback_lines)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i + 1900])
        return
    # ── FULL INTELLIGENCE PIPELINE ──
    try:
        from title_pipeline import run_full_pipeline
        from rising_gaps import CATEGORY_MAP

        ai_titles = []
        for k in ("titles_safe", "titles_differentiated",
                  "titles_longtail", "titles_viral"):
            ai_titles.extend(synth.get(k) or [])

        cat_ids = None
        detected_type = (intent.get("item_type") or "").lower()
        if detected_type in CATEGORY_MAP:
            cat_ids = CATEGORY_MAP[detected_type]

        pipeline_msg = await ctx.send("🧬 **Running intelligence pipeline...**\n"
                                      "_Mining · brute-forcing · ML scoring · 60-90s_")

        def _pipeline():
            conn2 = get_db(); cur2 = conn2.cursor()
            try:
                return run_full_pipeline(
                    cur2, description, intent=intent,
                    item_type=detected_type or "emote",
                    category_asset_ids=cat_ids,
                    ai_titles=ai_titles,
                )
            finally:
                cur2.close(); conn2.close()

        pipeline_result = await asyncio.to_thread(_pipeline)

        if pipeline_result and pipeline_result.get("report"):
            body = pipeline_result["report"]
            for i in range(0, len(body), 1900):
                await ctx.send(body[i:i+1900])
                await asyncio.sleep(0.3)

        try: await pipeline_msg.delete()
        except Exception: pass
    except Exception as e:
        print(f"[brainstorm] pipeline failed: {e}", flush=True)
    all_groups = {
        "🟢 Safe (mirror winners)":          synth.get("titles_safe") or [],
        "🎯 Differentiated (unique angle)":  synth.get("titles_differentiated") or [],
        "🔎 Long-tail SEO (4+ keywords)":    synth.get("titles_longtail") or [],
        "🔥 Viral bait (meme hook)":         synth.get("titles_viral") or [],
    }
    if not any(all_groups.values()):
        all_groups = {"Titles": synth.get("titles") or []}

    verified_groups = {}
    total_verified = 0
    total_rejected = 0
    for group_name, group_titles in all_groups.items():
        v, r = verify_titles(group_titles, allow_list)
        if v:
            verified_groups[group_name] = v
            total_verified += len(v)
        total_rejected += len(r)

    body = _fmt_ai_result(synth, verified_groups, [], stats, item_type,
                          total_verified=total_verified,
                          total_rejected=total_rejected)

    try:
        await progress.delete()
    except Exception:
        pass

    for i in range(0, len(body), 1900):
        await ctx.send(body[i:i + 1900])
        await asyncio.sleep(0.3)


@bot.command(name="rescue")
async def rescue(ctx, *, description: str = ""):
    if not description.strip():
        await ctx.send(
            "Usage: `!rescue <describe your launched item + stats>`\n"
            "Example: `!rescue rasputin dance emote, launched 3 days ago, 40 favs, 0 sales, R$75`"
        )
        return
    if not is_available():
        await ctx.send("AI is offline. Run `!ai_status`.")
        return

    progress = await ctx.send("🩺 **Analyzing your item...**")

    intent = extract_keywords(description)
    if not intent:
        words_raw = re.findall(r"[a-z]{3,}", description.lower())
        intent = {
            "primary": words_raw, "synonyms": [], "style": [], "vibe": [],
            "colors": [], "references": [], "search_terms": words_raw,
            "item_type": "unknown", "trend_source": "none",
        }

    item_type = intent.get("item_type", "unknown")
    terms = all_terms(intent)

    try:
        allow_list, top_items, stats = await asyncio.to_thread(
            _build_allow_list, intent
        )
    except Exception as e:
        await progress.edit(content=f"❌ DB search failed: `{e}`")
        return

    if not allow_list:
        await progress.edit(content="❌ No DB matches. Run the enricher more.")
        return

    comp_lines = []
    for it in top_items[:10]:
        name = (it.get("name") or "")[:70]
        favs = it.get("favourite_count") or 0
        price = it.get("price") or 0
        comp_lines.append(f"• `{name}` — {favs:,} favs · R${price}")

    await progress.edit(
        content=(f"🩺 **Item type:** {item_type}\n"
                 f"**Matched {stats['count']:,} competitors** in this niche.\n\n"
                 f"🧠 **AI is diagnosing your launch and writing new titles...**")
    )

    rescue_prompt = f"""You are a Roblox UGC title doctor. A creator launched an item that is NOT SELLING.

THEIR DESCRIPTION / CURRENT SITUATION:
{description}

ITEM TYPE DETECTED: {item_type}

REAL DB KEYWORDS available (you MUST use these for titles):
{', '.join(allow_list[:60])}

TOP 10 COMPETITORS in this niche (these are what WINNERS look like):
{chr(10).join(comp_lines)}

MARKET STATS:
- competitors: {stats.get('count', 0):,}
- avg favs: {stats.get('avg_favs', 0):,}
- median favs: {stats.get('median_favs', 0):,}
- winner bar (top 10%): {stats.get('winner_favs', 0):,} favs
- avg price: R${stats.get('price_avg', 0)}
- price range: R${stats.get('price_min', 0)}-R${stats.get('price_max', 0)}

YOUR JOB — return ONLY valid JSON:

{{
  "diagnosis": "3-4 sentences: why their item probably isn't selling. Be blunt.",
  "what_winners_do": "2-3 sentences: the specific naming/styling pattern the top 10 competitors share.",
  "titles_safe": ["3 titles that MIRROR what top competitors already do"],
  "titles_differentiated": ["3 titles that use SAME niche keywords but UNIQUE angle"],
  "titles_longtail": ["2 titles with 4+ keywords packed in"],
  "titles_viral": ["2 titles that hook meme/TikTok/Sound trends"],
  "new_description": "Full 2-3 sentence SEO description, keyword-rich. Only allow-list words plus glue.",
  "price_advice": "1-2 sentences: keep, raise, or drop price? Reference real median.",
  "relaunch_plan": "2-3 sentences: concrete next action.",
  "kill_or_keep": "KEEP / RESCUE / KILL — one word plus one sentence"
}}

RULES:
- Every word in every title MUST exist in the allow-list above (plus glue words).
- Titles MUST be 3-5 words. NEVER 6+ word keyword stuffing.
- Each title must READ AS A SENTENCE, not a list of keywords.
- PREFER SPECIFIC words over generic ones (use the user's actual keywords).
- Titles in each group must feel DIFFERENT.
- Do NOT invent keywords. Do NOT fabricate stats.
- Be direct. Assume this person lost money.
- Output ONLY the JSON object.
"""

    synth = None
    try:
        synth = await asyncio.to_thread(
            synthesize_hybrid, rescue_prompt, allow_list, top_items, stats,
            item_type, intent.get("trend_source", "none"),
            {"direct_matches": stats.get("direct_matches", 0),
             "expansion_used": stats.get("expansion_used", False),
             "expanded_terms": stats.get("expanded_terms", []),
             "failed_terms": stats.get("failed_terms", []),
             "reasoning": stats.get("reasoning", "")}
        )
    except Exception as e:
        print(f"[rescue] failed: {e}", flush=True)
        synth = None

    if not synth:
        try:
            await progress.delete()
        except Exception:
            pass

        lines = ["⚠️ **AI offline — here's what winners in your niche look like.**\n"]
        lines.append(f"**Your niche:** `{', '.join(terms[:10])}`")
        lines.append(f"**Competitors:** {stats['count']:,} items")
        lines.append(f"**Winner bar:** {stats.get('winner_favs', 0):,} favs to reach top 10%")
        lines.append(f"**Median price:** R${stats.get('price_avg', 0)}")
        lines.append("\n**🥊 Top 10 competitors:**")
        lines.extend(comp_lines)
        lines.append("\n**🎯 Real keywords you could use in your title:**")
        lines.append(", ".join(f"`{k}`" for k in allow_list[:25]))
        lines.append("\nRetry `!rescue` in 5–10 minutes when AI is back.")

        body = "\n".join(lines)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i + 1900])
        return

    try:
        await progress.delete()
    except Exception:
        pass

    lines = ["# 🩺 RESCUE REPORT\n"]

    if synth.get("diagnosis"):
        lines.append("## 🔍 Diagnosis")
        lines.append(synth["diagnosis"])
        lines.append("")

    if synth.get("what_winners_do"):
        lines.append("## 🏆 What Winners Do")
        lines.append(synth["what_winners_do"])
        lines.append("")

    groups = [
        ("🟢 SAFE (mirror winners)",         synth.get("titles_safe") or []),
        ("🎯 DIFFERENTIATED (unique angle)", synth.get("titles_differentiated") or []),
        ("🔎 LONG-TAIL SEO (4+ keywords)",   synth.get("titles_longtail") or []),
        ("🔥 VIRAL BAIT (meme hook)",        synth.get("titles_viral") or []),
    ]

    lines.append("## 📝 New Titles — Grouped by Strategy\n")
    total_verified = 0
    total_rejected = 0
    for group_name, group_titles in groups:
        if not group_titles:
            continue
        verified, rejected = verify_titles(group_titles, allow_list)
        total_verified += len(verified)
        total_rejected += len(rejected)
        if verified:
            lines.append(f"**{group_name}**")
            for t in verified:
                lines.append(f"• `{t}`")
            lines.append("")
    lines.append(f"_Total verified: **{total_verified}** · rejected: **{total_rejected}**_\n")

    if synth.get("new_description"):
        lines.append("## 📝 New Description (copy-paste)")
        lines.append(synth["new_description"])
        lines.append("")

    if synth.get("price_advice"):
        lines.append("## 💰 Price Advice")
        lines.append(synth["price_advice"])
        lines.append("")

    if synth.get("relaunch_plan"):
        lines.append("## 🚀 Relaunch Plan")
        lines.append(synth["relaunch_plan"])
        lines.append("")

    if synth.get("kill_or_keep"):
        lines.append("## ⚖️ Verdict")
        lines.append(synth["kill_or_keep"])
        lines.append("")

    lines.append("---")
    lines.append("**🥊 Top 10 competitors in your niche:**")
    lines.extend(comp_lines)
    lines.append("")
    lines.append(f"_Market: {stats.get('count', 0):,} competitors · "
                 f"winner bar {stats.get('winner_favs', 0):,} favs · "
                 f"median price R${stats.get('price_avg', 0)}_")

    body = "\n".join(lines)
    for i in range(0, len(body), 1900):
        await ctx.send(body[i:i + 1900])
        await asyncio.sleep(0.3)


@bot.command(name="analyze_image")
async def analyze_image(ctx, *, description: str = ""):
    if not is_available():
        await ctx.send("AI is offline. Run `!ai_status`.")
        return

    if not ctx.message.attachments:
        await ctx.send(
            "**Usage:** attach 1-4 images and type `!analyze_image <notes>`\n"
            "Example: `!analyze_image my green slime cat beanie, 17 favs, R$75`\n"
            "_Tip: upload multiple angles (front/side/back/on-avatar) for best analysis._"
        )
        return

    attachments = ctx.message.attachments[:4]
    if len(ctx.message.attachments) > 4:
        await ctx.send("ℹ️ Using first 4 images only.")

    progress = await ctx.send(f"🖼️ **Reading {len(attachments)} image(s)...**")

    images = []
    for a in attachments:
        ctype = a.content_type or ""
        if not ctype.startswith("image/"):
            continue
        try:
            b = await a.read()
        except Exception as e:
            await progress.edit(content=f"❌ Couldn't download `{a.filename}`: `{e}`")
            return
        if len(b) > 8 * 1024 * 1024:
            await ctx.send(f"⚠️ `{a.filename}` > 8MB — skipped.")
            continue
        images.append({"bytes": b, "mime": ctype})

    if not images:
        await progress.edit(content="❌ No valid image attachments found.")
        return

    await progress.edit(
        content=f"🖼️ **Analyzing {len(images)} image(s) with Gemini vision...**")
    try:
        vision = await asyncio.to_thread(
            analyze_image_for_ugc, images, description
        )
    except Exception as e:
        print(f"[analyze_image] vision failed: {e}", flush=True)
        vision = {}

    if not vision:
        try:
            await progress.delete()
        except Exception:
            pass

        lines = ["⚠️ **Vision analysis failed (both Gemini and OpenRouter).**\n"]
        lines.append("• `!brainstorm <casual description>` — describe the item in words")
        lines.append("• `!opportunity <keyword>` — market data without AI")
        lines.append("• Retry `!analyze_image` later")
        body = "\n".join(lines)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i + 1900])
        return

    search_desc = vision.get("search_description", "")
    if not search_desc:
        parts = (vision.get("visual_style", [])
                 + vision.get("distinctive_features", [])
                 + vision.get("visual_colors", []))
        search_desc = " ".join(parts[:8]) or description or "ugc item"

    await progress.edit(
        content=(f"🖼️ **Vision done.**\n"
                 f"• Colors: `{', '.join(vision.get('visual_colors', []))}`\n"
                 f"• Style: `{', '.join(vision.get('visual_style', []))}`\n"
                 f"• Features: `{', '.join(vision.get('distinctive_features', []))}`\n"
                 f"• Item type: **{vision.get('item_type_visual', 'unknown')}**\n\n"
                 f"🔎 **Searching DB for similar items...**")
    )

    intent = extract_keywords(search_desc)
    if not intent:
        intent = {
            "primary": (vision.get("visual_style", [])
                        + vision.get("distinctive_features", [])),
            "synonyms": [], "style": vision.get("visual_style", []),
            "vibe": vision.get("visual_mood", []),
            "colors": vision.get("visual_colors", []),
            "references": [],
            "search_terms": (vision.get("distinctive_features", [])
                             + vision.get("visual_colors", [])),
            "item_type": vision.get("item_type_visual", "unknown"),
            "trend_source": "none",
        }
    intent["item_type"] = vision.get("item_type_visual", "unknown")

    try:
        allow_list, top_items, stats = await asyncio.to_thread(
            _build_allow_list, intent
        )
    except Exception as e:
        await progress.edit(content=f"❌ DB search failed: `{e}`")
        return

    if not allow_list:
        await progress.edit(
            content="❌ No DB items matched this visual description. "
                    "Run the enricher more for this category."
        )
        return

    await progress.edit(
        content=(f"📊 Matched **{stats['count']:,}** real items.\n"
                 f"🧠 **Pass 2:** Gemini strategist at work...")
    )

    full_desc = (
        f"[IMAGE DESCRIPTION] {vision.get('visual_summary', '')}\n"
        f"[DETECTED COLORS] {', '.join(vision.get('visual_colors', []))}\n"
        f"[DETECTED STYLE] {', '.join(vision.get('visual_style', []))}\n"
        f"[DETECTED MOOD] {', '.join(vision.get('visual_mood', []))}\n"
        f"[DISTINCTIVE FEATURES] {', '.join(vision.get('distinctive_features', []))}\n"
        f"[ITEM TYPE] {vision.get('item_type_visual', 'unknown')}\n"
        f"[LIKELY AESTHETIC] {', '.join(vision.get('likely_aesthetic', []))}\n"
        f"[LIKELY TREND SOURCE] {vision.get('likely_trend_source', 'none')}\n"
        f"[TREND CONTEXT] {vision.get('likely_trend_context', '')}\n"
        f"[VIBE REFERENCES] {', '.join(vision.get('vibe_references', []))}\n"
        f"[TARGET AUDIENCE] {vision.get('target_audience', '')}\n"
        f"[COLOR PSYCHOLOGY] {vision.get('color_psychology', '')}\n"
        f"[IP WARNING] {vision.get('ip_reference_warning', 'NONE')}\n"
        f"[CREATOR NOTES] {description or '(none)'}"
    )

    synth = None
    try:
        synth = await asyncio.to_thread(
            synthesize_hybrid, full_desc, allow_list, top_items, stats,
            vision.get("item_type_visual", "unknown"), "none",
            {"direct_matches": stats.get("direct_matches", 0),
             "expansion_used": stats.get("expansion_used", False),
             "expanded_terms": stats.get("expanded_terms", []),
             "failed_terms": stats.get("failed_terms", []),
             "reasoning": stats.get("reasoning", "")}
        )
    except Exception as e:
        print(f"[analyze_image] synth failed: {e}", flush=True)
        synth = None

    try:
        await progress.delete()
    except Exception:
        pass

    vision_lines = ["# 🖼️ IMAGE + CULTURE ANALYSIS\n"]
    vision_lines.append("## 👁️ What I See")
    vision_lines.append(vision.get("visual_summary", "—"))
    vision_lines.append("")
    vision_lines.append(
        f"**Colors:** {', '.join(f'`{c}`' for c in vision.get('visual_colors', []))}"
    )
    vision_lines.append(
        f"**Style:** {', '.join(f'`{s}`' for s in vision.get('visual_style', []))}"
    )
    vision_lines.append(
        f"**Features:** {', '.join(f'`{f}`' for f in vision.get('distinctive_features', []))}"
    )
    vision_lines.append(
        f"**Detected item type:** `{vision.get('item_type_visual', 'unknown')}`"
    )
    vision_lines.append("")

    if vision.get("likely_aesthetic"):
        vision_lines.append("## 🎨 Aesthetic")
        vision_lines.append(", ".join(f"`{a}`" for a in vision["likely_aesthetic"]))
        vision_lines.append("")

    if vision.get("likely_trend_context"):
        vision_lines.append("## 🌊 Trend Context")
        vision_lines.append(f"**Source:** `{vision.get('likely_trend_source', 'none')}`")
        vision_lines.append(vision["likely_trend_context"])
        vision_lines.append("")

    if vision.get("vibe_references"):
        vision_lines.append("## 🎬 Vibe References")
        vision_lines.append(", ".join(f"`{r}`" for r in vision["vibe_references"]))
        vision_lines.append("")

    if vision.get("color_psychology"):
        vision_lines.append("## 🎨 Color Psychology")
        vision_lines.append(vision["color_psychology"])
        vision_lines.append("")

    if vision.get("target_audience"):
        vision_lines.append("## 👥 Target Audience")
        vision_lines.append(vision["target_audience"])
        vision_lines.append("")

    if vision.get("composition_notes"):
        vision_lines.append("## 📐 Composition")
        vision_lines.append(vision["composition_notes"])
        vision_lines.append("")

    ip_warn = vision.get("ip_reference_warning", "NONE")
    if ip_warn and ip_warn != "NONE":
        vision_lines.append("## 🚨 IP / TRADEMARK WARNING")
        vision_lines.append(
            f"**{ip_warn}**\n"
            "Do NOT use names from that IP in the title. Roblox will remove the item."
        )
        vision_lines.append("")

    match = vision.get("title_color_match", "?")
    if match == "NO":
        vision_lines.append("## 🚨 Color Mismatch")
        vision_lines.append(
            "Title/description mentions a color that doesn't match the image. "
            "Fix the title to match what buyers see."
        )
        vision_lines.append("")
    elif match == "PARTIAL":
        vision_lines.append("## ⚠️ Partial Color Mismatch")
        vision_lines.append("Check title vs image — some colors don't align.")
        vision_lines.append("")

    vision_body = "\n".join(vision_lines)
    for i in range(0, len(vision_body), 1900):
        await ctx.send(vision_body[i:i + 1900])

    if not synth:
        await ctx.send(
            "⚠️ **Strategy synthesis failed** (both AI providers rate-limited). "
            "The vision analysis above is still valid."
        )
        return

    all_groups = {
        "🟢 Safe (mirror winners)":          synth.get("titles_safe") or [],
        "🎯 Differentiated (unique angle)":  synth.get("titles_differentiated") or [],
        "🔎 Long-tail SEO (4+ keywords)":    synth.get("titles_longtail") or [],
        "🔥 Viral bait (meme hook)":         synth.get("titles_viral") or [],
    }
    if not any(all_groups.values()):
        all_groups = {"Titles": synth.get("titles") or []}

    verified_groups = {}
    total_verified = 0
    total_rejected = 0
    for group_name, group_titles in all_groups.items():
        v, r = verify_titles(group_titles, allow_list)
        if v:
            verified_groups[group_name] = v
            total_verified += len(v)
        total_rejected += len(r)

    body = _fmt_ai_result(
        synth, verified_groups, [], stats,
        vision.get("item_type_visual", "unknown"),
        total_verified=total_verified,
        total_rejected=total_rejected,
    )

    for i in range(0, len(body), 1900):
        await ctx.send(body[i:i + 1900])
        await asyncio.sleep(0.3)


@bot.command(name="ai_debug")
async def ai_debug(ctx):
    lines = ["**🔬 AI Debug Report**\n"]

    gkey = os.getenv("GEMINI_API_KEY", "")
    gmodel = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    okey = os.getenv("OPENROUTER_API_KEY", "")
    omodel = os.getenv("OPENROUTER_MODEL",
                       "meta-llama/llama-3.3-70b-instruct:free")

    lines.append("**Env vars:**")
    lines.append(f"• GEMINI_API_KEY: `{gkey[:8] if gkey else 'MISSING'}...` (len {len(gkey)})")
    lines.append(f"• GEMINI_MODEL: `{gmodel}`")
    lines.append(f"• OPENROUTER_API_KEY: `{okey[:10] if okey else 'MISSING'}...` (len {len(okey)})")
    lines.append(f"• OPENROUTER_MODEL: `{omodel}`")
    lines.append("")

    lines.append("**Gemini test** (`say hello`):")
    if not gkey:
        lines.append("• ❌ GEMINI_API_KEY not set")
    else:
        try:
            from google import genai as g
            client = g.Client(api_key=gkey)
            resp = client.models.generate_content(
                model=gmodel,
                contents="Say only the word: hello",
            )
            text = (resp.text or "").strip()
            if text:
                lines.append(f"• ✅ Response: `{repr(text)[:80]}`")
            else:
                lines.append("• ⚠️ Empty response")
                if getattr(resp, "candidates", None):
                    fr = getattr(resp.candidates[0], "finish_reason", "?")
                    lines.append(f"• finish_reason: `{fr}`")
        except Exception as e:
            lines.append(f"• ❌ {type(e).__name__}: `{str(e)[:200]}`")
    lines.append("")

    lines.append("**OpenRouter test** (`say hello`):")
    if not okey:
        lines.append("• ❌ OPENROUTER_API_KEY not set")
    else:
        try:
            from openai import OpenAI
            or_client = OpenAI(
                api_key=okey,
                base_url="https://openrouter.ai/api/v1",
            )
            resp = or_client.chat.completions.create(
                model=omodel,
                messages=[{"role": "user", "content": "Say only the word: hello"}],
                max_tokens=20,
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                lines.append(f"• ✅ Response: `{repr(text)[:80]}`")
            else:
                lines.append("• ⚠️ Empty response")
        except Exception as e:
            lines.append(f"• ❌ {type(e).__name__}: `{str(e)[:200]}`")

    body = "\n".join(lines)
    for i in range(0, len(body), 1900):
        await ctx.send(body[i:i + 1900])


# =========================================================================
# LOAD INTEL COMMANDS
# =========================================================================
try:
    from commands_intel import register_intel_commands
    register_intel_commands(bot, get_db, ASSET_TYPE_NAMES)
    print("✅ Intel commands loaded.", flush=True)
except Exception as e:
    print(f"⚠️ Intel commands failed to load: {e}", flush=True)

try:
    from commands_advanced import register_advanced_commands
    register_advanced_commands(bot, get_db)
    print("✅ Advanced commands loaded.", flush=True)
except Exception as e:
    print(f"⚠️ Advanced commands failed to load: {e}", flush=True)

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
