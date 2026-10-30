# Migrations — data integrity, visibility, matched controls

Run a backup before applying or rolling back.

```bash
pg_dump "$DATABASE_URL" -Fc -f backup_before_integrity.dump
```

## Apply

The migrations are additive and run through `database.setup_database()`, which is
called on bot startup and by the jobs that import `database`.

They do three things:

1. Add `items.favorite_status` and classify existing rows.
2. Replace duplicate sales fingerprint uniqueness with:
   - `source_event_id` uniqueness when present,
   - fingerprint uniqueness only for legacy rows with no event ID.
3. Add `search_queries`, `search_runs`, `search_observations`, and
   `experiment_controls`; add matched-control columns to `recommendation_ledger`;
   add a daily uniqueness rule to `item_history`.

## Rollback

Rollback is intentionally conservative and may discard new event-ID/visibility data.
Do not run it while a snapshot or visibility job is active.

```sql
BEGIN;

DROP TABLE IF EXISTS search_observations;
DROP TABLE IF EXISTS search_runs;
DROP TABLE IF EXISTS search_queries;
DROP TABLE IF EXISTS experiment_controls;

ALTER TABLE recommendation_ledger
  DROP COLUMN IF EXISTS model_version,
  DROP COLUMN IF EXISTS evidence_at,
  DROP COLUMN IF EXISTS control_method,
  DROP COLUMN IF EXISTS match_quality,
  DROP COLUMN IF EXISTS control_n,
  DROP COLUMN IF EXISTS did_estimate,
  DROP COLUMN IF EXISTS assumptions,
  DROP COLUMN IF EXISTS evaluated_at;

DROP INDEX IF EXISTS idx_item_history_daily;

DROP INDEX IF EXISTS idx_my_sales_event_id;
DROP INDEX IF EXISTS idx_my_sales_fingerprint_fallback;
ALTER TABLE my_sales
  DROP COLUMN IF EXISTS source_event_id,
  DROP COLUMN IF EXISTS source;
ALTER TABLE my_sales
  ADD CONSTRAINT my_sales_sale_time_item_name_buyer_amount_robux_key
  UNIQUE (sale_time, item_name, buyer, amount_robux);

ALTER TABLE items DROP COLUMN IF EXISTS favorite_status;

COMMIT;
```

The rollback restores the old fingerprint uniqueness. If legitimate identical
sales were added after the upgrade, this will fail; resolve them manually before
restoring the constraint.

## Notes

- `setup_database()` uses `IF NOT EXISTS` and is safe to re-run.
- The daily `item_history` unique index assumes no duplicate item/day rows exist.
  The audit reports duplicates; it does not delete them.
- `favorite_status` values:
  - `known` — an API count was observed
  - `ambiguous_zero` — stored zero, origin not proven
  - `missing` — NULL, not observed
- `source_event_id` is preferred. Fingerprint fallback applies only when it is NULL.
- Search observations are catalog-API samples, not browser personalization or a
  hidden algorithm score.
- Matched-control results are observational; the 80% interval is not a causal proof.

## 2026-10-31 � Money and date semantics

`setup_database()` adds these idempotently:

```sql
ALTER TABLE my_sales
    ADD COLUMN IF NOT EXISTS amount_semantics TEXT
    DEFAULT 'unknown_recorded_amount';

ALTER TABLE launch_ledger
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS tracking_started_at TIMESTAMPTZ;
```

Backfill (runs once per restart, only where NULL):

```sql
UPDATE launch_ledger
SET tracking_started_at = launched_at
WHERE tracking_started_at IS NULL;

UPDATE launch_ledger l
SET published_at = i.created_at
FROM items i
WHERE i.id = l.item_id
  AND l.published_at IS NULL
  AND i.created_at IS NOT NULL;
```

Meaning:
- `amount_semantics` records what `amount_robux` represents. New rows default to
  `unknown_recorded_amount`; it must not be labelled revenue or proceeds until a
  verified transaction export supplies the semantics.
- `published_at` is the asset's catalog creation date (age anchor).
- `tracking_started_at` is when VANTA began tracking. Renames and first tracking
  never reset product age; D1/D7/D30 windows use
  `COALESCE(published_at, launched_at)`.

Rollback drops the three columns (data loss for those columns only):

```sql
ALTER TABLE my_sales DROP COLUMN IF EXISTS amount_semantics;
ALTER TABLE launch_ledger
    DROP COLUMN IF EXISTS published_at,
    DROP COLUMN IF EXISTS tracking_started_at;
```

## 2026-10-31 � Sales identity aliases (`sales_name_aliases`)

Names are mutable; asset IDs are identity. `item_resolver.ensure_schema()` runs
from `setup_database()` and is idempotent.

```sql
BEGIN;

CREATE TABLE IF NOT EXISTS sales_name_aliases (
    alias text PRIMARY KEY,
    item_id bigint NOT NULL,
    status text NOT NULL,
    evidence_source text NOT NULL,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sales_alias_item
    ON sales_name_aliases (item_id);

COMMIT;
```

Seeded aliases (ON CONFLICT DO NOTHING):

| alias | item_id | status | evidence |
|---|---|---|---|
| `cute beanie w paws` | 130928797494687 | confirmed | creator-confirmed rename to Cute Kitty Fluffy Beanie |
| `cute kitty fluffy beanie` | 130928797494687 | confirmed | creator-confirmed rename from Cute Beanie w paws |
| `smooth 360 flip rizz` | 92364796546749 | candidate | title match; sales predate ledger launch |
| `name smooth 360 flip rizz` | 92364796546749 | candidate | sales-channel prefix variant |

Rollback:

```sql
BEGIN;
DROP INDEX IF EXISTS idx_sales_alias_item;
DROP TABLE IF EXISTS sales_name_aliases;
COMMIT;
```

The resolver never deletes sale rows. Totals are always
`mapped + unresolved + ambiguous = all records`; unresolved names stay visible.
