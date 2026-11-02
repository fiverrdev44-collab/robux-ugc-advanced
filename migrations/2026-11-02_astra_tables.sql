-- Astra tables (apply via RUN_MIGRATIONS_ON_START=1 or manually).
-- Not applied by this commit.

CREATE TABLE IF NOT EXISTS marketplace_links (
    link_id text PRIMARY KEY,
    item_id bigint,
    source text,
    clicks integer NOT NULL DEFAULT 0,
    unique_clickers integer NOT NULL DEFAULT 0,
    purchases integer NOT NULL DEFAULT 0,
    spend_robux integer NOT NULL DEFAULT 0,
    observed_at timestamptz DEFAULT now(),
    raw jsonb
);
CREATE INDEX IF NOT EXISTS idx_marketplace_links_item
    ON marketplace_links (item_id);

CREATE TABLE IF NOT EXISTS astra_runs (
    id bigserial PRIMARY KEY,
    item_id bigint,
    concept text,
    angles jsonb,
    titles jsonb,
    preview_version text,
    link_id text,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_astra_runs_item ON astra_runs (item_id);
CREATE INDEX IF NOT EXISTS idx_astra_runs_link ON astra_runs (link_id);
