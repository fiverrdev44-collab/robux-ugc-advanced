-- 2026-11-05_golden_hour_indexes.sql
--
-- Optional, additive index for the 48-hour golden-window query:
--   items WHERE created_at >= NOW() - INTERVAL '48 hours'
--
-- The snapshot side joins item_history on (item_id, snapshot_at) for the
-- recent items, which is already covered by:
--   idx_item_history_item_snapshot (item_id, snapshot_at)
-- so no additional item_history index is added here.
--
-- Review EXPLAIN (ANALYZE, BUFFERS) on staging before applying. Do not run
-- this automatically; no production migration is applied by the application.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_items_created_at
    ON items (created_at);

COMMIT;
