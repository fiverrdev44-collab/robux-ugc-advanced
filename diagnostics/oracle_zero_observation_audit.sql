-- VANTA 73 — ORACLE zero-observation audit (READ-ONLY)
--
-- Run on a replica/authorized read-only connection:
--   psql "$READONLY_DATABASE_URL" -X -v ON_ERROR_STOP=1 -P pager=off \
--        -A -F ' | ' -f diagnostics/oracle_zero_observation_audit.sql
--
-- No writes, no migrations, no Roblox API calls. This reports the counters the
-- worker already persists; it does not infer a cause from missing data.

\set ON_ERROR_STOP on
BEGIN READ ONLY;
SET LOCAL statement_timeout = '30s';
SET LOCAL lock_timeout = '5s';

\echo '=== 0. Objects ==='
SELECT to_regclass('public.trend_scan_runs') AS trend_scan_runs,
       to_regclass('public.trend_creator_cohorts') AS trend_creator_cohorts,
       to_regclass('public.trend_item_observations') AS trend_item_observations,
       to_regclass('public.tracked_creators') AS tracked_creators,
       current_setting('transaction_read_only') AS transaction_read_only;

\echo '=== 1. Recent ORACLE runs (persisted counters) ==='
SELECT scan_run_id, status, started_at, finished_at,
       creators_eligible, creators_scanned, creators_errored,
       items_discovered, items_in_window, observations_inserted,
       skipped_too_recent, skipped_rate_limited, skipped_unavailable,
       skipped_unknown_type
FROM trend_scan_runs
ORDER BY scan_run_id DESC
LIMIT 20;

\echo '=== 2. Recent run failure detail ==='
SELECT scan_run_id, status, truncated_creators, error_summary
FROM trend_scan_runs
ORDER BY scan_run_id DESC
LIMIT 20;

\echo '=== 3. Latest cohort creator/type provenance ==='
WITH latest AS (
    SELECT max(cohort_id) AS cohort_id FROM trend_creator_cohorts
)
SELECT c.creator_id,
       c.cohort_type,
       c.creator_type AS cohort_creator_type,
       t.creator_type AS tracked_creator_type,
       t.verified
FROM trend_creator_cohorts c
LEFT JOIN tracked_creators t ON t.creator_id = c.creator_id
WHERE c.cohort_id = (SELECT cohort_id FROM latest)
ORDER BY c.creator_id;

\echo '=== 4. Observation coverage for the latest cohort ==='
WITH latest AS (
    SELECT max(cohort_id) AS cohort_id FROM trend_creator_cohorts
),
cohort AS (
    SELECT creator_id FROM trend_creator_cohorts
    WHERE cohort_id = (SELECT cohort_id FROM latest)
)
SELECT count(DISTINCT o.creator_id) AS creators_with_observations,
       count(*) AS observation_rows,
       min(o.observed_at) AS first_observation,
       max(o.observed_at) AS last_observation
FROM trend_item_observations o
JOIN cohort c ON c.creator_id = o.creator_id;

ROLLBACK;
