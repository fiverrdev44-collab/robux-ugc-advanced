# F-09 Remediation Evidence — ORACLE Rate-Limit Recovery & Scan Continuity

## A. Final SHA

- Remediation code commit under certification:
  `cb13f6bfb39fbb3da4b14a8f0464361330630ef5`
- Branch: `fix/f09-oracle-rate-limit-recovery`
- Baseline: `3448d658fc7cc2ef4ab4c962e2566462e6b7f016`
- Frozen audit branch: `df325a3d0b584b7933dd55ca035380b8d0369531`
  (untouched)

## B. Root cause

- `creator_tracker._get_json()` returned `None` for an open shared circuit,
  timeout, invalid response, and most HTTP failures.
- `search_creator_complete()` treated `None` as “no more pages” and returned an
  empty/truncated result without a machine-readable failure state.
- ORACLE could therefore continue as if a creator had no new items, inflating
  apparent coverage while silently losing pages and creators.
- A single 429 raised `RateLimited`, aborting discovery for every remaining
  creator in the scan. No durable per-creator continuation existed, so a
  process restart could not resume; the summary did not expose deferred,
  unprocessed, or coverage counters.
- The 429's `Retry-After` was not retained by the discovery contract, so
  callers could not distinguish a short deferral from a long one.

## C. Changed files

- `creator_tracker.py`
  - Added explicit discovery outcome globals and statuses: complete,
    partial, rate_limited, deferred, timeout, unavailable,
    invalid_response, page_cap_reached.
  - `search_creator_complete()` now preserves valid pages, returns a
    `complete` boolean, `partial`, `status`, `error`, and `retry_after`.
  - Numeric and HTTP-date `Retry-After` are parsed through the shared
    execution-policy parser.
  - Existing return keys (`creator_id`, `creator_type`, `items`, `pages`,
    `truncated`) remain compatible.
- `oracle_worker.py`
  - Added a resumable per-creator scan loop.
  - Persists continuation state in the existing `creator_patterns` table under
    `oracle_recovery`; no new migration.
  - Reuses the existing `scan_run_id` on resume and marks it running again.
  - Skips already completed typed creators; re-fetches only incomplete/remaining
    creators from page 1.
  - One shared batch call per scan preserves the existing enrichment budget.
  - Per-creator observation commits, duplicate prevention through
    `(scan_run_id, item_id)`, isolated creator failures, and advisory-lock
    release on every exit path.
  - Added counters: eligible/typed, attempted, completed, deferred, incomplete,
    unprocessed, skipped unknown, rate-limited requests, recovery attempts,
    resumed creators, successful/failed observations, coverage percentage.
  - Final status is `success` only when all typed creators completed with no
    remaining, incomplete, errored, unknown, truncated, or failed observations.
- `.github/workflows/survival-tests.yml`
  - Added the F-09 offline test and feature-branch trigger.
- `.github/workflows/phase2-postgres.yml`
  - Added the F-09 PostgreSQL persistence test and feature-branch trigger.
- `test_f09_oracle_recovery.py`
  - 12 offline discovery/recovery tests.
- `test_f09_oracle_recovery_pg.py`
  - 3 disposable-PostgreSQL persistence/lock/idempotency tests.

No new Discord command, API budget, migration, or production setting was added.

## D. Recovery architecture

1. **Discovery outcome contract:** every creator discovery returns a status,
   valid items, page count, truncation flag, completion flag, error, and
   retry-after. A failure is never represented as an empty successful result.
2. **Per-creator completion:** completed typed creators are recorded in a
   durable recovery payload; remaining/incomplete creators stay in the payload.
3. **Circuit interaction:** before each creator, ORACLE checks the shared
   circuit. If open, it stops issuing requests, persists the remaining list,
   and returns `partial` with `deferred=true` and the stop reason.
4. **429 handling:** discovery and batch 429s are counted, the remaining work is
   persisted, and no immediate or unbounded retry is issued. The next scheduled
   execution starts only when the shared circuit permits.
5. **Continuation:** the next execution loads `oracle_recovery`, reuses the
   original `scan_run_id`, marks it running, skips completed creators, and
   processes the remaining typed identities. Stale recovery for a different
   cohort is discarded without changing frozen cohorts.
6. **Restart safety:** persistence is in `creator_patterns` (existing table),
   so a new process/store instance loads the same state. The PostgreSQL test
   proves a new store instance sees the saved state.
7. **Idempotency:** observations use the existing unique
   `(scan_run_id, item_id)` constraint. Re-fetching an incomplete creator cannot
   duplicate committed observations in the same scan.
8. **Typed identity:** recovery keys are `User:<id>` / `Group:<id>`, never
   display names. User 123 and Group 123 have independent progress. Unknown
   types are skipped and counted, never resumed as User.
9. **Accurate status:** `success` requires full typed discovery completion;
   any remaining/deferred/incomplete/errored/unknown/truncated/failed-batch
   work forces `partial`. Coverage is completed typed creators divided by
   eligible typed creators.
10. **Transactions/locks:** each creator's observation batch commits
    independently; a failed creator is rolled back without aborting others.
    The advisory lock is released in `finally` on success, deferral, and fatal
    paths.

## E. Database impact

No migration is required. The implementation reuses:

- `creator_patterns` for the durable `oracle_recovery` JSON state;
- `trend_scan_runs` for scan lifecycle/status;
- `trend_item_observations` for observation persistence and its existing
  `(scan_run_id, item_id)` uniqueness;
- the existing PostgreSQL advisory lock.

No production schema change or production migration was executed.

## F. Test evidence

- Complete offline suite: **35/35 scripts passed**.
- F-09 offline recovery suite: **12/12 passed**.
- F-09 disposable-PostgreSQL suite: **3/3 passed** (CI).
- Existing ORACLE worker: **20/20 passed**.
- Project ORACLE phase 1: **passed**.
- Creator intelligence: **22/22 passed**.
- F-05 API safety: **16/16 passed**.
- F-07/F-08 creator identity: **13/13 passed**.
- Command contracts: **90/90 passed**.
- Public and restricted callback suites passed.

Final code-commit CI:

- Survival Intelligence Tests (`offline-regression`): **success** —
  https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42490587923
  - Confirmed step: `Run F-09 ORACLE recovery regressions`.
- Phase 2 PostgreSQL Integration (`phase2-postgres`): **success** —
  https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42490587900
  - Confirmed step: `Run F-09 ORACLE recovery PostgreSQL persistence`.

The PostgreSQL test specifically verifies recovery-state persistence across a
new store instance, reuse of a scan run, duplicate observation prevention, and
advisory-lock release/reacquisition.

## G. Remaining limitations

- One active cohort recovery payload is stored. A newly frozen cohort discards
  stale recovery state by design; it does not rewrite historical cohorts.
- Only one ORACLE scan runs at a time via the existing advisory lock.
- Incomplete creators are re-fetched from page 1 on resume. Valid partial
  observations are preserved, and the scan-run uniqueness constraint prevents
  duplicates; pagination cursor persistence is not implemented.
- Page-cap creators are marked incomplete/truncated and are not automatically
  retried to avoid an infinite loop; increasing the cap requires an explicit
  change.
- Timeout/unavailable creators remain in the continuation set and may be
  retried on later scheduled runs; each run is bounded and protected by the
  shared circuit.
- If `creator_patterns` is unavailable, the scan still stops safely but durable
  restart recovery cannot be persisted; the summary marks
  `recovery_persisted=false`. The existing production schema provides this
  table.
- No production scan or live Roblox test was performed.

## H. F-09 verdict

`F-09 CLOSED — VERIFIED`

Discovery outcomes are explicit, partial pages are preserved, rate limits stop
requests and persist continuation, restart recovery is demonstrated against a
disposable PostgreSQL store, typed identities remain independent, duplicates
are prevented, and final status/coverage cannot report success for deferred or
unprocessed work.

## I. Overall certification

**Overall VANTA 73 certification remains NO-GO** until the remaining findings
and live operational release gates are complete. No merge, deploy, production
scan, production migration, M4 activation, or frozen-branch change was made.
