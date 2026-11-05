# VANTA 73 — Phase 2, Milestone 2: Creator Discovery & Intelligence

Status: implemented on `feat/phase2-market-intelligence` (follows M1).
No production writes, no deployment, no autonomous learning.

## Constraints honoured
- No paid APIs or new live Roblox requests; creator discovery reuses stored
  catalog rows.
- Existing Discord commands preserved; `!emote_title` untouched.
- Phase 1 evidence safeguards retained; favorites ≠ sales; missing stays missing.
- `ASTRA_LEARNING_IN_GENERATION` remains **OFF**.

## Final acceptance corrections

1. **Composite creator identity**: the additive migration adds nullable
   `items.creator_type`. Refresh uses the item's catalog type when present;
   otherwise it uses a tracked creator's type only when the display name
   corroborates the composite identity. It never infers a type from a numeric
   ID alone; otherwise the type stays `unknown`.
2. **Idempotent name history**: `previous_names` is built with a deduplicated
   JSONB aggregation that excludes the current display name. Repeated
   identical refreshes do not duplicate history; `first_seen`/`last_seen` are
   preserved; unknown verification does not overwrite established verification.
   `updated_at` is the documented refresh metadata that may change.
3. **Resumable refresh**: `refresh_from_items(..., cursor=...)` returns
   `next_cursor` and `done`. Ordering is stable by
   `(creator_type, creator_id)`; each key is visited once per sweep. Callers
   persist the cursor between process invocations. New keys below a cursor are
   picked up by the next full sweep from `None`.
4. **Verification uncertainty**: `creator_tracker._to_item()` preserves missing
   `creatorType` as `None` and missing `creatorHasVerifiedBadge` as `None`
   (never `False`/`User`). `upsert_items()` writes tri-state verification and
   preserves known verification when incoming evidence is unknown. Historical
   NULL values remain unknown, not confirmed nonverified.
5. **Deterministic comparison sampling**: `creator_comparison()` orders by
   `i.id` within the category/age window before `LIMIT`. The sample is
   reproducible for unchanged data but remains a sampled convenience sample,
   not representative of the Marketplace.
6. **Real PostgreSQL tests**: `.github/workflows/phase2-postgres.yml` runs a
   disposable `postgres:16` service, applies the M2 migration, and exercises
   registry refresh/upserts, idempotency, cursors, collisions, tri-state
   verification, snapshot coverage, comparisons, missing-table behavior, and
   rollback using synthetic data only.
7. **Reconciled with main** before final CI; M1 changes are preserved.

---

## 1. Creator coverage audit

**Status: not executed in this environment — `DATABASE_URL` is unset.**
Coverage is therefore not estimated or fabricated. The read-only audit is
provided at:

`diagnostics/creator_coverage_audit.sql`

It measures, without writes:
1. Items with/without stable creator IDs and unique creator IDs.
2. Known creator types from `tracked_creators`.
3. Items with known vs unknown creator type.
4. Verified / nonverified / unknown verification (NULL ≠ nonverified).
5. Creator × category distribution.
6. Snapshot coverage across all items.
7. Recent 48-hour items with 0/1/2+ snapshots and valid ≥1h growth windows.
8. Observation cadence from `trend_item_observations`.
9. Recent `trend_scan_runs` collection runs.
10. Recent items with fewer than two snapshots (collection-gap candidates).

Run it on a replica/staging DB and report actual numbers before judging
coverage.

## 2. Creator registry (additive)

Migration: `migrations/2026-11-05_creator_registry.sql` (additive; not applied).
It creates `creator_registry` and adds nullable `items.creator_type`; it does
not backfill historical types from numeric IDs.

Primary key: `(creator_type, creator_id)`.
- Never merges different creators that share a display name.
- User and group IDs with the same numeric value remain separate when their
  types are known.
- Missing type → `unknown`; missing verification → `unknown` (never confirmed
  nonverified).
- `display_name` is the latest observed name; `previous_names` preserves
  earlier names across rescans.
- Stores first/last observation, item count, category counts, price buckets,
  median favorites/price/age, snapshot-item counts, missing-favorite item
  counts, verification provenance, and type provenance.

Module: `creator_registry.py`
- `build_registry_rows()` — pure item-level aggregation, deduplicates repeated
  marketplace rows by `(creator_type, creator_id, item_id)` keeping the latest
  observation.
- `upsert_registry()` — idempotent `ON CONFLICT` upsert; preserves `first_seen`,
  appends renamed display names, and does not downgrade known verification to
  unknown.
- `refresh_from_items()` — resumable, keyset-batched creator refresh from
  stored `items`; no API calls.
- `discover_nonverified()` — returns stored nonverified/unknown creators with
  `source="stored_catalog"` and `live_api_calls=0`.

### Type resolution
`items` does not store `creator_type`. The registry resolves it from
`tracked_creators` where available; otherwise the type is `unknown` with
`type_provenance="missing"`. It does not guess User/Group and does not merge
unknown-type creators into a known type.

## 3. Discovery

Expansion is **catalog-first**:
- Already-collected item rows are aggregated into the registry, including
  nonverified and unknown-verification creators.
- No live API budget increase, no new requests, no account rotation.
- Refresh is deduplicated and idempotent; re-running the same batches does not
  double counts.
- Rate-limit/Retry-After behavior of the existing tracker is unchanged; this
  milestone adds no new network path.

## 4. Creator comparisons

`summarize_comparison()` is category-aware and reports:
- Established (≥5 items) vs emerging (<5).
- Verified / nonverified / unknown verification.
- Top / average / underperforming creators by median favorites (within the
  sampled category).
- Items, median favorites, median price, median age, snapshot-item counts.
- Creator item concentration (top creator share).
- Missing favorites and creators without snapshots.

Explicit disclaimers:
- Sampled convenience population, **not probability-representative** of the
  Roblox Marketplace.
- Favorites are not verified sales.
- Growth is only inferable where valid snapshots exist.
- Associations are not causal.

`creator_comparison()` bounds the sample by a day window (default 180) and a
row limit (default 5,000). It is read-only.

## 5. Snapshot coverage diagnostics

`snapshot_coverage()` measures recent items with 0/1/2+ snapshots and items with
≥2 snapshots spanning ≥1 hour. It returns a coverage percentage and a
`missing_evidence` flag; it does not fabricate velocity.

Why `!golden_hour` may lack history cannot be determined from the database
alone: collection cadence, item-selection rules, API failures, and missing
historical data produce similar symptoms. The audit SQL separates observations
so those causes can be investigated with real counts.

Budget-neutral improvement proposals (not implemented as increased frequency):
1. Prioritize items already in the 48-hour window during existing snapshot runs.
2. Reuse snapshots already collected by ORACLE/tracker runs; avoid duplicate
   requests.
3. Ensure the daily unique-snapshot index does not suppress useful intraday
   observations needed for the one-hour velocity rule (review, do not change
   cadence silently).
4. Report coverage honestly when velocity is unavailable.

## 6. Milestone 3 evidence interface

`creator_evidence(cur, family=...)` returns a read-only bundle for `!converge`:
- `registry`: creator counts by verification and missing type.
- `comparison`: category-aware segments and concentration.
- `snapshot_coverage`: recent coverage and missing-evidence flag.
- `sample_sizes`: comparison items/creators and snapshot items.
- `missing`: snapshot-growth gaps and missing type counts.
- `contract`: favorites-not-sales, non-representative sampling,
  growth-requires-snapshots, no-invented-demand.

Milestone 3 must still add verified sales attribution and opportunity scoring;
this milestone does not implement that engine.

## 7. Performance / API-budget analysis

- Registry refresh reads `items` and `tracked_creators`; snapshot-item counts
  use the existing `item_history(item_id)` index. Batches are by creator key
  (`creator_type, creator_id`) with a keyset, so refreshes are resumable.
- No live Roblox requests or paid APIs.
- Comparisons are bounded by window and row limit.
- The snapshot-coverage query is bounded to recent items.
- Optional index for golden-hour recent items:
  `migrations/2026-11-05_golden_hour_indexes.sql` (already provided in M1).
- No registry migration is applied automatically.

## 8. Tests

`test_phase2_milestone2.py` — **24/24 offline tests**:
- Identity collisions by name; user vs group numeric IDs; composite type
  resolution with and without name corroboration.
- Refresh SQL requires the composite name match; no ID-only inference.
- Name changes and duplicate-free previous-name history (SQL assertion).
- Missing verification → unknown; verified/nonverified tri-state.
- `creator_tracker._to_item()` preserves missing type/verification as None;
  ingestion upsert preserves composite type and tri-state.
- Missing creator IDs reported, not registered.
- Duplicate marketplace rows collapsed to one item.
- Category/price/age/snapshot aggregation; missing favorites.
- Partial rows with missing fields.
- Idempotent build.
- Keyed upsert SQL, first/last-seen preservation, deduplicated previous names.
- Resumable batched refresh and explicit cursor across separate invocations.
- Nonverified discovery from stored data (`live_api_calls=0`).
- No live API imports/paths in the registry module.
- Snapshot coverage counts and missing evidence.
- Comparison segments, nonverified/underperformers, unequal ages, concentration.
- Deterministic comparison SQL ordering; pre-migration type fallback.
- Empty comparison honesty.
- Milestone 3 evidence contract.

**Real PostgreSQL integration** (`test_phase2_pg_integration.py`, CI-only):
migration success; composite identity and User/Group collision; registry
refresh/upserts; repeated-upsert idempotency and name history; multiple
independent refresh invocations; verification tri-state; tracker ingestion;
snapshot coverage SQL; category comparison SQL; missing-table behavior before
migration; transaction rollback. Synthetic data only; no production
credentials. Local runs skip without `DATABASE_URL`.

**No staging PostgreSQL was available, so write-based persistence and SQL
execution were tested with fake cursors only.** The actual migration, upserts,
and coverage query remain to be run on staging.

## 9. Known limitations

- The coverage audit remains unexecuted locally (`DATABASE_URL` unavailable);
  CI PostgreSQL tests use synthetic data, not production coverage.
- Historical items have `creator_type = NULL`; an item's type is known only
  when the catalog supplied it or a tracked creator's name corroborates it.
  User/Group numeric collisions cannot be separated where the type is unknown.
- `creator_tracker` discovery still starts from verified creators; this
  milestone expands registry coverage from stored rows without adding a
  nonverified live crawl (API budget unchanged).
- Comparison samples are deterministic convenience samples, not
  probability-representative.
- Snapshot growth is only available for items with ≥2 snapshots spanning ≥1
  hour; coverage causes require the audit SQL on staging.
- Verified sales attribution is not implemented; favorites remain engagement
  evidence only. Learning stays off.

## 10. Merge readiness

**Ready for independent review; not merged.** The registry is additive, the
network budget is unchanged, and Phase 1 safeguards are preserved. The
disposable-PostgreSQL CI job verifies migration, composite identity, idempotent
upserts, cursor resumption, tri-state verification, coverage, comparisons,
missing-table behavior, and rollback. Before a controlled merge, run
`diagnostics/creator_coverage_audit.sql` on a replica/staging DB for real
coverage counts and review the registry refresh plan. No production data was
mutated during development.
