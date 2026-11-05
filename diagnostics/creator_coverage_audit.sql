-- VANTA 73 — Creator coverage audit (READ-ONLY)
-- Run manually on a replica/staging DB:
--   psql "$DATABASE_URL" -X -P pager=off -A -F ' | ' \
--        -f diagnostics/creator_coverage_audit.sql
-- No writes, no temp tables, no production mutation.
-- If no DATABASE_URL is available, these diagnostics remain unexecuted and
-- coverage must not be estimated.

\echo --- 1. items with / without stable creator IDs ---
SELECT count(*) AS items_total,
       count(*) FILTER (WHERE creator_id IS NOT NULL) AS items_with_creator_id,
       count(*) FILTER (WHERE creator_id IS NULL) AS items_missing_creator_id,
       count(DISTINCT creator_id) FILTER (WHERE creator_id IS NOT NULL)
           AS unique_creator_ids
FROM items;

\echo --- 2. known creator types (tracked_creators) ---
SELECT COALESCE(creator_type, 'unknown') AS creator_type,
       count(*) AS creators
FROM tracked_creators
GROUP BY 1
ORDER BY creators DESC;

\echo --- 3. items with known vs unknown creator type ---
SELECT count(*) FILTER (WHERE t.creator_type IS NOT NULL)
           AS items_with_known_type,
       count(*) FILTER (WHERE t.creator_type IS NULL)
           AS items_with_unknown_type
FROM items i
LEFT JOIN LATERAL (
    SELECT t2.creator_type
    FROM tracked_creators t2
    WHERE t2.creator_id = i.creator_id
      AND t2.creator_type IS NOT NULL
    ORDER BY t2.creator_type
    LIMIT 1
) t ON true
WHERE i.creator_id IS NOT NULL;

\echo --- 4. verification coverage (NULL = unknown, not nonverified) ---
SELECT count(*) FILTER (WHERE creator_verified IS TRUE) AS verified_items,
       count(*) FILTER (WHERE creator_verified IS FALSE) AS nonverified_items,
       count(*) FILTER (WHERE creator_verified IS NULL) AS unknown_items
FROM items
WHERE creator_id IS NOT NULL;

\echo --- 5. creator/category distribution (top 50) ---
SELECT COALESCE(t.creator_type, 'unknown') AS creator_type,
       i.asset_type_id,
       count(*) AS items,
       count(DISTINCT i.creator_id) AS creators
FROM items i
LEFT JOIN LATERAL (
    SELECT t2.creator_type
    FROM tracked_creators t2
    WHERE t2.creator_id = i.creator_id
      AND t2.creator_type IS NOT NULL
    ORDER BY t2.creator_type
    LIMIT 1
) t ON true
WHERE i.creator_id IS NOT NULL
GROUP BY 1, 2
ORDER BY items DESC
LIMIT 50;

\echo --- 6. snapshot coverage (all items) ---
WITH snap AS (
    SELECT item_id, count(*) AS n,
           min(snapshot_at) AS first_at, max(snapshot_at) AS last_at
    FROM item_history
    WHERE favorite_count IS NOT NULL
    GROUP BY item_id
)
SELECT count(*) AS items,
       count(*) FILTER (WHERE s.item_id IS NULL) AS no_snapshots,
       count(*) FILTER (WHERE s.n = 1) AS one_snapshot,
       count(*) FILTER (WHERE s.n >= 2) AS two_plus_snapshots,
       count(*) FILTER (WHERE s.n >= 2 AND
           extract(epoch FROM (s.last_at - s.first_at)) >= 3600)
           AS valid_growth_items
FROM items i
LEFT JOIN snap s ON s.item_id = i.id;

\echo --- 7. recent 48h items: snapshot coverage ---
WITH recent AS (
    SELECT id FROM items WHERE created_at >= now() - interval '48 hours'
), snap AS (
    SELECT h.item_id, count(*) AS n,
           min(h.snapshot_at) AS first_at, max(h.snapshot_at) AS last_at
    FROM item_history h
    JOIN recent r ON r.id = h.item_id
    WHERE h.snapshot_at >= now() - interval '48 hours'
      AND h.favorite_count IS NOT NULL
    GROUP BY h.item_id
)
SELECT count(*) AS recent_items,
       count(*) FILTER (WHERE s.item_id IS NULL) AS no_snapshots,
       count(*) FILTER (WHERE s.n = 1) AS one_snapshot,
       count(*) FILTER (WHERE s.n >= 2) AS two_plus_snapshots,
       count(*) FILTER (WHERE s.n >= 2 AND
           extract(epoch FROM (s.last_at - s.first_at)) >= 3600)
           AS valid_growth_items
FROM recent r
LEFT JOIN snap s ON s.item_id = r.id;

\echo --- 8. observation cadence (last 14 days) ---
SELECT date_trunc('hour', observed_at) AS hour,
       count(*) AS observations,
       count(DISTINCT item_id) AS items
FROM trend_item_observations
WHERE observed_at >= now() - interval '14 days'
GROUP BY 1
ORDER BY 1 DESC
LIMIT 200;

\echo --- 9. recent trend scan runs (collection cadence/coverage) ---
SELECT scan_run_id, status, started_at, finished_at,
       creators_eligible, observations_inserted
FROM trend_scan_runs
ORDER BY scan_run_id DESC
LIMIT 20;

\echo --- 10. snapshot gaps per recent item (items needing history) ---
WITH recent AS (
    SELECT id FROM items WHERE created_at >= now() - interval '48 hours'
), snap AS (
    SELECT item_id, count(*) AS n
    FROM item_history
    GROUP BY item_id
)
SELECT r.id, COALESCE(s.n, 0) AS snapshots
FROM recent r
LEFT JOIN snap s ON s.item_id = r.id
WHERE COALESCE(s.n, 0) < 2
ORDER BY r.id
LIMIT 200;
