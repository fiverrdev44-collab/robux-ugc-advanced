# VANTA 73 — M5 Test Results

- **Baseline:** `4399eaeea4195b550b8f5f2c77086fb9104ce6c3`
- **Date:** 2026-11-06 (UTC)
- **Host:** Windows, Python 3.12.10
- **Database for integration tests:** disposable PostgreSQL 16.2 via a temporary `pgserver` instance
- **Production systems:** not used for tests. No production writes, API jobs, migrations, or backfills.

## Offline regression suites

All commands below exited `0`.

| Command | Result | Count where emitted |
|---|---|---:|
| `python test_project_oracle.py` | PASS | script suite |
| `python tests/test_oracle_worker.py` | PASS | 20 |
| `python test_rename_watcher.py` | PASS | script suite |
| `python test_rename_tracking.py` | PASS | script suite |
| `python test_survival_intelligence.py` | PASS | script suite |
| `python test_jarvis_cases.py` | PASS | script suite |
| `python test_shared_repairs.py` | PASS | script suite |
| `python test_convergence_live.py` | PASS | 49 |
| `python test_execution_policy.py` | PASS | 25 |
| `python test_command_cancellation.py` | PASS | 3 |
| `python test_emote_title.py` | PASS | 25 |
| `python test_emote_quality_set.py` | PASS | 1 |
| `python test_emote_heldout_quality.py` | PASS | 1 |
| `python test_creator_intelligence_phase1.py` | PASS | 22 |
| `python test_phase2_milestone1.py` | PASS | 7 |
| `python test_phase2_milestone2.py` | PASS | 24 |
| `python test_creator_identity_persistence.py` | PASS | script suite |
| `python test_phase2_milestone3.py` | PASS | 35 |
| `python test_phase2_milestone4.py` | PASS | 30 |
| `python test_snapshot_batch.py` | PASS | script suite |
| `python test_astra.py` | PASS | script suite |
| `python test_product_understanding.py` | PASS | script suite |
| `python test_recommendation_lifecycle.py` | PASS | script suite; DB fixtures skipped without `DATABASE_URL` |

**Counted tests:** 242 individual tests where scripts emitted counts, plus script-based suites that report their own PASS summaries. No failures were observed.

The exact suite list mirrors `.github/workflows/survival-tests.yml` at the frozen baseline.

## Disposable PostgreSQL integration

Command pattern:

```text
PHASE2_TEST_DATABASE_URL=<disposable pgserver URL>
PHASE2_TEST_DB_CONFIRM=disposable
PHASE2_REQUIRE_PG=1
python test_phase2_pg_integration.py
```

Result:

```text
Ran 23 tests in 1.370s
OK
PG_TEST_RETURN_CODE=0
```

Coverage included M2 registry/identity/name-history, snapshot selection/storage, M3 evidence and sales attribution, M4 exact-category retrieval, natural-language token anchors, and read-only guarantees.

## Runtime command registry

A read-only import of `discord_ugc_bot` with dummy `TOKEN` and an unreachable `DATABASE_URL` produced:

```text
90 commands registered
```

The import also started APScheduler threads and attempted a snapshot catch-up connection; that is recorded as finding F-16. No production database was reached.

The runtime registry was compared with `COMMAND_COVERAGE_MATRIX.md`:

- Runtime: 90 commands
- Matrix: 84 commands
- Missing from matrix: `concept`, `emote_title`, `help`, `link`, `outcome`, `rename`
- Matrix status counts: 13 automated, 66 not exercised, 5 manual, 6 missing from matrix

Full details are in `M5_COMMAND_MATRIX.csv`.

## CI evidence

At the frozen baseline and its immediately preceding M4 review point:

- **M4 branch CI** (`de4240947009fc39d7bc2323333b2a5685081c2e`):
  - Phase 2 PostgreSQL Integration: success — `https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42264776965`
  - Survival Intelligence Tests: success — `https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42264776954`
- **Frozen main** (`4399eaeea4195b550b8f5f2c77086fb9104ce6c3`):
  - Oracle Auto-Deploy: success — `https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42273354866`
  - No Survival/PostgreSQL workflow run exists for this main SHA because those workflows run on selected feature-branch pushes and pull requests to main; the direct merge was not a PR.

## Limitations of this evidence

- Synthetic and disposable-database tests do not prove production behavior.
- `test_recommendation_lifecycle.py` skipped its DB fixtures locally because `DATABASE_URL` was intentionally absent.
- 66 registered commands are not exercised by automated tests.
- No live Roblox API load test was performed; API findings are static/architectural plus prior production 429 evidence.
- No production database query was executed in M5. Prior production observations are identified as such and were not re-run.
- The temporary PostgreSQL harness used PostgreSQL 16.2, not the exact production server version.

## Verification commands that were intentionally not run

- Production migrations or backfills.
- `!snapshot_now`, `!sales_backfill`, `!visibility_seed`, `!visibility_run`, `!scan_run`, `!enrich_run`, `!train`, or other mutating commands.
- Destructive or live Roblox API load tests.
- Any command against production Discord channels or production data.
