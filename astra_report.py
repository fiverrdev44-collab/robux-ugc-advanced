"""astra_report.py — the Analyst Report for !chain (Astra-v3 Phase 2).

Seven sections, Discord-sized chunks, no old metric dumps.
"""
import time


def _chunks(text, size=1900):
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


def build_analyst_report(result, live=None, understanding=None):
    family = result.get("family") or "unknown"
    concept = result.get("concept") or ""
    scored = result.get("scored_titles") or []
    stats = result.get("stats") or {}
    live = live or {}
    understanding = understanding or {}

    color_list = [c.get("value") if isinstance(c, dict) else c
                  for c in (understanding.get("colors") or [])]
    details = [d.get("value") if isinstance(d, dict) else d
               for d in (understanding.get("details") or [])]
    motion = [m.get("value") if isinstance(m, dict) else m
              for m in (understanding.get("motion") or [])]
    unknowns = understanding.get("unknowns") or []
    if family == "emotes":
        motion_line = ("only from creator preview/metadata; a static image is "
                       "not evidence of movement")
    elif motion:
        motion_line = ", ".join(motion)
    else:
        motion_line = "none (static accessory)"
    A = ["## A. PRODUCT UNDERSTANDING",
         f"- **Type:** {family}",
         f"- **Concept:** {concept or 'not provided'}",
         f"- **Colors:** {', '.join(color_list) or 'not stated'}",
         f"- **Visible details:** {', '.join(details) or 'not stated'}",
         f"- **Motion:** {motion_line}",
         f"- **Unknowns:** {', '.join(unknowns) or 'none captured'}"]

    checked = live.get("results")
    pages = live.get("pages")
    exact = live.get("exact")
    live_status = "ok" if live.get("ok") else (
        "unavailable" if live else "not run")
    B = ["## B. MARKET EVIDENCE",
         f"- DB sample: {stats.get('count', 0):,} matches · "
         f"avg favorites {stats.get('avg_favs', 0):,} · "
         f"median {stats.get('median_favs', 0):,}",
         f"- Winner bar (top 10%): {stats.get('winner_favs', 0):,} favorites · "
         f"avg price R${stats.get('price_avg', 0)}",
         f"- Live check: {live_status}"
         + (f" · {checked} results over {pages} page(s) · exact {exact}"
            if live else ""),
         f"- Observed at: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}"]
    if live and not live.get("ok"):
        B.append("- Live search failed; market claims below rely on DB evidence only.")

    C = ["## C. POSITIONING ANGLES"]
    angle_names = ["Safe", "Differentiated", "Long-tail", "Viral", "Backup"]
    for i, sc in enumerate(scored[:5]):
        opp = sc.get("opportunity") or {}
        breakdown = sc.get("breakdown") or []
        why = ", ".join(b.get("word", "") for b in breakdown[:2]) or "n/a"
        uncertainty = (
            f"{sc.get('exact_matches', opp.get('exact', 0))} exact matches"
            if sc.get("exact_matches") is not None else
            f"lane {opp.get('verdict', 'unknown')}")
        C.append(f"- **{sc.get('title')}** — {angle_names[min(i, 4)]} angle\n"
                 f"  Buyer: {family} shoppers using style + feature words.\n"
                 f"  Why it fits: {why}.\n"
                 f"  Uncertainty: {uncertainty}.")
    if not scored:
        C.append("- No verified titles were produced; evidence is insufficient.")

    D = ["## D. RECOMMENDED FIRST TEST"]
    if scored:
        champ = scored[0]
        opp = champ.get("opportunity") or {}
        D.append(f"- **Title:** {champ.get('title')}")
        D.append(f"- **Tradeoff:** lane {opp.get('verdict', 'unknown')} · "
                 f"demand {opp.get('demand_volume', 0):,} · "
                 f"supply {opp.get('supply', 0)} · "
                 f"exact {opp.get('exact', 0)}.")
        D.append("- This is a ranked option, not an instruction; you decide.")
    else:
        D.append("- No recommendation: titles did not pass verification.")

    desc = result.get("merged_description") or "(description unavailable)"
    E = ["## E. DESCRIPTION", desc.strip()]

    if family == "emotes":
        showcase = ("Use the creator's animation preview (not the Roblox thumbnail): "
                    "show the full loop, then a front-facing hook frame. "
                    "Do not infer motion from a static image.")
    else:
        showcase = ("Static accessory: show front, 3/4, and back in neutral light; "
                    "no motion claims. Keep scale true to the avatar.")
    F = ["## F. PREVIEW BRIEF", f"- {showcase}",
         "- One lighting setup, one background; avoid invented effects."]

    G = ["## G. MEASUREMENT PLAN",
         "- Record favorites at D1/D7/D14/D30 and units at D7/D30.",
         "- Use `!launch <item_id>` then `!ledger_sync`; evaluate with "
         "`!experiments`/`!verdict` at 14 and 30 days.",
         "- Compare against the family baseline, not against a single winner."]

    sections = [A, B, C, D, E, F, G]
    text = "\n\n".join("\n".join(s) for s in sections)
    return _chunks(text)
