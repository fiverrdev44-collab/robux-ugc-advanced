"""backtest_opportunity.py — time-split backtest for title scoring and the gate.

Train window learns word lifts from older launches. Test window is newer and
never contributes to the word statistics. Demand is current search volume, so
the demand component is not historical; the report states that limitation.

Run:
  python backtest_opportunity.py
  python backtest_opportunity.py --family emotes --family hair
"""
import argparse
import json
import math
import os
import random
import sys
from statistics import mean, median

import psycopg2

from title_scorer import _words, _clamp, LIFT_MIN, LIFT_MAX, CONFIDENCE_CAP
from verification import verify_title_deep
from opportunity_score import score_opportunity
from convergence_engine import resolve_family_ids


def fetch_train(cur, family, start_days, end_days, min_favs=0):
    ids = resolve_family_ids(family)
    fam_sql, params = "", []
    if ids:
        fam_sql = " and asset_type_id in (" + ",".join(["%s"] * len(ids)) + ")"
        params = list(ids)
    cur.execute(f"""
        select name, favorite_count,
               extract(epoch from (now() - created_at)) / 86400.0 as age_days
        from items
        where favorite_count is not null
          and favorite_count >= %s
          and created_at between now() - make_interval(days => %s)
                             and now() - make_interval(days => %s)
          {fam_sql}
    """, [int(min_favs), start_days, end_days] + params)
    out = []
    for name, favs, age in cur.fetchall():
        try:
            age = float(age or 0)
            if age <= 0:
                continue
            out.append({
                "name": name or "",
                "favs": float(favs or 0),
                "age_days": age,
                "favs_30d": float(favs or 0) / age * 30.0,
            })
        except Exception:
            continue
    return out


def fetch_test(cur, family, start_days, end_days):
    ids = resolve_family_ids(family)
    fam_sql, params = "", []
    if ids:
        fam_sql = " and asset_type_id in (" + ",".join(["%s"] * len(ids)) + ")"
        params = list(ids)
    cur.execute(f"""
        select id, name, favorite_count,
               extract(epoch from (now() - created_at)) / 86400.0 as age_days
        from items
        where favorite_count is not null
          and created_at between now() - make_interval(days => %s)
                             and now() - make_interval(days => %s)
          {fam_sql}
    """, [start_days, end_days] + params)
    out = []
    for item_id, name, favs, age in cur.fetchall():
        try:
            age = float(age or 0)
            if age < 7:
                continue
            out.append({
                "id": item_id,
                "name": name or "",
                "favs": float(favs or 0),
                "age_days": age,
                "favs_30d": float(favs or 0) / age * 30.0,
            })
        except Exception:
            continue
    return out


def train_word_stats(rows):
    buckets = {}
    bigrams = {}
    cat_vals = []
    for row in rows:
        favs = float(row["favs_30d"] or 0)
        cat_vals.append(favs)
        words = _words(row["name"])
        for w in set(words):
            buckets.setdefault(w, []).append(favs)
        for a, b in zip(words, words[1:]):
            bigrams.setdefault((a, b), []).append(favs)
    cat_med = median(cat_vals) if cat_vals else 25.0
    cat_med = max(cat_med, 25.0)

    def _build(source, min_n):
        out = {}
        for key, vals in source.items():
            if len(vals) < min_n:
                continue
            vals.sort()
            med = vals[len(vals) // 2]
            out[key] = {
                "lift": _clamp(med / cat_med, LIFT_MIN, LIFT_MAX),
                "count": len(vals),
                "median_favs": med,
                "freshness": 1.0,
            }
        return out

    return _build(buckets, 5), _build(bigrams, 5), cat_med


def build_demand(cur, words):
    from title_scorer import compute_search_demand
    return compute_search_demand(cur, sorted(words))


def _demand_mult(stats, demand, word):
    raw = demand.get(word, 0)
    if isinstance(raw, dict):
        live = int(raw.get("live") or 0)
        count = int(raw.get("count") or 0)
        vol = int(raw.get("volume") or 0)
    else:
        live, count, vol = 0, int(raw or 0), 0
    dem = live or count
    if live and vol:
        return 1 + (0.5 * math.log1p(dem) / 3.0
                    + 0.5 * math.log1p(vol) / math.log1p(1_000_000))
    if live:
        return 1 + math.log1p(dem) / 3.0
    return 1 + 0.1 * math.log1p(dem) / 3.0


def backtest_score(title, stats, bigrams, demand):
    words = _words(title)
    if not words:
        return 0.0
    total = 0.0
    for w in words:
        st = stats.get(w)
        if not st:
            continue
        conf = min(1.0, st["count"] / CONFIDENCE_CAP)
        total += st["lift"] * _demand_mult(stats, demand, w) * conf
    word_score = total / len(words)

    bi_total = 0.0
    bi_n = 0
    for a, b in zip(words, words[1:]):
        st = bigrams.get((a, b))
        if not st:
            continue
        conf = min(1.0, st["count"] / CONFIDENCE_CAP)
        bi_total += st["lift"] * conf
        bi_n += 1
    bi_score = bi_total / bi_n if bi_n else 0.0
    return word_score + 0.35 * bi_score


def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(x, y):
    n = len(x)
    if n < 3:
        return 0.0
    mx, my = mean(x), mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx = math.sqrt(sum((a - mx) ** 2 for a in x))
    dy = math.sqrt(sum((b - my) ** 2 for b in y))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def spearman(x, y, permutations=1000, seed=17):
    if len(x) < 3:
        return 0.0, 1.0
    rx, ry = _ranks(x), _ranks(y)
    rho = _pearson(rx, ry)
    rng = random.Random(seed)
    hits = 0
    for _ in range(permutations):
        shuffled = ry[:]
        rng.shuffle(shuffled)
        if abs(_pearson(rx, shuffled)) >= abs(rho):
            hits += 1
    return rho, (hits + 1) / (permutations + 1)


def top_decile(rows, score_key, outcome_key="favs_30d"):
    vals = sorted(r[outcome_key] for r in rows)
    if not vals:
        return None
    threshold = vals[int((len(vals) - 1) * 0.9)]
    k = max(1, int(len(rows) * 0.1))
    ranked = sorted(rows, key=lambda r: r[score_key], reverse=True)[:k]
    success = [1 if r[outcome_key] >= threshold else 0 for r in ranked]
    precision = mean(success) if success else 0.0
    rest = [r for r in rows if r not in ranked]
    return {
        "k": k,
        "threshold": round(threshold, 1),
        "precision": round(precision, 3),
        "base_rate": 0.1,
        "lift": round(precision / 0.1, 2) if precision else 0.0,
        "mean_top": round(mean(r[outcome_key] for r in ranked), 1),
        "mean_rest": (round(mean(r[outcome_key] for r in rest), 1)
                      if rest else None),
    }


def auc_top(rows, score_key, frac=0.1):
    vals = sorted(r["favs_30d"] for r in rows)
    if not vals:
        return None
    threshold = vals[int((len(vals) - 1) * (1 - frac))]
    labels = [1 if r["favs_30d"] >= threshold else 0 for r in rows]
    scores = [r[score_key] for r in rows]
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return None
    ranks = _ranks(scores)
    pos_rank_sum = sum(r for r, y in zip(ranks, labels) if y == 1)
    auc = (pos_rank_sum - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg))
    return round(auc, 3)


def calibration(train_rows, test_rows):
    vals = sorted(r["favs_30d"] for r in train_rows)
    if not vals:
        return None
    threshold = vals[int((len(vals) - 1) * 0.9)]
    hits = sum(1 for r in test_rows if r["favs_30d"] >= threshold)
    return {
        "train_p90_favs_30d": round(threshold, 1),
        "test_hits": hits,
        "test_n": len(test_rows),
        "test_rate": round(100.0 * hits / max(len(test_rows), 1), 1),
        "expected_rate": 10.0,
    }


def sample_stratified(rows, n):
    if len(rows) <= n:
        return rows
    ordered = sorted(rows, key=lambda r: r["favs_30d"])
    half = n // 2
    low = ordered[:max(1, len(ordered) // 2)]
    high = ordered[len(ordered) // 2:]
    rng = random.Random(23)
    pick = rng.sample(low, min(half, len(low)))
    pick += rng.sample(high, min(n - len(pick), len(high)))
    return pick


def run_family(cur, family, args):
    train = fetch_train(cur, family, args.train_start, args.train_end,
                        min_favs=args.train_min_favs)
    test = fetch_test(cur, family, args.test_start, args.test_end)
    if not train or not test:
        return {"family": family, "error": "empty train or test cohort"}

    stats, bigrams, cat_med = train_word_stats(train)
    demand = build_demand(cur, stats.keys())
    for row in test:
        row["score"] = round(
            backtest_score(row["name"], stats, bigrams, demand), 4
        )

    xs = [r["score"] for r in test]
    ys = [r["favs_30d"] for r in test]
    rho, p = spearman(xs, ys, permutations=args.permutations)
    pos_rows = [r for r in test if r["favs_30d"] > 0]
    rho_pos, p_pos = (spearman([r["score"] for r in pos_rows],
                               [r["favs_30d"] for r in pos_rows],
                               permutations=args.permutations)
                      if len(pos_rows) >= 3 else (None, None))
    decile = top_decile(test, "score")
    auc = auc_top(test, "score")
    coverage = 0.0
    covered = 0
    for r in test:
        words = _words(r["name"])
        if words:
            coverage += sum(1 for w in words if w in stats) / len(words)
            if any(w in stats for w in words):
                covered += 1
    coverage = coverage / max(len(test), 1)
    cal = calibration(train, test)

    opp_rows = []
    if not args.skip_opp:
        for row in sample_stratified(test, args.opp_sample):
            opp = score_opportunity(cur, row["name"], family)
            if opp:
                opp_rows.append({
                    "name": row["name"],
                    "favs_30d": row["favs_30d"],
                    "ctr": opp["ctr_proxy"],
                    "verdict": opp["verdict"],
                    "supply": opp["supply"],
                    "strong": opp["strong"],
                    "exact": opp["exact"],
                    "demand": opp["demand_live"],
                    "volume": opp["demand_volume"],
                })
    opp_rho = opp_p = None
    opp_decile = None
    components = {}
    if len(opp_rows) >= 5:
        ys_opp = [r["favs_30d"] for r in opp_rows]
        opp_rho, opp_p = spearman([r["ctr"] for r in opp_rows], ys_opp,
                                  permutations=args.permutations)
        opp_decile = top_decile(opp_rows, "ctr")
        for key in ("supply", "strong", "exact", "demand", "volume"):
            rho_c, p_c = spearman([r[key] for r in opp_rows], ys_opp,
                                  permutations=args.permutations)
            components[key] = {"rho": round(rho_c, 3), "p": round(p_c, 4)}

    gate_rows = []
    if not args.skip_gate:
        allow = set(stats.keys())
        for row in test:
            allow.update(_words(row["name"]))
        allow = sorted(allow)
        for row in sample_stratified(test, args.gate_sample):
            result = verify_title_deep(cur, row["name"], allow, family)
            gate_rows.append({
                "name": row["name"],
                "favs_30d": row["favs_30d"],
                "passed": result["passed"],
                "reasons": result.get("reasons") or [],
                "flags": result.get("flags") or [],
            })
    gate = None
    if gate_rows:
        passed = [r for r in gate_rows if r["passed"]]
        failed = [r for r in gate_rows if not r["passed"]]
        gate = {
            "n": len(gate_rows),
            "pass": len(passed),
            "fail": len(failed),
            "mean_pass": round(mean([r["favs_30d"] for r in passed]), 1)
                         if passed else None,
            "mean_fail": round(mean([r["favs_30d"] for r in failed]), 1)
                         if failed else None,
            "top_pass": sum(1 for r in passed if r["favs_30d"] > 0),
            "top_fail": sum(1 for r in failed if r["favs_30d"] > 0),
        }

    return {
        "family": family,
        "train_n": len(train),
        "test_n": len(test),
        "test_positive": sum(1 for r in test if r["favs_30d"] > 0),
        "train_family_median_favs": round(cat_med, 1),
        "words_learned": len(stats),
        "bigrams_learned": len(bigrams),
        "spearman": round(rho, 3),
        "p_value": round(p, 4),
        "spearman_positive": round(rho_pos, 3) if rho_pos is not None else None,
        "p_positive": round(p_pos, 4) if p_pos is not None else None,
        "top_decile": decile,
        "auc_top10": auc,
        "word_coverage": round(coverage, 3),
        "covered_titles": covered,
        "calibration": cal,
        "opportunity_sample_n": len(opp_rows),
        "opportunity_spearman": round(opp_rho, 3) if opp_rho is not None else None,
        "opportunity_p": round(opp_p, 4) if opp_p is not None else None,
        "opportunity_top_decile": opp_decile,
        "opportunity_components": components,
        "verdict_counts": _count(opp_rows, "verdict"),
        "gate": gate,
        "gate_examples": gate_rows[:8],
    }


def _count(rows, key):
    out = {}
    for r in rows:
        out[r.get(key)] = out.get(r.get(key), 0) + 1
    return out


def format_report(results):
    lines = ["# 🧪 Backtest — time-split holdout", ""]
    lines.append(
        "_Train learns word lifts. Test is newer and never contributes to "
        "the statistics. Demand is current search volume, so the demand "
        "component is not historical._"
    )
    lines.append("")
    usable = [r for r in results if not r.get("error")]
    significant = [
        r for r in usable
        if r.get("p_value", 1) < 0.1 and r.get("spearman", 0) > 0
    ]
    if usable and not significant:
        lines.append(
            "**Bottom line: NO PROVEN SIGNAL.** The title score did not rank "
            "launches better than chance in this holdout. Do not treat the "
            "score as a probability."
        )
        lines.append("")
    elif significant:
        lines.append(
            "**Bottom line: weak positive signal in "
            + ", ".join(r["family"] for r in significant)
            + ".** Still validate on a prospective cohort before trusting it."
        )
        lines.append("")
    for res in results:
        lines.append(f"## {res.get('family')}")
        if res.get("error"):
            lines.append(f"❌ {res['error']}")
            lines.append("")
            continue
        lines.append(
            f"• Train: **{res['train_n']}** items (favorites > 5) · "
            f"Test: **{res['test_n']}** items ({res['test_positive']} positive)"
        )
        lines.append(
            f"• Learned words: **{res['words_learned']}** · "
            f"bigrams **{res['bigrams_learned']}** · "
            f"word coverage **{res['word_coverage']:.0%}** "
            f"({res['covered_titles']}/{res['test_n']} titles)"
        )
        lines.append(
            f"• Spearman(score, 30d favs) = **{res['spearman']}** "
            f"(p={res['p_value']}) · positive-only **{res.get('spearman_positive')}** "
            f"(p={res.get('p_positive')}) · AUC top10 **{res.get('auc_top10')}**"
        )
        d = res.get("top_decile") or {}
        if d:
            lines.append(
                f"• Top decile: precision **{d['precision']:.1%}** "
                f"({d['lift']}× base) · top mean **{d['mean_top']}** "
                f"vs rest **{d['mean_rest']}** 30d favs"
            )
        c = res.get("calibration") or {}
        if c:
            lines.append(
                f"• Calibration: train p90 = **{c['train_p90_favs_30d']}** "
                f"favs/30d · test hit rate **{c['test_rate']}%** "
                f"(expected {c['expected_rate']}%)"
            )
        if res.get("opportunity_spearman") is not None:
            lines.append(
                f"• Opportunity CTR: Spearman **{res['opportunity_spearman']}** "
                f"(p={res['opportunity_p']}) on "
                f"{res['opportunity_sample_n']} sampled titles"
            )
            od = res.get("opportunity_top_decile") or {}
            if od:
                lines.append(
                    f"  – CTR top decile precision **{od['precision']:.1%}** "
                    f"({od['lift']}× base)"
                )
            comp = res.get("opportunity_components") or {}
            if comp:
                parts = ", ".join(
                    f"{k} {v['rho']:+.2f}" for k, v in comp.items()
                )
                lines.append(f"  – component rho vs outcome: {parts}")
        g = res.get("gate")
        if g:
            lines.append(
                f"• Gate sample: **{g['pass']}/{g['n']} passed** · "
                f"mean 30d favs pass **{g['mean_pass']}** vs fail "
                f"**{g['mean_fail']}** · positives pass/fail "
                f"{g['top_pass']}/{g['top_fail']}"
            )
            for ex in (res.get("gate_examples") or [])[:5]:
                if ex.get("passed"):
                    continue
                lines.append(
                    f"  – rejected `{ex['name'][:36]}` "
                    f"({ex['favs_30d']:.1f} favs/30d): "
                    f"{'; '.join(ex['reasons'])[:110]}"
                )
        lines.append("")
    lines.append("## How to read this")
    lines.append(
        "• Spearman > 0 and p < 0.1 = the score ranks launches better than chance.\n"
        "• Top-decile lift > 1 = the score puts real winners near the top.\n"
        "• Calibration near 10% = the “top 10%” base rate transfers to new launches.\n"
        "• Gate means: if failing titles have similar/higher 30d favorites, the "
        "gate is too strict.\n"
        "• Opportunity CTR on existing names is diagnostic only: the item itself "
        "is included in current supply/exact counts, so that row is confounded."
    )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", action="append", default=None)
    parser.add_argument("--train-start", type=int, default=120)
    parser.add_argument("--train-end", type=int, default=45)
    parser.add_argument("--train-min-favs", type=int, default=0)
    parser.add_argument("--test-start", type=int, default=45)
    parser.add_argument("--test-end", type=int, default=15)
    parser.add_argument("--permutations", type=int, default=600)
    parser.add_argument("--opp-sample", type=int, default=40)
    parser.add_argument("--gate-sample", type=int, default=20)
    parser.add_argument("--skip-opp", action="store_true")
    parser.add_argument("--skip-gate", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    families = args.family or ["emotes", "hair", "accessory"]
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    conn = psycopg2.connect(url, sslmode="require", connect_timeout=10)
    cur = conn.cursor()
    try:
        results = [run_family(cur, fam, args) for fam in families]
    finally:
        cur.close()
        conn.close()

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(format_report(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
