-- Project ORACLE Phase 2 — additive, idempotent.
-- NOT applied to production by the implementation branch.

CREATE TABLE IF NOT EXISTS trend_scan_runs (
    scan_run_id            BIGSERIAL PRIMARY KEY,
    started_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at            TIMESTAMPTZ,
    status                 TEXT NOT NULL DEFAULT 'running',
    cohort_snapshot_ref    TEXT,
    creators_eligible      INT,
    creators_scanned       INT,
    creators_errored       INT,
    items_discovered       INT,
    items_in_window        INT,
    observations_inserted  INT,
    skipped_too_recent     INT,
    skipped_rate_limited   INT,
    skipped_unavailable    INT,
    skipped_unknown_type   INT,
    truncated_creators     JSONB,
    error_summary          JSONB
);

ALTER TABLE trend_item_observations
    ADD COLUMN IF NOT EXISTS sales_count integer,
    ADD COLUMN IF NOT EXISTS item_type text,
    ADD COLUMN IF NOT EXISTS favorites_delta integer,
    ADD COLUMN IF NOT EXISTS hours_since_last numeric,
    ADD COLUMN IF NOT EXISTS favorites_velocity numeric;

ALTER TABLE trend_creator_cohorts
    ADD COLUMN IF NOT EXISTS creator_type text;

-- Backfill only where a real tracked creator_type exists; never default to User.
UPDATE trend_creator_cohorts c
SET creator_type = t.creator_type
FROM tracked_creators t
WHERE c.creator_id = t.creator_id
  AND c.creator_type IS NULL
  AND t.creator_type IS NOT NULL;
