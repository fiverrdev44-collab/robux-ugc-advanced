-- 2026-11-03_sales_integrity_columns.sql
--
-- ADDITIVE ONLY. Adds nullable columns and non-unique indexes to my_sales so
-- the ingestion identity model (txn:<provider>:<id> / discord:<msgid>:<idx>)
-- can be persisted alongside legacy rows. No existing rows are changed,
-- deleted, or re-keyed by this file.
--
-- Review + approval required before running in production. The application
-- degrades gracefully if these columns are absent (it keeps using the legacy
-- source_event_id/source columns only).

BEGIN;

ALTER TABLE my_sales ADD COLUMN IF NOT EXISTS notification_time     TIMESTAMPTZ;
ALTER TABLE my_sales ADD COLUMN IF NOT EXISTS transaction_id        TEXT;
ALTER TABLE my_sales ADD COLUMN IF NOT EXISTS source_event_version  TEXT;
ALTER TABLE my_sales ADD COLUMN IF NOT EXISTS embed_index           INTEGER;
ALTER TABLE my_sales ADD COLUMN IF NOT EXISTS asset_id              BIGINT;
ALTER TABLE my_sales ADD COLUMN IF NOT EXISTS group_id              BIGINT;
ALTER TABLE my_sales ADD COLUMN IF NOT EXISTS buyer_id              BIGINT;
ALTER TABLE my_sales ADD COLUMN IF NOT EXISTS raw_item_name         TEXT;
ALTER TABLE my_sales ADD COLUMN IF NOT EXISTS time_source           TEXT;
ALTER TABLE my_sales ADD COLUMN IF NOT EXISTS group_name            TEXT;

CREATE INDEX IF NOT EXISTS idx_my_sales_transaction_id
    ON my_sales (transaction_id) WHERE transaction_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_my_sales_source_event
    ON my_sales (source_event_id) WHERE source_event_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_my_sales_notification_time
    ON my_sales (notification_time);
CREATE INDEX IF NOT EXISTS idx_my_sales_asset_id
    ON my_sales (asset_id) WHERE asset_id IS NOT NULL;

-- NOT run here: a UNIQUE index on source_event_id/transaction_id must be
-- created only AFTER the reconciliation report confirms no duplicates:
--
--   CREATE UNIQUE INDEX idx_my_sales_source_event_unique
--       ON my_sales (source_event_id) WHERE source_event_id IS NOT NULL;
--
-- Run that statement manually once the report shows duplicate_event_ids = 0.

COMMIT;
