# VANTA 73 — Interpretation Upgrade (review branch)

**Status:** committed on branch `jarvis-interpretation`; **not deployed** (deploy workflows trigger only on
`main`/`master`). Merge to deploy.

## What changed

1. **Evidence records** (`evidence.py`): observed / missing / stale / partial / estimated / inferred, with
   metric, unit, asset, window, source, observation time, coverage. `numeric()` refuses wrong-metric or
   missing values.
2. **Learning retrieval** (`learning.py`): measured outcomes from `recommendation_ledger` are read only when
   `measured_at` and `outcome` exist, maturity is `mature`/`partial`, and the DiD payload is not
   `insufficient: true`. Injected into the chain and autopsy prompts when present.
3. **Durable memory** (`memory.py` + `conversation_memory` table): last item, candidates, pending offers,
   recent messages and title map survive restarts, scoped to channel + user with a 24h TTL.
4. **Interpretation-first outputs**: chain’s `# FINAL — DO THIS` is now `# ASSESSMENT & OPTIONS` with
   “nothing is applied automatically”; TikTok/verdict steps are conditional wording. Autopsy’s scale
   branch is “WHAT THE EVIDENCE SUGGESTS … options, not instructions”.
5. **Creative diversity**: `_diverse_titles()` removes near-duplicate adjective stacks while keeping
   original wording that has no historical precedent.
6. **Coverage** (`COMMAND_COVERAGE_MATRIX.md`): 84 canonical commands with aliases, implementation and the
   suite that covers them.

## Before → after (representative)

**Autopsy, item 86973415376933**
- Before: “Zero sales after 182 days” + failure/KILL protocol while KEEP was shown above.
- After (production run on `e6df59a`): `KEEP`, `💰 6 sales (30d)`, and
  `WHAT THE EVIDENCE SUGGESTS … Sales exist, so this is not a failure case`.
  Automated checks: `zero sales=False`, `kill=False`.

**Chain for a wooden fence prop**
- Before: “Earthy Wooden Fence Hat”, “Cyber Board Necklace”.
- After: waist family, type override `None`, belt-based options; prop gate strips
  necklace/chain/backpack/tail/wing/hat in chain and autopsy.

## Evidence that outcomes are retrieved (not just recorded)

`learning.format_learning_context()` returns `''` when no valid measured outcome exists (current
production state has 0 measured rows), and injects a labelled block when one does. `test_jarvis_cases.py`
proves an `insufficient: true` outcome is excluded and a mature outcome is included with its scope.

## Tests

- `test_jarvis_cases.py` — 6 checks: evidence semantics, insufficient-outcome exclusion, diversity,
  memory round-trip, no-directive wording, original wording preserved.
- Existing suites all pass: `test_vanta_conversation.py`, `test_identity_and_windows.py`,
  `test_recommendation_lifecycle.py`, `test_shared_repairs.py`.

## Remaining limitations

- No mature measured outcomes exist in production yet, so the learning loop is wired and tested but has
  nothing to retrieve until experiments mature.
- Memory stores router context only (channel+user); it does not persist full transcripts.
- The coverage matrix marks most commands “not exercised” — registered, but no per-command automated run.
- No analytical output mutates Roblox items; only existing explicit commands do.
