-- Astra Phase 3: link runs to launched assets and capture baselines.
-- Apply manually or with RUN_MIGRATIONS_ON_START=1 (one-shot). Idempotent.

ALTER TABLE astra_runs
    ADD COLUMN IF NOT EXISTS linked_item_id bigint,
    ADD COLUMN IF NOT EXISTS linked_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_astra_runs_linked
    ON astra_runs (linked_item_id);

CREATE TABLE IF NOT EXISTS astra_outcomes (
    id bigserial PRIMARY KEY,
    run_id bigint NOT NULL UNIQUE,
    item_id bigint NOT NULL,
    baseline_favorites integer,
    baseline_sales integer,
    baseline_captured_at timestamptz DEFAULT now(),
    launched_at timestamptz DEFAULT now(),
    heuristic_version text,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_astra_outcomes_item
    ON astra_outcomes (item_id);
