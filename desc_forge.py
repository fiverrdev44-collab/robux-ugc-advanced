"""
desc_forge.py — mine top descriptions in a niche, generate one that matches.

1. Query top items by favorite_count in the niche (with descriptions)
2. Filter out promo spam / URLs / credits / rants / meme spam / all-caps
3. If DB has fewer than MIN_DB_RESULTS clean rows → fallback to Roblox live search
4. Analyze pattern: line count, emoji density, top phrases
5. Feed real examples to Gemini → get a description that FITS the pattern
6. Never output URLs — prompt explicitly forbids hallucinated links

FIXES in this version:
  - Promo filter now rejects: "the group"/"in the group"/"group store",
    reupload/ownership claims, political rants, word-repetition (meme spam),
    description-is-item-name rows, decorative-symbol spam, ALL-CAPS words
    (PHROG/AAAA), "UGC" as a word (self-branding), meme-word blacklist
    (bois/phrog/froggy/skibidi/gyatt/etc).
  - _query_db and _fetch_live_descriptions translate category_configs
    family names → convergence_engine names before lookup.
  - _generate_description falls back to a standard 3-line prompt when
    mined pattern is weak (sample<10, avg_chars<80, avg_lines<1.5).
"""
import os
import re
import json
import requests
from collections import Counter
from bot_core import get_db
from convergence_engine import ASSET_TO_FAMILY


# Minimum clean descriptions from DB before we call Roblox live.
MIN_DB_RESULTS = 5

ROBLOX_SEARCH_URL = "https://catalog.roblox.com/v1/search/items/details"


# ─────────────────────────────────────────────────────────────────────
# PROMO SPAM FILTER
# ─────────────────────────────────────────────────────────────────────

# Decorative symbols that signal spam/meme descriptions when present
# in significant quantity. Katakana/kaomoji parts + cute glyphs.
_DECOR_SYMBOLS = set("♡♥⋆｡˚ฅﻌ°•·✧✦❀✿❁☆★彡ට็้ﺕ")

# Meme words that appear in troll UGC descriptions.
_MEME_WORDS = {
    "phrog", "froggy", "bois", "boi", "skibidi", "gyatt", "rizz",
    "mewing", "ohio", "fanum", "sussy", "sus", "goofy",
    "yass", "yasss", "gigachad", "lmao", "lmfao",
}


def _is_promo_spam(desc, name=None):
    """
    Returns True if description is dominated by URLs, group links,
    creator credits, decorative-symbol spam, political rants,
    reupload notes, meme word-repetition, ALL-CAPS emphasis, or
    self-branding like "x's UGC".

    Optional `name` allows rejecting rows where the description is
    just a repeat of the item name.
    """
    if not desc:
        return True

    d = desc.strip()
    dl = d.lower()

    # ── URLs (any form) ────────────────────────────────────────
    if any(x in dl for x in [
        "http://", "https://", "www.", ".com", ".gg", ".io",
        "roblox.com", "discord.gg", "discord.com", "youtube.com",
        "tiktok.com", "twitch.tv",
    ]):
        return True

    # ── Group / store / catalog promo ──────────────────────────
    promo_markers = [
        # Joining
        "join the", "join our", "join for", "join us", "join me",
        "join posé", "join pose", "join discord", "join group",
        "join my", "join now",
        # "the group" / "group store" catch-alls
        "the group", "in the group", "from the group", "of the group",
        "the group store", "group store", "our group store",
        # More items
        "for more ugc", "for more items", "for more emotes",
        "for more cute", "for more", "want more", "get more",
        # Store / catalog
        "shop more", "shop all", "shop now", "buy more",
        "check out our", "check out my", "check out the",
        "visit our", "visit my",
        # Branding
        "our store", "our group", "our community", "our catalog",
        "our ugc", "our emote", "our shop",
        "even better", "store:", "catalog:", "shop:", "group:",
        # Follow/subscribe CTAs
        "follow us", "follow me", "follow for", "subscribe",
        "add to your collection", "exclusive ugc", "dmca",
        "support us", "support me", "support the",
    ]
    if any(m in dl for m in promo_markers):
        return True

    # ── Creator credits (not descriptions) ─────────────────────
    credit_markers = [
        "idea by", "idea:", "idea -",
        "credit to", "credits to", "credit:",
        "made by", "created by", "model by", "anim by", "animation by",
        "inspired by", "based on",
    ]
    if any(m in dl for m in credit_markers):
        return True

    # ── Reupload / ownership claims ────────────────────────────
    reupload_markers = [
        "reupload", "re-upload", "original uploader", "original work",
        "i am the original", "i made this", "not stolen", "not a reupload",
        "please don't steal", "do not steal",
    ]
    if any(m in dl for m in reupload_markers):
        return True

    # ── Political / rant content ───────────────────────────────
    rant_markers = [
        "don't support", "do not support", "boycott", "corporations",
        "refuse to", "workers", "protest", "politics", "political",
        "free palestine", "black lives", "blm", "lgbtq",
    ]
    if any(m in dl for m in rant_markers):
        return True

    # Leading "by <name>" (creator attribution as first token)
    if dl.startswith("by ") or dl.startswith("by:"):
        return True

    # ── Too short ──────────────────────────────────────────────
    if len(d) < 40:
        return True

    # ── Emoji-dominated ────────────────────────────────────────
    emoji_chars = sum(1 for c in d if ord(c) > 0x2600)
    if len(d) > 0 and emoji_chars > len(d) * 0.25:
        return True

    # ── Decorative-symbol spam ─────────────────────────────────
    decor_count = sum(1 for c in d if c in _DECOR_SYMBOLS)
    if decor_count >= 3:
        real_words = re.findall(r"[a-zA-Z]{4,}", d)
        if len(real_words) < 5:
            return True

    # ── URL fragments (bare domains without scheme) ────────────
    if re.search(r"\b\w+\.(com|gg|io|net|org|tv|xyz)/", dl):
        return True

    # ── Word-repetition (meme spam) ────────────────────────────
    # Top token exceeds 40% of all tokens → meme spam.
    tokens = re.findall(r"[a-z]{3,}", dl)
    if len(tokens) >= 4:
        top_count = Counter(tokens).most_common(1)[0][1]
        if top_count / len(tokens) > 0.4:
            return True

    # ── ALL-CAPS emphasis ──────────────────────────────────────
    # "PHROG" / "AAAA" / "LOL" in caps 4+ chars = spam signal.
    if re.findall(r"\b[A-Z]{4,}\b", d):
        return True

    # ── UGC self-branding ──────────────────────────────────────
    # Real creators don't say "x's UGC" in the item description.
    if re.search(r"\bugc\b", dl):
        return True

    # ── Meme-word blacklist ────────────────────────────────────
    token_set = set(tokens)
    meme_hits = len(token_set & _MEME_WORDS)
    if meme_hits >= 2:
        return True
    if meme_hits >= 1 and len(tokens) <= 6:
        return True

    # ── Description IS the item name ───────────────────────────
    if name:
        name_tokens = set(re.findall(r"[a-z]{3,}", (name or "").lower()))
        desc_tokens = set(tokens)
        if name_tokens and desc_tokens:
            overlap = len(name_tokens & desc_tokens)
            # 80%+ of desc tokens came from the name AND desc adds
            # little new content → reject.
            if (overlap / len(desc_tokens) >= 0.8
                    and len(desc_tokens) <= len(name_tokens) + 2):
                return True

    return False


def _filter_clean(rows, limit):
    """Filter out promo spam, keep up to `limit`."""
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
            from convergence_engine import FAMILIES
            try:
                from category_configs import to_convergence_family
                fam = to_convergence_family(family)
            except Exception:
                fam = family
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
# LIVE FALLBACK — Roblox catalog search when DB is thin
# ─────────────────────────────────────────────────────────────────────

def _family_to_roblox_category(family):
    """Map our family name to Roblox catalog Category id (best-effort)."""
    if not family:
        return None
    try:
        from category_configs import to_convergence_family
        fam = to_convergence_family(family)
    except Exception:
        fam = family
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
    """
    Search Roblox catalog for `keyword`, grab top sellers with descriptions,
    save to DB (upsert), return rows in the same shape as _query_db.
    Safe: returns [] on any failure.
    """
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

                if conv_family and ASSET_TO_FAMILY.get(atype) != conv_family:
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
# MAIN FETCH — DB first, live fallback if thin
# ─────────────────────────────────────────────────────────────────────

def _fetch_top_descriptions(keyword, family=None, limit=20):
    """
    DB first. If fewer than MIN_DB_RESULTS clean rows, fall back to live
    Roblox search and merge. Live results are saved to DB.
    """
    rows = _query_db(keyword, family, limit)
    clean = _filter_clean(rows, limit)

    if len(clean) < MIN_DB_RESULTS:
        print(f"[desc_forge] DB thin ({len(clean)} clean) → live fallback", flush=True)
        live_rows = _fetch_live_descriptions(keyword, family, limit)
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

    return clean


# ─────────────────────────────────────────────────────────────────────
# PATTERN ANALYSIS
# ─────────────────────────────────────────────────────────────────────

def _analyze_patterns(rows):
    """Extract statistical pattern from real descriptions."""
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
# AI GENERATION — hard bans on URLs and corporate words
# ─────────────────────────────────────────────────────────────────────

def _generate_description(keyword, family, rows, pattern):
    """Ask Gemini for one description that FITS the mined pattern. NO URLs."""
    from gemini_brain import _generate

    examples = []
    for name, desc, favs, price in rows[:12]:
        d = (desc or "").strip()
        if not d:
            continue
        examples.append(f"[{favs:,}♥] {name[:50]}\n{d[:400]}\n---")

    examples_block = "\n".join(examples) or "(no examples)"

    sample = pattern.get("sample_size", 0)
    avg_chars = pattern.get("avg_chars", 0)
    avg_lines = pattern.get("avg_lines", 0)

    weak_pattern = (
        sample < 10
        or avg_chars < 80
        or avg_lines < 1.5
    )

    if weak_pattern:
        prompt = f"""You write Roblox UGC descriptions for {family} items.

The DB is thin for '{keyword}' — do NOT copy any pattern below.
Write a STANDARD strong Roblox UGC description instead.

=== REQUIRED FORMAT (3 lines) ===
Line 1: <keyword> + type word + ONE emoji. Example:
        "Kawaii Plush Beanie 🎀"
Line 2: 2-3 adjectives + use case. Example:
        "Soft pastel fleece for cozy winter fits."
Line 3: vibe / mood. Example:
        "Perfect for cottagecore and preppy outfits."

=== ABSOLUTE RULES ===
1. NEVER include URLs, group links, or "join" language.
2. NEVER reference creators, "by X", "idea by", or credits.
3. NO corporate words: enhance, elevate, seamless, integration,
   designed for, experience, ultimate, leverage, optimize.
4. Include keyword: {keyword}
5. Include a type word for {family} (hat/beanie/hair/dance/etc).
6. Casual, human, creator-voice. 3 lines exactly.
7. Return ONLY the description text. No quotes, no labels.

REAL EXAMPLES FROM THIS NICHE FOR TONE ONLY:
{examples_block}

DESCRIPTION:"""
    else:
        prompt = f"""You write Roblox UGC descriptions. Style-match the real top-seller examples below.

=== NICHE ===
Keyword: {keyword}
Category: {family}

=== REAL TOP DESCRIPTIONS IN THIS NICHE (copy their STYLE, not their text) ===
{examples_block}

=== MINED PATTERN ===
- Average line count: {pattern.get('avg_lines')} lines
- Average emoji count: {pattern.get('avg_emojis')} per description
- Average character count: {pattern.get('avg_chars')}
- % with emoji on first line: {pattern.get('pct_emoji_first_line')}%
- Common first words: {', '.join(pattern.get('top_first_words') or [])}

=== ABSOLUTE RULES (NON-NEGOTIABLE) ===
1. NEVER include URLs. No http://, no https://, no www., no .com, no .gg, no roblox.com links.
2. NEVER invent a Roblox community link, catalog link, or store link.
3. NEVER write "join our", "shop our", "visit our", or any group promo.
4. NEVER reference a specific creator or group by name.
5. Match the average line count EXACTLY ({pattern.get('avg_lines')} lines).
6. Match the average emoji count ({pattern.get('avg_emojis')} emojis).
7. MUST include: {keyword}, and one type word (dance/emote/hat/etc).
8. NO corporate words: enhance, elevate, seamless, integration, designed for, experience, ultimate, leverage, compound, aligns, optimize.
9. Write like a real creator describing their item. Casual. Human.
10. Return ONLY the description text. No quotes, no labels, no preamble.
11. If the real examples contain URLs, IGNORE that aspect — we do NOT want URLs.

Good example of correct output:
Smooth hip sway dance emote 🎀
Cute motion animation with lively steps and bouncy energy.
Perfect for chillin with friends, party fits, or trending.

DESCRIPTION:"""

    raw = _generate(prompt, json_mode=False, temperature=0.85, max_tokens=600)
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
    """Returns list of Discord message chunks."""
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
    """
    Compact pattern + real examples for prompt injection.
    Returns "" on any failure — safe to call anytime.
    """
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
