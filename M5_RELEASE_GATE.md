# VANTA 73 — M5 Release Gate

- **Baseline:** `4399eaeea4195b550b8f5f2c77086fb9104ce6c3`
- **Gate decision:** **NO-GO for controlled M4 activation**
- **M4 flag:** `PHASE2_M4_ENABLED=0` — remain OFF
- **Production state:** unchanged by this audit
- **Evidence:** `M5_AUDIT_REPORT.md`, `M5_FINDINGS.json`, `M5_TEST_RESULTS.md`, `M5_COMMAND_MATRIX.csv`

## Why NO-GO

M4’s feature implementation and focused CI pass, but the surrounding system does not yet meet the activation safety bar:

1. **P1 command authorization:** `!concept` and several mutating/costly commands have no owner/admin guard or rate limit.
2. **P1 secret handling:** `!ai_debug` prints partial API-key material to non-owners.
3. **P1 evidence integrity:** legacy `!predict` presents an uncalibrated heuristic as a probability with action directives; legacy ROI output fabricates expected sales/revenue.
4. **P1 API safety:** multiple Roblox call sites bypass the shared scheduler and circuit breaker.
5. **P1 release governance:** `main` is unprotected and pushes auto-deploy without required CI.

Activating M4 now would add another unauthenticated AI-cost command to this surface. The feature must remain dormant until these gates close.

## Mandatory gates before GO

### G1 — Command authorization
- Central owner/admin guard with explicit command classification.
- At minimum, protect `!concept`, `!brainstorm`, `!ai_debug`, `!snapshot_now`, `!sales_backfill`, `!sales_post_now`, `!sales_scan`, `!visibility_seed`, `!visibility_run`, `!dbtest`, and all mutating supercomputer commands.
- Verification: non-owner command tests assert rejection before DB/API/AI calls.

### G2 — Secret handling
- Remove key prefixes/lengths from `!ai_debug`.
- Make diagnostics owner-only.
- Verification: fake-key unit test proves no substring of a configured key appears in output.

### G3 — Evidence language
- Rename `probability` to heuristic score; remove “Attack immediately”, “Launch within 7 days”, and similar directives.
- Remove or explicitly label expected sales/revenue as non-evidence scenarios; require attributable sales for financial claims.
- Verification: output tests fail on probability/sales claims without evidence.

### G4 — Shared API scheduling
- Route all Roblox requests through one scheduler/client with shared pacing, Retry-After, dedupe, and circuit state.
- Verification: circuit-open fault injection proves zero new requests across all paths.

### G5 — Release governance
- Protect `main`.
- Require PR + Survival + PostgreSQL CI before merge.
- Pin GitHub Actions and Python dependencies.
- Fail deploy on dependency-install error.
- Verification: direct push rejected; deploy dry run fails on install failure.

### G6 — Database and identity integrity
- Migrate `tracked_creators` to `(creator_type, creator_id)` or add a typed identity table.
- Update Creator Brain/ORACLE to use stable composite identity.
- Standardize timestamp types to UTC-aware values.
- Replace destructive startup dedupe with a reviewed, event-ID-aware migration.
- Verification: disposable PostgreSQL tests for User/Group same-ID, name collisions, timezone windows, and duplicate event IDs.

### G7 — M4 M3 integration
- Pass stored M3 evidence into M4 or explicitly remove the unreachable `EXPERIMENT CANDIDATE` claim.
- No additional Roblox API requests.
- Verification: command-level test with a stored M3 bundle; assert it reaches `_market_status` and the report.

### G8 — Coverage
- Regenerate `COMMAND_COVERAGE_MATRIX.md` from runtime registration in CI.
- Add tests for currently unexercised high-risk commands.
- Verification: CI fails on matrix/runtime drift.

## M4-specific readiness

- M4 implementation: **passes focused review and tests**.
- M4 unit suite: 30/30.
- M3 suite: 35/35.
- Disposable PostgreSQL: 23/23.
- M4 makes no Roblox marketplace requests.
- M4 candidate claims are metric-specific and evidence-labeled.
- M4 remains behind an OFF-by-default feature flag.
- M4 command path currently does not receive an M3 bundle (P2 F-12).
- M4 activation is **blocked** by G1–G5; G6–G8 are required before v1.0 acceptance.

## GO conditions for controlled M4 activation

A later re-audit may issue **GO** only when:

1. G1–G5 are closed with reproducible tests.
2. The corrected SHA passes Survival and PostgreSQL CI from a protected main/PR gate.
3. `PHASE2_M4_ENABLED=0` remains the default and no production environment flag is changed.
4. M4 remains explicitly described as creative guidance, not market validation or profitability prediction.
5. No additional Roblox API budget or scheduled collection is introduced.

## Rollback

No M4 activation is being performed. If a later activation is approved:

- Set `PHASE2_M4_ENABLED=0` to disable the command.
- Restart the service only through the approved deployment process.
- No database migration is required to disable M4.
- Preserve evidence artifacts for re-audit.

## Final status

**NO-GO.** Keep M4 dormant. No merge, deployment, migration, backfill, API-budget change, ORACLE change, autonomous-learning change, or `!emote_title` change was performed by this audit.
