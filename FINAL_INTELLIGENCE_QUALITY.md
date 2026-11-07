# VANTA 73 — Final Intelligence Quality Assessment

- **Baseline:** `d6976d3e404303f6ddccb8f64785c84112c2ffc6`
- **Branch:** `audit/final-vanta73-certification`
- **Implementation SHA:** `0e1510d2e160c5792592d74e681135c806e90233`
- **Evidence type:** offline synthetic fixtures, disposable PostgreSQL, and
  existing held-out title tests. No live model quality or sales-performance
  evaluation was performed.

## Marketplace evidence

PASS:
- M3 separates observed/sampled/heuristic/unknown evidence and refuses to treat
  missing live verification as zero competition.
- M4 requires metric-specific evidence for sales, favorites, creator counts,
  competitors, demand, and percentages.
- M4 labels popularity-ordered samples as non-representative convenience
  samples and reports undated exclusions.
- M4 rejects fabricated sales/revenue claims and keeps hypothetical validation
  experiments allowed.
- Favorites are consistently distinguished from sales in the repaired paths.

LIMITED:
- Production creator-ID coverage was previously ~0.38%; M3/M4 degrade to
  item-sample creator evidence and mark registry-dependent data unavailable.
- Database evidence is bounded and cannot establish full-category supply.
- No live marketplace verification is performed by M4.

## Predictions and probability language

Fixed:
- `predictor.py` now calls its output a heuristic opportunity score, not a
  probability.
- Removed “Attack immediately”, “Launch within 7 days”, and similar directives.
- `opportunity_feed.py` and `menu.py` now use heuristic-score language.
- ROI output no longer fabricates expected sales or revenue from favorites.

Remaining:
- The underlying heuristic factors are not calibrated against a held-out
  outcome dataset.
- `intel_common.d30_milestone_probability` remains a family-cohort heuristic;
  it is explicitly labeled “uncalibrated” where displayed.
- `algo_brain.py` previously asserted universal CTR/freshness thresholds. The
  text was softened to heuristic guidance, but platform ranking behaviour is
  still not independently validated.
- `confidence.py` contains a documented assumption that conversion may transfer
  between niches; this is a limitation, not measured evidence.

## Title generation and `!emote_title`

PASS:
- Existing emote title tests pass: 25 core, 1 quality-set, 1 held-out.
- `emote_title_engine.py` explicitly states no CTR or sales predictions are
  produced.
- Title ranking is described as creative quality, not CTR/sales/demand.
- `!emote_title` remains public with a bounded per-user/global quota; denied
  requests make zero AI/API calls.

LIMITED:
- Title quality evidence is offline/synthetic and does not establish live
  marketplace performance.
- The command is public by design and can consume the global allowance.
- No live A/B or causal sales evidence exists.

## Category coverage

Synthetic/disposable evidence covers:
- Emotes
- Hair
- Headwear
- Face accessories
- Back/neck/waist accessories
- Mixed/unsupported category rejection

LIMITED:
- Live marketplace comparisons for every category were not performed.
- Category-specific evidence remains bounded by stored data and exact asset-type
  filters where implemented.
- Clothing/Gear paths are supported by existing convergence taxonomy but were
  not comprehensively behavior-tested in this pass.

## Product identity and originality

PASS:
- M4 rejects exact/near-duplicate competitor titles, copied choreography and
  distinctive accessory designs, unrelated substituted concepts, protected
  character references, and duplicate concepts within one response.
- M4 labels textual similarity checks as non-legal, non-global originality
  evidence.
- M2 composite creator identity is used by creator-registry paths.

LIMITED:
- `creator_brain.py` still groups by display name, so name collisions/renames
  can contaminate creator patterns.
- `tracked_creators` remains keyed by numeric creator ID, so User/Group
  collisions can misattribute types in ORACLE paths.

## Overall intelligence verdict

**Conditional / not certified for release.** The repaired evidence and claim
paths are materially safer, but calibration, live category coverage, stable
creator identity in ORACLE, and production-only behavior remain unverified.
No simulated result is presented as sales performance.
