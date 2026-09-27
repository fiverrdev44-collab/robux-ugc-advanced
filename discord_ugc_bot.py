import os
import threading
import asyncio
import io
import json
import time
import discord
from discord.ext import commands
from datetime import datetime, timedelta
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

SLANG_WORDS = {
    "rizz", "skibidi", "griddy", "sigma", "gyatt", "mewing", "ohio",
    "fanum", "sus", "based", "cringe", "goat", "slay", "vibe", "aura",
    "flex", "yeet", "poggers", "bruh", "cap", "bet", "bussin", "ratio"
}

COLOR_WORDS = {
    "black", "white", "pink", "blue", "red", "green", "purple", "yellow",
    "orange", "gold", "silver", "brown", "beige", "gray", "grey", "neon",
    "cyan", "magenta", "crimson", "aqua"
}

STYLE_WORDS = {
    "emo", "goth", "y2k", "pastel", "kawaii", "grunge", "cyber", "coquette",
    "anime", "dark", "fluffy", "preppy", "streetwear", "academia", "vkei",
    "harajuku", "cottagecore", "fairycore", "vintage", "retro", "gothic",
    "aesthetic", "cottage", "boho", "hipster", "punk", "scene", "soft"
}

ITEM_WORDS = {
    "hat", "beanie", "crown", "cap", "hoodie", "shirt", "shoes", "wing",
    "wings", "tail", "ears", "horn", "horns", "glasses", "mask", "necklace",
    "chain", "backpack", "headphones", "emote", "dance", "hair", "face",
    "pants", "jacket", "sword", "pet", "bag", "purse", "scarf", "bandana",
    "beret", "visor", "lens", "ear", "head", "snapback", "bonnet", "balaclava"
}


def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode='require')


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
    if w in SLANG_WORDS:
        return "slang"
    if w in COLOR_WORDS:
        return "color"
    if w in STYLE_WORDS:
        return "style"
    if w in ITEM_WORDS:
        return "item"
    if w.isdigit():
        return "number"
    return "unknown"


def analyze_opportunity(cur, kw):
    pattern = word_boundary_pattern(kw)
    cur.execute("""
        SELECT id, LOWER(name), COALESCE(LOWER(description), ''), 
               favorite_count, price, creator_name
        FROM items
        WHERE (name ~* %s OR COALESCE(description, '') ~* %s)
          AND favorite_count > 0
        LIMIT 5000
    """, (pattern, pattern))
    all_items = cur.fetchall()
    if not all_items:
        return None

    cur.execute("""
        SELECT DISTINCT suggestion FROM search_suggestions 
        WHERE suggestion LIKE %s OR seed_keyword LIKE %s LIMIT 1000
    """, (f"%{kw}%", f"%{kw}%"))
    candidates = [r[0] for r in cur.fetchall()]

    suggs = []
    for s in candidates:
        s = s.strip().lower()
        if not s or len(s) < 3 or len(s) > 40:
            continue
        if s in STOP_WORDS:
            continue
        if any(junk in s for junk in ["twee", "emoji", "emoticon"]):
            continue
        if matches_seed(s, kw):
            suggs.append(s)
    suggs = list(set(suggs))[:80]

    stats = defaultdict(lambda: {"favs": 0, "count": 0})
    for _, name, desc, favs, price, creator in all_items:
        for s in suggs:
            if matches_seed(name, s):
                stats[s]["favs"] += favs or 0
                stats[s]["count"] += 1

    for _, name, _, favs, _, _ in all_items:
        words = name.split()
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            if kw in bigram and 3 < len(bigram) < 40:
                if matches_seed(bigram, kw):
                    stats[bigram]["favs"] += favs or 0
                    stats[bigram]["count"] += 1

    top_keywords = []
    for s, data in stats.items():
        if data["count"] < 2:
            continue
        af = data["favs"] / data["count"]
        top_keywords.append((s, af, data["count"], af / math.log1p(data["count"])))
    top_keywords.sort(key=lambda x: x[3], reverse=True)

    adjacent_counter = Counter()
    for _, name, desc, favs, _, _ in all_items:
        for w in set(extract_words(name)):
            if w != kw and not matches_seed(w, kw):
                adjacent_counter[w] += 1
    adjacent = [w for w, c in adjacent_counter.most_common(60) if c >= 3]

    desc_counter = Counter()
    for _, _, desc, _, _, _ in all_items:
        desc_counter.update(extract_words(desc))
    desc_only = [w for w, c in desc_counter.most_common(60)
                 if w != kw and w not in adjacent and c >= 2]

    prices = [p for _, _, _, _, p, _ in all_items if p and p > 0]
    median_price = sorted(prices)[len(prices) // 2] if prices else 0
    top_items = sorted(all_items, key=lambda x: x[3] or 0, reverse=True)[:30]
    top_prices = [p for _, _, _, _, p, _ in top_items if p and p > 0]
    best_price = sorted(top_prices)[len(top_prices) // 2] if top_prices else median_price

    creators = [c for _, _, _, _, _, c in all_items if c]
    unique_creators = len(set(creators))
    top_creator_counts = Counter(creators).most_common(1)
    top_creator_share = (top_creator_counts[0][1] / len(all_items) * 100) if top_creator_counts else 0

    total_competitors = len(all_items)
    if total_competitors < 20:
        saturation = "🟢 Low — untapped!"
    elif total_competitors < 100:
        saturation = "🟡 Medium — healthy"
    elif total_competitors < 500:
        saturation = "🟠 High — competitive"
    else:
        saturation = "🔴 Saturated — hard to rank"

    style_words = ["gothic", "cute", "emo", "y2k", "pastel", "kawaii", "grunge",
                   "cyber", "coquette", "anime", "dark", "light", "fluffy",
                   "cyberpunk", "retro", "vintage", "aesthetic", "preppy",
                   "streetwear", "cottagecore", "fairycore", "academia"]
    style_counts = Counter()
    for _, name, desc, _, _, _ in all_items:
        text = f"{name} {desc}"
        for style in style_words:
            if re.search(r'\b' + style + r'\b', text):
                style_counts[style] += 1
    top_styles = style_counts.most_common(8)

    study_items = sorted(all_items, key=lambda x: x[3] or 0, reverse=True)[:5]

    return {
        "seed": kw,
        "total_matches": len(all_items),
        "top_keywords": top_keywords,
        "adjacent": adjacent,
        "description_keywords": desc_only,
        "median_price": median_price,
        "best_price": best_price,
        "unique_creators": unique_creators,
        "top_creator_share": round(top_creator_share, 1),
        "saturation": saturation,
        "top_styles": top_styles,
        "study_items": study_items,
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
            embed = discord.Embed(
                title=f"🎯 Keywords for `{seed}`",
                description=f"Showing **{start+1}–{min(start+self.per_page, len(items))}** of **{len(items)}**.",
                color=0x00ff88
            )
            for i, (w, af, c, sc) in enumerate(chunk, start + 1):
                embed.add_field(
                    name=f"{i}. {w}",
                    value=f"Score: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Comp: **{c:,}**",
                    inline=False
                )
            embed.set_footer(text=f"Page {self.page+1}/{max_page+1} • Switch tabs below")

        elif self.view_mode == "adjacent":
            adjs = d["adjacent"]
            embed = discord.Embed(
                title=f"🔗 Adjacent Keywords for `{seed}`",
                description=f"Words that appear alongside `{seed}`.",
                color=0x66ccff
            )
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
            embed = discord.Embed(
                title=f"📝 Hidden Description Keywords for `{seed}`",
                description="SEO words top sellers bury in descriptions.",
                color=0xaa66ff
            )
            if descs:
                half = (len(descs) + 1) // 2
                left = " · ".join(f"`{w}`" for w in descs[:half])
                right = " · ".join(f"`{w}`" for w in descs[half:])
                if left: embed.add_field(name="\u200b", value=left, inline=True)
                if right: embed.add_field(name="\u200b", value=right, inline=True)
            else:
                embed.add_field(name="No description keywords", value="Try a different seed.", inline=False)

        elif self.view_mode == "market":
            embed = discord.Embed(
                title=f"💰 Market Info for `{seed}`",
                description="Competitive intelligence.",
                color=0xffaa00
            )
            embed.add_field(name="💰 Price", 
                          value=f"Median: **{d['median_price']} R$**\nBest: **{d['best_price']} R$**", inline=True)
            embed.add_field(name="📊 Health",
                          value=f"Comp: **{d['total_matches']}**\n{d['saturation']}", inline=True)
            embed.add_field(name="👥 Creators",
                          value=f"Unique: **{d['unique_creators']}**\nTop: **{d['top_creator_share']}%**", inline=True)
            if d["top_styles"]:
                styles_str = "\n".join(f"`{s}` — {c} items" for s, c in d["top_styles"])
                embed.add_field(name="🎨 Styles", value=styles_str, inline=False)
            if d["study_items"]:
                study_str = "\n".join(
                    f"`{iid}` — {name[:45]} ({favs:,} favs)"
                    for iid, name, _, favs, _, _ in d["study_items"]
                )
                embed.add_field(name="👀 Study These", value=study_str, inline=False)
        return embed

    def rebuild_buttons(self):
        self.clear_items()
        d = self.data

        kw_btn = discord.ui.Button(
            label=f"🎯 Keywords ({len(d['top_keywords'])})",
            style=discord.ButtonStyle.success if self.view_mode == "keywords" else discord.ButtonStyle.secondary, row=1)
        kw_btn.callback = self.set_keywords; self.add_item(kw_btn)

        adj_btn = discord.ui.Button(
            label=f"🔗 Adjacent ({len(d['adjacent'])})",
            style=discord.ButtonStyle.success if self.view_mode == "adjacent" else discord.ButtonStyle.secondary, row=1)
        adj_btn.callback = self.set_adjacent; self.add_item(adj_btn)

        desc_btn = discord.ui.Button(
            label=f"📝 Description ({len(d['description_keywords'])})",
            style=discord.ButtonStyle.success if self.view_mode == "description" else discord.ButtonStyle.secondary, row=1)
        desc_btn.callback = self.set_description; self.add_item(desc_btn)

        market_btn = discord.ui.Button(
            label="💰 Market",
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
        self.keyword = keyword
        self.items = items
        self.title_prefix = title_prefix
        self.color = color
        self.per_page = per_page
        self.page = 0
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
        embed = discord.Embed(
            title=f"{self.title_prefix}: `{self.keyword}`",
            description=f"Showing **{start+1}–{min(end, len(self.items))}** of **{len(self.items)}**.",
            color=self.color
        )
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


# ============================================================
# SHARED HELPERS
# ============================================================
def _analyze_word(cur, word):
    pattern = word_boundary_pattern(word)
    cur.execute("""
        SELECT COUNT(*), AVG(favorite_count), AVG(price)
        FROM items
        WHERE (name ~* %s OR COALESCE(description, '') ~* %s)
          AND favorite_count > 0
    """, (pattern, pattern))
    row = cur.fetchone()
    return {"word": word, "count": row[0] or 0, "avg_favs": row[1] or 0, "avg_price": row[2] or 0}


def _analyze_combo(cur, words):
    if len(words) < 2:
        return {"count": 0, "avg_favs": 0, "avg_price": 0}
    conditions = " AND ".join(["name ~* %s"] * len(words))
    patterns = [word_boundary_pattern(w) for w in words]
    cur.execute(f"""
        SELECT COUNT(*), AVG(favorite_count), AVG(price)
        FROM items WHERE {conditions} AND favorite_count > 0
    """, tuple(patterns))
    row = cur.fetchone()
    return {"count": row[0] or 0, "avg_favs": row[1] or 0, "avg_price": row[2] or 0}


def _get_adjacent_for(cur, word, limit=15):
    pattern = word_boundary_pattern(word)
    cur.execute("""
        SELECT name FROM items WHERE name ~* %s AND favorite_count > 0 LIMIT 500
    """, (pattern,))
    rows = cur.fetchall()
    counter = Counter()
    for (name,) in rows:
        for w in set(extract_words(name)):
            if w != word and not matches_seed(w, word):
                counter[w] += 1
    return [w for w, c in counter.most_common(limit * 2) if c >= 2][:limit]


def _find_alternatives(cur, modifier, item_type, limit=6):
    pattern = word_boundary_pattern(item_type)
    cur.execute("""
        SELECT name FROM items WHERE name ~* %s AND favorite_count > 0 LIMIT 500
    """, (pattern,))
    rows = cur.fetchall()
    counter = Counter()
    for (name,) in rows:
        for w in set(extract_words(name)):
            if w != item_type and not matches_seed(w, item_type):
                counter[w] += 1
    alternatives = []
    for w, c in counter.most_common(50):
        if w == modifier.lower() or c < 2:
            continue
        stats = _analyze_word(cur, w)
        if stats["avg_favs"] > 1000:
            alternatives.append({"word": w, "count": c, "avg_favs": stats["avg_favs"]})
        if len(alternatives) >= limit:
            break
    return alternatives


def find_matching_items(cur, words, limit=5):
    if not words:
        return []
    conditions = " OR ".join(["name ~* %s"] * len(words))
    patterns = [word_boundary_pattern(w) for w in words]
    cur.execute(f"""
        SELECT id, name, favorite_count, price FROM items
        WHERE ({conditions}) AND favorite_count > 0
        ORDER BY favorite_count DESC LIMIT %s
    """, tuple(patterns) + (limit,))
    return cur.fetchall()


def smart_verdict(word_stats, combo_stats):
    total_usage = sum(w["count"] for w in word_stats)
    top_avg = max((w["avg_favs"] for w in word_stats), default=0)
    combo_count = combo_stats["count"] if combo_stats else 0

    if total_usage == 0:
        return ("🟡", "EARLY BIRD",
                "None of these words appear in my database yet. You might be **ahead of the market**, "
                "or the phrasing might be too niche. Try `!gap <item>` to see what users ARE buying.")

    if combo_count == 0 and total_usage > 0:
        if top_avg > 50000:
            return ("🔥", "FIRST-MOVER GOLDMINE",
                    f"No item combines these words — but individually they're proven winners "
                    f"(top word averages {top_avg:,.0f} favs). **High reward, low risk.**")
        elif top_avg > 10000:
            return ("🟢", "UNTAPPED COMBO",
                    "No combo exists yet, but the words have solid demand. Great opportunity to pioneer.")
        return ("🟡", "UNTESTED", "No item combines these words. Could be sleeper hit OR dead demand.")

    if combo_count < 10:
        if combo_stats["avg_favs"] > 10000:
            return ("🔥", "JACKPOT",
                    f"Only **{combo_count}** items — but they average **{combo_stats['avg_favs']:,.0f}** favs.")
        return ("🟢", "UNTAPPED NICHE", f"Only {combo_count} items exist. Room to dominate.")
    if combo_count < 50:
        return ("🟡", "SWEET SPOT", f"{combo_count} items — proven demand with manageable competition.")
    if combo_count < 200:
        return ("🟠", "COMPETITIVE", f"{combo_count} items. Need a clear edge.")
    return ("🔴", "SATURATED", f"{combo_count} items. Too crowded — pivot or add unique modifiers.")


def build_strategy(verdict, word_stats, combo_stats, adjacent, alternatives, data):
    emoji, label, _ = verdict
    lines = []
    if emoji == "🔥":
        lines.append("**ATTACK NOW.** Rare opportunity.")
        lines.append("• Design an exceptional item")
        lines.append("• Use the exact combo in title")
        if data: lines.append(f"• Price around **{data['best_price']} R$**")
        lines.append("• Upload ASAP — window won't last")
    elif emoji == "🟢":
        lines.append("**GREEN LIGHT.** Solid opportunity.")
        lines.append("• Use top 2 keywords in title")
        if alternatives: lines.append(f"• Add `{alternatives[0]['word']}` for reach")
        if data: lines.append(f"• Price between **{data['median_price']}–{data['best_price']} R$**")
    elif emoji == "🟡":
        lines.append("**TEST IT.** Moderate signal.")
        lines.append("• Add specific modifiers (color + style + item)")
        lines.append("• Check alternatives tab for stronger angles")
        lines.append("• Study top 3 rivals")
    elif emoji == "🟠":
        lines.append("**DIFFERENTIATE.** Crowded but winnable.")
        lines.append("• Add unique style combo")
        lines.append("• Undercut by 15–20% OR go premium with better design")
        if alternatives: lines.append(f"• Try `{alternatives[0]['word']}` instead")
    else:
        lines.append("**PIVOT.** Too saturated.")
        if alternatives: lines.append(f"• Switch to `{alternatives[0]['word']}`")
        lines.append("• Or add 2 modifiers to shrink niche")
        lines.append("• Skip unless radically better design")
    return "\n".join(lines)


def get_or_create_profile(cur, discord_id, username):
    cur.execute("""
        INSERT INTO user_profiles (discord_id, username, last_active)
        VALUES (%s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (discord_id) DO UPDATE SET
            username = EXCLUDED.username, last_active = CURRENT_TIMESTAMP
        RETURNING total_consultations, first_seen
    """, (discord_id, username))
    row = cur.fetchone()
    return {"total_consultations": row[0] or 0, "first_seen": row[1]}


def increment_consultations(cur, discord_id):
    cur.execute("UPDATE user_profiles SET total_consultations = total_consultations + 1 WHERE discord_id = %s",
                (discord_id,))


def save_consultation(cur, discord_id, seed, verdict, report_text):
    emoji, label, _ = verdict
    cur.execute("""
        INSERT INTO saved_consultations (discord_id, seed, verdict_label, verdict_emoji, full_report)
        VALUES (%s, %s, %s, %s, %s)
    """, (discord_id, seed, label, emoji, report_text))


def get_past_consultations(cur, discord_id, limit=5):
    cur.execute("""
        SELECT seed, verdict_label, verdict_emoji, created_at
        FROM saved_consultations WHERE discord_id = %s
        ORDER BY created_at DESC LIMIT %s
    """, (discord_id, limit))
    return cur.fetchall()


def add_to_watchlist(cur, discord_id, keyword, baseline_favs=0):
    cur.execute("""
        INSERT INTO watchlist (discord_id, keyword, baseline_favs)
        VALUES (%s, %s, %s)
        ON CONFLICT (discord_id, keyword) DO NOTHING
        RETURNING id
    """, (discord_id, keyword, baseline_favs))
    return cur.fetchone() is not None


def get_timing_intelligence(cur, keyword):
    pattern = word_boundary_pattern(keyword)
    cur.execute("""
        SELECT created_at FROM items WHERE name ~* %s 
        AND favorite_count > 1000 AND created_at IS NOT NULL LIMIT 500
    """, (pattern,))
    rows = cur.fetchall()
    if not rows or len(rows) < 10:
        return None
    day_counts = Counter()
    hour_counts = Counter()
    for (ts,) in rows:
        try:
            if isinstance(ts, str): continue
            day_counts[ts.strftime("%A")] += 1
            hour_counts[ts.hour] += 1
        except Exception: continue
    if not day_counts: return None
    return {
        "best_day": day_counts.most_common(1)[0][0],
        "best_hours": [f"{h}:00" for h, _ in hour_counts.most_common(3)],
    }


def get_launch_window(cur, keyword):
    pattern = word_boundary_pattern(keyword)
    cur.execute("SELECT item_id FROM items WHERE name ~* %s AND favorite_count > 0 LIMIT 200", (pattern,))
    ids = [r[0] for r in cur.fetchall()]
    if not ids:
        return "🟢 No trend data — safe to launch anytime"
    cur.execute("""
        SELECT MAX(snapshot_at) - MIN(snapshot_at), AVG(favorite_count),
               MAX(favorite_count), MIN(favorite_count)
        FROM item_history WHERE item_id = ANY(%s)
    """, (ids,))
    row = cur.fetchone()
    if not row or not row[0]:
        return "🟢 Launch ASAP for first-mover advantage"
    growth = (row[2] or 0) - (row[3] or 0)
    if growth > 5000:
        return "🔥 **HOT NOW** — launch within 48h"
    elif growth > 500:
        return "📈 **Rising** — launch within 1-2 weeks"
    elif growth > 0:
        return "➡️ **Steady** — launch anytime"
    return "📉 **Cooling** — consider pivot or variant"


def get_niche_graph(cur, keyword, depth=2, top_per_level=8):
    graph = {"level_1": [], "level_2": {}}
    l1 = _get_adjacent_for(cur, keyword, limit=top_per_level)
    graph["level_1"] = l1
    for w in l1[:5]:
        l2 = _get_adjacent_for(cur, w, limit=4)
        graph["level_2"][w] = [x for x in l2 if x != keyword and x not in l1]
    return graph


def get_creator_dominance(cur, keyword):
    pattern = word_boundary_pattern(keyword)
    cur.execute("""
        SELECT creator_name, COUNT(*), SUM(favorite_count)
        FROM items WHERE name ~* %s AND favorite_count > 0 AND creator_name IS NOT NULL
        GROUP BY creator_name ORDER BY 3 DESC LIMIT 5
    """, (pattern,))
    return cur.fetchall()


def generate_ab_titles(idea, words, combo_stats, alternatives, adjacent, data):
    titles = []
    if combo_stats and combo_stats["count"] > 0:
        titles.append({
            "title": " ".join(w.capitalize() for w in words)[:80],
            "strategy": "Proven combo", "predicted": "🟢 High",
            "why": f"Matches {combo_stats['count']} existing items"
        })
    else:
        titles.append({
            "title": " ".join(w.capitalize() for w in words)[:80],
            "strategy": "First-mover", "predicted": "🟡 Medium",
            "why": "No existing combo, but individual words have demand"
        })
    if alternatives:
        alt = alternatives[0]["word"]
        rest = " ".join(w.capitalize() for w in words[1:]) if len(words) > 1 else ""
        titles.append({
            "title": f"{alt.capitalize()} {rest}".strip()[:80],
            "strategy": "Proven alternative", "predicted": "🟢 High",
            "why": f"`{alt}` averages {alternatives[0]['avg_favs']:,.0f} favs"
        })
    if adjacent and len(adjacent) >= 2:
        titles.append({
            "title": f"{words[0].capitalize()} {words[-1].capitalize()} – {adjacent[0].capitalize()} {adjacent[1].capitalize()}"[:80],
            "strategy": "Long-tail SEO", "predicted": "🟢 High",
            "why": f"Targets 4 keywords: {words[0]}, {words[-1]}, {adjacent[0]}, {adjacent[1]}"
        })
    return titles


def _compute_roi(data, combo_stats, word_stats):
    if not data:
        return None
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
    return {
        "expected_favs": int(expected_favs),
        "expected_sales": int(expected_sales),
        "expected_revenue": int(expected_revenue),
        "confidence": conf, "best_price": best_price,
    }


def _assess_risk(word_stats, combo_stats, data, trend_data):
    risks = []
    combo_count = combo_stats["count"] if combo_stats else 0
    if combo_count > 200:
        risks.append(("🔴", "Market saturation", "Try niche modifier or unique color/style"))
    elif combo_count > 50:
        risks.append(("🟠", "Medium competition", "Differentiate or undercut by 15%"))
    if combo_count == 0 and word_stats:
        top_avg = max(w["avg_favs"] for w in word_stats)
        if top_avg < 5000:
            risks.append(("🔴", "Unproven demand", "Test with a cheaper variant first"))
    if trend_data and trend_data.get("avg_growth") is not None:
        g = trend_data["avg_growth"]
        if g < -50:
            risks.append(("🔴", "Fading trend", "Pivot to a related rising keyword"))
        elif g < 0:
            risks.append(("🟡", "Slightly declining", "Move fast"))
    if data and data["top_creator_share"] > 25:
        risks.append(("🟠", f"Creator dominance ({data['top_creator_share']}%)",
                      "Study their design or target adjacent keywords"))
    if data and data["median_price"] > 0 and data["best_price"] > data["median_price"] * 2:
        risks.append(("🟡", "Price sensitivity", "Price below median to attract"))
    if not risks:
        risks.append(("🟢", "No major risks", "Solid opportunity — execute cleanly"))
    return risks


def _get_trend_signal(cur, word):
    pattern = word_boundary_pattern(word)
    cur.execute("SELECT item_id FROM items WHERE name ~* %s AND favorite_count > 0 LIMIT 100", (pattern,))
    ids = [r[0] for r in cur.fetchall()]
    if not ids: return None
    cur.execute("""
        SELECT AVG(growth), COUNT(*) FROM (
            SELECT item_id, MAX(favorite_count) - MIN(favorite_count) AS growth
            FROM item_history WHERE item_id = ANY(%s)
            GROUP BY item_id HAVING COUNT(*) >= 2
        ) sub
    """, (ids,))
    row = cur.fetchone()
    if not row or row[0] is None: return None
    return {"avg_growth": row[0], "tracked": row[1]}


def _generate_portfolio(cur, seed, alternatives, adjacent, data):
    portfolio = [{"angle": "Flagship", "idea": seed, "why": "Core concept — best design effort"}]
    last_word = seed.split()[-1] if len(seed.split()) > 1 else seed
    for alt in alternatives[:2]:
        portfolio.append({"angle": "Alternative", "idea": f"{alt['word']} {last_word}",
                          "why": f"Proven keyword ({alt['avg_favs']:,.0f} avg favs)"})
    for adj in adjacent[:2]:
        if len(adj) > 3 and adj not in seed and classify_word(adj) not in ("slang", "number"):
            portfolio.append({"angle": "Adjacent", "idea": f"{adj} {last_word}",
                              "why": "Natural keyword extension"})
    return portfolio[:5]


def _analyze_rivals(cur, seed, top_n=3):
    pattern = word_boundary_pattern(seed)
    cur.execute("""
        SELECT id, name, favorite_count, price, creator_name
        FROM items WHERE name ~* %s AND favorite_count > 0
        ORDER BY favorite_count DESC LIMIT %s
    """, (pattern, top_n))
    return cur.fetchall()


def _optimize_price(data, combo_stats, word_stats):
    if not data: return []
    median = data.get("median_price", 0) or 100
    best = data.get("best_price", 0) or median
    return [
        {"name": "🟢 Aggressive", "price": int(median * 0.7),
         "pro": "Undercut competitors. Fastest sales.", "con": "Lower margin."},
        {"name": "🎯 Sweet Spot", "price": int(best),
         "pro": "Matches best-sellers. Balanced.", "con": "Standard competition."},
        {"name": "💎 Premium", "price": int(best * 1.5),
         "pro": "Max per-sale profit.", "con": "Slower sales. Needs top design."}
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
    if styles_in_idea:
        lines.append(f"**Style:** {', '.join(styles_in_idea)}")
    if data and data.get("top_styles"):
        top = [s for s, _ in data["top_styles"][:3]]
        lines.append(f"**Popular styles:** {', '.join(top)}")
    if adjacent:
        details = [w for w in adjacent if classify_word(w) not in ("color", "style", "slang")][:5]
        if details: lines.append(f"**Details:** {', '.join(details)}")
    return "\n".join(lines)


def build_full_report(session, verdict, roi, risks, pricing, portfolio, design, timing, window, ab_titles, graph, dominance):
    emoji, label, explanation = verdict
    lines = []
    lines.append("=" * 60)
    lines.append(f"UGC CONSULTATION REPORT — {session.seed.upper()}")
    lines.append(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("=" * 60 + "\n")
    lines.append(f"VERDICT: {emoji} {label}")
    lines.append(explanation + "\n")
    lines.append("─" * 60 + "\nMARKET PULSE\n" + "─" * 60)
    for w in session.word_stats:
        lines.append(f"  {w['word']}: {w['count']} items, avg {w['avg_favs']:,.0f} favs, "
                     f"avg {w['avg_price']:,.0f} R$")
    lines.append("")
    if session.combo_stats:
        cs = session.combo_stats
        lines.append(f"COMBO: {cs['count']} items, avg {cs['avg_favs']:,.0f} favs, avg {cs['avg_price']:,.0f} R$\n")
    lines.append("─" * 60 + "\nRISK ASSESSMENT\n" + "─" * 60)
    for icon, risk, mit in risks:
        lines.append(f"  {icon} {risk}")
        lines.append(f"     → {mit}")
    lines.append("")
    if roi:
        lines.append("─" * 60 + "\nROI PROJECTION\n" + "─" * 60)
        lines.append(f"  Expected favourites: {roi['expected_favs']:,}")
        lines.append(f"  Expected sales:      {roi['expected_sales']:,}")
        lines.append(f"  Expected revenue:    {roi['expected_revenue']:,} R$")
        lines.append(f"  Confidence:          {roi['confidence']}\n")
    if pricing:
        lines.append("─" * 60 + "\nPRICING STRATEGY\n" + "─" * 60)
        for p in pricing:
            lines.append(f"  {p['name']} — {p['price']} R$")
            lines.append(f"     + {p['pro']}")
            lines.append(f"     - {p['con']}")
        lines.append("")
    if portfolio:
        lines.append("─" * 60 + "\nPORTFOLIO STRATEGY\n" + "─" * 60)
        for i, item in enumerate(portfolio, 1):
            lines.append(f"  {i}. [{item['angle']}] {item['idea']}")
            lines.append(f"     {item['why']}")
        lines.append("")
    if ab_titles:
        lines.append("─" * 60 + "\nA/B TITLE VARIANTS\n" + "─" * 60)
        for t in ab_titles:
            lines.append(f"  [{t['strategy']}] {t['predicted']}")
            lines.append(f'     "{t["title"]}"')
            lines.append(f"     Why: {t['why']}")
        lines.append("")
    if design:
        lines.append("─" * 60 + "\nDESIGN BRIEF\n" + "─" * 60)
        for line in design.split("\n"):
            lines.append(f"  {line}")
        lines.append("")
    if timing:
        lines.append("─" * 60 + "\nTIMING INTELLIGENCE\n" + "─" * 60)
        lines.append(f"  Best day: {timing['best_day']}")
        lines.append(f"  Best hours: {', '.join(timing['best_hours'])}\n")
    if window:
        lines.append(f"LAUNCH WINDOW: {window}\n")
    if dominance:
        lines.append("─" * 60 + "\nCREATOR DOMINANCE\n" + "─" * 60)
        for creator, cnt, total_favs in dominance:
            lines.append(f"  {creator}: {cnt} items, {total_favs:,} total favs")
        lines.append("")
    lines.append("=" * 60)
    lines.append("END OF REPORT")
    lines.append("=" * 60)
    return "\n".join(lines)


# ============================================================
# ELITE GUIDE — 13-STAGE CONSULTATION
# ============================================================
@bot.command(name="guide")
async def guide(ctx, *, idea: str = None):
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    async def ask_yes_no(question, timeout=180):
        await ctx.send(question)
        try:
            msg = await bot.wait_for("message", check=check, timeout=timeout)
            reply = msg.content.strip().lower()
            if reply in ("yes", "y", "yeah", "yep", "ok", "sure", "go", "yup"):
                return True
            if reply in ("cancel", "exit", "stop"):
                return None
            return False
        except asyncio.TimeoutError:
            return False

    discord_id = ctx.author.id
    username = str(ctx.author)

    # ---- Load profile / history ----
    try:
        conn = get_db(); cur = conn.cursor()
        profile = get_or_create_profile(cur, discord_id, username)
        past = get_past_consultations(cur, discord_id, limit=3)
        cur.close(); conn.close()
    except Exception:
        profile = {"total_consultations": 0, "first_seen": None}
        past = []

    greeting = ""
    if profile["total_consultations"] > 0:
        greeting = f"👋 **Welcome back, {ctx.author.display_name}.** This is consultation **#{profile['total_consultations'] + 1}**.\n\n"
        if past:
            greeting += "**Recent:**\n"
            for seed, label, emoji, _ in past[:3]:
                greeting += f"• {emoji} `{seed}` — {label}\n"
            greeting += "\n"

    if not idea:
        await ctx.send(embed=discord.Embed(
            title="🧠 Elite UGC Consultation Engine",
            description=(
                f"{greeting}"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "**13-stage market consultation** including:\n"
                "1️⃣ Word classification\n2️⃣ Market pulse\n3️⃣ Diagnosis\n"
                "4️⃣ Risk assessment\n5️⃣ Rival analysis\n6️⃣ Creator dominance\n"
                "7️⃣ Alternatives\n8️⃣ Niche keyword graph\n9️⃣ ROI projection\n"
                "🔟 Pricing strategy\n1️⃣1️⃣ Portfolio blueprint\n1️⃣2️⃣ Design brief\n"
                "1️⃣3️⃣ A/B title variants\n\n"
                "**What's your UGC idea?**\n"
                "*Examples: `y2k cyber visor` · `transparent beanie`*\n\n"
                "Type `cancel` to exit."
            ),
            color=0x00aaff
        ))
        try:
            msg = await bot.wait_for("message", check=check, timeout=180)
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

    # ---- Stage 1 ----
    classifications = [classify_word(w) for w in words]
    icons = {"slang": "⚡", "color": "🎨", "style": "✨", "item": "🧢",
             "number": "🔢", "unknown": "❔"}
    understanding = "\n".join(f"{icons[c]} `{w}` — **{c}**" for w, c in zip(words, classifications))

    await ctx.send(embed=discord.Embed(
        title=f"📖 Stage 1/13 — Understanding `{idea_clean}`",
        description=f"Parsing **{len(words)}** components:\n\n{understanding}\n\n*Scanning marketplace...*",
        color=0x00aaff
    ))

    # ---- Stage 2: Deep scan ----
    conn = get_db(); cur = conn.cursor()
    word_stats = [_analyze_word(cur, w) for w in words]
    combo_stats = _analyze_combo(cur, words) if len(words) >= 2 else None
    opportunity_data = analyze_opportunity(cur, words[-1])
    adjacent = _get_adjacent_for(cur, words[-1], limit=15)
    rivals = _analyze_rivals(cur, words[-1], top_n=3)
    trend_data = _get_trend_signal(cur, words[-1]) or {}
    timing = get_timing_intelligence(cur, words[-1])
    launch_window = get_launch_window(cur, words[-1])
    graph = get_niche_graph(cur, words[-1], depth=2, top_per_level=8)
    dominance = get_creator_dominance(cur, words[-1])

    alternatives = []
    if len(words) >= 2 and word_stats[0]["count"] < 100:
        alternatives = _find_alternatives(cur, words[0], words[-1], limit=6)

    matching = find_matching_items(cur, words, limit=5)
    portfolio = _generate_portfolio(cur, idea_clean, alternatives, adjacent, opportunity_data)

    try:
        increment_consultations(cur, discord_id)
        conn.commit()
    except Exception:
        pass
    cur.close(); conn.close()

    # ---- Market pulse ----
    pulse = discord.Embed(
        title="📊 Stage 2/13 — Market Pulse",
        description="Real data per word:",
        color=0x66ccff
    )
    for i, w in enumerate(word_stats, 1):
        if w["count"] == 0: status = "❌ Not in DB"
        elif w["count"] < 10: status = f"🟡 Rare ({w['count']})"
        elif w["count"] < 100: status = f"🟢 Niche ({w['count']})"
        elif w["count"] < 500: status = f"🟠 Popular ({w['count']})"
        else: status = f"🔴 Saturated ({w['count']})"
        pulse.add_field(
            name=f"{i}. `{w['word']}` — {status}",
            value=f"Avg Favs: **{w['avg_favs']:,.0f}** · Avg Price: **{w['avg_price']:,.0f} R$**",
            inline=False
        )
    if trend_data.get("avg_growth") is not None:
        g = trend_data["avg_growth"]
        arrow = "📈" if g > 50 else "📉" if g < -50 else "➡️"
        pulse.add_field(name=f"{arrow} Trend Signal",
                        value=f"**{g:+,.0f}** favs/snapshot across {trend_data['tracked']} items", inline=False)
    await ctx.send(embed=pulse)
    await asyncio.sleep(1)

    # ---- Stage 3: Diagnosis ----
    verdict = smart_verdict(word_stats, combo_stats)
    emoji, label, explanation = verdict
    color_map = {"🔥": 0xff2266, "🟢": 0x00ff88, "🟡": 0xffaa00, "🟠": 0xff6600, "🔴": 0xff2222}

    diag = discord.Embed(
        title=f"{emoji} Stage 3/13 — Diagnosis: {label}",
        description=f"━━━━━━━━━━━━━━━━━━━━━\n\n{explanation}",
        color=color_map.get(emoji, 0x00aaff)
    )
    if combo_stats and combo_stats["count"] > 0:
        diag.add_field(name="🎯 Combo Match",
                      value=f"**{combo_stats['count']}** items combine these words\n"
                            f"Avg Fav: **{combo_stats['avg_favs']:,.0f}** · Avg Price: **{combo_stats['avg_price']:,.0f} R$**",
                      inline=False)
    await ctx.send(embed=diag)

    # ---- Stage 4: Risks ----
    risks = _assess_risk(word_stats, combo_stats, opportunity_data, trend_data)
    risk_embed = discord.Embed(
        title="⚠️ Stage 4/13 — Risk Assessment",
        description=f"**{len(risks)} risk{'s' if len(risks) > 1 else ''}** identified:",
        color=0xff8800
    )
    for icon, risk, mit in risks:
        risk_embed.add_field(name=f"{icon} {risk}", value=f"→ *{mit}*", inline=False)
    await ctx.send(embed=risk_embed)

    # ---- Stage 5: Rivals ----
    if rivals:
        rival_embed = discord.Embed(
            title="🥊 Stage 5/13 — Rival Analysis",
            description="**Study these** before you build:",
            color=0xff3388
        )
        for iid, name, favs, price, creator in rivals:
            creator_str = f"by {creator}" if creator else "unknown"
            rival_embed.add_field(name=f"`{iid}` — {name[:55]}",
                                  value=f"**{favs:,}** favs · **{price} R$** · {creator_str}", inline=False)
        await ctx.send(embed=rival_embed)

    # ---- Stage 6: Dominance ----
    if dominance and len(dominance) > 1:
        dom_embed = discord.Embed(title="👑 Stage 6/13 — Creator Dominance",
                                  description="Who owns this niche?",
                                  color=0xffcc00)
        for creator, cnt, total_favs in dominance[:5]:
            dom_embed.add_field(name=creator,
                                value=f"**{cnt}** items · **{total_favs:,}** total favs",
                                inline=True)
        if dominance[0][2] > sum(d[2] for d in dominance[1:]) * 2:
            dom_embed.set_footer(text="⚠️ One creator dominates. Consider adjacent keywords.")
        await ctx.send(embed=dom_embed)

    # ---- Stage 7: Alternatives ----
    if alternatives:
        alt_embed = discord.Embed(
            title="🎨 Stage 7/13 — Proven Alternatives",
            description=f"Words that work with `{words[-1]}`:",
            color=0xaa66ff
        )
        alt_lines = "\n".join(
            f"• `{a['word']}` — **{a['count']}** items, avg **{a['avg_favs']:,.0f}** favs"
            for a in alternatives[:5]
        )
        alt_embed.add_field(name="\u200b", value=alt_lines, inline=False)
        await ctx.send(embed=alt_embed)

    # ---- Stage 8: Keyword graph ----
    if graph["level_1"]:
        graph_embed = discord.Embed(
            title="🕸️ Stage 8/13 — Niche Keyword Graph",
            description=f"2-level keyword map for `{words[-1]}`:",
            color=0x44ddff
        )
        graph_embed.add_field(name="🔗 Level 1 — Direct",
                              value=" · ".join(f"`{w}`" for w in graph["level_1"][:10]),
                              inline=False)
        for l1_word, l2_list in list(graph["level_2"].items())[:3]:
            if l2_list:
                graph_embed.add_field(name=f"└ `{l1_word}` →",
                                      value=" · ".join(f"`{w}`" for w in l2_list[:5]),
                                      inline=False)
        await ctx.send(embed=graph_embed)

    # ---- Ask 1 ----
    cont = await ask_yes_no(
        "📊 **Continue to ROI projection, pricing, portfolio & launch plan?**\n"
        "Reply `yes` · `skip` for strategy only · `cancel`."
    )
    if cont is None:
        await ctx.send("❌ Cancelled.")
        return

    roi = None
    pricing = None
    ab_titles = []
    design = _make_design_brief(idea_clean, word_stats, adjacent, opportunity_data)

    if cont:
        # ---- Stage 9: ROI ----
        roi = _compute_roi(opportunity_data, combo_stats, word_stats)
        if roi:
            roi_embed = discord.Embed(
                title="💰 Stage 9/13 — ROI Projection",
                description=f"Expected performance for `{idea_clean}`:",
                color=0x00ff88
            )
            roi_embed.add_field(name="📈 Expected Favs", value=f"**~{roi['expected_favs']:,}**", inline=True)
            roi_embed.add_field(name="💸 Expected Sales", value=f"**~{roi['expected_sales']:,}**", inline=True)
            roi_embed.add_field(name="💎 Expected Revenue", value=f"**~{roi['expected_revenue']:,} R$**", inline=True)
            roi_embed.add_field(name="🎯 Confidence", value=roi["confidence"], inline=True)
            roi_embed.add_field(name="💵 Recommended Price", value=f"**{roi['best_price']} R$**", inline=True)
            roi_embed.set_footer(text="Model: 40% of combo median, 30% Roblox cut applied")
            await ctx.send(embed=roi_embed)

        # ---- Stage 10: Pricing ----
        pricing = _optimize_price(opportunity_data, combo_stats, word_stats)
        if pricing:
            price_embed = discord.Embed(
                title="💵 Stage 10/13 — Pricing Strategy",
                description="Three price points with tradeoffs:",
                color=0x00ccff
            )
            for p in pricing:
                price_embed.add_field(
                    name=f"{p['name']} — **{p['price']} R$**",
                    value=f"✅ *{p['pro']}*\n⚠️ *{p['con']}*",
                    inline=False
                )
            await ctx.send(embed=price_embed)

        # ---- Stage 11: Portfolio ----
        if portfolio:
            port_embed = discord.Embed(
                title="🎨 Stage 11/13 — Portfolio Blueprint",
                description=f"Build **{len(portfolio)} related items**:",
                color=0xff66aa
            )
            for i, item in enumerate(portfolio, 1):
                port_embed.add_field(
                    name=f"{i}. [{item['angle']}] `{item['idea']}`",
                    value=f"*{item['why']}*",
                    inline=False
                )
            port_embed.set_footer(text="Release 1/week for compounding growth")
            await ctx.send(embed=port_embed)

        # ---- Stage 12: Design brief ----
        design_embed = discord.Embed(
            title="✏️ Stage 12/13 — Design Brief",
            description=design,
            color=0x9966ff
        )
        if adjacent:
            design_embed.add_field(
                name="🔗 Keywords for title/description",
                value=" · ".join(f"`{w}`" for w in adjacent[:10]),
                inline=False
            )
        await ctx.send(embed=design_embed)

        # ---- Stage 13: A/B titles ----
        ab_titles = generate_ab_titles(idea_clean, words, combo_stats,
                                        alternatives, adjacent, opportunity_data)
        if ab_titles:
            ab_embed = discord.Embed(
                title="🅰️ Stage 13/13 — A/B Title Testing",
                description="**3 title variants**:",
                color=0x00ffaa
            )
            for i, t in enumerate(ab_titles, 1):
                ab_embed.add_field(
                    name=f"Variant {chr(64+i)} — {t['strategy']} [{t['predicted']}]",
                    value=f"```{t['title']}```\n{t['why']}",
                    inline=False
                )
            await ctx.send(embed=ab_embed)

    # ---- Timing ----
    timing_embed = discord.Embed(
        title="🕐 Bonus — Timing Intelligence",
        description="When to launch:",
        color=0xffaa00
    )
    if timing:
        timing_embed.add_field(name="📅 Best Day", value=f"**{timing['best_day']}**", inline=True)
        timing_embed.add_field(name="⏰ Best Hours", value=", ".join(timing["best_hours"]), inline=True)
    timing_embed.add_field(name="🚀 Launch Window", value=launch_window, inline=False)
    await ctx.send(embed=timing_embed)

    # ---- Final strategy ----
    strategy = build_strategy(verdict, word_stats, combo_stats, adjacent, alternatives, opportunity_data)
    strategy_embed = discord.Embed(
        title="🎯 Final Strategy",
        description=f"━━━━━━━━━━━━━━━━━━━━━\n\n{strategy}",
        color=0x00ffcc
    )
    strategy_embed.set_footer(text=f"Consultation for '{idea_clean}' · {datetime.utcnow().strftime('%Y-%m-%d')}")
    await ctx.send(embed=strategy_embed)

    # ---- Watchlist ----
    watch = await ask_yes_no(f"👁️ **Add `{words[-1]}` to your watchlist?** (yes/no)")
    if watch:
        try:
            conn = get_db(); cur = conn.cursor()
            added = add_to_watchlist(cur, discord_id, words[-1], baseline_favs=0)
            conn.commit()
            cur.close(); conn.close()
            if added:
                await ctx.send(f"✅ `{words[-1]}` added to watchlist.")
            else:
                await ctx.send(f"ℹ️ Already on your watchlist.")
        except Exception as e:
            await ctx.send(f"⚠️ Couldn't save: {e}")

    # ---- Export report ----
    export = await ask_yes_no("📄 **Export full report as file?** (yes/no)")
    if export:
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
            conn.commit()
            cur.close(); conn.close()
        except Exception:
            pass
        file = discord.File(
            io.BytesIO(report.encode("utf-8")),
            filename=f"ugc_report_{idea_clean.replace(' ', '_')}.txt"
        )
        await ctx.send("📄 **Full report attached:**", file=file)

    # ---- Checklist ----
    final_title = ab_titles[0]["title"] if ab_titles else " ".join(w.capitalize() for w in words)[:80]
    final_price = roi["best_price"] if roi else 100

    checklist = discord.Embed(
        title="✅ Launch Checklist",
        description="Execute in order:",
        color=0x00ff88
    )
    checklist.add_field(name="Day 1 — Design",
                        value="☐ Model in Roblox Studio\n☐ Reference top 3 rivals\n☐ Apply design brief keywords",
                        inline=False)
    checklist.add_field(name="Day 2 — Upload",
                        value=f"☐ Title: **{final_title}**\n☐ Price: **{final_price} R$**\n"
                              f"☐ Full SEO description\n☐ Eye-catching thumbnail",
                        inline=False)
    checklist.add_field(name="Day 3–7 — Monitor",
                        value="☐ Check Creator Dashboard daily\n☐ Track favourites\n☐ Adjust price if needed",
                        inline=False)
    checklist.add_field(name="Day 8–30 — Scale",
                        value="☐ >500 favs: make color variants\n☐ <50 favs: pivot to alternative\n☐ Start next portfolio item",
                        inline=False)
    await ctx.send(embed=checklist)

    await ctx.send(
        f"🎉 **Consultation complete for `{idea_clean}`.**\n\n"
        f"**Commands:** `!watchlist` · `!history` · `!guide` for new ideas"
    )


# ============================================================
# UTILITY COMMANDS
# ============================================================
@bot.command(name="watchlist")
async def watchlist_cmd(ctx):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("""
            SELECT keyword, baseline_favs, added_at FROM watchlist
            WHERE discord_id = %s ORDER BY added_at DESC LIMIT 20
        """, (ctx.author.id,))
        rows = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        await ctx.send(f"⚠️ DB error: {e}")
        return

    if not rows:
        await ctx.send("👁️ Your watchlist is empty. Add keywords during `!guide`.")
        return

    embed = discord.Embed(
        title=f"👁️ {ctx.author.display_name}'s Watchlist",
        description=f"Tracking **{len(rows)}** keywords:",
        color=0x00aaff
    )
    for kw, baseline, added in rows:
        embed.add_field(name=f"`{kw}`", value=f"Added {added.strftime('%m/%d')}", inline=True)
    await ctx.send(embed=embed)


@bot.command(name="history")
async def history_cmd(ctx):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("""
            SELECT seed, verdict_label, verdict_emoji, created_at
            FROM saved_consultations WHERE discord_id = %s
            ORDER BY created_at DESC LIMIT 15
        """, (ctx.author.id,))
        rows = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        await ctx.send(f"⚠️ DB error: {e}")
        return

    if not rows:
        await ctx.send("📖 No consultation history yet. Run `!guide`.")
        return

    embed = discord.Embed(
        title=f"📖 {ctx.author.display_name}'s Consultation History",
        description=f"**{len(rows)}** saved consultations:",
        color=0xffaa00
    )
    for seed, label, emoji, when in rows:
        embed.add_field(
            name=f"{emoji} `{seed}` — {label}",
            value=when.strftime("%Y-%m-%d %H:%M"),
            inline=False
        )
    await ctx.send(embed=embed)


# ============================================================
# BOT EVENTS + BASE COMMANDS
# ============================================================
@bot.event
async def on_ready():
    print(f"✅ {bot.user} is online (Elite Market Intelligence Engine)")


@bot.command(name="scan_status")
async def scan_status(ctx):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM discovered_items"); d = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM items"); e = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM item_history"); h = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM search_suggestions"); s = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM learned_keywords"); l = cur.fetchone()[0]
    cur.close(); conn.close()
    embed = discord.Embed(title="📡 Market Intelligence Status", color=0x00aaff)
    embed.add_field(name="🔍 IDs Discovered", value=f"**{d:,}**", inline=True)
    embed.add_field(name="📦 Items Analyzed", value=f"**{e:,}**", inline=True)
    embed.add_field(name="📊 History Snapshots", value=f"**{h:,}**", inline=True)
    embed.add_field(name="💬 Search Suggestions", value=f"**{s:,}**", inline=True)
    embed.add_field(name="🧠 Learned Keywords", value=f"**{l:,}**", inline=True)
    await ctx.send(embed=embed)


@bot.command(name="trends")
async def trends(ctx):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT name, description FROM items WHERE favorite_count > 0 
        ORDER BY favorite_count DESC LIMIT 1000
    """)
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
    cur.execute("""
        SELECT name, description, favorite_count FROM items 
        WHERE (name ~* %s OR COALESCE(description, '') ~* %s) AND favorite_count > 0 LIMIT 3000
    """, (pattern, pattern))
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
    embed.description = f"Analyzed **{len(rows)}** items. Use buttons below."
    await ctx.send(embed=embed, view=view)


@bot.command(name="desc_analyze")
async def desc_analyze(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword.")
        return
    conn = get_db(); cur = conn.cursor()
    pattern = word_boundary_pattern(kw)
    cur.execute("""
        SELECT name, COALESCE(description, ''), favorite_count FROM items 
        WHERE name ~* %s AND description IS NOT NULL AND description != ''
          AND favorite_count > 0 LIMIT 2000
    """, (pattern,))
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
    word_list = [w for w, _ in counter.most_common(100)]
    comp_map = defaultdict(int)
    for name, desc in all_rows:
        text = f"{name} {desc}"
        for w in word_list:
            if re.search(r'\b' + re.escape(w) + r'\b', text):
                comp_map[w] += 1
    results = []
    for w, count in counter.most_common(100):
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
    cur.execute("""
        SELECT name, COALESCE(description, ''), favorite_count FROM items 
        WHERE (name ~* %s OR COALESCE(description, '') ~* %s) AND favorite_count > 50 LIMIT 3000
    """, (pattern, pattern))
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
    cur.execute("""
        SELECT item_id, MAX(favorite_count) - MIN(favorite_count), COUNT(*) 
        FROM item_history GROUP BY item_id HAVING COUNT(*) >= 2 
        ORDER BY 2 DESC LIMIT 50
    """)
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
    cur.execute("""
        SELECT favorite_count, price, snapshot_at FROM item_history 
        WHERE item_id = %s ORDER BY snapshot_at DESC LIMIT 15
    """, (item_id,))
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
