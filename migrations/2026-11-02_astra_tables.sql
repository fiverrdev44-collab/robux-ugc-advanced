-- Astra runs: generated concepts/titles and algorithmic outcomes.
-- Apply via RUN_MIGRATIONS_ON_START=1 or manually. Idempotent.

CREATE TABLE IF NOT EXISTS astra_runs (
    id bigserial PRIMARY KEY,
    item_id bigint,
    concept text,
    asset_type text,
    angles jsonb,
    titles jsonb,
    chosen_title text,
    preview_version text,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_astra_runs_item ON astra_runs (item_id);
