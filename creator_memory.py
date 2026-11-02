"""creator_memory.py — Astra runs and algorithmic launch outcomes.

Stores what VANTA generated (concept, asset type, titles, chosen title) and
joins it to launch_ledger so the bot can answer whether a recommended title
actually earned favorites/sales versus the baseline. No external link tracking.
"""
SCHEMA = """
create table if not exists astra_runs (
    id bigserial primary key,
    item_id bigint,
    concept text,
    asset_type text,
    angles jsonb,
    titles jsonb,
    chosen_title text,
    preview_version text,
    created_at timestamptz default now()
);
create index if not exists idx_astra_runs_item on astra_runs (item_id);
"""


def ensure_schema(cur, conn=None):
    cur.execute(SCHEMA)
    if conn is not None:
        conn.commit()


def record_run(cur, concept, titles, chosen_title=None, asset_type=None,
               angles=None, item_id=None, preview_version=None):
    cur.execute("""
        insert into astra_runs
          (item_id, concept, asset_type, angles, titles, chosen_title,
           preview_version)
        values (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
        returning id
    """, (item_id, (concept or "")[:300], asset_type,
          str(angles or []), str(list(titles or [])[:5]),
          (chosen_title or "")[:200], (preview_version or "")[:120]))
    return cur.fetchone()[0]


def recent_runs(cur, item_id=None, limit=20):
    if item_id:
        cur.execute("""
            select id, item_id, concept, asset_type, angles, titles,
                   chosen_title, preview_version, created_at
            from astra_runs where item_id = %s
            order by created_at desc limit %s
        """, (item_id, int(limit)))
    else:
        cur.execute("""
            select id, item_id, concept, asset_type, angles, titles,
                   chosen_title, preview_version, created_at
            from astra_runs order by created_at desc limit %s
        """, (int(limit),))
    return [{
        "id": r[0], "item_id": r[1], "concept": r[2], "asset_type": r[3],
        "angles": r[4], "titles": r[5], "chosen_title": r[6],
        "preview_version": r[7], "created_at": str(r[8]),
    } for r in cur.fetchall()]


def algorithm_outcome(cur, run_id):
    """Answer: recommendation X generated; when launched, it achieved Y favs."""
    cur.execute("""
        select id, item_id, chosen_title, concept, created_at
        from astra_runs where id = %s
    """, (run_id,))
    run = cur.fetchone()
    if not run:
        return {"found": False, "run_id": run_id}
    rid, item_id, title, concept, created = run
    ledger = None
    if item_id:
        cur.execute("""
            select item_id, title, favs_d7, favs_d30, units_d7, units_d30,
                   revenue_d7, revenue_d30, label_beat_median
            from launch_ledger where item_id = %s
        """, (item_id,))
        ledger = cur.fetchone()
    if not ledger and title:
        cur.execute("""
            select item_id, title, favs_d7, favs_d30, units_d7, units_d30,
                   revenue_d7, revenue_d30, label_beat_median
            from launch_ledger
            where lower(title) = lower(%s)
            order by launched_at desc limit 1
        """, (title,))
        ledger = cur.fetchone()
    if not ledger:
        return {"found": True, "run_id": rid, "item_id": item_id,
                "title": title or concept, "launched": False,
                "message": (f"Recommendation {rid} ({title or concept}) was "
                            f"generated. No launch is tracked for it yet.")}
    (l_item, l_title, d7, d30, u7, u30, r7, r30, beat) = ledger
    favs = d30 if d30 is not None else d7
    return {
        "found": True, "launched": True, "run_id": rid, "item_id": l_item,
        "title": title or l_title, "launch_title": l_title,
        "favs_d7": d7, "favs_d30": d30, "units_d30": u30,
        "revenue_d30": r30, "beat_median": beat,
        "message": (f"Recommendation {rid} ({title or l_title}) was generated. "
                    f"When launched, it achieved {favs if favs is not None else 'no'} "
                    f"favorites"
                    + (f" and {u30} units (D30)" if u30 is not None else "")
                    + "."),
    }


def outcome_summary(cur, item_id=None, limit=10):
    where = ("measured_at is not null and outcome is not null "
             "and coalesce(maturity,'pending') in ('mature','partial')")
    if item_id:
        cur.execute(f"""select id, item_id, maturity, outcome, measured_at
                        from recommendation_ledger
                        where {where} and item_id = %s
                        order by measured_at desc limit %s""",
                    (item_id, int(limit)))
    else:
        cur.execute(f"""select id, item_id, maturity, outcome, measured_at
                        from recommendation_ledger
                        where {where}
                        order by measured_at desc limit %s""",
                    (int(limit),))
    return [{"rec_id": r[0], "item_id": r[1], "maturity": r[2],
             "outcome": r[3], "measured_at": str(r[4])}
            for r in cur.fetchall()]
