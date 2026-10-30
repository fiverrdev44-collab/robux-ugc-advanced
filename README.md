# VANTA 73 — Roblox UGC Intelligence Bot

A Discord operations bot for Roblox UGC creators: catalog discovery and enrichment, niche
scoring, verified title/description generation, live marketplace checks, launch tracking,
sales ingestion, and closed-loop experiments.

**What it is:** a verification and decision-support system. Every AI title, claim, pivot, and
description is gated against real data before it reaches you. It talks like a person (VANTA),
routes to the existing engines, and never executes arbitrary model output.

**What it is not:** a guaranteed sales predictor. The ranking model is still experimental;
current accuracy and data gaps are documented below.

---

## Feature overview

| Area | What you get |
|---|---|
| Conversational VANTA | Public threads or private DMs; casual phrasing, typos, follow-ups, ordinals, image attachments; AI planner with deterministic fast paths |
| Niche discovery | Convergence scan, gap engine, rising gaps, emerging waves, daily opportunity feed |
| Item decisions | KEEP / RENAME / KILL verdicts from age, favorites, velocity, percentile, sales; failure autopsy and full revive plans |
| Creation pipeline | Concept fan-out → competitor/winners analysis → AI titles/descriptions → verification → statistical ranking → final action block |
| Title & description tooling | Word-lift scoring, ML title predictor, pattern/lift mining, sales-weighted keywords woven into descriptions |
| Market intelligence | X-ray dashboards, winner-loser patterns, early winners, momentum, trend oracle, competition checks |
| Sales & revenue | Discord sale ingestion, backfill, per-item and daily reports, revenue simulation, group metrics |
| Launch ledger & experiments | Launch logging, D1/D7/D30 outcomes, recommendation ledger, applied/ignored tracking, matched-control DiD |
| Search visibility | Query seeding, sampled marketplace positions, coverage/freshness reporting |
| Ops & governance | Health endpoint, watchdog, scheduler, selftest/certification, data audit, deploy workflows |

---

## Quick start

```
!start
```

`!start` opens the conversational Command Center:

- **Talk to VANTA** — creates a public `vanta-<user>-<signature>` thread and starts the conversation.
- **Find opportunities** / **Analyze an item** / **Check performance** — send a starter message.
- **Private (DM)** — opens a private conversation with the bot.
- **All tools** — ephemeral list of every registered command.
- **Manual** — beginner walkthrough.

Then talk normally:

```
check this item 121930221694467
why is this item failing?
find me a niche with low competition
i made this, what do you think?   (attach an image)
make a better title and description
i want to change tags
how are my sales doing?
go deeper
the second one
same for this item 92364796546749
```

Everyday loop: find a niche → build/verify a name → judge the launched item → record what
happened → measure at 7/14/30 days.

The legacy button console is still available with `!start classic`, and every original
`!command` works as before.

---

## Conversational interface (VANTA)

`vanta_conversation.py` is a bounded, thread/DM-scoped router. It maps natural language to an
allow-listed set of existing command callbacks — it never invents commands or IDs.

- **Fast paths (deterministic):** greetings, presence checks, acknowledgments, cancel, help,
  bare item IDs/URLs, `!commands`, and ordinal/number replies resolved from pending context.
- **AI planner:** for everything else, Gemini/OpenRouter returns strict JSON
  (`action`, `item_id`, `concept`, `family`, `confidence`, `clarify`). The plan is validated
  against the allow-list before anything runs; unknown or unsafe actions are rejected and the
  deterministic route is used instead.
- **Context:** remembers the last item, result list, tracked items, pending action, and the
  last six messages; "it", "this", "the second one", and `1` resolve against that context.
- **Rate/latency bounds:** at most 20 planner calls per hour per conversation, 30s timeout,
  ~300 output tokens.
- **Ownership:** thread names are HMAC-signed with `VANTA_THREAD_SECRET` (falls back to the bot
  token); ownership is checked with `hmac.compare_digest`, so a lookalike thread name is ignored.
  DMs are bound to the DM channel and author.
- **Privacy:** public threads are visible to channel members; the intro warns and points to
  **Private (DM)** for sensitive details.
- **Registry execution:** matched intents call the existing command callback through a proxy
  context with a 300s timeout; returned item IDs feed back into conversation state.
- **Resilience:** if the AI is unavailable, slow, or over budget, the deterministic classifier
  answers; failures never block normal `!commands`.
- **State lifetime:** in-memory store with a 24h TTL; context resets when the bot restarts.

Intent set: `inspect_item`, `diagnose_item`, `revive_item`, `analyze_image`,
`find_opportunities`, `create_ideas`, `improve_metadata`, `tags`, `check_sales`,
`check_experiments`, `check_visibility`, `data_audit`, `help`, plus conversational glue
(`greeting`, `presence`, `ack`, `cancel`, `list_my_items`, `clarify`).

---

## Command reference

All commands use the `!` prefix. Arguments in `[brackets]` are optional.

### Core workflow

| Command | What it does |
|---|---|
| `!start [classic]` | Command Center (conversational) or legacy tactical console |
| `!converge [family] [limit]` | Rank open niches by demand, supply, velocity, recency, creator concentration (`all_families` scans every family) |
| `!converge_debug <keyword>` | Diagnose one keyword's convergence score |
| `!chain <concept>` | Full pipeline: niche → market → competitors → descriptions → AI titles → verification → statistical ranking → final action block |
| `!chain variant <item_id> [theme]` | Variant of a proven winner |
| `!chain <family>:<concept>` | Family-scoped chain |
| `!verdict <item_id>` | KEEP / RENAME / KILL with age, favorites, velocity, percentile, live sales, confidence interval |
| `!autopsy <item_id> [notes]` | Failure diagnosis, peer autopsy, keyword intelligence, recovery titles, live marketplace check, experiment record |
| `!revive <item_id>` (alias `revive_item`) | Full rebuild: live stats, niche scan, variant chain, peer autopsy, 14-day plan |
| `!brainstorm <description>` | AI concept expansion with verified titles |
| `!rescue <description>` | Rebuild a failing item with verified alternatives |
| `!analyze_image [notes]` + 1–4 images | Vision → keywords → verified titles and tags |
| `!creative <seed>` | AI fan-out (20 concepts) + DB demand gate |
| `!creative_raw <seed>` | Debug view of anchors, raw AI output, parsed concepts |
| `!desc_forge <[family:]keyword>` | Mine top-seller descriptions and generate a matching one |
| `!desc_forge <keyword>` | Powerful, style-matched listing description mined from top sellers |
| `!tags <[family:]name>` | Legacy keyword mining (Roblox removed the tag field; prefer `!desc_forge`) |
| `!guide [idea]` | Interactive four-section consultation (market, risks, pricing/ROI, titles) |
| `!playbook [topic]` | Proven UGC tactics: niche, naming, pricing, launch, promotion |
| `!path` | Your current UGC stage and next milestones from real data |

### Market and intelligence

| Command | What it does |
|---|---|
| `!xray` | Full market X-ray dashboard |
| `!patterns [family]` | Recurring title patterns and word lift |
| `!failures [family]` | Words and patterns correlated with flops |
| `!early [days]` | Early winner detection by favorites velocity |
| `!rising_gaps [days] [category] [seed]` | Rising, low-competition keywords |
| `!momentum [days]` | Favorites momentum ranking |
| `!momentum_debug` | Momentum engine diagnostics |
| `!predict <idea>` | Six-factor success score |
| `!oracle <keyword>` | Trend forecast and next-wave detection |
| `!nextwave` | Emerging keywords before they peak |
| `!opportunities` | Daily ranked opportunity feed |
| `!gap [keyword]` | Golden, sweet, and saturated keyword gaps |
| `!classic <keyword>` | Classic-clothing keyword gaps |
| `!emote <keyword>` | Emote market data |
| `!emote_status` | Emote catalog coverage and demand |
| `!analyze <keyword>` | Keyword analysis across titles and descriptions |
| `!desc_analyze <keyword>` | Keywords found only in descriptions |
| `!opportunity <keyword>` | Opportunity score for one keyword |
| `!trends` | Keyword trend history |
| `!velocity [days] [limit]` | Fastest rising items by favorite velocity |
| `!track <item_id>` | Track an item's favorites history |
| `!watchlist` | Your watched keywords |
| `!history` | Your recent saved verdicts |
| `!scan_status` | Scanner progress and coverage |

### Sales, pricing, revenue

| Command | What it does |
|---|---|
| `!sales_report [days]` | Revenue summary and daily trend |
| `!sales_for <item_name>` | Sales for a specific item |
| `!sales_backfill [limit]` | Import historical sales from the sales channel |
| `!sales_post_now` | Backfill, then post the 7-day summary |
| `!sales_probe <item\|item_id>` | Probe six Roblox sales APIs |
| `!sales_debug` | Diagnose missing sales, dates, timezone, channel |
| `!sales_scan [limit]` | Inspect sales-channel embed formats |
| `!sales_keywords [family]` | Learn which title words correlate with sales |
| `!revsim <price> [initial_favs] [promo]` | 30-day revenue scenario with interval; calibrated only when enough ledger outcomes exist |
| `!group_metrics <group_id> [metric] [days] [limit]` | Roblox group analytics |
| `!cookie_check` | Validate the server-side Roblox cookie and account |
| `!whales [studio_name]` | Track top-studio drops and activity |
| `!golden_hour [limit]` | 48-hour velocity acceleration in the early testing window |
| `!meta_sniper <niche>` | High-demand terms top items in a niche do not use |
| `!vacuum [limit]` | Search suggestions with exploding volume and low competition |
| `!stealth <name>\|<category>\|<style>` | Studio-friendly, spam-immune description generator |

### Launch ledger, experiments, visibility

| Command | What it does |
|---|---|
| `!launch <item_id> [launched] [notes]` | Record an item as launched |
| `!launch_sync [groups]` | Auto-log every item from your groups |
| `!ledger_sync` | Fill D1/D7/D30 favorites and sales |
| `!hitrate [days]` | Your launches vs niche peers |
| `!experiments [limit]` | Auto-apply changes, measure due rows, show matched-control DiD, print summary |
| `!applied [id\|last]` | Mark advice as applied; starts 7/14/30-day measurement |
| `!ignored [id\|last]` | Mark advice as skipped |
| `!data_audit` (alias `integrity`) | Read-only audit: favorite states, duplicate sales/snapshots, ledger gaps, experiment coverage |
| `!visibility` | Search-visibility coverage and freshness |
| `!visibility_seed [limit]` | Seed visibility queries from live suggestions |
| `!visibility_run [limit]` | Collect due search-visibility observations now |
| `!verified_scan [limit]` (alias `scan_verified`) | Scan verified creators; resumable and throttled |
| `!creator_brain` (aliases `meta`, `cohort`) | Study creator patterns from your own data |

### Operations and diagnostics

| Command | What it does |
|---|---|
| `!scan_run` | Owner-only: discover new catalog items |
| `!enrich_run [batches]` | Owner-only: enrich discovered items |
| `!snapshot_now` | Trigger a favorites snapshot |
| `!suggest_probe [query]` | Probe Roblox autocomplete endpoints |
| `!suggest_run` | Owner-only: run the autocomplete scraper |
| `!train` | Owner-only: retrain the title predictor |
| `!dbtest` | Database connectivity and backlog |
| `!ai_status` | AI provider configuration and reachability |
| `!ai_debug` | AI environment diagnostics + live provider test |
| `!logs [lines]` | Owner-only: recent bot logs |
| `!version` | Running commit and whether origin is ahead |
| `!bot_update` | Owner-only: sync `origin/main` and restart |
| `!selftest` | Owner-only: full automated audit and certificate |
| `!selftest_db` | Owner-only: database/infra health score |

Owner-only commands are restricted to `BOT_OWNER_ID` / `DISCORD_OWNER_ID` plus built-in
operator IDs. The "NASA-grade" audit is internal branding, not affiliated with NASA.

---

## Verification pipeline

Every AI output passes staged gates in `verification.py` before display:

1. **Tokens** — 3–6 tokens, no duplicates, and every token must resolve to the category
   allow-list, verified type words, or an allowed stem. Failures drop the title.
2. **Phrase** — family-scoped supply, median/top favorites, exact-name competition, and live
   search demand. Database errors fail closed.
3. **Claims** — numbers in prose must match a computed fact (tolerance `max(1, 15%)`).
4. **Guarantees** — "guaranteed", "100%", "will go viral", "risk-free", etc. are removed.
5. **Buckets** — the AI cannot call a keyword SATURATED when the DB says NEUTRAL; bucket text is
   reconciled against the database.
6. **Pivot / primary keyword** — must exist, resolve in the DB, and have live demand; DEAD,
   SATURATED, GHOST, zero-supply/zero-demand values are cleared. VIRGIN requires live demand.
7. **Descriptions** — customer-facing only; internal metrics, negative copy, promo, and "flex"
   language are removed. A factual fallback is used if the text becomes unusable.
8. **Lanes** — new-name selection prefers OPEN/CONTESTED lanes; if every survivor is SATURATED,
   the final block says so.
9. **Live marketplace** — champion titles are checked across up to 10 live search pages for
   exact matches and relatedness; capped samples are labeled.

Verification proves the words and claims are real. It does **not** prove the item will sell.

---

## Experiments and confidence

- `experiments.py` owns `recommendation_ledger`: every verdict/autopsy/revive recommendation is
  stored (7-day dedupe, supersede), applied/ignored is tracked, and outcomes are measured at the
  nearest 7/14/30-day checkpoint. Outcomes compare favorites, velocity, and `my_sales` units
  against baselines and append to `outcome_history`.
- `matched_experiments.py` compares treated items with the nearest untreated items using only
  pre-intervention features (log price, age/30, log pre-velocity). It reports an observational
  difference-in-differences estimate with 80% and 95% bootstrap intervals. Fewer than five
  controls is labeled **exploratory** — never causal proof.
- `confidence.py` builds 80% cohort intervals (bootstrap + Wilson) for favorites/velocity,
  top-decile and top-1% thresholds, and sales-derived units. With fewer than 20 cohort items it
  falls back to the family and finally reports `insufficient` instead of a guess.
- `pivot_history.py` keeps pivot advice consistent across repeated autopsies.

---

## AI stack

`gemini_brain.py` is the single AI entry point.

- **Providers:** Google Gemini (preferred, `GEMINI_API_KEY`) and OpenRouter (OpenAI-compatible
  fallback, `OPENROUTER_API_KEY`). Vision uses OpenRouter's vision model when Gemini is absent.
- **Models:** `GEMINI_MODEL` (default `gemini-3.5-flash-lite`), `OPENROUTER_MODEL`
  (default `qwen/qwen-2.5-72b-instruct:free`), `OPENROUTER_VISION_MODEL`.
- **Capabilities:** keyword extraction, search-term expansion, keyword intelligence
  (GOLD/OPPORTUNITY/SATURATED/WEAK/DEAD/NEUTRAL + pivot + diagnosis), hybrid title/description
  synthesis (10 titles across 4 buckets), image analysis, and Q&A.
- **JSON mode** on both providers; deterministic fallbacks (`generate_fallback_titles`,
  `fallback_title_payload`) when the model is unavailable or output is invalid.
- **Retries/limits:** Gemini retries 4× on 503/500/timeouts and stops on 429/quota/permission;
  OpenRouter retries 3×. Provider-reported token usage is logged per call
  (`get_last_usage`); an input estimate is logged only when usage is unavailable.
- Titles are always re-verified after generation; unverified AI titles are withheld, never shown.

Supporting engines: `title_scorer` (word lift, demand, freshness, uniqueness, champion pick),
`title_predictor` (linear ML, trained from the ledger), `winner_analysis` (winners vs losers),
`algo_brain` (Roblox ranking heuristics), `category_configs` (families, vocabulary, shape rules),
`tag_generator` (tag mining + relevance gate), `desc_forge` (top-seller description mining),
`creative_expand`/`creative_pivot` (concept fan-out and category-gated pivots),
`gap_engine`/`rising_gaps` (gap discovery), `market_velocity`/`momentum` (velocity facts),
`oracle`/`opportunity_feed` (forecasts and daily feed), `peer_autopsy` (nearest-winner diffs),
`recovery_brain` (failure modes + Roblox fetch/save), `smart_pipeline` (parallel competition
scan + live enrichment), `ugc_playbook` (tactics and audits).

---

## Data pipeline

GitHub Actions run the heavy crawlers on the Oracle server; the in-process scheduler runs
bot-side jobs. All times UTC.

| Job | When | Purpose |
|---|---|---|
| `scanner.py` | 02:00 (Actions) | Discover catalog items across 6 categories × 6 sorts + learned keywords |
| `enricher.py` | Manual workflow / `ugc-enrich.service` loop | Fill descriptions, prices, creators, favorites; mark permanent failures |
| `live_enrich.py` | On demand (library) | Keyword search + detail fetch with rate limits and circuit breaker |
| `snapshot.py` | 03:30 + top-ups 09:30/15:30/21:30 + catch-up | Favorites history; ledger items always included |
| `favorites_backfill.py` | 02:30 | Fill NULL and ambiguous-zero favorites (500/day, ledger first) |
| `suggest.py` | 04:30/10:30/16:30/22:30 (Actions) | Autocomplete suggestions with rank; DB-mined fallback |
| `discover_keywords.py` | 05:30 (Actions) | Mine and score keywords from 30k items |
| `backfill_dates.py` | 06:30 (Actions) | Repair `items.created_at` |
| `launch_sync` | 07:30 (scheduler) | Auto-log group items |
| `experiment_measure` | 08:00 (scheduler) | Measure due 7/14/30 checkpoints |
| `experiment_watch` | Every 15 min (scheduler) | Auto-detect renames/price changes and measure |
| `verified_scan` | 01:15/07:15/13:15/19:15 | Crawl verified creators |
| `creator_brain` | 05:00 | Study creator cohorts |
| `daily_ml_train` | 04:00 | Retrain the title predictor |
| `post_monitor` | 18:00 | Post the 7-day sales report |
| `visibility` | 04:30/16:30 | Sample marketplace search positions |
| `sales_listener.py` | Live | Parse sale notifications into `my_sales` |

---

## Database (PostgreSQL)

| Table | Purpose |
|---|---|
| `discovered_items` | Raw IDs found by the scanner (pending enrichment) |
| `failed_items` | Permanent 400/404 IDs, retried at most 3 times |
| `items` | Catalog rows: name, description, favorites, price, creator, asset type, `favorite_status` |
| `item_history` | Daily favorites/sales/price snapshots |
| `search_suggestions` | Autocomplete results per seed keyword |
| `learned_keywords` | Vetted keyword scores mined from titles/descriptions |
| `user_profiles`, `saved_consultations` | Per-user profile and stored verdict reports |
| `watchlist`, `competitor_tracking`, `item_tracker` | Per-user tracking |
| `my_portfolio` | User-owned items |
| `my_sales` | Sale events (`sale_date`, `sale_time`, dedupe `source_event_id`, source) |
| `launch_ledger` | Launches, D1/D7/D30 favorites, units, revenue, features, labels |
| `recommendation_ledger` | Advice lifecycle, baselines, outcomes, matched-control results |
| `experiment_controls` | Matched control items and pre-intervention distances |
| `creator_patterns`, `tracked_creators` | Creator findings and verified-creator queue |
| `search_queries`, `search_runs`, `search_observations` | Search-visibility history |

Notable indexes: `item_history` per-item and one-per-day uniqueness, `pg_trgm` GIN on
`items.name`, partial unique indexes for `my_sales` (`source_event_id`, fingerprint fallback),
recommendation due-time and item indexes, visibility observation uniqueness.

Writes are idempotent: `IF NOT EXISTS` tables/columns/indexes, `ON CONFLICT DO NOTHING/UPDATE`,
pre-index dedupe deletes, and safe per-statement rollback. Schema changes and rollback are
documented in `MIGRATIONS.md`.

`launch_ledger` labels:

- `label_beat_median` — D30 favorites ≥ family median
- `label_top_decile` — D30 favorites ≥ family p90
- `label_recouped` — D30 revenue ≥ `UGC_UPLOAD_FEE_ROBUX` (default 750)

---

## Architecture

| Module | Role |
|---|---|
| `discord_ugc_bot.py` | Orchestrator: command registration, health endpoint, watchdog, scheduler boot |
| `bot_core.py` | DB connection, lexicons, analysis/report helpers, profiles, watchlist |
| `bot_ui.py` | Paginators, guide navigation, prompt helper |
| `menu.py` | `!start` Command Center and legacy console |
| `vanta_conversation.py` | Natural-language router, thread signing, DM flow, planner, registry proxy |
| `commands_advanced.py` | Chain, converge, tags, descriptions, creative |
| `commands_ai.py` | Brainstorm, rescue, image analysis, AI diagnostics |
| `commands_intel.py` | Autopsy, verdict, revive, momentum, predict, oracle, nextwave, creator brain |
| `commands_xray.py` | X-ray, patterns, failures, early winners |
| `commands_market.py` | Trends, analyze, desc_analyze, opportunity, gaps, tracking, data audit |
| `commands_sales.py` | Sales reports, backfill, probes, group metrics, cookie checks |
| `commands_supercomputer.py` | Ops, whales, vacuum, meta sniper, revsim, ledger, selftest, version/update |
| `commands_experiments.py` | Applied/ignored/experiments |
| `commands_guide.py` | Interactive consultation guide |
| `commands_visibility.py` | Visibility coverage, seeding, collection |
| `verification.py` | Token/phrase/claims/pivot/description gates |
| `confidence.py` | Bootstrap/Wilson cohort intervals and sales history |
| `opportunity_score.py` | Demand-vs-competition score and lane priority |
| `experiments.py` | Recommendation ledger and 7/14/30 measurement |
| `matched_experiments.py` | Pre-intervention matching and observational DiD |
| `search_visibility.py` | Query registry, runs, observations, coverage |
| `data_audit.py` | Read-only integrity report |
| `live_market.py` | Paginated live exact/relevance checks |
| `revsim.py` | Ledger-calibrated revenue scenarios |
| `title_scorer.py`, `title_predictor.py`, `title_pipeline.py` | Title scoring, ML predictor, seed/alternative pipeline |
| `tag_generator.py`, `desc_forge.py` | Tags and description mining |
| `convergence_engine.py`, `gap_engine.py`, `rising_gaps.py` | Niche and gap discovery |
| `market_velocity.py`, `momentum.py`, `early_winners.py` | Velocity, momentum, breakout detection |
| `oracle.py`, `predictor.py`, `opportunity_feed.py` | Forecasts, success score, daily feed |
| `pattern_forge.py`, `winner_analysis.py`, `competition_check.py`, `peer_autopsy.py` | Patterns, winners, competition, peer autopsy |
| `algo_brain.py`, `creator_brain.py`, `recovery_brain.py`, `smart_pipeline.py`, `ugc_playbook.py` | Ranking heuristics, cohorts, recovery, parallel pipeline, tactics |
| `gemini_brain.py` | AI prompts, providers, fallbacks, usage tracking |
| `category_configs.py`, `intel_common.py`, `launch_ledger.py`, `pivot_history.py` | Shared config, verdict/pivot logic, ledger sync, pivot consistency |
| `scanner.py`, `enricher.py`, `live_enrich.py`, `snapshot.py` | Crawl and enrich pipeline |
| `suggest.py`, `discover_keywords.py`, `backfill_dates.py`, `favorites_backfill.py` | Auxiliary data repair and discovery |
| `sales_listener.py`, `post_monitor.py`, `creator_tracker.py` | Sales ingestion, reporting, creator crawling |
| `scheduler.py` | In-process jobs (snapshots, training, measurements, watcher) |
| `selftest.py` | Full automated audit and command harness |

Paused / not wired: `vanta_guide.py` (a `!guide`/`!tools` field manual) and `vanta_tools.py`
(its tool directory) are not registered; the live `!guide` is `commands_guide.py`.

Unused or standalone: `title_simulator.py` (no imports), `backtest_opportunity.py` (CLI),
and `title_pipeline.py`, `title_miner.py`, `creative_pivot.py`, `competition_check.py`
(covered by the selftest import smoke check only).

---

## Operations

- **Health:** Flask endpoint `/` returns 200 `OK` only when the bot is ready, not closed, and
  latency is under 120s; otherwise 503. `/trigger-report` (POST, `X-Trigger-Token`) runs the
  post-monitor on demand.
- **Watchdog:** 120s startup grace, then a 60s loop; closed bot, NaN latency, or >120s latency
  triggers `os._exit(1)` for systemd to restart.
- **Services:** `ugc-bot` (Discord bot) and `ugc-enrich` (looping enricher) on the Oracle server,
  both `Restart=always`-style systemd units. Environment for pipeline jobs lives in
  `/etc/ugc-bot/pipeline.env`.
- **Deploy:** push to `main` → GitHub Actions resets `~/robux-ugc-advanced` to `origin/main`,
  installs deps, clears `__pycache__`, and restarts `ugc-bot`. Workflows also run the scanner,
  suggest scraper, keyword discovery, date backfill, manual enrichment/refresh, and a DB check.
- **Self-healing commands:** `!version`, `!bot_update`, `!selftest`, `!selftest_db`, `!logs`.

---

## Testing

```
python test_vanta_conversation.py    # router/planner, pure (no Discord, no DB)
python test_integrity_upgrades.py    # normalization, DiD math, lane gates, DB idempotency
python selftest.py                   # full audit (env, schema, freshness, engines, live items)
```

`!selftest` runs the same audit plus a command harness and issues a certificate only when there
are no hard failures and the effective score is ≥90.

---

## Setup

Requirements: Python 3.11+ (server runtime 3.11.9; developed on 3.12), PostgreSQL, Discord bot
token, a Gemini or OpenRouter key, and a Roblox cookie for live checks.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python discord_ugc_bot.py
```

Environment:

```
TOKEN=                      # Discord bot token
DATABASE_URL=postgresql://...
GEMINI_API_KEY=
GEMINI_MODEL=               # default gemini-3.5-flash-lite
OPENROUTER_API_KEY=
OPENROUTER_MODEL=
ROBLOSECURITY_COOKIE=       # also ROBLOSECURITY_COOKIE_1..5 for scanner workers
ROBLOX_USER_ID=
SALES_CHANNEL_ID=
ALERT_CHANNEL_ID=
MY_GROUP_NAMES=group1,group2
UGC_UPLOAD_FEE_ROBUX=750
BOT_OWNER_ID=
DISCORD_OWNER_ID=
TRIGGER_TOKEN=
PORT=10000
VANTA_THREAD_SECRET=        # optional; falls back to the bot token
```

Tuning knobs include `ENRICH_BATCH_SIZE`, `SNAPSHOT_TOP_ITEMS`, `SNAPSHOT_MIN_FAVS`,
`VISIBILITY_MAX_PAGES`, and `VISIBILITY_DELAY`.

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

- 60% of catalog items have a non-NULL favorite count, but only **26.3% have positive
  favorites**; 66k zeros are ambiguous and 78k are NULL (`favorites_backfill.py` runs nightly).
- `launch_ledger`: 9 rows; 0 D30 favorites; 0 measured experiments.
- Gear is thin; bundles are not true asset-table support.
- Verified-creator discovery is sampled, not exhaustive.

---

## Honest limitations

- Ranking is not validated for production use; no validated sales/recoup model.
- Live exact checks sample up to 300 results, not the full catalog.
- Descriptions are creative prose; only claims/numbers/internal language are filtered.
- Description "tags" are not a ranking field — Roblox removed avatar item tags in December 2025,
  so keyword ideas must live in the title and description. Keywords must still share a token
  with the item name or category type words.
- The bot cannot create demand or guarantee sales.
- Conversational public threads are visible to channel members; use **Private (DM)** for
  sensitive details. Thread ownership is HMAC-verified; the visible user ID alone is not trusted.
- Conversation context is in-memory with a 24h TTL and resets on restart.
- The AI planner is bounded: allow-listed actions only, ~300 output tokens, 20 calls/hour per
  conversation, 30s timeout, deterministic routing first. No mutating operation is routed from
  casual language.
- Provider-reported token usage is logged per AI call; otherwise an explicit input estimate is
  logged.
