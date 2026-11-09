# VANTA 73 — Final Release Candidate Certification

## A. Release candidate

- **Production baseline verified:** `7703b26f1cda063b2c8e2bebd3addb3a00bbe6d2`
  (`origin/main`; local `main` was behind and was not used)
- **Integration branch:** `release/vanta73-final-certification-rc`
- **Final integration SHA:** `e57ec5ad3155472502d251dd1ebbd8272dedd108`
- **Merge commit:** `a3fb9db041112f0610e38eb379e3e54658b159f5`
- **Frozen audit checkpoint:** `df325a3d0b584b7933dd55ca035380b8d0369531`
  (untouched)
- **Merge summary:** `fix/f18-sales-source-authentication` was merged into a
  branch created from the verified production HEAD with normal Git ancestry.
  No conflicts were encountered; the merge used the `ort` strategy. No
  force-push, production merge, or deployment occurred.
- No Avatar Background feature branch was merged.

## B. Remediation matrix

| Finding | Integrated fix | Independent evidence |
|---|---|---|
| F-05 | Shared Roblox transport, global 429 circuit, Retry-After/date parsing, session-preserving requests, no rotation | `test_f05_api_safety.py` 16/16; offline and CI |
| F-07 | Composite `(creator_type, creator_id)` identity, typed tracking/discovery, migration | `test_f07_f08_creator_identity.py` 13/13; PostgreSQL 5/5 |
| F-08 | Creator Brain typed cohorts, no display-name grouping, unresolved coverage disclosure | Same identity suites; CLI/callback regressions |
| F-09 | Explicit discovery outcomes, durable `creator_patterns` recovery, scan-run reuse, idempotent observations | `test_f09_oracle_recovery.py` 12/12; PostgreSQL 3/3 |
| F-10 | UTC `TIMESTAMPTZ` conversion, explicit UTC-day index, timezone-safe scheduling/analytics | `test_f10_timestamp_integrity.py` 10/10; PostgreSQL 5/5 |
| F-18 | Central trusted-source validation, strict webhook precedence, validated-before-parse/DB, fail-closed config | `test_f18_sales_source_security.py` 16/16; production enforcement pending |

All fixes coexist in the release branch; the complete offline suite passed
37/37, all command contracts passed 90/90, and every release PostgreSQL suite
passed.

## C. Security review

### C.1 Persistence validation boundary

- Live and backfill listeners set a module-private token
  (`sales_listener._SOURCE_VALIDATED`) only after the central source validator
  accepts the message.
- `_save_sale_single`, `_save_sales_batch`, `_insert_sale_result`, and
  `_insert_sale` require identity with that token.
- A boolean `_source_validated=True` alone is insufficient; the regression test
  proves it cannot bypass validation or touch the DB.
- The legacy `validated=True` override was removed.
- The only direct marker use outside the listener is the test/admin helper in
  `test_integrity_upgrades.py`; its trust boundary is a test process, not a
  Discord message or runtime command. Normal runtime paths cannot supply it
  with untrusted data.
- Enforce mode rejects before embed parsing and before DB access.

### C.2 Sales logging

- Sales listener logs now carry only: mode/decision/reason, source
  classification, message ID, channel/guild ID, embed index, and aggregate
  counts.
- Parsed item names, group names, buyer data, amounts, titles, embed field
  values, raw content, and exception messages are no longer logged.
- Exception logs use exception type only.
- `sales_source_validation` logs contain no content or configuration values.
- Regression tests assert that item tokens, buyer email, amount, and secrets do
  not appear in output.

## D. Database readiness

### D.1 Ordered release migration manifest

1. `migrations/2026-11-01_items_name_lower_trim_index.sql` — run separately
   because `CREATE INDEX CONCURRENTLY` cannot run in a transaction.
2. `migrations/2026-11-02_astra_tables.sql`
3. `migrations/2026-11-02_astra_outcomes.sql`
4. `migrations/2026-11-02_project_oracle_phase1.sql`
5. `migrations/2026-11-02_project_oracle_phase2.sql`
6. `migrations/2026-11-03_sales_integrity_columns.sql`
7. `migrations/2026-11-05_creator_registry.sql` (items.creator_type and
   creator_registry prerequisite)
8. `migrations/2026-11-05_golden_hour_indexes.sql`
9. `migrations/2026-11-08_f07_creator_identity_expand.sql`
10. `migrations/2026-11-08_f07_oracle_identity_additive.sql`
11. `migrations/2026-11-08_f07_creator_identity_contract.sql`
12. `migrations/2026-11-08_f10_timestamp_integrity.sql`

Dependencies were verified from code and rehearsed in this exact order.
ORACLE additive follows phase 2, F-07 expand precedes contract, and F-10 runs
after creator identity conversion.

### D.2 Rehearsal evidence

`test_release_migration_manifest_pg.py` (3/3 passed) on disposable PostgreSQL
with realistic legacy data verifies:

- Exact ordered migration execution.
- Row preservation for items, history, creators, cohorts, observations,
  recovery payload, predictor weights, and sales.
- User/Group 123 coexistence after contract.
- UTC snapshot-day uniqueness and index expression.
- Existing ORACLE recovery data and historical sales preservation.
- Application read/write compatibility after the manifest.
- Safe re-run/idempotency for the manifest where promised.

Additional PostgreSQL suites passed: F-07/F-08 5/5, F-09 3/3, F-10 5/5, and
the Phase 2 integration suite.

### D.3 Preflight and rollback

- Read-only preflight: `release/preflight.sql` (row counts/date ranges,
  timestamp types, UTC duplicate days, identity ambiguity, ORACLE cohort
  duplicates, sales duplicates, migration-readiness markers).
- Operational-gate correction: the UTC duplicate-day preflight expression is
  type-aware for both legacy `TIMESTAMP` and `TIMESTAMPTZ` and is tested under
  non-UTC PostgreSQL sessions (`test_operational_gate_preflight_pg.py`).
- Backup required before migration.
- Expected locks: F-10 type changes and F-07 primary-key replacement take
  `ACCESS EXCLUSIVE` locks; schedule a maintenance window.
- F-07 contract rollback is blocked if typed User/Group collisions now exist;
  archive/backup resolution is required first.
- F-10 rollback drops the UTC index first, reverses types with
  `AT TIME ZONE 'UTC'`, and recreates the old daily index.
- No production migration was executed.

## E. Regression results

- Complete offline suite: **37/37 passed**, 0 failed.
- F-05: **16/16**.
- F-07/F-08: **13/13 offline**, **5/5 PostgreSQL**.
- F-09: **12/12 offline**, **3/3 PostgreSQL**.
- F-10: **10/10 offline**, **5/5 PostgreSQL**.
- F-18: **16/16**; legacy sales-source suite **5/5**.
- Sales integrity: **20/20**; sales reconciliation tests passed.
- Command contracts: **90/90**; public/restricted callbacks passed.
- Integrity upgrades on disposable PostgreSQL: **11/11** (local rehearsal).
- Release migration manifest: **3/3** (local and CI).
- CI on `e57ec5a`:
  - Survival Intelligence Tests (`offline-regression`): **success** —
    https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42594280599
  - Phase 2 PostgreSQL Integration (`phase2-postgres`): **success** —
    https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42594281253
  - Sales Integrity Tests: **success** —
    https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42594280569
- Confirmations include F-05, F-07/F-08, F-09, F-10, F-18, ordered release
  manifest, command contracts/callbacks, and sales integrity steps.

## F. Operational readiness

Outstanding before production release:

- Run `release/preflight.sql` against an approved production-like snapshot.
- Obtain migration approval and a maintenance window; take a backup.
- Run a production-like migration rehearsal and smoke test after each phase.
- Approve the sales channel, guild, webhook IDs, and bot sender IDs; do not
  invent them.
- Deploy F-18 in `dry-run`; review would-reject/reason aggregates against
  representative historical messages.
- Test trusted and untrusted live messages in a non-production channel.
- Document false-rejection risk and obtain explicit enforcement approval.
- Run production-like smoke tests for commands, snapshots, ORACLE, scheduler,
  and sales reporting.
- Obtain the required GitHub review/deployment approval.
- Keep `PHASE2_M4_ENABLED=0`; keep Avatar Background work separate.

## G. Release blockers

- **Code defects:** none identified in the certified RC scope.
- **Migration dependencies:** production migration approval, backup,
  maintenance window, and preflight/rollback review remain.
- **Configuration dependencies:** F-18 trusted IDs, guild/channel, dry-run
  evidence, and explicit enforce approval remain. Production mode remains
  `off`.
- **Deployment approvals:** `main` is protected, but the ruleset requires zero
  approving reviews and strict `offline-regression`/`phase2-postgres` checks.
  A push to `main` triggers `.github/workflows/deploy.yml`, which resets the
  production checkout and restarts `ugc-bot`. No production merge or deploy was
  performed.
- **Live-verification requirements:** production-like migration smoke,
  Discord/sales dry-run, live trusted/untrusted source tests, and operational
  rollback rehearsal remain.

## H. Certification verdict

- **CODE RELEASE CANDIDATE: PASS** — integrated branch, 37/37 offline tests,
  all release PostgreSQL suites, 90/90 command contracts, and CI are green on
  `e57ec5a`.
- **DATABASE MIGRATION READINESS: PASS** — ordered manifest, preflight, data
  preservation, idempotency, and rollback rehearsal passed on disposable
  PostgreSQL; production execution still requires approval.
- **SALES ENFORCEMENT READINESS: FAIL** — implementation is verified, but
  trusted production IDs, dry-run observation, explicit enforcement approval,
  and production verification have not occurred.
- **PRODUCTION RELEASE: NO-GO** — the code candidate is certified, but
  production migration, sales enforcement, governance approvals, and live
  smoke gates remain open.

A successful release-candidate certification is not permission to deploy.
Production release requires separate explicit approval.
