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
    """Rich, multi-source opportunity analysis."""
    pattern = word_boundary_pattern(kw)

    # ---- 1. Get all matching items (titles + descriptions) ----
    cur.execute("""
        SELECT id, LOWER(name), COALESCE(LOWER(description), ''), 
               favorite_count, price, creator_name
        FROM items
        WHERE (name ~* %s OR COALESCE(description, '') ~* %s)
          AND favorite_count > 0
        LIMIT 3000
    """, (pattern, pattern))
    all_items = cur.fetchall()

    if not all_items:
        return None

    # ---- 2. Get search suggestions for seed ----
    cur.execute("""
        SELECT DISTINCT suggestion FROM search_suggestions 
        WHERE suggestion LIKE %s OR seed_keyword LIKE %s LIMIT 500
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
    suggs = list(set(suggs))[:50]

    # ---- 3. Score seed-containing keywords ----
    stats = defaultdict(lambda: {"favs": 0, "count": 0})
    for _, name, desc, favs, price, creator in all_items:
        # From suggestions - match against title
        for s in suggs:
            if matches_seed(name, s):
                stats[s]["favs"] += favs or 0
                stats[s]["count"] += 1

    # Bigrams from titles
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
    top_keywords = top_keywords[:10]

    # ---- 4. ADJACENT keywords (words that co-occur but don't contain seed) ----
    adjacent_counter = Counter()
    for _, name, desc, favs, _, _ in all_items:
        # Count words from titles that appear alongside the seed
        words = set(extract_words(name))
        for w in words:
            if w != kw and not matches_seed(w, kw):
                adjacent_counter[w] += 1
    adjacent = [w for w, _ in adjacent_counter.most_common(50) if _ >= 3][:10]

    # ---- 5. DESCRIPTION keywords (hidden SEO) ----
    desc_counter = Counter()
    for _, _, desc, _, _, _ in all_items:
        desc_counter.update(extract_words(desc))
    # Remove seed and adjacent dupes
    desc_only = [w for w, _ in desc_counter.most_common(50) 
                 if w != kw and w not in adjacent and _ >= 2][:8]

    # ---- 6. PRICE analysis ----
    prices = [p for _, _, _, _, p, _ in all_items if p and p > 0]
    median_price = sorted(prices)[len(prices) // 2] if prices else 0
    # Find price of top-favourited items
    top_items = sorted(all_items, key=lambda x: x[3] or 0, reverse=True)[:20]
    top_prices = [p for _, _, _, _, p, _ in top_items if p and p > 0]
    best_price = sorted(top_prices)[len(top_prices) // 2] if top_prices else median_price

    # ---- 7. CREATOR diversity ----
    creators = [c for _, _, _, _, _, c in all_items if c]
    unique_creators = len(set(creators))
    top_creator_counts = Counter(creators).most_common(1)
    top_creator_share = (top_creator_counts[0][1] / len(all_items) * 100) if top_creator_counts else 0

    # ---- 8. MARKET HEALTH ----
    total_competitors = len(all_items)
    avg_favs = sum(f or 0 for _, _, _, f, _, _ in all_items) / len(all_items)
    if total_competitors < 20:
        saturation = "🟢 Low — untapped!"
    elif total_competitors < 100:
        saturation = "🟡 Medium — healthy"
    elif total_competitors < 500:
        saturation = "🟠 High — competitive"
    else:
        saturation = "🔴 Saturated — hard to rank"

    # ---- 9. STYLE patterns ----
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
    top_styles = style_counts.most_common(5)

    # ---- 10. TOP ITEMS to study ----
    study_items = sorted(all_items, key=lambda x: x[3] or 0, reverse=True)[:3]

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
        "avg_favs": round(avg_favs, 0),
        "top_styles": top_styles,
        "study_items": study_items,
    }


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
          AND favorite_count > 0 LIMIT 2000
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
    embed = discord.Embed(title=f"🧠 Deep Analysis for `{kw}`",
                          description=f"Analyzed **{len(rows)}** items.",
                          color=0x00ff88)
    for i, (w, af, c, sc) in enumerate(results[:15], 1):
        embed.add_field(name=f"{i}. {w}",
                        value=f"Score: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Comp: **{c:,}**",
                        inline=False)
    await ctx.send(embed=embed)


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
    embed = discord.Embed(title=f"📝 Hidden Keywords in `{kw}` descriptions",
                          color=0xaa66ff)
    for i, (w, c) in enumerate(counter.most_common(15), 1):
        embed.add_field(name=f"{i}. {w}", value=f"Used in **{c}** descriptions", inline=False)
    await ctx.send(embed=embed)


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

    # ---- Build the rich embed ----
    embed = discord.Embed(
        title=f"💎 Full Opportunity Analysis: `{kw}`",
        description=f"Analyzed **{data['total_matches']}** matching items across titles + descriptions.",
        color=0xff00cc
    )

    # 1. Top keywords
    if data["top_keywords"]:
        lines = []
        for i, (p, af, c, sc) in enumerate(data["top_keywords"][:7], 1):
            lines.append(f"**{i}. {p}**\nOpp: `{sc:,.0f}` | AvgFav: `{af:,.0f}` | Comp: `{c}`")
        embed.add_field(name="🎯 Top Keywords (contain your seed)",
                        value="\n".join(lines), inline=False)

    # 2. Adjacent keywords
    if data["adjacent"]:
        adj_str = " · ".join(f"`{w}`" for w in data["adjacent"])
        embed.add_field(name="🔗 Adjacent Keywords (new angles)",
                        value=adj_str, inline=False)

    # 3. Description keywords
    if data["description_keywords"]:
        desc_str = " · ".join(f"`{w}`" for w in data["description_keywords"])
        embed.add_field(name="📝 Hidden Description Keywords",
                        value=desc_str, inline=False)

    # 4. Price insight
    embed.add_field(
        name="💰 Price Insight",
        value=f"Median: **{data['median_price']} R$** | Best-seller price: **{data['best_price']} R$**",
        inline=False
    )

    # 5. Market health
    embed.add_field(
        name="📊 Market Health",
        value=f"Competitors: **{data['total_matches']}** | Saturation: **{data['saturation']}**\n"
              f"Unique creators: **{data['unique_creators']}** | Top creator owns **{data['top_creator_share']}%**",
        inline=False
    )

    # 6. Style patterns
    if data["top_styles"]:
        styles_str = " · ".join(f"`{s}` ({c})" for s, c in data["top_styles"])
        embed.add_field(name="🎨 Style Patterns",
                        value=styles_str, inline=False)

    # 7. Study items
    if data["study_items"]:
        study_str = "\n".join(
            f"`{iid}` — {name[:35]}... ({favs:,} favs)"
            for iid, name, _, favs, _, _ in data["study_items"]
        )
        embed.add_field(name="👀 Study These Top Items",
                        value=study_str, inline=False)

    embed.set_footer(text="Use the keywords + description words in your next item.")
    await ctx.send(embed=embed)


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
    embed = discord.Embed(title=f"💃 Emote Opportunity: `{kw}`",
                          color=0xff66aa)
    if data["top_keywords"]:
        for i, (p, af, c, sc) in enumerate(data["top_keywords"][:10], 1):
            embed.add_field(name=f"{i}. {p}",
                            value=f"Score: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Comp: **{c}**",
                            inline=False)
    if data["adjacent"]:
        embed.add_field(name="🔗 Adjacent", value=" · ".join(f"`{w}`" for w in data["adjacent"]), inline=False)
    await ctx.send(embed=embed)


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
    embed = discord.Embed(title=f"👕 Classic Clothing: `{kw}`",
                          color=0x66ccff)
    if data["top_keywords"]:
        for i, (p, af, c, sc) in enumerate(data["top_keywords"][:10], 1):
            embed.add_field(name=f"{i}. {p}",
                            value=f"Score: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Comp: **{c}**",
                            inline=False)
    if data["adjacent"]:
        embed.add_field(name="🔗 Adjacent", value=" · ".join(f"`{w}`" for w in data["adjacent"]), inline=False)
    await ctx.send(embed=embed)


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
          AND favorite_count > 50 LIMIT 2000
    """, (pattern, pattern))
    rows = cur.fetchall()
    if not rows:
        await ctx.send(f"⚠️ No data for `{kw}`. Try `emo`, `beanie`, `grunge`, `chains`.")
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
            gaps.append((w, af, c))
    cur.close(); conn.close()
    gaps.sort(key=lambda x: x[1], reverse=True)
    embed = discord.Embed(title=f"🕳️ Market Gaps for `{kw}`",
                          description="High demand + low competition (<50 items).",
                          color=0x00ffcc)
    if not gaps:
        embed.add_field(name="No gaps found", value="Try `emo`, `beanie`, `grunge`.", inline=False)
    for i, (w, af, c) in enumerate(gaps[:15], 1):
        embed.add_field(name=f"{i}. {w}",
                        value=f"AvgFav: **{af:,.0f}** | Comp: **{c}**",
                        inline=False)
    await ctx.send(embed=embed)


@bot.command(name="velocity")
async def velocity(ctx):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT item_id, MAX(favorite_count) - MIN(favorite_count), COUNT(*) 
        FROM item_history GROUP BY item_id HAVING COUNT(*) >= 2 
        ORDER BY 2 DESC LIMIT 10
    """)
    rows = cur.fetchall()
    if not rows:
        await ctx.send("⚠️ Not enough history yet. Run enricher 2+ times.")
        cur.close(); conn.close(); return
    embed = discord.Embed(title="🚀 Fastest Rising Items", color=0xff5500)
    for i, (iid, growth, snaps) in enumerate(rows, 1):
        cur.execute("SELECT name, price FROM items WHERE id = %s", (iid,))
        r = cur.fetchone()
        name = r[0] if r else f"Item {iid}"
        price = r[1] if r else "?"
        embed.add_field(name=f"{i}. {name[:50]}",
                        value=f"📈 +**{growth:,}** favs | 💰 {price} R$",
                        inline=False)
    cur.close(); conn.close()
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
