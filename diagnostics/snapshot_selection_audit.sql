-- VANTA 73 — snapshot selection starvation audit (READ-ONLY)
--
-- Run on a replica/authorized read-only connection:
--   psql "$READONLY_DATABASE_URL" -X -v ON_ERROR_STOP=1 -P pager=off \
--        -A -F ' | ' -v snapshot_limit=1500 -f diagnostics/snapshot_selection_audit.sql
--
-- Coverage is measured from stored item_history rows only. snapshot.py's
-- "inserted" log counter counts attempted inserts even when ON CONFLICT DO
-- NOTHING discards them, so it is NOT evidence. No writes or API calls.

\set ON_ERROR_STOP on
\if :{?snapshot_limit}
\else
\set snapshot_limit 1500
\endif

BEGIN READ ONLY;
SET LOCAL statement_timeout = '30s';
SET LOCAL lock_timeout = '5s';

\echo '=== 0. Objects and index ==='
SELECT to_regclass('public.items') AS items,
       to_regclass('public.item_history') AS item_history,
       to_regclass('public.launch_ledger') AS launch_ledger,
       to_regclass('public.idx_item_history_daily')
           AS idx_item_history_daily,
       COALESCE((
           SELECT i.indisunique FROM pg_index i
           WHERE i.indexrelid = to_regclass('public.idx_item_history_daily')
       ), false) AS idx_item_history_daily_is_unique,
       current_setting('transaction_read_only') AS transaction_read_only;

\echo '=== 1. Stored snapshot coverage (all history) ==='
SELECT count(*) AS history_rows,
       count(DISTINCT item_id) AS items_with_history,
       min(snapshot_at) AS first_snapshot,
       max(snapshot_at) AS last_snapshot,
       now() - max(snapshot_at) AS age_of_last_snapshot
FROM item_history;

\echo '=== 2. Recent items: stored snapshots only ==='
WITH recent AS (
    SELECT id FROM items WHERE created_at >= now() - interval '48 hours'
),
snap AS (
    SELECT item_id, count(*) AS n
    FROM item_history
    WHERE item_id IN (SELECT id FROM recent)
    GROUP BY item_id
)
SELECT (SELECT count(*) FROM recent) AS recent_items,
       count(*) FILTER (WHERE s.item_id IS NULL) AS no_snapshots,
       count(*) FILTER (WHERE s.n = 1) AS one_snapshot,
       count(*) FILTER (WHERE s.n >= 2) AS two_plus_snapshots
FROM recent r
LEFT JOIN snap s ON s.item_id = r.id;

\echo '=== 3. Snapshot cadence by date (last 14 days, stored rows) ==='
SELECT (snapshot_at AT TIME ZONE 'UTC')::date AS snapshot_date,
       count(*) AS snapshot_rows,
       count(DISTINCT item_id) AS items,
       min(snapshot_at) AS first_at,
       max(snapshot_at) AS last_at
FROM item_history
WHERE snapshot_at >= now() - interval '14 days'
GROUP BY 1
ORDER BY 1 DESC;

\echo '=== 4. Selection rank: exact snapshot.py ordering ==='
-- Mirrors snapshot.py: tier < 99, tier ASC,
-- tier=0 launch-ledger -> recent -> other, then last_updated_at ASC NULLS FIRST.
WITH ranked AS (
    SELECT i.id,
           i.created_at,
           COALESCE(i.fetched_at, i.updated_at) AS last_updated_at,
           CASE
               WHEN i.id IN (SELECT item_id FROM launch_ledger)
                 OR i.created_at > now() - interval '3 days'
                 OR (COALESCE(i.favorite_count, 0) > 1000
                     AND COALESCE(i.fetched_at, i.updated_at)
                         < now() - interval '2 hours')
                   THEN 0
               WHEN (COALESCE(i.favorite_count, 0) BETWEEN 100 AND 1000
                     AND COALESCE(i.fetched_at, i.updated_at)
                         < now() - interval '8 hours')
                 OR (i.created_at > now() - interval '14 days'
                     AND COALESCE(i.fetched_at, i.updated_at)
                         < now() - interval '6 hours')
                   THEN 1
               WHEN COALESCE(i.fetched_at, i.updated_at)
                    < now() - interval '7 days'
                   THEN 2
               ELSE 99
           END AS tier,
           CASE
               WHEN i.id IN (SELECT item_id FROM launch_ledger) THEN 0
               WHEN i.created_at > now() - interval '3 days' THEN 1
               ELSE 2
           END AS tier0_priority
    FROM items i
),
eligible AS (
    SELECT * FROM ranked WHERE tier < 99
),
ordered AS (
    SELECT *,
           row_number() OVER (
               ORDER BY tier ASC,
                        CASE WHEN tier = 0 THEN tier0_priority ELSE 2 END ASC,
                        last_updated_at ASC NULLS FIRST,
                        id ASC
           ) AS selection_rank
    FROM eligible
)
SELECT :snapshot_limit AS snapshot_limit,
       count(*) AS eligible_total,
       count(*) FILTER (WHERE tier = 0) AS tier0_total,
       count(*) FILTER (WHERE tier = 0 AND last_updated_at IS NULL)
           AS tier0_null_updated,
       count(*) FILTER (WHERE created_at >= now() - interval '48 hours')
           AS recent_48h,
       count(*) FILTER (WHERE created_at >= now() - interval '48 hours'
                         AND selection_rank <= :snapshot_limit)
           AS recent_within_limit,
       min(selection_rank) FILTER (
           WHERE created_at >= now() - interval '48 hours') AS best_recent_rank,
       max(selection_rank) FILTER (
           WHERE created_at >= now() - interval '48 hours') AS worst_recent_rank
FROM ordered;

\echo '=== 5. Recent items displaced by the limit (sample) ==='
WITH ranked AS (
    SELECT i.id, i.created_at,
           COALESCE(i.fetched_at, i.updated_at) AS last_updated_at,
           CASE
               WHEN i.id IN (SELECT item_id FROM launch_ledger)
                 OR i.created_at > now() - interval '3 days'
                 OR (COALESCE(i.favorite_count, 0) > 1000
                     AND COALESCE(i.fetched_at, i.updated_at)
                         < now() - interval '2 hours') THEN 0
               WHEN (COALESCE(i.favorite_count, 0) BETWEEN 100 AND 1000
                     AND COALESCE(i.fetched_at, i.updated_at)
                         < now() - interval '8 hours')
                 OR (i.created_at > now() - interval '14 days'
                     AND COALESCE(i.fetched_at, i.updated_at)
                         < now() - interval '6 hours') THEN 1
               WHEN COALESCE(i.fetched_at, i.updated_at)
                    < now() - interval '7 days' THEN 2
               ELSE 99
           END AS tier,
           CASE
               WHEN i.id IN (SELECT item_id FROM launch_ledger) THEN 0
               WHEN i.created_at > now() - interval '3 days' THEN 1
               ELSE 2
           END AS tier0_priority
    FROM items i
),
ordered AS (
    SELECT *,
           row_number() OVER (
               ORDER BY tier ASC,
                        CASE WHEN tier = 0 THEN tier0_priority ELSE 2 END ASC,
                        last_updated_at ASC NULLS FIRST,
                        id ASC
           ) AS selection_rank
    FROM ranked
    WHERE tier < 99
)
SELECT id, created_at, last_updated_at, tier, selection_rank,
       CASE WHEN selection_rank > :snapshot_limit
            THEN 'displaced by limit' ELSE 'selected' END AS status
FROM ordered
WHERE created_at >= now() - interval '48 hours'
ORDER BY selection_rank
LIMIT 50;

\echo '=== 6. Recent ingestion/fetch state (not snapshot proof) ==='
SELECT count(*) AS recent_items,
       count(*) FILTER (WHERE fetched_at IS NULL) AS fetched_at_null,
       count(*) FILTER (WHERE favorite_count IS NULL) AS favorite_count_null,
       min(fetched_at) AS earliest_fetched_at,
       max(fetched_at) AS latest_fetched_at
FROM items
WHERE created_at >= now() - interval '48 hours';

ROLLBACK;
