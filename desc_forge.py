"""
desc_forge.py — mine top descriptions in a niche, generate one that matches.

1. Query top 20 items by favorite_count in the keyword's niche (with descriptions)
2. Analyze pattern: line count, emoji density, first-sentence shape, top phrases
3. Feed real examples to Gemini → get a description that FITS the pattern
4. Return both the analysis and the generated description
"""
import re
import json
from collections import Counter
from bot_core import get_db
from convergence_engine import ASSET_TO_FAMILY


def _fetch_top_descriptions(keyword, family=None, limit=20):
    """Get top items in the niche that actually have descriptions."""
    conn = get_db(); cur = conn.cursor()
    try:
        fam_sql = ""
        fam_params = []
        if family:
            from convergence_engine import FAMILIES
            ids = FAMILIES.get(family)
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
              and length(trim(description)) > 10
              {fam_sql}
            order by favorite_count desc
            limit %s
        """, [pat] + fam_params + [limit])
        return cur.fetchall()
    finally:
        cur.close(); conn.close()


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

        tokens = re.findall(r"[a-z]{3,}", d.lower())
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


def _generate_description(keyword, family, rows, pattern):
    """Ask Gemini for one description that FITS the mined pattern."""
    from gemini_brain import _generate

    examples = []
    for name, desc, favs, price in rows[:12]:
        d = (desc or "").strip()
        if not d:
            continue
        examples.append(f"[{favs:,}♥] {name[:50]}\n{d[:400]}\n---")

    examples_block = "\n".join(examples) or "(no examples)"

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
- % with blank line separator: {pattern.get('pct_blank_line')}%
- Common first words: {', '.join(pattern.get('top_first_words') or [])}
- Common bigrams in winners: {', '.join(pattern.get('top_bigrams') or [])}

=== RULES ===
1. Match the average line count EXACTLY ({pattern.get('avg_lines')} lines).
2. Match the average emoji count ({pattern.get('avg_emojis')} emojis).
3. Use the same SHAPE as the top examples — if they lead with the item name, you lead with the item name. If they lead with a vibe word, you lead with a vibe word.
4. MUST include: {keyword}, and one type word (dance/emote/hat/etc).
5. NO corporate words: enhance, elevate, seamless, integration, designed for, experience, ultimate, leverage, compound, aligns, optimize.
6. Write like a real creator. Casual. Human. Not a marketing brochure.
7. Return ONLY the description text. No quotes, no labels, no preamble.

DESCRIPTION:"""

    raw = _generate(prompt, json_mode=False, temperature=0.85, max_tokens=600)
    return (raw or "").strip()


def forge_description(keyword, family=None):
    rows = _fetch_top_descriptions(keyword, family=family, limit=20)
    if not rows:
        return {
            "error": f"No items with descriptions found for `{keyword}`. "
                     f"Try a broader keyword or run the enricher."
        }

    pattern = _analyze_patterns(rows)
    try:
        description = _generate_description(keyword, family or "all", rows, pattern)
    except Exception as e:
        return {"error": f"AI generation failed: {e}", "pattern": pattern, "rows": rows}

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
        f"_Mined {p.get('sample_size', 0)} top items in this niche_",
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
