# VANTA 73 — Roblox UGC Intelligence Bot

A Discord operations bot for Roblox UGC creators: catalog discovery and enrichment, niche
scoring, verified title/description generation, live marketplace checks, launch tracking,
sales ingestion, and closed-loop experiments.

**What it is:** a verification and decision-support system. Creative pipelines apply product,
identity, claim, and marketplace-evidence checks where supported; coverage and live-data
completeness vary by command. It talks like a person (VANTA), routes to registered engines,
and does not execute arbitrary model-generated commands.

**What it is not:** a guaranteed sales predictor. The ranking model is still experimental;
current accuracy and data gaps are documented below.

---

## Release status and final audit (2026-11-07)

> **Current state: M6-A merged and automatically deployed; final A–Z certification is still pending.**
> VANTA 73 is a research/decision-support tool, not a validated CTR, conversion, or revenue predictor.

| Milestone or gate | Verified status |
|---|---|
| Protected production branch | `main` at [`d6976d3`](https://github.com/fiverrdev44-collab/robux-ugc-advanced/commit/d6976d3e404303f6ddccb8f64785c84112c2ffc6); active ruleset |
| M6-A authorization, secrets, and AI usage limits | [PR #12](https://github.com/fiverrdev44-collab/robux-ugc-advanced/pull/12) merged on 2026-11-06 21:41 UTC |
| Oracle Auto-Deploy | [GitHub Actions run 42298766141](https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42298766141) succeeded on that exact merge commit |
| Production Discord smoke checks reported by operator | `!help`, `!ai_status`, and owner `!ai_debug` responded; provider hello checks succeeded without revealing key material |
| Remaining runtime smoke checks | Non-owner authorization, `!version`, service health/logs and M4 environment flag require explicit production evidence |
| Registered commands | **90** in `command_security.ALL_COMMANDS`; runtime dispatch inventory must be reconfirmed in the final audit |
| Historic command coverage matrix | `COMMAND_COVERAGE_MATRIX.md` lists **84**, including **13 automated**, **5 manual**, **66 not exercised**; stale baseline, **not** a current post-M6-A coverage claim |
| Final release verdict | **NOT CERTIFIED** — final command-by-command, data-integrity, intelligence-quality and production checks outstanding |

**Feature freeze:** No new command families, autonomous learning, expanded scraping, or M4 activation during final certification. A successful merge/deploy is not proof that all 90 commands work.

### Completed milestones at a glance

- **Phase 2 M1–M3:** existing evidence-labeling, creator-discovery and opportunity-validation improvements connect marketplace observations, cohort comparisons, and live checks without treating favorites as sales.
- **Phase 2 M4:** original-UGC concept work is merged into `main` but **dormant**. `PHASE2_M4_ENABLED` was last reported OFF by the operator; its actual live value is **not independently verified here**. Do not enable until its separate activation gate is approved.
- **M5:** read-only A–Z assessment identified remaining security, model-accuracy, API-budget, creator-identity, DB/ORACLE, CI, and command-coverage defects. That audit does **not** constitute a passing release certificate.
- **M6-A:** centralized authorization, secret-safe AI diagnostics, per-user/global AI throttling, planner limits, aliases and integration/security tests delivered and merged through protected `main`. See [M6A_SECURITY_CORRECTION.md](M6A_SECURITY_CORRECTION.md) and [M6A1_SALES_SOURCE_REVIEW.md](M6A1_SALES_SOURCE_REVIEW.md). Those files were written before the merge; this status table supersedes their original “not deployed” statements.

### What the creator workflow is intended to accomplish

```text
Discover across UGC categories  ->  Compare niche and creator cohorts
-> Validate product idea and title  ->  Launch / record baseline
-> Observe favorites, visibility and owned sales
-> Compare against relevant peers  ->  Keep / test a change / move on
```

This is a decision workflow, **not** an automatic sales-optimization guarantee. Owned-item sales records require trusted source attribution; competitor sales, CTR, and revenue cannot be inferred from favorites.

---

## Feature overview

| Area | What you get |
|---|---|
| Conversational VANTA | Public threads or private DMs; casual phrasing, typos, follow-ups, ordinals, image attachments; AI planner with deterministic fast paths |
| Niche discovery | Convergence scan, gap engine, rising gaps, emerging waves, daily opportunity feed |
| Item decisions | KEEP / RENAME / KILL verdicts from age, favorites, velocity, percentile, sales; failure autopsy and full revive plans |
| Creation pipeline | Concept fan-out → product understanding → competitor/winners analysis → AI titles/descriptions → verification → statistical ranking → Analyst Report |
| Algorithmic tracking | `!link`/`!rename` baselines, `!outcome` D7/D30 deltas, auto-link every 2 h, rename watcher every 15 min, algorithmic-fit heuristic (frozen version) |
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
  ~400 output tokens.
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

## M6-A security and deployment controls

M6-A is the first merged security-hardening release ([PR #12](https://github.com/fiverrdev44-collab/robux-ugc-advanced/pull/12)).

- **Authorization before command execution:** `command_security.py` classifies 90 canonical commands; the declared policy has 52 owner-only, 37 public read-only, and one public rate-limited AI command (`!emote_title`). Unknown commands fail closed, and aliases resolve to their canonical command. **Note:** policy labels still require a side-effect audit (see below).
- **Secret-safe diagnostics:** `!ai_debug` is owner-only; API keys are reported as configured/not configured, not as key prefixes, lengths, or values. Provider connectivity probes can incur calls.
- **AI-cost protection:** standard owner AI commands use a sliding 600-second limiter (owner 20 and global 30 by default; non-owner default 5 where applicable). `!emote_title` remains public with its own **10 non-owner / 20 owner / 30 global** calls per 600 seconds. Rejected requests are blocked before callbacks.
- **Conversation AI planner:** deterministic routes avoid provider calls; non-owner **20/hour**, owner **100/hour**, and global **200/hour** attempt quotas apply *before* external calls. Failed/time-out attempts count. Limits are process-local and restart with the bot; do not treat them as distributed quotas.
- **Protected deployments:** active main-branch ruleset requires a PR, disallows force-push/deletion, and requires up-to-date `offline-regression` and `phase2-postgres` GitHub Actions checks. Merging to `main` invokes the Oracle SSH auto-deploy; the workflow does **not** automatically apply DB migrations.
- **CI cleanup still needed:** Sales Integrity Tests and Survival Intelligence Tests both publish a job called `offline-regression`. Unique check names and corresponding ruleset updates are a release-hardening task.

**Do not confuse "public read-only" in the declared policy with a verified absence of side effects.** For example, the current `!verdict` callback can fetch live Roblox item data and upsert it to PostgreSQL; `!creator_brain` saves computed findings; `!hitrate` refreshes ledger records. All require accurate reclassification, authorization review, and integration tests during the final audit.

---

## Command reference

All commands use the `!` prefix. Arguments in `[brackets]` are optional.

### Core workflow

| Command | What it does |
|---|---|
| `!start [classic]` | Command Center (conversational) or legacy tactical console |
| `!converge [family] [limit]` | Rank open niches by demand, supply, velocity, recency, creator concentration (`all_families` scans every family) |
| `!converge_debug <keyword>` | Diagnose one keyword's convergence score |
| `!chain <concept>` | Full pipeline: product understanding → niche/market → competitors → verified AI titles → statistical ranking → seven-section Analyst Report |
| `!chain variant <item_id> [theme]` | Variant of a proven winner |
| `!chain <family>:<concept>` | Family-scoped chain |
| `!emote_title <movement description> [reference URL]` | Emote-specific original title generator, product/motion validation, bounded category-correct DB/live comparison, creative-quality scoring and launch-observation plan; owner or bounded public quota |
| `!concept <category> \| <creative request>` | Dormant Phase 2 M4 original-UGC command; requires separately approved feature-flag activation |
| `!help [command]` | Registered Discord command help |
| `!verdict <item_id>` | Item evidence and KEEP/RENAME/KILL options; **currently may live-refresh/upsert PostgreSQL**, so not verified read-only |
| `!autopsy <item_id> [notes]` | Scale-vs-recovery routing: sales > 0 or KEEP/DOUBLE_DOWN runs SCALE PROTOCOL; only KILL/RENAME with zero sales runs failure diagnosis, peer autopsy, recovery titles, live check, experiment record |
| `!revive <item_id>` (alias `revive_item`) | Full rebuild: live stats, niche scan, variant chain, peer autopsy, 14-day plan |
| `!brainstorm <description>` | AI concept expansion with verified titles |
| `!rescue <description>` | Rebuild a failing item with verified alternatives |
| `!analyze_image [notes]` + 1–4 images | Vision → keywords → verified titles and tags |
| `!creative <seed>` | AI fan-out (20 concepts) + DB demand gate |
| `!creative_raw <seed>` | Debug view of anchors, raw AI output, parsed concepts |
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
| `!predict <idea>` | Six-factor **uncalibrated heuristic**; currently mislabels score as a success probability (open accuracy defect) |
| `!oracle <keyword>` | Trend forecast and next-wave detection |
| `!nextwave` | Emerging keywords before they peak |
| `!opportunities` | Daily ranked opportunity feed |
| `!gap [keyword]` | Emote-only keyword gap sample (current SQL filters to asset type 61); not an all-UGC scan |
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
| `!sales_report [days]` | Sale records and recorded amount with explicit UTC window, asset-mapped vs unresolved coverage, and amount-semantics warning |
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
| `!launch <item_id> [launched] [notes]` | Record an item as launched; VANTA then auto-scans your catalog for a matching recommendation |
| `!link <run_id> <item_id>` | Link a generated run to any asset (old or new); captures the launch-time baseline now |
| `!rename <run_id> <item_id>` | Same as `!link` for an existing item you just renamed; reports rename baseline |
| `!outcome <run_id>` | D7 favorites gained and sale records since the link/rename moment |
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
| `scanner.py` | 02:00 (Actions) | Discover items via search pages **plus monotonic ID stepping** (30-item batches, `SCANNER_ID_WINDOW`) |
| `enricher.py` | Manual workflow / `ugc-enrich.service` loop | **30-item batch details** (`roblox_batch_client.py`) with bulk upsert; marks missing/404 IDs as failed |
| `live_enrich.py` | On demand (library) | Keyword search + detail fetch with rate limits and circuit breaker |
| `snapshot.py` | 03:30 + top-ups 09:30/15:30/21:30 + catch-up | Favorites history via **30-item batch client** and bulk unnest update; tiered half-life selection (`SNAPSHOT_TIER_LIMIT`, default 1500) |
| `favorites_backfill.py` | 02:30 | Fill NULL and ambiguous-zero favorites (`FAVORITES_BACKFILL_LIMIT`, default 1500/day, ledger first) |
| `rename_watcher` | Every 15 min (scheduler) | Check live titles for recent rename advice; capture a fresh baseline when a rename is detected |
| `market_research_worker` | Every 6 h (scheduler) | Priority refresh (launch ledger → recent launches → exploratory) in 30-item batches |
| `auto_link` | Every 2 h (scheduler) | Match new/renamed owned items to recent unlinked runs and capture baselines |
| `suggest.py` | 04:30/10:30/16:30/22:30 (Actions) | Autocomplete suggestions with rank; DB-mined fallback |
| `discover_keywords.py` | 05:30 (Actions) | Mine and score keywords from 30k items |
| `backfill_dates.py` | 06:30 (Actions) | Repair `items.created_at` |
| `launch_sync` | 07:30 (scheduler) | Auto-log group items |
| `experiment_measure` | 08:00 (scheduler) | Measure due 7/14/30 checkpoints |
| `experiment_watch` | Every 15 min (scheduler) | Auto-detect renames/price changes and measure |
| `verified_scan` | 01:15/07:15/13:15/19:15 | Crawl verified creators |
| `creator_brain` | 05:00 | Study creator cohorts (existing verified-creator system) |
| `trend_cohorts` | 05:30, when `ORACLE_ENABLED=1` | Build/freeze ORACLE creator cohorts |
| `oracle_scan` | Every 6 h, when `ORACLE_ENABLED=1` | Discover cohort assets, batch-fetch current metadata, append observations and calculate favorites/day velocity |
| `daily_ml_train` | 04:00 | Retrain the title predictor |
| `post_monitor` | 18:00 | Post the 7-day sales report |
| `visibility` | 04:30/16:30 | Sample marketplace search positions |
| `sales_listener.py` | Live | Parse sale notifications into `my_sales` |

### Project ORACLE — Phase 1 and Phase 2

ORACLE is an additive research subsystem. It does not replace the existing
`tracked_creators`, `creator_tracker.py`, `creator_brain.py`, `!verified_scan`,
or `!creator_brain` workflows.

- **Discovery:** `oracle_worker.py` uses `creator_tracker.search_creator_complete()`.
  Roblox `SortType=3` means recently updated, not recently created; the worker filters
  with the discovery response's actual `itemCreatedUtc` timestamp (stored as
  `created_at`). Missing creation timestamps are retained as unknown rather than
  being silently interpreted as recent launches.
- **Fetch:** discovered numeric asset IDs are fetched in one batch-client call per scan.
  The original asset ID and discovery creation timestamp are preserved.
- **Velocity:** `favorites_delta`, `hours_since_last`, and
  `favorites_velocity` are derived from timestamped favorite observations.
  `favorites_velocity` is favorites per day, not lifetime favorites divided by age.
  Missing favorites remain NULL; ORACLE does not infer sales for other creators.
- **Coverage:** creator type is never guessed. Unknown User/Group types are skipped and
  counted; page-cap truncation, discovery rate limits and failed asset fetches make
  the scan partial rather than silently reporting complete coverage.
- **Scheduling:** `oracle_scan` runs every six hours only when
  `ORACLE_ENABLED=1` at scheduler startup. The worker checks the flag again at runtime.
  A PostgreSQL advisory lock prevents overlapping scans.
- **Scan history:** `trend_scan_runs` records each run; `trend_item_observations`
  is append-only and unique per `(scan_run_id, item_id)`.

**Migration and production boundary:** Phase 2 schema changes are in
`migrations/2026-11-02_project_oracle_phase2.sql`. The normal deploy workflow
does not apply SQL migrations. Verify that the Phase 1 migration (including
`trend_item_observations.scan_run_id`) is present before applying Phase 2.
Apply the Phase 2 migration through the Council-approved database pipeline only.
Do not set `ORACLE_ENABLED=1` until the required Phase 1 and Phase 2 tables/columns
are confirmed in the target database.

**Manual smoke run:** after migrations are applied and the Council authorizes a live
scan, activate the same environment used by the bot and run
`python -m oracle_worker`. The module prints a JSON summary. With
`ORACLE_ENABLED` unset or not equal to `1`, it returns a disabled summary and
does not connect to the database. The manual command does not apply migrations.

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
| `creator_patterns`, `tracked_creators` | Existing creator findings and verified-creator queue |
| `trend_creator_cohorts` | Frozen ORACLE ELITE / EMERGING / CONTROL creator snapshots |
| `trend_item_observations` | Append-only, timestamped creator-item metadata and favorite observations |
| `trend_scan_runs` | ORACLE scan lifecycle, coverage counts, skips, truncation and errors |
| `astra_runs` | Generated concepts/titles, chosen title, `linked_item_id`, `linked_at` |
| `astra_outcomes` | Per-run launch/rename baseline and `launched_at` for D7/D30 deltas |
| `sales_name_aliases` | Confirmed/candidate sale-name → asset aliases (beanie rename fixture) |
| `conversation_memory` | Durable router context per user+channel (24 h TTL) |
| `search_queries`, `search_runs`, `search_observations` | Search-visibility history |

Notable indexes: `item_history` per-item and one-per-day uniqueness, `pg_trgm` GIN on
`items.name`, functional `idx_items_name_lower_trim` on `items (lower(trim(name)))`, partial
unique indexes for `my_sales` (`source_event_id`, fingerprint fallback), recommendation due-time
and item indexes, `sales_name_aliases` item index, Astra run/outcome indexes, visibility
observation uniqueness.

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
| `roblox_batch_client.py` | Async 30-item catalog POST client: token bucket, AIMD, jitter backoff, CSRF |
| `product_understanding.py` | Shared family/colors/details/motion model with per-fact source; emote-thumbnail and static-motion rules |
| `astra_report.py` | Seven-section Analyst Report for `!chain` (product, market, angles, test, description, preview, measurement) |
| `market_research_worker.py` | 6-hour priority research cycle with circuit breaker and idempotent upserts |
| `rename_watcher.py` | 15-minute rename detector that snapshots a fresh launch baseline |
| `creator_memory.py` | Astra runs, `!link`/`!rename` baselines, `!outcome` deltas, auto-link matcher |
| `commands_astra.py` | `!link`, `!rename`, `!outcome` |
| `apply_phase3_migration.py`, `apply_missing_index.py` | One-time migration/index runners |
| `astra.py` | Algorithmic-fit heuristic (frozen `astra-fit-v1`), platform guard, identity lock, Astra output |
| `item_resolver.py` | Canonical sale→asset identity (`sales_name_aliases`), confirmed rename fixtures |
| `reporting.py` | Single definition of UTC reporting windows and amount semantics |
| `evidence.py` | Traceable evidence records (metric/unit/asset/window/source/validity) |
| `learning.py` | Retrieves only valid measured outcomes; injected into chain/autopsy prompts |
| `memory.py` | Durable conversation context (`conversation_memory`, user+channel scoped, 24h TTL) |
| `test_api_speed.py` | Opt-in live benchmark: 30 sequential GETs vs one 30-item batch POST |
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

## Measured ingestion speed

`test_api_speed.py` (opt-in, live) grabs 30 real asset IDs and compares the legacy per-item
`GET /v2/assets/{id}/details` loop with one 30-item `POST /v1/catalog/items/details` batch.

| Run | Old way (30 GETs) | New way (1 POST) | Speedup | 429s |
|---|---|---|---|---|
| Paced 1.0 s/item (production-like) | 30.522 s | 0.376 s | **81.3×** | 0 / 0 |
| Aggressive 0.25 s/item | 9.721 s | 0.534 s | 18.2× | **10** / 0 |

The aggressive run is the honest failure mode: thirty rapid GETs were rate-limited ten times,
while the batch returned all 30 items with no 429. Numbers are a single small sample, not a
throughput guarantee.

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
python test_m6a_security.py               # M6-A authorization, secret redaction, AI cost, planner and dispatch guards
python test_phase2_pg_integration.py       # Phase 2 PostgreSQL integration; disposable DB only
python test_project_oracle.py           # ORACLE Phase 1 cohorts, append-only observations and velocity
python tests/test_oracle_worker.py        # ORACLE Phase 2 worker, coverage, retries, transactions and CLI
python test_vanta_conversation.py         # router/planner, rename/selection, memory, pending chain
python test_identity_and_windows.py      # alias resolver + dynamic DB window reconciliation
python test_recommendation_lifecycle.py  # application evidence, maturity, rec-10 marker
python test_shared_repairs.py            # visibility 429, backoff, batch client, chain fallback, prop gate
python test_jarvis_cases.py              # evidence semantics, learning filtering, diversity, memory
python test_astra.py                     # algorithmic-fit heuristic, platform guard, identity lock
python test_product_understanding.py     # blue hat/no motion, emote thumbnail rule, family sources
python test_phase2.py                    # research worker priority, circuit breaker, analyst report
python test_phase3.py                    # linking, outcome deltas, evaluation guard, frozen version
python test_auto_linker.py               # auto-link matching (Pose vs Pose V2), family gate
python test_rename_tracking.py           # old-item baselines, rename detection, launched_at anchors
python test_rename_watcher.py            # 15-minute watcher detection and autopsy persistence
python test_snapshot_batch.py            # snapshot batch fetch + bulk unnest history write
python test_algorithm_journey.py         # run → launch ledger → favorites answer
python test_integrity_upgrades.py        # pure checks; DB transaction test writes my_sales (skip in prod)
python api_performance_audit.py          # live speed benchmark + daily API footprint estimate
python test_api_speed.py                 # opt-in live benchmark (30 GETs vs 1 batch POST)
python test_live_roblox_sync.py          # read-only DB-vs-live marketplace sample (writes LIVE_MARKET_AUDIT.md)
python test_live_advantage.py            # gap/rank/velocity truth check (writes LIVE_ADVANTAGE_AUDIT.md)
python selftest.py                       # full audit (env, schema, freshness, engines, live items)
```

DB-backed tests skip automatically when `DATABASE_URL` is absent. The `test_live_*`,
`test_api_speed.py`, and `api_performance_audit.py` suites make external requests and are excluded
from the default audit run. `!selftest` runs the audit plus a command harness and issues a
certificate only when there are no hard failures and the effective score is ≥90.

---

## Setup

Requirements: Python 3.10+ (production runs 3.10.12; developed on 3.12), PostgreSQL, Discord bot
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
RUN_MIGRATIONS_ON_START=0   # 1 = run schema DDL once on boot; 0 (default) = skip DDL
```

Schema DDL is **not** run on every restart. Set `RUN_MIGRATIONS_ON_START=1` for the first boot
after a schema change, then return it to `0`; otherwise apply migrations manually. DDL runs used
to take `ACCESS EXCLUSIVE` locks on `items`/`launch_ledger` during startup and could deadlock
against reads.

Applied to production:

```
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_items_name_lower_trim
  ON items (lower(trim(name)));
```

That functional index supports the exact-title lookup in `item_resolver.resolve_name`
(previously a sequential scan that could hit the 20 s statement timeout).

Astra schema migrations (applied; re-runnable):

```
migrations/2026-11-02_astra_tables.sql     -- astra_runs
migrations/2026-11-02_astra_outcomes.sql   -- linked_item_id/linked_at + astra_outcomes
python apply_phase3_migration.py           -- one-shot outcome migration
python apply_missing_index.py              -- one-shot functional index
```

Tuning knobs include `ENRICH_BATCH_SIZE`, `SNAPSHOT_TOP_ITEMS`, `SNAPSHOT_MIN_FAVS`,
`SNAPSHOT_TIER_LIMIT`, `SNAPSHOT_BATCH_RATE`, `SNAPSHOT_BATCH_CONCURRENCY`,
`SCANNER_ID_WINDOW`, `FAVORITES_BACKFILL_LIMIT`, `RESEARCH_MAX_IDS`,
`RESEARCH_HIGH_LIMIT`, `RESEARCH_MEDIUM_LIMIT`, `RESEARCH_LOW_LIMIT`,
`RENAME_WATCH_DAYS`, `RENAME_WATCH_RATE`, `ASTRA_LEARNING_IN_GENERATION`,
`VISIBILITY_MAX_PAGES`, and `VISIBILITY_DELAY`.

---

## Recent updates (2026-11-02)

- **Product understanding (Astra v3):** `product_understanding.py` extracts family, colors,
  details, motion, constraints and unknowns with per-fact sources (user/API/visual/inferred/
  unknown). Emotes never infer motion from a static image; static accessories never carry motion.
- **Chain Analyst Report:** `!chain` now prints seven sections — Product Understanding, Market
  Evidence, 3–5 Positioning Angles, Recommended First Test, Description, Preview Brief, and
  Measurement Plan. The old metric-dump blocks are no longer sent.
- **Algorithmic fit:** the heuristic is frozen as `astra-fit-v1`, labelled “Algorithmic Fit
  Heuristic (not a prediction)”, and reports `result_count` separately from
  `retrieval_completeness` (5 returned / 5 checked = 5/5, not “5 of 30 pages”).
- **Launch & rename memory:** `!link` (any item age), `!rename`, and `!outcome` capture a baseline
  at link time (`launched_at = now()`) and report D7 favorites/units from that moment. Auto-link
  runs every 2 h; a rename watcher checks live titles every 15 minutes.
- **Research worker:** `market_research_worker.py` refreshes HIGH (launch ledger), MEDIUM (recent
  launches) and LOW (exploratory) items every 6 h in 30-item batches with a circuit breaker.
- **Snapshot batching:** `snapshot.py` now uses the 30-item client and a bulk `unnest` update for
  `items`/`item_history` instead of per-item GETs. Live benchmark: **73.7× faster** (30.946 s →
  0.420 s, 0 × 429); estimated background footprint **~0.2%** of a 100 req/min daily allowance
  (or ~1.21% before snapshot batching).
- **Evaluation guard:** live generation does not see past outcomes unless
  `ASTRA_LEARNING_IN_GENERATION=1`; outcome-based learning is an explicit path.
- **Database:** `astra_runs`, `astra_outcomes`, `linked_item_id`/`linked_at`, and the
  `idx_items_name_lower_trim` functional index are applied. The former `marketplace_links`/`!links`
  external-link tracking was removed entirely.
- **Tests:** added Astra/product/phase2/phase3/auto-link/rename/snapshot suites; the identity test
  now reconciles against live SQL instead of hardcoded historical totals.

---

## Recent updates (2026-11-01)

- **Interpretation boundary:** analytical outputs no longer present “DO THIS / KILL / SCALE” as directives.
  Chain ends with **ASSESSMENT & OPTIONS** (“nothing is applied automatically”); autopsy’s sales-present
  branch reads “WHAT THE EVIDENCE SUGGESTS … options, not instructions”. Internal labels remain for
  compatibility but authorize no action.
- **Evidence and learning:** `evidence.py` records metric/unit/asset/window/source/validity; `learning.py`
  retrieves only measured outcomes with maturity `mature`/`partial` and no `insufficient: true` marker, and
  injects them into chain/autopsy prompts. Production currently has **0 usable outcomes**, so the loop is
  wired and tested but not yet demonstrated on real sales.
- **Durable memory:** `conversation_memory` persists last item, candidates, pending offers and recent
  messages per user+channel (24h TTL) across restarts.
- **Creative diversity:** near-duplicate adjective stacks are filtered; original wording with no historical
  precedent is preserved.
- **Measured ingestion speed:** one 30-item batch POST is **81.3× faster** than 30 paced GETs
  (0.376 s vs 30.522 s, 0 × 429); with aggressive pacing the old path hit 10 × 429 while the batch hit 0.
- **DDL decoupled from startup:** `setup_database()` skips schema DDL unless `RUN_MIGRATIONS_ON_START=1`,
  removing the `ACCESS EXCLUSIVE` lock/deadlock window on restarts. A functional index migration for
  `items (lower(trim(name)))` is prepared under `migrations/` but **not applied**.
- **Sales identity:** `sales_name_aliases` with confirmed/candidate/ambiguous/unresolved states; the
  creator-confirmed rename “Cute Beanie w paws” → “Cute Kitty Fluffy Beanie” resolves to asset
  `130928797494687` (fixture: 139 records / 4,045 recorded R$). Reports show mapped vs unresolved coverage.
- **Windows and money:** one half-open UTC window definition (7 days = 7 dates, today partial), and
  `my_sales.amount_semantics` defaults to `unknown_recorded_amount`. Recorded amount is never called
  revenue or profit.
- **Dates:** `launch_ledger.published_at` (catalog creation) and `tracking_started_at` are separate;
  D1/D7/D30 anchor on `COALESCE(published_at, launched_at)`.
- **Batch ingestion:** `roblox_batch_client.py` fetches 30 assets per POST (token bucket 90/min, AIMD,
  full-jitter backoff honouring `Retry-After`, CSRF challenge handling); enricher uses it with bulk upsert.
- **Scheduling:** snapshot selection uses the tiered half-life CTE (`SNAPSHOT_TIER_LIMIT`, default 1500);
  scanner adds monotonic ID stepping (`SCANNER_ID_WINDOW`, default 600).
- **Experiments:** recommendation lifecycle fields, verified-vs-inferred application, maturity states,
  active-experiment protection, and `insufficient: true` DiD payloads never counted as effects.
- **Autopsy:** sales ground truth is injected into the AI prompt; sales > 0 or KEEP/DOUBLE_DOWN routes to
  SCALE PROTOCOL and cannot produce “zero sales”/“KILL”. Static props (sign/fence/board) cannot take
  wearable nouns (necklace/chain/backpack/tail/wing/hat) in chain or autopsy titles.
- **Chain:** conversational runs are DB-only with a 600s chat timeout; deterministic intent/title/description
  fallbacks keep it working when the AI provider is offline; hat type detection uses word boundaries
  (“that” no longer matches “hat”).
- **Reliability:** live marketplace calls back off with `Retry-After`; visibility failures now record an
  error; the title predictor’s stored in-sample R² is reported as `model_r2`, never as confidence.
- **Docs:** `COMMAND_REPAIR_MATRIX.md`, `LIVE_MARKET_AUDIT.md`, `LIVE_ADVANTAGE_AUDIT.md`, and the
  rollback notes in `MIGRATIONS.md`.

---

## Final stabilization backlog — release blockers, not future features

The following items were identified by the M5 review and/or source inspection. **They have not all been corrected or certified.** Severity and scope must be reconciled against the current runtime in the final A–Z audit.

| Area | Open verification / repair |
|---|---|
| Misleading prediction and ROI | `predictor.py` / `!predict` presents a weighted heuristic as a percentage probability; `bot_core._compute_roi()` estimates sales/revenue from unsupported favorites-per-sale ratios. Never interpret these as verified odds or earnings. |
| Marketplace HTTP budgets | Audit direct `requests` paths (including creator tracking) against the shared retry, circuit-breaker and budget policy. `creator_tracker.py` currently switches Roblox cookies after 429; replace that behavior with safe cooldown, not identity-based quota bypass. |
| Identity and ORACLE correctness | Resolve numeric User/Group creator-ID collisions, name-based cohort grouping, rate-limit recovery, timestamp consistency, and incomplete-scan coverage semantics. |
| Sales integrity | Reconcile item identity, source event IDs, and any deduplication capable of deleting distinct records. Sales-channel ingestion presently lacks verified sender/webhook allowlisting ([review](M6A1_SALES_SOURCE_REVIEW.md)); escalate priority where the channel admits untrusted senders. |
| Runtime command behavior | Rebuild coverage from all 90 registered commands, not the outdated 84-row matrix. Verify real callback dispatch, permissions, limits, side effects, errors, API failures, database integration and useful output. |
| M4 dormant integration | Check M3 experiment compatibility and test dormant functionality in isolation. Do not enable production `PHASE2_M4_ENABLED` under the final audit. |
| CI / startup / diagnostics | Resolve duplicate `offline-regression` names, workflow pinning and swallowed failures, scheduler startup/import side effects, and unnecessary DB metadata in CI logs. |
| Production proof | Verify `!version` against the merge SHA, service health, non-owner denial tests, live feature flags, sale-source trust and rollback readiness. The passing auto-deploy workflow alone is insufficient. |

**Evidence boundaries:** favorites are not units sold; search suggestions and sampled listings are not complete search demand or marketplace supply; a Roblox badge is not proof of strong creator sales; generated title scores are not measured CTR. The catalog may support useful comparative research, but neither causal attribution nor a high-CTR guarantee follows automatically.

### Final release gate

1. Freeze new features and create an isolated audit branch.
2. Enumerate all registered commands and aliases at runtime; test every callback with realistic mocked services and disposable PostgreSQL, including negative, authorization and fault-injection paths.
3. Resolve all release-blocking findings, retain regression evidence, and run both required CI checks on a protected PR.
4. Merge/deploy **only after explicit human approval**; verify production health, permissions, the deployed SHA and disabled M4 separately.
5. Publish a final command matrix, audit findings, test results, intelligence-quality limitations and a **GO/NO-GO** verdict. A tool self-test score or green deploy is not by itself a certification.

**Then transition to maintenance mode:** monitor incidents, fix regressions and patch security issues; defer new marketplace-learning work until independently justified by sufficient owned-item outcomes.

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
- The batch details endpoint returns name, description, price, favorites, creator, and type only —
  it does **not** refresh `created_at` or `total_sales` (existing values are preserved, not zeroed).
- Live checks sample up to 300 results, not the full catalog. HTTP 429/400 responses are reported as
  blocked, never as zero competition.
- The title predictor's stored metric is in-sample R² (no holdout); it is not a probability and does
  not rank `!chain`.
- Descriptions are creative prose; only claims/numbers/internal language are filtered.
- Description "tags" are not a ranking field — Roblox removed avatar item tags in December 2025,
  so keyword ideas must live in the title and description. Keywords must still share a token
  with the item name or category type words.
- The bot cannot create demand or guarantee sales.
- No usable mature recommendation outcomes exist yet; `learning.py` is wired and tested but has
  nothing real to retrieve, so “learning from sales” is not yet demonstrated.
- `idx_items_name_lower_trim` is applied; exact-title lookups use the functional index.
- Auto-linking requires a ≥80% title similarity and a matching family; renamed items are matched
  through applied rename advice, so mismatched or highly edited titles still need manual `!link`.
- `astra_runs`/`astra_outcomes` start empty; outcomes appear only after a run is linked (manually or
  by the 2-hour auto-linker / 15-minute rename watcher). No real D7/D30 journey has been demonstrated yet.
- The batched snapshot path is unit-tested but has not yet been exercised by a full production
  snapshot run.
- Schema DDL must not run on every boot: `RUN_MIGRATIONS_ON_START` stays `0` except for a one-shot
  migration boot. Forgetting to run migrations leaves new tables/columns absent.
- Conversational public threads are visible to channel members; use **Private (DM)** for
  sensitive details. Thread ownership is HMAC-verified; the visible user ID alone is not trusted.
- Conversation context persists in `conversation_memory` (user+channel scoped, 24h TTL) across
  restarts; it stores router context, not full transcripts.
- The AI planner uses allow-listed actions, a ~400-token output bound, a 30s timeout,
  deterministic routing first, and user-scoped 20/hour (owner 100/hour) plus global
  200/hour process-local limits; see the M6-A security section. The command-authorization
  gate still applies to planner-dispatched actions.
- Provider-reported token usage is logged per AI call; otherwise an explicit input estimate is
  logged.
