"""trend_cohorts.py — Project ORACLE creator cohorts (Phase 1).

Additive subsystem. Selects ELITE (age-normalized matured performance),
EMERGING (genuine recent growth with sufficient history) and CONTROL (random,
not failure-biased) creators, then freezes the cohort for its period.
"""
from datetime import datetime, timedelta, timezone

from creator_identity import creator_key

COHORT_SIZE = {"ELITE": 50, "EMERGING": 25, "CONTROL": 25}
MIN_MATURED_ITEMS = 5
MIN_EMERGING_DAYS = 7
MIN_EMERGING_ITEMS = 3
MIN_CONTROL_ITEMS = 3


def cohort_key(period_start):
    return f"ORACLE-{period_start.strftime('%Y%m%d')}"


def _rows(cur, sql, params=None):
    try:
        cur.execute(sql) if params is None else cur.execute(sql, params)
        return cur.fetchall()
    except Exception as e:
        print(f"[trend_cohorts] query failed: {type(e).__name__}: {e}", flush=True)
        return []


def select_elite(cur, limit=COHORT_SIZE["ELITE"]):
    """Top typed creators by median favorites/day on matured items."""
    rows = _rows(cur, """
        SELECT i.creator_type, i.creator_id,
               percentile_cont(0.5) WITHIN GROUP (
                   ORDER BY i.favorite_count::float /
                   GREATEST(EXTRACT(EPOCH FROM (now() - i.created_at)) / 86400.0, 1)
               ) AS score,
               count(*) AS n
        FROM items i
        WHERE i.creator_id IS NOT NULL
          AND i.creator_type IN ('User', 'Group')
          AND i.created_at < now() - interval '30 days'
          AND coalesce(i.favorite_count, 0) > 0
        GROUP BY i.creator_type, i.creator_id
        HAVING count(*) >= %s
        ORDER BY score DESC, i.creator_type ASC, i.creator_id ASC
        LIMIT %s
    """, (MIN_MATURED_ITEMS, int(limit)))
    return [{"creator_type": r[0], "creator_id": r[1],
             "creator_key": creator_key(r[0], r[1]),
             "score": float(r[2] or 0),
             "reason": f"age-normalized favs/day over {r[3]} matured items"}
            for r in rows]


def select_emerging(cur, limit=COHORT_SIZE["EMERGING"], exclude=None):
    """Typed creators with genuine recent favorite growth and enough history."""
    exclude = list(exclude or [])
    rows = _rows(cur, """
        WITH growth AS (
            SELECT i.creator_type, i.creator_id, i.id,
                   (max(h.favorite_count) - min(h.favorite_count)) /
                   GREATEST(EXTRACT(EPOCH FROM
                       (max(h.snapshot_at) - min(h.snapshot_at))) / 86400.0, 1)
                       AS velocity,
                   count(DISTINCT date(h.snapshot_at)) AS days,
                   min(h.favorite_count) AS first_favs,
                   max(h.favorite_count) AS last_favs
            FROM items i
            JOIN item_history h ON h.item_id = i.id
            WHERE i.creator_id IS NOT NULL
              AND i.creator_type IN ('User', 'Group')
              AND h.favorite_count IS NOT NULL
              AND h.snapshot_at > now() - interval '14 days'
            GROUP BY i.creator_type, i.creator_id, i.id
            HAVING count(DISTINCT date(h.snapshot_at)) >= %s
               AND min(h.favorite_count) IS NOT NULL
        )
        SELECT creator_type, creator_id,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY velocity) AS score,
               count(*) AS n
        FROM growth
        WHERE velocity > 0
          AND (cardinality(%s::text[]) = 0
               OR (creator_type || ':' || creator_id) <> ALL(%s::text[]))
        GROUP BY creator_type, creator_id
        HAVING count(*) >= %s
        ORDER BY score DESC, creator_type ASC, creator_id ASC
        LIMIT %s
    """, (MIN_EMERGING_DAYS, exclude, exclude, MIN_EMERGING_ITEMS,
          int(limit)))
    return [{"creator_type": r[0], "creator_id": r[1],
             "creator_key": creator_key(r[0], r[1]),
             "score": float(r[2] or 0),
             "reason": f"recent favs/day over {r[3]} items with >= "
                       f"{MIN_EMERGING_DAYS}d history"}
            for r in rows]


def select_control(cur, limit=COHORT_SIZE["CONTROL"], exclude=None,
                   seed="oracle-v1"):
    """Deterministic random typed creators; not failure-biased."""
    exclude = list(exclude or [])
    rows = _rows(cur, """
        SELECT creator_type, creator_id, count(*) AS n
        FROM items
        WHERE creator_id IS NOT NULL
          AND creator_type IN ('User', 'Group')
          AND (cardinality(%s::text[]) = 0
               OR (creator_type || ':' || creator_id) <> ALL(%s::text[]))
        GROUP BY creator_type, creator_id
        HAVING count(*) >= %s
        ORDER BY md5(creator_type || ':' || creator_id::text || %s)
        LIMIT %s
    """, (exclude, exclude, MIN_CONTROL_ITEMS, seed, int(limit)))
    return [{"creator_type": r[0], "creator_id": r[1],
             "creator_key": creator_key(r[0], r[1]),
             "score": None,
             "reason": f"random eligible creator ({r[2]} items), seed={seed}"}
            for r in rows]


def build_cohorts(cur, period_start=None, period_end=None, seed="oracle-v1",
                  force=False):
    """Select and persist one frozen cohort set for the period."""
    now = datetime.now(timezone.utc)
    period_end = period_end or now
    period_start = period_start or (period_end - timedelta(days=90))
    cid = cohort_key(period_start)

    if not force:
        cur.execute("select count(*) from trend_creator_cohorts where cohort_id = %s",
                    (cid,))
        existing = cur.fetchone()
        if existing and int(existing[0] or 0) > 0:
            return {"cohort_id": cid, "frozen": True,
                    "message": "cohort already exists for this period"}

    elite = select_elite(cur)
    elite_ids = [r["creator_key"] for r in elite]
    emerging = select_emerging(cur, exclude=elite_ids)
    emerging_ids = elite_ids + [r["creator_key"] for r in emerging]
    control = select_control(cur, exclude=emerging_ids, seed=seed)

    inserted = 0
    try:
        for kind, rows in (("ELITE", elite), ("EMERGING", emerging),
                           ("CONTROL", control)):
            for r in rows:
                cur.execute("""
                    INSERT INTO trend_creator_cohorts
                      (cohort_id, creator_id, creator_type, creator_key,
                       cohort_type, selection_score, selection_reason,
                       cohort_period_start, cohort_period_end)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (cohort_id, creator_key) DO NOTHING
                """, (cid, r["creator_id"], r["creator_type"],
                      r["creator_key"], kind, r["score"], r["reason"],
                      period_start, period_end))
                inserted += cur.rowcount or 0
    except Exception as e:
        try:
            cur.connection.rollback()
        except Exception:
            pass
        return {"cohort_id": cid, "error": f"{type(e).__name__}: {e}",
                "frozen": False}
    try:
        cur.connection.commit()
    except Exception:
        pass
    return {"cohort_id": cid, "frozen": True, "inserted": inserted,
            "counts": {"ELITE": len(elite), "EMERGING": len(emerging),
                       "CONTROL": len(control)},
            "period": [str(period_start), str(period_end)]}
