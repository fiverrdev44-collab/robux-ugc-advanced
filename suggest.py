import os
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import get_db_connection, setup_database

SUGGEST_API = "https://www.roblox.com/search/suggest"
WORKERS = 10

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


def get_dynamic_seeds():
    """
    Self-expanding: pull seeds from suggestion words we've already collected.
    The scraper grows smarter over time.
    """
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
            if not s:
                continue
            s = s.strip().lower()
            # Only use short phrases (1-2 words) as seeds
            if 3 < len(s) < 25 and s not in seen and len(s.split()) <= 2:
                new_seeds.append(s)
                seen.add(s)
            if len(new_seeds) >= 100:  # cap for runtime
                break
        print(f"🧠 Learned {len(new_seeds)} dynamic seeds from database.")
        return new_seeds
    except Exception as e:
        print(f"⚠️ Could not load dynamic seeds: {e}")
        return []


def fetch_suggestions(seed):
    """Fetch suggestions for one seed. Thread-safe."""
    for attempt in range(2):
        try:
            resp = requests.get(
                SUGGEST_API,
                params={"keyword": seed, "maxResults": 10},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                return seed, [s.get("keyword", "").strip().lower()
                              for s in data.get("suggestions", [])
                              if s.get("keyword")]
            if resp.status_code == 429:
                time.sleep(1.5)
                continue
        except Exception:
            time.sleep(0.5)
    return seed, []


def run_suggest():
    setup_database()
    start = time.time()

    # Combine hardcoded + learned seeds
    all_seeds = HARDCODED_SEEDS + get_dynamic_seeds()
    print(f"💬 Scraping {len(all_seeds)} seeds with {WORKERS} workers...")

    # ---- PARALLEL FETCH ----
    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(fetch_suggestions, seed): seed for seed in all_seeds}
        for i, future in enumerate(as_completed(futures), 1):
            seed, suggs = future.result()
            results.append((seed, suggs))
            if i % 30 == 0:
                print(f"  Fetched {i}/{len(all_seeds)}...")

    # ---- DB WRITE (bulk) ----
    conn = get_db_connection()
    cur = conn.cursor()
    total = 0
    for seed, suggs in results:
        for s in suggs:
            cur.execute(
                "INSERT INTO search_suggestions (seed_keyword, suggestion) VALUES (%s, %s)",
                (seed, s)
            )
            total += 1
    conn.commit()
    cur.close()
    conn.close()

    print(f"✅ Total {total} suggestions stored in {time.time()-start:.1f}s")


if __name__ == "__main__":
    run_suggest()
