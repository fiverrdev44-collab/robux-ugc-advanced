# F-07/F-08 Remediation Evidence — Creator Identity Integrity

## A. Final SHA

- Remediation code commit under certification:
  `acbc47ade629680778191e36bf59c200ba17859f`
- Branch: `fix/f07-f08-creator-identity-integrity`
- Baseline: `4618c67eae7c4d6b2287c16e9ad5f6596ad73d71`
- Frozen audit branch: `df325a3d0b584b7933dd55ca035380b8d0369531`
  (untouched)

## B. Root causes

- **F-07:** `tracked_creators.creator_id` was the sole primary key. User 123
  and Group 123 could not coexist. `ensure_creators()` checked only the numeric
  ID, `mark_scanned()` updated only the numeric ID, and the old
  `creator_type DEFAULT 'User'` silently turned missing types into users.
- **F-08:** Creator Brain grouped items by `lower(creator_name)` and re-queried
  by display name. Two unrelated creators with the same name were merged, and
  a rename fragmented one creator into two identities.
- **ORACLE:** `trend_creator_cohorts` used `UNIQUE (cohort_id, creator_id)` and
  `trend_item_observations` stored only a numeric creator reference, carrying
  the same User/Group ambiguity into frozen cohorts and observations.

## C. Changed files

- `creator_identity.py` — canonical User/Group/unknown helpers, composite key,
  and composite-PK detection.
- `creator_tracker.py` — typed upserts, conflict targets, batch selection,
  `mark_scanned(creator_id, creator_type)`, no silent User default, unknown
  types excluded from scanning.
- `creator_brain.py` — claims and statistics grouped by
  `(creator_type, creator_id)`; identity coverage disclosure; no display-name
  grouping.
- `creator_registry.py` — tracked-name type inference only when exactly one
  creator type matches; ambiguous matches remain unknown.
- `database.py` — fresh-schema `tracked_creators` uses the composite primary
  key and `creator_type DEFAULT 'unknown'`.
- `trend_cohorts.py` — ORACLE ELITE/EMERGING/CONTROL selection grouped and
  excluded by typed creator keys; cohort inserts use `creator_key`.
- `trend_radar.py` — observations persist `creator_type`.
- `oracle_worker.py` — cohort dedupe and observation writes use typed
  identities; unknown types are skipped and counted.
- `migrations/2026-11-08_f07_creator_identity_expand.sql` — additive
  normalization, provenance, generated key, indexes.
- `migrations/2026-11-08_f07_creator_identity_contract.sql` — guarded composite
  primary-key replacement.
- `migrations/2026-11-08_f07_oracle_identity_additive.sql` — observation
  `creator_type`, cohort `creator_key`, typed uniqueness.
- `test_f07_f08_creator_identity.py` — 13 offline identity tests.
- `test_f07_f08_creator_identity_pg.py` — 5 disposable-PostgreSQL migration and
  behavior tests.
- `test_creator_intelligence_phase1.py`, `test_project_oracle.py`,
  `tests/test_oracle_worker.py` — fixtures updated to typed identities.
- `.github/workflows/survival-tests.yml`,
  `.github/workflows/phase2-postgres.yml` — branch triggers and new test steps.

## D. Migration plan

### D.1 Schema changes

1. `2026-11-05_creator_registry.sql` (existing, required if not already applied):
   adds `items.creator_type` and the composite `creator_registry`.
2. `2026-11-08_f07_creator_identity_expand.sql`:
   - adds `type_provenance`;
   - drops the old `creator_type DEFAULT 'User'`;
   - normalizes `User`/`Group`, and maps NULL/other values to explicit
     `unknown`;
   - sets `creator_type NOT NULL DEFAULT 'unknown'`;
   - adds the generated `creator_key = creator_type || ':' || creator_id`;
   - adds identity and scan indexes.
3. `2026-11-08_f07_creator_identity_contract.sql`:
   - preflights duplicate composite identities;
   - replaces the numeric-only primary key with
     `PRIMARY KEY (creator_type, creator_id)`;
   - adds a unique `creator_key` index.
4. `2026-11-08_f07_oracle_identity_additive.sql`:
   - adds `trend_item_observations.creator_type`;
   - adds `trend_creator_cohorts.creator_key` (`User:123`, `Group:123`, or
     explicit `unknown:123`);
   - replaces numeric-only cohort uniqueness with
     `UNIQUE (cohort_id, creator_key)`;
   - leaves frozen `creator_id`/`creator_type` values unchanged.

### D.2 Data preservation and ambiguity

- Existing rows are never deleted.
- Existing `User`/`Group` values are preserved and marked `legacy_stored`;
  the old default-`User` origin cannot be proven and is documented.
- NULL or non-User/Group values become explicit `unknown` and are excluded from
  identity-specific Creator Brain/ORACLE comparisons.
- ORACLE rows without a verified type get `unknown:<id>` and are skipped by
  typed discovery; historical types are not guessed.
- Historical `trend_item_observations` rows keep `creator_type` NULL.

### D.3 Deployment order (pending approval; never automatic)

1. Back up the database and run the preflight inventory queries.
2. Apply `2026-11-05_creator_registry.sql` if `items.creator_type`/registry are
   absent.
3. Apply `2026-11-08_f07_creator_identity_expand.sql`.
4. Apply `2026-11-08_f07_oracle_identity_additive.sql`.
5. Apply `2026-11-08_f07_creator_identity_contract.sql` in an approved window.
6. Deploy the remediation code.
7. Verify row counts, composite PK, cohort uniqueness, and command health.

### D.4 Rollback

- Expand/oracle rollback: drop the derived `creator_key`/`creator_type`
  columns and new indexes; original rows remain.
- Contract rollback: the provided guard raises an exception if typed User/Group
  collisions now exist. After archiving/backup resolution, drop the composite
  primary key and restore `PRIMARY KEY (creator_id)`.
- Cohort rollback requires restoring `UNIQUE (cohort_id, creator_id)` only after
  typed collisions are resolved.
- Migrations are not run at bot startup.

### D.5 Approval status

No migration was applied to production, staging, or the local environment.
Disposable-PostgreSQL execution is the only migration evidence in this report.

## E. Verification evidence

- **Numeric collision:** PostgreSQL test inserts User 123 and Group 123; both
  rows coexist. A duplicate User 123 insert fails under the composite PK.
- **Typed tracking:** `mark_scanned(123, "User")` updates only the User row;
  the Group row keeps `last_scanned IS NULL`.
- **Discovery/idempotency:** repeated `ensure_creators` calls add zero rows;
  User/User and Group/Group identities remain unique.
- **Unknown types:** `ensure_creators` stores `unknown` with `verified=false`;
  `search_creator`, `search_creator_complete`, and `verify_creator_badge`
  refuse to guess a User.
- **Display names:** User 100 `StarWorks` and Group 200 `StarWorks` remain two
  creators; User 300 `STARWORKS` remains a third; a rename of User 100 stays
  one typed identity.
- **Creator Brain:** typed cohort and comparison queries return only User/Group
  identities; median favorites and segment counts remain correct; unresolved
  coverage is reported separately (fixture: 80% typed, 1 unresolved item).
- **Registry:** tracked-name type inference returns a type only when exactly
  one distinct type matches; ambiguous User/Group name matches stay unknown.
- **ORACLE:** ELITE/EMERGING/CONTROL selection is grouped by
  `(creator_type, creator_id)`; User/Group 123 both scan; observations persist
  `creator_type`; cohort uniqueness uses `creator_key`.
- **Compatibility:** all 90 command contracts pass, public/restricted callback
  suites pass, and all 16 F-05 API safety tests remain green.

## F. Test results

- Complete offline suite: **34/34 scripts passed**.
- F-07/F-08 offline suite: **13/13 passed**.
- Disposable PostgreSQL F-07/F-08 suite: **5/5 passed** (CI).
- Creator intelligence suite: **22/22 passed**.
- Project ORACLE: **all passed**; ORACLE worker: **20/20 passed**.
- F-05 API safety: **16/16 passed**.
- Command contracts: **90/90 passed**.
- GitHub Actions:
  - Survival Intelligence Tests (`offline-regression`): **success**
    https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42483423004
  - Phase 2 PostgreSQL Integration (`phase2-postgres`): **success**
    https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42483423124
  - Confirmed steps: `Run F-07/F-08 creator identity regressions` and
    `Run F-07/F-08 creator identity PostgreSQL migrations` both succeeded.

## G. Independent verdicts

- `F-07 CLOSED — VERIFIED`
- `F-08 CLOSED — VERIFIED`

Both verdicts are supported by composite-key migration execution on disposable
PostgreSQL, typed tracking tests, Creator Brain separation/rename/coverage
tests, and preserved command/F-05 regressions.

## H. Overall release verdict

**Overall VANTA 73 certification remains NO-GO** until the remaining
independent findings and live operational gates are resolved. No merge,
deployment, production migration, M4 activation, or frozen-branch change was
performed.
