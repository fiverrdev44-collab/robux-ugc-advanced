import os
import requests
import time
from database import get_db_connection, setup_database

SUGGEST_API = "https://www.roblox.com/search/suggest"

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

ALL_SEEDS = UGC_SEEDS + CLASSIC_SEEDS + EMOTE_SEEDS


def fetch_suggestions(seed):
    try:
        resp = requests.get(SUGGEST_API, params={"keyword": seed, "maxResults": 10}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return [s.get("keyword", "").strip().lower() 
                    for s in data.get("suggestions", []) if s.get("keyword")]
    except Exception as e:
        print(f"Error '{seed}': {e}")
    return []


def run_suggest():
    setup_database()
    conn = get_db_connection()
    cur = conn.cursor()
    total = 0
    for seed in ALL_SEEDS:
        suggs = fetch_suggestions(seed)
        for s in suggs:
            cur.execute("INSERT INTO search_suggestions (seed_keyword, suggestion) VALUES (%s, %s)", (seed, s))
            total += 1
        conn.commit()
        print(f"  '{seed}': {len(suggs)}")
        time.sleep(0.3)
    cur.close(); conn.close()
    print(f"✅ Total: {total}")


if __name__ == "__main__":
    run_suggest()
