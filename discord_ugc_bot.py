import os
import threading
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
    """Rich, multi-source opportunity analysis — returns LOTS of results."""
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

    # Seed-matching suggestions
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

    # Score seed-matching keywords
    stats = defaultdict(lambda: {"favs": 0, "count": 0})
    for _, name, desc, favs, price, creator in all_items:
        for s in suggs:
            if matches_seed(name, s):
                stats[s]["favs"] += favs or 0
                stats[s]["count"] += 1

    # Bigrams
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

    # Adjacent keywords
    adjacent_counter = Counter()
    for _, name, desc, favs, _, _ in all_items:
        for w in set(extract_words(name)):
            if w != kw and not matches_seed(w, kw):
                adjacent_counter[w] += 1
    adjacent = [w for w, c in adjacent_counter.most_common(60) if c >= 3]

    # Description keywords
    desc_counter = Counter()
    for _, _, desc, _, _, _ in all_items:
        desc_counter.update(extract_words(desc))
    desc_only = [w for w, c in desc_counter.most_common(60) 
                 if w != kw and w not in adjacent and c >= 2]

    # Prices
    prices = [p for _, _, _, _, p, _ in all_items if p and p > 0]
    median_price = sorted(prices)[len(prices) // 2] if prices else 0
    top_items = sorted(all_items, key=lambda x: x[3] or 0, reverse=True)[:30]
    top_prices = [p for _, _, _, _, p, _ in top_items if p and p > 0]
    best_price = sorted(top_prices)[len(top_prices) // 2] if top_prices else median_price

    # Creators
    creators = [c for _, _, _, _, _, c in all_items if c]
    unique_creators = len(set(creators))
    top_creator_counts = Counter(creators).most_common(1)
    top_creator_share = (top_creator_counts[0][1] / len(all_items) * 100) if top_creator_counts else 0

    # Saturation
    total_competitors = len(all_items)
    if total_competitors < 20:
        saturation = "🟢 Low — untapped!"
    elif total_competitors < 100:
        saturation = "🟡 Medium — healthy"
    elif total_competitors < 500:
        saturation = "🟠 High — competitive"
    else:
        saturation = "🔴 Saturated — hard to rank"

    # Styles
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

    # Study items
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
# PAGINATION VIEW with Arrow Buttons
# ============================================================
class PaginatedView(discord.ui.View):
    """Buttons for navigating multiple pages of keywords."""
    def __init__(self, keyword, items, title_prefix, color, per_page=10):
        super().__init__(timeout=180)
        self.keyword = keyword
        self.items = items
        self.title_prefix = title_prefix
        self.color = color
        self.per_page = per_page
        self.page = 0
        self.max_page = max(0, (len(items) - 1) // per_page)
        self.update_buttons()

    def update_buttons(self):
        # Disable buttons if at edges
        self.prev_btn.disabled = (self.page == 0)
        self.next_btn.disabled = (self.page >= self.max_page)
        self.first_btn.disabled = (self.page == 0)
        self.last_btn.disabled = (self.page >= self.max_page)
        self.page_indicator.label = f"Page {self.page + 1}/{self.max_page + 1}"

    def build_embed(self):
        start = self.page * self.per_page
        end = start + self.per_page
        chunk = self.items[start:end]

        embed = discord.Embed(
            title=f"{self.title_prefix}: `{self.keyword}`",
            description=f"Showing **{start + 1}–{min(end, len(self.items))}** of **{len(self.items)}** results. Use buttons to navigate.",
            color=self.color
        )
        for i, (w, af, c, sc) in enumerate(chunk, start + 1):
            embed.add_field(
                name=f"{i}. {w}",
                value=f"Score: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Comp: **{c:,}**",
                inline=False
            )
        embed.set_footer(text=f"Page {self.page + 1} of {self.max_page + 1}")
        return embed

    @discord.ui.button(label="⏮️", style=discord.ButtonStyle.secondary, row=0)
    async def first_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = 0
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.primary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="Page 1/1", style=discord.ButtonStyle.secondary, row=0, disabled=True)
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.primary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.max_page, self.page + 1)
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def last_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = self.max_page
        self.update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


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
    cur.close(); conn.close()
    embed = discord.Embed(title="📡 Market Intelligence Status", color=0x00aaff)
    embed.add_field(name="🔍 IDs Discovered", value=f"**{d:,}**", inline=True)
    embed.add_field(name="📦 Items Analyzed", value=f"**{e:,}**", inline=True)
    embed.add_field(name="📊 History Snapshots", value=f"**{h:,}**", inline=True)
    embed.add_field(name="💬 Search Suggestions", value=f"**{s:,}**", inline=True)
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

    view = PaginatedView(kw, results, "🧠 Deep Analysis", 0x00ff88, per_page=10)
    embed = view.build_embed()
    embed.description = f"Analyzed **{len(rows)}** items. Use buttons below to navigate."
    await ctx.send(embed=embed, view=view)


@bot.command(name="desc_analyze")
async def desc_analyze(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT description FROM items 
        WHERE name ~* %s AND description IS NOT NULL AND description != ''
        LIMIT 2000
    """, (word_boundary_pattern(kw),))
    rows = cur.fetchall()
    cur.close(); conn.close()
    if not rows:
        await ctx.send(f"⚠️ No descriptions for `{kw}`.")
        return
    counter = Counter()
    for (d,) in rows:
        counter.update(extract_words(d))
    items = [(w, c, 0, c) for w, c in counter.most_common(100)]
    view = PaginatedView(kw, items, "📝 Hidden Description Keywords", 0xaa66ff, per_page=10)
    await ctx.send(embed=view.build_embed(), view=view)


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

    # ---- SUMMARY EMBED ----
    summary = discord.Embed(
        title=f"💎 Full Opportunity Analysis: `{kw}`",
        description=f"Analyzed **{data['total_matches']}** matching items.",
        color=0xff00cc
    )

    # Top 5 keywords preview
    if data["top_keywords"]:
        lines = []
        for i, (p, af, c, sc) in enumerate(data["top_keywords"][:5], 1):
            lines.append(f"**{i}. {p}** — Score: `{sc:,.0f}` | AvgFav: `{af:,.0f}` | Comp: `{c}`")
        summary.add_field(name="🎯 Top 5 Keywords (see full list with buttons ⬇️)",
                          value="\n".join(lines), inline=False)

    if data["adjacent"]:
        adj_str = " · ".join(f"`{w}`" for w in data["adjacent"][:15])
        summary.add_field(name="🔗 Adjacent Keywords", value=adj_str, inline=False)

    if data["description_keywords"]:
        desc_str = " · ".join(f"`{w}`" for w in data["description_keywords"][:12])
        summary.add_field(name="📝 Hidden Description Keywords", value=desc_str, inline=False)

    summary.add_field(
        name="💰 Price Insight",
        value=f"Median: **{data['median_price']} R$** | Best-seller price: **{data['best_price']} R$**",
        inline=False
    )

    summary.add_field(
        name="📊 Market Health",
        value=f"Competitors: **{data['total_matches']}** | Saturation: **{data['saturation']}**\n"
              f"Unique creators: **{data['unique_creators']}** | Top creator owns **{data['top_creator_share']}%**",
        inline=False
    )

    if data["top_styles"]:
        styles_str = " · ".join(f"`{s}` ({c})" for s, c in data["top_styles"])
        summary.add_field(name="🎨 Style Patterns", value=styles_str, inline=False)

    if data["study_items"]:
        study_str = "\n".join(
            f"`{iid}` — {name[:40]} ({favs:,} favs)"
            for iid, name, _, favs, _, _ in data["study_items"]
        )
        summary.add_field(name="👀 Study These Top Items", value=study_str, inline=False)

    summary.set_footer(text="📄 Full keyword list sent as separate paginated message below...")
    await ctx.send(embed=summary)

    # ---- PAGINATED KEYWORD LIST ----
    if data["top_keywords"]:
        view = PaginatedView(
            kw,
            data["top_keywords"],
            "🎯 Full Keyword List",
            0x00ff88,
            per_page=10
        )
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
    if data["top_keywords"]:
        view = PaginatedView(kw, data["top_keywords"], "💃 Emote Opportunity", 0xff66aa, per_page=10)
        await ctx.send(embed=view.build_embed(), view=view)
    else:
        await ctx.send(f"⚠️ No results for `{kw}`.")


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
    if data["top_keywords"]:
        view = PaginatedView(kw, data["top_keywords"], "👕 Classic Clothing", 0x66ccff, per_page=10)
        await ctx.send(embed=view.build_embed(), view=view)
    else:
        await ctx.send(f"⚠️ No results for `{kw}`.")


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

    view = PaginatedView(kw, gaps, "🕳️ Market Gaps", 0x00ffcc, per_page=10)
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
        description=f"Top **{len(items)}** fastest-rising items since tracking began.",
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
