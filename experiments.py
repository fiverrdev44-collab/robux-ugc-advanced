"""experiments.py — closed-loop recommendation ledger.

Every recommendation gets an ID, a baseline, an applied/ignored state, and a
measured 7-day outcome. Nothing here predicts; it records what actually
happened after an action.
"""
import json
import re
from datetime import datetime, timezone

from bot_core import get_db


def _json(value):
    return json.dumps(value or {}, default=str)


def _norm(name):
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def create_recommendation(cur, item_id, source, rec_type, baseline,
                          recommended, predicted=None, evidence=None,
                          note=None, dedupe_days=7):
    if item_id:
        cur.execute("""
            select id from recommendation_ledger
            where item_id = %s and rec_type = %s
              and status in ('proposed', 'applied')
              and created_at > now() - make_interval(days => %s)
            order by created_at desc limit 1
        """, (item_id, rec_type, int(dedupe_days)))
        row = cur.fetchone()
        if row:
            return row[0], False

    cur.execute("""
        insert into recommendation_ledger
          (item_id, source, rec_type, baseline_name, baseline_price,
           baseline_favs, baseline_sales_30d, baseline_velocity,
           baseline_age_days, recommended_name, recommended_pivot,
           recommended_price, predicted, evidence, note)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s::jsonb, %s::jsonb, %s)
        returning id
    """, (
        item_id, source, rec_type,
        baseline.get("name"), baseline.get("price", 0),
        baseline.get("favs", 0), baseline.get("sales_30d", 0),
        baseline.get("velocity", 0), baseline.get("age_days", 0),
        recommended.get("name"), recommended.get("pivot"),
        recommended.get("price", 0),
        _json(predicted), _json(evidence), note,
    ))
    return cur.fetchone()[0], True


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
            measure_at = now() + make_interval(days => %s)
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


def measure_due(cur, force=False, limit=50):
    where = "status = 'applied'"
    params = []
    if not force:
        where += " and measure_at is not null and measure_at <= now()"
    cur.execute(f"""
        select id, item_id, applied_at, baseline_name, baseline_price,
               baseline_favs, baseline_sales_30d, baseline_velocity,
               baseline_age_days, recommended_name, recommended_price
        from recommendation_ledger
        where {where}
        order by measure_at asc nulls first
        limit %s
    """, params + [int(limit)])
    rows = cur.fetchall()
    measured = 0
    for (rec_id, item_id, applied_at, b_name, b_price, b_favs,
         b_sales, b_vel, b_age, r_name, r_price) in rows:
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
        }
        cur.execute("""
            update recommendation_ledger
            set status = 'measured', measured_at = now(), outcome = %s::jsonb
            where id = %s
        """, (_json(outcome), rec_id))
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
