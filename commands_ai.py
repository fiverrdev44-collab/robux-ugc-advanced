"""
commands_ai.py — AI commands: brainstorm, rescue, analyze_image,
ai_status, ai_debug + all AI helpers.

CATEGORY-AWARE: uses category_configs.py for family detection, relevance
filtering, and DB asset-type filters. Emote path is unchanged.
"""
import asyncio
import re
import math
import os
import discord
from collections import Counter, defaultdict

from gemini_brain import (
    extract_keywords, all_terms, synthesize_hybrid, verify_titles,
    is_available, expand_search_terms, analyze_image_for_ugc,
)
from algo_brain import build_algo_context
from winner_analysis import analyze_winners
from bot_core import (
    get_db, extract_words, word_boundary_pattern,
    FILLER_WORDS, MIN_PRICE, MAX_PRICE,
    STOP_WORDS,
)
from category_configs import (
    get_category_config,
    detect_family_from_intent,
    detect_family_from_asset_type,
    get_all_type_words,
    get_filler_block,
)


# ── Category-aware keyword filter ───────────────────────────
_GENERIC_BLOCK = {
    "code", "joe", "move", "intro", "guy", "man", "woman", "person",
    "thing", "stuff", "item", "asset", "made", "version", "edit",
    "style", "look", "make", "will", "just", "like", "want", "need",
    "know", "get", "got", "one", "two", "three", "four", "five",
    "first", "last", "next", "back", "front", "side", "top", "bottom",
    "left", "right", "here", "there", "where", "when", "what", "who",
    "which", "yeah", "yea", "nah", "ok", "okay", "guys", "folks",
    "everyone", "somebody", "anyone", "nobody",
} | FILLER_WORDS

# Emote-specific rich vocab (kept for emote regression safety)
_EMOTE_VOCAB = {
    "dance", "emote", "animation", "move", "movement", "groove",
    "sway", "step", "bounce", "hop", "jump", "slide", "spin", "twirl",
    "wave", "floss", "glide", "strut", "walk", "run", "pose", "lean",
    "swing", "shake", "roll", "pop", "lock", "drop", "flip", "kick",
    "clap", "snap", "tap", "shuffle", "bop", "stomp", "wiggle", "shimmy",
    "jiggle", "swagger", "swag", "bob", "nod", "twerk", "grind",
    "chill", "smooth", "mellow", "lazy", "relaxed", "hype", "vibe",
    "energy", "flow", "rhythm", "beat", "aura",
    "cool", "snappy", "bouncy", "poppy", "sassy", "boss",
    "glitch", "cyber", "neon", "viral", "wild", "fast",
    "slow", "soft", "loose", "tight", "quick", "slick", "fresh",
    "crazy", "epic", "silly", "goofy", "funny", "troll",
    "happy", "sad", "angry", "shy", "confident", "humble",
    "cute", "cozy", "moody", "fancy", "flashy", "subtle",
    "night", "day", "sun", "moon", "star", "fire", "ice",
    "party", "club", "disco", "rave", "festival",
    "kpop", "k-pop", "hiphop", "hip-hop", "rap", "pop", "rock",
    "edm", "techno", "house", "jazz", "salsa", "ballet",
    "floss", "griddy", "dab", "moonwalk", "renegade", "dougie",
}

_RELEVANCE_VOCAB_CACHE = {}


def _get_relevance_vocab(family):
    """Build/return the relevance vocab for a category family (cached)."""
    key = (family or "emote").lower()
    if key in _RELEVANCE_VOCAB_CACHE:
        return _RELEVANCE_VOCAB_CACHE[key]
    vocab = set()
    if key == "emote":
        vocab.update(_EMOTE_VOCAB)
    try:
        cfg = get_category_config(key)
        for w in cfg.get("type_words", []):
            vocab.add(w)
        for arch in cfg.get("title_archetypes", []):
            for w in re.findall(r"[a-z]{3,}", str(arch).lower()):
                vocab.add(w)
        for b in cfg.get("buckets", []):
            for w in re.findall(r"[a-z]{3,}", str(b.get("vibe", "")).lower()):
                if len(w) >= 3:
                    vocab.add(w)
    except Exception:
        pass
    _RELEVANCE_VOCAB_CACHE[key] = vocab
    return vocab


def _get_category_bridge_seeds(family):
    """Bridge seeds for the vocab sample builder."""
    seeds = set()
    try:
        cfg = get_category_config(family)
        for w in cfg.get("type_words", []):
            seeds.add(w)
        for arch in cfg.get("title_archetypes", []):
            for w in re.findall(r"[a-z]{3,}", str(arch).lower()):
                seeds.add(w)
        for b in cfg.get("buckets", []):
            for w in re.findall(r"[a-z]{3,}", str(b.get("vibe", "")).lower()):
                if len(w) >= 3:
                    seeds.add(w)
    except Exception:
        pass
    if (family or "").lower() == "emote":
        seeds.update(_EMOTE_BRIDGE_SEEDS)
    return list(seeds)


def _is_relevant_keyword(word, seed_set, family="emote"):
    """Keep only words that are (a) category-relevant OR (b) match the seed."""
    w = (word or "").lower()
    if w in seed_set:
        return True
    if w in _get_relevance_vocab(family):
        return True
    for s in seed_set:
        if len(s) >= 4 and (s in w or w in s):
            return True
    return False


# ── DB search helpers ────────────────────────────────────────
def _db_search(patterns):
    if not patterns:
        return []
    sql = """
        SELECT id, name, favorite_count, price, total_sales, description
        FROM items
        WHERE (lower(name) LIKE ANY(%s)
            OR lower(COALESCE(description, '')) LIKE ANY(%s))
          AND favorite_count > 5
        LIMIT 2500
    """
    try:
        conn = get_db(); cur = conn.cursor()
        try:
            cur.execute(sql, (patterns, patterns))
            return cur.fetchall()
        finally:
            cur.close(); conn.close()
    except Exception as e:
        print(f"[db-search] {e}", flush=True)
        return []


def _db_search_by_category(patterns, asset_type_ids):
    """Category-filtered search. Falls back to unfiltered if no asset ids."""
    if not patterns:
        return []
    if not asset_type_ids:
        return _db_search(patterns)
    sql = """
        SELECT id, name, favorite_count, price, total_sales, description
        FROM items
        WHERE (lower(name) LIKE ANY(%s)
            OR lower(COALESCE(description, '')) LIKE ANY(%s))
          AND asset_type_id = ANY(%s)
          AND favorite_count > 5
        LIMIT 2500
    """
    try:
        conn = get_db(); cur = conn.cursor()
        try:
            cur.execute(sql, (patterns, patterns, list(asset_type_ids)))
            return cur.fetchall()
        finally:
            cur.close(); conn.close()
    except Exception as e:
        print(f"[db-search-cat] {e}", flush=True)
        return []


def _db_search_emote_only(patterns):
    """Backward-compat wrapper."""
    return _db_search_by_category(patterns, [61])


def _term_match_count(term):
    if not term or len(term) < 3:
        return 0
    try:
        conn = get_db(); cur = conn.cursor()
        try:
            cur.execute(
                """SELECT COUNT(*) FROM (
                     SELECT 1 FROM items
                     WHERE lower(name) LIKE %s
                        OR lower(COALESCE(description,'')) LIKE %s
                     LIMIT 500
                   ) sub""",
                (f"%{term}%", f"%{term}%")
            )
            return cur.fetchone()[0] or 0
        finally:
            cur.close(); conn.close()
    except Exception:
        return 0


_VOCAB_TYPE_TO_ASSET_ID = {"emote": 61}

_EMOTE_BRIDGE_SEEDS = [
    "emote", "dance", "animation", "gesture", "expression", "reaction",
    "floss", "griddy", "dab", "wave", "shuffle", "moonwalk", "renegade",
    "dougie", "stanky", "shmoney", "krump", "hiphop", "breakdance",
    "gangnam", "salsa", "ballet", "vogue", "twist", "robot",
    "spin", "twirl", "kick", "bounce", "jump", "pose", "salute", "clap",
    "cheer", "victory", "greeting", "hello", "goodbye", "hug", "kiss",
    "idle", "sit", "crouch", "sleep", "meditate", "levitate", "float",
    "laugh", "cry", "smile", "silly", "rage", "shy", "smug", "confused",
    "kpop", "korean", "anime", "naruto", "jojo", "goku", "gojo", "luffy",
    "sigma", "rizz", "skibidi", "gyatt", "mewing", "aura", "sus", "ratio",
    "goat", "slay", "bussin", "yeet", "bruh", "fanum", "cap",
    "tiktok", "trend", "trending", "viral", "meme", "loop", "hype",
    "party", "swag", "epic", "smooth", "groove", "sway",
    "r6", "r15",
    "cute", "emo", "edgy", "coquette", "preppy", "pastel", "cyber",
]


def _get_db_vocab_sample(item_type="unknown", limit=800):
    """Category-aware vocab sample. Uses family's asset_type_ids."""
    family = item_type
    try:
        cfg = get_category_config(family)
        asset_ids = cfg.get("asset_type_ids") or []
    except Exception:
        cfg = {}
        asset_ids = []

    # Backward-compat fallback
    if not asset_ids:
        legacy = _VOCAB_TYPE_TO_ASSET_ID.get((item_type or "").lower())
        if legacy:
            asset_ids = [legacy]

    rows = []
    try:
        conn = get_db(); cur = conn.cursor()
        try:
            if asset_ids:
                cur.execute(
                    "SELECT name FROM items "
                    "WHERE favorite_count > 50 AND asset_type_id = ANY(%s) "
                    "LIMIT 20000",
                    (list(asset_ids),)
                )
                rows = cur.fetchall()
                if len(rows) < 500:
                    cur.execute(
                        "SELECT name FROM items "
                        "WHERE favorite_count > 50 LIMIT 15000"
                    )
                    rows.extend(cur.fetchall())
            else:
                cur.execute(
                    "SELECT name FROM items "
                    "WHERE favorite_count > 50 LIMIT 15000"
                )
                rows = cur.fetchall()
        finally:
            cur.close(); conn.close()
    except Exception as e:
        print(f"[vocab-sample] {e}", flush=True)
        rows = []

    counter = Counter()
    token_re = re.compile(r"[a-z]+")
    for (name,) in rows:
        for w in set(token_re.findall((name or "").lower())):
            if len(w) >= 3 and w not in STOP_WORDS:
                counter[w] += 1

    vocab = [w for w, _ in counter.most_common(limit)]

    # Category-specific bridge seeds
    bridge = _get_category_bridge_seeds(family)
    existing = set(vocab)
    for w in bridge:
        if w not in existing:
            vocab.append(w)
            existing.add(w)

    return vocab


def _find_gap_alternatives(terms, top_n=5):
    """Thread-safe: opens its own DB connection."""
    if not terms:
        return [], {}

    valid_terms = [t.lower().strip() for t in terms
                   if len(t.strip()) >= 3 and t.lower() not in FILLER_WORDS]
    if not valid_terms:
        return [], {}

    term_stats = {}
    conn = None; cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        patterns = [f"%{t}%" for t in valid_terms]
        cur.execute("""
            SELECT LOWER(name), favorite_count FROM items
            WHERE LOWER(name) LIKE ANY(%s) AND favorite_count > 50
            LIMIT 5000
        """, (patterns,))
        rows = cur.fetchall()

        for t in valid_terms:
            term_stats[t] = {"comp": 0, "favs_sum": 0, "favs_count": 0}

        for name, favs in rows:
            for t in valid_terms:
                if re.search(r'\b' + re.escape(t) + r'\b', name):
                    term_stats[t]["comp"] += 1
                    term_stats[t]["favs_sum"] += favs or 0
                    term_stats[t]["favs_count"] += 1

        for t in valid_terms:
            s = term_stats[t]
            s["avg_favs"] = int(s["favs_sum"] / s["favs_count"]) if s["favs_count"] else 0
    except Exception as e:
        print(f"[gap-alts] term stats: {e}", flush=True)
        return [], term_stats
    finally:
        try:
            if cur: cur.close()
        except Exception: pass
        try:
            if conn: conn.close()
        except Exception: pass

    saturated = [t for t, s in term_stats.items() if s["comp"] > 200]
    if not saturated:
        return [], term_stats

    all_candidates = defaultdict(lambda: {"count": 0, "favs": 0})
    conn = None; cur = None
    try:
        conn = get_db()
        cur = conn.cursor()

        for sat_term in saturated:
            pattern = word_boundary_pattern(sat_term)
            try:
                cur.execute("""
                    SELECT name, favorite_count FROM items
                    WHERE name ~* %s AND favorite_count > 100
                    LIMIT 1000
                """, (pattern,))
                rows = cur.fetchall()
            except Exception:
                try: cur.connection.rollback()
                except Exception: pass
                continue
            for name, favs in rows:
                for w in set(extract_words(name)):
                    if w in valid_terms or w in FILLER_WORDS:
                        continue
                    all_candidates[w]["count"] += 1
                    all_candidates[w]["favs"] += favs or 0

        filtered = []
        for w, s in all_candidates.items():
            if s["count"] < 2 or s["count"] > 50:
                continue
            avg = s["favs"] / s["count"]
            if avg < 500:
                continue
            filtered.append((w, avg, s["count"]))

        if not filtered:
            return [], term_stats

        candidate_words = [w for w, _, _ in filtered[:100]]
        comp_map = defaultdict(int)
        try:
            cpatterns = [f"%{w}%" for w in candidate_words]
            cur.execute("""
                SELECT LOWER(name) FROM items
                WHERE favorite_count > 0 AND LOWER(name) LIKE ANY(%s)
            """, (cpatterns,))
            matched = cur.fetchall()
            for (name,) in matched:
                for w in candidate_words:
                    if re.search(r'\b' + re.escape(w) + r'\b', name):
                        comp_map[w] += 1
        except Exception as e:
            print(f"[gap-alts] comp check: {e}", flush=True)

        alternatives = []
        for w, avg, cnt in filtered:
            comp = comp_map.get(w, 0)
            if comp < 1 or comp > 100:
                continue
            score = avg / math.log1p(comp)
            alternatives.append({
                "word": w, "avg_favs": int(avg), "count": cnt,
                "comp": comp, "score": int(score),
            })

        alternatives.sort(key=lambda x: x["score"], reverse=True)
        return alternatives[:top_n], term_stats
    except Exception as e:
        print(f"[gap-alts] phase 2: {e}", flush=True)
        return [], term_stats
    finally:
        try:
            if cur: cur.close()
        except Exception: pass
        try:
            if conn: conn.close()
        except Exception: pass


def _build_allow_list(intent, max_keywords=60, gap_words=None, family=None):
    """
    Category-aware allow-list builder. If family=None, auto-detects from intent.
    """
    if family is None:
        family = detect_family_from_intent(intent)

    terms = all_terms(intent)
    if not terms:
        return [], [], {}

    try:
        cfg = get_category_config(family)
        asset_ids = cfg.get("asset_type_ids") or []
    except Exception:
        asset_ids = []

    rows_by_id = {}
    patterns = [f"%{t}%" for t in terms if len(t) >= 2]
    if patterns:
        if asset_ids:
            for r in _db_search_by_category(patterns, asset_ids):
                rows_by_id[r[0]] = r
        else:
            for r in _db_search(patterns):
                rows_by_id[r[0]] = r
    direct_count = len(rows_by_id)

    expanded_terms = []
    bridge_reasoning = ""
    failed_terms = []
    if direct_count < 50:
        try:
            failed_terms = [t for t in terms if len(t) >= 3 and _term_match_count(t) < 3]
            if failed_terms:
                db_vocab = _get_db_vocab_sample(family, 800)
                if db_vocab:
                    exp = expand_search_terms(intent, db_vocab, failed_terms)
                    expanded_terms = exp.get("expanded_terms", [])
                    bridge_reasoning = exp.get("reasoning", "")
                    if expanded_terms:
                        p2 = [f"%{t}%" for t in expanded_terms if len(t) >= 2]
                        if p2:
                            for r in _db_search(p2):
                                rows_by_id[r[0]] = r
        except Exception as e:
            print(f"[bridge] failed: {e}", flush=True)

    rows = list(rows_by_id.values())
    if not rows:
        return [], [], {
            "direct_matches": 0,
            "expansion_used": bool(expanded_terms),
            "expanded_terms": expanded_terms,
            "failed_terms": failed_terms,
            "reasoning": bridge_reasoning,
        }

    word_stats = defaultdict(lambda: {"count": 0, "favs": 0})
    bigrams = {}
    token_re = re.compile(r"[a-z0-9]+")
    for r in rows:
        name = (r[1] or "").lower()
        favs = r[2] or 0
        toks = token_re.findall(name)
        seen = set()
        for t in toks:
            if len(t) >= 2 and t not in seen:
                word_stats[t]["count"] += 1
                word_stats[t]["favs"] += favs
                seen.add(t)
        for a, b in zip(toks, toks[1:]):
            bg = f"{a} {b}"
            bigrams[bg] = bigrams.get(bg, 0) + 1

    seed_set = set()
    for t in terms:
        for tok in (t or "").lower().split():
            if len(tok) >= 3:
                seed_set.add(tok)

    scored_words = []
    for w, s in word_stats.items():
        if w in _GENERIC_BLOCK:
            continue
        if s["count"] < 2:
            continue
        if not _is_relevant_keyword(w, seed_set, family):
            continue
        avg = s["favs"] / s["count"]
        score = avg / math.log1p(s["count"])
        scored_words.append((w, avg, s["count"], score))

    scored_words.sort(key=lambda x: x[3], reverse=True)
    opportunity_keywords = scored_words[:40]
    unigrams = [w for w, _, _, _ in opportunity_keywords]

    force_include = []
    for t in terms:
        t_clean = (t or "").lower().strip()
        if len(t_clean) < 3 or t_clean in FILLER_WORDS:
            continue
        force_include.append(t_clean)
    for w in force_include:
        if w not in unigrams:
            unigrams.insert(0, w)

    if gap_words:
        for w in gap_words:
            if w not in unigrams and w not in FILLER_WORDS:
                unigrams.insert(0, w)

    top_bigrams = [b for b, _ in sorted(bigrams.items(), key=lambda x: -x[1])[:15]
                   if not any(part in FILLER_WORDS for part in b.split())]
    allow_list = unigrams[:max_keywords]
    allow_list += [b for b in top_bigrams if b not in allow_list]

    sane_rows = [r for r in rows if not r[3] or MIN_PRICE <= r[3] <= MAX_PRICE]

    GENERIC_TERMS = {
        "cute", "kawaii", "pink", "red", "white", "black", "blue", "brown",
        "green", "yellow", "purple", "orange", "gold", "silver", "gray", "grey",
        "y2k", "pastel", "grunge", "emo", "preppy", "aesthetic", "soft", "dark",
        "playful", "whimsical", "fun", "sweet", "pretty", "beautiful",
        "cool", "nice", "small", "big", "tiny", "little",
    } | FILLER_WORDS
    strong_terms = [t for t in terms if len(t) >= 3 and t.lower() not in GENERIC_TERMS]
    primary_terms = sorted(strong_terms, key=len, reverse=True)[:3]

    def _has_primary(r):
        name = (r[1] or "").lower()
        return any(t in name for t in primary_terms)

    def _match_score(r):
        name = (r[1] or "").lower()
        return sum(1 for t in strong_terms if t in name)

    relevant_rows = [r for r in sane_rows if _has_primary(r) and _match_score(r) >= 2]
    if len(relevant_rows) < 5:
        relevant_rows = [r for r in sane_rows if _has_primary(r)]
    if len(relevant_rows) < 5:
        relevant_rows = [r for r in sane_rows if _match_score(r) >= 2]
    if len(relevant_rows) < 5:
        relevant_rows = sane_rows

    items_with_favs = [r for r in relevant_rows if (r[2] or 0) > 0]
    if items_with_favs:
        top_rows = sorted(items_with_favs, key=lambda r: (r[2] or 0), reverse=True)[:10]
    else:
        top_rows = sorted(relevant_rows, key=lambda r: (r[2] or 0), reverse=True)[:10]

    top_items = [
        {"name": r[1], "favourite_count": r[2] or 0,
         "price": r[3] or 0, "total_sales": r[4] or 0}
        for r in top_rows
    ]

    prices = [r[3] for r in sane_rows if r[3] and MIN_PRICE <= r[3] <= MAX_PRICE]
    prices_sorted = sorted(prices)
    price_median = prices_sorted[len(prices_sorted) // 2] if prices_sorted else 0

    favs = sorted([r[2] or 0 for r in rows], reverse=True)
    total = len(favs)
    avg_favs = round(sum(favs) / total) if total else 0
    median_favs = favs[total // 2] if total else 0
    winner_favs = favs[max(0, total // 10)] if total else 0
    winner_count = sum(1 for f in favs if f > 10000)
    loser_count = sum(1 for f in favs if f < 1000)

    stats = {
        "count": total,
        "price_min": min(prices) if prices else 0,
        "price_avg": price_median,
        "price_max": max(prices) if prices else 0,
        "total_sales": sum((r[4] or 0) for r in rows),
        "avg_favs": avg_favs, "median_favs": median_favs,
        "winner_favs": winner_favs, "winner_count": winner_count,
        "loser_count": loser_count,
        "direct_matches": direct_count,
        "expansion_used": bool(expanded_terms),
        "expanded_terms": expanded_terms[:15],
        "failed_terms": failed_terms[:10],
        "reasoning": bridge_reasoning,
        "family": family,
        "opportunity_keywords": [
            {"word": w, "avg_favs": int(avg), "count": c, "score": int(sc)}
            for w, avg, c, sc in opportunity_keywords[:10]
        ],
    }
    return allow_list, top_items, stats


def _fmt_ai_result(synth, verified_groups, rejected, stats, item_type="unknown",
                   total_verified=0, total_rejected=0):
    lines = ["# 🧠 UGC STRATEGY REPORT"]
    if item_type and item_type != "unknown":
        try:
            cfg = get_category_config(item_type)
            lines.append(f"*Detected category: **{cfg['label']}***")
        except Exception:
            lines.append(f"*Detected item type: **{item_type.upper()}***")
    if stats.get("expansion_used"):
        lines.append("*Search tier: **Tier 2** (AI bridged missing terms)*")
    else:
        lines.append("*Search tier: **Tier 1** (direct DB hits)*")
    lines.append("")

    lines.append("## 📝 New Titles — Grouped by Strategy\n")
    if verified_groups:
        for group_name, titles in verified_groups.items():
            lines.append(f"**{group_name}**")
            for t in titles:
                lines.append(f"• `{t}`")
            lines.append("")
    else:
        lines.append("⚠️ No titles passed verification.\n")
    if total_verified:
        lines.append(f"_Total verified: **{total_verified}** · rejected: **{total_rejected}**_\n")

    sections = [
        ("search_diagnosis",              "## 🔍 Search Diagnosis"),
        ("positioning",                   "## 🎯 Positioning"),
        ("market_diagnosis",              "## 📊 Market Diagnosis"),
        ("winner_blueprint",              "## 🏆 Winner Blueprint (top 10% vs bottom 50%)"),
        ("marketplace_algorithm_playbook","## 🧠 Marketplace Algorithm Playbook"),
        ("ranking_factor_breakdown",      "## 📐 Ranking Factor Breakdown"),
        ("sale_velocity_plan",            "## 📈 Sale Velocity Plan (homepage targets)"),
        ("price_elasticity_call",         "## 💰 Price Elasticity Call"),
        ("saturation_verdict",            "## ⚠️ Saturation Verdict"),
        ("launch_window_math",            "## ⏰ Launch Window Math"),
        ("trend_intel",                   "## 🌊 Trend Intelligence"),
        ("discovery_path",                "## 🧭 Discovery Path (buyer journey)"),
        ("seo_description",               "## 📝 SEO Description (copy-paste)"),
        ("cross_promotion_play",          "## 🔗 Cross-Promotion Play"),
        ("social_playbook",               "## 📱 Social Playbook"),
        ("risk_analysis",                 "## ⚠️ Risk Analysis"),
        ("expected_performance",          "## 📈 Expected Performance"),
        ("verdict",                       "## ⚖️ Verdict"),
    ]
    for key, header in sections:
        v = synth.get(key)
        if v:
            lines.append(header); lines.append(str(v)); lines.append("")

    if synth.get("killer_keywords"):
        lines.append("## 🎯 Killer Keywords")
        lines.append(", ".join(f"`{k}`" for k in synth["killer_keywords"][:15]))
        lines.append("")

    if synth.get("bonus_plays"):
        lines.append("## 💎 Bonus Plays")
        for b in synth["bonus_plays"][:5]:
            lines.append(f"- {b}")
        lines.append("")

    lines.append("---")
    lines.append(
        f"_Data: **{stats.get('count', 0):,}** items · "
        f"avg favs **{stats.get('avg_favs', 0):,}** · "
        f"winner bar **{stats.get('winner_favs', 0):,}** · "
        f"avg price **R${stats.get('price_avg', 0)}**_"
    )
    return "\n".join(lines)


def register_ai_commands(bot):

    @bot.command(name="ai_status")
    async def ai_status(ctx):
        if is_available():
            gmodel = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
            omodel = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
            has_or = bool(os.getenv("OPENROUTER_API_KEY", "").strip())
            lines = [
                "**🧠 AI Status: ONLINE**",
                f"• Primary: `Gemini` ({gmodel})",
                f"• Fallback: {'`OpenRouter` (' + omodel + ')' if has_or else '❌ not configured'}",
                "Commands: `!brainstorm`, `!rescue`, `!analyze_image`, `!ai_debug`",
            ]
            await ctx.send("\n".join(lines))
        else:
            await ctx.send(
                "**🧠 AI Status: OFFLINE**\n"
                "No AI provider configured. Check `GEMINI_API_KEY` "
                "and/or `OPENROUTER_API_KEY` on Render."
            )

    @bot.command(name="brainstorm")
    async def brainstorm(ctx, *, description: str = ""):
        if not description.strip():
            await ctx.send("Usage: `!brainstorm rasputin dance emote from youtube`")
            return
        if not is_available():
            await ctx.send("AI is offline. Run `!ai_status`.")
            return

        progress = await ctx.send("🧠 **Pass 1:** Extracting intent...")

        intent = extract_keywords(description)
        if not intent:
            await progress.edit(content="⚠️ Pass 1 failed — using keyword-only fallback...")
            words_raw = re.findall(r"[a-z]{3,}", description.lower())
            intent = {
                "primary": words_raw, "synonyms": [], "style": [], "vibe": [],
                "colors": [], "references": [], "search_terms": words_raw,
                "item_type": "unknown", "trend_source": "none",
            }

        item_type = intent.get("item_type", "unknown")
        trend_source = intent.get("trend_source", "none")
        family = detect_family_from_intent(intent)
        try:
            cfg = get_category_config(family)
            category_label = cfg["label"]
        except Exception:
            category_label = family
        terms = all_terms(intent)

        creative_added = []
        if family == "emote":
            try:
                from creative_expand import get_creative_seeds
                creative_added = await asyncio.to_thread(
                    get_creative_seeds, description, 8, "emote"
                )
                if creative_added:
                    existing = set(intent.get("search_terms", []))
                    for c in creative_added:
                        if c and c not in existing:
                            intent.setdefault("search_terms", []).append(c)
                            existing.add(c)
                    terms = all_terms(intent)
            except Exception as e:
                print(f"[brainstorm] creative_expand failed: {e}", flush=True)
                creative_added = []

        creative_line = ""
        if creative_added:
            creative_line = (
                f"\n🧬 **Creative expansion:** +{len(creative_added)} concepts "
                f"(demand-validated)\n"
                f"`{', '.join(creative_added[:8])}`"
                + (f" _+{len(creative_added)-8} more_" if len(creative_added) > 8 else "")
            )

        await progress.edit(
            content=(f"🧠 **Pass 1 done.**\n"
                     f"• Category: **{category_label}**\n"
                     f"• Trend source: **{trend_source}**\n"
                     f"• Terms: `{', '.join(terms[:15])}`"
                     f"{creative_line}\n\n"
                     f"🔎 **Analyzing saturation...**")
        )

        # ── 🚀 CREATIVE PIVOT (category-aware) ────────────────
        creative_pivot_result = None
        try:
            from creative_pivot import (
                find_creative_pivots, format_creative_pivot_report,
            )

            seed_words = []
            for k in ("primary", "specific_moves", "search_terms", "title_verbs"):
                for t in (intent.get(k) or []):
                    for w in re.findall(r"[a-z]{3,}", str(t).lower()):
                        if w not in seed_words:
                            seed_words.append(w)
            seed_words = seed_words[:6]

            if seed_words:
                pivot_msg = await ctx.send(
                    "🚀 **Expanding creatively — AI + search data + learned keywords...**"
                )

                def _run_cp():
                    c = get_db(); cur = c.cursor()
                    try:
                        return find_creative_pivots(
                            seed_words=seed_words,
                            item_type=family,
                            cur=cur,
                            cookie=os.getenv("ROBLOSECURITY_COOKIE_1"),
                            max_candidates=25,
                            live_verify_top_n=3,
                        )
                    finally:
                        cur.close(); c.close()

                creative_pivot_result = await asyncio.to_thread(_run_cp)

                if creative_pivot_result and creative_pivot_result.get("top_pivots"):
                    cp_body = format_creative_pivot_report(creative_pivot_result)
                    try:
                        await pivot_msg.edit(content=cp_body[:1900])
                    except Exception:
                        pass
                    if len(cp_body) > 1900:
                        for i in range(1900, len(cp_body), 1900):
                            await ctx.send(cp_body[i:i+1900])
                            await asyncio.sleep(0.3)

                    # Inject pivots into search_terms
                    for p in creative_pivot_result["top_pivots"]:
                        kw = p.get("keyword")
                        if kw and kw not in intent.setdefault("search_terms", []):
                            intent["search_terms"].append(kw)
                    terms = all_terms(intent)
                else:
                    try: await pivot_msg.delete()
                    except Exception: pass
        except Exception as e:
            print(f"[brainstorm] creative pivot failed: {e}", flush=True)

        gap_alternatives = []
        term_stats = {}
        try:
            gap_alternatives, term_stats = await asyncio.to_thread(
                _find_gap_alternatives, terms, 5
            )
        except Exception as e:
            print(f"[brainstorm] gap finder failed: {e}", flush=True)

        saturated_terms = [t for t, s in term_stats.items() if s.get("comp", 0) > 200]
        if saturated_terms:
            warn = ["⚠️ **Saturation Warning** — these keywords are heavily contested:"]
            for t in saturated_terms:
                s = term_stats[t]
                warn.append(f"• `{t}` — **{s['comp']:,}** competitors, avg {s['avg_favs']:,} favs")
            if gap_alternatives:
                warn.append("")
                warn.append("**🕳️ Gap alternatives** — lower comp, same demand:")
                for a in gap_alternatives:
                    warn.append(f"• `{a['word']}` — **{a['comp']}** competitors, avg **{a['avg_favs']:,}** favs (score {a['score']:,})")
                warn.append("")
                warn.append("_Titles below mix your keywords with these gap words._")
            else:
                warn.append("")
                warn.append("_No gap alternatives found — niche is fully saturated or DB is thin._")
            try:
                await ctx.send("\n".join(warn))
            except Exception:
                pass

        gap_words = [a["word"] for a in gap_alternatives] if gap_alternatives else None

        await progress.edit(
            content=(f"🔎 **Tier 1:** Direct DB search "
                     f"({category_label})"
                     f"{' with gap injection' if gap_words else ''}...")
        )

        try:
            allow_list, top_items, stats = await asyncio.to_thread(
                _build_allow_list, intent, 60, gap_words, family
            )
        except Exception as e:
            await progress.edit(content=f"❌ DB search failed: `{e}`")
            return

        if not allow_list:
            await progress.edit(content="❌ **Nothing matched.** Run the enricher more for this niche.")
            return

        await progress.edit(
            content=(f"📊 Matched **{stats['count']:,}** real items.\n"
                     f"• Avg favs: **{stats.get('avg_favs', 0):,}**\n"
                     f"• Winner threshold: **{stats.get('winner_favs', 0):,}** favs\n\n"
                     f"🧠 **Pass 2:** AI strategist at work...")
        )

        if stats.get("opportunity_keywords"):
            opp_lines = ["**🕳️ Top opportunity keywords in your niche:**"]
            for kw in stats["opportunity_keywords"][:8]:
                opp_lines.append(f"• `{kw['word']}` — **{kw['count']}** items, avg **{kw['avg_favs']:,}** favs")
            try:
                await ctx.send("\n".join(opp_lines))
            except Exception:
                pass

        winner_data = {}
        algo_ctx = ""
        try:
            def _run_winner():
                conn = get_db(); cur = conn.cursor()
                try:
                    return analyze_winners(cur, terms, top_n=40)
                finally:
                    cur.close(); conn.close()
            winner_data = await asyncio.to_thread(_run_winner)
        except Exception as e:
            print(f"[brainstorm] winner analysis failed: {e}", flush=True)

        try:
            algo_ctx = build_algo_context(intent)
        except Exception as e:
            print(f"[brainstorm] algo context failed: {e}", flush=True)

        specific_moves = intent.get("specific_moves", [])

        # ── Keyword intelligence for synthesis prompt ────────
        keyword_intel = None
        try:
            from gemini_brain import classify_keyword_intelligence

            comp_data = []
            for t in terms[:6]:
                t_clean = (t or "").strip()
                if len(t_clean) < 3:
                    continue
                try:
                    c2 = get_db(); cur2 = c2.cursor()
                    try:
                        cur2.execute("""
                            SELECT COUNT(*),
                                   COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP
                                            (ORDER BY favorite_count), 0)
                            FROM items
                            WHERE LOWER(name) LIKE %s AND favorite_count > 5
                        """, (f"%{t_clean}%",))
                        r = cur2.fetchone()
                    finally:
                        cur2.close(); c2.close()
                    if r:
                        comp_data.append({
                            "keyword": t_clean,
                            "comp": int(r[0] or 0),
                            "median_favs": int(r[1] or 0),
                            "median_price": 0,
                        })
                except Exception:
                    continue

            if comp_data:
                keyword_intel = await asyncio.to_thread(
                    classify_keyword_intelligence,
                    comp_data[0]["keyword"], comp_data, family,
                )
        except Exception as e:
            print(f"[brainstorm] keyword intelligence failed: {e}", flush=True)

        synth = None
        try:
            synth = await asyncio.to_thread(
                synthesize_hybrid, description, allow_list, top_items, stats,
                item_type, trend_source,
                {"direct_matches": stats.get("direct_matches", 0),
                 "expansion_used": stats.get("expansion_used", False),
                 "expanded_terms": stats.get("expanded_terms", []),
                 "failed_terms": stats.get("failed_terms", []),
                 "reasoning": stats.get("reasoning", "")},
                None, specific_moves, winner_data, algo_ctx, keyword_intel,
            )
        except Exception as e:
            print(f"[brainstorm] synth failed: {e}", flush=True)
            synth = None

        if not synth:
            try:
                await progress.delete()
            except Exception:
                pass

            fallback_lines = ["⚠️ **AI returned nothing — showing raw market data only.**\n"]
            fallback_lines.append(f"**🎯 Terms:** `{', '.join(terms[:15])}`")
            fallback_lines.append(
                f"**📊 Matched:** {stats['count']:,} real items · "
                f"avg favs {stats.get('avg_favs', 0):,} · "
                f"winner bar {stats.get('winner_favs', 0):,}"
            )
            if top_items:
                fallback_lines.append("\n**🥊 Top competitors:**")
                for it in top_items[:5]:
                    name = (it.get("name") or "")[:60]
                    favs = it.get("favourite_count") or 0
                    price = it.get("price") or 0
                    fallback_lines.append(f"• `{name}` — {favs:,} favs · R${price}")
            if allow_list:
                kw_str = ", ".join(f"`{k}`" for k in allow_list[:20])
                fallback_lines.append(f"\n**🎯 Allow-list:**\n{kw_str}")
            body = "\n".join(fallback_lines)
            for i in range(0, len(body), 1900):
                await ctx.send(body[i:i + 1900])
            return

        try:
            from smart_pipeline import run_full_pipeline
            from rising_gaps import CATEGORY_MAP

            ai_titles = []
            for k in ("titles_safe", "titles_differentiated",
                      "titles_longtail", "titles_viral"):
                ai_titles.extend(synth.get(k) or [])

            cat_ids = None
            if family in CATEGORY_MAP:
                cat_ids = CATEGORY_MAP[family]
            else:
                try:
                    cat_ids = get_category_config(family).get("asset_type_ids") or None
                except Exception:
                    cat_ids = None

            pipeline_msg = await ctx.send(
                "🧬 **Running smart pipeline (parallel)...**\n"
                "_Live-enriching thin data · cascading to alternatives_"
            )

            def _pipeline():
                return run_full_pipeline(
                    description=description,
                    intent=intent,
                    item_type=family,
                    category_asset_ids=cat_ids,
                    ai_titles=ai_titles,
                    live_enrich=True,
                    db_factory=get_db,
                )

            pipeline_result = await asyncio.to_thread(_pipeline)

            if pipeline_result and pipeline_result.get("report"):
                body = pipeline_result["report"]
                for i in range(0, len(body), 1900):
                    await ctx.send(body[i:i+1900])
                    await asyncio.sleep(0.3)

            try:
                await pipeline_msg.delete()
            except Exception:
                pass
        except Exception as e:
            print(f"[brainstorm] smart pipeline failed: {e}", flush=True)

        all_groups = {
            "🟢 Safe (mirror winners)":          synth.get("titles_safe") or [],
            "🎯 Differentiated (unique angle)":  synth.get("titles_differentiated") or [],
            "🔎 Long-tail SEO (4+ keywords)":    synth.get("titles_longtail") or [],
            "🔥 Viral bait (meme hook)":         synth.get("titles_viral") or [],
        }
        if not any(all_groups.values()):
            all_groups = {"Titles": synth.get("titles") or []}

        verified_groups = {}
        total_verified = 0
        total_rejected = 0
        for group_name, group_titles in all_groups.items():
            v, r = verify_titles(group_titles, allow_list)
            if v:
                verified_groups[group_name] = v
                total_verified += len(v)
            total_rejected += len(r)

        body = _fmt_ai_result(synth, verified_groups, [], stats, family,
                              total_verified=total_verified,
                              total_rejected=total_rejected)

        try:
            await progress.delete()
        except Exception:
            pass

        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i + 1900])
            await asyncio.sleep(0.3)

    @bot.command(name="rescue")
    async def rescue(ctx, *, description: str = ""):
        if not description.strip():
            await ctx.send(
                "Usage: `!rescue <describe your launched item + stats>`\n"
                "Example: `!rescue rasputin dance emote, launched 3 days ago, 40 favs, 0 sales, R$75`"
            )
            return
        if not is_available():
            await ctx.send("AI is offline. Run `!ai_status`.")
            return

        progress = await ctx.send("🩺 **Analyzing your item...**")

        intent = extract_keywords(description)
        if not intent:
            words_raw = re.findall(r"[a-z]{3,}", description.lower())
            intent = {
                "primary": words_raw, "synonyms": [], "style": [], "vibe": [],
                "colors": [], "references": [], "search_terms": words_raw,
                "item_type": "unknown", "trend_source": "none",
            }

        item_type = intent.get("item_type", "unknown")
        family = detect_family_from_intent(intent)
        terms = all_terms(intent)

        try:
            allow_list, top_items, stats = await asyncio.to_thread(
                _build_allow_list, intent, 60, None, family
            )
        except Exception as e:
            await progress.edit(content=f"❌ DB search failed: `{e}`")
            return

        if not allow_list:
            await progress.edit(content="❌ No DB matches. Run the enricher more.")
            return

        comp_lines = []
        for it in top_items[:10]:
            name = (it.get("name") or "")[:70]
            favs = it.get("favourite_count") or 0
            price = it.get("price") or 0
            comp_lines.append(f"• `{name}` — {favs:,} favs · R${price}")

        await progress.edit(
            content=(f"🩺 **Category:** {family}\n"
                     f"**Matched {stats['count']:,} competitors** in this niche.\n\n"
                     f"🧠 **AI is diagnosing your launch and writing new titles...**")
        )

        rescue_prompt = f"""You are a Roblox UGC title doctor. A creator launched an item that is NOT SELLING.

THEIR DESCRIPTION / CURRENT SITUATION:
{description}

CATEGORY: {family}

REAL DB KEYWORDS available (you MUST use these for titles):
{', '.join(allow_list[:60])}

TOP 10 COMPETITORS in this niche:
{chr(10).join(comp_lines)}

MARKET STATS:
- competitors: {stats.get('count', 0):,}
- avg favs: {stats.get('avg_favs', 0):,}
- median favs: {stats.get('median_favs', 0):,}
- winner bar (top 10%): {stats.get('winner_favs', 0):,} favs
- avg price: R${stats.get('price_avg', 0)}

YOUR JOB — return ONLY valid JSON:

{{
  "diagnosis": "3-4 sentences: why their item probably isn't selling. Be blunt.",
  "what_winners_do": "2-3 sentences: the specific naming pattern the top 10 competitors share.",
  "titles_safe": ["3 titles that MIRROR what top competitors already do"],
  "titles_differentiated": ["3 titles that use SAME niche keywords but UNIQUE angle"],
  "titles_longtail": ["2 titles with 4+ keywords packed in"],
  "titles_viral": ["2 titles that hook meme/TikTok/Sound trends"],
  "new_description": "Full 2-3 sentence SEO description, keyword-rich.",
  "price_advice": "1-2 sentences: keep, raise, or drop price?",
  "relaunch_plan": "2-3 sentences: concrete next action.",
  "kill_or_keep": "KEEP / RESCUE / KILL — one word plus one sentence"
}}

RULES:
- Every word in every title MUST exist in the allow-list above (plus glue words).
- Titles MUST be 3-5 words.
- Each title must READ AS A SENTENCE, not a list of keywords.
- Do NOT invent keywords. Do NOT fabricate stats.
- Output ONLY the JSON object.
"""

        synth = None
        try:
            synth = await asyncio.to_thread(
                synthesize_hybrid, rescue_prompt, allow_list, top_items, stats,
                family, intent.get("trend_source", "none"),
                {"direct_matches": stats.get("direct_matches", 0),
                 "expansion_used": stats.get("expansion_used", False),
                 "expanded_terms": stats.get("expanded_terms", []),
                 "failed_terms": stats.get("failed_terms", []),
                 "reasoning": stats.get("reasoning", "")}
            )
        except Exception as e:
            print(f"[rescue] failed: {e}", flush=True)
            synth = None

        if not synth:
            try:
                await progress.delete()
            except Exception:
                pass

            lines = ["⚠️ **AI offline — here's what winners in your niche look like.**\n"]
            lines.append(f"**Your niche:** `{', '.join(terms[:10])}`")
            lines.append(f"**Competitors:** {stats['count']:,} items")
            lines.append(f"**Winner bar:** {stats.get('winner_favs', 0):,} favs to reach top 10%")
            lines.append(f"**Median price:** R${stats.get('price_avg', 0)}")
            lines.append("\n**🥊 Top 10 competitors:**")
            lines.extend(comp_lines)
            lines.append("\n**🎯 Real keywords you could use in your title:**")
            lines.append(", ".join(f"`{k}`" for k in allow_list[:25]))
            lines.append("\nRetry `!rescue` in 5–10 minutes when AI is back.")

            body = "\n".join(lines)
            for i in range(0, len(body), 1900):
                await ctx.send(body[i:i + 1900])
            return

        try:
            await progress.delete()
        except Exception:
            pass

        lines = ["# 🩺 RESCUE REPORT\n"]

        if synth.get("diagnosis"):
            lines.append("## 🔍 Diagnosis"); lines.append(synth["diagnosis"]); lines.append("")

        if synth.get("what_winners_do"):
            lines.append("## 🏆 What Winners Do"); lines.append(synth["what_winners_do"]); lines.append("")

        groups = [
            ("🟢 SAFE (mirror winners)",         synth.get("titles_safe") or []),
            ("🎯 DIFFERENTIATED (unique angle)", synth.get("titles_differentiated") or []),
            ("🔎 LONG-TAIL SEO (4+ keywords)",   synth.get("titles_longtail") or []),
            ("🔥 VIRAL BAIT (meme hook)",        synth.get("titles_viral") or []),
        ]

        lines.append("## 📝 New Titles — Grouped by Strategy\n")
        total_verified = 0; total_rejected = 0
        for group_name, group_titles in groups:
            if not group_titles: continue
            verified, rejected = verify_titles(group_titles, allow_list)
            total_verified += len(verified)
            total_rejected += len(rejected)
            if verified:
                lines.append(f"**{group_name}**")
                for t in verified:
                    lines.append(f"• `{t}`")
                lines.append("")
        lines.append(f"_Total verified: **{total_verified}** · rejected: **{total_rejected}**_\n")

        if synth.get("new_description"):
            lines.append("## 📝 New Description (copy-paste)"); lines.append(synth["new_description"]); lines.append("")

        if synth.get("price_advice"):
            lines.append("## 💰 Price Advice"); lines.append(synth["price_advice"]); lines.append("")

        if synth.get("relaunch_plan"):
            lines.append("## 🚀 Relaunch Plan"); lines.append(synth["relaunch_plan"]); lines.append("")

        if synth.get("kill_or_keep"):
            lines.append("## ⚖️ Verdict"); lines.append(synth["kill_or_keep"]); lines.append("")

        lines.append("---")
        lines.append("**🥊 Top 10 competitors in your niche:**")
        lines.extend(comp_lines)
        lines.append("")
        lines.append(f"_Market: {stats.get('count', 0):,} competitors · "
                     f"winner bar {stats.get('winner_favs', 0):,} favs · "
                     f"median price R${stats.get('price_avg', 0)}_")

        body = "\n".join(lines)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i + 1900])
            await asyncio.sleep(0.3)

    @bot.command(name="analyze_image")
    async def analyze_image(ctx, *, description: str = ""):
        if not is_available():
            await ctx.send("AI is offline. Run `!ai_status`.")
            return

        if not ctx.message.attachments:
            await ctx.send(
                "**Usage:** attach 1-4 images and type `!analyze_image <notes>`\n"
                "Example: `!analyze_image my green slime cat beanie, 17 favs, R$75`\n"
                "_Tip: upload multiple angles for best analysis._"
            )
            return

        attachments = ctx.message.attachments[:4]
        if len(ctx.message.attachments) > 4:
            await ctx.send("ℹ️ Using first 4 images only.")

        progress = await ctx.send(f"🖼️ **Reading {len(attachments)} image(s)...**")

        images = []
        for a in attachments:
            ctype = a.content_type or ""
            if not ctype.startswith("image/"):
                continue
            try:
                b = await a.read()
            except Exception as e:
                await progress.edit(content=f"❌ Couldn't download `{a.filename}`: `{e}`")
                return
            if len(b) > 8 * 1024 * 1024:
                await ctx.send(f"⚠️ `{a.filename}` > 8MB — skipped.")
                continue
            images.append({"bytes": b, "mime": ctype})

        if not images:
            await progress.edit(content="❌ No valid image attachments found.")
            return

        await progress.edit(content=f"🖼️ **Analyzing {len(images)} image(s) with Gemini vision...**")
        try:
            vision = await asyncio.to_thread(analyze_image_for_ugc, images, description)
        except Exception as e:
            print(f"[analyze_image] vision failed: {e}", flush=True)
            vision = {}

        if not vision:
            try:
                await progress.delete()
            except Exception:
                pass
            lines = ["⚠️ **Vision analysis failed (both Gemini and OpenRouter).**\n"]
            lines.append("• `!brainstorm <casual description>` — describe the item in words")
            lines.append("• `!opportunity <keyword>` — market data without AI")
            lines.append("• Retry `!analyze_image` later")
            body = "\n".join(lines)
            for i in range(0, len(body), 1900):
                await ctx.send(body[i:i + 1900])
            return

        search_desc = vision.get("search_description", "")
        if not search_desc:
            parts = (vision.get("visual_style", [])
                     + vision.get("distinctive_features", [])
                     + vision.get("visual_colors", []))
            search_desc = " ".join(parts[:8]) or description or "ugc item"

        await progress.edit(
            content=(f"🖼️ **Vision done.**\n"
                     f"• Colors: `{', '.join(vision.get('visual_colors', []))}`\n"
                     f"• Style: `{', '.join(vision.get('visual_style', []))}`\n"
                     f"• Features: `{', '.join(vision.get('distinctive_features', []))}`\n"
                     f"• Item type: **{vision.get('item_type_visual', 'unknown')}**\n\n"
                     f"🔎 **Searching DB for similar items...**")
        )

        intent = extract_keywords(search_desc)
        if not intent:
            intent = {
                "primary": (vision.get("visual_style", []) + vision.get("distinctive_features", [])),
                "synonyms": [], "style": vision.get("visual_style", []),
                "vibe": vision.get("visual_mood", []),
                "colors": vision.get("visual_colors", []), "references": [],
                "search_terms": (vision.get("distinctive_features", []) + vision.get("visual_colors", [])),
                "item_type": vision.get("item_type_visual", "unknown"),
                "trend_source": "none",
            }
        intent["item_type"] = vision.get("item_type_visual", "unknown")
        family = detect_family_from_intent(intent)

        try:
            allow_list, top_items, stats = await asyncio.to_thread(
                _build_allow_list, intent, 60, None, family
            )
        except Exception as e:
            await progress.edit(content=f"❌ DB search failed: `{e}`")
            return

        if not allow_list:
            await progress.edit(content="❌ No DB items matched this visual description.")
            return

        await progress.edit(
            content=(f"📊 Matched **{stats['count']:,}** real items.\n"
                     f"🧠 **Pass 2:** Gemini strategist at work...")
        )

        full_desc = (
            f"[IMAGE DESCRIPTION] {vision.get('visual_summary', '')}\n"
            f"[DETECTED COLORS] {', '.join(vision.get('visual_colors', []))}\n"
            f"[DETECTED STYLE] {', '.join(vision.get('visual_style', []))}\n"
            f"[DETECTED MOOD] {', '.join(vision.get('visual_mood', []))}\n"
            f"[DISTINCTIVE FEATURES] {', '.join(vision.get('distinctive_features', []))}\n"
            f"[ITEM TYPE] {vision.get('item_type_visual', 'unknown')}\n"
            f"[LIKELY AESTHETIC] {', '.join(vision.get('likely_aesthetic', []))}\n"
            f"[LIKELY TREND SOURCE] {vision.get('likely_trend_source', 'none')}\n"
            f"[TREND CONTEXT] {vision.get('likely_trend_context', '')}\n"
            f"[VIBE REFERENCES] {', '.join(vision.get('vibe_references', []))}\n"
            f"[TARGET AUDIENCE] {vision.get('target_audience', '')}\n"
            f"[COLOR PSYCHOLOGY] {vision.get('color_psychology', '')}\n"
            f"[IP WARNING] {vision.get('ip_reference_warning', 'NONE')}\n"
            f"[CREATOR NOTES] {description or '(none)'}"
        )

        synth = None
        try:
            synth = await asyncio.to_thread(
                synthesize_hybrid, full_desc, allow_list, top_items, stats,
                family, "none",
                {"direct_matches": stats.get("direct_matches", 0),
                 "expansion_used": stats.get("expansion_used", False),
                 "expanded_terms": stats.get("expanded_terms", []),
                 "failed_terms": stats.get("failed_terms", []),
                 "reasoning": stats.get("reasoning", "")}
            )
        except Exception as e:
            print(f"[analyze_image] synth failed: {e}", flush=True)
            synth = None

        try:
            await progress.delete()
        except Exception:
            pass

        vision_lines = ["# 🖼️ IMAGE + CULTURE ANALYSIS\n"]
        vision_lines.append("## 👁️ What I See")
        vision_lines.append(vision.get("visual_summary", "—"))
        vision_lines.append("")
        vision_lines.append(f"**Colors:** {', '.join(f'`{c}`' for c in vision.get('visual_colors', []))}")
        vision_lines.append(f"**Style:** {', '.join(f'`{s}`' for s in vision.get('visual_style', []))}")
        vision_lines.append(f"**Features:** {', '.join(f'`{f}`' for f in vision.get('distinctive_features', []))}")
        vision_lines.append(f"**Detected item type:** `{vision.get('item_type_visual', 'unknown')}`")
        vision_lines.append("")

        if vision.get("likely_aesthetic"):
            vision_lines.append("## 🎨 Aesthetic")
            vision_lines.append(", ".join(f"`{a}`" for a in vision["likely_aesthetic"]))
            vision_lines.append("")
        if vision.get("likely_trend_context"):
            vision_lines.append("## 🌊 Trend Context")
            vision_lines.append(f"**Source:** `{vision.get('likely_trend_source', 'none')}`")
            vision_lines.append(vision["likely_trend_context"]); vision_lines.append("")
        if vision.get("vibe_references"):
            vision_lines.append("## 🎬 Vibe References")
            vision_lines.append(", ".join(f"`{r}`" for r in vision["vibe_references"])); vision_lines.append("")
        if vision.get("color_psychology"):
            vision_lines.append("## 🎨 Color Psychology"); vision_lines.append(vision["color_psychology"]); vision_lines.append("")
        if vision.get("target_audience"):
            vision_lines.append("## 👥 Target Audience"); vision_lines.append(vision["target_audience"]); vision_lines.append("")

        ip_warn = vision.get("ip_reference_warning", "NONE")
        if ip_warn and ip_warn != "NONE":
            vision_lines.append("## 🚨 IP / TRADEMARK WARNING")
            vision_lines.append(f"**{ip_warn}**\nDo NOT use names from that IP in the title.")
            vision_lines.append("")

        vision_body = "\n".join(vision_lines)
        for i in range(0, len(vision_body), 1900):
            await ctx.send(vision_body[i:i + 1900])

        if not synth:
            await ctx.send("⚠️ **Strategy synthesis failed.** The vision analysis above is still valid.")
            return

        all_groups = {
            "🟢 Safe (mirror winners)":          synth.get("titles_safe") or [],
            "🎯 Differentiated (unique angle)":  synth.get("titles_differentiated") or [],
            "🔎 Long-tail SEO (4+ keywords)":    synth.get("titles_longtail") or [],
            "🔥 Viral bait (meme hook)":         synth.get("titles_viral") or [],
        }
        if not any(all_groups.values()):
            all_groups = {"Titles": synth.get("titles") or []}

        verified_groups = {}
        total_verified = 0; total_rejected = 0
        for group_name, group_titles in all_groups.items():
            v, r = verify_titles(group_titles, allow_list)
            if v:
                verified_groups[group_name] = v
                total_verified += len(v)
            total_rejected += len(r)

        body = _fmt_ai_result(synth, verified_groups, [], stats,
                              family,
                              total_verified=total_verified,
                              total_rejected=total_rejected)

        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i + 1900])
            await asyncio.sleep(0.3)

    @bot.command(name="ai_debug")
    async def ai_debug(ctx):
        lines = ["**🔬 AI Debug Report**\n"]

        gkey = os.getenv("GEMINI_API_KEY", "")
        gmodel = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
        okey = os.getenv("OPENROUTER_API_KEY", "")
        omodel = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

        lines.append("**Env vars:**")
        lines.append(f"• GEMINI_API_KEY: `{gkey[:8] if gkey else 'MISSING'}...` (len {len(gkey)})")
        lines.append(f"• GEMINI_MODEL: `{gmodel}`")
        lines.append(f"• OPENROUTER_API_KEY: `{okey[:10] if okey else 'MISSING'}...` (len {len(okey)})")
        lines.append(f"• OPENROUTER_MODEL: `{omodel}`")
        lines.append("")

        lines.append("**Gemini test** (`say hello`):")
        if not gkey:
            lines.append("• ❌ GEMINI_API_KEY not set")
        else:
            try:
                from google import genai as g
                client = g.Client(api_key=gkey)
                resp = client.models.generate_content(model=gmodel, contents="Say only the word: hello")
                text = (resp.text or "").strip()
                if text:
                    lines.append(f"• ✅ Response: `{repr(text)[:80]}`")
                else:
                    lines.append("• ⚠️ Empty response")
            except Exception as e:
                lines.append(f"• ❌ {type(e).__name__}: `{str(e)[:200]}`")
        lines.append("")

        lines.append("**OpenRouter test** (`say hello`):")
        if not okey:
            lines.append("• ❌ OPENROUTER_API_KEY not set")
        else:
            try:
                from openai import OpenAI
                or_client = OpenAI(api_key=okey, base_url="https://openrouter.ai/api/v1")
                resp = or_client.chat.completions.create(
                    model=omodel,
                    messages=[{"role": "user", "content": "Say only the word: hello"}],
                    max_tokens=20,
                )
                text = (resp.choices[0].message.content or "").strip()
                if text:
                    lines.append(f"• ✅ Response: `{repr(text)[:80]}`")
                else:
                    lines.append("• ⚠️ Empty response")
            except Exception as e:
                lines.append(f"• ❌ {type(e).__name__}: `{str(e)[:200]}`")

        body = "\n".join(lines)
        for i in range(0, len(body), 1900):
            await ctx.send(body[i:i + 1900])
