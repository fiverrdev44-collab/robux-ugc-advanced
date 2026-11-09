-- 2026-11-08_f07_creator_identity_expand.sql
--
-- F-07 expand phase: additive, non-destructive, idempotent.
-- Prepares tracked_creators for composite identity without dropping the old
-- primary key. Deploy this before the application if the old PK is still in
-- place, then apply the contract migration during an approved window.
--
-- Data policy: existing User/Group values are preserved; NULL/other values
-- become explicitly 'unknown' (never guessed as User). type_provenance records
-- that the value came from the legacy table so reports can disclose it.

BEGIN;

DO $$
BEGIN
    IF to_regclass('tracked_creators') IS NULL THEN
        RAISE EXCEPTION 'tracked_creators table is missing';
    END IF;
END $$;

ALTER TABLE tracked_creators
    ADD COLUMN IF NOT EXISTS type_provenance TEXT;

-- Remove the old silent 'User' default before normalizing existing rows.
ALTER TABLE tracked_creators
    ALTER COLUMN creator_type DROP DEFAULT;

UPDATE tracked_creators
SET type_provenance = CASE
        WHEN creator_type IS NULL OR btrim(creator_type) = ''
            THEN 'legacy_unknown'
        WHEN lower(btrim(creator_type)) IN ('user', 'group')
            THEN 'legacy_stored'
        ELSE 'legacy_unknown'
    END
WHERE type_provenance IS NULL;

UPDATE tracked_creators
SET creator_type = CASE
        WHEN lower(btrim(creator_type)) = 'user' THEN 'User'
        WHEN lower(btrim(creator_type)) = 'group' THEN 'Group'
        ELSE 'unknown'
    END
WHERE creator_type IS NULL
   OR btrim(creator_type) = ''
   OR lower(btrim(creator_type)) NOT IN ('user', 'group');

ALTER TABLE tracked_creators
    ALTER COLUMN creator_type SET DEFAULT 'unknown',
    ALTER COLUMN creator_type SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'tracked_creators'::regclass
          AND conname = 'tracked_creators_type_check'
    ) THEN
        ALTER TABLE tracked_creators
            ADD CONSTRAINT tracked_creators_type_check
            CHECK (creator_type IN ('User', 'Group', 'unknown'));
    END IF;
END $$;

ALTER TABLE tracked_creators
    ADD COLUMN IF NOT EXISTS creator_key TEXT
    GENERATED ALWAYS AS (creator_type || ':' || creator_id) STORED;

CREATE INDEX IF NOT EXISTS idx_tracked_creators_identity
    ON tracked_creators (creator_type, creator_id);
CREATE INDEX IF NOT EXISTS idx_tracked_creators_scan
    ON tracked_creators (last_scanned NULLS FIRST);

DO $$
DECLARE
    total_rows BIGINT;
    unknown_rows BIGINT;
    user_rows BIGINT;
    group_rows BIGINT;
BEGIN
    SELECT count(*),
           count(*) FILTER (WHERE creator_type = 'unknown'),
           count(*) FILTER (WHERE creator_type = 'User'),
           count(*) FILTER (WHERE creator_type = 'Group')
      INTO total_rows, unknown_rows, user_rows, group_rows
      FROM tracked_creators;
    RAISE NOTICE 'F-07 expand inventory: total=% unknown=% user=% group=%',
        total_rows, unknown_rows, user_rows, group_rows;
END $$;

COMMIT;
