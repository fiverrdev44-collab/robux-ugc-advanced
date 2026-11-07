# VANTA 73 — Final Release Certification

- **Baseline:** `d6976d3e404303f6ddccb8f64785c84112c2ffc6`
- **Certification branch:** `audit/final-vanta73-certification`
- **Implementation SHA:** `0e1510d2e160c5792592d74e681135c806e90233`
- **Verdict:** **NO-GO for production release certification**

Feature freeze was respected. No new commands, AI engines, marketplace-learning
features, production migrations, backfills, Oracle deploys, feature-flag changes,
API-budget increases, or automatic merges were performed.

## What is now verified

- 90 registered commands are inventoried in `FINAL_COMMAND_MATRIX.csv`.
- Every command has a registration, alias, dispatch, and authorization contract.
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
- 27 offline suites and 23 disposable-PostgreSQL tests pass.
- CI Survival and PostgreSQL workflows pass on the implementation SHA.

## Unresolved blockers

### P1
1. **F-05:** Multiple direct Roblox API calls bypass the shared scheduler,
   Retry-After handling, and circuit breaker.
2. **F-06:** `main` is unprotected and pushes can auto-deploy without required
   Survival/PostgreSQL checks. This requires repository settings, not code.
3. **F-14 limitation:** AI quotas are process-local; multi-process deployment
   needs shared quota storage.

### P2
4. **F-07:** `tracked_creators` still has a numeric-only primary key, allowing
   User/Group collisions.
5. **F-08:** Creator Brain cohorts/patterns still group by display name.
6. **F-09:** A single discovery rate limit can abort the ORACLE creator pass.
7. **F-10:** Mixed `TIMESTAMP`/`TIMESTAMPTZ` semantics remain.
8. **F-11 verification:** Event-ID-aware dedupe is code-correct but could not be
   executed because the disposable setup path hardcodes PostgreSQL SSL.
9. **F-12:** M4 is dormant and does not receive an M3 bundle in the command path.
10. **F-18:** Sales embeds are not authenticated against a trusted webhook or
    sender. Design is documented; ingestion behavior is unchanged.
11. **F-13:** Full per-command callback/live coverage is incomplete. Matrix:
    2 PASS, 54 BLOCKED, 34 NOT TESTED for callback behavior; all 90 have
    contract/auth PASS.

## Deployment requirements before a future GO

1. Fix F-05 by routing every Roblox request through the shared scheduler/client
   with one circuit and Retry-After policy.
2. Protect `main`, require PR review and Survival/PostgreSQL checks, and require
   manual production approval.
3. Fix composite creator identity and Creator Brain/ORACLE grouping.
4. Implement ORACLE per-creator rate-limit recovery within the existing budget.
5. Standardize timestamp semantics or prove timezone-safe behavior.
6. Complete an SSL-capable disposable PostgreSQL verification of sales dedupe.
7. Complete per-command callback tests for public commands and controlled tests
   for owner-only commands.
8. Roll out sales-source validation in dry-run, then enforce, with a separate
   reviewed environment/configuration change.
9. Keep `PHASE2_M4_ENABLED=0` until M4 M3-evidence integration is completed.

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
defects and all command authorization contracts, but unresolved P1 API/release
controls and incomplete callback/live command coverage prevent production
certification. No claim of live service health or sales performance is made.
