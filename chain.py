"""
chain.py — full pipeline. Brainstorm depth + FINAL action + statistical scoring.

Runs:
  1. Intent extraction
  2. Niche pre-check (deduped, family-fixed)
  3. Market scan
  4. Winner analysis
  5. Algo context
  6. Keyword intelligence
  7. Niche velocity / trajectory / concentration
  8. Description mining
  9. Big AI strategy prompt
  10. Focused title pass
  11. Smart pipeline
  12. Statistical title scoring
  13. Description + tags merge (AI body + tag_generator)
  14. FINAL block
"""
import re
import json
import asyncio
from bot_core import get_db
from convergence_engine import ASSET_TO_FAMILY, FAMILIES


_FAMILY_MAP = {
    "headwear": "hair", "hat": "hair", "hats": "hair", "cap": "hair",
    "crown": "hair", "beanie": "hair", "beret": "hair", "hair": "hair",
    "face": "face", "neck": "neck", "shoulder": "shoulder",
    "front": "front", "back": "back", "waist": "waist",
    "shirt": "tops", "pants": "tops", "jacket": "back",
    "shoes": "other", "classic": "classic",
    "emote": "emotes", "dance": "emotes", "emotes": "emotes",
    "gear": "gear", "bundle": "bundle",
}

_HAT_WORDS = ("beanie", "hat", "cap", "beret", "crown", "bonnet",
              "visor", "snapback", "bucket hat", "fedora", "bowler")


def _map_family(label):
    if not label:
        return "hair"
    l = str(label).lower().strip()
    if l in FAMILIES:
        return l
    return _FAMILY_MAP.get(l, "hair")


def _detect_type_override(concept):
    if not concept:
        return None
    c = concept.lower()
    if any(w in c for w in _HAT_WORDS):
        return "hat"
    return None


def run_chain(concept, family=None, parent_id=None):
    from gemini_brain import (
        extract_keywords, all_terms, synthesize_hybrid, _generate
    )
    from intel_common import classify_keyword
    from commands_ai import _build_allow_list
    from category_configs import get_category_config

    # ── Parent context ──
    parent_context = ""
    parent_name = None
    if parent_id:
        try:
            conn = get_db(); cur = conn.cursor()
            try:
                cur.execute("""
                    select name, description, favorite_count, price,
                           asset_type_id from items where id = %s
                """, (parent_id,))
                row = cur.fetchone()
                if row:
                    parent_name = row[0]
                    parent_context = (
                        f"\n=== PARENT ITEM (this is a VARIANT) ===\n"
                        f"Parent name: {row[0]}\n"
                        f"Parent favs: {row[2]:,} · price R${row[3]}\n"
                        f"Parent description: {(row[1] or '')[:200]}\n"
                        f"\nRULES FOR VARIANT:\n"
                        f"- KEEP core keywords from parent name\n"
                        f"- Add ONE new theme word (color/vibe/effect)\n"
                        f"- Don't drop words that made the parent a winner\n"
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

    raw_family = family or intent.get("item_type", "unknown")
    if family and family in FAMILIES:
        family = family
    else:
        family = _map_family(raw_family)

    intent["item_type"] = family
    item_type = family
    terms = all_terms(intent)

    type_override = _detect_type_override(concept)
    if parent_name and not type_override:
        type_override = _detect_type_override(parent_name)

    # ── Stage 2: Niche pre-check ──
    niche_data = []
    try:
        conn = get_db(); cur = conn.cursor()
        try:
            seen = set()
            for t in terms:
                t_clean = str(t).strip().lower().split()[0] if str(t).strip() else ""
                if len(t_clean) < 3 or t_clean in seen:
                    continue
                seen.add(t_clean)
                kw = classify_keyword(cur, t_clean, family)
                if kw:
                    niche_data.append(kw)
                if len(niche_data) >= 6:
                    break
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

    # ── Stage 4: Winner analysis ──
    winner_data = {}
    try:
        from winner_analysis import analyze_winners
        def _run_winner():
            c = get_db(); cu = c.cursor()
            try:
                return analyze_winners(cu, terms, top_n=40)
            finally:
                cu.close(); c.close()
        winner_data = _run_winner()
    except Exception as e:
        print(f"[chain] winner analysis failed: {e}", flush=True)

    # ── Stage 5: Algo context ──
    algo_ctx = ""
    try:
        from algo_brain import build_algo_context
        algo_ctx = build_algo_context(intent)
    except Exception as e:
        print(f"[chain] algo context failed: {e}", flush=True)

    # ── Stage 6: Keyword intelligence ──
    keyword_intel = None
    try:
        from gemini_brain import classify_keyword_intelligence
        comp_data = []
        for t in terms[:6]:
            t_clean = str(t).strip()
            if len(t_clean) < 3:
                continue
            c2 = get_db(); cu2 = c2.cursor()
            try:
                cu2.execute("""
                    SELECT COUNT(*),
                           COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP
                                    (ORDER BY favorite_count), 0)
                    FROM items
                    WHERE LOWER(name) LIKE %s AND favorite_count > 5
                """, (f"%{t_clean}%",))
                r = cu2.fetchone()
            finally:
                cu2.close(); c2.close()
            if r:
                comp_data.append({
                    "keyword": t_clean,
                    "comp": int(r[0] or 0),
                    "median_favs": int(r[1] or 0),
                    "median_price": 0,
                })
        if comp_data:
            keyword_intel = classify_keyword_intelligence(
                comp_data[0]["keyword"], comp_data, family
            )
    except Exception as e:
        print(f"[chain] keyword intelligence failed: {e}", flush=True)

    # ── Stage 7: Niche velocity ──
    niche_intel = None
    try:
        from market_velocity import build_niche_intel
        seed_keywords = []
        for t in terms:
            tc = str(t).strip().lower()
            if len(tc) >= 3 and tc not in seed_keywords:
                seed_keywords.append(tc)
            if len(seed_keywords) >= 4:
                break
        if seed_keywords:
            cat_ids = None
            try:
                cat_ids = get_category_config(family).get("asset_type_ids") or None
            except Exception:
                cat_ids = None

            def _run_niche():
                c = get_db(); cu = c.cursor()
                try:
                    return build_niche_intel(cu, seed_keywords, asset_ids=cat_ids)
                finally:
                    cu.close(); c.close()

            niche_intel = _run_niche()
    except Exception as e:
        print(f"[chain] niche intel failed: {e}", flush=True)

    # ── Stage 8: Description mining ──
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

    # ── Best niche keyword ──
    best_niche_kw = None
    best_niche_bucket = None
    best_obj = None
    if niche_data:
        best_obj = min(niche_data, key=lambda x: (
            1 if x["bucket"] == "GOLD" else
            2 if x["bucket"] == "OPPORTUNITY" else
            3 if x["bucket"] == "VIRGIN" else
            4 if x["bucket"] == "NEUTRAL" else 5
        ))
        best_niche_kw = best_obj["keyword"]
        best_niche_bucket = best_obj["bucket"]

    # ── Stage 9: Big strategy prompt ──
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
            None, intent.get("specific_moves", []),
            winner_data, algo_ctx, keyword_intel, niche_intel,
        ) or {}
    except Exception as e:
        print(f"[chain] synth failed: {e}", flush=True)

    # ── Stage 10: Focused title pass ──
    try:
        cfg = get_category_config(family)
        if type_override == "hat":
            type_words = "hat, beanie, cap, beret, crown, visor"
        else:
            type_words = ", ".join(cfg.get("type_words", [])[:6]) or "hat, beanie"

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
                f"At least 4 of 10 titles MUST contain `{best_niche_kw}` "
                f"as the FIRST or SECOND token.\n"
            )

        parent_rule = ""
        if parent_name:
            parent_rule = (
                f"\n=== VARIANT RULE ===\n"
                f"Variant of `{parent_name}`. Keep core keywords.\n"
            )

        focused_prompt = f"""You are the #1 Roblox UGC naming strategist.
Generate EXACTLY 10 titles for a Roblox {family} item.

CONCEPT: {concept}

REAL COMPETITORS (study, do NOT copy):
{top_comp_lines}

TYPE WORDS (every title ends with one): {type_words}

STRUCTURES:
{archetypes}

ALLOW-LIST:
{', '.join(allow_list[:80])}
{keyword_rule}{parent_rule}
RULES:
1. Every title = 3-5 tokens
2. Every title ends with a type word
3. Every title is UNIQUE
4. No generic fluff unless in allow-list
5. Titles read as real product names

OUTPUT — ONLY JSON:
{{
  "titles_safe": ["...", "...", "..."],
  "titles_differentiated": ["...", "...", "..."],
  "titles_longtail": ["...", "..."],
  "titles_viral": ["...", "..."]
}}
"""
        focused_raw = _generate(focused_prompt, json_mode=True,
                                temperature=0.85, max_tokens=1500)
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
    except Exception as e:
        print(f"[chain] focused title pass failed: {e}", flush=True)

    # ── Stage 10b: Staged verification ──
    verification_audit = None
    try:
        from verification import verify_synth, facts_from_stats
        niche_extra = {}
        if best_obj:
            niche_extra = {
                "supply": best_obj.get("supply", 0),
                "demand": best_obj.get("demand", 0),
                "median_favs": best_obj.get("median_favs", 0),
            }

        def _verify():
            conn_v = get_db(); cur_v = conn_v.cursor()
            try:
                facts = facts_from_stats(stats, niche_extra)
                return verify_synth(cur_v, synth, allow_list, family, facts,
                             actual_bucket=best_niche_bucket,
                             item_name=concept)
            finally:
                cur_v.close(); conn_v.close()

        synth, verification_audit = _verify()
    except Exception as e:
        print(f"[chain] verification failed: {e}", flush=True)
        if not isinstance(synth, dict):
            synth = {}
        for key in ("titles_safe", "titles_differentiated",
                    "titles_longtail", "titles_viral"):
            synth[key] = []
        verification_audit = {
            "error": type(e).__name__,
            "verified": 0,
            "rejected": [],
            "metrics": {},
            "claims": [],
            "pivots": [],
        }

    # ── Stage 11: Smart pipeline ──
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
                description=concept, intent=intent, item_type=family,
                category_asset_ids=cat_ids, ai_titles=ai_titles,
                live_enrich=True, db_factory=get_db,
            )

        pr = _pipeline()
        if pr and pr.get("report"):
            pipeline_report = pr["report"]
    except Exception as e:
        print(f"[chain] smart pipeline failed: {e}", flush=True)

    # ── Stage 12: Statistical title scoring ──
    scored_titles = []
    try:
        from title_scorer import score_titles_batch, pick_champion
        all_titles = []
        for k in ("titles_safe", "titles_differentiated",
                  "titles_longtail", "titles_viral"):
            all_titles.extend(synth.get(k) or [])
        if all_titles:
            scored_titles = score_titles_batch(all_titles, family=family)
    except Exception as e:
        print(f"[chain] title scoring failed: {e}", flush=True)

    try:
        verified_metrics = (verification_audit or {}).get("metrics") or {}
        for sc in scored_titles:
            opp = (verified_metrics.get(sc["title"]) or {}).get("opportunity") or {}
            sc["opportunity"] = opp
            sc["final_score"] = sc["score"]
        scored_titles.sort(key=lambda x: x["final_score"], reverse=True)
    except Exception as e:
        print(f"[chain] opportunity rerank failed: {e}", flush=True)

    # ── Stage 12b: 80% confidence intervals ──
    confidence_data = None
    try:
        from confidence import build_confidence
        conf_phrase = (scored_titles[0]["title"] if scored_titles
                       else (best_niche_kw or concept))
        conf_price = (stats.get("price_avg") or 0)

        def _confidence():
            conn_c = get_db(); cur_c = conn_c.cursor()
            try:
                return build_confidence(
                    cur_c, family=family, phrase=conf_phrase, price=conf_price
                )
            finally:
                cur_c.close(); conn_c.close()

        confidence_data = _confidence()
    except Exception as e:
        print(f"[chain] confidence failed: {e}", flush=True)

    # ── Stage 13: Description + tags merge ──
    # Uses tag_generator (description_engine was removed).
    # Builds: AI body (seo_description) + 45 mined tags + audit.
    merged_description = None
    description_audit = None
    try:
        from tag_generator import generate_tags

        # Pick the champion title as the tag seed
        tag_seed = None
        if scored_titles:
            tag_seed = scored_titles[0]["title"]
        if not tag_seed:
            tag_seed = concept

        # Generate 45 sales-weighted tags
        tag_result = generate_tags(tag_seed, family=family, max_tags=45)
        tags = (tag_result or {}).get("tags") or []

        # AI body — strip any stray tags the AI added
        ai_body = (synth.get("seo_description") or "").strip()
        ai_body_lines = [
            ln for ln in ai_body.split("\n")
            if not ln.strip().lower().startswith("tags:")
        ]
        ai_body = "\n".join(ai_body_lines).strip()

        # Merge: AI body + tag block
        if ai_body and tags:
            tag_line = ", ".join(tags)
            merged_description = f"{ai_body}\n\ntags: {tag_line}"
        elif ai_body:
            merged_description = ai_body
        elif tags:
            merged_description = f"tags: {', '.join(tags)}"

        # Build audit from tag_generator result
        description_audit = {
            "primary_keyword": (
                scored_titles[0]["breakdown"][0]["word"]
                if scored_titles and scored_titles[0].get("breakdown")
                else None
            ),
            "primary_demand": (
                scored_titles[0]["breakdown"][0]["demand"]
                if scored_titles and scored_titles[0].get("breakdown")
                else 0
            ),
            "mined_tag_count": len(tags),
            "top_10_tags": tags[:10],
            "family": family,
        }
    except Exception as e:
        print(f"[chain] description merge failed: {e}", flush=True)

    return {
        "concept": concept,
        "parent_name": parent_name,
        "is_variant": bool(parent_id),
        "family": family,
        "item_type": item_type,
        "type_override": type_override,
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
        "niche_intel": niche_intel,
        "scored_titles": scored_titles,
        "merged_description": merged_description,
        "description_audit": description_audit,
        "verification": verification_audit,
        "confidence": confidence_data,
    }


def format_chain(result):
    if result.get("error"):
        return [f"❌ {result['error']}"]

    chunks = []
    synth = result.get("synth") or {}
    s = result["stats"]

    # ── HEADER ──
    type_label = result.get("type_override") or result['item_type']
    if result.get("is_variant") and result.get("parent_name"):
        chunks.append(
            f"# 🔗 CHAIN — VARIANT\n"
            f"_Parent: `{result['parent_name'][:60]}`_\n"
            f"_Family: `{result['family']}` · Type: `{type_label}`_"
        )
    else:
        chunks.append(
            f"# 🔗 CHAIN — `{result['concept'][:60]}`\n"
            f"_Family: `{result['family']}` · Type: `{type_label}`_"
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
                f"demand {k.get('demand_live', k['demand'])} "
                f"({k.get('demand_volume', 0):,} vol)"
                + ("" if k.get("demand_reliable", True)
                   else " · low-confidence")
            )
        chunks.append("\n".join(lines))

    # ── MARKET ──
    chunks.append(
        f"## 📊 Market\n"
        f"• Items matched: **{s.get('count', 0):,}**\n"
        f"• Avg favs: **{s.get('avg_favs', 0):,}** · "
        f"median **{s.get('median_favs', 0):,}**\n"
        f"• Winner bar (top 10%): **{s.get('winner_favs', 0):,}** favs\n"
        f"• Avg price: **R${s.get('price_avg', 0)}**"
    )

    # ── OPPORTUNITY ──
    if s.get("opportunity_keywords"):
        lines = ["## 🕳️ Top opportunity keywords"]
        for kw in s["opportunity_keywords"][:8]:
            lines.append(
                f"• `{kw['word']}` — {kw['count']} items, avg {kw['avg_favs']:,}♥"
            )
        chunks.append("\n".join(lines))

    # ── NICHE INTEL ──
    niche_intel = result.get("niche_intel")
    if niche_intel:
        try:
            from market_velocity import format_niche_intel_for_prompt
            body = format_niche_intel_for_prompt(niche_intel)
            for i in range(0, len(body), 1900):
                chunks.append(body[i:i+1900])
        except Exception:
            pass

    # ── COMPETITORS ──
    if result["top_items"]:
        lines = ["## 🥊 Top competitors"]
        for it in result["top_items"]:
            name = (it.get("name") or "")[:60]
            favs = it.get("favourite_count") or 0
            price = it.get("price") or 0
            lines.append(f"• `{name}` — {favs:,}♥ · R${price}")
        chunks.append("\n".join(lines))

    # ── REAL DESCRIPTIONS ──
    if result["desc_examples"]:
        lines = ["## 📝 Real descriptions from winners"]
        for name, desc, favs, price in result["desc_examples"]:
            d = (desc or "").strip().replace("\n", " ")[:150]
            lines.append(f"**{name[:50]}** — {favs:,}♥\n_{d}_")
        chunks.append("\n".join(lines))

    # ── AI STRATEGY ──
    if synth:
        for key, header in [
            ("search_diagnosis",  "## 🔍 Search Diagnosis"),
            ("positioning",       "## 🎯 Positioning"),
            ("market_diagnosis",  "## 📊 Market Diagnosis"),
            ("winner_blueprint",  "## 🏆 Winner Blueprint"),
            ("saturation_verdict","## ⚠️ Saturation Summary"),
        ]:
            v = synth.get(key)
            if v:
                chunks.append(f"{header}\n{v}")

        if synth.get("killer_keywords"):
            kw = ", ".join(f"`{k}`" for k in synth["killer_keywords"][:15])
            chunks.append(f"## 🎯 Killer keywords\n{kw}")
        if synth.get("cross_promotion_play"):
            chunks.append(f"## 🔗 Cross-Promotion\n{synth['cross_promotion_play']}")
        if synth.get("social_playbook"):
            chunks.append(f"## 📱 Social Playbook\n{synth['social_playbook']}")
        if synth.get("cultural_ammo"):
            chunks.append(f"## 🎭 Cultural Context\n{synth['cultural_ammo']}")
        if synth.get("bonus_plays"):
            lines = ["## 💎 Bonus Plays"]
            for b in synth["bonus_plays"][:5]:
                lines.append(f"• {b}")
            chunks.append("\n".join(lines))

    # ── MERGED DESCRIPTION (AI body + engine tags) ──
    merged = result.get("merged_description")
    audit = result.get("description_audit") or {}
    if merged:
        chunks.append(
            f"## ✨ Suggested description (copy-paste)\n```\n"
            f"{merged[:1500]}\n```"
        )
        if audit:
            audit_lines = [
                "**🔍 Description audit — every word traceable:**",
                f"• Primary keyword: `{audit.get('primary_keyword', '?')}` "
                f"({audit.get('primary_demand', 0)} searches)",
                f"• Tags mined: **{audit.get('mined_tag_count', 0)}**",
            ]
            top10 = audit.get("top_10_tags", [])
            if top10:
                audit_lines.append(f"• Top 10 tags: `{', '.join(top10)}`")
            chunks.append("\n".join(audit_lines))

    # ── 10 TITLES ──
    if synth:
        title_groups = [
            ("🟢 SAFE (mirror winners)",         synth.get("titles_safe") or []),
            ("🎯 DIFFERENTIATED (unique angle)", synth.get("titles_differentiated") or []),
            ("🔎 LONG-TAIL SEO (4+ keywords)",   synth.get("titles_longtail") or []),
            ("🔥 VIRAL (meme/TikTok hook)",      synth.get("titles_viral") or []),
        ]
        if any(g for _, g in title_groups):
            lines = ["# 📝 10 TITLES\n"]
            for gname, group_titles in title_groups:
                if not group_titles:
                    continue
                lines.append(f"**{gname}**")
                for t in group_titles:
                    lines.append(f"• `{t}`")
                lines.append("")
            chunks.append("\n".join(lines))

    # ── SMART PIPELINE ──
    if result.get("pipeline_report"):
        rep = result["pipeline_report"]
        for i in range(0, len(rep), 1900):
            chunks.append(rep[i:i+1900])

    # ── STATISTICAL TITLE RANKING ──
    scored = result.get("scored_titles") or []
    if scored:
        lines = ["# 📊 STATISTICAL TITLE RANKING\n",
                 "_Real word-lift × search-demand × freshness from DB._\n"]
        for i, sc in enumerate(scored[:5], 1):
            gap_part = f" · gap {sc.get('visibility_gap', 0):.0f}" \
                       if sc.get("visibility_gap", 0) >= 5 else ""
            opp = sc.get("opportunity") or {}
            opp_part = (
                f" · {opp.get('verdict')} · visibility proxy (unvalidated) {opp.get('ctr_proxy')}/100"
                if opp else ""
            )
            lines.append(
                f"**#{i} `{sc['title']}`** — score **{sc.get('final_score', sc['score'])}**"
                + (f" (raw {sc['score']})" if sc.get('final_score') is not None
                   and sc.get('final_score') != sc['score'] else "")
                + gap_part + opp_part
                + (f" · unique" if sc['exact_matches'] == 0
                   else f" · {sc['exact_matches']} matches")
            )
            for b in sorted(sc["breakdown"],
                            key=lambda x: x["contribution"],
                            reverse=True)[:4]:
                if b.get("no_data"):
                    vol = b.get("demand_volume", 0)
                    vol_str = f" · {vol:,} volume" if vol else ""
                    lines.append(f"   ⚫ `{b['word']}` — no niche data "
                                 f"({b['demand']} live{vol_str}) → +0.0")
                    continue
                lift = b["lift"]
                if lift >= 2.5: emoji = "🟢"
                elif lift >= 1.5: emoji = "🔵"
                elif lift >= 1.0: emoji = "⚪"
                elif lift >= 0.5: emoji = "🟠"
                else: emoji = "🔴"
                gap = b.get("visibility_gap", 0)
                gap_str = f" · gap {gap:.0f}" if gap >= 5 else ""
                vol = b.get("demand_volume", 0)
                vol_str = f" · {vol:,} volume" if vol else ""
                lines.append(
                    f"   {emoji} `{b['word']}` lift {lift}× "
                    f"({b['sample']} items · {b['demand']} live{vol_str}"
                    f"{gap_str}) → +{b['contribution']}"
                )
            if sc.get("bigram"):
                lines.append(f"   🎯 bigram `{sc['bigram']}` → +{sc['bigram_bonus']}")
            lines.append("")
        body = "\n".join(lines)
        for i in range(0, len(body), 1900):
            chunks.append(body[i:i+1900])

    # ── VERIFICATION + CONFIDENCE ──
    try:
        from verification import format_audit
        body = format_audit(result.get("verification"))
        if body:
            chunks.append(body)
    except Exception:
        pass
    try:
        from confidence import format_confidence
        body = format_confidence(result.get("confidence"))
        if body:
            chunks.append(body)
    except Exception:
        pass

    # ── FINAL BLOCK ──
    final_lines = ["# ✅ FINAL — DO THIS"]

    if scored:
        champion = scored[0]["title"]
        backup = scored[1]["title"] if len(scored) > 1 else None
        final_lines.append(f"**1. Name:** `{champion}`  ← top-ranked verified name")
        if backup:
            final_lines.append(f"**2. Backup name:** `{backup}`")
    else:
        titles = []
        for key in ("titles_differentiated", "titles_safe", "titles_viral"):
            titles.extend(synth.get(key) or [])
        if titles:
            final_lines.append(f"**1. Name:** `{titles[0]}`")
            if len(titles) > 1:
                final_lines.append(f"**2. Backup name:** `{titles[1]}`")
        else:
            final_lines.append("**1. Name:** (no titles generated)")

    if merged:
        final_lines.append("**3. Paste description** (from above block)")

    if result.get("best_niche_kw"):
        final_lines.append(
            f"**4. Niche:** `{result['best_niche_kw']}` = "
            f"{result['best_niche_bucket']}"
        )
    if scored:
        champ_opp = scored[0].get("opportunity") or {}
        if champ_opp:
            final_lines.append(
                f"**Verified title lane:** {champ_opp.get('verdict')} · "
                f"demand {champ_opp.get('demand_volume', 0):,} · "
                f"supply {champ_opp.get('supply', 0)} · "
                f"exact {champ_opp.get('exact', 0)}"
            )

    if s.get("price_avg"):
        final_lines.append(f"**5. Price:** R${s.get('price_avg', 0)}")

    # Apply the encoded UGC playbook to the chosen title/price.
    try:
        from ugc_playbook import audit_title, audit_price
        if scored:
            issues = audit_title(scored[0]["title"])
            if issues:
                final_lines.append(
                    "**Playbook check:** " + "; ".join(issues[:3])
                )
        if s.get("price_avg"):
            note = audit_price(s.get("price_avg"))
            if note:
                final_lines.append(f"**Pricing note:** {note}")
    except Exception:
        pass

    final_lines.append("**6. Post 1 TikTok today** with the name as overlay")
    final_lines.append("**7. In 14 days:** run `!verdict <new_item_id>`")

    chunks.append("\n".join(final_lines))

    return chunks
