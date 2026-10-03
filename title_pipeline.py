"""
title_pipeline.py — Full intelligence pipeline.
Runs miner + simulator + predictor in one shot.
"""
import re

from title_miner import mine_keyword_pool, brute_force_combinations
from title_simulator import simulate_title
from title_predictor import predict_title, train_model, _load_weights


def _tokens(text):
    return [t for t in re.findall(r"[a-z]{3,}", (text or "").lower())]


def _extract_seeds(description, intent=None, top_n=4):
    words = _tokens(description)
    if intent:
        priority = (intent.get("specific_moves") or []) + (intent.get("primary") or [])
        for p in priority:
            for t in _tokens(p):
                if t not in words:
                    words.insert(0, t)
    seen = set()
    out = []
    for w in words:
        if len(w) < 4 or w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= top_n:
            break
    return out


def run_full_pipeline(cur, description, intent=None, item_type="emote",
                      category_asset_ids=None, ai_titles=None):
    result = {
        "seeds": [],
        "keyword_pool": [],
        "discovered_titles": [],
        "scored_titles": [],
        "model_status": {},
        "best_title": None,
        "report": "",
    }

    seeds = _extract_seeds(description, intent)
    result["seeds"] = seeds
    if not seeds:
        return result

    try:
        pool = mine_keyword_pool(cur, seeds, category_asset_ids, pool_size=40)
        result["keyword_pool"] = pool
    except Exception as e:
        print(f"[pipeline] mine failed: {e}", flush=True)
        pool = []

    try:
        discovered = brute_force_combinations(
            cur, pool, item_type=item_type,
            max_combos=100, category_asset_ids=category_asset_ids,
        )
        result["discovered_titles"] = discovered
    except Exception as e:
        print(f"[pipeline] brute force failed: {e}", flush=True)
        discovered = []

    loaded = _load_weights(cur)
    if not loaded:
        try:
            trained = train_model(cur)
            if trained:
                loaded = {
                    "weights": trained["weights"],
                    "n_samples": trained["n_samples"],
                    "accuracy": trained["accuracy"],
                }
        except Exception as e:
            print(f"[pipeline] train failed: {e}", flush=True)

    result["model_status"] = {
        "loaded": bool(loaded),
        "samples": loaded["n_samples"] if loaded else 0,
        "accuracy": round(loaded["accuracy"] * 100, 1) if loaded else 0,
    }

    all_titles = set()
    if ai_titles:
        all_titles.update(t for t in ai_titles if t)
    for d in discovered[:50]:
        all_titles.add(d["title"])
    all_titles = list(all_titles)

    scored = []
    for title in all_titles:
        try:
            sim = simulate_title(cur, title, None, category_asset_ids)
            pred = predict_title(cur, title, category_asset_ids, auto_train=False)
            sim_score = sim["front_page_score"] if sim else 0
            pred_score = pred.get("score", 0) if pred else 0
            combined = sim_score * 0.6 + pred_score * 0.4
            scored.append({
                "title": title,
                "combined_score": round(combined, 1),
                "sim_score": round(sim_score, 1),
                "pred_score": round(pred_score, 1),
                "verdict": sim["verdict"] if sim else "?",
                "raw": sim["raw"] if sim else {},
            })
        except Exception as e:
            print(f"[pipeline] score fail '{title}': {e}", flush=True)

    scored.sort(key=lambda x: x["combined_score"], reverse=True)
    result["scored_titles"] = scored
    if scored:
        result["best_title"] = scored[0]

    result["report"] = _format_report(result)
    return result


def _format_report(r):
    lines = ["# 🧬 FULL INTELLIGENCE PIPELINE", ""]
    if r["seeds"]:
        lines.append(f"**Seeds:** `{'`, `'.join(r['seeds'])}`\n")

    ms = r["model_status"]
    if ms.get("loaded"):
        lines.append(f"**ML Model:** trained on **{ms['samples']:,}** items · "
                     f"R²=**{ms['accuracy']}%**\n")

    if r["keyword_pool"]:
        lines.append("## 🎯 MINED KEYWORDS\n")
        for i, p in enumerate(r["keyword_pool"][:8], 1):
            lines.append(
                f"**{i}. `{p['word']}`** — {p['comp']} comp · "
                f"median {p['median_favs']:,} favs · "
                f"score **{p['gap_score']}**"
            )
        lines.append("")

    first_movers = [d for d in r["discovered_titles"] if d["exact_matches"] == 0][:5]
    if first_movers:
        lines.append("## 🏆 FIRST-MOVER TITLES (0 exact matches)\n")
        for i, d in enumerate(first_movers, 1):
            lines.append(f"**{i}. `{d['title']}`** — "
                         f"{d['first_token_comp']} comp · score **{d['final_score']}**")
        lines.append("")

    if r["scored_titles"]:
        lines.append("## 🥇 FINAL RANKED TITLES\n")
        for i, s in enumerate(r["scored_titles"][:10], 1):
            lines.append(f"**{i}. `{s['title']}`** — **{s['combined_score']}/100**")
            lines.append(f"   · Sim: {s['sim_score']} · ML: {s['pred_score']} · {s['verdict']}")
        lines.append("")

    if r["best_title"]:
        b = r["best_title"]
        lines.append("## ✅ TOP RECOMMENDATION\n")
        lines.append(f"### `{b['title']}`")
        lines.append(f"**Score: {b['combined_score']}/100**")
        lines.append(f"- Simulation: **{b['sim_score']}** · ML: **{b['pred_score']}**")
        lines.append(f"- {b['verdict']}")
        if b.get("raw"):
            lines.append(f"- Exact matches in DB: **{b['raw'].get('exact_matches', 0)}**")
            lines.append(f"- First token competitors: **{b['raw'].get('first_comp', 0)}**")
        lines.append("")
        lines.append("**→ Use this title.**")

    return "\n".join(lines)
