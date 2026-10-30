"""
desc_forge.py — mine top descriptions in a niche, generate one that matches.

FIXES in this version:
  - ACCESSORY UMBRELLA: "accessory" matches all 5 sub-types
    (43, 44, 45, 46, 47).
  - FAMILY FILTER: accepts items with unknown asset_type_id instead of
    silently dropping them. Fixes "30 results · 0 saved" bug.
  - Promo filter rejects: group promo, credits, rants, meme spam,
    all-caps, UGC self-branding, meme words.
  - Family translation between naming schemes.
  - Weak-pattern fallback prompt.
"""
import os
import re
import json
import requests
from collections import Counter
from bot_core import get_db
from convergence_engine import ASSET_TO_FAMILY


MIN_DB_RESULTS = 5

ROBLOX_SEARCH_URL = "https://catalog.roblox.com/v1/search/items/details"

ACCESSORY_IDS = [43, 44, 45, 46, 47]


# ─────────────────────────────────────────────────────────────────────
# PROMO SPAM FILTER
# ─────────────────────────────────────────────────────────────────────

_DECOR_SYMBOLS = set("♡♥⋆｡˚ฅﻌ°•·✧✦❀✿❁☆★彡ට็้ﺕ")

_MEME_WORDS = {
    "phrog", "froggy", "bois", "boi", "skibidi", "gyatt", "rizz",
    "mewing", "ohio", "fanum", "sussy", "sus", "goofy",
    "yass", "yasss", "gigachad", "lmao", "lmfao",
}


def _is_promo_spam(desc, name=None):
    if not desc:
        return True

    d = desc.strip()
    dl = d.lower()

    if any(x in dl for x in [
        "http://", "https://", "www.", ".com", ".gg", ".io",
        "roblox.com", "discord.gg", "discord.com", "youtube.com",
        "tiktok.com", "twitch.tv",
    ]):
        return True

    promo_markers = [
        "join the", "join our", "join for", "join us", "join me",
        "join posé", "join pose", "join discord", "join group",
        "join my", "join now",
        "the group", "in the group", "from the group", "of the group",
        "the group store", "group store", "our group store",
        "for more ugc", "for more items", "for more emotes",
        "for more cute", "for more", "want more", "get more",
        "shop more", "shop all", "shop now", "buy more",
        "check out our", "check out my", "check out the",
        "visit our", "visit my",
        "our store", "our group", "our community", "our catalog",
        "our ugc", "our emote", "our shop",
        "even better", "store:", "catalog:", "shop:", "group:",
        "follow us", "follow me", "follow for", "subscribe",
        "add to your collection", "exclusive ugc", "dmca",
        "support us", "support me", "support the",
    ]
    if any(m in dl for m in promo_markers):
        return True

    credit_markers = [
        "idea by", "idea:", "idea -",
        "credit to", "credits to", "credit:",
        "made by", "created by", "model by", "anim by", "animation by",
        "inspired by", "based on",
    ]
    if any(m in dl for m in credit_markers):
        return True

    reupload_markers = [
        "reupload", "re-upload", "original uploader", "original work",
        "i am the original", "i made this", "not stolen", "not a reupload",
        "please don't steal", "do not steal",
    ]
    if any(m in dl for m in reupload_markers):
        return True

    rant_markers = [
        "don't support", "do not support", "boycott", "corporations",
        "refuse to", "workers", "protest", "politics", "political",
        "free palestine", "black lives", "blm", "lgbtq",
    ]
    if any(m in dl for m in rant_markers):
        return True

    if dl.startswith("by ") or dl.startswith("by:"):
        return True

    if len(d) < 40:
        return True

    emoji_chars = sum(1 for c in d if ord(c) > 0x2600)
    if len(d) > 0 and emoji_chars > len(d) * 0.25:
        return True

    decor_count = sum(1 for c in d if c in _DECOR_SYMBOLS)
    if decor_count >= 3:
        real_words = re.findall(r"[a-zA-Z]{4,}", d)
        if len(real_words) < 5:
            return True

    if re.search(r"\b\w+\.(com|gg|io|net|org|tv|xyz)/", dl):
        return True

    tokens = re.findall(r"[a-z]{3,}", dl)
    if len(tokens) >= 4:
        top_count = Counter(tokens).most_common(1)[0][1]
        if top_count / len(tokens) > 0.4:
            return True

    if re.findall(r"\b[A-Z]{4,}\b", d):
        return True

    if re.search(r"\bugc\b", dl):
        return True

    token_set = set(tokens)
    meme_hits = len(token_set & _MEME_WORDS)
    if meme_hits >= 2:
        return True
    if meme_hits >= 1 and len(tokens) <= 6:
        return True

    if name:
        name_tokens = set(re.findall(r"[a-z]{3,}", (name or "").lower()))
        desc_tokens = set(tokens)
        if name_tokens and desc_tokens:
            overlap = len(name_tokens & desc_tokens)
            if (overlap / len(desc_tokens) >= 0.8
                    and len(desc_tokens) <= len(name_tokens) + 2):
                return True

    return False


def _filter_clean(rows, limit):
    clean = []
    for name, desc, favs, price in rows:
        if _is_promo_spam(desc, name=name):
            continue
        clean.append((name, desc, favs, price))
        if len(clean) >= limit:
            break
    return clean


# ─────────────────────────────────────────────────────────────────────
# DB QUERY
# ─────────────────────────────────────────────────────────────────────

def _query_db(keyword, family, limit):
    conn = get_db(); cur = conn.cursor()
    try:
        fam_sql = ""
        fam_params = []
        if family:
            if family == "accessory":
                # Umbrella — all 5 sub-types
                fam_sql = " and asset_type_id in (43, 44, 45, 46, 47)"
                fam_params = []
            else:
                from convergence_engine import FAMILIES
                try:
                    from category_configs import to_convergence_family
                    fam = to_convergence_family(family)
                except Exception:
                    fam = family
                if fam == "accessory":
                    fam_sql = " and asset_type_id in (43, 44, 45, 46, 47)"
                    fam_params = []
                else:
                    ids = FAMILIES.get(fam)
                    if ids:
                        ph = ",".join(["%s"] * len(ids))
                        fam_sql = f" and asset_type_id in ({ph})"
                        fam_params = list(ids)

        kw = keyword.strip().lower()
        if " " in kw:
            match_op, pat = "ilike", f"%{kw}%"
        else:
            match_op, pat = "~*", rf"\y{re.escape(kw)}\y"

        cur.execute(f"""
            select name, description, favorite_count, price
            from items
            where name {match_op} %s
              and favorite_count > 50
              and description is not null
              and length(trim(description)) > 20
              {fam_sql}
            order by favorite_count desc
            limit %s
        """, [pat] + fam_params + [limit * 5])
        return cur.fetchall()
    finally:
        cur.close(); conn.close()


# ─────────────────────────────────────────────────────────────────────
# LIVE FALLBACK
# ─────────────────────────────────────────────────────────────────────

def _family_to_roblox_category(family):
    if not family:
        return None
    if family == "accessory":
        return None  # umbrella — no single category
    try:
        from category_configs import to_convergence_family
        fam = to_convergence_family(family)
    except Exception:
        fam = family
    if fam == "accessory":
        return None
    return {
        "hair":     12,
        "face":     13,
        "neck":     5,
        "shoulder": 9,
        "front":    7,
        "back":     8,
        "waist":    6,
    }.get(fam)


def _fetch_live_descriptions(keyword, family=None, limit=20):
    try:
        cookie = (os.getenv("ROBLOSECURITY_COOKIE_1")
                  or os.getenv("ROBLOSECURITY_COOKIE"))
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; UGCBot/1.0)",
            "Accept": "application/json",
        }
        if cookie:
            headers["Cookie"] = f".ROBLOSECURITY={cookie}"

        conv_family = family
        if family and family != "accessory":
            try:
                from category_configs import to_convergence_family
                conv_family = to_convergence_family(family)
            except Exception:
                pass

        cat = _family_to_roblox_category(conv_family)

        params = {
            "Keyword": keyword,
            "Limit": 30,
            "SortType": 3,
        }
        if cat:
            params["Category"] = cat

        r = requests.get(ROBLOX_SEARCH_URL, params=params,
                         headers=headers, timeout=15)

        if r.status_code != 200:
            print(f"[desc_forge] live search HTTP {r.status_code}", flush=True)
            return []

        data = (r.json() or {}).get("data", []) or []
        if not data:
            print(f"[desc_forge] live search 0 results", flush=True)
            return []

        out = []
        saved = 0
        conn = get_db(); cur = conn.cursor()
        try:
            for item in data:
                item_id = item.get("id")
                name = (item.get("name") or "").strip()
                desc = (item.get("description") or "").strip()
                favs = item.get("favoriteCount") or 0
                price = item.get("price") or 0
                atype = item.get("assetType") or 0
                creator = item.get("creatorName") or ""

                if not item_id or not name:
                    continue
                if favs < 50:
                    continue

                # Accessory umbrella — match any sub-type
                if conv_family == "accessory" and atype not in ACCESSORY_IDS:
                    continue
                # Regular family filter — only reject if we KNOW the type
                # doesn't match. Unknown asset types are accepted rather
                # than silently dropped. Fixes "30 results · 0 saved".
                elif conv_family and conv_family != "accessory":
                    item_family = ASSET_TO_FAMILY.get(atype)
                    if item_family and item_family != conv_family:
                        continue

                try:
                    cur.execute("""
                        insert into items (id, name, description, favorite_count,
                                           price, asset_type_id, creator_name, fetched_at)
                        values (%s, %s, %s, %s, %s, %s, %s, now())
                        on conflict (id) do update set
                            description = excluded.description,
                            favorite_count = excluded.favorite_count,
                            price = excluded.price,
                            fetched_at = now()
                    """, (item_id, name, desc, favs, price, atype, creator))
                    saved += 1
                except Exception as e:
                    print(f"[desc_forge] save {item_id} failed: {e}", flush=True)
                    continue

                out.append((name, desc, favs, price))

            conn.commit()
        finally:
            cur.close(); conn.close()

        print(f"[desc_forge] live: {len(data)} results · {saved} saved", flush=True)
        return out

    except Exception as e:
        print(f"[desc_forge] live fallback failed: {e}", flush=True)
        return []


# ─────────────────────────────────────────────────────────────────────
# MAIN FETCH
# ─────────────────────────────────────────────────────────────────────

_KEYWORD_STOP = {
    "the", "a", "an", "for", "with", "and", "of", "to", "my", "our",
    "new", "best", "item", "items", "ugc", "roblox", "edition",
}


def _candidate_keywords(keyword):
    """Progressively simpler mining keywords so a full item title like
    'Cute Kitty Fluffy Beanie' still finds top sellers."""
    words = re.findall(r"[a-z0-9]+", (keyword or "").lower())
    toks = [w for w in words if w not in _KEYWORD_STOP and len(w) >= 3]
    candidates = []
    if (keyword or "").strip():
        candidates.append(keyword.strip())
    if len(toks) >= 2:
        candidates.append(" ".join(toks[-2:]))
    if toks:
        candidates.append(toks[-1])
    if len(toks) >= 2:
        candidates.append(" ".join(toks[:-1]))
    for tok in reversed(toks):
        candidates.append(tok)
    seen, out = set(), []
    for c in candidates:
        c = c.strip().lower()
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _query_family_fallback(family, limit):
    """Last resort: top items in the family with clean descriptions."""
    conn = get_db()
    cur = conn.cursor()
    try:
        fam_ids = []
        if family:
            try:
                from convergence_engine import FAMILIES
                from category_configs import to_convergence_family
                fam = to_convergence_family(family)
            except Exception:
                fam = family
            if fam == "accessory":
                fam_ids = ACCESSORY_IDS
            else:
                fam_ids = FAMILIES.get(fam) or []
        sql = """
            select name, description, favorite_count, price
            from items
            where favorite_count > 200
              and description is not null
              and length(trim(description)) > 40
        """
        params = []
        if fam_ids:
            sql += " and asset_type_id in (%s)" % ",".join(["%s"] * len(fam_ids))
            params = list(fam_ids)
        sql += " order by favorite_count desc limit %s"
        params.append(limit * 5)
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


def _fetch_top_descriptions(keyword, family=None, limit=20):
    best = []
    for kw in _candidate_keywords(keyword):
        try:
            rows = _query_db(kw, family, limit)
        except Exception as e:
            print(f"[desc_forge] db query failed for '{kw}': {e}", flush=True)
            continue
        clean = _filter_clean(rows, limit)
        if len(clean) >= MIN_DB_RESULTS:
            print(f"[desc_forge] keyword '{kw}' -> {len(clean)} clean", flush=True)
            return clean
        if len(clean) > len(best):
            best = clean

    clean = best
    if len(clean) < MIN_DB_RESULTS:
        print(f"[desc_forge] DB thin ({len(clean)} clean) → live fallback", flush=True)
        live_kw = (_candidate_keywords(keyword) or [keyword])[-1]
        live_rows = _fetch_live_descriptions(live_kw, family, limit)
        live_clean = _filter_clean(live_rows, limit)

        seen_names = set()
        merged = []
        for r in clean + live_clean:
            key = (r[0] or "").lower().strip()
            if key in seen_names:
                continue
            seen_names.add(key)
            merged.append(r)
            if len(merged) >= limit:
                break
        clean = merged

    if not clean:
        print("[desc_forge] falling back to family top sellers", flush=True)
        try:
            clean = _filter_clean(_query_family_fallback(family, limit), limit)
        except Exception as e:
            print(f"[desc_forge] family fallback failed: {e}", flush=True)

    return clean


# ─────────────────────────────────────────────────────────────────────
# PATTERN ANALYSIS
# ─────────────────────────────────────────────────────────────────────

def _analyze_patterns(rows):
    if not rows:
        return {}

    lines_counts = []
    emoji_counts = []
    char_lengths = []
    all_bigrams = Counter()
    first_words = Counter()
    has_emoji_line1 = 0
    has_blank_line = 0

    emoji_re = re.compile(
        "[" "\U0001F300-\U0001F9FF"
        "\U0001F600-\U0001F64F"
        "\U0001F680-\U0001F6FF"
        "\u2600-\u27BF"
        "\uFE0F" "]+",
        flags=re.UNICODE,
    )

    url_re = re.compile(r"https?://\S+|www\.\S+|\S+\.com\S*|\S+\.gg\S*")

    for name, desc, favs, price in rows:
        d = (desc or "").strip()
        if not d:
            continue
        lines = [ln for ln in d.split("\n") if ln.strip()]
        lines_counts.append(len(lines))
        char_lengths.append(len(d))

        emojis = emoji_re.findall(d)
        emoji_counts.append(len(emojis))

        if lines:
            first = lines[0]
            if emoji_re.search(first):
                has_emoji_line1 += 1
            words = re.findall(r"[a-zA-Z']+", first.lower())
            if words:
                first_words[words[0]] += 1

        if "\n\n" in d:
            has_blank_line += 1

        d_clean = url_re.sub("", d)
        tokens = re.findall(r"[a-z]{3,}", d_clean.lower())
        for a, b in zip(tokens, tokens[1:]):
            all_bigrams[f"{a} {b}"] += 1

    total = len([r for r in rows if r[1]])
    if total == 0:
        return {}

    avg_lines = sum(lines_counts) / len(lines_counts) if lines_counts else 0
    avg_emojis = sum(emoji_counts) / len(emoji_counts) if emoji_counts else 0
    avg_chars = sum(char_lengths) / len(char_lengths) if char_lengths else 0

    return {
        "sample_size": total,
        "avg_lines": round(avg_lines, 1),
        "avg_emojis": round(avg_emojis, 1),
        "avg_chars": int(avg_chars),
        "pct_emoji_first_line": round(100 * has_emoji_line1 / total, 0),
        "pct_blank_line": round(100 * has_blank_line / total, 0),
        "top_first_words": [w for w, _ in first_words.most_common(5)],
        "top_bigrams": [b for b, _ in all_bigrams.most_common(12)],
    }


# ─────────────────────────────────────────────────────────────────────
# AI GENERATION
# ─────────────────────────────────────────────────────────────────────

def _generate_description(keyword, family, rows, pattern):
    from gemini_brain import _generate

    examples = []
    for name, desc, favs, price in rows[:12]:
        d = (desc or "").strip()
        if not d:
            continue
        examples.append(f"[{favs:,}♥] {name[:50]}\n{d[:400]}\n---")

    examples_block = "\n".join(examples) or "(no examples)"

    avg_chars = pattern.get("avg_chars", 0)
    phrases = pattern.get("top_bigrams") or []
    first_words = pattern.get("top_first_words") or []
    target_chars = max(320, int((avg_chars or 200) * 1.4))

    prompt = f"""You write high-converting Roblox UGC descriptions. Write ONE powerful
description for a {family} item about: {keyword}.

Real top-seller descriptions in this niche (tone and structure only):
{examples_block}

=== STRUCTURE (4-6 short lines) ===
1. Hook line: the keyword + one type word + ONE emoji.
2. 1-3 feature/benefit lines: how it looks, moves, or sits, and why people want it.
3. One fit/aesthetic line: which outfits or vibes it matches.
4. Weave these high-value phrases naturally into the body — do NOT write "tags:",
   do NOT list them, do NOT stuff commas: {', '.join(phrases[:8])}

=== RULES (non-negotiable) ===
- No URLs, group links, "join", credits, or creator names.
- No corporate filler: enhance, elevate, seamless, ultimate, leverage, optimize, experience.
- No invented numbers or claims.
- Casual human creator voice. Aim for about {target_chars} characters.
- Every line must read like a sentence. Never end with a keyword list or a line
  of separated nouns/adjectives.
- Return ONLY the description text. No labels, no quotes, no preamble.

DESCRIPTION:"""

    raw = _generate(prompt, json_mode=False, temperature=0.85, max_tokens=800)
    return (raw or "").strip()


# ─────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────

def forge_description(keyword, family=None):
    rows = _fetch_top_descriptions(keyword, family=family, limit=20)
    if not rows:
        return {
            "error": f"No items with clean descriptions found for `{keyword}`. "
                     f"Roblox live search also returned nothing usable."
        }

    pattern = _analyze_patterns(rows)
    try:
        description = _generate_description(keyword, family or "all", rows, pattern)
    except Exception as e:
        return {"error": f"AI generation failed: {e}",
                "pattern": pattern, "rows": rows}

    return {
        "keyword": keyword,
        "family": family or "all",
        "pattern": pattern,
        "description": description,
        "examples": rows[:8],
    }


def format_forge(result):
    if result.get("error"):
        return [f"❌ {result['error']}"]

    p = result["pattern"]
    rows = result.get("examples", [])
    kw = result["keyword"]

    chunks = []

    header = [
        f"# 🔨 DESC FORGE — `{kw}`",
        f"_Mined {p.get('sample_size', 0)} clean descriptions in this niche_",
        "",
        "## 📊 Pattern from top sellers",
        f"• Lines: **{p.get('avg_lines')}** avg",
        f"• Emojis: **{p.get('avg_emojis')}** avg",
        f"• Length: **{p.get('avg_chars')}** chars",
        f"• Emoji on line 1: **{p.get('pct_emoji_first_line')}%**",
        f"• Common first words: `{', '.join(p.get('top_first_words') or [])}`",
        f"• Common phrases: `{', '.join(p.get('top_bigrams')[:8])}`",
    ]
    chunks.append("\n".join(header))

    if result.get("description"):
        d = result["description"]
        chunks.append(
            f"## ✨ Generated description\n```\n{d[:1500]}\n```"
        )

    if rows:
        examples_lines = ["## 🔍 Top examples it studied"]
        for name, desc, favs, price in rows[:5]:
            d = (desc or "").strip().replace("\n", " ")
            examples_lines.append(
                f"**{name[:50]}** — {favs:,}♥\n_{d[:150]}_"
            )
        chunks.append("\n".join(examples_lines))

    return chunks


def pattern_prompt_block(keyword, family=None, max_examples=5):
    try:
        rows = _fetch_top_descriptions(keyword, family=family, limit=15)
        if not rows:
            return ""
        pattern = _analyze_patterns(rows)

        lines = [
            "",
            "=== REAL TOP DESCRIPTIONS IN THIS NICHE (style-match these) ===",
            f"Pattern: {pattern.get('avg_lines')} lines avg · "
            f"{pattern.get('avg_emojis')} emojis avg · "
            f"{pattern.get('avg_chars')} chars avg · "
            f"{pattern.get('pct_emoji_first_line')}% have emoji on line 1",
            f"Common first words: {', '.join(pattern.get('top_first_words') or [])}",
            f"Common bigrams: {', '.join((pattern.get('top_bigrams') or [])[:8])}",
            "",
            "Real examples to copy the STYLE of (not the text):",
        ]
        for name, desc, favs, price in rows[:max_examples]:
            d = (desc or "").strip()[:300]
            if not d:
                continue
            lines.append(f"[{favs:,}♥] {name[:45]}")
            lines.append(d)
            lines.append("---")
        lines.append("")

        return "\n".join(lines)
    except Exception as e:
        print(f"[desc_forge] pattern_prompt_block failed: {e}", flush=True)
        return ""
