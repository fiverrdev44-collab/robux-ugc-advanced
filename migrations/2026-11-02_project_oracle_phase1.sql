-- Project ORACLE — Phase 1 (additive; does not touch existing creator tables).
-- Apply manually or with RUN_MIGRATIONS_ON_START=1. Idempotent.

CREATE TABLE IF NOT EXISTS trend_creator_cohorts (
    id bigserial PRIMARY KEY,
    cohort_id text NOT NULL,
    creator_id bigint NOT NULL,
    cohort_type text NOT NULL
        CHECK (cohort_type IN ('ELITE', 'EMERGING', 'CONTROL')),
    selected_at timestamptz NOT NULL DEFAULT now(),
    selection_score double precision,
    selection_reason text,
    cohort_period_start timestamptz NOT NULL,
    cohort_period_end timestamptz NOT NULL,
    UNIQUE (cohort_id, creator_id)
);
CREATE INDEX IF NOT EXISTS idx_trend_cohorts_type
    ON trend_creator_cohorts (cohort_type, cohort_id);
CREATE INDEX IF NOT EXISTS idx_trend_cohorts_creator
    ON trend_creator_cohorts (creator_id);

CREATE TABLE IF NOT EXISTS trend_item_observations (
    id bigserial PRIMARY KEY,
    item_id bigint NOT NULL,
    creator_id bigint,
    observed_at timestamptz NOT NULL DEFAULT now(),
    scan_run_id bigint NOT NULL,
    favorites integer,
    title text,
    description text,
    price integer,
    created_at timestamptz,
    favorite_data_status text NOT NULL DEFAULT 'unknown'
        CHECK (favorite_data_status IN ('known', 'missing', 'unknown')),
    UNIQUE (scan_run_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_trend_obs_item_time
    ON trend_item_observations (item_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_trend_obs_creator
    ON trend_item_observations (creator_id);
