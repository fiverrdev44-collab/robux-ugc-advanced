-- VANTA 73 release preflight (READ ONLY)
-- Run only against a production-like snapshot, with approval.
-- Every statement is SELECT-only; this file must not modify data.

-- 1. Core row counts and time range.
SELECT 'items' AS object, count(*) AS rows,
       min(created_at) AS oldest, max(fetched_at) AS newest
FROM items
UNION ALL
SELECT 'item_history', count(*), min(snapshot_at), max(snapshot_at)
FROM item_history
UNION ALL
SELECT 'my_sales', count(*), min(sale_time), max(sale_time)
FROM my_sales
UNION ALL
SELECT 'tracked_creators', count(*), min(last_scanned), max(last_scanned)
FROM tracked_creators;

-- 2. Legacy timestamp types that F-10 is expected to convert.
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = current_schema()
  AND (
      (table_name = 'items'
       AND column_name IN ('created_at', 'updated_at', 'fetched_at'))
      OR (table_name = 'item_history' AND column_name = 'snapshot_at')
      OR (table_name = 'tracked_creators'
          AND column_name IN ('last_scanned', 'added_at'))
      OR (table_name = 'launch_ledger'
          AND column_name IN ('launched_at', 'last_synced'))
      OR (table_name = 'creator_patterns' AND column_name = 'updated_at')
  )
ORDER BY table_name, column_name;

-- 3. UTC duplicate snapshot days (must return zero rows before migration).
-- The expression is type-aware and independent of the session TimeZone:
--   * TIMESTAMP (legacy UTC wall time): double AT TIME ZONE yields a UTC date.
--   * TIMESTAMPTZ (absolute instant): single AT TIME ZONE yields a UTC date.
SELECT item_id,
       CASE
           WHEN pg_typeof(snapshot_at) =
                'timestamp without time zone'::regtype
               THEN (((snapshot_at AT TIME ZONE 'UTC')
                      AT TIME ZONE 'UTC')::date)
           ELSE ((snapshot_at AT TIME ZONE 'UTC')::date)
       END AS utc_day,
       count(*) AS rows
FROM item_history
GROUP BY 1, 2
HAVING count(*) > 1
ORDER BY 3 DESC, 1;

-- 4. Current daily index definition (must be inspected before replacement).
SELECT pg_get_indexdef(to_regclass('idx_item_history_daily')) AS index_def;

-- 5. Creator identity ambiguity inventory.
SELECT COALESCE(creator_type, 'NULL') AS stored_type,
       count(*) AS rows,
       count(*) FILTER (WHERE creator_id IS NULL) AS missing_ids
FROM tracked_creators
GROUP BY 1
ORDER BY 1;

SELECT creator_id, count(*) AS typed_rows
FROM tracked_creators
GROUP BY creator_id
HAVING count(*) > 1
ORDER BY 2 DESC, 1;

-- 6. ORACLE cohort identity inventory.
SELECT COALESCE(creator_type, 'NULL') AS stored_type,
       count(*) AS rows
FROM trend_creator_cohorts
GROUP BY 1
ORDER BY 1;

SELECT cohort_id, creator_id, count(*) AS rows
FROM trend_creator_cohorts
GROUP BY 1, 2
HAVING count(*) > 1
ORDER BY 3 DESC, 1, 2;

-- 7. Sales identity/duplicate inventory.
SELECT count(*) AS rows,
       count(*) FILTER (WHERE source_event_id IS NULL) AS missing_event_id,
       count(*) FILTER (WHERE transaction_id IS NULL) AS missing_txn_id,
       min(sale_time) AS oldest_sale,
       max(sale_time) AS newest_sale
FROM my_sales;

SELECT source_event_id, count(*) AS rows
FROM my_sales
WHERE source_event_id IS NOT NULL
GROUP BY 1
HAVING count(*) > 1
ORDER BY 2 DESC, 1
LIMIT 50;

SELECT transaction_id, count(*) AS rows
FROM my_sales
WHERE transaction_id IS NOT NULL
GROUP BY 1
HAVING count(*) > 1
ORDER BY 2 DESC, 1
LIMIT 50;

-- 8. Migration-readiness markers.
SELECT
    to_regclass('creator_registry') IS NOT NULL AS creator_registry_exists,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'items' AND column_name = 'creator_type'
    ) AS items_creator_type_exists,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'my_sales' AND column_name = 'transaction_id'
    ) AS sales_identity_columns_exist,
    to_regclass('trend_scan_runs') IS NOT NULL AS oracle_tables_exist,
    to_regclass('astra_runs') IS NOT NULL AS astra_tables_exist;
