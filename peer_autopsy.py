"""
peer_autopsy.py — compare an item to its 5 nearest winners.

Answers ONE question: what do the winners have that this item doesn't?
Every diff is specific and actionable.
"""
import re
from bot_core import get_db


_STOP = {"the", "and", "with", "for", "of", "in", "on", "at", "to", "a", "an",
         "emote", "dance", "animation"}


def _words(name):
    return [w for w in re.findall(r"[a-z]{3,}", (name or "").lower())
            if w not in _STOP]


def find_peers(cur, item_id, top_n=5):
    """Find nearest winners in the same niche (keyword overlap)."""
    cur.execute("""
        select name, favorite_count, price, asset_type_id,
               extract(epoch from (now() - created_at))/86400.0 as age_days
        from items where id = %s
    """, (item_id,))
    row = cur.fetchone()
    if not row:
        return None
    name, favs, price, atype, age = row

    my_words = _words(name)
    if not my_words:
        return None

    # Candidates: same asset_type, any of my words, favorites > 100
    patterns = [f"%{w}%" for w in my_words]
    cur.execute("""
        select name, favorite_count, price,
               extract(epoch from (now() - created_at))/86400.0 as age_days
        from items
        where asset_type_id = %s
          and id != %s
          and favorite_count > 100
          and lower(name) like any(%s)
        order by favorite_count desc
        limit 50
    """, (atype, item_id, patterns))
    candidates = cur.fetchall()

    # Rank by keyword overlap + velocity
    scored = []
    for cn, cf, cp, ca in candidates:
        cw = set(_words(cn))
        overlap = len(set(my_words) & cw)
        if overlap < 1:
            continue
        ca = float(ca or 1)
        velocity = cf / ca
        scored.append({
            "name": cn, "favs": cf, "price": cp or 0,
            "age": round(ca, 1), "velocity": round(velocity, 2),
            "overlap": overlap,
            "word_count": len(_words(cn)),
            "has_parens": "(" in cn,
            "has_emoji": any(ord(c) > 0x2600 for c in cn),
            "lead_word": (_words(cn) or [""])[0],
        })

    # Sort: overlap desc, velocity desc
    scored.sort(key=lambda x: (-x["overlap"], -x["velocity"]))
    return {
        "my_name": name,
        "my_favs": favs or 0,
        "my_price": price or 0,
        "my_age": round(float(age or 1), 1),
        "my_velocity": round((favs or 0) / max(float(age or 1), 1), 2),
        "my_words": my_words,
        "peers": scored[:top_n],
    }


def analyze_diffs(pd):
    """What do winners have that this item doesn't."""
    if not pd or not pd.get("peers"):
        return None
    peers = pd["peers"]
    my_words_set = set(pd["my_words"])

    avg_words = sum(p["word_count"] for p in peers) / len(peers)
    avg_velocity = sum(p["velocity"] for p in peers) / len(peers)
    no_parens = sum(1 for p in peers if not p["has_parens"])
    no_emoji = sum(1 for p in peers if not p["has_emoji"])

    # Which non-category keywords do peers use that I don't
    peer_kw = set()
    for p in peers:
        peer_kw.update(_words(p["name"]))
    missing_kw = sorted(peer_kw - my_words_set)[:8]

    # Lead words (excluding my own)
    lead_words = list(dict.fromkeys(
        p["lead_word"] for p in peers if p["lead_word"]
    ))[:5]

    my_word_count = len(pd["my_words"])
    my_has_parens = "(" in pd["my_name"]
    my_has_emoji = any(ord(c) > 0x2600 for c in pd["my_name"])

    ratio = pd["my_velocity"] / max(avg_velocity, 0.01)

    return {
        "avg_words": round(avg_words, 1),
        "avg_velocity": round(avg_velocity, 2),
        "ratio": round(ratio, 2),
        "my_word_count": my_word_count,
        "my_has_parens": my_has_parens,
        "my_has_emoji": my_has_emoji,
        "peers_no_parens": f"{no_parens}/{len(peers)}",
        "peers_no_emoji": f"{no_emoji}/{len(peers)}",
        "top_lead_words": lead_words,
        "missing_keywords": missing_kw,
    }


def build_verdict(pd, diffs):
    """One-sentence save-or-kill verdict."""
    if not diffs:
        return "Insufficient data."

    ratio = diffs["ratio"]
    my_v = pd["my_velocity"]
    avg_v = diffs["avg_velocity"]

    if ratio >= 0.8:
        return ("✅ **KEEP.** You're already near peer average. "
                "Post 2 TikToks, don't touch the name.")
    if ratio >= 0.3:
        fix_count = 0
        fixes = []
        if diffs["my_has_parens"]:
            fixes.append("remove parens")
            fix_count += 1
        if diffs["my_has_emoji"]:
            fixes.append("remove emoji")
            fix_count += 1
        if diffs["my_word_count"] > diffs["avg_words"]:
            fixes.append(f"shorten to {diffs['avg_words']:.0f} words")
            fix_count += 1
        if diffs["missing_keywords"]:
            fixes.append(f"add `{diffs['missing_keywords'][0]}`")
            fix_count += 1

        fix_str = " + ".join(fixes[:3]) if fixes else "rename only"
        return (
            f"🔧 **RESCUE.** You're at {ratio:.0%} of peer velocity. "
            f"Fix: **{fix_str}**. 30 min work. Re-check in 14d."
        )
    return (
        f"🪦 **KILL.** {ratio:.0%} of peer velocity ({my_v}/day vs "
        f"{avg_v}/day). Even perfect rename gets you to ~half their velocity. "
        f"Launch a new item."
    )


def peer_autopsy(item_id, top_n=5):
    """Main entry — returns list of message chunks."""
    conn = get_db(); cur = conn.cursor()
    try:
        pd = find_peers(cur, item_id, top_n=top_n)
        if not pd:
            return ["❌ Item not found or no peers."]
        diffs = analyze_diffs(pd)
        if not diffs:
            return ["❌ Not enough peer data yet."]
        verdict = build_verdict(pd, diffs)
        return _format(pd, diffs, verdict)
    finally:
        cur.close(); conn.close()


def _format(pd, diffs, verdict):
    lines = [
        "# 🔬 PEER AUTOPSY\n",
        f"**YOUR ITEM:** `{pd['my_name'][:60]}`",
        f"_{pd['my_favs']}♥ · {pd['my_age']}d · {pd['my_velocity']}/day_\n",
        "## 🏆 NEAREST WINNERS",
    ]
    for i, p in enumerate(pd["peers"], 1):
        lines.append(
            f"**#{i} `{p['name'][:55]}`**\n"
            f"   {p['favs']:,}♥ · {p['velocity']}/day · "
            f"{p['word_count']}w"
            + (" · parens" if p["has_parens"] else "")
            + (" · emoji" if p["has_emoji"] else "")
        )

    lines.append("\n## ✅ WINNERS' PATTERN")
    lines.append(f"• Avg title length: **{diffs['avg_words']} words** "
                 f"(you: {diffs['my_word_count']})")
    lines.append(f"• Avg velocity: **{diffs['avg_velocity']}/day** "
                 f"(you: {pd['my_velocity']}/day — {diffs['ratio']:.0%} of peer)")
    lines.append(f"• No parens: **{diffs['peers_no_parens']}**")
    lines.append(f"• No emoji: **{diffs['peers_no_emoji']}**")
    if diffs["top_lead_words"]:
        lines.append(f"• Lead words: `{'`, `'.join(diffs['top_lead_words'])}`")

    lines.append("\n## ❌ YOUR DIFFS")
    any_diff = False
    if diffs["my_has_parens"]:
        lines.append("• **Has parens** — search ignores them")
        any_diff = True
    if diffs["my_has_emoji"]:
        lines.append("• **Has emoji** — dilutes token weight")
        any_diff = True
    if diffs["my_word_count"] > diffs["avg_words"]:
        lines.append(f"• **Too long** — {diffs['my_word_count']}w vs "
                     f"{diffs['avg_words']}w avg")
        any_diff = True
    if diffs["missing_keywords"]:
        lines.append(f"• **Missing keywords:** "
                     f"`{'`, `'.join(diffs['missing_keywords'][:5])}`")
        any_diff = True
    if not any_diff:
        lines.append("• No structural diffs — failure is niche/timing")

    lines.append(f"\n## 🎯 DECISION\n{verdict}")
    return ["\n".join(lines)]
