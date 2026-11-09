-- 2026-11-08_f10_timestamp_integrity.sql
--
-- F-10: normalize legacy naive TIMESTAMP columns to timezone-aware UTC.
--
-- Provenance basis: every repository database connection sets the PostgreSQL
-- session TimeZone to UTC (database.py and bot_core.py connection options),
-- and Roblox item creation timestamps are UTC. Legacy naive values are
-- therefore interpreted as UTC, never as the migration session's local time.
-- The conversion uses explicit AT TIME ZONE 'UTC' expressions and does not
-- depend on the session TimeZone.
--
-- This migration is approval-gated. It rewrites tables and takes
-- ACCESS EXCLUSIVE locks; schedule a maintenance window and review the
-- preflight notices before applying. It is not run at bot startup.
--
-- Rollback (manual, after the same review):
--   BEGIN;
--   DROP INDEX IF EXISTS idx_item_history_daily;
--   ALTER TABLE items
--     ALTER COLUMN created_at TYPE timestamp USING created_at AT TIME ZONE 'UTC',
--     ALTER COLUMN updated_at TYPE timestamp USING updated_at AT TIME ZONE 'UTC',
--     ALTER COLUMN fetched_at TYPE timestamp USING fetched_at AT TIME ZONE 'UTC';
--   ALTER TABLE item_history
--     ALTER COLUMN snapshot_at TYPE timestamp USING snapshot_at AT TIME ZONE 'UTC';
--   CREATE UNIQUE INDEX idx_item_history_daily
--     ON item_history (item_id, (snapshot_at::date));
--   -- Repeat the reverse type change for the other columns listed below.
--   COMMIT;

BEGIN;

CREATE OR REPLACE FUNCTION _f10_utc_column(tbl text, col text)
RETURNS void AS $$
BEGIN
    IF to_regclass(tbl) IS NULL THEN
        RETURN;
    END IF;
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = tbl
          AND column_name = col
          AND data_type = 'timestamp without time zone'
    ) THEN
        EXECUTE format(
            'ALTER TABLE %I ALTER COLUMN %I TYPE timestamptz '
            'USING %I AT TIME ZONE %L',
            tbl, col, col, 'UTC');
    END IF;
END $$ LANGUAGE plpgsql;

DO $$
DECLARE
    item_rows BIGINT;
    history_rows BIGINT;
    future_items BIGINT;
    future_history BIGINT;
    duplicate_utc_days BIGINT;
    history_type TEXT;
BEGIN
    SELECT count(*) INTO item_rows FROM items;
    SELECT count(*) INTO history_rows FROM item_history;
    SELECT count(*) INTO future_items
      FROM items WHERE created_at > now() + interval '2 days';
    SELECT count(*) INTO future_history
      FROM item_history WHERE snapshot_at > now() + interval '2 days';

    SELECT data_type INTO history_type
      FROM information_schema.columns
     WHERE table_schema = current_schema()
       AND table_name = 'item_history'
       AND column_name = 'snapshot_at';
    IF history_type = 'timestamp without time zone' THEN
        SELECT count(*) INTO duplicate_utc_days
          FROM (
              SELECT item_id,
                     (((snapshot_at AT TIME ZONE 'UTC')
                       AT TIME ZONE 'UTC')::date) AS d
              FROM item_history
              GROUP BY 1, 2
              HAVING count(*) > 1
          ) dup;
    ELSE
        SELECT count(*) INTO duplicate_utc_days
          FROM (
              SELECT item_id,
                     ((snapshot_at AT TIME ZONE 'UTC')::date) AS d
              FROM item_history
              GROUP BY 1, 2
              HAVING count(*) > 1
          ) dup;
    END IF;

    RAISE NOTICE
        'F-10 preflight: items=% history=% future_items=% future_history=% '
        'duplicate_utc_days=%',
        item_rows, history_rows, future_items, future_history,
        duplicate_utc_days;

    IF duplicate_utc_days > 0 THEN
        RAISE EXCEPTION
            'F-10 aborted: % duplicate item_history rows share a UTC calendar '
            'day; resolve before replacing idx_item_history_daily',
            duplicate_utc_days;
    END IF;
END $$;

-- Drop the session-timezone-dependent daily index. The replacement is created
-- after the column type change using the immutable UTC-wall-time expression.
DROP INDEX IF EXISTS idx_item_history_daily;

-- Core catalog and observation timestamps (Roblox UTC / DB UTC session).
SELECT _f10_utc_column('items', 'created_at');
SELECT _f10_utc_column('items', 'updated_at');
SELECT _f10_utc_column('items', 'fetched_at');
SELECT _f10_utc_column('item_history', 'snapshot_at');
SELECT _f10_utc_column('failed_items', 'last_tried');
SELECT _f10_utc_column('search_suggestions', 'fetched_at');
SELECT _f10_utc_column('learned_keywords', 'learned_at');

-- User/account and tracking timestamps.
SELECT _f10_utc_column('user_profiles', 'first_seen');
SELECT _f10_utc_column('user_profiles', 'last_active');
SELECT _f10_utc_column('saved_consultations', 'created_at');
SELECT _f10_utc_column('watchlist', 'added_at');
SELECT _f10_utc_column('watchlist', 'last_checked');
SELECT _f10_utc_column('competitor_tracking', 'added_at');
SELECT _f10_utc_column('item_tracker', 'added_at');
SELECT _f10_utc_column('my_portfolio', 'added_at');

-- Launch and learning timestamps.
SELECT _f10_utc_column('launch_ledger', 'launched_at');
SELECT _f10_utc_column('launch_ledger', 'last_synced');
SELECT _f10_utc_column('creator_patterns', 'updated_at');
SELECT _f10_utc_column('tracked_creators', 'last_scanned');
SELECT _f10_utc_column('tracked_creators', 'added_at');
SELECT _f10_utc_column('predictor_weights', 'trained_at');

-- UTC calendar-day uniqueness, independent of the session TimeZone.
CREATE UNIQUE INDEX idx_item_history_daily
    ON item_history (
        item_id,
        ((snapshot_at AT TIME ZONE 'UTC')::date));

DO $$
DECLARE
    item_rows BIGINT;
    history_rows BIGINT;
BEGIN
    SELECT count(*) INTO item_rows FROM items;
    SELECT count(*) INTO history_rows FROM item_history;
    RAISE NOTICE 'F-10 postflight: items=% history=%', item_rows, history_rows;
END $$;

DROP FUNCTION _f10_utc_column(text, text);

COMMIT;
