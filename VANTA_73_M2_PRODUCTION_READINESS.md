# VANTA 73 — M2 Production Readiness (pre-M3)

Production commit: `ec100c0`
Scope: M2 creator registry readiness, controlled migration, bounded backfill,
and read-only diagnostics. No production migration or backfill was executed.

## 0. Execution status

**Production diagnostics were not executed.** No authorized database URL or
read-only replica credentials are present in this environment (`DATABASE_URL`,
`PG*`, `STAGING*`, and replica variables are unset). No results below are
fabricated.

All production-dependent items remain **UNVERIFIED** until the read-only script
is run by an operator with authorized access:

```bash
psql "$READONLY_DATABASE_URL" -X -v ON_ERROR_STOP=1 -P pager=off \
     -A -F ' | ' -f diagnostics/production_readiness_m2.sql
```

Run it against a replica where possible. The script opens `BEGIN READ ONLY`,
sets timeouts, performs no writes, and rolls back. It reports
`transaction_read_only` so the operator can confirm the read-only state.

### 0.1 Running with credentials already provisioned on the server/replica

Do not paste a DSN into chat, a commit, a report, or shell history. Use the
read-only DSN that is already available to the authorized server/replica
operator. The commands below reference the variable only; they never print it.

```bash
cd ~/robux-ugc-advanced

# Use the existing read-only DSN variable provisioned on the host.
if [ -z "${READONLY_DATABASE_URL:-}" ]; then
  echo "READONLY_DATABASE_URL is not set in this shell; use the host's existing read-only DSN variable."
  exit 1
fi

psql "$READONLY_DATABASE_URL" -X -v ON_ERROR_STOP=1 -P pager=off \
     -A -F ' | ' -f diagnostics/production_readiness_m2.sql \
     | tee "/tmp/m2_readiness_$(date -u +%Y%m%dT%H%M%SZ).txt"
```

If the host exposes the read-only DSN under a different variable name, use that
name instead. Prefer a replica endpoint or a role with `CONNECT`/`USAGE`/
`SELECT` only. If only the primary is available, obtain approval first (item 2
in section 8); the script is still strictly read-only.

The operator should share only the captured output file. No credentials were
requested, printed, or stored by this task.

## 1. Code-level findings (verified locally)

- The M2 migration is additive only:
  - `ALTER TABLE items ADD COLUMN IF NOT EXISTS creator_type TEXT;`
  - `CREATE TABLE IF NOT EXISTS creator_registry (...)` keyed by
    `(creator_type, creator_id)`.
  - Four indexes on the new table.
- The auto-deploy workflow (`.github/workflows/deploy.yml`) only fetches code,
  installs dependencies, and restarts `ugc-bot`. **It does not apply database
  migrations.** Unless the migration was applied manually, `items.creator_type`
  and `creator_registry` are absent in production.
- The deployed code degrades safely when the migration is absent:
  - `creator_evidence()` returns `registry.available = false` with
    `reason = "missing_table"` when `creator_registry` is missing, and does not
    abort a normal `autocommit=False` transaction.
  - `creator_comparison()` checks for `items.creator_type` before using it.
- Composite identity is enforced by the primary key
  `(creator_type, creator_id)`, not by display name.
- `resolve_creator_type()` uses the item's own `creator_type` as authoritative.
  It uses `tracked_creators` only when the creator name corroborates the
  numeric ID; otherwise the type remains `unknown` with provenance `missing`.
- Verification is tri-state: any `TRUE` => `verified`, else any `FALSE` =>
  `nonverified`, else `unknown` / `missing`. `NULL` is never treated as
  confirmed nonverified.
- Registry name history is filtered against the effective post-upsert display
  name, so an incoming `NULL`/empty display name cannot add the retained
  current name to `previous_names`; prior names are deduplicated.
- Relevant tests passed on `5abb74e` (pre-merge) and CI passed on `5abb74e`:
  - `test_phase2_milestone2.py` (unit) and the PostgreSQL integration suite.
  - The same code is in production commit `ec100c0`.

## 2. Production database readiness checklist

Status values: **CODE OK** = verified in code/tests; **UNVERIFIED** = requires
authorized production read-only access.

| # | Check | Status | Evidence / next action |
|---|-------|--------|------------------------|
| 1 | `items.creator_type` exists | UNVERIFIED | Run section 1 of `production_readiness_m2.sql` |
| 2 | `creator_registry` exists | UNVERIFIED | Deploy does not migrate; confirm with section 1 |
| 3 | Registry row count, if present | UNVERIFIED | Section 6 |
| 4 | Stable creator-ID coverage | UNVERIFIED | Section 3 |
| 5 | Known vs unknown creator types | UNVERIFIED | Section 4 |
| 6 | Verified/nonverified/unknown coverage | UNVERIFIED | Sections 5 and 6 |
| 7 | Recent 48h snapshot coverage | UNVERIFIED | Section 8 |
| 8 | No incorrect User/Group numeric-ID merge | CODE OK / UNVERIFIED data | PK is composite; production audit in 7a/7d |
| 9 | Evidence stays unavailable/unknown with insufficient provenance | CODE OK / UNVERIFIED data | `creator_evidence()` and `resolve_creator_type()`; sections 4 and 6 |
| 10 | `!golden_hour` 48h velocity diagnosis | CODE-LEVEL CAUSES / UNVERIFIED data | Sections 8 and 9 |
| 11 | `idx_item_history_daily` exists and is unique | UNVERIFIED | Section 2b; existence is checked, not assumed |

Readiness decision: **not yet ready for M3 acceptance** until checks 1–7, 10,
and 11 are executed and reviewed. No data values are assumed.

## 3. Controlled migration plan (requires explicit approval)

Do not apply without approval. This migration is separate from deployment.

### 3.1 Preconditions

1. Explicit approval to apply the migration.
2. Authorized replica/staging database available.
3. Confirm current state with read-only checks 1–2.
4. Confirm no unexpected existing column/table definition conflicts.
5. Take a backup and prove restore on a disposable database.
6. Choose a low-traffic window.

### 3.2 Backup

Use an approved backup target. Example:

```bash
pg_dump "$PRODUCTION_DATABASE_URL" \
  --schema=public \
  --table=public.items \
  --table=public.creator_registry \
  --format=custom --file="backup_pre_m2_$(date -u +%Y%m%dT%H%M%SZ).dump"
```

If `creator_registry` does not exist yet, back up `items` at minimum and record
row counts. Verify the dump restores into a disposable database before touching
production.

### 3.3 Lock and transaction considerations

- `ALTER TABLE items ADD COLUMN creator_type TEXT` is metadata-only for a
  nullable column with no default, but it still requires a brief
  `ACCESS EXCLUSIVE` lock on `items`. Set a short `lock_timeout` and retry
  rather than queueing behind long transactions.
- The new table and indexes are created empty; their cost is minimal. Keep the
  whole migration in one transaction because PostgreSQL supports transactional
  DDL.
- Do not run `CREATE INDEX CONCURRENTLY` inside the migration transaction.
  The indexes are on a brand-new empty table, so ordinary `CREATE INDEX` is
  acceptable.

### 3.4 Apply procedure

1. Start a transaction with timeouts:
   ```sql
   BEGIN;
   SET LOCAL lock_timeout = '5s';
   SET LOCAL statement_timeout = '60s';
   ```
2. Execute `migrations/2026-11-05_creator_registry.sql` exactly as reviewed.
3. Run verification queries from section 4 below in the same transaction.
4. If all checks pass: `COMMIT;`.
5. If lock timeout or verification failure: `ROLLBACK;` and reschedule.
6. Record the executed migration file hash, operator, timestamp, and database.

### 3.5 Migration verification queries

```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'items'
  AND column_name = 'creator_type';

SELECT to_regclass('public.creator_registry') AS creator_registry;

SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public' AND tablename = 'creator_registry'
ORDER BY indexname;

SELECT count(*) AS registry_rows FROM public.creator_registry;
```

Expected immediately after migration: column exists; table exists; four
indexes exist; registry row count is `0` (no automatic backfill).

### 3.6 Rollback

Preferred rollback is additive-safe:

1. Stop any registry writer/backfill.
2. Take a final backup.
3. Drop only the new table if required:
   ```sql
   DROP TABLE IF EXISTS public.creator_registry;
   ```
4. Leave `items.creator_type` in place unless explicitly approved. It is
   nullable and harmless; dropping it destroys new evidence and should be a
   separate approved change:
   ```sql
   ALTER TABLE public.items DROP COLUMN IF EXISTS creator_type;
   ```

Rollback must be approved in advance. Do not drop columns while writers are
active.

## 4. Bounded initial backfill plan (requires explicit approval)

Do not start automatically. The existing function is already resumable and
makes no Roblox API calls:

`creator_registry.refresh_from_items(cur, batch_size, max_batches, cursor, now)`

It orders by `(creator_type, creator_id)`, returns `next_cursor`, and writes
only `creator_registry` via idempotent upserts.

### 4.1 Preflight

- Confirm migration is applied and registry is empty or has a known row count.
- Capture registry row count and `max(updated_at)` as the rollback baseline.
- Confirm `items` and `tracked_creators` are readable.
- Confirm no concurrent backfill is running.
- Estimate scope with section 3/4 of the diagnostic script.

### 4.2 Recommended bounds

- `batch_size`: 100–250 creators per invocation.
- `max_batches`: 1 per invocation.
- One invocation = one bounded transaction and one commit.
- Persist `next_cursor` externally (job record/table or operator log) after
  each commit.
- Run outside peak hours; no Roblox API requests are made.
- Stop immediately on lock timeout, statement timeout, unexpected row-count
  regression, or cursor non-advancement.

### 4.3 Invocation outline

```python
from creator_registry import refresh_from_items

result = refresh_from_items(
    cur,
    batch_size=200,
    max_batches=1,
    cursor=saved_cursor,   # None for the first run
)
# Commit only after the bounded batch succeeds.
conn.commit()
# Persist result["next_cursor"] and result["done"].
```

Do not loop this into a full catalog backfill automatically.

### 4.4 Per-batch verification

```sql
SELECT count(*) AS registry_rows FROM public.creator_registry;

SELECT creator_type, count(*) AS creators
FROM public.creator_registry
GROUP BY 1 ORDER BY 2 DESC;

SELECT count(*) AS current_name_in_previous_names
FROM public.creator_registry
WHERE jsonb_typeof(previous_names) = 'array'
  AND display_name IS NOT NULL
  AND previous_names @> jsonb_build_array(display_name);

SELECT creator_id, count(*) AS rows
FROM public.creator_registry
GROUP BY creator_id
HAVING count(*) > 1
ORDER BY creator_id
LIMIT 20;
```

Stop if current-name residue is non-zero, duplicate composite keys appear
(should be impossible), or registry rows fall unexpectedly.

### 4.5 Backfill rollback

There is no per-run marker column. Before backfill, take a backup or record the
exact registry row count/keys. Rollback options, in order of preference:

1. Restore `creator_registry` from the pre-backfill dump.
2. If approved and the registry was empty before the run, `TRUNCATE
   public.creator_registry;`.
3. Do not delete rows by guesswork; the registry has no backfill-run ID.

## 5. User/Group numeric-ID collision verification

Code-level guarantees:

- Primary key is `(creator_type, creator_id)`; identical numeric IDs under
  `User` and `Group` are separate rows.
- `resolve_creator_type()` never assigns a tracked type from the numeric ID
  alone. It requires a case-insensitive creator-name match.
- If both types are present for one numeric ID, the item stays `unknown`
  unless its own `creator_type` is present or one name match is unambiguous.
- Tests covering composite identity and name-match resolution are in
  `test_phase2_milestone2.py`; the PostgreSQL integration suite also covers
  composite identity and passed in CI.

Production verification (not executed): sections 7a–7d of
`diagnostics/production_readiness_m2.sql`.

Hygiene note: if a creator is first stored as `('unknown', id)` and later
resolves to `('User', id)` or `('Group', id)`, the old unknown row is not
deleted automatically. That is not a User/Group merge, but it is duplicate
evidence and must be reviewed before any cleanup. Section 7c lists these rows.
No cleanup should be run without approval.

## 6. Provenance and unknown-evidence verification

- Missing `creator_registry` => `creator_evidence()` returns
  `available: false`, `reason: "missing_table"`.
- Missing verification values => `verification_status = "unknown"`,
  `verification_provenance = "missing"`.
- Missing type evidence => `creator_type = "unknown"`,
  `type_provenance = "missing"`.
- Registry counts are still returned when the table exists, even if every row
  is unknown; the `missing` block reports `registry_type_missing`.

Production verification (not executed): sections 4, 5, and 6.

## 7. `!golden_hour` 48-hour velocity diagnosis (no API increase)

### 7.1 What the command requires

`golden_hour_metrics()` selects `items` where
`created_at >= NOW() - INTERVAL '48 hours'`, then requires:

- at least two `item_history` rows in the last 48 hours,
- `favorite_count IS NOT NULL`,
- a first-to-last snapshot span of at least 1 hour.

If any condition fails, the item is shown as unmeasured. This is correct
fail-closed behavior, not fabrication.

### 7.2 Code-level findings that can suppress measurements

1. **The 48h population is defined by `items.created_at`**, which is the
   Roblox catalog item creation timestamp, not the time this system discovered
   or stored the item. If the catalog is dominated by older assets, the recent
   population can be zero or very small even while scanning is healthy.
2. **Snapshot cadence may be limited to one stored sample per item per date.**
   Production existence and uniqueness of `idx_item_history_daily` are
   **checked in section 2b, not assumed**. If it exists as a unique index on
   `(item_id, (snapshot_at::date))`, the scheduled 09:30/15:30/21:30 top-ups
   re-run insertion but `ON CONFLICT DO NOTHING` discards same-date rows, so two
   distinct dates are required for a velocity measurement. If the index is
   absent, same-day duplicates may exist; section 8c measures that directly.
3. **Top-ups re-fetch rather than skip already-captured items.** When the
   unique index exists, the snapshot selection query does not exclude items
   already captured today; the index absorbs the conflict. This is an efficiency
   issue and does not by itself create velocity data.
4. **Coverage is measured from stored rows, not the attempted-insert counter.**
   `snapshot.py` increments its `inserted` log counter by the attempted batch
   size even when `ON CONFLICT DO NOTHING` discards rows. That counter is not
   evidence; sections 8 and 9 query stored `item_history` rows only.
5. **Item ingestion/fetch coverage matters.** A recent item that is never
   fetched successfully, or is outside the tiered snapshot selection, has no
   history. Throttling, restarts, and the fetch deadline can reduce coverage.
6. **Clock/timezone skew** between `items.created_at` (`TIMESTAMP`) and
   `item_history.snapshot_at` comparisons can move items in or out of the 48h
   window. The diagnostic script checks recent counts and snapshot-before-
   creation anomalies.

These are candidate causes. They must be confirmed with production data; no
value is assumed here.

### 7.3 Diagnostic interpretation matrix

Run sections 8 and 9 of `diagnostics/production_readiness_m2.sql`:

- `recent_items = 0` => the 48h `created_at` population is empty. This is a
  product-definition/window issue, not a snapshot correctness failure.
- `recent_items > 0`, all `no_snapshots` => snapshot selection or fetch
  coverage never reached those items.
- mostly `one_snapshot` => daily cadence has not produced a second date yet,
  or runs were missed.
- `two_plus_snapshots > 0` but `span_too_short > 0` => same-day duplicates or
  clock anomalies; compare section 2b (index existence/uniqueness), section 8c
  (stored duplicates), and section 9d.
- `idx_item_history_daily_exists = false` => do not describe cadence as
  one-per-day; review stored coverage and same-day duplicate counts first.
- `velocity_eligible > 0` but the Discord command shows none => check session
  timezone, database target, and whether the command is reading the intended
  database.

No code changes and no additional Roblox API requests are made by this
diagnosis.

## 8. Steps requiring explicit approval

1. Providing/using authorized read-only production or replica credentials.
2. Running any diagnostic against the production primary instead of a replica.
3. Applying `migrations/2026-11-05_creator_registry.sql`.
4. Running any registry backfill, including a single bounded batch.
5. Any write, cleanup, merge, or deletion of `('unknown', id)` registry rows.
6. Dropping `creator_registry` or `items.creator_type` as rollback.
7. Changing `!golden_hour`, snapshot cadence, the daily unique index, or the
   48h window definition.
8. Any deployment or production restart beyond the already-completed deploy.

## 9. Deliverable summary

- Read-only SQL: `diagnostics/production_readiness_m2.sql`.
  - Opens `BEGIN READ ONLY`, reports `transaction_read_only`, and rolls back.
  - Checks `idx_item_history_daily` existence/uniqueness instead of assuming it.
  - Measures snapshot coverage from stored `item_history` rows only; the
    attempted-insert counter in `snapshot.py` is explicitly not used.
- Production findings: **not available** in this environment; no credentials
  were requested, printed, or stored.
- Migration plan: prepared above; not applied.
- Backfill plan: bounded and resumable; not started.
- Verification/rollback: prepared above.
- Collision and provenance: code/tests verified; production data pending.
- `!golden_hour`: code-level causes identified; production diagnosis pending.

## 10. Exact next approval required

**Approve running `diagnostics/production_readiness_m2.sql` against the
authorized read-only replica (preferred) using the host's existing read-only
DSN.** If no replica is available, the alternative approval is to run the same
strictly read-only script against the production primary. This approval does
not cover migration, backfill, writes, rollback, merge, or deployment.
