import os
import re
import time
from collections import Counter, defaultdict
from database import get_db_connection, setup_database

# --- Tuning ---
MIN_ITEM_COUNT = 3       # keyword must appear in at least 3 items
MIN_AVG_FAVS = 50        # keyword must be in items with 50+ avg favourites
TOP_N = 500              # keep top 500 keywords
MAX_ITEM_SCAN = 30000    # scan up to 30k items per run

STOP_WORDS = {
    "the","a","an","and","of","in","to","for","is","on","that","by","with",
    "from","as","it","at","be","or","no","not","but","all","are","was","were",
    "they","them","his","her","my","your","its","i","you","he","she","we","me",
    "us","our","new","one","if","so","up","out","just","can","also","do","get",
    "has","had","have","did","more","some","like","this","will","use","used",
    "very","much","many","make","made","made","made","will","would","could",
    "should","may","might","must","shall","than","then","there","here","when",
    "where","why","how","what","who","which","am","been","being","having"
}


def extract_phrases(text):
    """Extract single words + bigrams from a text."""
    if not text:
        return []
    words = [w.lower() for w in re.findall(r"[a-zA-Z]+", text) 
             if len(w) > 2 and w.lower() not in STOP_WORDS]
    phrases = []
    # singles
    phrases.extend(words)
    # bigrams (consecutive word pairs)
    for i in range(len(words) - 1):
        phrases.append(f"{words[i]} {words[i+1]}")
    return phrases


def discover_keywords():
    setup_database()
    conn = get_db_connection()
    cur = conn.cursor()

    print("📊 Loading items from database...")
    start = time.time()

    cur.execute(f"""
        SELECT name, description, favorite_count, total_sales
        FROM items
        WHERE favorite_count > 0 OR total_sales > 0
        ORDER BY favorite_count DESC
        LIMIT {MAX_ITEM_SCAN}
    """)
    rows = cur.fetchall()
    print(f"   Loaded {len(rows)} items in {time.time()-start:.1f}s")

    if not rows:
        print("⚠️ No items to analyze. Run the enricher first.")
        cur.close(); conn.close()
        return

    # --- Aggregate scores per phrase ---
    stats = defaultdict(lambda: {"total_favs": 0, "total_sales": 0, "count": 0})
    print(f"🧠 Analyzing {len(rows)} items...")

    for name, desc, favs, sales in rows:
        text = f"{name or ''} {desc or ''}"
        phrases = set(extract_phrases(text))  # unique per item
        for p in phrases:
            stats[p]["total_favs"] += (favs or 0)
            stats[p]["total_sales"] += (sales or 0)
            stats[p]["count"] += 1

    print(f"   Found {len(stats)} unique phrases")

    # --- Score and filter ---
    scored = []
    for phrase, s in stats.items():
        if s["count"] < MIN_ITEM_COUNT:
            continue
        avg_f = s["total_favs"] / s["count"]
        avg_s = s["total_sales"] / s["count"]
        if avg_f < MIN_AVG_FAVS:
            continue
        # Demand score (weighted)
        score = (avg_f * 0.7) + (avg_s * 10)
        scored.append((phrase, score, avg_f, avg_s, s["count"]))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:TOP_N]
    print(f"   Top {len(top)} keywords selected")

    # --- Save to learned_keywords ---
    print("💾 Saving to database...")
    cur.execute("DELETE FROM learned_keywords")  # refresh each run
    for phrase, score, avg_f, avg_s, cnt in top:
        cur.execute("""
            INSERT INTO learned_keywords 
                (keyword, score, avg_favorites, avg_sales, item_count)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (keyword) DO UPDATE SET
                score = EXCLUDED.score,
                avg_favorites = EXCLUDED.avg_favorites,
                avg_sales = EXCLUDED.avg_sales,
                item_count = EXCLUDED.item_count,
                learned_at = CURRENT_TIMESTAMP
        """, (phrase, score, avg_f, avg_s, cnt))
    conn.commit()

    cur.close()
    conn.close()
    print(f"✅ Saved {len(top)} learned keywords in {time.time()-start:.1f}s")
    print(f"\n🏆 Top 10 keywords learned:")
    for i, (phrase, score, af, as_, cnt) in enumerate(top[:10], 1):
        print(f"  {i}. {phrase} — score {score:,.0f} (avg {af:,.0f} favs, {cnt} items)")


if __name__ == "__main__":
    discover_keywords()
