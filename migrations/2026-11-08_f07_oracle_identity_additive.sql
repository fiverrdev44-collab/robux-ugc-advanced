-- 2026-11-08_f07_oracle_identity_additive.sql
--
-- F-07 ORACLE identity expansion: additive, non-destructive, idempotent.
-- Adds creator_type to observations and a derived creator_key to frozen
-- cohorts so User 123 and Group 123 can coexist. Original creator_id and
-- creator_type values are never rewritten; ambiguous rows become
-- 'unknown:<id>' and remain explicitly unresolved.

BEGIN;

ALTER TABLE trend_item_observations
    ADD COLUMN IF NOT EXISTS creator_type TEXT;

CREATE INDEX IF NOT EXISTS idx_trend_obs_creator_type
    ON trend_item_observations (creator_type, creator_id);

ALTER TABLE trend_creator_cohorts
    ADD COLUMN IF NOT EXISTS creator_key TEXT;

UPDATE trend_creator_cohorts
SET creator_key = CASE
        WHEN creator_type IN ('User', 'Group') AND creator_id IS NOT NULL
            THEN creator_type || ':' || creator_id
        WHEN creator_id IS NOT NULL
            THEN 'unknown:' || creator_id
        ELSE NULL
    END
WHERE creator_key IS NULL;

-- Remove the old numeric-only uniqueness; it cannot represent User/Group
-- collisions. This does not delete or rewrite cohort rows.
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'trend_creator_cohorts'::regclass
          AND contype = 'u'
          AND pg_get_constraintdef(oid) = 'UNIQUE (cohort_id, creator_id)'
    LOOP
        EXECUTE format(
            'ALTER TABLE trend_creator_cohorts DROP CONSTRAINT %I',
            r.conname);
    END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_trend_cohort_identity
    ON trend_creator_cohorts (cohort_id, creator_key);

CREATE INDEX IF NOT EXISTS idx_trend_cohorts_type_identity
    ON trend_creator_cohorts (cohort_type, creator_type, creator_id);

-- New rows must carry a typed or explicitly unknown key. Historical rows were
-- backfilled above; NULL is no longer accepted.
ALTER TABLE trend_creator_cohorts
    ALTER COLUMN creator_key SET NOT NULL;

COMMIT;

-- Rollback (manual, approval required):
--   DROP INDEX IF EXISTS uq_trend_cohort_identity;
--   ALTER TABLE trend_creator_cohorts DROP COLUMN IF EXISTS creator_key;
--   ALTER TABLE trend_creator_cohorts ADD CONSTRAINT
--       trend_creator_cohorts_cohort_id_creator_id_key
--       UNIQUE (cohort_id, creator_id);  -- only after resolving typed collisions
--   DROP INDEX IF EXISTS idx_trend_obs_creator_type;
--   ALTER TABLE trend_item_observations DROP COLUMN IF EXISTS creator_type;
