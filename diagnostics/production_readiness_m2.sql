-- VANTA 73 — M2 production readiness diagnostics (READ-ONLY)
--
-- Run against an authorized replica where possible:
--   psql "$READONLY_DATABASE_URL" -X -v ON_ERROR_STOP=1 -P pager=off \
--        -A -F ' | ' -f diagnostics/production_readiness_m2.sql
--
-- This script performs SELECTs only. It opens a READ ONLY transaction, sets a
-- statement timeout, and rolls back. It does not create temp tables, migrate,
-- backfill, or write data. If it errors, do not "fix" it by removing the read
-- only guard: inspect the error first.

\set ON_ERROR_STOP on
BEGIN READ ONLY;
SET LOCAL statement_timeout = '30s';
SET LOCAL lock_timeout = '5s';

\echo '=== 0. Environment ==='
SELECT current_database() AS database,
       current_user AS db_user,
       inet_server_addr() AS server_addr,
       inet_server_port() AS server_port,
       current_setting('server_version') AS server_version,
       current_setting('TimeZone') AS session_timezone,
       current_setting('transaction_read_only') AS transaction_read_only,
       pg_is_in_recovery() AS is_replica,
       now() AS observed_at;

\echo '=== 1. Required objects and columns ==='
SELECT
    (to_regclass('public.items') IS NOT NULL) AS has_items,
    (to_regclass('public.item_history') IS NOT NULL) AS has_item_history,
    (to_regclass('public.tracked_creators') IS NOT NULL) AS has_tracked_creators,
    (to_regclass('public.creator_registry') IS NOT NULL) AS has_creator_registry,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'items'
          AND column_name = 'creator_type'
    ) AS items_creator_type_exists,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'items'
          AND column_name = 'creator_id'
    ) AS items_creator_id_exists,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'items'
          AND column_name = 'creator_verified'
    ) AS items_creator_verified_exists
\gset

\echo items=:has_items item_history=:has_item_history tracked_creators=:has_tracked_creators creator_registry=:has_creator_registry
\echo items.creator_type=:items_creator_type_exists items.creator_id=:items_creator_id_exists items.creator_verified=:items_creator_verified_exists

\echo '=== 2. Relevant indexes ==='
SELECT schemaname, tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('items', 'item_history', 'creator_registry')
ORDER BY tablename, indexname;

\echo '--- 2b. Daily snapshot uniqueness index (checked, not assumed) ---'
SELECT to_regclass('public.idx_item_history_daily') IS NOT NULL
           AS idx_item_history_daily_exists,
       COALESCE((
           SELECT i.indisunique
           FROM pg_index i
           WHERE i.indexrelid = to_regclass('public.idx_item_history_daily')
       ), false) AS idx_item_history_daily_is_unique,
       pg_get_indexdef(to_regclass('public.idx_item_history_daily'))
           AS idx_item_history_daily_definition;

\echo '--- 2c. Any other unique index covering item_history(item_id, date) ---'
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename = 'item_history'
  AND indexdef ILIKE '%UNIQUE%'
ORDER BY indexname;

\echo '=== 3. Stable creator-ID coverage (items) ==='
SELECT count(*) AS items_total,
       count(*) FILTER (WHERE creator_id IS NOT NULL) AS items_with_creator_id,
       count(*) FILTER (WHERE creator_id IS NULL) AS items_missing_creator_id,
       count(DISTINCT creator_id) FILTER (WHERE creator_id IS NOT NULL)
           AS unique_numeric_creator_ids,
       count(*) FILTER (WHERE creator_id IS NOT NULL AND created_at IS NULL)
           AS items_with_id_missing_created_at,
       count(*) FILTER (WHERE creator_id IS NOT NULL
                         AND created_at >= now() - interval '48 hours')
           AS items_with_id_created_48h
FROM items;

\echo '=== 4. Known versus unknown creator type ==='
\if :items_creator_type_exists
SELECT COALESCE(NULLIF(creator_type, ''), 'unknown') AS item_creator_type,
       count(*) AS items,
       count(DISTINCT creator_id) AS numeric_creator_ids
FROM items
WHERE creator_id IS NOT NULL
GROUP BY 1
ORDER BY items DESC;

WITH item_rows AS (
    SELECT i.id,
           i.creator_id,
           NULLIF(i.creator_type, '') AS explicit_type,
           lower(i.creator_name) AS item_name
    FROM items i
    WHERE i.creator_id IS NOT NULL
),
tracked AS (
    SELECT creator_id, creator_type, lower(creator_name) AS tracked_name
    FROM tracked_creators
    WHERE creator_id IS NOT NULL AND creator_type IS NOT NULL
),
tracked_by_id AS (
    SELECT creator_id, count(DISTINCT creator_type) AS type_count
    FROM tracked
    GROUP BY creator_id
),
name_matched AS (
    SELECT DISTINCT it.id
    FROM item_rows it
    JOIN tracked t
      ON t.creator_id = it.creator_id
     AND t.tracked_name = it.item_name
)
SELECT count(*) AS items,
       count(*) FILTER (WHERE r.explicit_type IS NOT NULL)
           AS explicit_item_type,
       count(*) FILTER (WHERE r.explicit_type IS NULL
                         AND COALESCE(tb.type_count, 0) = 1
                         AND nm.id IS NOT NULL)
           AS safe_tracked_name_match,
       count(*) FILTER (WHERE r.explicit_type IS NULL
                         AND COALESCE(tb.type_count, 0) > 1)
           AS ambiguous_multiple_tracked_types,
       count(*) FILTER (WHERE r.explicit_type IS NULL
                         AND COALESCE(tb.type_count, 0) = 0)
           AS unknown_no_tracked_match,
       count(*) FILTER (WHERE r.explicit_type IS NULL
                         AND COALESCE(tb.type_count, 0) = 1
                         AND nm.id IS NULL)
           AS unknown_id_only_name_mismatch
FROM item_rows r
LEFT JOIN tracked_by_id tb ON tb.creator_id = r.creator_id
LEFT JOIN name_matched nm ON nm.id = r.id;
\else
\echo 'items.creator_type is MISSING: M2 migration has not been applied.'
WITH item_rows AS (
    SELECT i.id, i.creator_id, lower(i.creator_name) AS item_name
    FROM items i
    WHERE i.creator_id IS NOT NULL
),
tracked AS (
    SELECT creator_id, creator_type, lower(creator_name) AS tracked_name
    FROM tracked_creators
    WHERE creator_id IS NOT NULL AND creator_type IS NOT NULL
),
tracked_by_id AS (
    SELECT creator_id, count(DISTINCT creator_type) AS type_count
    FROM tracked
    GROUP BY creator_id
),
name_matched AS (
    SELECT DISTINCT it.id
    FROM item_rows it
    JOIN tracked t
      ON t.creator_id = it.creator_id
     AND t.tracked_name = it.item_name
)
SELECT count(*) AS items,
       count(*) FILTER (WHERE COALESCE(tb.type_count, 0) = 1
                         AND nm.id IS NOT NULL)
           AS resolvable_by_tracked_name_only,
       count(*) FILTER (WHERE COALESCE(tb.type_count, 0) > 1)
           AS ambiguous_multiple_tracked_types,
       count(*) FILTER (WHERE COALESCE(tb.type_count, 0) = 0)
           AS unknown_no_tracked_match
FROM item_rows r
LEFT JOIN tracked_by_id tb ON tb.creator_id = r.creator_id
LEFT JOIN name_matched nm ON nm.id = r.id;
\endif

\echo '=== 5. Verified / nonverified / unknown coverage (items) ==='
\if :items_creator_verified_exists
SELECT count(*) FILTER (WHERE creator_verified IS TRUE) AS verified_items,
       count(*) FILTER (WHERE creator_verified IS FALSE) AS nonverified_items,
       count(*) FILTER (WHERE creator_verified IS NULL) AS unknown_items
FROM items
WHERE creator_id IS NOT NULL;
\else
\echo 'items.creator_verified is missing; verification coverage is unknown.'
\endif

\echo '=== 6. creator_registry presence, counts, provenance ==='
\if :has_creator_registry
SELECT count(*) AS registry_rows FROM public.creator_registry;

SELECT creator_type, count(*) AS creators
FROM public.creator_registry
GROUP BY 1
ORDER BY creators DESC;

SELECT verification_status, verification_provenance, count(*) AS creators
FROM public.creator_registry
GROUP BY 1, 2
ORDER BY creators DESC;

SELECT COALESCE(type_provenance, 'missing') AS type_provenance,
       count(*) AS creators
FROM public.creator_registry
GROUP BY 1
ORDER BY creators DESC;

SELECT count(*) FILTER (WHERE type_provenance IS NULL
                           OR type_provenance IN ('', 'missing'))
           AS creators_missing_type_provenance,
       count(*) FILTER (WHERE verification_status = 'unknown')
           AS creators_unknown_verification,
       count(*) FILTER (WHERE verification_status = 'verified')
           AS creators_verified,
       count(*) FILTER (WHERE verification_status = 'nonverified')
           AS creators_nonverified,
       count(*) FILTER (WHERE verification_provenance IN ('', 'missing'))
           AS creators_missing_verification_provenance,
       count(*) FILTER (WHERE display_name IS NULL) AS creators_missing_display_name
FROM public.creator_registry;

\echo '--- 6b. previous_names hygiene (NULL display names, current name residue) ---'
SELECT count(*) FILTER (WHERE current_name_in_previous) AS current_name_in_previous_names,
       count(*) FILTER (WHERE non_array_previous_names) AS non_array_previous_names,
       count(*) FILTER (WHERE duplicate_previous_names) AS duplicate_previous_names
FROM (
    SELECT display_name,
           previous_names,
           CASE
               WHEN jsonb_typeof(previous_names) = 'array'
                AND display_name IS NOT NULL
                   THEN previous_names @> jsonb_build_array(display_name)
               ELSE false
           END AS current_name_in_previous,
           jsonb_typeof(previous_names) IS DISTINCT FROM 'array'
               AS non_array_previous_names,
           CASE
               WHEN jsonb_typeof(previous_names) = 'array'
                   THEN jsonb_array_length(previous_names) <>
                        (SELECT count(DISTINCT v)
                         FROM jsonb_array_elements_text(previous_names) v)
               ELSE false
           END AS duplicate_previous_names
    FROM public.creator_registry
) x;

SELECT creator_type, count(*) AS creators,
       sum(item_count) AS registry_item_count,
       min(last_seen) AS earliest_last_seen,
       max(last_seen) AS latest_last_seen
FROM public.creator_registry
GROUP BY creator_type
ORDER BY creators DESC;
\else
\echo 'creator_registry is MISSING. Registry-dependent M3 evidence is unavailable.'
\endif

\echo '=== 7. User/Group numeric-ID collision audit ==='
\if :has_creator_registry
\echo '--- 7a. Same numeric ID represented under more than one type (expected separate rows) ---'
SELECT creator_id,
       count(*) AS type_rows,
       array_agg(creator_type ORDER BY creator_type) AS types,
       array_agg(display_name ORDER BY creator_type) AS names
FROM public.creator_registry
GROUP BY creator_id
HAVING count(*) > 1
ORDER BY creator_id
LIMIT 200;

\echo '--- 7b. Same display name under different composite keys (must not be merged) ---'
SELECT lower(display_name) AS display_name,
       count(*) AS composite_keys,
       array_agg(creator_type || ':' || creator_id
                 ORDER BY creator_type, creator_id) AS keys
FROM public.creator_registry
WHERE display_name IS NOT NULL AND display_name <> ''
GROUP BY 1
HAVING count(*) > 1
ORDER BY composite_keys DESC, display_name
LIMIT 100;

\echo '--- 7c. Unknown-type registry rows whose numeric ID is known in tracked_creators ---'
\if :has_tracked_creators
SELECT r.creator_type, r.creator_id, r.display_name, t.types
FROM public.creator_registry r
JOIN (
    SELECT creator_id, array_agg(DISTINCT creator_type) AS types
    FROM public.tracked_creators
    WHERE creator_type IS NOT NULL
    GROUP BY creator_id
) t USING (creator_id)
WHERE r.creator_type = 'unknown'
ORDER BY r.creator_id
LIMIT 200;
\else
\echo 'tracked_creators is missing; cannot run 7c.'
\endif
\else
\echo 'creator_registry is missing; registry collision checks unavailable.'
\endif

\if :has_tracked_creators
\echo '--- 7d. Numeric IDs tracked as BOTH User and Group (ambiguous; must stay unknown unless corroborated) ---'
SELECT creator_id,
       array_agg(DISTINCT creator_type) AS types,
       count(DISTINCT lower(creator_name)) AS distinct_names
FROM public.tracked_creators
WHERE creator_type IN ('User', 'Group')
GROUP BY creator_id
HAVING count(DISTINCT creator_type) > 1
ORDER BY creator_id
LIMIT 200;
\else
\echo 'tracked_creators is missing; cannot run 7d.'
\endif

\echo '=== 8. Snapshot coverage (actual stored item_history rows) ==='
-- Coverage is measured from stored item_history rows only. snapshot.py's
-- "inserted" log counter is incremented for attempted inserts even when
-- ON CONFLICT DO NOTHING discards the row, so that counter is NOT evidence.
SELECT count(*) AS history_rows,
       count(DISTINCT item_id) AS items_with_history,
       min(snapshot_at) AS first_snapshot,
       max(snapshot_at) AS last_snapshot,
       now() - max(snapshot_at) AS age_of_last_snapshot
FROM item_history;

WITH recent AS (
    SELECT id FROM items WHERE created_at >= now() - interval '48 hours'
),
snap AS (
    SELECT item_id, count(*) AS n,
           min(snapshot_at) AS first_at, max(snapshot_at) AS last_at
    FROM item_history
    WHERE snapshot_at >= now() - interval '48 hours'
      AND favorite_count IS NOT NULL
    GROUP BY item_id
)
SELECT (SELECT count(*) FROM recent) AS recent_items,
       count(*) FILTER (WHERE s.item_id IS NULL) AS no_snapshots,
       count(*) FILTER (WHERE s.n = 1) AS one_snapshot,
       count(*) FILTER (WHERE s.n >= 2) AS two_plus_snapshots,
       count(*) FILTER (WHERE s.n >= 2
                         AND extract(epoch FROM (s.last_at - s.first_at)) >= 3600)
           AS valid_growth_items
FROM recent r
LEFT JOIN snap s ON s.item_id = r.id;

\echo '--- 8b. Observed snapshot cadence by date (last 14 days) ---'
SELECT snapshot_at::date AS snapshot_date,
       count(*) AS snapshot_rows,
       count(DISTINCT item_id) AS items,
       min(snapshot_at) AS first_at,
       max(snapshot_at) AS last_at
FROM item_history
WHERE snapshot_at >= now() - interval '14 days'
GROUP BY 1
ORDER BY 1 DESC;

\echo '--- 8c. Duplicate item/date snapshots in stored data (last 14 days) ---'
SELECT count(*) AS item_date_groups_with_duplicates
FROM (
    SELECT item_id, snapshot_at::date AS snapshot_date, count(*) AS n
    FROM item_history
    WHERE snapshot_at >= now() - interval '14 days'
    GROUP BY 1, 2
    HAVING count(*) > 1
) x;

\echo '=== 9. !golden_hour 48-hour velocity diagnostics (stored rows only) ==='
-- Mirrors the command's stored-record conditions. It does not read the
-- snapshot job's attempted-insert log counter and makes no API calls.
WITH recent AS (
    SELECT id, name, created_at
    FROM items
    WHERE created_at >= now() - interval '48 hours'
),
agg AS (
    SELECT r.id, r.name, r.created_at,
           count(h.snapshot_at) AS snapshot_count,
           min(h.snapshot_at) AS first_at,
           max(h.snapshot_at) AS last_at,
           extract(epoch FROM (max(h.snapshot_at) - min(h.snapshot_at)))
               / 3600.0 AS span_hours
    FROM recent r
    LEFT JOIN item_history h
      ON h.item_id = r.id
     AND h.snapshot_at >= now() - interval '48 hours'
     AND h.favorite_count IS NOT NULL
    GROUP BY r.id, r.name, r.created_at
)
SELECT count(*) AS recent_items,
       count(*) FILTER (WHERE snapshot_count = 0) AS no_snapshots,
       count(*) FILTER (WHERE snapshot_count = 1) AS one_snapshot,
       count(*) FILTER (WHERE snapshot_count >= 2
                         AND span_hours >= 1.0) AS velocity_eligible,
       count(*) FILTER (WHERE snapshot_count >= 2
                         AND span_hours < 1.0) AS span_too_short
FROM agg;

\echo '--- 9b. Up to 50 recent items that cannot produce velocity, with reason ---'
WITH recent AS (
    SELECT id, name, created_at
    FROM items
    WHERE created_at >= now() - interval '48 hours'
),
agg AS (
    SELECT r.id, r.name, r.created_at,
           count(h.snapshot_at) AS snapshot_count,
           min(h.snapshot_at) AS first_at,
           max(h.snapshot_at) AS last_at,
           extract(epoch FROM (max(h.snapshot_at) - min(h.snapshot_at)))
               / 3600.0 AS span_hours
    FROM recent r
    LEFT JOIN item_history h
      ON h.item_id = r.id
     AND h.snapshot_at >= now() - interval '48 hours'
     AND h.favorite_count IS NOT NULL
    GROUP BY r.id, r.name, r.created_at
)
SELECT id, name, created_at,
       round((extract(epoch FROM (now() - created_at)) / 3600.0)::numeric, 2)
           AS age_hours,
       snapshot_count, round(span_hours::numeric, 2) AS span_hours,
       CASE
           WHEN snapshot_count = 0 THEN 'no snapshots in 48h window'
           WHEN snapshot_count = 1 THEN 'only one snapshot in 48h window'
           WHEN span_hours < 1.0 THEN 'snapshot span under 1 hour'
           ELSE 'eligible (unexpected in this list)'
       END AS reason
FROM agg
WHERE NOT (snapshot_count >= 2 AND span_hours >= 1.0)
ORDER BY created_at DESC
LIMIT 50;

\echo '--- 9c. items.created_at sanity (recent population definition) ---'
SELECT count(*) AS items_total,
       count(*) FILTER (WHERE created_at IS NULL) AS created_at_null,
       count(*) FILTER (WHERE created_at > now()) AS created_at_in_future,
       count(*) FILTER (WHERE created_at >= now() - interval '24 hours')
           AS created_last_24h,
       count(*) FILTER (WHERE created_at >= now() - interval '48 hours')
           AS created_last_48h,
       min(created_at) AS oldest_created_at,
       max(created_at) AS newest_created_at
FROM items;

\echo '--- 9d. History rows older than their item creation timestamp (clock/timezone anomaly) ---'
SELECT count(*) AS snapshots_before_item_creation
FROM item_history h
JOIN items i ON i.id = h.item_id
WHERE h.snapshot_at >= now() - interval '7 days'
  AND i.created_at IS NOT NULL
  AND h.snapshot_at < i.created_at;

\echo '=== 10. Optional trend/observation tables (guarded) ==='
SELECT (to_regclass('public.trend_item_observations') IS NOT NULL)
           AS has_trend_item_observations,
       (to_regclass('public.trend_scan_runs') IS NOT NULL)
           AS has_trend_scan_runs
\gset

\if :has_trend_item_observations
SELECT date_trunc('hour', observed_at) AS hour,
       count(*) AS observations,
       count(DISTINCT item_id) AS items
FROM public.trend_item_observations
WHERE observed_at >= now() - interval '14 days'
GROUP BY 1
ORDER BY 1 DESC
LIMIT 200;
\else
\echo 'trend_item_observations is missing.'
\endif

\if :has_trend_scan_runs
SELECT scan_run_id, status, started_at, finished_at,
       creators_eligible, observations_inserted
FROM public.trend_scan_runs
ORDER BY scan_run_id DESC
LIMIT 20;
\else
\echo 'trend_scan_runs is missing.'
\endif

ROLLBACK;
