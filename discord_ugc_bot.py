import os
import threading
import asyncio
import discord
from discord.ext import commands
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


def analyze_opportunity(cur, kw):
    """Rich multi-source opportunity analysis."""
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


# ============================================================
# MULTI-VIEW PAGINATOR
# ============================================================
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
                description=f"Showing **{start+1}–{min(start+self.per_page, len(items))}** of **{len(items)}** keywords.",
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
                description=f"Words that appear alongside `{seed}` — new angles.",
                color=0x66ccff
            )
            if adjs:
                half = (len(adjs) + 1) // 2
                left = " · ".join(f"`{w}`" for w in adjs[:half])
                right = " · ".join(f"`{w}`" for w in adjs[half:])
                if left:
                    embed.add_field(name="\u200b", value=left, inline=True)
                if right:
                    embed.add_field(name="\u200b", value=right, inline=True)
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
                if left:
                    embed.add_field(name="\u200b", value=left, inline=True)
                if right:
                    embed.add_field(name="\u200b", value=right, inline=True)
            else:
                embed.add_field(name="No description keywords", value="Try a different seed.", inline=False)

        elif self.view_mode == "market":
            embed = discord.Embed(
                title=f"💰 Market Info for `{seed}`",
                description="Competitive intelligence.",
                color=0xffaa00
            )
            embed.add_field(
                name="💰 Price Insight",
                value=f"Median: **{d['median_price']} R$**\nBest-seller: **{d['best_price']} R$**",
                inline=True
            )
            embed.add_field(
                name="📊 Market Health",
                value=f"Competitors: **{d['total_matches']}**\nSaturation: **{d['saturation']}**",
                inline=True
            )
            embed.add_field(
                name="👥 Creators",
                value=f"Unique: **{d['unique_creators']}**\nTop share: **{d['top_creator_share']}%**",
                inline=True
            )
            if d["top_styles"]:
                styles_str = "\n".join(f"`{s}` — {c} items" for s, c in d["top_styles"])
                embed.add_field(name="🎨 Style Patterns", value=styles_str, inline=False)
            if d["study_items"]:
                study_str = "\n".join(
                    f"`{iid}` — {name[:45]} ({favs:,} favs)"
                    for iid, name, _, favs, _, _ in d["study_items"]
                )
                embed.add_field(name="👀 Study These Top Items", value=study_str, inline=False)

        return embed

    def rebuild_buttons(self):
        self.clear_items()
        d = self.data

        kw_btn = discord.ui.Button(
            label=f"🎯 Keywords ({len(d['top_keywords'])})",
            style=discord.ButtonStyle.success if self.view_mode == "keywords" else discord.ButtonStyle.secondary,
            row=1
        )
        kw_btn.callback = self.set_keywords
        self.add_item(kw_btn)

        adj_btn = discord.ui.Button(
            label=f"🔗 Adjacent ({len(d['adjacent'])})",
            style=discord.ButtonStyle.success if self.view_mode == "adjacent" else discord.ButtonStyle.secondary,
            row=1
        )
        adj_btn.callback = self.set_adjacent
        self.add_item(adj_btn)

        desc_btn = discord.ui.Button(
            label=f"📝 Description ({len(d['description_keywords'])})",
            style=discord.ButtonStyle.success if self.view_mode == "description" else discord.ButtonStyle.secondary,
            row=1
        )
        desc_btn.callback = self.set_description
        self.add_item(desc_btn)

        market_btn = discord.ui.Button(
            label="💰 Market",
            style=discord.ButtonStyle.success if self.view_mode == "market" else discord.ButtonStyle.secondary,
            row=1
        )
        market_btn.callback = self.set_market
        self.add_item(market_btn)

        if self.view_mode == "keywords":
            total = len(d["top_keywords"])
            max_page = max(0, (total - 1) // self.per_page)

            first = discord.ui.Button(label="⏮️", style=discord.ButtonStyle.secondary,
                                      row=0, disabled=(self.page == 0))
            first.callback = self.first_page
            self.add_item(first)

            prev = discord.ui.Button(label="◀️", style=discord.ButtonStyle.primary,
                                     row=0, disabled=(self.page == 0))
            prev.callback = self.prev_page
            self.add_item(prev)

            indicator = discord.ui.Button(
                label=f"Page {self.page+1}/{max_page+1}",
                style=discord.ButtonStyle.secondary, row=0, disabled=True
            )
            self.add_item(indicator)

            nxt = discord.ui.Button(label="▶️", style=discord.ButtonStyle.primary,
                                    row=0, disabled=(self.page >= max_page))
            nxt.callback = self.next_page
            self.add_item(nxt)

            last = discord.ui.Button(label="⏭️", style=discord.ButtonStyle.secondary,
                                     row=0, disabled=(self.page >= max_page))
            last.callback = self.last_page
            self.add_item(last)

    async def set_keywords(self, interaction):
        self.view_mode = "keywords"
        self.page = 0
        self.rebuild_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def set_adjacent(self, interaction):
        self.view_mode = "adjacent"
        self.rebuild_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def set_description(self, interaction):
        self.view_mode = "description"
        self.rebuild_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def set_market(self, interaction):
        self.view_mode = "market"
        self.rebuild_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def first_page(self, interaction):
        self.page = 0
        self.rebuild_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def prev_page(self, interaction):
        self.page = max(0, self.page - 1)
        self.rebuild_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def next_page(self, interaction):
        total = len(self.data["top_keywords"])
        max_page = max(0, (total - 1) // self.per_page)
        self.page = min(max_page, self.page + 1)
        self.rebuild_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def last_page(self, interaction):
        total = len(self.data["top_keywords"])
        max_page = max(0, (total - 1) // self.per_page)
        self.page = max_page
        self.rebuild_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


# ============================================================
# SIMPLE PAGINATOR
# ============================================================
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

        first = discord.ui.Button(label="⏮️", style=discord.ButtonStyle.secondary,
                                  disabled=(self.page == 0))
        first.callback = self.first_page
        self.add_item(first)

        prev = discord.ui.Button(label="◀️", style=discord.ButtonStyle.primary,
                                 disabled=(self.page == 0))
        prev.callback = self.prev_page
        self.add_item(prev)

        indicator = discord.ui.Button(
            label=f"Page {self.page+1}/{self.max_page+1}",
            style=discord.ButtonStyle.secondary, disabled=True
        )
        self.add_item(indicator)

        nxt = discord.ui.Button(label="▶️", style=discord.ButtonStyle.primary,
                                disabled=(self.page >= self.max_page))
        nxt.callback = self.next_page
        self.add_item(nxt)

        last = discord.ui.Button(label="⏭️", style=discord.ButtonStyle.secondary,
                                 disabled=(self.page >= self.max_page))
        last.callback = self.last_page
        self.add_item(last)

    def build_embed(self):
        start = self.page * self.per_page
        end = start + self.per_page
        chunk = self.items[start:end]

        embed = discord.Embed(
            title=f"{self.title_prefix}: `{self.keyword}`",
            description=f"Showing **{start+1}–{min(end, len(self.items))}** of **{len(self.items)}** results.",
            color=self.color
        )
        for i, (w, af, c, sc) in enumerate(chunk, start + 1):
            embed.add_field(
                name=f"{i}. {w}",
                value=f"Score: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Comp: **{c:,}**",
                inline=False
            )
        embed.set_footer(text=f"Page {self.page+1} of {self.max_page+1}")
        return embed

    async def first_page(self, interaction):
        self.page = 0
        self.rebuild()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def prev_page(self, interaction):
        self.page = max(0, self.page - 1)
        self.rebuild()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def next_page(self, interaction):
        self.page = min(self.max_page, self.page + 1)
        self.rebuild()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def last_page(self, interaction):
        self.page = self.max_page
        self.rebuild()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


# ============================================================
# GUIDE HELPERS
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
    return {
        "word": word,
        "count": row[0] or 0,
        "avg_favs": row[1] or 0,
        "avg_price": row[2] or 0,
    }


def _analyze_combo(cur, words):
    if len(words) < 2:
        return {"count": 0, "avg_favs": 0, "avg_price": 0}
    conditions = " AND ".join(["name ~* %s"] * len(words))
    patterns = [word_boundary_pattern(w) for w in words]
    cur.execute(f"""
        SELECT COUNT(*), AVG(favorite_count), AVG(price)
        FROM items
        WHERE {conditions} AND favorite_count > 0
    """, tuple(patterns))
    row = cur.fetchone()
    return {
        "count": row[0] or 0,
        "avg_favs": row[1] or 0,
        "avg_price": row[2] or 0,
    }


def _get_adjacent_for(cur, word, limit=15):
    pattern = word_boundary_pattern(word)
    cur.execute("""
        SELECT name FROM items
        WHERE name ~* %s AND favorite_count > 0
        LIMIT 500
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
        SELECT name FROM items
        WHERE name ~* %s AND favorite_count > 0
        LIMIT 500
    """, (pattern,))
    rows = cur.fetchall()
    counter = Counter()
    for (name,) in rows:
        for w in set(extract_words(name)):
            if w != item_type and not matches_seed(w, item_type):
                counter[w] += 1
    alternatives = []
    for w, c in counter.most_common(50):
        if w == modifier.lower():
            continue
        if c < 2:
            continue
        stats = _analyze_word(cur, w)
        if stats["avg_favs"] > 1000:
            alternatives.append({"word": w, "count": c, "avg_favs": stats["avg_favs"]})
        if len(alternatives) >= limit:
            break
    return alternatives


def _verdict(combo_count, combo_favs, item_count, modifier_count):
    if combo_count == 0:
        if modifier_count > 0 and item_count > 100:
            return ("🔥", "JACKPOT", "Nobody has combined these words yet. Both exist and work.")
        return ("🟡", "UNTESTED", "No items combine these words. Could be a hit OR dead demand.")
    elif combo_count < 10:
        return ("🟢", "UNTAPPED", f"Only {combo_count} items combine these words. Underserved niche.")
    elif combo_count < 50:
        return ("🟡", "SWEET SPOT", f"{combo_count} items — proven demand with manageable competition.")
    elif combo_count < 200:
        return ("🟠", "COMPETITIVE", f"{combo_count} items. Need better design/price to stand out.")
    else:
        return ("🔴", "SATURATED", f"{combo_count} items. Too crowded — try a different combo.")


# ============================================================
# ULTRA-SMART GUIDE
# ============================================================
@bot.command(name="guide")
async def guide(ctx, *, idea: str = None):
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    if not idea:
        await ctx.send(
            "🧠 **UGC Research Guide**\n\n"
            "Type your idea (1–3 words):\n"
            "*Examples: `beanie` · `transparent beanie` · `emo bear hat`*\n\n"
            "Type `cancel` to exit."
        )
        try:
            msg = await bot.wait_for("message", check=check, timeout=90)
            idea = msg.content.strip().lower()
        except asyncio.TimeoutError:
            await ctx.send("⏰ Guide timed out.")
            return

    if idea in ("cancel", "exit", "stop"):
        await ctx.send("❌ Cancelled.")
        return

    idea_clean = re.sub(r'[^a-z0-9\s]', '', idea.lower()).strip()
    words = [w for w in idea_clean.split() if len(w) >= 3]

    if not words:
        await ctx.send("❌ Idea needs at least one real word (3+ letters).")
        return

    await ctx.send(f"🔍 **Analyzing `{idea_clean}`**...")

    conn = get_db(); cur = conn.cursor()

    word_stats = [_analyze_word(cur, w) for w in words]
    combo_stats = _analyze_combo(cur, words) if len(words) >= 2 else None

    if combo_stats:
        emoji, label, explanation = _verdict(
            combo_stats["count"], combo_stats["avg_favs"],
            word_stats[-1]["count"], word_stats[0]["count"]
        )
    else:
        w = word_stats[0]
        if w["count"] < 5:
            emoji, label, explanation = ("🟡", "RARE", f"Only {w['count']} items use this word.")
        elif w["count"] < 50:
            emoji, label, explanation = ("🟢", "UNTAPPED", f"Only {w['count']} items — nice niche.")
        elif w["count"] < 200:
            emoji, label, explanation = ("🟡", "HEALTHY", f"{w['count']} items — good balance.")
        elif w["count"] < 1000:
            emoji, label, explanation = ("🟠", "COMPETITIVE", f"{w['count']} items — crowded.")
        else:
            emoji, label, explanation = ("🔴", "SATURATED", f"{w['count']} items — very crowded.")

    alternatives = []
    if len(words) >= 2 and word_stats[0]["count"] < 100:
        alternatives = _find_alternatives(cur, words[0], words[-1], limit=6)

    adjacent = _get_adjacent_for(cur, words[-1], limit=15)
    data = analyze_opportunity(cur, words[-1])

    cur.close(); conn.close()

    color_map = {"🔥": 0xff2266, "🟢": 0x00ff88, "🟡": 0xffaa00, "🟠": 0xff6600, "🔴": 0xff2222}
    master = discord.Embed(
        title=f"{emoji} Verdict for `{idea_clean}`",
        description=f"**{label}** — {explanation}",
        color=color_map.get(emoji, 0x00ff88)
    )

    for i, w in enumerate(word_stats, 1):
        master.add_field(
            name=f"📊 Word {i}: `{w['word']}`",
            value=(
                f"Items: **{w['count']:,}** | "
                f"Avg Favs: **{w['avg_favs']:,.0f}** | "
                f"Avg Price: **{w['avg_price']:,.0f} R$**"
            ),
            inline=False
        )

    if combo_stats:
        master.add_field(
            name="🎯 Combo Match",
            value=(
                f"Items with ALL words: **{combo_stats['count']:,}** | "
                f"Avg Favs: **{combo_stats['avg_favs']:,.0f}** | "
                f"Avg Price: **{combo_stats['avg_price']:,.0f} R$**"
            ),
            inline=False
        )

    if alternatives:
        alt_str = "\n".join(
            f"• `{a['word']}` — {a['count']} items, avg {a['avg_favs']:,.0f} favs"
            for a in alternatives
        )
        master.add_field(
            name="🎨 Proven Alternatives",
            value=f"Instead of `{words[0]}`, try:\n{alt_str}",
            inline=False
        )

    if adjacent:
        master.add_field(
            name=f"🔗 Words that go with `{words[-1]}`",
            value=" · ".join(f"`{w}`" for w in adjacent[:12]),
            inline=False
        )

    master.set_footer(text="Full analysis below — use tabs to explore.")
    await ctx.send(embed=master)

    if data:
        view = MultiViewPaginator(data)
        await ctx.send(
            f"💎 **Full analysis of `{words[-1]}`**:",
            embed=view.build_embed(),
            view=view
        )

    await ctx.send(
        "🎨 **Want me to generate a title?**\n"
        "Reply `yes` to build one from data, or `no` to stop."
    )

    try:
        msg = await bot.wait_for("message", check=check, timeout=90)
        reply = msg.content.strip().lower()
    except asyncio.TimeoutError:
        await ctx.send("⏰ Guide complete. Use `!guide` anytime.")
        return

    if reply not in ("yes", "y", "yeah", "yep", "ok", "sure", "go"):
        await ctx.send("✅ Guide complete. Good luck!")
        return

    title_parts = []

    if combo_stats and combo_stats["count"] > 0:
        title_parts.append(" ".join(w.capitalize() for w in words))
    elif alternatives:
        alt = alternatives[0]["word"]
        title_parts.append(f"{alt.capitalize()} {' '.join(w.capitalize() for w in words[1:])}")
    else:
        title_parts.append(" ".join(w.capitalize() for w in words))

    added_adj = None
    for a in adjacent:
        if a.lower() not in " ".join(title_parts).lower() and len(a) > 3:
            added_adj = a
            break

    if added_adj:
        title_parts.append(f"– {added_adj.capitalize()}")

    suggested_title = " ".join(title_parts)[:80]

    if combo_stats and combo_stats["count"] >= 3 and combo_stats["avg_price"] > 0:
        suggested_price = int(combo_stats["avg_price"])
        price_source = "combo median"
    elif data and data["best_price"] > 0:
        suggested_price = data["best_price"]
        price_source = "best-seller median"
    elif word_stats[-1]["avg_price"] > 0:
        suggested_price = int(word_stats[-1]["avg_price"])
        price_source = f"average of `{words[-1]}` items"
    else:
        suggested_price = 100
        price_source = "default fallback"

    desc_words = []
    if data and data["description_keywords"]:
        desc_words = data["description_keywords"][:8]

    final = discord.Embed(
        title="🎨 Your Data-Backed Item",
        description="Everything below is based on real market data.",
        color=0x00ffcc
    )

    final.add_field(name="📌 Suggested Title", value=f"**{suggested_title}**", inline=False)
    final.add_field(
        name="💰 Suggested Price",
        value=f"**{suggested_price} R$** — based on {price_source}",
        inline=True
    )

    if combo_stats and combo_stats["count"] > 0:
        final.add_field(
            name="📊 Combo Data",
            value=f"{combo_stats['count']} existing items\nAvg {combo_stats['avg_favs']:,.0f} favs",
            inline=True
        )
    else:
        final.add_field(
            name="🚀 Status",
            value="First-mover advantage!\n0 existing items",
            inline=True
        )

    if desc_words:
        final.add_field(
            name="📝 Description Keywords",
            value=" · ".join(f"`{w}`" for w in desc_words),
            inline=False
        )

    final.add_field(
        name="✅ Next Steps",
        value=(
            "1. Design your UGC model\n"
            "2. Paste the title above into Roblox\n"
            "3. Copy description keywords into your item description\n"
            f"4. Set price to **{suggested_price} R$**\n"
            "5. Upload and monitor favourites for 48h"
        ),
        inline=False
    )

    await ctx.send(embed=final)
    await ctx.send("🎉 **Guide complete!** Run `!guide` again for a new idea.")


# ============================================================
# BOT EVENTS + COMMANDS
# ============================================================
@bot.event
async def on_ready():
    print(f"✅ {bot.user} is online (Market Intelligence Engine)")


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
        SELECT name, description FROM items 
        WHERE favorite_count > 0 
        ORDER BY favorite_count DESC LIMIT 1000
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    if not rows:
        await ctx.send("⚠️ No data yet. Run the enricher first.")
        return
    counter = Counter()
    for name, desc in rows:
        counter.update(extract_words(name))
        counter.update(extract_words(desc))
    embed = discord.Embed(title="📈 Top Trend Words",
                          description="Based on the top 1,000 most-favourited items.",
                          color=0xffaa00)
    for i, (w, c) in enumerate(counter.most_common(15), 1):
        embed.add_field(name=f"{i}. {w}", value=f"Appears **{c}** times", inline=False)
    await ctx.send(embed=embed)


@bot.command(name="analyze")
async def analyze(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword like `!analyze bear`")
        return
    conn = get_db(); cur = conn.cursor()
    pattern = word_boundary_pattern(kw)
    cur.execute("""
        SELECT name, description, favorite_count FROM items 
        WHERE (name ~* %s OR COALESCE(description, '') ~* %s)
          AND favorite_count > 0 LIMIT 3000
    """, (pattern, pattern))
    rows = cur.fetchall()
    if not rows:
        await ctx.send(f"⚠️ No data for `{kw}`. Try a more common word.")
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
        s = stats[w]
        af = s["favs"] / s["count"]
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
        await ctx.send("❌ Provide a keyword like `!desc_analyze emo`")
        return
    conn = get_db(); cur = conn.cursor()
    pattern = word_boundary_pattern(kw)
    cur.execute("""
        SELECT name, COALESCE(description, ''), favorite_count FROM items 
        WHERE name ~* %s 
          AND description IS NOT NULL AND description != ''
          AND favorite_count > 0
        LIMIT 2000
    """, (pattern,))
    rows = cur.fetchall()
    if not rows:
        await ctx.send(f"⚠️ No descriptions for `{kw}`.")
        cur.close(); conn.close(); return

    counter = Counter()
    word_favs = defaultdict(int)
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
        if count < 2:
            continue
        avg_favs = word_favs[w] / count
        comp = comp_map.get(w, 1) or 1
        score = avg_favs / math.log1p(comp)
        results.append((w, avg_favs, comp, score))

    results.sort(key=lambda x: x[3], reverse=True)

    if not results:
        await ctx.send(f"⚠️ Not enough description data for `{kw}`.")
        return

    view = SimplePaginator(kw, results, "📝 Hidden Description Keywords", 0xaa66ff, per_page=10)
    embed = view.build_embed()
    embed.description = f"Analyzed **{len(rows)}** descriptions from items with `{kw}` in title."
    await ctx.send(embed=embed, view=view)


@bot.command(name="opportunity")
async def opportunity(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword like `!opportunity beanie`")
        return
    conn = get_db(); cur = conn.cursor()
    data = analyze_opportunity(cur, kw)
    cur.close(); conn.close()
    if not data:
        await ctx.send(f"⚠️ No data for `{kw}`. Try `emo`, `beanie`, `grunge`, `bear`.")
        return
    view = MultiViewPaginator(data)
    await ctx.send(embed=view.build_embed(), view=view)


@bot.command(name="emote")
async def emote(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword like `!emote dance`")
        return
    conn = get_db(); cur = conn.cursor()
    data = analyze_opportunity(cur, kw)
    cur.close(); conn.close()
    if not data:
        await ctx.send(f"⚠️ No emote data for `{kw}`. Try `dance`, `wave`, `floss`.")
        return
    view = MultiViewPaginator(data)
    await ctx.send(embed=view.build_embed(), view=view)


@bot.command(name="classic")
async def classic(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword like `!classic flannel`")
        return
    conn = get_db(); cur = conn.cursor()
    data = analyze_opportunity(cur, kw)
    cur.close(); conn.close()
    if not data:
        await ctx.send(f"⚠️ No classic clothing data for `{kw}`.")
        return
    view = MultiViewPaginator(data)
    await ctx.send(embed=view.build_embed(), view=view)


@bot.command(name="gap")
async def gap(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword like `!gap emo`")
        return
    conn = get_db(); cur = conn.cursor()
    pattern = word_boundary_pattern(kw)
    cur.execute("""
        SELECT name, COALESCE(description, ''), favorite_count FROM items 
        WHERE (name ~* %s OR COALESCE(description, '') ~* %s)
          AND favorite_count > 50 LIMIT 3000
    """, (pattern, pattern))
    rows = cur.fetchall()
    if not rows:
        await ctx.send(f"⚠️ No data for `{kw}`. Try `emo`, `beanie`, `grunge`.")
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
        await ctx.send(f"⚠️ No gaps for `{kw}`. Try `emo`, `beanie`, `grunge`.")
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
        await ctx.send(f"⚠️ No gaps found for `{kw}`.")
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
        await ctx.send("⚠️ Not enough history yet. Run enricher 2+ times.")
        cur.close(); conn.close(); return
    items = []
    for iid, growth, snaps in rows:
        cur.execute("SELECT name, price FROM items WHERE id = %s", (iid,))
        r = cur.fetchone()
        name = r[0] if r else f"Item {iid}"
        price = r[1] if r else "?"
        items.append((name[:50], growth, price, growth))
    cur.close(); conn.close()

    embed = discord.Embed(
        title="🚀 Fastest Rising Items",
        description=f"Top **{len(items)}** fastest-rising items.",
        color=0xff5500
    )
    for i, (name, growth, price, _) in enumerate(items[:10], 1):
        embed.add_field(name=f"{i}. {name}",
                        value=f"📈 +**{growth:,}** favs | 💰 {price} R$",
                        inline=False)
    embed.set_footer(text="Top 10 shown")
    await ctx.send(embed=embed)


@bot.command(name="track")
async def track(ctx, item_id: int):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT name FROM items WHERE id = %s", (item_id,))
    m = cur.fetchone()
    cur.execute("""
        SELECT favorite_count, price, snapshot_at 
        FROM item_history WHERE item_id = %s 
        ORDER BY snapshot_at DESC LIMIT 15
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
                        value=f"Favs: **{favs:,}** | Price: **{price} R$**",
                        inline=False)
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
