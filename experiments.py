"""experiments.py — closed-loop recommendation ledger.

Every recommendation gets an ID, a baseline, an applied/ignored state, and a
measured 7-day outcome. Nothing here predicts; it records what actually
happened after an action.
"""
import json
import re
from datetime import datetime, timedelta, timezone

from bot_core import get_db


def _json(value):
    return json.dumps(value or {}, default=str)


def _norm(name):
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def application_matches(actual_name, actual_price, rec_name, rec_price):
    """A metadata change is only evidence when it matches the request."""
    name_match = bool(rec_name) and _norm(actual_name or "") == _norm(rec_name or "")
    try:
        price_match = (rec_price is not None
                       and int(actual_price or 0) == int(rec_price))
    except (TypeError, ValueError):
        price_match = False
    return {"name_match": name_match, "price_match": price_match,
            "verified": bool(name_match or price_match)}


def create_recommendation(cur, item_id, source, rec_type, baseline,
                          recommended, predicted=None, evidence=None,
                          note=None, dedupe_days=7, hypothesis=None,
                          proposed_change=None, success_condition=None,
                          alternatives=None, expected_direction=None,
                          effort=None):
    active_id = None
    if item_id:
        cur.execute("""
            select id from recommendation_ledger
            where item_id = %s and status = 'applied'
              and measured_at is null
              and measure_at is not null and measure_at > now()
            order by applied_at desc nulls last
            limit 1
        """, (item_id,))
        row = cur.fetchone()
        active_id = row[0] if row else None

    if active_id is None and item_id:
        cur.execute("""
            select id, rec_type from recommendation_ledger
            where item_id = %s
              and status = 'proposed'
              and created_at > now() - make_interval(days => %s)
            order by created_at desc
        """, (item_id, int(dedupe_days)))
        for existing_id, existing_type in cur.fetchall():
            if existing_type == rec_type:
                return existing_id, False
        cur.execute("""
            update recommendation_ledger
            set status = 'superseded'
            where item_id = %s and status = 'proposed'
        """, (item_id,))

    # A new suggestion must not silently replace a running experiment.
    status = "superseded" if active_id else "proposed"
    cur.execute("""
        insert into recommendation_ledger
          (item_id, source, rec_type, status, superseded_by,
           baseline_name, baseline_price,
           baseline_favs, baseline_sales_30d, baseline_velocity,
           baseline_age_days, recommended_name, recommended_pivot,
           recommended_price, predicted, evidence, note,
           hypothesis, proposed_change, success_condition, alternatives,
           expected_direction, effort)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s::jsonb, %s::jsonb, %s, %s, %s::jsonb, %s::jsonb,
                %s::jsonb, %s, %s)
        returning id
    """, (
        item_id, source, rec_type, status, active_id,
        baseline.get("name"), baseline.get("price", 0),
        baseline.get("favs", 0), baseline.get("sales_30d", 0),
        baseline.get("velocity", 0), baseline.get("age_days", 0),
        recommended.get("name"), recommended.get("pivot"),
        recommended.get("price", 0),
        _json(predicted), _json(evidence), note,
        hypothesis, _json(proposed_change), _json(success_condition),
        _json(alternatives), expected_direction, effort,
    ))
    return cur.fetchone()[0], status == "proposed"


def mark_applied(cur, rec_id, days=7):
    cur.execute("""
        select id, status, source, rec_type, item_id,
               baseline_name, recommended_name
        from recommendation_ledger where id = %s
    """, (rec_id,))
    row = cur.fetchone()
    if not row:
        return None, "not found"
    cur.execute("""
        update recommendation_ledger
        set status = 'applied',
            applied_at = now(),
            measure_at = now() + make_interval(days => %s),
            application_status = 'creator_reported',
            application_evidence = jsonb_build_object(
                'method', 'manual !applied',
                'recorded_at', now()
            )
        where id = %s
        returning measure_at
    """, (int(days), rec_id))
    measure_at = cur.fetchone()[0]
    return {
        "id": row[0], "status": row[1], "source": row[2],
        "rec_type": row[3], "item_id": row[4],
        "baseline_name": row[5], "recommended_name": row[6],
        "measure_at": measure_at,
    }, None


def mark_ignored(cur, rec_id):
    cur.execute("""
        update recommendation_ledger
        set status = 'ignored', measured_at = now()
        where id = %s and status = 'proposed'
        returning id
    """, (rec_id,))
    row = cur.fetchone()
    if not row:
        return None, "only proposed recommendations can be ignored"
    return row[0], None


def _sales_units(cur, names, since):
    cleaned = sorted({_norm(n) for n in names if n})
    if not cleaned:
        return 0
    cur.execute("""
        select count(*) from my_sales
        where sale_time >= %s
          and regexp_replace(lower(item_name), '[^a-z0-9]+', ' ', 'g')
              = any(%s)
    """, (since, cleaned))
    return int(cur.fetchone()[0] or 0)


def auto_apply_changes(cur, limit=50):
    """Auto-mark proposals only when the changed field matches the request.

    A generic rename or price change is not proof the advice was followed, so
    non-matching changes are recorded as `inferred_change` and stay proposed.
    """
    cur.execute("""
        select id, item_id, baseline_name, baseline_price,
               recommended_name, recommended_price
        from recommendation_ledger
        where status = 'proposed' and item_id is not null
          and created_at > now() - interval '30 days'
        order by created_at desc
        limit %s
    """, (int(limit),))
    rows = cur.fetchall()
    applied = 0
    inferred = 0
    for (rec_id, item_id, b_name, b_price,
         rec_name, rec_price) in rows:
        cur.execute("select name, price from items where id = %s", (item_id,))
        item = cur.fetchone()
        if not item:
            continue
        name, price = item
        name_changed = ((name or "").strip().lower()
                        != (b_name or "").strip().lower())
        price_changed = int(price or 0) != int(b_price or 0)
        if not (name_changed or price_changed):
            continue

        match = application_matches(name, price, rec_name, rec_price)
        evidence = {
            "actual_name": name,
            "actual_price": int(price or 0),
            "baseline_name": b_name,
            "baseline_price": int(b_price or 0),
            "requested_name": rec_name,
            "requested_price": (int(rec_price) if rec_price is not None else None),
            "name_match": match["name_match"],
            "price_match": match["price_match"],
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }
        if match["verified"]:
            cur.execute("""
                update recommendation_ledger
                set status = 'applied',
                    applied_at = now(),
                    measure_at = now() + interval '7 days',
                    application_status = 'verified_fields',
                    application_evidence = %s::jsonb,
                    note = coalesce(note, '') ||
                           ' | auto-applied: requested field matched'
                where id = %s and status = 'proposed'
            """, (_json(evidence), rec_id))
            applied += 1
        else:
            cur.execute("""
                update recommendation_ledger
                set application_status = 'inferred_change',
                    application_evidence = %s::jsonb,
                    note = coalesce(note, '') ||
                           ' | inferred change: does not match request'
                where id = %s and status = 'proposed'
            """, (_json(evidence), rec_id))
            inferred += 1
    if inferred:
        print(f"[experiments] {inferred} metadata change(s) inferred, not applied",
              flush=True)
    return applied


def mark_latest(cur, rec_type=None):
    """Apply the newest proposed recommendation, no ID needed."""
    sql = """
        select id from recommendation_ledger
        where status = 'proposed'
    """
    params = []
    if rec_type:
        sql += " and rec_type = %s"
        params.append(rec_type)
    sql += " order by created_at desc limit 1"
    cur.execute(sql, params)
    row = cur.fetchone()
    if not row:
        return None, "no proposed recommendation found"
    return mark_applied(cur, row[0])


def mark_latest_ignored(cur):
    cur.execute("""
        select id from recommendation_ledger
        where status = 'proposed'
        order by created_at desc limit 1
    """)
    row = cur.fetchone()
    if not row:
        return None, "no proposed recommendation found"
    return mark_ignored(cur, row[0])


def measure_due(cur, force=False, limit=50):
    where = "status in ('applied', 'measured')"
    params = []
    if not force:
        where += " and measure_at is not null and measure_at <= now()"
    cur.execute(f"""
        select id, item_id, applied_at, baseline_name, baseline_price,
               baseline_favs, baseline_sales_30d, baseline_velocity,
               baseline_age_days, recommended_name, recommended_price,
               coalesce(contaminated, false)
        from recommendation_ledger
        where {where}
        order by measure_at asc nulls first
        limit %s
    """, params + [int(limit)])
    rows = cur.fetchall()
    measured = 0
    for (rec_id, item_id, applied_at, b_name, b_price, b_favs,
         b_sales, b_vel, b_age, r_name, r_price, contaminated) in rows:
        cur.execute("""
            select name, favorite_count, price
            from items where id = %s
        """, (item_id,))
        item = cur.fetchone()
        if not item:
            continue
        cur_name, cur_favs, cur_price = item
        now = datetime.now(timezone.utc)
        days = max((now - applied_at).total_seconds() / 86400.0, 0.01)
        post_favs = max(int(cur_favs or 0) - int(b_favs or 0), 0)
        post_vel = post_favs / days
        base_vel = float(b_vel or 0)
        vel_delta = ((post_vel - base_vel) / base_vel * 100.0
                     if base_vel > 0 else None)
        units = _sales_units(
            cur, [b_name, cur_name, r_name], applied_at
        )
        base_units_day = float(b_sales or 0) / 30.0
        units_day = units / days
        sales_delta = ((units_day - base_units_day) / base_units_day * 100.0
                       if base_units_day > 0 else None)
        outcome = {
            "days": round(days, 2),
            "current_name": cur_name,
            "current_price": int(cur_price or 0),
            "current_favs": int(cur_favs or 0),
            "post_favs": post_favs,
            "post_velocity": round(post_vel, 3),
            "baseline_velocity": round(base_vel, 3),
            "velocity_delta_pct": (round(vel_delta, 1)
                                   if vel_delta is not None else None),
            "post_units": units,
            "units_per_day": round(units_day, 3),
            "baseline_units_per_day": round(base_units_day, 3),
            "sales_delta_pct": (round(sales_delta, 1)
                                if sales_delta is not None else None),
            "checkpoint": min((7, 14, 30), key=lambda d: abs(d - days)),
        }
        next_day = next((d for d in (7, 14, 30) if d > days + 0.5), None)
        if contaminated:
            maturity = "invalid"
        elif cur_favs is None or b_favs is None:
            maturity = "missing"
        elif next_day is not None:
            maturity = "partial"
        else:
            maturity = "mature"
        if next_day is not None and not force:
            next_at = applied_at + timedelta(days=next_day)
            cur.execute("""
                update recommendation_ledger
                set status = 'applied', measured_at = now(),
                    measure_at = %s, outcome = %s::jsonb,
                    outcome_history = outcome_history || %s::jsonb,
                    maturity = %s
                where id = %s
            """, (next_at, _json(outcome), _json([outcome]), maturity, rec_id))
        else:
            cur.execute("""
                update recommendation_ledger
                set status = 'measured', measured_at = now(),
                    measure_at = null, outcome = %s::jsonb,
                    outcome_history = outcome_history || %s::jsonb,
                    maturity = %s
                where id = %s
            """, (_json(outcome), _json([outcome]), maturity, rec_id))
        measured += 1
    return measured


def summary(cur, limit=10):
    cur.execute("""
        select count(*) filter (where status = 'proposed'),
               count(*) filter (where status = 'applied'),
               count(*) filter (where status = 'measured'),
               count(*) filter (where status = 'ignored')
        from recommendation_ledger
    """)
    proposed, applied, measured, ignored = cur.fetchone()
    cur.execute("""
        select outcome->>'velocity_delta_pct',
               outcome->>'sales_delta_pct'
        from recommendation_ledger
        where status = 'measured'
    """)
    vels, sales = [], []
    for v, s in cur.fetchall():
        try:
            if v is not None:
                vels.append(float(v))
        except (TypeError, ValueError):
            pass
        try:
            if s is not None:
                sales.append(float(s))
        except (TypeError, ValueError):
            pass
    cur.execute("""
        select r.id, r.item_id, r.rec_type, r.status,
               coalesce(i.name, r.baseline_name, '?'),
               r.recommended_name, r.measure_at, r.measured_at,
               r.outcome
        from recommendation_ledger r
        left join items i on i.id = r.item_id
        order by r.created_at desc
        limit %s
    """, (int(limit),))
    recent = cur.fetchall()
    return {
        "counts": {
            "proposed": int(proposed or 0),
            "applied": int(applied or 0),
            "measured": int(measured or 0),
            "ignored": int(ignored or 0),
        },
        "avg_velocity": round(sum(vels) / len(vels), 1) if vels else None,
        "avg_sales": round(sum(sales) / len(sales), 1) if sales else None,
        "n_measured": int(measured or 0),
        "recent": recent,
    }


def format_summary(data):
    c = data["counts"]
    lines = [
        "# 🧪 EXPERIMENTS",
        f"Proposed **{c['proposed']}** · Applied **{c['applied']}** · "
        f"Measured **{c['measured']}** · Ignored **{c['ignored']}**",
    ]
    if data.get("n_measured"):
        parts = []
        if data.get("avg_velocity") is not None:
            parts.append(f"Avg velocity uplift "
                         f"**{data['avg_velocity']:+.1f}%**")
        if data.get("avg_sales") is not None:
            parts.append(f"Avg sales uplift **{data['avg_sales']:+.1f}%**")
        lines.append(
            " · ".join(parts) + f" (n={data['n_measured']})"
            if parts else f"Measured **{data['n_measured']}** (no deltas yet)"
        )
    else:
        lines.append("_No measured experiments yet._")
    lines.append("")
    for (rec_id, item_id, rec_type, status, name, rec_name,
         measure_at, measured_at, outcome) in data["recent"]:
        extra = ""
        if outcome:
            v = outcome.get("velocity_delta_pct")
            s = outcome.get("sales_delta_pct")
            bits = []
            day = outcome.get("checkpoint")
            if day:
                bits.append(f"day {day}")
            if v is not None:
                bits.append(f"{v:+.1f}% velocity")
            if s is not None:
                bits.append(f"{s:+.1f}% sales")
            extra = " · " + " · ".join(bits) if bits else ""
        elif status == "applied" and measure_at:
            extra = f" · measure {measure_at:%Y-%m-%d}"
        lines.append(
            f"`#{rec_id}` **{rec_type}** · {status} · "
            f"`{(name or '?')[:40]}`{extra}"
        )
    lines.append(
        "\n_`!applied <id>` after you change the item · "
        "`!ignored <id>` if you skip it._"
    )
    return "\n".join(lines)
