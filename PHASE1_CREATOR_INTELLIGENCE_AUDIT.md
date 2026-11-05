# VANTA 73 — Creator Intelligence Phase 1 Audit

Status: **Phase 1 (intelligence foundation)**. Observational intelligence only.
No self-improvement claim. `ASTRA_LEARNING_IN_GENERATION` remains **OFF**.
No production data was modified, no migrations applied, no deploy.

---

## 1. Architecture audit

| Module | Role | Inputs | Outputs | Phase 1 finding |
|---|---|---|---|---|
| `creator_tracker.py` | Discover/track creators | Roblox catalog + badge | `tracked_creators`, `items` | Discovery is verified-only → sampling bias. Kept for tracking; learning no longer restricted to it. |
| `creator_brain.py` | Cohort study | `items` | `creator_patterns` | Success-only (top median) cohort; verified-only switch in `!creator_brain`. Added representative segments; command now learns from all creators. |
| `trend_cohorts.py` | Period cohorts | `items`, history | cohort stats | Snapshot-window logic; missing observations handled by period filters. |
| `oracle_worker.py` | Snapshot/velocity | `items`, `item_history` | observations | Velocity requires ≥2 snapshots; missing history stays missing. |
| `pattern_forge.py` | Feature association | `items` | lift results | **Defect:** comparison group excluded favorite *values*, not items without the feature. Fixed. |
| `peer_autopsy.py` | Peer comparison | `items` | autopsy report | Descriptive; not used as a causal estimator. |
| `learning.py` | Measured-outcome retrieval | `recommendation_ledger` | prompt context | Added readiness audit, timing guard, verified-sale exclusion; flag stays off. |
| `creative_expand.py` / `chain.py` | Creative generation | findings/context | titles/descriptions | Learning context attached only when the explicit flag is on. |
| `convergence_engine.py` | DB discovery | `items`, `item_history` | candidates | Labels measured vs missing velocity, median favorites, sampled supply. |
| `convergence_live.py` | Live verification | Roblox catalog | sampled evidence | Asset-type filtering, 429/deferred handling, caches; samples, not totals. |
| `recommendation_ledger` | Closed-loop ledger | proposals/outcomes | measured outcomes | Application and measurement timestamps present; readiness not yet proven. |
| `launch_ledger.py` | Published catalog | uploads | launch baseline | Independent outcome source; not automatically joined to the recommendation ledger. |

### Duplicated / inconsistent logic

- Median implementations differed (upper median vs true median). Fixed in
  `pattern_forge` and `creator_brain`; convergence already uses
  `percentile_cont(0.5)`.
- Feature tokenization is duplicated between `pattern_forge` and
  `creator_brain`; both now count item-level membership, but they are not yet a
  single shared feature store.
- Catalog pacing is still split across `convergence_live`,
  `live_market.check_title`, `live_enrich`, `creator_tracker`, and `enricher`.
  Phase 2 should consolidate, not add a sixth scheduler.
- `!converge`, `!chain`, `!creator_brain`, and `learning` do not share a
  persisted evidence/version model.

### Unreliable measurements / misleading statistics

- Favorites are not sales, demand, CTR, revenue, or profit.
- Autocomplete occurrences are not verified buyer demand.
- Live catalog samples are not total marketplace supply.
- A verified badge is not evidence of strong sales.
- A low observed competitor count is not evidence of high demand.
- Missing favorites/observations must remain missing, not plausible numbers.
- Success-only and popularity-ranked cohorts create survivorship/popularity
  bias; comparisons need representative segments and confounder controls.

---

## 2. Evidence lineage map

```
Roblox public APIs
  ├─ catalog search/details ──> live_market / creator_tracker / enricher
  │        └─ items: favorite_count, price, creator_name, created_at, asset_type_id
  │        └─ item_history: favorite snapshots (oracle_worker / trend windows)
  └─ user/group badge ────────> tracked_creators.verified
Discord sales notifications
  └─ sales_listener ──────────> my_sales: item, buyer, amount, transaction time
Recommendations
  ├─ chain / converge / emote > recommendation_ledger: proposal, baseline,
  │                             application_status, applied_at, measure_at
  └─ launch_ledger ───────────> published item baseline + launch outcome
Learning
  └─ learning.load_measured_outcomes: applied + mature + measured outcome,
       excludes insufficient DiD, unverified sales, and measured_at < applied_at
Convergence
  └─ convergence_engine (DB) + convergence_live (live sample, asset type 61)
```

Evidence classes used in this phase:

| Class | Examples | Treatment |
|---|---|---|
| Observed | favorites, price, timestamps, item IDs, verified badge, `my_sales` rows | Report as observed; favorites ≠ sales |
| Model/heuristic | candidate ranking, lift, confidence labels | Labeled heuristic; no causal/probability claim |
| Assumption | age/price/category strata, verified badge meaning | Documented; not treated as ground truth |
| Unknown | missing favorites, missing snapshots, unverified sales, absent demand | Remain unknown/missing |

---

## 3. Confirmed defects and Phase 1 fixes

### D1 — `pattern_forge` comparison group (confirmed)
Old: `without = [f for f in all_favs if f not in favs_list]` — this removes
**all items sharing a favorite value**, including non-featured items.
New: item-ID membership (`features[feat]` is a set of item IDs; the comparison
group is `all_ids - with_ids`), then prefer the same
(category, age bucket, price bucket) stratum, then same category, then global.
Results now include `without_count`, `comparison_scope`,
`creator_concentration`, `single_creator_dominated`, `metric="favorites"`,
`causal=False`.

Synthetic before/after (2 featured items at 100/50 favorites; non-featured
100/50/10/10):
- Before: comparison = [10, 10], median 10, lift 7.5x, no sample size shown.
- After: comparison = [100, 50, 10, 10], median 30, lift 2.5x,
  `without_count=4`, scope `same_category_price_age`.

### D2 — Median definition
Upper median for even samples replaced with the true median
(`[1,2,3,4] → 2.5`) in `pattern_forge` and `creator_brain`.

### D3 — Zero-favorite items excluded from failure patterns
`_fetch_all` used `favorite_count > min_favs`; with `min_favs=0` this excluded
observed zero-favorite items. Changed to `>=`, so underperformers with 0
favorites are represented.

### D4 — Fabricated favorites in `commands_supercomputer.py`
Removed both `(item_id % 7500) + 250` fallbacks from `!whales` and
`!golden_hour`. Added `format_favorite()`: `None → "unknown"`, `0 → "0"`,
`1234 → "1,234"`. Existing `database.py` setup already clears the old
`(ABS(id) % 8500) + 150` synthetic rows on startup.

### D5 — Verified-only creator learning
`!creator_brain` switched to `verified_only=True` whenever any verified creator
existed. Changed to representative mode (`learn(cur)`), so nonverified creators
remain in the cohort. `creator_brain` still supports an explicit
`verified_only=True` for a caller that asks for it.

### D6 — Success-only creator comparison
The primary pattern analysis still uses the top-median-favorites cohort, but it
is now explicitly labelled a **success cohort** (`cohort_label`,
`cohort_selection`, `cohort_is_representative=false`) and is never described as
representative. `build_comparison_cohorts()` is kept separate and reports
established/emerging, verified/nonverified, and top/average/underperformer
segments with their own population and selection metadata
(`selection.population`, `selection.segments`, `selection.representative=false`).

`save()` persists the comparison summary and cohort labels, and
`load_findings()` restores them. A cached study that lacks a comparison summary
is labelled unavailable and explicitly warns not to read the success cohort as
representative. Nonverified and underperforming creators remain visible in the
comparison analysis.

### D7 — Learning readiness (consistent eligible population)
`learning_readiness()` now computes every threshold over **one eligible
population** using a CTE:

- applied (`applied_at` or `status='applied'`),
- measured (`measured_at`, `outcome` present),
- mature/partial,
- temporally valid (`measured_at >= applied_at`).

Within that population:
- sales evidence requires explicit `outcome.verified = true` **and** a non-null
  `item_id` (missing verification is not proof);
- controls are counted only on eligible outcomes;
- eligibility, maturity, verified-sales, and control thresholds all come from
  the same rows.

`load_measured_outcomes()` likewise excludes sales outcomes without explicit
verification or item attribution, and retains the timing guard. The generation
flag remains **OFF**. Separately satisfied ledger-wide counts can no longer
produce a false-positive READY.

### D8 — Convergence evidence
No redesign. The existing labels (observed DB evidence, sampled live results,
keyword-level vs candidate-title verification, velocity measured/missing,
deferred/Retry-After) are documented in the Phase 2 contract below.

---

## 4. Regression tests

`test_creator_intelligence_phase1.py` (22 tests, synthetic fixtures only):

- Favorite-value comparison trap → item membership; before/after lift.
- Missing favorites skipped.
- Unequal item ages restricted to the same stratum.
- Insufficient sample sizes excluded.
- Creator concentration reported/flagged.
- Duplicate token observations counted once.
- Empty cohort.
- True median.
- Zero-favorite items included in failure patterns.
- `format_favorite` keeps missing unknown and zero as zero.
- No synthetic favorite formula in the source.
- Learning readiness: one eligible population; disjoint thresholds cannot
  produce READY; missing sales verification does not count; thin population
  fails; temporal leakage fails.
- Learning retrieval excludes unverified sales, unattributed sales, and
  insufficient DiD outcomes.
- Representative creator segments include nonverified and underperforming
  creators; success cohort is labelled and separate.
- `save()`/`load_findings()` preserve the comparison summary and cohort labels;
  cached reports without a comparison warn against success-only interpretation.
- Partial Roblox API failure is marked incomplete.

Existing suites (shared, JARVIS, ASTRA, product understanding, convergence,
execution policy, sales integrity) remain green. No write-based integration test
was run because no staging database was available; all tests are offline fakes.
No production data was touched.

---

## 5. Remaining limitations

- Strata are coarse (category × age bucket × price bucket). No multivariate
  adjustment; creator concentration is reported, not adjusted.
- Pattern mining and failure patterns are observational and selection-biased;
  they are not causal effect estimates.
- `creator_tracker` discovery is still verified-only; `creator_brain` now
  compares all creators present in `items`, but the underlying sample is not yet
  a probability sample of the marketplace. Comparison segments are a broader
  convenience sample, not probability-representative, and cached legacy studies
  may lack a comparison summary.
- Learning readiness thresholds are conservative and not yet demonstrated on
  production data; verified, attributed sales evidence is not proven. The
  generation flag remains off.
- `!converge` live results are samples; low competitor counts are not demand.
- No AI calls were added; the system is not self-improving and does not claim to
  be.

---

## 6. Phase 2 implementation plan

1. **Representative creator sampling**: add nonverified/emerging discovery and a
   category × age window sample; stop treating verified as success.
2. **Shared evidence model**: persist normalized item/creator/feature evidence
   with observation timestamps and source/version; make `pattern_forge`,
   `creator_brain`, and convergence read the same evidence.
3. **Confounder-aware comparisons**: matched or stratified comparisons on
   category, age, price, creator tier; report effect sizes and uncertainty only
   where the method justifies it.
4. **Verified outcome linkage**: join `my_sales`/`launch_ledger` to recommended
   items; require verified attribution before "demand" or "profitability".
5. **Convergence integration**: implement the contract below; add
   representative competition checks and demand evidence; forbid
   low-competitor → high-demand inference.
6. **Measured learning**: out-of-time/prequential evaluation, no future
   leakage, explicit controls; only then consider enabling
   `ASTRA_LEARNING_IN_GENERATION`.
7. **Staging DB harness** for write-based integration tests; never touch
   production.

---

## 7. Phase 2 integration contract — `!converge` → Creator Intelligence

`!converge` may provide:

- **Candidate**: `keyword`, `family`, `score`, `components`
  (`natural_readability`, `memorability`, `product_clarity`, `originality`,
  `relevance`, `verified_similarity`, `verified_competition`,
  `evidence_completeness`), `evidence_status`.
- **Observed DB evidence**: `supply` (favorites-filtered sample), `recent`,
  `median_favs`, `p90_favs`, `concentration`, and `velocity` +
  `velocity_measured` (missing when observations are insufficient).
- **Autocomplete**: `demand`/`demand_volume` — labeled unverified occurrences,
  never verified buyer demand.
- **Live sample**: `sampled_results`, `category_correct`,
  `category_mismatched`, `exact_title_matches`, `conceptual_matches`,
  `top_competitors`, `checked_at`, `retry_after`, `deferred`,
  `skipped_for_sufficiency`.
- **Candidate-title verification**: `exact` / `similar` / `conceptual` / `none` /
  `insufficient` / `unverified`, with timestamps.

Creator Intelligence **must**:

- treat favorites as observed engagement, not sales;
- treat live samples as samples, not total supply;
- treat missing velocity/favorites as unknown;
- consume `deferred`/`retry_after` and never retry early;
- join verified sales (`my_sales` / `launch_ledger`) before claiming demand or
  profitability;
- keep candidate-title verification separate from keyword-level matches;
- avoid causal or CTR/sales-probability claims.

Creator Intelligence **must not**:

- infer demand from a low competitor count;
- treat verified badges as sales evidence;
- learn from unapplied, immature, unverified, or temporally leaked outcomes;
- enable `ASTRA_LEARNING_IN_GENERATION` without passing the readiness audit and
  independent review.

---

## 8. Before/after summary

| Area | Before | After |
|---|---|---|
| Pattern comparison | favorite-value exclusion | item-ID with/without; stratified comparison; sample counts |
| Median | upper middle | true median |
| Zero-favorite items | excluded from failure patterns | included |
| Missing favorites | fabricated display fallback | `unknown`; zero stays zero |
| Creator cohort | top-median / verified-only switch, unlabeled | success cohort explicitly labelled; separate comparison segments; persisted in cache |
| Learning | ledger-wide aggregate counts; unverified sales could count | one eligible population; verified, attributed sales only; flag OFF |
| Convergence | labels present but undocumented | documented Phase 2 evidence contract |

---

## 9. CI / commit

- Full offline CI (`offline-regression`) is triggered on the branch push and
  includes this new suite; the run URL and final SHA are reported in the
  delivery message.
- No merge, deploy, migration, or production mutation was performed.
