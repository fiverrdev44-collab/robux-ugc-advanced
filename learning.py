"""learning.py — retrieve measured outcomes so later analysis uses them.

Recording advice is not learning. This module reads the recommendation ledger
and returns only outcomes that have evidence: measured_at set, a real outcome,
maturity not invalid/missing, and no `insufficient: true` DiD marker.
"""
import json


def _as_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return {}


def load_measured_outcomes(cur, item_id=None, limit=5):
    """Return evidence-backed measured outcomes, newest first.

    Same-item outcomes are preferred when an item_id is supplied.
    """
    where = ("measured_at is not null and outcome is not null "
             "and coalesce(maturity,'pending') in ('mature','partial')")
    cur.execute(f"""
        select id, item_id, rec_type, status, maturity, outcome,
               did_estimate, control_n, applied_at, measured_at
        from recommendation_ledger
        where {where}
        order by measured_at desc
        limit %s
    """, (max(int(limit) * 4, int(limit)),))
    rows = cur.fetchall()

    out = []
    for (rec_id, iid, rec_type, status, maturity, outcome,
         did, control_n, applied_at, measured_at) in rows:
        payload = _as_dict(outcome)
        did_payload = _as_dict(did)
        if did_payload.get("insufficient") is True:
            continue
        if not payload:
            continue
        out.append({
            "rec_id": rec_id, "item_id": iid, "rec_type": rec_type,
            "status": status, "maturity": maturity,
            "measured_at": str(measured_at), "outcome": payload,
            "control_n": control_n or 0,
        })

    if item_id:
        out.sort(key=lambda r: (r["item_id"] == item_id, r["measured_at"]),
                 reverse=True)
    return out[:int(limit)]


def format_learning_context(cur, item_id=None, limit=3):
    """Compact prompt block of measured outcomes, or '' when none exist."""
    try:
        rows = load_measured_outcomes(cur, item_id=item_id, limit=limit)
    except Exception:
        return ""
    if not rows:
        return ""
    lines = ["=== MEASURED OUTCOMES FROM YOUR CATALOG (EVIDENCE, NOT PROOF) ==="]
    for r in rows:
        o = r["outcome"]
        bits = []
        for key in ("velocity_delta_pct", "sales_delta_pct", "post_favs",
                    "post_units", "days"):
            if key in o and o[key] is not None:
                bits.append(f"{key}={o[key]}")
        scope = f"item {r['item_id']} · {r['rec_type']} · {r['maturity']}"
        controls = f" · controls={r['control_n']}" if r["control_n"] else " · no controls"
        lines.append(f"- {scope}{controls} · " + ", ".join(bits))
    lines.append("Use these only as bounded evidence; one item is not a rule.")
    return "\n".join(lines)
