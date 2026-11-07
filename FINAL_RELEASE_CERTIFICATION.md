# VANTA 73 â€” Final Release Certification

- **Baseline:** `d6976d3e404303f6ddccb8f64785c84112c2ffc6`
- **Certification branch:** `audit/final-vanta73-certification`
- **Remediation SHA:** `aa0aef932b61ec8753e496ab8527cba65942b2b8`
- **Final tested code HEAD:** `e8750da903906f29d55dbc2dc311197c91da9f85`
- **Verdict:** **NO-GO for production release certification**

Feature freeze was respected. No new commands, AI engines, marketplace-learning
features, production migrations, backfills, Oracle deploys, feature-flag changes,
API-budget increases, or automatic merges were performed.

## What is now verified

- 90 registered commands are inventoried in `FINAL_COMMAND_MATRIX.csv`.
- Every command has a registration, alias, dispatch, and authorization contract.
- All 34 previously untested public commands now execute through real registered
  callbacks with isolated Discord/DB/API/AI fixtures and output assertions.
- 53 of 54 restricted callbacks execute through real registered callbacks with
  owner identities, mocked DB/API/AI/filesystem/process operations, and output
  assertions. Only `!selftest` remains BLOCKED.
- Central authorization denies non-owners for owner-only commands before callbacks.
- Aliases cannot bypass authorization; unknown commands fail closed.
- `!ai_debug` no longer exposes key prefixes, lengths, or key material.
- `!emote_title` is a documented public exception with a bounded quota.
- Conversation-planner AI is bounded per user and globally.
- `verdict`, `hitrate`, and `creator_brain` were corrected from public read-only
  to owner-only/mutating classifications.
- Predictor output is heuristic, not a success probability.
- ROI output no longer fabricates sales/revenue.
- Sales dedupe now requires identical source-event IDs.
- Scheduler startup is behind the main guard; importing the bot no longer starts it.
- DB Check workflow no longer prints host/name/user.
- Duplicate GitHub Actions job name `offline-regression` was split into
  `survival-tests`/`sales-integrity`; deploy now fails on dependency-install error.
- 29 offline suites and 24 disposable-PostgreSQL tests pass.
- CI Survival and PostgreSQL workflows pass on the remediation SHA.
  - Survival: `https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42404066454`
  - PostgreSQL: `https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42404066436`

## Governance state (corrected)

- `main` is **protected**.
- Active ruleset **26727577** requires a pull request and the
  `offline-regression` + `phase2-postgres` checks.
- Deletion and non-fast-forward updates are prohibited.
- No configured bypass actors.
- **Zero required approving reviews** and no independently verified manual
  deployment approval remain genuine governance gaps.
- `sales-integrity` is the unique former `offline-regression` job name.

## Unresolved blockers

### P1
1. **F-05 (partial):** Read-only GETs and targeted authenticated sales POST/
   CSRF calls now use `safe_roblox` with shared pacing, Retry-After, a bounded
   POST budget, and shared circuit state. The batch client checks/trips the
   shared circuit on 429. Remaining untargeted direct request paths mean the
   circuit is not yet universal.
2. **F-14 limitation (P3):** One active bot process was verified. Quotas are
   process-local and sufficient for the verified single-process deployment;
   multi-process would require shared storage.

### P2
3. **F-07:** `tracked_creators` still has a numeric-only primary key, allowing
   User/Group collisions.
4. **F-08:** Creator Brain cohorts/patterns still group by display name.
5. **F-09:** A single discovery rate limit can abort the ORACLE creator pass.
6. **F-10:** Mixed `TIMESTAMP`/`TIMESTAMPTZ` semantics remain.
7. **F-12:** M4 is dormant and does not receive an M3 bundle in the command path.
8. **F-18:** Sales source validation is implemented and tested in off/dry-run/
   enforce modes, and invalid modes now raise a hard configuration error. It is
   not wired into ingestion; enforcement requires approved webhook/sender IDs
   and rollout.
9. **F-13:** All 34 previously NOT TESTED public commands and 53/54 restricted
   commands have genuine callback PASS evidence. Matrix: 89 PASS, 1 BLOCKED,
   0 NOT TESTED; all 90 have contract/auth PASS. `!selftest` remains BLOCKED
   because its composite real-subcommand runtime exceeds the isolated callback
   budget. Live smoke is not performed.

F-11 is now fixed and verified: the disposable PostgreSQL test proves distinct
source event IDs survive and duplicate event IDs collapse.

## Deployment requirements before a future GO

1. Finish F-05 by routing all remaining untargeted direct POST/probe paths
   through shared pacing/circuit controls.
2. Add at least one required approving review and a manual production deployment
   approval; do not modify rulesets without approval.
3. Fix composite creator identity and Creator Brain/ORACLE grouping.
4. Implement ORACLE per-creator rate-limit recovery within the existing budget.
5. Standardize timestamp semantics or prove timezone-safe behavior.
6. Complete a staged `!selftest` harness and perform production-only smoke
   tests.
7. Approve trusted webhook/sender identities and roll out sales-source validation
   in dry-run, then enforce.
8. Keep `PHASE2_M4_ENABLED=0` until M4 M3-evidence integration is completed.

## Rollback procedure for the certification branch

The branch contains code/test/workflow changes only; nothing is deployed by this
certification.

If a later release is approved and must be reverted:

1. Deploy the previous known-good main SHA through the normal deployment process.
2. Set `PHASE2_M4_ENABLED=0` if it was enabled.
3. Do not roll back database changes: none were applied by this branch.
4. Re-run the read-only smoke tests below.
5. Preserve the audit logs and matrix for incident review.

## Required production-only smoke tests before future release

These were **not** executed in this audit:

- Owner and non-owner invocation of one public command and one restricted command.
- `!ai_debug` as owner: verify no key material appears.
- `!emote_title` under and over the allowlist quota in a controlled channel.
- One read-only marketplace command (e.g. `!scan_status`).
- One AI command with provider unavailable, verifying no fabricated output.
- Snapshot scheduler status and last completed snapshot timestamp.
- Sales ingestion with a known test webhook in dry-run mode.
- PostgreSQL connection and transaction rollback behavior.
- Service restart and scheduler single-instance check.

## Maintenance-mode recommendation

Until the P1 blockers are closed:

- Keep M4 disabled.
- Restrict owner-only commands to trusted operators.
- Do not enable new backfills or visibility seeds.
- Keep API pacing conservative and avoid manual retry storms.
- Treat the system as suitable for controlled research use, not certified
  production release.

## Final certification verdict

**NO-GO.** The audit produced credible, repeatable evidence for the repaired
defects, all command authorization contracts, and 87 previously untested public
and restricted callback behaviors. Unresolved P1 API/release controls, the
`!selftest` composite-callback blocker, and unperformed production smoke tests
prevent production certification. No claim of live service health or sales
performance is made.

