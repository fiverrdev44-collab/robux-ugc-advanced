# Background Intelligence Upgrade — Evidence and Limitations

## 1. Root cause report

- `!background_analyze` did not exist in the repository history. There is no
  `background_review.py`, `background_opportunities.py`, or
  `category_creator_learning.py` in any local or origin branch.
- The existing background implementation is `background_intelligence.py`
  (`build_report`, `query_backgrounds`, `rank_items`), exposed through
  `!early 7 backgrounds` in `commands_xray.early_cmd`. It is deliberately
  title/database-only: it reads capped `items`/`item_history` rows, extracts
  title themes, and states that visual review is not included.
- `commands_ai.analyze_image()` used the generic UGC vision prompt and then
  queried the generic DB allow-list. It did not perform AssetType-92 live
  searches, did not compare actual competitor listings, and did not produce a
  background-specific scene brief.
- `commands_advanced.chain_cmd()` used `live_market.check_title()` for every
  family. That live check was not AssetType-filtered, so background results
  could be contaminated by unrelated asset types.
- `chain.run_chain()` had no channel for visual observations from an image
  analysis; `!chain backgrounds:` could only use the text concept.
- `convergence_engine.FAMILIES` did not contain `backgrounds`, so
  `resolve_family_ids("backgrounds")` returned no IDs even though category
  configuration recognized AssetType 92. Unknown families also returned no
  filter instead of failing closed.
- These defects explain a report of stored title matches without reliable live
  competitor checks, no independent image verification, and generic
  descriptions. A DB sample or title keyword list is not a live marketplace
  result.

## 2. Minimal code changes

- Ported the existing `background_intelligence.py` and its four tests from
  `feat/avatar-background-intelligence-92` onto the certified RC background
  integration branch.
- Added `background_analyze.py`, a coordinator that reuses existing engines:
  - actual Discord image bytes through `gemini_brain.analyze_image_for_ugc`;
  - a background-specific scene prompt and a second independent verification
    prompt;
  - `avatar_backgrounds.validate_image` for structural file checks;
  - `convergence_live.verify_niche(..., family="backgrounds")` for live
    AssetType-92-only comparisons;
  - `avatar_backgrounds.build_creative_brief` for scene-design fallbacks.
- Added `background_analyze` as an **alias** of the existing owner-only
  `analyze_image` command (no new canonical command, count remains 90).
  `command_security.COMMAND_ALIASES` maps it, preserving owner authorization
  and AI-cost policy.
- Added `id`, `creator`, `favorites`, `price`, `created_at`, and a bounded
  `competitors` list to `convergence_live.verify_niche` results.
- Added `backgrounds: [92]` to `convergence_engine.FAMILIES` and made unknown
  family filters fail closed (`and 1=0`).
- Added `visual_context` to `chain.run_chain` and passed the last validated
  background analysis from `commands_advanced.chain_cmd`.
- For `!chain backgrounds:`, replaced the unfiltered `check_title()` live check
  with `verify_niche(..., family="backgrounds")`.
- Added `test_background_analyze.py` and updated the survival CI workflow.

## 3. Live verification status

- Offline/mock evidence verifies live success, HTTP 429, deferred, empty
  results, sparse creator data and the AssetType-92 family filter.
- **No authorized staging Discord channel or live API verification was
  available in this environment.** Therefore deliverable 4 (an actual staging
  Discord output) and the live portion of deliverable 5 are **BLOCKED**, not
  fabricated.
- The analyzer can be exercised in staging with:
  `!background_analyze <scene notes>` plus an attached image, then
  `!chain backgrounds:<concept>`.
- An approved Discord webhook is evidence of notification origin, not proof of
  a Roblox transaction; favorites are not sales.

## 4. Rendered output shape (synthetic fixture, not staging)

A mocked Oggy-inspired cartoon-house fixture produces:

- Image evidence: structural file check, first-pass scene summary, setting,
  landmarks, lighting/palette, atmosphere/composition.
- Verification: independent status plus discrepancies; on failure, explicit
  `first-pass only` label.
- Live evidence: query, timestamp, status, sampled/type-92/exact counts,
  actual competitor IDs, names, creator, favorites, price, publication date
  when returned.
- Titles: one preferred original, two alternatives; franchise option is
  marked as an authorization/IP-risk hypothesis.
- Editorial comparison table and a scene-specific description/search terms.
- Explicit "no sales, revenue, CTR, impressions, conversion or verified demand"
  boundary.

Synthetic example (not an actual Discord message):

```text
# 🌌 BACKGROUND ANALYZE — AssetType 92
## 👁️ Image evidence
• Evidence: first-pass vision + verified independent check
• Scene: A rounded cartoon house on a quiet street with an orange roof.
## 🛰️ LIVE marketplace evidence (AssetType 92 only)
• Query `cartoon house background` · ok · 12 sampled · 12 type-92
  - [Toon House Background](https://www.roblox.com/catalog/111222333)
## 🏷️ Title options — one preferred, two alternatives
**Preferred:** **Toon House Avatar Background**
**Alternative 1:** Playful Toon House Background
**Alternative 2:** Oggy-Inspired Toon House Background
```

## 5. Tests

- Complete offline suite on the feature branch: **39/39 passed**, 0 failed.
- New `test_background_analyze.py`: **12/12 passed** (Oggy-inspired,
  original cartoon house, missing image, vision failure, verification failure,
  live success, 429, empty results, sparse creator data, family/chain context,
  command alias, no CTR/sales claims).
- Ported `test_background_intelligence.py`: **4/4 passed**.
- Existing command contracts: **90/90 passed**; restricted callbacks passed.
- `test_convergence_live.py`: passed after adding background fields.

## 6. Remaining limitations

- Actual staging Discord output and live Marketplace verification remain
  blocked pending staging access and explicit authorization.
- The second independent visual pass consumes a second AI provider call; the
  existing AI-cost limiter applies, but this is a real cost. Disable with
  `verify=False` only in tests/admin contexts.
- Publication dates are shown only when the live search response returns
  `itemCreatedUtc`/`itemUpdatedUtc`; otherwise the report says unavailable.
- The search response is a bounded sample; it is not complete marketplace
  coverage, demand, sales or CTR.
- Franchise terms are not banned; the report marks IP authorization as
  unverified and does not claim legal safety.
- No production merge, deployment, migration, M4 activation, or Avatar
  Background merge was performed.
