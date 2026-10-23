# VANTA 73 — Roblox UGC Intelligence Bot

A Discord operations bot for Roblox UGC creators: catalog intelligence, niche scoring,
verified title/description generation, live marketplace checks, launch tracking, and
closed-loop experiments.

**What it is:** a verification and decision-support system. Every AI title, claim, pivot,
and description is gated against real data before it reaches you.

**What it is not:** a guaranteed sales predictor. The ranking model is still experimental.
Current accuracy and limitations are documented below.

---

## Quick start

```
!start
!converge emotes
!chain hip sway dance
!verdict 121930221694467
!autopsy 121930221694467
```

The daily loop is: find a niche → build/verify a name → judge the launched item → record
what happened → measure at 7/14/30 days.

---

## Core workflow

| Command | What it does |
|---|---|
| `!start` | Interactive menu: scan, recon, tags, whale radar, vacuum, revsim, velocity, manual, labs |
| `!converge [family]` | Rank open niches by demand, supply, velocity, recency, and creator concentration |
| `!converge all_families` | Scan every configured family |
| `!converge_debug <keyword>` | Diagnose one keyword’s convergence score |
| `!chain <concept>` | Full pipeline: niche → market → competitors → descriptions → AI titles → verification → statistical ranking → final action block |
| `!chain variant <item_id> [theme]` | Variant of a proven winner |
| `!chain <family>:<concept>` | Family-scoped chain |
| `!verdict <item_id>` | KEEP / RENAME / KILL using age, favorites, velocity, percentile, and sales |
| `!autopsy <item_id>` | Failure diagnosis, peer autopsy, keyword intelligence, recovery titles, live marketplace check, experiment |
| `!revive <item_id>` | Full rebuild: live stats, niche scan, variant chain, peer autopsy, 14-day plan |
| `!brainstorm <concept>` | AI concept expansion with verified titles |
| `!rescue <situation>` | Rebuild a failing item with verified alternatives |
| `!analyze_image` | Attach an image; vision → keywords → verified titles and tags |
| `!creative <concept>` | AI fan-out + DB demand gate |
| `!creative_raw <concept>` | Debug view of anchor phrases and raw AI output |
| `!desc_forge <keyword>` | Mine top-seller descriptions and generate a matching description |
| `!tags <name>` | Generate sales-weighted tags from real top sellers |
| `!playbook` | Proven UGC tactics: niche, naming, pricing, launch, promotion |
| `!path` | Your current UGC stage and next milestones from real data |
| `!guide` | Interactive consultation guide |

---

## Market and intelligence

| Command | What it does |
|---|---|
| `!xray <niche>` | Supply, winners, pricing, and concentration for a niche |
| `!patterns [family]` | Recurring title patterns and word lift |
| `!failures [family]` | Words and patterns correlated with flops |
| `!early [days]` | Early winner detection by favorites velocity |
| `!rising_gaps` | Rising, low-competition keywords |
| `!momentum [days]` | Favorites momentum ranking |
| `!momentum_debug` | Momentum engine diagnostics |
| `!predict <idea>` | Six-factor success score |
| `!oracle <keyword>` | Trend forecast and next-wave detection |
| `!nextwave` | Emerging keywords before they peak |
| `!opportunities` | Daily ranked opportunity feed |
| `!gap` | Golden, sweet, and saturated keyword gaps |
| `!classic` | Classic-clothing keyword gaps |
| `!emote` | Emote market data |
| `!emote_status` | Emote catalog coverage and demand |
| `!analyze <keyword>` | Keyword analysis across titles and descriptions |
| `!desc_analyze <keyword>` | Keywords found only in descriptions |
| `!opportunity <keyword>` | Opportunity score for one keyword |
| `!trends` | Keyword trend history |
| `!velocity <item_id>` | Favorites velocity for an item |
| `!track <item_id>` | Track an item’s favorites history |
| `!watchlist` | Watched items |
| `!history` | Recent saved verdicts |
| `!scan_status` | Scanner progress and coverage |

---

## Sales, pricing, and revenue

| Command | What it does |
|---|---|
| `!sales_report [days]` | Revenue summary and daily trend |
| `!sales_for <item>` | Sales for a specific item |
| `!sales_backfill [limit]` | Import historical sales from the sales channel |
| `!sales_post_now` | Trigger today’s summary |
| `!sales_probe <item_id>` | Probe Roblox sales APIs |
| `!sales_debug` | Diagnose missing sales, dates, timezone, channel |
| `!sales_scan` | Inspect sales-channel embed formats |
| `!sales_keywords` | Learn which title words correlate with sales |
| `!revsim <price> [day1_favs] [promo]` | 30-day revenue scenario with 80% interval; calibrated only when enough ledger outcomes exist |
| `!group_metrics <group_id>` | Roblox group analytics |
| `!cookie_check` | Verify the server-side Roblox cookie |
| `!whales` | Track top-studio drops and activity |
| `!golden_hour` | 48-hour velocity acceleration during the early testing window |
| `!meta_sniper` | High-demand terms top items in a niche do not use |
| `!vacuum` | Scan search suggestions for exploding volume with low competition |
| `!stealth` | Studio-friendly, spam-immune description generator |

---

## Launch ledger and closed-loop experiments

| Command | What it does |
|---|---|
| `!launch <item_id>` | Record an item as launched |
| `!launch_sync` | Auto-log every item from your groups |
| `!ledger_sync` | Fill D1/D7/D30 favorites and sales |
| `!hitrate` | Your launches vs niche peers |
| `!experiments` | Show recommendation outcomes, matched-control DiD, and measure due rows |
| `!applied [id\|last]` | Mark advice as applied; starts the 7/14/30-day measurement |
| `!ignored [id\|last]` | Mark advice as skipped |
| `!data_audit` | Read-only audit: favorites states, duplicate sales/snapshots, ledger gaps, experiment coverage |
| `!visibility` | Search-visibility coverage and freshness |
| `!visibility_seed [n]` | Seed visibility queries from live suggestions |
| `!visibility_run [n]` | Collect due search-visibility observations now |

Recommendations are stored in `recommendation_ledger`. A 15-minute watcher auto-detects
renames and price changes; `!applied last` is only needed for “keep + promote” advice with
no detectable item change. Daily jobs also measure due experiments.

---

## Data and creator operations

| Command | What it does |
|---|---|
| `!verified_scan [limit]` | Scan verified creators; resumable and throttled |
| `!creator_brain` | Study creator patterns from your own data |
| `!scan_run` | Owner-only: discover new catalog items |
| `!enrich_run [batches]` | Owner-only: enrich discovered items |
| `!snapshot_now` | Trigger a favorites snapshot |
| `!suggest_probe` | Probe Roblox autocomplete endpoints |
| `!suggest_run` | Owner-only: run the autocomplete scraper |
| `!train` | Owner-only: retrain the title predictor |
| `!dbtest` | Database connectivity |
| `!logs [n]` | Owner-only: recent bot logs |
| `!version` | Running commit and whether origin is ahead |
| `!bot_update` | Owner-only: sync origin/main and restart |
| `!selftest` | Owner-only: full automated audit |
| `!selftest_db` | Owner-only: database health check |

The “NASA-grade” audit is internal branding, not affiliated with NASA.

---

## Verification pipeline

Every AI output passes these gates before display:

1. **Tokens** — every title token must exist in the category allow-list or verified type words.
2. **Phrase** — family-scoped supply, median favorites, exact-name competition, live demand.
3. **Saturation** — saturation and broad-word warnings are advisory; they do not silently reject proven names.
4. **Claims** — numbers in prose must match a computed fact; fabricated numbers are removed.
5. **Guarantees** — “guaranteed”, “100%”, “will go viral”, “risk-free”, etc. are removed.
6. **Bucket consistency** — the AI cannot call a keyword SATURATED when the DB says NEUTRAL.
7. **Primary keyword / pivot** — must exist and reclassify against the DB; rejected values are cleared.
8. **Descriptions** — customer-facing only; internal metrics, negative copy, promo, and “flex” language are removed. A factual fallback is used if the whole text is unusable.
9. **Live marketplace** — champion titles are checked across up to 10 live search pages for exact matches and relatedness. A capped sample is labeled as such.

Verification proves the words and claims are real. It does **not** prove the item will sell.

Matched-control experiments compare treated items with similar untreated items using
pre-intervention family, age, price and velocity. The result is an observational
difference-in-differences estimate with 80% and 95% intervals. Fewer than five controls
is labeled **exploratory** — never causal proof.

---

## Accuracy status (2026-10-23)

Backtest: time-split holdout; 2,500+ launches across emotes, hair, headwear, accessories, clothing.

```
v1 title score:      AUC 0.440 · top-decile 5.6% vs 10% base
v2 feature model:    AUC 0.533 · top-decile 18.1% vs 12.5% base (unshipped)
Calibration:         v1 ~13.4% vs 10% expected; v2 miscalibrated
Forecast error:      no improvement over the median baseline
```

**v2 is not shipped** because AUC is below 0.55 and calibration is poor. The bot does not
present its ranking as a probability.

Known data gaps:

- 60% of catalog items have a non-NULL favorite count, but only **26.3% have positive favorites**; 66k zeros are ambiguous and 78k are NULL (`favorites_backfill.py` runs nightly).
- `launch_ledger`: 9 rows; 0 D30 favorites; 0 measured experiments.
- Gear is thin; bundles are not true asset-table support.
- Verified-creator discovery is sampled, not exhaustive.

---

## Architecture

| Module | Role |
|---|---|
| `discord_ugc_bot.py` | Orchestrator, watchdog, health endpoint, command registration |
| `menu.py` | Interactive `!start` UI |
| `commands_advanced.py` | Chain, converge, tags, descriptions, creative |
| `commands_ai.py` | Brainstorm, rescue, image analysis |
| `commands_intel.py` | Autopsy, verdict, revive, momentum, predict, oracle, nextwave |
| `commands_xray.py` | X-ray, patterns, failures, early winners |
| `commands_market.py` | Trends, analyze, desc_analyze, opportunity |
| `commands_sales.py` | Sales report, backfill, diagnostics |
| `commands_supercomputer.py` | Operations, vacuum, meta sniper, revsim, whales, selftest |
| `commands_experiments.py` | Applied/ignored/experiments |
| `commands_guide.py` | Guide and playbook |
| `verification.py` | Token/phrase/claim/bucket/description gates |
| `confidence.py` | Bootstrap/prediction intervals, cohort evidence, sales history |
| `opportunity_score.py` | Demand-vs-competition score and visibility proxy |
| `experiments.py` | Recommendation ledger, auto-apply, 7/14/30 measurement |
| `matched_experiments.py` | Pre-intervention matching and observational DiD with 80% interval |
| `search_visibility.py` | Normalized queries, timestamped search runs and observations |
| `data_audit.py` | Read-only data-integrity report |
| `live_market.py` | Paginated live exact/relevance checks |
| `revsim.py` | Ledger-calibrated revenue scenarios |
| `creator_tracker.py` | Verified-creator discovery and live badge checks |
| `favorites_backfill.py` | Fill missing favorites from live Roblox |
| `title_scorer.py` | Word-lift / demand / freshness / uniqueness ranking |
| `tag_generator.py` | Tag mining and filtering |
| `desc_forge.py` | Top-seller description mining |
| `convergence_engine.py` | Five-signal niche scoring |
| `intel_common.py` | Shared percentile, verdict, portfolio logic |
| `chain.py` | Full strategy pipeline |
| `category_configs.py` | Families, vocab, shape rules, generic fallback |
| `gemini_brain.py` | AI prompts, promo filter, title verification |
| `launch_ledger.py` | Launch features, outcomes, recoup labels |
| `scheduler.py` | Daily snapshots, launch sync, experiments, favorites backfill, 15-minute watcher |

---

## Data pipeline

| Job | Schedule | Purpose |
|---|---|---|
| `scanner.py` | 02:00 UTC | Discover catalog items |
| `enricher.py` | Every 6h | Fill descriptions, prices, creators |
| `snapshot.py` | 03:30 UTC + top-ups | Favorites history; ledger items always included |
| `favorites_backfill.py` | 02:30 UTC | Fill missing favorites |
| `suggest.py` | Every 6h | Roblox autocomplete suggestions with rank/volume |
| `discover_keywords.py` | 05:30 UTC | Keyword discovery |
| `backfill_dates.py` | 06:30 UTC | Created-date repair |
| `launch_sync` | 07:30 UTC | Auto-log group items |
| `experiment_measure` | 08:00 UTC | Measure due 7/14/30 checkpoints |
| `experiment_watch` | Every 15 min | Auto-detect renames/prices and measure |
| `favorites_backfill` | 02:30 UTC | Fill NULL and ambiguous-zero favorites, 500/day, ledger items first |
| `visibility` | 04:30 and 16:30 UTC | Sample marketplace search positions and store observations |
| `sales_listener.py` | Live | Parse sale notifications into `my_sales` |

---

## Database (PostgreSQL)

| Table | Purpose |
|---|---|
| `items` | Catalog items: name, description, favorites, price, creator, asset type |
| `item_history` | Favorites/price/sales snapshots |
| `search_suggestions` | Live and mined search phrases, rank, volume |
| `learned_keywords` | Vetted keyword scores |
| `my_sales` | Recorded sales events |
| `launch_ledger` | Launches, D1/D7/D30 favorites, units, revenue, features, labels |
| `recommendation_ledger` | Advice, baseline, applied/ignored, outcome history, model version, DiD |
| `experiment_controls` | Matched control items and pre-intervention distances |
| `search_queries`, `search_runs`, `search_observations` | Search-visibility history |
| `tracked_creators` | Verified creator queue |
| `my_portfolio`, `watchlist`, `item_tracker` | Portfolio and tracking |

`launch_ledger` labels:
- `label_beat_median` — D30 favorites ≥ family median
- `label_top_decile` — D30 favorites ≥ family p90
- `label_recouped` — D30 revenue ≥ `UGC_UPLOAD_FEE_ROBUX` (default 750)

---

## Setup

Schema migrations and rollback: see `MIGRATIONS.md`.

Requirements: Python 3.12, PostgreSQL, Discord bot token, Gemini/OpenAI key, Roblox cookie.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Environment:

```
DISCORD_TOKEN=
DATABASE_URL=postgresql://...
GEMINI_API_KEY=
OPENAI_API_KEY=
ROBLOSECURITY_COOKIE=
SALES_CHANNEL_ID=
MY_GROUP_NAMES=group1,group2
UGC_UPLOAD_FEE_ROBUX=750
```

Run:

```powershell
python discord_ugc_bot.py
```

Deploy: push to `main`; GitHub Actions deploys to Oracle Server 2 and restarts
`ugc-bot` via systemd. `!version` shows the running commit.

---

## Honest limitations

- Ranking is not validated for production use.
- No validated sales/recoup model.
- Live exact checks sample up to 300 results, not the full catalog.
- Verified-creator discovery is sampled.
- Descriptions are creative prose; only claims/numbers/internal language are filtered.
- The bot cannot create demand or guarantee sales.
