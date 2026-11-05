-- 2026-11-05_creator_registry.sql
--
-- ADDITIVE ONLY. Creates a creator registry keyed by (creator_type, creator_id)
-- so different creators are never merged by display name, and user/group IDs
-- are never conflated. No existing table or row is modified.
--
-- Review + approval required before applying. The application reads existing
-- items/tracked_creators and can backfill this registry; no migration is run
-- automatically.

BEGIN;

-- Composite creator identity support on items. Additive and nullable.
-- Deliberately no backfill from tracked_creators by numeric ID: historical
-- items keep creator_type NULL (unknown) because User/Group IDs can collide.
ALTER TABLE items ADD COLUMN IF NOT EXISTS creator_type TEXT;

CREATE TABLE IF NOT EXISTS creator_registry (
    creator_type            TEXT        NOT NULL,
    creator_id              BIGINT      NOT NULL,
    display_name            TEXT,
    verification_status     TEXT        NOT NULL DEFAULT 'unknown',
    verification_provenance TEXT,
    type_provenance         TEXT,
    first_seen              TIMESTAMPTZ,
    last_seen               TIMESTAMPTZ,
    item_count              INTEGER     NOT NULL DEFAULT 0,
    category_counts         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    price_counts            JSONB       NOT NULL DEFAULT '{}'::jsonb,
    median_favorites        REAL,
    median_price            REAL,
    median_age_days         REAL,
    snapshot_item_count     INTEGER     NOT NULL DEFAULT 0,
    max_snapshots           INTEGER     NOT NULL DEFAULT 0,
    missing_favorite_items  INTEGER     NOT NULL DEFAULT 0,
    previous_names          JSONB       NOT NULL DEFAULT '[]'::jsonb,
    updated_at              TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (creator_type, creator_id)
);

CREATE INDEX IF NOT EXISTS idx_creator_registry_id
    ON creator_registry (creator_id);
CREATE INDEX IF NOT EXISTS idx_creator_registry_name
    ON creator_registry (lower(display_name));
CREATE INDEX IF NOT EXISTS idx_creator_registry_verified
    ON creator_registry (verification_status);
CREATE INDEX IF NOT EXISTS idx_creator_registry_seen
    ON creator_registry (last_seen DESC);

COMMIT;
