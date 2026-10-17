# Roblox UGC Advanced Analytics Bot

A full-catalog intelligence system for Roblox UGC creators. Scans 65k+ items,
mines statistical signals from titles + descriptions, tracks live sales via
Discord webhooks, and generates launch-ready names, tags, descriptions, and
verdicts — all from Discord commands.

Every recommendation traces to real data. Zero AI hallucination in outputs.

---

## ⚡ The 3-command workflow
!converge emotes → find open niches
!chain <concept> → full plan + statistical champion title
!verdict <item_id> → is it working? (KEEP / RENAME / KILL)

That's the entire daily loop. Everything else is a specialization.

---

## 🎯 All Commands

### Core workflow

| Command | Purpose |
|---|---|
| `!start` | Interactive workflow menu with 8 buttons |
| `!chain <concept>` | **Full pipeline** — niche → market → competitors → descriptions → 10 titles → statistical ranking → FINAL action block |
| `!chain variant <id> <theme>` | Variant of a proven winner (keeps winner keywords, adds theme) |
| `!converge <family>` | Rank open niches by 5-signal opportunity score |
| `!converge all_families` | Scan every category at once |
| `!verdict <id>` | Multi-signal decision (age · favs · velocity · percentile) |
| `!titles <concept>` | Standalone statistical title engine (top 10 ranked) |
| `!tags <name>` | 45 sales-weighted SEO tags mined from real top sellers |
| `!desc <name>` | Data-driven description: 3-line body + tag block + full audit |

### Intelligence & analysis

| Command | Purpose |
|---|---|
| `!brainstorm <concept>` | Deep-dive analysis with 10 titles + market diagnosis + cultural context |
| `!autopsy <item_id>` | Full failure analysis when verdict says RENAME |
| `!xray` | Full market dashboard |
| `!patterns <family>` | Statistical lift mining (words / bigrams / prices) |
| `!failures <family>` | Words correlated with flops |
| `!early <days>` | Early winner detection (favs/day + low supply filter) |
| `!rising_gaps` | Emerging keywords + category gaps |
| `!momentum <days>` | Trend velocity across keywords |
| `!predict <keyword>` | 6-factor success probability |
| `!oracle <keyword>` | Trend forecast + next-wave detection |
| `!nextwave` | Early trends before they peak |
| `!opportunities` | Daily ranked feed of best plays |

### Market data

| Command | Purpose |
|---|---|
| `!scan_status` | Discovered IDs, analyzed items, description coverage |
| `!trends` | Top words across titles + descriptions |
| `!analyze <keyword>` | Deep keyword analysis (titles + descriptions) |
| `!desc_analyze <keyword>` | Keyword goldmines hidden in descriptions only |
| `!market_scan <category> <sort>` | Live Roblox catalog scan (favorited / sales / updated) |
| `!comp <phrase>` | Deep competition check |
| `!opportunity <keyword>` | Market data for a single keyword |
| `!dbtest` | Database connection status |
| `!db_size` | Current DB size + top tables |

### Sales tracking (live webhooks)

| Command | Purpose |
|---|---|
| `!sales_report [days]` | Revenue summary: top items, daily trend |
| `!sales_for <item>` | Sales for a specific item (fuzzy match) |
| `!sales_backfill [limit]` | Import historical sales from Discord channel |
| `!sales_post_now` | Trigger today's summary right now |

### AI & utility

| Command | Purpose |
|---|---|
| `!analyze_image` (attach) | Vision → keywords → titles |
| `!rescue <situation>` | Failing item rescue plan |
| `!ai_status` | Gemini + OpenRouter status |
| `!ai_debug` | Test both AI provider calls |
| `!guide` | Built-in help |
| `!snapshot_now` | Force snapshot from Render IP |
| `!momentum_debug` | Momentum system diagnostics |

---

## 🏗️ Architecture

### Command modules

| File | Purpose |
|---|---|
| `discord_ugc_bot.py` | Orchestrator — watchdog, Flask health, boot backoff |
| `menu.py` | Interactive `!start` UI with 8 buttons |
| `commands_ai.py` | `!brainstorm`, `!rescue`, `!analyze_image` |
| `commands_intel.py` | `!autopsy`, `!verdict`, `!momentum`, `!predict`, `!oracle`, `!nextwave` |
| `commands_advanced.py` | `!converge`, `!chain`, `!tags`, `!desc`, `!rising_gaps`, `!snapshot_now` |
| `commands_sales.py` | `!sales_report`, `!sales_for`, `!sales_backfill`, `!sales_post_now` |
| `commands_xray.py` | `!xray`, `!patterns`, `!failures`, `!early` |
| `commands_market.py` | `!trends`, `!analyze`, `!desc_analyze`, `!opportunity` |
| `commands_guide.py` | `!guide` help |

### Intelligence layer

| File | Purpose |
|---|---|
| `intel_common.py` | Shared classifier · percentile · portfolio · verdict logic |
| `convergence_engine.py` | Category-aware niche scoring (5 signals) |
| `chain.py` | Full pipeline orchestrator |
| `title_scorer.py` | **Statistical title scoring** — word-lift × search-demand × visibility-gap × freshness × uniqueness |
| `tag_generator.py` | Sales-weighted tag miner from real top sellers |
| `description_engine.py` | Data-driven description builder with audit |
| `market_velocity.py` | Velocity · trajectory · concentration |
| `pattern_forge.py` | Statistical lift mining |
| `early_winners.py` | Early winner detection |
| `winner_analysis.py` | Top 10% vs bottom 50% patterns |
| `smart_pipeline.py` | Parallel comp scan (6 workers, single-writer enrich) |
| `gemini_brain.py` | All AI prompts + hard promo filter |
| `algo_brain.py` | Roblox algorithm context for prompts |
| `category_configs.py` | Category families + vocab + shape rules |
| `bot_core.py` | DB access + shared helpers |
| `bot_ui.py` | Paginators + navigation views |

### Data pipeline

| File | Runs from | Schedule |
|---|---|---|
| `scanner.py` | GH Actions | 02:00 UTC daily |
| `enricher.py` | GH Actions | Every 6h |
| `snapshot.py` | Render scheduler | 03:30 UTC daily |
| `suggest.py` | GH Actions | Every 6h |
| `discover_keywords.py` | GH Actions | 05:30 UTC daily |
| `backfill_dates.py` | GH Actions | 06:30 UTC daily |
| `scheduler.py` | Render | Snapshot · ML train · daily report |
| `sales_listener.py` | Render (on_message) | Live — parses Roblox sale embeds |
| `post_monitor.py` | Render (scheduler) | Daily report at 22:00 GMT+4 |
| `live_enrich.py` | Called by smart_pipeline | On-demand Roblox API |
| `desc_forge.py` | Called by chain/synth | Description mining |
| `recovery_brain.py` | Called by autopsy | Failure mode detection |
| `predictor.py` | Called by `!predict` | 6-factor success scoring |
| `opportunity_feed.py` | Called by `!opportunities` | Daily feed builder |
| `momentum.py` | Called by `!momentum` | Trend velocity |
| `oracle.py` | Called by `!oracle` | Trend forecasting |
| `rising_gaps.py` | Called by `!rising_gaps` | Emerging keyword detection |
| `winner_analysis.py` | Called by chain/brainstorm | Winner blueprint |
| `competition_check.py` | Called by autopsy | Deep phrase comp |

---

## 📊 How the title scorer works

Every title is scored on 6 real signals — no AI guessing:

1. **Word lift** — median favs of items containing word ÷ category median
   (clamped to [0.1, 5.0] to prevent explosions)
2. **Search demand** — how many real search queries contain the word
3. **Bigram lift** — median favs of items matching two words together
4. **Freshness** — trending up/down over last 90 days
5. **Visibility gap** — search demand ÷ supply (finds open spots)
6. **Uniqueness** — 0 exact title matches = 1.5× bonus

**Output:** champion + backup + wildcard, each with full word-by-word audit.

Every number traces to `items` and `search_suggestions`. Zero hallucination.

---

## 🗄️ Database schema (Supabase Postgres)

| Table | Purpose |
|---|---|
| `items` | ~65k UGC items (id, name, description, favorite_count, price, asset_type_id, created_at) |
| `item_history` | Snapshot history for velocity calculations |
| `discovered_items` | ID cache from Roblox scanner |
| `search_suggestions` | ~33.6k real Roblox search queries |
| `learned_keywords` | Vetted keywords with scores |
| `my_sales` | **Live sales** — populated by `sales_listener.py` from Discord webhooks |
| `my_portfolio` | Your 10 items |
| `predictor_weights` | ML model weights |
| `competitor_tracking`, `item_tracker`, `watchlist` | Tracking |
| `user_profiles`, `saved_consultations` | Consultation history |

**Free tier limit:** 500 MB. Currently ~60 MB (12%).

### Cleanup if approaching 400 MB

```sql
delete from item_history where snapshot_at < now() - interval '30 days';
vacuum full item_history;

delete from discovered_items
where id not in (select id from items)
  and id not in (select id from item_history);
vacuum full discovered_items;
