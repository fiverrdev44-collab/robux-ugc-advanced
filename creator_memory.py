"""creator_memory.py — creator-specific Astra runs and link traffic.

Stores the angles, titles and preview versions that were actually tested, and
joins Marketplace Links traffic/outcomes. It never stores heuristic scores as
training labels; only recorded sales/ledger evidence is outcome data.
"""
SCHEMA = """
create table if not exists astra_runs (
    id bigserial primary key,
    item_id bigint,
    concept text,
    angles jsonb,
    titles jsonb,
    preview_version text,
    link_id text,
    created_at timestamptz default now()
);
create index if not exists idx_astra_runs_item on astra_runs (item_id);
create index if not exists idx_astra_runs_link on astra_runs (link_id);
"""


def ensure_schema(cur, conn=None):
    cur.execute(SCHEMA)
    if conn is not None:
        conn.commit()


def record_run(cur, item_id, concept, angles, titles,
               preview_version=None, link_id=None):
    cur.execute("""
        insert into astra_runs
          (item_id, concept, angles, titles, preview_version, link_id)
        values (%s, %s, %s::jsonb, %s::jsonb, %s, %s)
        returning id
    """, (item_id, (concept or "")[:300], str(angles), str(titles),
          (preview_version or "")[:120], link_id))
    return cur.fetchone()[0]


def recent_runs(cur, item_id=None, limit=20):
    if item_id:
        cur.execute("""
            select id, item_id, concept, angles, titles, preview_version,
                   link_id, created_at
            from astra_runs where item_id = %s
            order by created_at desc limit %s
        """, (item_id, int(limit)))
    else:
        cur.execute("""
            select id, item_id, concept, angles, titles, preview_version,
                   link_id, created_at
            from astra_runs order by created_at desc limit %s
        """, (int(limit),))
    return [{
        "id": r[0], "item_id": r[1], "concept": r[2], "angles": r[3],
        "titles": r[4], "preview_version": r[5], "link_id": r[6],
        "created_at": str(r[7]),
    } for r in cur.fetchall()]


def outcome_summary(cur, item_id=None, limit=10):
    """Observed outcomes only (measured recommendation ledger rows)."""
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
