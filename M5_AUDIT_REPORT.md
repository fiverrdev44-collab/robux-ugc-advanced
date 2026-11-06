# VANTA 73 — M5 Complete A–Z Audit

- **Frozen baseline:** `4399eaeea4195b550b8f5f2c77086fb9104ce6c3`
- **Audit branch:** `audit/m5-complete-a-z`
- **Audit date:** 2026-11-06 (UTC)
- **Mode:** read-only audit. No production code, database, migration, API budget, ORACLE, autonomous-learning, or `!emote_title` changes.
- **Artifacts:** `M5_COMMAND_MATRIX.csv`, `M5_FINDINGS.json`, `M5_TEST_RESULTS.md`, `M5_RELEASE_GATE.md`
- **Scope:** repository integrity, runtime command registry, AI and market evidence, database safety and integrity, ORACLE, Roblox API scheduling, reliability, security, and regression testing.

## Executive verdict

**No-Go for controlled M4 activation.**

M4 itself is implemented behind `PHASE2_M4_ENABLED=0`, its focused tests pass, and its evidence/metric gates are substantially stronger than the legacy prediction paths. However, the audit found multiple system-wide P1 issues that would make activation unsafe:

- Mutating and costly Discord commands lack consistent authorization.
- `!ai_debug` exposes partial API key material without an owner gate.
- Legacy `!predict` presents an uncalibrated heuristic as a probability with action directives.
- Legacy ROI output fabricates expected sales and revenue from favorites.
- Multiple Roblox API call sites bypass the shared scheduler and circuit breaker.
- `main` is unprotected and every push auto-deploys without required CI.

M4 activation should wait for the P1 gates in `M5_RELEASE_GATE.md`.

## Audit area classification

| Area | Classification | Basis |
|---|---|---|
| A. Repository integrity | **PASS** | Frozen SHA verified; 180 tracked files; all command modules imported; 90 commands registered. Dependency pinning is a P3 concern. |
| B. Discord commands | **FAIL** | Runtime registry has 90 commands; matrix lists 84. 66 commands are “not exercised”, 5 “manual”, 13 “automated”. Authorization is inconsistent. |
| C. AI intelligence | **FAIL** | M3/M4 have strong evidence and validation controls, but `!predict`, ROI output, and `!ai_debug` violate probability, sales-evidence, and secret-handling expectations. |
| D. Market intelligence | **FAIL** | M3/M4 labels are generally strong; legacy ROI conflates favorites with expected sales, M4 does not consume M3 in the command path, and Creator Brain uses names instead of stable IDs. |
| E. Database | **FAIL** | `tracked_creators` is not composite-keyed; timestamp types are mixed; startup setup can destructively dedupe sales if the migration flag is enabled; M2 registry migration is not applied by deploy. |
| F. ORACLE | **FAIL** | Creator Brain cohorts/patterns use display names; a single discovery rate limit aborts the whole creator pass. `pattern_forge` correctly labels selection bias and non-causality. |
| G. Roblox API | **FAIL** | Several command/helper paths call Roblox directly without the shared rate limiter, Retry-After handling, or circuit breaker. The batch client has a separate budget and no shared circuit. |
| H. Reliability and security | **FAIL** | Authorization gaps, partial key disclosure, unprotected main, auto-deploy without required CI, unpinned dependencies, and import-time scheduler startup. |
| I. Regression testing | **PASS for executed suites / FAIL for command coverage** | All executed offline suites and 23 disposable-PostgreSQL tests passed. Coverage remains command-family level; 66 commands are not exercised. |

## Findings summary

Full evidence and reproduction details are in `M5_FINDINGS.json`.

| ID | Severity | Finding | Status |
|---|---|---|---|
| F-01 | P1 | Mutating/costly commands lack consistent authorization | Observed |
| F-02 | P1 | `!ai_debug` exposes API-key prefixes to non-owners | Observed |
| F-03 | P1 | Heuristic score presented as success probability with directives | Observed |
| F-04 | P1 | Expected sales/revenue fabricated from favorites | Observed |
| F-05 | P1 | Direct Roblox API calls bypass shared scheduler/circuit | Observed |
| F-06 | P1 | Main unprotected; push auto-deploys without required CI | Observed |
| F-07 | P2 | `tracked_creators` keyed only by numeric creator ID | Observed |
| F-08 | P2 | Creator Brain cohorts/patterns use display names | Observed |
| F-09 | P2 | One discovery rate limit aborts the ORACLE creator pass | Observed |
| F-10 | P2 | Mixed timestamp/timezone semantics in market windows | Observed |
| F-11 | P2 | Startup dedupe can delete distinct sales if enabled | Potential |
| F-12 | P2 | `!concept` never receives an M3 bundle | Observed |
| F-13 | P2 | Command coverage matrix is stale and coverage incomplete | Observed |
| F-14 | P2 | Unbudgeted AI debug/provider calls | Observed |
| F-15 | P3 | Unpinned dependencies and deployment action | Observed |
| F-16 | P3 | Importing the bot starts the scheduler | Observed |
| F-17 | P3 | DB Check workflow prints host/name/user | Observed |

## P1 findings — detailed

### F-01 — Authorization gaps

`BOT_OWNERS` checks are concentrated in `commands_supercomputer.py` (lines 31, 1138, 1166, 1187, 1215, 1567, 1765, 1948, 2220). No global command guard was found. Examples:

- `commands_advanced.py:108` — `!snapshot_now` triggers a snapshot/API/DB path.
- `commands_sales.py:124,159,566` — sales backfill/report/scan paths.
- `commands_visibility.py:23,44` — seed/run write visibility data and may call live search.
- `commands_concept.py:14` — `!concept` spends AI quota and has no owner/rate limit.
- `commands_ai.py:724,1701` — `!brainstorm` and `!ai_debug` spend AI quota; `!ai_debug` also leaks key prefixes.
- `commands_market.py:101` — `!dbtest` exposes table counts/timestamps.

**Impact:** any user with command access can trigger API/DB writes or AI spend.

### F-02 — Secret prefix disclosure

`commands_ai.py:1706-1714` prints `GEMINI_API_KEY[:8]`, `OPENROUTER_API_KEY[:10]`, and key lengths. No owner check. **Impact:** partial secret disclosure and unneeded provider calls.

### F-03 — Probability mislabeling

`predictor.py:79-111` sums heuristic factors and calls the result `probability`; `format_prediction` prints action directives (“Attack immediately”, “Launch within 7 days”). `commands_intel.py:172` calls it “success probability”. No calibration evidence is attached.

### F-04 — Fabricated sales/revenue

`bot_core.py:551-570` derives `expected_sales` from favorites using fixed ratios and `expected_revenue` from price. `commands_guide.py:524-527` displays “Expected Sales” and “Expected Revenue”. No attributable sales evidence is required.

### F-05 — API scheduler bypass

Direct `requests.get/post` call sites include:

- `commands_sales.py:262,336,349,359,448,479`
- `commands_supercomputer.py:1107`
- `creative_pivot.py:210`
- `desc_forge.py:273`
- `recovery_brain.py:373,413,427,442,503,532`
- `suggest.py:86`
- `tag_generator.py:285,289,297`

These do not share `execution_policy` pacing, Retry-After handling, in-flight dedupe, or circuit state. `roblox_batch_client.py:110-162` uses its own token bucket and retry loop without the shared circuit.

### F-06 — Release governance

GitHub reports `main` as `protected=false`. `deploy.yml` triggers on every push to `main/master`, runs `git reset --hard`, installs dependencies with `|| true`, and restarts the service. The frozen main SHA had only an auto-deploy run, not the Survival/PostgreSQL workflows.

## P2 findings — highlights

- **F-07:** `database.py:465-473` defines `tracked_creators` with `creator_id BIGINT PRIMARY KEY` and default `creator_type='User'`; `creator_tracker.py:217-220` uses `ON CONFLICT (creator_id) DO NOTHING`. A Group and User sharing a numeric ID collide.
- **F-08:** `creator_brain.py:40-45,64-70,130-135` groups by `lower(creator_name)`, so same-name creators merge and renamed creators split.
- **F-09:** `oracle_worker.py:301-307` breaks the creator loop on `RateLimited`. Prior read-only production evidence recorded `creators_scanned=0` and `observations_inserted=0` for the first cohort creator.
- **F-10:** `items.created_at` and `item_history.snapshot_at` are `TIMESTAMP` without timezone (`database.py:71-95`), while market windows compare to `NOW()`.
- **F-11:** `database.py:273-280` deletes duplicate `my_sales` rows by fingerprint without considering `source_event_id`. It is gated by `RUN_MIGRATIONS_ON_START=1`; this is a potential, flag-dependent data-loss risk.
- **F-12:** `commands_concept.py:52` calls `render_concept_request` without an M3 bundle; `original_concept_engine.py:792-815` only returns `EXPERIMENT CANDIDATE` when an M3 `VALIDATE EXPERIMENTALLY` verdict is supplied. The production command cannot reach that state.
- **F-13:** runtime 90 commands vs matrix 84. Missing: `concept`, `emote_title`, `help`, `link`, `outcome`, `rename`.
- **F-14:** `!ai_debug` performs direct Gemini/OpenRouter calls outside the AI budget; `!concept` has no per-user quota.

## P3 findings — highlights

- `requirements.txt` has no version constraints; `deploy.yml` uses `appleboy/ssh-action@master` and ignores install failures.
- `discord_ugc_bot.py:188-193` starts the scheduler at import time. The M5 command-registry import observed scheduler jobs being scheduled.
- `db_check.yml:26-30` prints DB host, name, and user to logs.

## Positive evidence

- Frozen SHA matches `origin/main`.
- All command modules imported successfully; 90 commands registered.
- M2/M3/M4 evidence modules explicitly handle missing registry and preserve stable composite identity where implemented.
- M3 separates observed/sampled/heuristic/unknown evidence; M4 labels proposals and validates metric-specific claims.
- `market_velocity.py` is SQL facts-only; `pattern_forge.py` labels selection-biased associations and non-causality.
- `creator_registry.creator_evidence()` uses safe existence checks/savepoints and does not abort normal transactions.
- Convergence limit, cache-key depth, circuit-aware shortlist processing, and M4 sample-window/metric validation are covered by tests.
- 23 offline suites and 23 disposable-PostgreSQL tests passed locally (see `M5_TEST_RESULTS.md`).
- M4 is dormant (`PHASE2_M4_ENABLED=0`).

## Prioritized correction plan

1. **P1 — Authorization:** add a central command guard and metadata; protect all mutating/costly commands, especially `!concept`, `!snapshot_now`, sales/visibility collectors, and AI diagnostics.
2. **P1 — Secret handling:** owner-gate and redact `!ai_debug`; report only configured/not configured.
3. **P1 — Evidence language:** remove/rename `probability`, “Attack immediately”, and expected sales/revenue; require attributable sales and calibration evidence.
4. **P1 — API safety:** route every Roblox call through one scheduler/client with shared pacing, Retry-After, dedupe, and circuit state.
5. **P1 — Release gate:** protect `main`, require Survival/PostgreSQL checks and review, pin actions/dependencies, and fail deploys on install errors.
6. **P2 — Identity integrity:** migrate `tracked_creators` to composite identity and update Creator Brain/ORACLE.
7. **P2 — ORACLE resilience:** isolate per-creator rate-limit failures and add resumable discovery without increasing the budget.
8. **P2 — Time and sales integrity:** standardize UTC timestamps and replace destructive startup dedupe with a reviewed, event-ID-aware migration.
9. **P2 — M3/M4 bridge:** explicitly pass stored M3 evidence or remove the unreachable EXPERIMENT CANDIDATE claim.
10. **P2/P3 — Coverage and operations:** regenerate the command matrix from runtime in CI, add missing suites, move scheduler startup behind an app factory, and redact DB diagnostics.

## Observed vs potential vs unverified

- **Observed:** runtime/matrix drift, authorization gaps, key-prefix printing, probability/ROI wording, direct API calls, main protection status, name-based Creator Brain SQL, `tracked_creators` schema, M4 command path.
- **Potential:** destructive startup dedupe when the migration flag is enabled; timezone-dependent window drift if a non-UTC session is used.
- **Unverified in M5:** current production error rates, current production registry/migration state, and production command behavior. The prior production audit evidence is cited only where explicitly timestamped; no new production scan was performed.

## M4 activation verdict

**NO-GO until the P1 gates are closed.** M4’s code and tests are ready for review, but activating the command would expose an unauthenticated AI-cost surface while system-wide command authorization, secret handling, evidence language, API scheduling, and release governance remain unresolved.

No production code, database, migration, API budget, ORACLE, autonomous-learning, or `!emote_title` change was made.
