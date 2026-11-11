# VANTA 73 — Unified Final Release Candidate

## Scope and provenance
- Base: `release/vanta73-final-certification-rc` at `6812cb6e4e251fbcf53789161d3845e1a09efe55`, including merged Avatar Background PR #15 (AssetType 92).
- Port source: `release/vanta73-operational-gate` at `1681eeb1a28cb8281fe72190a73d19b7f2b620ea`.
- Included: corrected type-aware `release/preflight.sql`, `test_operational_gate_preflight_pg.py`, and operational-preflight PostgreSQL CI step.
- CI triggers enabled on `release/vanta73-unified-final-rc` for offline, PostgreSQL, and sales-integrity workflows.
- Prior operational report remains on the operational-gate branch as historical evidence and is **not** represented as a completed staging gate for this unified branch.

## Verification
- On branch creation: NOT TESTED. See exact final-SHA CI checks after push.
- No staging production-like database rehearsal, Discord smoke, F-18 dry-run, or deployment-approval gate has been completed by this integration step.
- `main` and production are not modified.
- `PHASE2_M4_ENABLED` remains at its existing default; this integration does not activate M4.
- A merge into `main` is not authorized: it can trigger the production deploy workflow.

## Required for production
1. Review the unified diff and verify full final-SHA offline/PostgreSQL/sales CI.
2. Run an approved isolated production-like snapshot migration and staging smoke test.
3. Confirm backup/rollback readiness, sales-source dry-run evidence, and independent deployment approval.
4. Only then request separate explicit production deployment approval.
