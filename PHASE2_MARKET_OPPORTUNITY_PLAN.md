# VANTA 73 — Phase 2: Market Opportunity Intelligence

Phase 2 connects existing evidence systems into opportunity discovery. It does
not create a second intelligence engine and does not enable autonomous learning.

## Reuse map

| Existing system | Phase 2 role |
|---|---|
| Creator Brain (`creator_brain.py`) | Success cohort + separate representative comparison segments |
| Pattern Forge (`pattern_forge.py`) | Observational feature associations with sample sizes and confounders |
| ORACLE (`oracle_worker.py`, `item_history`) | Snapshot-based favorite velocity where observations exist |
| Convergence (`convergence_engine.py`, `convergence_live.py`) | DB shortlist + sampled live competition |
| Creator tracking (`creator_tracker.py`, `tracked_creators`) | Stable creator identifiers and provenance |
| Recommendation/launch ledgers | Applied/measured outcomes; verified sales evidence |
| `learning.py` | Readiness audit only; generation flag remains OFF |
| `my_sales` | Verified sales evidence where legitimately linked |

## Evidence classes

- **Observed**: favorites, prices, timestamps, IDs, verified badge, `my_sales`.
- **Sampled**: live catalog search results (not total supply).
- **Heuristic**: rankings, lift, confidence labels.
- **Assumption**: strata, badge meaning, windows.
- **Unknown/Missing**: missing favorites, snapshots, verified sales, demand.

Favorites ≠ sales. Autocomplete ≠ demand. Low competition ≠ opportunity.
Verified badge ≠ strong sales. No causal claims.

## Milestone sequence

### M1 — Reporting integrity (implemented in this branch)
1. `!golden_hour`: replace “velocity/algorithmic momentum” with observed
   favorites plus **snapshot-measured velocity only when ≥2 snapshots span at
   least 1 hour**. Otherwise `velocity unavailable`. Rank measured velocity
   first, then observed favorites. Label “not algorithmic ranking data”.
2. `!failures`: remove the 999 placeholder. Report under/high-favorite
   frequencies and sample sizes; `ratio=None` + `evidence` when the comparison
   frequency is zero or the comparison group is empty.
3. `!whales`: relabel “live surveillance of top 50 studios” as a **stored
   catalog sample from monitored studio names**, explicitly not live and not
   50-studio coverage.

Acceptance: fixtures for sparse snapshots, missing favorites, zero comparison
frequencies, and corrected labels; no fabricated velocity or ratios.

### M2 — Creator discovery expansion
- Add a `creator_registry` view/table keyed by `(creator_id, creator_type)` with
  stable IDs, verified flag, item counts, category mix, publication-age window,
  price bands, and evidence provenance.
- Discovery samples nonverified/emerging creators from the same catalog
  searches; no separate API budget increase.
- Deduplicate creators by ID (names can change/collide).
- Segment: established/emerging, verified/nonverified, top/average/under.
- Tests: duplicate names with different IDs, name changes, empty cohorts,
  rate-limit-aware discovery.

### M3 — Opportunity validation bridge
- `!converge` provides an evidence bundle: candidate concept, DB sample,
  measured velocity where available, sampled live competition, category, price,
  age, creator participation, title-level verification, missing evidence.
- Creator Intelligence adds creator-level context (independent participation,
  concentration, comparison segment).
- Verified sales are joined only when `my_sales`/`launch_ledger` provide
  attributable evidence.
- Output must show confidence limitations and incomplete coverage; low
  competition alone is never “opportunity”.
- Tests: misleading rankings, partial API failures, sparse snapshots, sampling
  bias, false high-demand conclusions.

### M4 — Original UGC ideas
- Generate grounded concepts from validated observations (emote/accessory),
  never copying another creator’s design or choreography.
- Every recommendation includes: original concept, intended audience,
  supporting observations, competition findings, confidence limitations, key
  risks, suggested validation experiment.
- Tests: concept provenance, no copied titles/choreography, unsupported claims
  rejected, no invented demand.

### M5 — Evaluation and staging
- Add a staging DB harness for write-based integration tests; production remains
  read-only.
- Pre-register evaluation metrics (evidence completeness, ranking agreement,
  false-demand rate).
- Learning remains disabled until eligible-population readiness and independent
  review pass.
- Tests: end-to-end offline, then staging.

## Phase 2 data contracts (additive; no production migration in M1)

- `intelligence_evidence`: `source`, `observed_at`, `metric`, `value`, `unit`,
  `sample_n`, `provenance`, `is_estimated`, `is_missing`.
- `creator_registry`: stable ID/type, display name, verified, segment,
  first/last seen, source.
- `opportunity_candidate`: concept, family, evidence IDs, competition sample,
  verified sales evidence (nullable), confidence, limitations.

## Safety and limits

- Preserve all existing Discord commands.
- No `!emote_title` changes.
- No autonomous learning; `ASTRA_LEARNING_IN_GENERATION` stays off.
- Respect Roblox rate limits and Retry-After; no additional paid APIs.
- No production writes in M1; staging only for future write tests.
- Do not merge or deploy automatically.

---

# Milestone 1 implementation note

Files: `commands_supercomputer.py` (`golden_hour`, whale labels),
`pattern_forge.py` (failure ratio), `test_phase2_milestone1.py`,
`.github/workflows/survival-tests.yml`.

Expected behavior:
- Golden window: measured snapshot velocity or explicit “velocity unavailable”.
- Failures: no 999; sample sizes shown; zero comparison frequency is
  insufficient evidence, not an artificial ratio.
- Whales: stored-sample label, not live/50-studio surveillance.
