# VANTA 73 — Final Operational Release Gate Report

## Baseline and scope

- **Production baseline verified:** `7703b26f1cda063b2c8e2bebd3addb3a00bbe6d2`
  (`origin/main`, unchanged)
- **Tested release candidate:** `423f213569e17ea8740e9ce62344110893f8427e`
- **Operational-gate branch:** `release/vanta73-operational-gate`
- **Operational-gate code commit:** `eea7e1ab30caae0bfde68cee043a572c3d38ebd8`
- **Frozen audit checkpoint:** `df325a3d0b584b7933dd55ca035380b8d0369531`
  (untouched)
- No production merge, deployment, migration, sales enforcement, M4
  activation, or Avatar Background integration occurred.

## Gate 1 — Preflight correctness

**Status: PASS — VERIFIED**

- `release/preflight.sql` now uses a type-aware UTC-day expression:
  - Legacy `TIMESTAMP` (UTC wall time): double `AT TIME ZONE 'UTC'`.
  - `TIMESTAMPTZ` (absolute instant): single `AT TIME ZONE 'UTC'`.
- The expression is independent of the PostgreSQL session TimeZone.
- `test_operational_gate_preflight_pg.py` verifies both schemas under
  `-05:00`, `+05:30`, and `GMT`, including UTC day-boundary and offset rows:
  **3/3 passed**.
- The preflight remains read-only (no INSERT/UPDATE/DELETE/DDL statements).
- `test_release_migration_manifest_pg.py` was re-run after the correction:
  **3/3 passed**.
- Offline suite: **37/37 passed**.
- CI on `eea7e1ab`:
  - Survival Intelligence Tests: success —
    https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42611084930
  - Phase 2 PostgreSQL Integration: success —
    https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42611085001
    (includes ordered release migration manifest and operational preflight)
  - Sales Integrity Tests: success —
    https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42611084952

## Gate 2 — Production-like database rehearsal

**Status: BLOCKED — REQUIRED ACCESS OR APPROVAL MISSING**

No authorized isolated production-like PostgreSQL snapshot was available in
this environment. No production connection, production migration, or invented
production result was used.

Synthetic disposable-PostgreSQL rehearsals already pass, but they are not a
substitute for this gate. Required before GO:

1. Obtain explicit approval for an isolated copy of the production snapshot.
2. Take a backup of the isolated rehearsal database.
3. Record actual schema, migration baseline, row counts, timestamp provenance,
   duplicate UTC snapshot days, creator identity counts, ORACLE cohort rows,
   sales counts and anomalies.
4. Apply the ordered manifest from the RC report to the isolated database only.
5. Verify application compatibility after every major phase.
6. Measure index creation time and `ACCESS EXCLUSIVE` lock behavior.
7. Rehearse rollback and document any irreversible F-07 collision limitation.

## Gate 3 — Application smoke testing

**Status: BLOCKED — REQUIRED ACCESS OR APPROVAL MISSING**

No migrated staging database was available. Offline tests were not substituted
for staging evidence.

Required before GO:

- Deploy the RC to an isolated staging environment.
- Run `!selftest` and verify database connectivity and command registration.
- Exercise command authorization, marketplace analysis, creator intelligence,
  ORACLE, snapshot scheduling, sales reporting, and reconciliation.
- Mock or isolate external integrations unless explicitly authorized.
- Any permitted live API calls must be low-volume, budget-protected, and
  separately authorized. No production scraping/backfill.
- Record actual outcomes, failures, dependencies, and untested behavior.

## Gate 4 — Sales source readiness

**Status: BLOCKED — REQUIRED ACCESS OR APPROVAL MISSING**

No operator-approved numeric sales channel/guild/webhook/sender identities or
isolated staging channel were provided. No IDs or tokens were invented or
printed.

Required before GO:

1. Operator supplies approved channel, guild, webhook and bot-source IDs
   through the approved configuration channel.
2. Configure `SALES_SOURCE_MODE=dry-run` in staging.
3. Verify representative legitimate historical notifications are recognized.
4. Verify unapproved webhook, unapproved bot, human, wrong-channel and
   wrong-guild messages would be rejected.
5. Compare aggregate would-reject/reason counts against expected legitimate
   traffic.
6. Document false-rejection risk and obtain explicit enforcement approval.
7. Activate `enforce` only in a separately approved production change.
8. Keep `off` as the immediate rollback configuration.

An approved webhook is evidence of notification origin, not independent proof
of a completed Roblox transaction. Marketplace reconciliation remains separate.

## Gate 5 — Deployment governance

**Status: PASS — VERIFIED (inspection and rollout plan); control gap remains**

Findings:

- `.github/workflows/deploy.yml` triggers on pushes to `main`/`master` and
  automatically SSHes to the production server, runs `git reset --hard
  origin/main`, and restarts `ugc-bot`.
- The active `VANTA 73 - Main Protection` ruleset requires:
  - pull requests,
  - non-fast-forward protection,
  - strict `offline-regression` and `phase2-postgres` checks,
  - **0 required approving reviews**, no code-owner or last-push approval.
- Therefore a merge to `main` can automatically deploy without an independent
  review or manual production approval.

Recommended but **not applied**:

- Require at least one independent approving review and last-push approval.
- Add a protected `production` environment with a manual approval gate.
- Disable or gate automatic deployment on `main` until approval is recorded.
- Keep required status checks `offline-regression` and `phase2-postgres`.
- Do not alter rulesets or workflows without explicit authorization.

## Final evidence

- Operational-gate code SHA: `eea7e1ab30caae0bfde68cee043a572c3d38ebd8`.
- Preflight/migration rehearsal: 3/3 + 3/3 on disposable PostgreSQL.
- Offline suite: 37/37.
- All required CI checks on `eea7e1ab` passed (run IDs above).
- Production `main` remains `7703b26...`; no merge/deploy/migration.

## Deployment sequencing plan (requires approval at every step)

1. **Access approval:** authorize isolated production-like snapshot and staging
   access.
2. **Preflight approval:** run read-only preflight; review counts, UTC
   duplicates, identity ambiguity, cohort/sales duplicates and migration
   markers.
3. **Backup:** back up the target database; record restore point.
4. **Migration approval:** apply the ordered manifest to the isolated snapshot,
   then to production only in an approved maintenance window.
5. **Application approval:** deploy the RC code after schema readiness; keep
   sales mode `off`.
6. **Smoke gate:** run `!selftest`, command registration, ORACLE, snapshot,
   sales reporting/reconciliation and read-only checks.
7. **Sales dry-run approval:** configure approved IDs in staging; collect
   aggregate evidence; assess false rejections.
8. **Enforcement approval:** switch to `enforce` only with explicit approval;
   monitor rejections/missing sales; rollback to `off` if needed.
9. **Production GO:** only after independent review, successful smoke, approved
   migration, approved sales configuration, and documented rollback.

### Rollback strategy

- **Application:** revert to the previous production commit; if auto-deploy is
  still active, use an authorized deployment hold and verify the running
  service version.
- **Database:** restore the pre-migration backup. F-07 composite-key rollback is
  not safe once new User/Group collisions have been stored; archive/resolve
  collisions first. F-10 rollback must drop the UTC index first and reverse
  types with explicit `AT TIME ZONE 'UTC'`.
- **Sales source:** set `SALES_SOURCE_MODE=off`; do not delete historical sales
  or source metadata.

## Final verdicts

- **CODE RELEASE CANDIDATE:** `PASS — VERIFIED`
- **DATABASE OPERATIONAL READINESS:** `BLOCKED — REQUIRED ACCESS OR APPROVAL MISSING`
- **SALES ENFORCEMENT READINESS:** `BLOCKED — REQUIRED ACCESS OR APPROVAL MISSING`
- **DEPLOYMENT GOVERNANCE:** `FAIL — VERIFIED GAP` (auto-deploy on `main` and
  zero required approving reviews; no manual production gate)
- **LIVE SMOKE TEST READINESS:** `BLOCKED — REQUIRED ACCESS OR APPROVAL MISSING`
- **OVERALL PRODUCTION:** `NO-GO`

A production GO recommendation is not authorization to deploy. No production
action was taken.
