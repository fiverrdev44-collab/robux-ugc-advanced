"""data_audit.py — read-only integrity report.

Never deletes ambiguous records. Reports what is missing, duplicated, stale, or
unmeasured so the operator can decide.
"""


def _one(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchone()[0]


def favorite_states(cur):
    cur.execute("""
        SELECT COALESCE(favorite_status, 'unset'), COUNT(*)
        FROM items
        GROUP BY 1
        ORDER BY 2 DESC
    """)
    states = {k: int(v) for k, v in cur.fetchall()}
    cur.execute("""
        SELECT
          COUNT(*) FILTER (WHERE favorite_count IS NULL),
          COUNT(*) FILTER (WHERE favorite_count = 0),
          COUNT(*) FILTER (WHERE favorite_count > 0),
          COUNT(*)
        FROM items
    """)
    nulls, zeros, positive, total = cur.fetchone()
    return {
        "status": states,
        "null": int(nulls or 0),
        "zero": int(zeros or 0),
        "positive": int(positive or 0),
        "total": int(total or 0),
        "coverage_pct": round(100.0 * (positive or 0) / max(total or 1, 1), 1),
    }


def sales_integrity(cur):
    total = _one(cur, "SELECT COUNT(*) FROM my_sales")
    event_ids = _one(cur, """
        SELECT COUNT(*) FROM my_sales WHERE source_event_id IS NOT NULL
    """)
    fallback = _one(cur, """
        SELECT COUNT(*) FROM my_sales WHERE source_event_id IS NULL
    """)
    dup_event = _one(cur, """
        SELECT COUNT(*) FROM (
            SELECT source_event_id FROM my_sales
            WHERE source_event_id IS NOT NULL
            GROUP BY 1 HAVING COUNT(*) > 1
        ) t
    """)
    dup_fingerprint = _one(cur, """
        SELECT COUNT(*) FROM (
            SELECT sale_time, item_name, buyer, amount_robux
            FROM my_sales
            WHERE source_event_id IS NULL
            GROUP BY 1,2,3,4 HAVING COUNT(*) > 1
        ) t
    """)
    return {
        "total": int(total or 0),
        "event_id": int(event_ids or 0),
        "fallback_fingerprint": int(fallback or 0),
        "duplicate_event_ids": int(dup_event or 0),
        "duplicate_fingerprints": int(dup_fingerprint or 0),
    }


def snapshot_integrity(cur):
    rows = _one(cur, "SELECT COUNT(*) FROM item_history")
    items = _one(cur, "SELECT COUNT(DISTINCT item_id) FROM item_history")
    today = _one(cur, """
        SELECT COUNT(*) FROM item_history
        WHERE snapshot_at >= CURRENT_DATE
    """)
    week = _one(cur, """
        SELECT COUNT(*) FROM item_history
        WHERE snapshot_at > now() - interval '7 days'
    """)
    dup_days = _one(cur, """
        SELECT COUNT(*) FROM (
            SELECT item_id, snapshot_at::date
            FROM item_history
            GROUP BY 1,2 HAVING COUNT(*) > 1
        ) t
    """)
    return {
        "rows": int(rows or 0),
        "items": int(items or 0),
        "today": int(today or 0),
        "last_7d": int(week or 0),
        "duplicate_item_days": int(dup_days or 0),
    }


def ledger_integrity(cur):
    total = _one(cur, "SELECT COUNT(*) FROM launch_ledger")
    missing_features = _one(cur, """
        SELECT COUNT(*) FROM launch_ledger WHERE features IS NULL
    """)
    missing_d30 = _one(cur, """
        SELECT COUNT(*) FROM launch_ledger WHERE favs_d30 IS NULL
    """)
    old_missing_d30 = _one(cur, """
        SELECT COUNT(*) FROM launch_ledger
        WHERE launched_at < now() - interval '30 days'
          AND favs_d30 IS NULL
    """)
    stale = _one(cur, """
        SELECT COUNT(*) FROM launch_ledger
        WHERE last_synced IS NULL
           OR last_synced < now() - interval '7 days'
    """)
    unlabeled = _one(cur, """
        SELECT COUNT(*) FROM launch_ledger
        WHERE launched_at < now() - interval '30 days'
          AND label_beat_median IS NULL
    """)
    return {
        "total": int(total or 0),
        "missing_features": int(missing_features or 0),
        "missing_d30": int(missing_d30 or 0),
        "old_missing_d30": int(old_missing_d30 or 0),
        "stale_sync": int(stale or 0),
        "old_unlabeled": int(unlabeled or 0),
    }


def experiment_integrity(cur):
    cur.execute("""
        SELECT COALESCE(status, 'unset'), COUNT(*)
        FROM recommendation_ledger
        GROUP BY 1 ORDER BY 2 DESC
    """)
    counts = {k: int(v) for k, v in cur.fetchall()}
    due = _one(cur, """
        SELECT COUNT(*) FROM recommendation_ledger
        WHERE status = 'applied'
          AND measure_at IS NOT NULL AND measure_at <= now()
    """)
    measured_no_outcome = _one(cur, """
        SELECT COUNT(*) FROM recommendation_ledger
        WHERE status = 'measured' AND outcome IS NULL
    """)
    return {
        "status": counts,
        "due_now": int(due or 0),
        "measured_without_outcome": int(measured_no_outcome or 0),
    }


def build_report(cur):
    return {
        "favorites": favorite_states(cur),
        "sales": sales_integrity(cur),
        "snapshots": snapshot_integrity(cur),
        "ledger": ledger_integrity(cur),
        "experiments": experiment_integrity(cur),
    }


def format_report(r):
    f = r["favorites"]
    s = r["sales"]
    h = r["snapshots"]
    l = r["ledger"]
    e = r["experiments"]

    lines = ["# 🧪 DATA INTEGRITY AUDIT", ""]
    lines.append("## Favorites")
    lines.append(
        f"• known **{f['positive']:,}** · NULL **{f['null']:,}** · "
        f"zero **{f['zero']:,}** · coverage **{f['coverage_pct']}%**"
    )
    lines.append(
        "• status: " + ", ".join(
            f"{k}={v:,}" for k, v in sorted(f["status"].items())
        )
    )
    lines.append("_Zero is ambiguous unless favorite_status is known._")
    lines.append("")

    lines.append("## Sales")
    lines.append(
        f"• rows **{s['total']:,}** · event-ID **{s['event_id']:,}** · "
        f"fingerprint fallback **{s['fallback_fingerprint']:,}**"
    )
    lines.append(
        f"• duplicate event IDs **{s['duplicate_event_ids']}** · "
        f"duplicate fallback fingerprints **{s['duplicate_fingerprints']}**"
    )
    lines.append("")

    lines.append("## Snapshots")
    lines.append(
        f"• rows **{h['rows']:,}** · items **{h['items']:,}** · "
        f"last 24h **{h['today']:,}** · last 7d **{h['last_7d']:,}**"
    )
    lines.append(
        f"• duplicate item-days **{h['duplicate_item_days']}**"
    )
    lines.append("")

    lines.append("## Launch ledger")
    lines.append(
        f"• rows **{l['total']}** · missing features **{l['missing_features']}** · "
        f"missing D30 favorites **{l['missing_d30']}**"
    )
    lines.append(
        f"• old launches missing D30 **{l['old_missing_d30']}** · "
        f"stale sync **{l['stale_sync']}** · old unlabeled **{l['old_unlabeled']}**"
    )
    lines.append("")

    lines.append("## Experiments")
    lines.append(
        "• status: " + ", ".join(
            f"{k}={v}" for k, v in sorted(e["status"].items())
        )
    )
    lines.append(
        f"• due now **{e['due_now']}** · measured without outcome "
        f"**{e['measured_without_outcome']}**"
    )
    lines.append("")
    lines.append("_Read-only report. Nothing is deleted automatically._")
    return "\n".join(lines)
