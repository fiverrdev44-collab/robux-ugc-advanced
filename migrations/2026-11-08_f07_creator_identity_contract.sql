-- 2026-11-08_f07_creator_identity_contract.sql
--
-- F-07 contract phase: replaces the numeric-only primary key with the
-- composite (creator_type, creator_id) key. Run only after the expand
-- migration and after reviewing the inventory. Transactional.
--
-- Rollback is documented at the bottom. It is intentionally guarded because a
-- rollback after User/Group collisions have been stored would lose identities.

BEGIN;

DO $$
DECLARE
    dup_count BIGINT;
BEGIN
    SELECT count(*) INTO dup_count
    FROM (
        SELECT creator_type, creator_id
        FROM tracked_creators
        GROUP BY creator_type, creator_id
        HAVING count(*) > 1
    ) d;
    IF dup_count > 0 THEN
        RAISE EXCEPTION
            'F-07 contract aborted: % duplicate composite identities exist',
            dup_count;
    END IF;
END $$;

-- Drop the old numeric-only primary key if it is still present.
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'tracked_creators'::regclass
          AND contype = 'p'
          AND pg_get_constraintdef(oid) <> 'PRIMARY KEY (creator_type, creator_id)'
    LOOP
        EXECUTE format(
            'ALTER TABLE tracked_creators DROP CONSTRAINT %I', r.conname);
    END LOOP;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'tracked_creators'::regclass
          AND contype = 'p'
          AND pg_get_constraintdef(oid) = 'PRIMARY KEY (creator_type, creator_id)'
    ) THEN
        ALTER TABLE tracked_creators
            ADD CONSTRAINT tracked_creators_pkey
            PRIMARY KEY (creator_type, creator_id);
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tracked_creators_key
    ON tracked_creators (creator_key);

COMMIT;

-- Rollback (manual, approval required):
--   BEGIN;
--   DO $$
--   BEGIN
--       IF EXISTS (
--           SELECT creator_id FROM tracked_creators
--           GROUP BY creator_id HAVING count(*) > 1
--       ) THEN
--           RAISE EXCEPTION
--               'rollback blocked: typed User/Group collisions exist; archive '
--               'or back up first';
--       END IF;
--   END $$;
--   ALTER TABLE tracked_creators DROP CONSTRAINT tracked_creators_pkey;
--   ALTER TABLE tracked_creators
--       ADD CONSTRAINT tracked_creators_pkey PRIMARY KEY (creator_id);
--   COMMIT;
