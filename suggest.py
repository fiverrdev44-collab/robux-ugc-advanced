import os
import requests
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from database import get_db_connection, setup_database

# Try multiple endpoints — Roblox changes these often
ENDPOINTS = [
    "https://apis.roblox.com/search-suggestions/v1/suggest",
    "https://apis.roblox.com/search-suggestions/v1/omni-suggest/keywords",
    "https://www.roblox.com/search/suggest",
    "https://catalog.roblox.com/v1/search/suggestions",
]
WORKERS = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.roblox.com/",
    "Origin": "https://www.roblox.com",
}

UGC_SEEDS = [
    "hat", "hair", "face", "shirt", "pants", "jacket", "shoe", "wing", "tail",
    "ear", "horn", "crown", "chain", "necklace", "backpack", "bag", "sword",
    "pet", "cute", "emo", "goth", "y2k", "pastel", "cyber", "kawaii", "fluffy",
    "bear", "cat", "dog", "dragon", "angel", "demon", "robot", "armor", "cape",
    "mask", "glasses", "bandage", "coquette", "grunge", "vampire", "fairy",
    "aesthetic", "harajuku", "cottagecore", "dark", "light", "neon", "glow"
]

CLASSIC_SEEDS = [
    "t-shirt", "tshirt", "shirt", "pants", "jeans", "hoodie", "sweater",
    "jacket", "plaid", "flannel", "preppy", "grunge", "y2k", "emo", "goth",
    "aesthetic", "streetwear", "casual", "formal", "school", "uniform",
    "dress", "skirt", "shorts", "cargo", "denim", "leather", "sports",
    "jersey", "varsity", "anime", "kawaii", "cute", "dark", "light", "neon"
]

EMOTE_SEEDS = [
    "dance", "emote", "floss", "griddy", "wave", "dab", "russian", "meme",
    "renegade", "shuffle", "spin", "flip", "kick", "punch", "idle", "sit",
    "laugh", "cry", "rage", "silly", "cat", "dog", "bunny", "sigma", "rizz",
    "skibidi", "moonwalk", "robot", "victory", "clap", "cheer", "flex",
    "salute", "pose", "run", "walk", "swim", "fly", "float", "anime", "aura"
]

HARDCODED_SEEDS = UGC_SEEDS + CLASSIC_SEEDS + EMOTE_SEEDS

STOP_WORDS = {
    "the","a","an","and","of","in","to","for","is","on","that","by","with",
    "from","as","it","at","be","or","no","not","but","all","are","was","were",
    "they","them","his","her","my","your","its","i","you","he","she","we","me",
    "us","our","new","one","if","so","up","out","just","can","also","do","get"
}


def try_endpoint(endpoint, seed):
    """Try one endpoint with one seed. Return list of suggestion strings or []."""
    try:
        for param_name in ["query", "keyword", "q"]:
            params = {param_name: seed, "limit": 10, "maxResults": 10}
            try:
                resp = requests.get(endpoint, params=params, headers=HEADERS, timeout=8)
            except Exception:
                continue
            if resp.status_code != 200:
                continue
            # Try to parse JSON
            try:
                data = resp.json()
            except Exception:
                continue

            # Handle different possible shapes
            items = None
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                for key in ["suggestions", "keywords", "data", "results", "items"]:
                    if key in data and isinstance(data[key], list):
                        items = data[key]
                        break
            if not items:
                continue

            parsed = []
            for s in items:
                if isinstance(s, str):
                    parsed.append(s.strip().lower())
                elif isinstance(s, dict):
                    kw = (s.get("keyword") or s.get("text") 
                          or s.get("name") or s.get("query"))
                    if kw:
                        parsed.append(str(kw).strip().lower())
            if parsed:
                return parsed
        return []
    except Exception:
        return []


def fetch_suggestions(seed):
    """Try all endpoints until one returns data."""
    for endpoint in ENDPOINTS:
        result = try_endpoint(endpoint, seed)
        if result:
            return seed, result, endpoint
    return seed, [], None


def get_dynamic_seeds():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT suggestion FROM search_suggestions 
            WHERE suggestion IS NOT NULL 
            ORDER BY fetched_at DESC LIMIT 3000
        """)
        rows = cur.fetchall()
        cur.close(); conn.close()

        seen = set(HARDCODED_SEEDS)
        new_seeds = []
        for (s,) in rows:
            if not s: continue
            s = s.strip().lower()
            if 3 < len(s) < 25 and s not in seen and len(s.split()) <= 2:
                new_seeds.append(s)
                seen.add(s)
            if len(new_seeds) >= 100:
                break
        print(f"🧠 Learned {len(new_seeds)} dynamic seeds.")
        return new_seeds
    except Exception as e:
        print(f"⚠️ Dynamic seeds error: {e}")
        return []


def mine_database_keywords():
    """Fallback: extract top keywords from our own items table."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        # Removed favorite_count filter — some items might have NULL
        cur.execute("""
            SELECT name FROM items 
            WHERE name IS NOT NULL AND name != ''
            ORDER BY COALESCE(favorite_count, 0) DESC 
            LIMIT 10000
        """)
        rows = cur.fetchall()
        cur.close(); conn.close()

        print(f"   Loaded {len(rows)} item names from DB.")

        counter = Counter()
        for (name,) in rows:
            if not name: continue
            words = [w.lower() for w in re.findall(r"[a-zA-Z]+", name) 
                     if len(w) > 2 and w.lower() not in STOP_WORDS]
            for w in words:
                counter[w] += 1
            for i in range(len(words) - 1):
                counter[f"{words[i]} {words[i+1]}"] += 1

        top = counter.most_common(800)
        print(f"   Mined {len(top)} unique keywords from titles.")
        return top
    except Exception as e:
        print(f"⚠️ DB mining error: {e}")
        return []


def run_suggest():
    setup_database()
    start = time.time()

    all_seeds = HARDCODED_SEEDS + get_dynamic_seeds()
    print(f"💬 Scraping {len(all_seeds)} seeds across {len(ENDPOINTS)} endpoints...")

    results = []
    working_endpoint = None

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(fetch_suggestions, seed): seed for seed in all_seeds}
        for i, future in enumerate(as_completed(futures), 1):
            seed, suggs, endpoint = future.result()
            if suggs:
                results.append((seed, suggs))
                if not working_endpoint:
                    working_endpoint = endpoint
                    print(f"  ✅ Working endpoint: {endpoint}")
            if i % 30 == 0:
                print(f"  Fetched {i}/{len(all_seeds)}...")

    total = 0
    conn = get_db_connection()
    cur = conn.cursor()

    if results:
        real_suggestions = sum(len(s) for _, s in results)
        print(f"💾 Saving {real_suggestions} real suggestions from {len(results)} seeds...")
        for seed, suggs in results:
            for s in suggs:
                cur.execute(
                    "INSERT INTO search_suggestions (seed_keyword, suggestion) VALUES (%s, %s)",
                    (seed, s)
                )
                total += 1
        conn.commit()

    # ---- FALLBACK: mine our own DB ----
    if total == 0:
        print("⚠️ No suggestions from Roblox. Mining our own database...")
        fallback = mine_database_keywords()
        for phrase, count in fallback:
            cur.execute(
                "INSERT INTO search_suggestions (seed_keyword, suggestion) VALUES (%s, %s)",
                ("__db_mined__", phrase)
            )
            total += 1
        conn.commit()

    cur.close()
    conn.close()
    print(f"✅ Total {total} suggestions stored in {time.time()-start:.1f}s")


if __name__ == "__main__":
    run_suggest()
