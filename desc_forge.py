

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
