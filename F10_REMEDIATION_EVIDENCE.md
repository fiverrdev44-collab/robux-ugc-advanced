# F-10 Remediation Evidence — Database Timestamp Integrity

## A. Final SHA

- Remediation code commit under certification:
  `e64ec4ae233b525162f71bf4e970afdb7eaf37b4`
- Branch: `fix/f10-timestamp-integrity`
- Baseline: `7da87443916340039a2544de4ac2767e52256ef5`
- Frozen audit branch: `df325a3d0b584b7933dd55ca035380b8d0369531`
  (untouched)

## B. Root causes

- The legacy catalog tables used naive `TIMESTAMP` columns for absolute
  instants (`items.created_at/updated_at/fetched_at`,
  `item_history.snapshot_at`, and tracking/ledger timestamps).
- Writers used `CURRENT_TIMESTAMP`/`now()` or Python UTC values, but the
  column type discarded the offset. Correctness therefore depended on the
  PostgreSQL session TimeZone remaining UTC.
- Several Python paths mixed naive and aware datetimes or relied on
  `datetime.utcnow()`; `date.today()` was used for a UTC reporting boundary.
- The daily snapshot uniqueness expression `(snapshot_at::date)` depended on
  the database session timezone after a `TIMESTAMPTZ` migration would be
  applied.
- Several SQL day/week groupings used implicit casts (`created_at::date`,
  `sale_time::date`, `date(snapshot_at)`) that change with session timezone.

## C. Timestamp inventory

| Area | Columns | Before | Intended meaning | Remediation |
|---|---|---|---|---|
| Catalog | `items.created_at`, `updated_at`, `fetched_at` | `TIMESTAMP` | Roblox publication / DB observation | `TIMESTAMPTZ`; explicit UTC conversion |
| Favorites history | `item_history.snapshot_at` | `TIMESTAMP` | Observation instant | `TIMESTAMPTZ`; UTC distinct-day unique index |
| Enrichment retry | `failed_items.last_tried` | `TIMESTAMP` | Retry clock | `TIMESTAMPTZ` |
| Search/learning | `search_suggestions.fetched_at`, `learned_keywords.learned_at` | `TIMESTAMP` | Observation/learning instant | `TIMESTAMPTZ` |
| Accounts | `user_profiles.first_seen/last_active`, `saved_consultations.created_at`, `watchlist.added_at/last_checked`, `competitor_tracking.added_at`, `item_tracker.added_at`, `my_portfolio.added_at` | `TIMESTAMP` | User/event instants | `TIMESTAMPTZ` |
| Launch ledger | `launch_ledger.launched_at`, `last_synced` | `TIMESTAMP` | Launch/activity instants | `TIMESTAMPTZ` |
| Creator/recovery | `creator_patterns.updated_at`, `tracked_creators.last_scanned/added_at` | `TIMESTAMP` | Tracking/recovery clock | `TIMESTAMPTZ` |
| Predictor | `predictor_weights.trained_at` | `TIMESTAMP` | Training instant | `TIMESTAMPTZ` |
| Sales | `my_sales.sale_time` | already `TIMESTAMPTZ` | Marketplace transaction instant | Preserved; offsets tested |
| Sales date | `my_sales.sale_date` | `DATE` | UTC calendar date | Preserved |
| ORACLE/search/experiments | `trend_*`, `search_*`, `recommendation_ledger`, `experiment_controls` | already `TIMESTAMPTZ` | Event/observation instants | Preserved |

`time_utils.py` now makes provenance explicit:

- `ensure_utc` converts aware values and returns `None` for naive values of
  unknown provenance.
- `db_utc` is only for legacy UTC-session database values.
- `utc_now`, `utc_day`, `age_days`, `within_window`, `deadline_after` replace
  local/naive arithmetic.

## D. Changed files

- `time_utils.py` — explicit UTC/provenance helpers.
- `database.py` — fresh schemas use `TIMESTAMPTZ`; daily index uses
  `(snapshot_at AT TIME ZONE 'UTC')::date`.
- `migrations/2026-11-08_f10_timestamp_integrity.sql` — approval-gated
  conversion, preflight, duplicate detection, UTC index replacement and
  rollback guidance.
- `scheduler.py` — snapshot catch-up uses aware UTC and safe legacy coercion.
- `convergence_engine.py`, `creator_tracker.py`, `launch_ledger.py` — safe
  naive/aware handling for DB timestamps and cooldowns.
- `commands_intel.py`, `commands_supercomputer.py`, `selftest.py`, `bot_core.py`
  — removed `utcnow()`/naive freshness arithmetic; explicit UTC conversion.
- `confidence.py`, `market_velocity.py`, `trend_cohorts.py`, `data_audit.py`,
  diagnostics SQL — explicit UTC day/week expressions.
- `title_predictor.py` — `trained_at TIMESTAMPTZ`.
- `.github/workflows/survival-tests.yml`,
  `.github/workflows/phase2-postgres.yml` — F-10 branch triggers and tests.
- `test_f10_timestamp_integrity.py` — 10 offline contract tests.
- `test_f10_timestamp_integrity_pg.py` — 5 disposable-PostgreSQL tests.

No Discord commands, creator identities, API budgets, or security controls
were changed.

## E. Database migration plan

### E.1 Preflight

- Record row counts for `items` and `item_history`.
- Report future-dated item/history rows for operator review.
- Detect duplicate `(item_id, UTC calendar day)` history rows.
- Inspect the current `idx_item_history_daily` definition and dependent
  indexes.
- Abort before structural changes if duplicate UTC days exist.

### E.2 Conversion

- Convert only `timestamp without time zone` columns, and only if the table and
  column exist (idempotent helper).
- Use explicit `USING column AT TIME ZONE 'UTC'`; never rely on session
  TimeZone.
- Drop the session-dependent daily index and recreate it with
  `(snapshot_at AT TIME ZONE 'UTC')::date` after the type change.
- Preserve all rows and values; no deletes, truncates or fabricated timestamps.
- Wrap the operation in one transaction so failure rolls back both type and
  index changes.

### E.3 Idempotency and locks

- Re-running the migration skips already-converted columns and recreates the
  UTC index safely.
- `ALTER TABLE ... TYPE` rewrites tables and takes `ACCESS EXCLUSIVE` locks;
  schedule a maintenance window. No automatic startup execution.

### E.4 Rollback

- Drop the UTC daily index first.
- Reverse the type changes with `USING column AT TIME ZONE 'UTC'`.
- Recreate the old `(snapshot_at::date)` index only after the type reversal.
- Values remain the same UTC wall-clock instants; no data loss.
- Rollback is manual and approval-gated.

### E.5 Deployment sequencing

1. Backup and preflight review.
2. Apply the F-10 migration in an approved maintenance window.
3. Deploy code (the codebase is also tolerant of legacy naive values through
   `db_utc`, but the migration is required for durable type correctness).
4. Verify column types, UTC index, row counts, snapshot freshness, and ORACLE
   windows.

No production migration was executed.

## F. Test evidence

- Complete offline suite: **36/36 scripts passed**.
- F-10 offline suite: **10/10 passed**.
- F-10 disposable PostgreSQL suite: **5/5 passed** (CI and local embedded
  PostgreSQL rehearsal).
- F-09 ORACLE recovery: **12/12 offline + 3/3 PostgreSQL** passed.
- F-07/F-08 identity: **13/13 offline + 5/5 PostgreSQL** passed.
- F-05 API safety: **16/16 passed**.
- ORACLE worker: **20/20 passed**; Project ORACLE passed.
- Creator intelligence: **22/22 passed**.
- Command contracts: **90/90 passed**.
- Public and restricted callback suites passed.

Final code-commit CI:

- Survival Intelligence Tests (`offline-regression`): **success** —
  https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42515680388
  - Confirmed step: `Run F-10 timestamp integrity regressions`.
- Phase 2 PostgreSQL Integration (`phase2-postgres`): **success** —
  https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42515682092
  - Confirmed step: `Run F-10 timestamp integrity PostgreSQL migration`.

## G. Data preservation

- PostgreSQL rehearsals preserve row counts and UTC wall-clock values.
- User/Group creator identity was not touched.
- `my_sales.sale_time` offsets are preserved and normalized to the same
  instant; `sale_date` remains the UTC date.
- `item_history` rows remain chronologically ordered; duplicate UTC days are
  detected before index replacement and abort without changing the table.
- Rollback test restores naive UTC values and the original index without data
  loss.
- No production data was modified.

## H. Limitations

- The production migration has not been applied; deployment approval is
  required.
- Historical naive values are interpreted as UTC based on the repository's
  documented UTC session policy (`SET TimeZone = 'UTC'` / connection options).
  Out-of-band writes with unknown local timezone cannot be proven; the preflight
  future-row report must be reviewed and the migration stopped if anomalies
  are found.
- The type conversion rewrites tables and requires `ACCESS EXCLUSIVE` locks;
  downtime depends on table size.
- Disposable PostgreSQL is the only database rehearsal; no production
  connection or production migration was used.
- Non-critical legacy tables are migrated when present and skipped when
  absent; missing-column provenance was not fabricated.

## I. F-10 verdict

`F-10 CLOSED — VERIFIED`

Critical absolute instants are now timezone-aware UTC, legacy values are
converted only under documented UTC provenance with duplicate/anomaly
preflight, daily snapshot uniqueness is explicit UTC, scheduling and analytics
are tested across non-UTC sessions and boundary cases, sales instants and
deduplication are preserved, and the migration is rehearsed with rollback and
idempotency evidence.

## J. Final release verdict

**Overall VANTA 73 certification remains NO-GO** until the remaining audit
findings and live operational release gates are resolved. No merge, deployment,
production migration, M4 activation, new command, or frozen-branch modification
was performed. `PHASE2_M4_ENABLED` remains off.
