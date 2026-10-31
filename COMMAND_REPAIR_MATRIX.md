# COMMAND REPAIR MATRIX — VANTA 73

Generated from the offline runtime registry at commit `5929a50` (deployed, verified).
Canonical commands: **84**.

Columns: command → aliases → implementation (module:line) → side effects → checks → defects → fix → verification.

Verification key: **S** static/registration · **U** unit/mocked · **I** integration · **L** authorized live.

## Core & creative

| command | aliases | impl | side effects | checks | defects | fix | verification |
|---|---|---|---|---|---|---|---|
| `analyze_image` | — | commands_ai:1380 | read-only | none | none identified | — | S |
| `autopsy` | — | commands_intel:413 | read-only | none | creates recommendation with hypothesis/proposed_change/success_condition (5929a50). | — | S·L |
| `brainstorm` | — | commands_ai:724 | read-only | none | none identified | — | S |
| `chain` | — | commands_advanced:497 | read-only | none | live_enrich disabled in conversation; timeout 600s (7b97dd0); live-verified 66s DB-only run. | — | S·L |
| `converge` | — | commands_advanced:268 | read-only | none | none identified | — | S |
| `converge_debug` | — | commands_advanced:334 | read-only | none | none identified | — | S |
| `creative` | — | commands_advanced:141 | read-only | none | none identified | — | S |
| `creative_raw` | — | commands_advanced:203 | read-only | none | none identified | — | S |
| `desc_forge` | — | commands_advanced:445 | read-only | none | keyword fallback + head-noun filter (34f9ff1..28f074d); live-verified. | — | S·L |
| `guide` | — | commands_guide:52 | read-only | none | none identified | — | S |
| `path` | roadmap | commands_supercomputer:1518 | read-only | none | none identified | — | S |
| `playbook` | tactics | commands_supercomputer:1487 | read-only | none | none identified | — | S |
| `rescue` | — | commands_ai:1165 | read-only | none | none identified | — | S |
| `revive` | revive_item | commands_intel:1513 | read-only | none | same; resolver + lifecycle metadata wired (5929a50). | — | S·L |
| `start` | — | menu:804 | read-only | none | none identified | — | S |
| `tags` | — | commands_advanced:563 | read-only | none | conversation reroutes to desc_forge; classic still keyword mining; cross-family filter (1972fa7). | — | S |
| `verdict` | — | commands_intel:252 | read-only | none | uses item_sales_summary -> resolver (91bbcea); verified static. | — | S |

## Research & market

| command | aliases | impl | side effects | checks | defects | fix | verification |
|---|---|---|---|---|---|---|---|
| `analyze` | — | commands_market:189 | read-only | none | none identified | — | S |
| `classic` | — | commands_market:304 | read-only | none | none identified | — | S |
| `desc_analyze` | — | commands_market:231 | read-only | none | none identified | — | S |
| `early` | — | commands_xray:63 | read-only | none | none identified | — | S |
| `emote` | — | commands_market:289 | read-only | none | none identified | — | S |
| `emote_status` | — | commands_market:20 | read-only | none | none identified | — | S |
| `failures` | — | commands_xray:118 | read-only | none | none identified | — | S |
| `gap` | — | commands_market:319 | read-only | none | none identified | — | S |
| `history` | — | commands_market:79 | read-only | none | none identified | — | S |
| `momentum` | — | commands_intel:130 | read-only | none | none identified | — | S |
| `momentum_debug` | — | commands_intel:84 | read-only | none | none identified | — | S |
| `nextwave` | — | commands_intel:206 | read-only | none | none identified | — | S |
| `opportunities` | — | commands_intel:226 | read-only | none | none identified | — | S |
| `opportunity` | — | commands_market:274 | read-only | none | none identified | — | S |
| `oracle` | — | commands_intel:181 | read-only | none | none identified | — | S |
| `patterns` | — | commands_xray:90 | read-only | none | none identified | — | S |
| `predict` | — | commands_intel:154 | read-only | none | none identified | — | S |
| `rising_gaps` | — | commands_advanced:39 | read-only | none | none identified | — | S |
| `scan_status` | — | commands_market:153 | read-only | none | none identified | — | S |
| `track` | — | commands_market:458 | read-only | none | none identified | — | S |
| `trends` | — | commands_market:169 | read-only | none | none identified | — | S |
| `velocity` | — | commands_market:404 | read-only | none | none identified | — | S |
| `watchlist` | — | commands_market:59 | read-only | none | none identified | — | S |
| `xray` | — | commands_xray:37 | read-only | none | none identified | — | S |

## Sales

| command | aliases | impl | side effects | checks | defects | fix | verification |
|---|---|---|---|---|---|---|---|
| `cookie_check` | — | commands_sales:414 | read-only | none | none identified | — | S |
| `meta_sniper` | sniper | commands_supercomputer:490 | read-only | none | none identified | — | S |
| `revsim` | simulator | commands_supercomputer:343 | read-only | none | explicitly uncalibrated prior — correct behavior, no fabrication. | — | S |
| `sales_backfill` | — | commands_sales:113 | writes my_sales | in-callback owner guard | none identified | — | S |
| `sales_debug` | — | commands_sales:495 | read-only | none | none identified | — | S |
| `sales_for` | — | commands_sales:85 | read-only | none | resolver + canonical name + identity status (91bbcea). | — | S·L |
| `sales_keywords` | sales_words | commands_supercomputer:759 | read-only | none | none identified | — | S |
| `sales_post_now` | — | commands_sales:148 | backfill + posts | in-callback owner guard | none identified | — | S |
| `sales_probe` | — | commands_sales:174 | read-only | none | none identified | — | S |
| `sales_report` | — | commands_sales:13 | read-only | none | resolver + windows + coverage + amount semantics (91bbcea); verified production. | — | S·L |
| `sales_scan` | — | commands_sales:555 | read-only | none | none identified | — | S |
| `stealth` | stealth_desc | commands_supercomputer:292 | read-only | none | none identified | — | S |

## Tracking & experiments

| command | aliases | impl | side effects | checks | defects | fix | verification |
|---|---|---|---|---|---|---|---|
| `applied` | apply_rec | commands_experiments:6 | writes ledger | in-callback owner guard | records creator_reported evidence (8178496). | — | S·L |
| `data_audit` | integrity | commands_market:477 | read-only | none | none identified | — | S |
| `experiments` | labs, results | commands_experiments:60 | writes ledger/measurement | in-callback owner guard | auto_apply verifies fields; maturity; rec-10 insufficient marker honored (8178496). | — | S·L |
| `ignored` | skip_rec | commands_experiments:35 | writes ledger | in-callback owner guard | none identified | — | S |
| `launch` | log_launch | commands_supercomputer:1112 | writes launch_ledger | in-callback owner guard | none identified | — | S |
| `launch_sync` | sync_launches | commands_supercomputer:1452 | writes ledger | in-callback owner guard | none identified | — | S |
| `ledger_sync` | sync_ledger | commands_supercomputer:1222 | writes ledger | in-callback owner guard | none identified | — | S |
| `visibility` | — | commands_visibility:6 | read-only | none | 56/71 runs failed, no error strings — confirmed defect, not yet fixed. | — | S |
| `visibility_run` | — | commands_visibility:44 | network + writes DB | in-callback owner guard | none identified | — | S |
| `visibility_seed` | — | commands_visibility:23 | writes DB | in-callback owner guard | none identified | — | S |

## Operations

| command | aliases | impl | side effects | checks | defects | fix | verification |
|---|---|---|---|---|---|---|---|
| `ai_debug` | — | commands_ai:1656 | read-only | none | none identified | — | S |
| `ai_status` | — | commands_ai:703 | read-only | none | none identified | — | S |
| `bot_update` | update_bot, selfupdate | commands_supercomputer:2073 | git sync + restart | in-callback owner guard | none identified | — | S |
| `dbtest` | — | commands_market:101 | read-only | none | none identified | — | S |
| `enrich_run` | run_enricher | commands_supercomputer:1049 | writes DB (items) | in-callback owner guard | none identified | — | S |
| `snapshot_now` | — | commands_advanced:107 | writes DB (history) | in-callback owner guard | none identified | — | S |

## Other

| command | aliases | impl | side effects | checks | defects | fix | verification |
|---|---|---|---|---|---|---|---|
| `about` | ver, about | commands_supercomputer:2019 | read-only | none | none identified | — | S |
| `certify` | certify | commands_supercomputer:1806 | read-only | none | none identified | — | S |
| `cohort` | meta, cohort | commands_intel:1875 | read-only | none | none identified | — | S |
| `gmetrics` | gmetrics | commands_sales:270 | read-only | none | none identified | — | S |
| `golden` | golden | commands_supercomputer:442 | read-only | none | none identified | — | S |
| `healthcheck_db` | healthcheck_db | commands_supercomputer:1623 | read-only | none | none identified | — | S |
| `hit_rate` | hit_rate | commands_supercomputer:1241 | read-only | none | none identified | — | S |
| `log` | log | commands_supercomputer:1425 | read-only | none | none identified | — | S |
| `probe_suggest` | probe_suggest | commands_supercomputer:902 | read-only | none | none identified | — | S |
| `retrain` | retrain | commands_supercomputer:1077 | read-only | none | none identified | — | S |
| `run_scanner` | run_scanner | commands_supercomputer:1028 | read-only | none | none identified | — | S |
| `scan_verified` | scan_verified | commands_intel:1919 | read-only | none | none identified | — | S |
| `scrape_suggest` | scrape_suggest | commands_supercomputer:997 | read-only | none | none identified | — | S |
| `snipe` | snipe | commands_supercomputer:132 | read-only | none | none identified | — | S |
| `whale` | whale | commands_supercomputer:58 | read-only | none | none identified | — | S |
