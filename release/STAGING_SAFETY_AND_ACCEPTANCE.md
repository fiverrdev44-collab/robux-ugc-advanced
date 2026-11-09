# VANTA 73 — Staging Safety and Acceptance Checklist

**Status: PREPARED, NOT EXECUTED.** The unified release branch contains Avatar Background (AssetType 92) changes and the type-aware UTC preflight. This checklist does not authorize a deployment, migration, database copy, sales-policy change or external API access.

## Why an isolated staging instance is needed

The current production `main` branch auto-deploys to the Oracle server. The code also starts its scheduler when the bot is launched, which can trigger database writes, snapshots, research, monitoring, and alerts. Therefore, **do not start a second copy of the bot with production credentials** and **do not run this branch on the production server** just to perform a smoke test.

## Gate A — Operator authorization (BLOCKED until supplied)

- Operator explicitly authorizes a separate staging runtime and isolated, sanitized production-like PostgreSQL database copy (or identifies an existing staging environment).
- Obtain a **separate test Discord bot token**; invite only to a dedicated staging Discord server/channel. Do not use the production bot token or a real sales-notification source.
- Provision *separate*, least-privilege staging credentials and staging-only destination channels. Keep credentials only in the approved secret store; do not paste them into reports or chat.
- Review every worker/scheduler/ingestion path before enabling. In particular, disable outbound scheduled research, marketplace scraping, background scans, launch sync, webhook ingestion, scheduled sales notifications, and auto-deploy in staging unless their test-only routing has been verified and specifically approved.
- No live Roblox calls or automated backfills unless the operator approves a bounded API budget and a safe scope.
- Keep `SALES_SOURCE_MODE=off` initially and `PHASE2_M4_ENABLED=0`.
- Record the proposed environment and rollback plan before any copy or migration.

## Gate B — Production-like database rehearsal (BLOCKED)

1. Obtain approval for a sanitized snapshot; copy to an **isolated** PostgreSQL database. Verify DB host and database identity before any mutation.
2. Take and verify an isolated staging backup. Measure baseline row counts and checksums where feasible.
3. Execute `release/preflight.sql` **read-only** on the isolated database. Record duplicate UTC days, timestamp column types, creator identity conflicts, sales identity anomalies and index definitions.
4. Analyze anomalies. **Stop** on duplicates or identity conflicts; obtain remediation approval. Don't silently deduplicate.
5. Apply the documented ordered migration manifest in staging only, observing the separate `CREATE INDEX CONCURRENTLY` requirement and maintenance/lock expectations.
6. Re-run preflight and compare preserved item, snapshot, sales and creator counts and identity relationships. Measure lock timings and rollback feasibility.
7. Rehearse restoration from the staging backup. Never restore over production.
8. Record PASS/FAIL/BLOCKED, actual schema, timestamps, durations, and execution evidence.

## Gate C — Bot command smoke (BLOCKED)

Launch a test bot only after verifying the token, DB, scheduler, listeners, and alert destinations are isolated. Verify:

- Startup: required imports, commands registered, `!selftest`, authorization and DB reads.
- `!early 7 backgrounds`: returns only AssetType 92 listings OR an explicit insufficient-evidence result. No hats, wings, emotes, or general early-winners fallback.
- `!chain background starry sky fence distant village`: identifies the **backgrounds** family; proposed titles must not be wearable accessories. Use mocked marketplace data unless live access is approved.
- `!converge backgrounds`, `!patterns backgrounds`, `!failures backgrounds`, `!xray`: use family-restricted data and check empty/sparse-dataset handling.
- Confirm asset family separation for hair, hats, back accessories, emotes and backgrounds; check category 92 filters in DB queries.
- Check ORACLE, snapshots, creator intelligence and sales reconciliation against isolated fixtures only.
- Record each command's exact result, data coverage, test identity, and whether external providers were mocked.

## Gate D — Sales source authorization (BLOCKED)

- Operator supplies approved staging guild/channel/bot/webhook IDs through the secret store, not in a report.
- Keep production `SALES_SOURCE_MODE=off`; test `dry-run` only in isolated staging.
- Verify accepted legitimate notifications, wrong channel/guild, untrusted bots, untrusted webhooks, human messages, duplicates and reconciliation outcomes.
- Review false rejects, would-reject counts and provenance before considering enforcement. No production `enforce` change without fresh explicit approval.

## Gate E — Production governance (BLOCKED)

- `.github/workflows/deploy.yml` currently deploys automatically on pushes to `main` or `master`. A merge into `main` is itself a production-affecting action.
- Require independent approval, a protected production environment/manual deployment gate, a verified backup/restore plan, maintenance-window approval and explicit permission for migrations/deployment.
- No merges into `main`, production changes, secret changes, migrations, ORACLE changes or sales enforcement as part of this staging preparation.

## What is verified vs unverified

- GitHub Actions on disposable fixtures are useful code evidence, **not** proof of production-like data compatibility or live Discord operation.
- Actual staging service availability, sanitized database snapshots, tokens, Discord IDs and credentials: **NOT PROVIDED / NOT TESTED**.
- All gates above remain **BLOCKED** pending authorized access and observed results. Record raw evidence before marking a gate PASS.
