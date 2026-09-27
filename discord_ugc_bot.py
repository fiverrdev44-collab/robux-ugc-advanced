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


def matches_seed(suggestion, seed):
    return re.search(r'\b' + re.escape(seed) + r'\b', suggestion) is not None


def fast_opportunity(cur, kw):
    """Fast whole-word opportunity analysis with bigram extraction."""
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
    if not suggs:
        suggs = [kw]

    cur.execute("""
        SELECT LOWER(name), favorite_count FROM items
        WHERE favorite_count > 0 AND LOWER(name) LIKE ANY(%s)
    """, ([f"%{s}%" for s in suggs],))
    rows = cur.fetchall()

    if not rows:
        return []

    stats = defaultdict(lambda: {"favs": 0, "count": 0})
    for name, favs in rows:
        for s in suggs:
            if re.search(r'\b' + re.escape(s) + r'\b', name):
                stats[s]["favs"] += favs or 0
                stats[s]["count"] += 1

    # Bigram extraction from matching items
    extra_phrases = set()
    for name, _ in rows:
        words = name.split()
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}".strip()
            if kw in bigram and 3 < len(bigram) < 40:
                if re.search(r'\b' + re.escape(kw) + r'\b', bigram):
                    extra_phrases.add(bigram)

    for phrase in extra_phrases:
        if phrase in stats:
            continue
        matched_favs = 0
        matched_count = 0
        for name, favs in rows:
            if re.search(r'\b' + re.escape(phrase) + r'\b', name):
                matched_favs += favs or 0
                matched_count += 1
        if matched_count >= 2:
            stats[phrase]["favs"] = matched_favs
            stats[phrase]["count"] = matched_count

    results = []
    for s, data in stats.items():
        if data["count"] == 0:
            continue
        avg_f = data["favs"] / data["count"]
        results.append((s, avg_f, data["count"], avg_f / math.log1p(data["count"])))

    results.sort(key=lambda x: x[3], reverse=True)
    return results


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

    # Bulk competition count
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
        await ctx.send("❌ Provide a keyword like `!opportunity bear`")
        return
    conn = get_db(); cur = conn.cursor()
    results = fast_opportunity(cur, kw)
    cur.close(); conn.close()
    if not results:
        await ctx.send(f"⚠️ No data for `{kw}`. Try `emo`, `bear`, `beanie`, `grunge`.")
        return
    embed = discord.Embed(
        title=f"💎 Opportunity Finder: `{kw}`",
        description="Higher score = better opportunity.",
        color=0xff00cc
    )
    for i, (p, af, c, sc) in enumerate(results[:15], 1):
        embed.add_field(
            name=f"{i}. {p}",
            value=f"Opportunity: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Comp: **{c:,}**",
            inline=False
        )
    await ctx.send(embed=embed)


@bot.command(name="emote")
async def emote(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword like `!emote dance`")
        return
    conn = get_db(); cur = conn.cursor()
    results = fast_opportunity(cur, kw)
    cur.close(); conn.close()
    if not results:
        await ctx.send(f"⚠️ No emote data for `{kw}`. Try `dance`, `wave`, `floss`.")
        return
    embed = discord.Embed(title=f"💃 Emote Opportunity: `{kw}`", color=0xff66aa)
    for i, (p, af, c, sc) in enumerate(results[:15], 1):
        embed.add_field(name=f"{i}. {p}",
                        value=f"Score: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Comp: **{c:,}**",
                        inline=False)
    await ctx.send(embed=embed)


@bot.command(name="classic")
async def classic(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    if not kw:
        await ctx.send("❌ Provide a keyword like `!classic flannel`")
        return
    conn = get_db(); cur = conn.cursor()
    results = fast_opportunity(cur, kw)
    cur.close(); conn.close()
    if not results:
        await ctx.send(f"⚠️ No classic clothing data for `{kw}`.")
        return
    embed = discord.Embed(title=f"👕 Classic Clothing: `{kw}`", color=0x66ccff)
    for i, (p, af, c, sc) in enumerate(results[:15], 1):
        embed.add_field(name=f"{i}. {p}",
                        value=f"Score: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Comp: **{c:,}**",
                        inline=False)
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
        embed = discord.Embed(title=f"🕳️ Market Gaps for `{kw}`",
                              description="High demand + low competition.",
                              color=0x00ffcc)
        embed.add_field(name="No data found",
                        value="Try `emo`, `beanie`, `grunge`, `chains`, `crown`.",
                        inline=False)
        await ctx.send(embed=embed)
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
        embed = discord.Embed(title=f"🕳️ Market Gaps for `{kw}`",
                              description="High demand + low competition.",
                              color=0x00ffcc)
        embed.add_field(name="No gaps found",
                        value="Try `emo`, `beanie`, `grunge`, `chains`.",
                        inline=False)
        await ctx.send(embed=embed)
        cur.close(); conn.close(); return

    # Bulk competition count
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
        embed.add_field(name="No gaps found",
                        value="Try `emo`, `beanie`, `grunge`, `chains`.",
                        inline=False)
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
