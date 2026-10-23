"""matched_experiments.py — pre/post comparison against matched controls.

This is an observational difference-in-differences estimate, not proof of
causation. Controls are selected using pre-intervention features only.
"""
import json
import math
import random
from datetime import timedelta
from statistics import median

from bot_core import get_db


def _fav_near(cur, item_id, when, tolerance_days=3):
    cur.execute("""
        SELECT favorite_count
        FROM item_history
        WHERE item_id = %s
          AND snapshot_at BETWEEN %s AND %s
        ORDER BY abs(extract(epoch from (snapshot_at - %s)))
        LIMIT 1
    """, (item_id, when - timedelta(days=tolerance_days),
          when + timedelta(days=tolerance_days), when))
    row = cur.fetchone()
    return None if not row or row[0] is None else int(row[0])


def _velocity_pair(cur, item_id, treatment_at, window_days=7):
    before = _fav_near(cur, item_id, treatment_at - timedelta(days=window_days))
    at = _fav_near(cur, item_id, treatment_at)
    after = _fav_near(cur, item_id, treatment_at + timedelta(days=window_days))
    if before is None or at is None or after is None:
        return None
    pre = (at - before) / float(window_days)
    post = (after - at) / float(window_days)
    return {
        "pre": round(pre, 4),
        "post": round(post, 4),
        "delta": round(post - pre, 4),
        "before": before,
        "at": at,
        "after": after,
    }


def distance(treatment, candidate):
    """Pure matching distance using pre-intervention features only."""
    d_price = abs(math.log1p(max(treatment["price"], 0))
                  - math.log1p(max(candidate["price"], 0)))
    d_age = abs(treatment["age_days"] - candidate["age_days"]) / 30.0
    d_vel = abs(math.log1p(max(treatment["pre_velocity"], 0))
                - math.log1p(max(candidate["pre_velocity"], 0)))
    return round(d_price + d_age + d_vel, 4)


def select_controls(treatment, candidates, max_controls=5):
    """Pure selection: treatment and candidates are pre-intervention dicts."""
    ranked = sorted(candidates, key=lambda c: distance(treatment, c))
    return ranked[:max_controls]


def did_estimate(treatment_delta, control_deltas, confidence=0.80, iters=1000,
                 seed=17):
    if not control_deltas:
        return {"insufficient": True, "reason": "no controls"}
    estimate = treatment_delta - median(control_deltas)
    if len(control_deltas) < 3:
        return {
            "insufficient": True,
            "reason": f"only {len(control_deltas)} controls with pre/post data",
            "estimate": round(estimate, 4),
            "n": len(control_deltas),
        }
    rng = random.Random(seed)
    boots = []
    for _ in range(iters):
        sample = [rng.choice(control_deltas) for _ in control_deltas]
        boots.append(treatment_delta - median(sample))
    boots.sort()

    def _interval(conf):
        alpha = (1 - conf) / 2
        return [round(boots[int(alpha * (len(boots) - 1))], 4),
                round(boots[int((1 - alpha) * (len(boots) - 1))], 4)]

    n = len(control_deltas)
    return {
        "insufficient": False,
        "estimate": round(estimate, 4),
        "ci80": _interval(0.80),
        "ci95": _interval(0.95),
        "n": n,
        "exploratory": n < 5,
        "method": "difference-in-differences, median control change",
        "assumptions": [
            "controls share family, age, price and pre-velocity bands",
            "no simultaneous treatment on controls",
            "observational comparison, not a randomized experiment",
        ],
    }


def _family_ids(family):
    try:
        from convergence_engine import resolve_family_ids
        return resolve_family_ids(family)
    except Exception:
        return None


def _item_family(cur, item_id):
    cur.execute("""
        SELECT i.asset_type_id, i.price, i.created_at,
               coalesce(l.family, '') AS family
        FROM items i LEFT JOIN launch_ledger l ON l.item_id = i.id
        WHERE i.id = %s
    """, (item_id,))
    row = cur.fetchone()
    if not row:
        return None
    atype, price, created, family = row
    if not family:
        try:
            from category_configs import detect_family_from_asset_type
            family = detect_family_from_asset_type(atype)
        except Exception:
            family = None
    return {"asset_type_id": atype, "price": int(price or 0),
            "created_at": created, "family": family}


def evaluate(cur, rec_id, window_days=7, max_controls=5):
    cur.execute("""
        SELECT item_id, applied_at, baseline_favs, baseline_velocity,
               baseline_age_days, baseline_price, status
        FROM recommendation_ledger WHERE id = %s
    """, (rec_id,))
    rec = cur.fetchone()
    if not rec:
        return {"insufficient": True, "reason": "recommendation not found"}
    item_id, applied_at, base_favs, base_vel, base_age, base_price, status = rec
    if not item_id or not applied_at:
        result = {"insufficient": True, "reason": "no item or applied_at"}
        _store(cur, rec_id, None, result)
        return result

    treat_pair = _velocity_pair(cur, item_id, applied_at, window_days)
    if not treat_pair:
        result = {"insufficient": True,
                  "reason": "treatment lacks pre/post snapshots"}
        _store(cur, rec_id, None, result)
        return result

    fam = _item_family(cur, item_id)
    ids = _family_ids(fam["family"]) if fam else None
    fam_sql, params = "", []
    if ids:
        fam_sql = " and i.asset_type_id in (" + ",".join(["%s"] * len(ids)) + ")"
        params = list(ids)
    cur.execute(f"""
        SELECT i.id, i.name,
               COALESCE((l.features->>'price')::int, i.price) AS price,
               i.created_at
        FROM items i
        LEFT JOIN launch_ledger l ON l.item_id = i.id
        WHERE i.id <> %s
          AND i.created_at IS NOT NULL
          AND i.created_at BETWEEN %s AND %s
          AND COALESCE((l.features->>'price')::int, i.price)
              BETWEEN %s AND %s
          {fam_sql}
          AND NOT EXISTS (
              SELECT 1 FROM recommendation_ledger r
              WHERE r.item_id = i.id AND r.applied_at IS NOT NULL
          )
        LIMIT 300
    """, [item_id, applied_at - timedelta(days=30),
          applied_at + timedelta(days=30),
          max(0, int((base_price or (fam or {}).get("price", 0)) * 0.6)),
          max(1, int((base_price or (fam or {}).get("price", 0)) * 1.6))] + params)
    candidates = []
    for cid, name, price, created in cur.fetchall():
        pair = _velocity_pair(cur, cid, applied_at, window_days)
        if not pair:
            continue
        age = max((applied_at - created).total_seconds() / 86400.0, 0)
        candidates.append({
            "id": cid, "name": name, "price": int(price or 0),
            "age_days": round(age, 1), "pre_velocity": pair["pre"],
            "_pair": pair,
        })
    treatment = {
        "id": item_id,
        "price": int(base_price or (fam or {}).get("price", 0)),
        "age_days": float(base_age or 0),
        "pre_velocity": treat_pair["pre"],
    }
    controls = select_controls(treatment, candidates, max_controls)
    for c in controls:
        c["distance"] = distance(treatment, c)
    result = did_estimate(treat_pair["delta"],
                          [c["_pair"]["delta"] for c in controls])
    result["treatment_pre"] = treat_pair["pre"]
    result["treatment_post"] = treat_pair["post"]
    result["window_days"] = window_days
    result["family"] = (fam or {}).get("family")
    _store(cur, rec_id, controls, result)
    return result


def _store(cur, rec_id, controls, result):
    cur.execute("DELETE FROM experiment_controls WHERE rec_id = %s", (rec_id,))
    if controls:
        for c in controls:
            cur.execute("""
                INSERT INTO experiment_controls
                  (rec_id, control_item_id, distance, features)
                VALUES (%s, %s, %s, %s::jsonb)
            """, (rec_id, c["id"], c.get("distance"),
                  json.dumps({k: v for k, v in c.items() if k != "_pair"},
                             default=str)))
    quality = None
    if controls:
        quality = round(1.0 / (1.0 + median(
            [c.get("distance", 0) for c in controls])), 3)
    cur.execute("""
        UPDATE recommendation_ledger SET
            control_method = 'matched pre-intervention cohort',
            control_n = %s,
            match_quality = %s,
            did_estimate = %s::jsonb,
            assumptions = %s,
            evaluated_at = now()
        WHERE id = %s
    """, (len(controls or []), quality, json.dumps(result, default=str),
          "observational DiD; not causal proof", rec_id))


def evaluate_due(cur, limit=20):
    cur.execute("""
        SELECT id FROM recommendation_ledger
        WHERE status IN ('applied', 'measured')
          AND applied_at IS NOT NULL
          AND (evaluated_at IS NULL OR evaluated_at < now() - interval '7 days')
        ORDER BY applied_at DESC
        LIMIT %s
    """, (int(limit),))
    count = 0
    for (rec_id,) in cur.fetchall():
        try:
            evaluate(cur, rec_id)
            count += 1
        except Exception as e:
            print(f"[matched] rec {rec_id} failed: {e}", flush=True)
    return count


def format_did(result):
    if not result:
        return None
    if result.get("insufficient"):
        return f"_Matched controls: insufficient — {result.get('reason')}_"
    lo80, hi80 = result.get("ci80", [None, None])
    lo95, hi95 = result.get("ci95", [None, None])
    label = "Exploratory DiD" if result.get("exploratory") else "DiD"
    return (
        f"_{label} estimate **{result['estimate']:+.3f} favs/day** "
        f"(80% CI {lo80:+.3f} to {hi80:+.3f}; "
        f"95% CI {lo95:+.3f} to {hi95:+.3f}; n={result['n']} controls)_\n"
        f"_Observational comparison, not causal proof._"
    )


def recent_lines(cur, limit=5):
    cur.execute("""
        SELECT id, control_n, match_quality, did_estimate
        FROM recommendation_ledger
        WHERE evaluated_at IS NOT NULL
        ORDER BY evaluated_at DESC
        LIMIT %s
    """, (int(limit),))
    rows = cur.fetchall()
    if not rows:
        return ""
    lines = ["", "## 🧬 MATCHED CONTROLS"]
    for rec_id, n, quality, did in rows:
        if not did:
            continue
        if did.get("insufficient"):
            lines.append(
                f"• `#{rec_id}` — insufficient ({did.get('reason')})"
            )
        else:
            lo, hi = did.get("ci80", [None, None])
            label = "exploratory" if did.get("exploratory") else "DiD"
            lo95 = (did.get("ci95") or [None, None])[0]
            hi95 = (did.get("ci95") or [None, None])[1]
            lines.append(
                f"• `#{rec_id}` — {label} **{did['estimate']:+.3f} favs/day** "
                f"(80% CI {lo:+.3f}–{hi:+.3f}; 95% CI {lo95:+.3f}–{hi95:+.3f}; "
                f"n={did.get('n')}, quality {quality or 0:.2f})"
            )
    if len(lines) == 2:
        return ""
    lines.append("_Observational comparison, not causal proof._")
    return "\n".join(lines)
