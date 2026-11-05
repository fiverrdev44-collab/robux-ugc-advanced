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
             "and coalesce(maturity,'pending') in ('mature','partial') "
             "and (applied_at is not null or status = 'applied') "
             "and (applied_at is null or measured_at >= applied_at)")
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
        if payload.get("verified") is False:
            # Explicitly unverified outcomes are not learning evidence.
            continue
        sales_evidence = any(k in payload for k in
                             ("post_units", "sales_delta_pct"))
        if sales_evidence and payload.get("verified") is not True:
            # Missing verification is not proof of verified sales.
            continue
        if sales_evidence and iid is None:
            # Sales evidence must be attributable to a catalog item.
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


def learning_readiness(cur):
    """Read-only audit of whether measured feedback is safe to learn from.

    All thresholds are computed over ONE eligible-outcome population:
    applied + measured + mature/partial + temporally valid. Sales evidence
    additionally requires explicit ``verified: true`` and an attributed item.
    Separate ledger records cannot satisfy different thresholds and produce a
    false-positive READY.

    Never enables ASTRA_LEARNING_IN_GENERATION.
    """
    try:
        cur.execute("""
            with eligible as (
                select *
                from recommendation_ledger
                where (applied_at is not null or status = 'applied')
                  and measured_at is not null
                  and outcome is not null
                  and coalesce(maturity,'pending') in ('mature','partial')
                  and (applied_at is null or measured_at >= applied_at)
            )
            select
              (select count(*) from recommendation_ledger),
              (select count(*) from eligible),
              (select count(*) from eligible where maturity = 'mature'),
              (select count(*) from eligible
                 where outcome ? 'post_units'
                    or outcome ? 'sales_delta_pct'),
              (select count(*) from eligible
                 where (outcome ? 'post_units'
                        or outcome ? 'sales_delta_pct')
                   and outcome->>'verified' = 'true'
                   and item_id is not null),
              (select count(*) from eligible
                 where (outcome ? 'post_units'
                        or outcome ? 'sales_delta_pct')
                   and coalesce(outcome->>'verified','') <> 'true'),
              (select count(*) from eligible
                 where coalesce(control_n,0) >= 10),
              (select count(*) from recommendation_ledger
                 where measured_at is not null
                   and applied_at is not null
                   and measured_at < applied_at),
              (select count(*) from recommendation_ledger
                 where outcome is not null
                   and outcome->>'verified' = 'false')
        """)
        row = cur.fetchone()
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "ready": False,
                "recommended_flag": False,
                "reason": ("ledger not ready; ASTRA_LEARNING_IN_GENERATION "
                           "stays off")}

    (total, eligible, mature, eligible_sales, verified_sales,
     unverified_sales, eligible_controls, leakage,
     explicitly_unverified) = [int(x or 0) for x in row]
    checks = {
        "eligible_outcomes": eligible >= 20,
        "mature_outcomes": mature >= 10,
        "verified_sales_evidence": verified_sales >= 10,
        "eligible_controls": eligible_controls >= 5,
        "no_temporal_leakage": leakage == 0,
        "no_unverified_sales": unverified_sales == 0,
    }
    ready = all(checks.values())
    return {
        "ok": True, "total": total, "eligible": eligible,
        "mature": mature, "eligible_sales": eligible_sales,
        "verified_sales": verified_sales,
        "unverified_sales": unverified_sales,
        "eligible_controls": eligible_controls,
        "leakage": leakage,
        "explicitly_unverified": explicitly_unverified,
        "checks": checks, "ready": ready,
        "recommended_flag": False,
        "reason": ("eligible thresholds met; keep "
                   "ASTRA_LEARNING_IN_GENERATION off until independent review"
                   if ready else
                   "insufficient or unreliable eligible evidence; keep "
                   "ASTRA_LEARNING_IN_GENERATION off"),
    }


def format_learning_readiness(report):
    if not report.get("ok"):
        return f"⚠️ Learning readiness unavailable: {report.get('error')}"
    lines = ["# 🎓 LEARNING READINESS (read-only audit)"]
    lines.append(
        f"• Ledger rows: {report['total']:,} · eligible outcomes "
        f"{report['eligible']:,} · mature {report['mature']:,}")
    lines.append(
        f"• Eligible sales evidence: {report['eligible_sales']:,} · "
        f"verified {report['verified_sales']:,} · "
        f"unverified {report['unverified_sales']:,}")
    lines.append(
        f"• Eligible with controls: {report['eligible_controls']:,} · "
        f"temporal leakage: {report['leakage']:,}")
    for name, passed in report["checks"].items():
        lines.append(f"• {name}: {'✅' if passed else '❌'}")
    lines.append(f"• Generation flag: **OFF** ({report['reason']})")
    return "\n".join(lines)
