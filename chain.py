"""
chain.py — full pipeline in one command.
Runs: intent → niche → market → descriptions → focused title pass →
      smart pipeline (brainstorm depth) → FINAL.

Uses at most 2-3 Gemini calls:
  1. Big synthesize_hybrid prompt (market analysis + description)
  2. Focused title pass (brainstorm-quality titles)
  3. Smart pipeline (parallel live enrichment + ranked titles)

The focused pass OVERWRITES the titles from the big prompt because small
models dilute titles when asked to do 15 things at once.

Variant mode: pass parent_id to keep winner keywords + add ONE theme word.
"""
import re
import json
import asyncio
from bot_core import get_db
from convergence_engine import ASSET_TO_FAMILY


def run_chain(concept, family=None, parent_id=None):
    from gemini_brain import (
        extract_keywords, all_terms, synthesize_hybrid, _generate
    )
    from intel_common import classify_keyword
    from convergence_engine import FAMILIES
    from commands_ai import _build_allow_list
    from category_configs import get_category_config

    # ── Parent context for variant mode ──
    parent_context = ""
    parent_name = None
    if parent_id:
        try:
            conn = get_db(); cur = conn.cursor()
            try:
                cur.execute("""
                    select name, description, favorite_count, price,
                           asset_type_id
                    from items where id = %s
                """, (parent_id,))
                row = cur.fetchone()
                if row:
                    parent_name = row[0]
                    parent_context = (
                        f"\n=== PARENT ITEM (this is a VARIANT of this) ===\n"
                        f"Parent name: {row[0]}\n"
                        f"Parent favs: {row[2]:,} · price R${row[3]}\n"
                        f"Parent description: {(row[1] or '')[:200]}\n"
                        f"\nRULES FOR VARIANT:\n"
                        f"- KEEP the core keywords from the parent name\n"
                        f"- Add ONE new theme word (color, vibe, effect)\n"
                        f"- Don't drop the words that made the parent a winner\n"
                        f"- Don't use generic words like 'cute' or 'kawaii' "
                        f"unless the parent already used them\n"
                    )
                    if not concept or concept.lower() in ("variant", "remix"):
                        concept = row[0]
            finally:
                cur.close(); conn.close()
        except Exception as e:
            print(f"[chain] parent load failed: {e}", flush=True)

    # ── Stage 1: Intent ──
    intent = extract_keywords(concept)
    if not intent:
        return {"error": "Intent extraction failed. Try a clearer description."}

    if family and family in FAMILIES:
        intent["item_type"] = family

    item_type = intent.get("item_type", "unknown")
    family = family or _intent_to_family(intent)
    terms = all_terms(intent)

    # ── Stage 2: Niche pre-check ──
    niche_data = []
    try:
        conn = get_db(); cur = conn.cursor()
        try:
            for t in terms[:5]:
                t_clean = str(t).strip().lower().split()[0] if str(t).strip() else ""
                if len(t_clean) < 3:
                    continue
                kw = classify_keyword(cur, t_clean, family)
                if kw:
                    niche_data.append(kw)
        finally:
            cur.close(); conn.close()
    except Exception as e:
        print(f"[chain] niche pre-check failed: {e}", flush=True)

    # ── Stage 3: Market ──
    try:
        allow_list, top_items, stats = _build_allow_list(intent, 60, None, family)
    except Exception as e:
        return {"error": f"DB search failed: {e}"}

    if not allow_list:
        return {"error": "No DB matches. Try different keywords."}

    # ── Stage 4: Description examples ──
    desc_examples = []
    try:
        from desc_forge import _fetch_top_descriptions
        seed_kw = None
        if concept:
            parts = str(concept).strip().split()
            if parts:
                first = parts[0]
                if ":" in first:
                    first = first.split(":", 1)[1]
                seed_kw = first
        if not seed_kw and intent.get("specific_moves"):
            seed_kw = intent["specific_moves"][0]
        if not seed_kw and allow_list:
            seed_kw = allow_list[0]
        if seed_kw:
            seed_kw = str(seed_kw).strip().split()[0]
            if len(seed_kw) >= 3:
                rows = _fetch_top_descriptions(seed_kw, family=family, limit=10)
                if rows:
                    desc_examples = rows[:3]
    except Exception as e:
        print(f"[chain] desc mining failed: {e}", flush=True)

    # ── Best niche keyword for title pass ──
    best_niche_kw = None
    best_niche_bucket = None
    if niche_data:
        best_obj = min(niche_data, key=lambda x: (
            1 if x["bucket"] == "GOLD" else
            2 if x["bucket"] == "OPPORTUNITY" else
            3 if x["bucket"] == "VIRGIN" else
            4 if x["bucket"] == "NEUTRAL" else 5
        ))
        best_niche_kw = best_obj["keyword"]
        best_niche_bucket = best_obj["bucket"]

    # ── Stage 5a: Big strategy prompt ──
    synth = {}
    try:
        concept_for_ai = concept
        if parent_context:
            concept_for_ai = f"{concept}\n{parent_context}"

        synth = synthesize_hybrid(
            concept_for_ai, allow_list, top_items, stats,
            item_type, intent.get("trend_source", "none"),
            {"direct_matches": stats.get("direct_matches", 0),
             "expansion_used": stats.get("expansion_used", False),
             "expanded_terms": stats.get("expanded_terms", []),
             "failed_terms": stats.get("failed_terms", []),
             "reasoning": stats.get("reasoning", "")},
            None, intent.get("specific_moves", []), None, None, None, None,
        ) or {}
    except Exception as e:
        print(f"[chain] synth failed: {e}", flush=True)

    # ── Stage 5b: FOCUSED TITLE PASS — brainstorm-quality ──
    try:
        cfg = get_category_config(family)
        type_words = ", ".join(cfg.get("type_words", [])[:6]) or "emote, dance"
        archetypes = "\n".join(
            f"- {a}" for a in cfg.get("title_archetypes", [])[:5]
        )

        top_comp_lines = "\n".join(
            f"- {it.get('name', '')[:60]} ({it.get('favourite_count', 0):,}♥)"
            for it in top_items[:8]
        ) or "(none)"

        keyword_rule = ""
        if best_niche_kw and best_niche_bucket in ("GOLD", "OPPORTUNITY", "VIRGIN"):
            keyword_rule = (
                f"\n=== MANDATORY KEYWORD ===\n"
                f"At least 4 of the 10 titles MUST contain the word "
                f"`{best_niche_kw}` as the FIRST or SECOND token.\n"
            )

        parent_rule = ""
        if parent_name:
            parent_rule = (
                f"\n=== VARIANT RULE ===\n"
                f"This is a variant of: `{parent_name}`\n"
                f"KEEP the core keywords from that name. Add ONE new "
                f"theme word (color/vibe/effect). At least 3 titles must "
                f"share 2+ words with the parent name.\n"
            )

        focused_prompt = f"""You are the #1 Roblox UGC naming strategist.

Generate EXACTLY 10 titles for a Roblox {family} item.

=== CONCEPT ===
{concept}

=== REAL COMPETITORS (study their naming, do NOT copy) ===
{top_comp_lines}

=== CATEGORY TYPE WORDS (every title must end with one of these) ===
{type_words}

=== EXAMPLE STRUCTURES ===
{archetypes}

=== ALLOW-LIST (only use words from this + type words + glue) ===
{', '.join(allow_list[:80])}
{keyword_rule}{parent_rule}
=== RULES (NON-NEGOTIABLE) ===
1. Every title = 3 to 5 tokens
2. Every title ends with a type word above
3. Every title is UNIQUE
4. NO generic fluff unless it's in the allow-list: cute, kawaii, aesthetic, adorable
5. NO stopword padding
6. Titles must READ as real product names, not keyword dumps
7. Follow MANDATORY KEYWORD rule if given (do NOT ignore it)

=== OUTPUT — ONLY JSON ===
{{
  "titles_safe": ["...", "...", "..."],
  "titles_differentiated": ["...", "...", "..."],
  "titles_longtail": ["...", "..."],
  "titles_viral": ["...", "..."]
}}
"""

        focused_raw = _generate(
            focused_prompt, json_mode=True,
            temperature=0.85, max_tokens=1500
        )
        if focused_raw:
            try:
                focused_data = json.loads(focused_raw)
            except Exception:
                m = re.search(r"\{.*\}", focused_raw, re.DOTALL)
                focused_data = json.loads(m.group(0)) if m else {}

            if focused_data:
                for key in ("titles_safe", "titles_differentiated",
                            "titles_longtail", "titles_viral"):
                    if focused_data.get(key):
                        synth[key] = focused_data[key]
                synth["_focused_title_pass"] = True
    except Exception as e:
        print(f"[chain] focused title pass failed: {e}", flush=True)

    # ── Stage 6: SMART PIPELINE — brainstorm depth ──
    pipeline_report = None
    try:
        from smart_pipeline import run_full_pipeline
        from rising_gaps import CATEGORY_MAP

        cfg = get_category_config(family)

        ai_titles = []
        for k in ("titles_safe", "titles_differentiated",
                  "titles_longtail", "titles_viral"):
            ai_titles.extend(synth.get(k) or [])

        cat_ids = None
        try:
            if family in CATEGORY_MAP:
                cat_ids = CATEGORY_MAP[family]
            else:
                cat_ids = cfg.get("asset_type_ids") or None
        except Exception:
            cat_ids = None

        def _pipeline():
            return run_full_pipeline(
                description=concept,
                intent=intent,
                item_type=family,
                category_asset_ids=cat_ids,
                ai_titles=ai_titles,
                live_enrich=True,
                db_factory=get_db,
            )

        pr = _pipeline()
        if pr and pr.get("report"):
            pipeline_report = pr["report"]
    except Exception as e:
        print(f"[chain] smart pipeline failed: {e}", flush=True)

    return {
        "concept": concept,
        "parent_name": parent_name,
        "is_variant": bool(parent_id),
        "family": family,
        "item_type": item_type,
        "terms": terms,
        "niche": niche_data,
        "best_niche_kw": best_niche_kw,
        "best_niche_bucket": best_niche_bucket,
        "stats": stats,
        "top_items": top_items[:5],
        "allow_list": allow_list[:20],
        "desc_examples": desc_examples,
        "synth": synth,
        "pipeline_report": pipeline_report,
    }


def _intent_to_family(intent):
    try:
        from category_configs import detect_family_from_intent
        return detect_family_from_intent(intent)
    except Exception:
        return "emote"


def format_chain(result):
    if result.get("error"):
        return [f"❌ {result['error']}"]

    chunks = []

    # ── HEADER ──
    if result.get("is_variant") and result.get("parent_name"):
        chunks.append(
            f"# 🔗 CHAIN — VARIANT\n"
            f"_Parent: `{result['parent_name'][:60]}`_\n"
            f"_Family: `{result['family']}` · "
            f"Type: `{result['item_type']}`_"
        )
    else:
        chunks.append(
            f"# 🔗 CHAIN — `{result['concept'][:60]}`\n"
            f"_Family: `{result['family']}` · "
            f"Type: `{result['item_type']}`_"
        )

    # ── NICHE ──
    if result["niche"]:
        emoji_map = {
            "GOLD": "🟢", "OPPORTUNITY": "🔵",
            "NEUTRAL": "⚪", "SATURATED": "🔴",
            "VIRGIN": "💎", "GHOST": "🪦",
        }
        lines = ["## 🎯 Niche check"]
        for k in result["niche"]:
            e = emoji_map.get(k["bucket"], "⚪")
            lines.append(
                f"{e} `{k['keyword']}` — **{k['bucket']}** · "
                f"supply {k['supply']} · median {k['median_favs']}♥ · "
                f"demand {k['demand']}"
            )
        chunks.append("\n".join(lines))

    # ── MARKET ──
    s = result["stats"]
    chunks.append(
        f"## 📊 Market\n"
        f"• Items matched: **{s.get('count', 0):,}**\n"
        f"• Avg favs: **{s.get('avg_favs', 0):,}** · "
        f"median **{s.get('median_favs', 0):,}**\n"
        f"• Winner bar (top 10%): **{s.get('winner_favs', 0):,}** favs\n"
        f"• Avg price: **R${s.get('price_avg', 0)}**"
    )

    # ── COMPETITORS ──
    if result["top_items"]:
        lines = ["## 🥊 Top competitors"]
        for it in result["top_items"]:
            name = (it.get("name") or "")[:60]
            favs = it.get("favourite_count") or 0
            price = it.get("price") or 0
            lines.append(f"• `{name}` — {favs:,}♥ · R${price}")
        chunks.append("\n".join(lines))

    # ── DESCRIPTION EXAMPLES ──
    if result["desc_examples"]:
        lines = ["## 📝 Real descriptions from winners"]
        for name, desc, favs, price in result["desc_examples"]:
            d = (desc or "").strip().replace("\n", " ")[:150]
            lines.append(f"**{name[:50]}** — {favs:,}♥\n_{d}_")
        chunks.append("\n".join(lines))

    # ── AI STRATEGY ──
    synth = result["synth"]
    if synth:
        if synth.get("seo_description"):
            chunks.append(
                f"## ✨ Suggested description (copy-paste)\n```\n"
                f"{synth['seo_description'][:800]}\n```"
            )
        if synth.get("killer_keywords"):
            kw = ", ".join(f"`{k}`" for k in synth["killer_keywords"][:12])
            chunks.append(f"## 🎯 Killer keywords\n{kw}")

    # ── 10 TITLES — grouped like brainstorm ──
    if synth:
        title_groups = [
            ("🟢 SAFE (mirror winners)",         synth.get("titles_safe") or []),
            ("🎯 DIFFERENTIATED (unique angle)", synth.get("titles_differentiated") or []),
            ("🔎 LONG-TAIL SEO (4+ keywords)",   synth.get("titles_longtail") or []),
            ("🔥 VIRAL (meme/TikTok hook)",      synth.get("titles_viral") or []),
        ]
        if any(group_titles for _, group_titles in title_groups):
            lines = ["# 📝 10 TITLES\n"]
            for gname, group_titles in title_groups:
                if not group_titles:
                    continue
                lines.append(f"**{gname}**")
                for t in group_titles:
                    lines.append(f"• `{t}`")
                lines.append("")
            chunks.append("\n".join(lines))

    # ── SMART PIPELINE — brainstorm depth ──
    if result.get("pipeline_report"):
        rep = result["pipeline_report"]
        for i in range(0, len(rep), 1900):
            chunks.append(rep[i:i+1900])

    # ── FINAL BLOCK ──
    final_lines = ["# ✅ FINAL — DO THIS"]

    titles = []
    for key in ("titles_differentiated", "titles_safe", "titles_viral"):
        titles.extend(synth.get(key) or [])

    if titles:
        final_lines.append(f"**1. Name:** `{titles[0]}`")
        if len(titles) > 1:
            final_lines.append(f"**2. Backup name:** `{titles[1]}`")
    else:
        final_lines.append("**1. Name:** (no titles generated — try again)")

    if synth.get("seo_description"):
        final_lines.append("**3. Paste description** (from above block)")

    if result.get("best_niche_kw"):
        final_lines.append(
            f"**4. Niche:** `{result['best_niche_kw']}` = "
            f"{result['best_niche_bucket']}"
        )

    if s.get("price_avg"):
        final_lines.append(f"**5. Price:** R${s.get('price_avg', 0)}")

    final_lines.append("**6. Post 1 TikTok today** with the name as text overlay")
    final_lines.append("**7. In 14 days:** run `!verdict <new_item_id>`")

    chunks.append("\n".join(final_lines))

    return chunks
