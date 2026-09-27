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
    "has","had","have","did","more","some","like","this","will","use","used"
}


def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode='require')


def extract_words(text):
    if not text:
        return []
    words = re.findall(r"[a-zA-Z]+", text.lower())
    return [w for w in words if len(w) > 2 and w not in STOP_WORDS]


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
    """Top words in most-favourited items."""
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
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT name, description, favorite_count FROM items 
        WHERE (LOWER(name) LIKE %s OR LOWER(description) LIKE %s)
          AND favorite_count > 0 LIMIT 2000
    """, (f"%{kw}%", f"%{kw}%"))
    rows = cur.fetchall()
    if not rows:
        await ctx.send(f"⚠️ No data for `{kw}` yet.")
        cur.close(); conn.close(); return
    stats = defaultdict(lambda: {"favs": 0, "count": 0})
    for name, desc, favs in rows:
        for w in set(extract_words(f"{name} {desc}")):
            if w == kw: continue
            stats[w]["favs"] += (favs or 0)
            stats[w]["count"] += 1
    results = []
    for w, s in stats.items():
        if s["count"] < 3: continue
        af = s["favs"] / s["count"]
        cur.execute("SELECT COUNT(*) FROM items WHERE LOWER(name) LIKE %s", (f"%{w}%",))
        c = cur.fetchone()[0] or 1
        results.append((w, af, c, af / math.log1p(c)))
    cur.close(); conn.close()
    results.sort(key=lambda x: x[3], reverse=True)
    embed = discord.Embed(title=f"🧠 Deep Analysis for `{kw}`",
                          description=f"Analyzed **{len(rows)}** items.",
                          color=0x00ff88)
    for i, (w, af, c, sc) in enumerate(results[:10], 1):
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
        WHERE LOWER(name) LIKE %s AND description IS NOT NULL AND description != ''
        LIMIT 2000
    """, (f"%{kw}%",))
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
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT suggestion FROM search_suggestions 
        WHERE suggestion LIKE %s OR seed_keyword LIKE %s LIMIT 100
    """, (f"%{kw}%", f"%{kw}%"))
    suggs = [r[0] for r in cur.fetchall()] or [kw]
    results = []
    for phrase in suggs:
        cur.execute("SELECT COUNT(*) FROM items WHERE LOWER(name) LIKE %s", (f"%{phrase}%",))
        c = cur.fetchone()[0] or 1
        cur.execute("""
            SELECT AVG(favorite_count), COUNT(*) FROM items 
            WHERE LOWER(name) LIKE %s AND favorite_count > 0
        """, (f"%{phrase}%",))
        af, cnt = cur.fetchone()
        if not cnt: continue
        af = af or 0
        score = af / math.log1p(c)
        results.append((phrase, af, c, score))
    cur.close(); conn.close()
    results.sort(key=lambda x: x[3], reverse=True)
    embed = discord.Embed(title=f"💎 Opportunity Finder: `{kw}`",
                          description="Higher score = better opportunity.",
                          color=0xff00cc)
    for i, (p, af, c, sc) in enumerate(results[:10], 1):
        embed.add_field(name=f"{i}. {p}",
                        value=f"Opportunity: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Comp: **{c:,}**",
                        inline=False)
    await ctx.send(embed=embed)


@bot.command(name="gap")
async def gap(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT name, description, favorite_count FROM items 
        WHERE (LOWER(name) LIKE %s OR LOWER(description) LIKE %s)
          AND favorite_count > 50 LIMIT 2000
    """, (f"%{kw}%", f"%{kw}%"))
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
    gaps = []
    for w, s in stats.items():
        if s["count"] < 2 or s["count"] > 20: continue
        af = s["favs"] / s["count"]
        if af < 500: continue
        cur.execute("SELECT COUNT(*) FROM items WHERE LOWER(name) LIKE %s", (f"%{w}%",))
        c = cur.fetchone()[0] or 1
        if c < 50:
            gaps.append((w, af, c))
    cur.close(); conn.close()
    gaps.sort(key=lambda x: x[1], reverse=True)
    embed = discord.Embed(title=f"🕳️ Market Gaps for `{kw}`",
                          description="High demand + low competition.",
                          color=0x00ffcc)
    if not gaps:
        embed.add_field(name="No gaps found", value="Try a different seed.")
    for i, (w, af, c) in enumerate(gaps[:10], 1):
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


@bot.command(name="emote")
async def emote(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT suggestion FROM search_suggestions 
        WHERE suggestion LIKE %s OR seed_keyword LIKE %s LIMIT 100
    """, (f"%{kw}%", f"%{kw}%"))
    suggs = [r[0] for r in cur.fetchall()] or [kw]
    results = []
    for phrase in suggs:
        cur.execute("SELECT COUNT(*) FROM items WHERE LOWER(name) LIKE %s", (f"%{phrase}%",))
        c = cur.fetchone()[0] or 1
        cur.execute("""
            SELECT AVG(favorite_count), COUNT(*) FROM items 
            WHERE LOWER(name) LIKE %s AND favorite_count > 0
        """, (f"%{phrase}%",))
        af, cnt = cur.fetchone()
        if not cnt: continue
        af = af or 0
        results.append((phrase, af, c, af / math.log1p(c)))
    cur.close(); conn.close()
    results.sort(key=lambda x: x[3], reverse=True)
    embed = discord.Embed(title=f"💃 Emote Opportunity: `{kw}`", color=0xff66aa)
    for i, (p, af, c, sc) in enumerate(results[:10], 1):
        embed.add_field(name=f"{i}. {p}",
                        value=f"Score: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Comp: **{c:,}**",
                        inline=False)
    await ctx.send(embed=embed)


@bot.command(name="classic")
async def classic(ctx, *, keyword: str):
    kw = keyword.strip().lower()
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT suggestion FROM search_suggestions 
        WHERE suggestion LIKE %s OR seed_keyword LIKE %s LIMIT 100
    """, (f"%{kw}%", f"%{kw}%"))
    suggs = [r[0] for r in cur.fetchall()] or [kw]
    results = []
    for phrase in suggs:
        cur.execute("SELECT COUNT(*) FROM items WHERE LOWER(name) LIKE %s", (f"%{phrase}%",))
        c = cur.fetchone()[0] or 1
        cur.execute("""
            SELECT AVG(favorite_count), COUNT(*) FROM items 
            WHERE LOWER(name) LIKE %s AND favorite_count > 0
        """, (f"%{phrase}%",))
        af, cnt = cur.fetchone()
        if not cnt: continue
        af = af or 0
        results.append((phrase, af, c, af / math.log1p(c)))
    cur.close(); conn.close()
    results.sort(key=lambda x: x[3], reverse=True)
    embed = discord.Embed(title=f"👕 Classic Clothing: `{kw}`", color=0x66ccff)
    for i, (p, af, c, sc) in enumerate(results[:10], 1):
        embed.add_field(name=f"{i}. {p}",
                        value=f"Score: **{sc:,.0f}** | AvgFav: **{af:,.0f}** | Comp: **{c:,}**",
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
