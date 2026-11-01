# VANTA 73 — Command Coverage Matrix

Generated from the offline runtime registry. Status is evidence-based:
**registered** = reachable via the bot registry; **automated** = covered by a unit/DB suite;
**manual** = exercised only by hand or scheduled runs; **not exercised** = registered, no test.

| Command | Aliases | Implementation | Automated evidence | Status |
|---|---|---|---|---|
| `ai_debug` | — | commands_ai:1656 | — | not exercised |
| `ai_status` | — | commands_ai:703 | — | not exercised |
| `analyze` | — | commands_market:189 | — | not exercised |
| `analyze_image` | — | commands_ai:1380 | test_vanta_conversation.py | automated |
| `applied` | apply_rec | commands_experiments:6 | test_recommendation_lifecycle.py | automated |
| `autopsy` | — | commands_intel:413 | test_identity_and_windows.py, test_recommendation_lifecycle.py | automated |
| `bot_update` | update_bot, selfupdate | commands_supercomputer:2073 | — | manual |
| `brainstorm` | — | commands_ai:724 | — | not exercised |
| `chain` | — | commands_advanced:497 | test_shared_repairs.py, test_jarvis_cases.py | automated |
| `classic` | — | commands_market:304 | — | not exercised |
| `converge` | — | commands_advanced:268 | — | not exercised |
| `converge_debug` | — | commands_advanced:334 | — | not exercised |
| `cookie_check` | — | commands_sales:414 | — | not exercised |
| `creative` | — | commands_advanced:141 | — | not exercised |
| `creative_raw` | — | commands_advanced:203 | — | not exercised |
| `creator_brain` | meta, cohort | commands_intel:1875 | — | not exercised |
| `data_audit` | integrity | commands_market:477 | — | not exercised |
| `dbtest` | — | commands_market:101 | — | not exercised |
| `desc_analyze` | — | commands_market:231 | — | not exercised |
| `desc_forge` | — | commands_advanced:445 | test_shared_repairs.py | automated |
| `early` | — | commands_xray:63 | — | not exercised |
| `emote` | — | commands_market:289 | — | not exercised |
| `emote_status` | — | commands_market:20 | — | not exercised |
| `enrich_run` | run_enricher | commands_supercomputer:1049 | — | manual |
| `experiments` | labs, results | commands_experiments:60 | test_recommendation_lifecycle.py | automated |
| `failures` | — | commands_xray:118 | — | not exercised |
| `gap` | — | commands_market:319 | — | not exercised |
| `golden_hour` | golden | commands_supercomputer:442 | — | not exercised |
| `group_metrics` | gmetrics | commands_sales:270 | — | not exercised |
| `guide` | — | commands_guide:52 | — | not exercised |
| `history` | — | commands_market:79 | — | not exercised |
| `hitrate` | hit_rate | commands_supercomputer:1241 | — | not exercised |
| `ignored` | skip_rec | commands_experiments:35 | test_recommendation_lifecycle.py | automated |
| `launch` | log_launch | commands_supercomputer:1112 | — | not exercised |
| `launch_sync` | sync_launches | commands_supercomputer:1452 | — | not exercised |
| `ledger_sync` | sync_ledger | commands_supercomputer:1222 | — | not exercised |
| `logs` | log | commands_supercomputer:1425 | — | not exercised |
| `meta_sniper` | sniper | commands_supercomputer:490 | — | not exercised |
| `momentum` | — | commands_intel:130 | — | not exercised |
| `momentum_debug` | — | commands_intel:84 | — | not exercised |
| `nextwave` | — | commands_intel:206 | — | not exercised |
| `opportunities` | — | commands_intel:226 | — | not exercised |
| `opportunity` | — | commands_market:274 | — | not exercised |
| `oracle` | — | commands_intel:181 | — | not exercised |
| `path` | roadmap | commands_supercomputer:1518 | — | not exercised |
| `patterns` | — | commands_xray:90 | — | not exercised |
| `playbook` | tactics | commands_supercomputer:1487 | — | not exercised |
| `predict` | — | commands_intel:154 | — | not exercised |
| `rescue` | — | commands_ai:1165 | — | not exercised |
| `revive` | revive_item | commands_intel:1513 | test_recommendation_lifecycle.py | automated |
| `revsim` | simulator | commands_supercomputer:343 | — | not exercised |
| `rising_gaps` | — | commands_advanced:39 | — | not exercised |
| `sales_backfill` | — | commands_sales:113 | — | not exercised |
| `sales_debug` | — | commands_sales:495 | — | not exercised |
| `sales_for` | — | commands_sales:85 | test_identity_and_windows.py | automated |
| `sales_keywords` | sales_words | commands_supercomputer:759 | — | not exercised |
| `sales_post_now` | — | commands_sales:148 | — | not exercised |
| `sales_probe` | — | commands_sales:174 | — | not exercised |
| `sales_report` | — | commands_sales:13 | test_identity_and_windows.py | automated |
| `sales_scan` | — | commands_sales:555 | — | not exercised |
| `scan_run` | run_scanner | commands_supercomputer:1028 | — | manual |
| `scan_status` | — | commands_market:153 | — | not exercised |
| `selftest` | certify | commands_supercomputer:1806 | — | not exercised |
| `selftest_db` | healthcheck_db | commands_supercomputer:1623 | — | not exercised |
| `snapshot_now` | — | commands_advanced:107 | — | manual |
| `start` | — | menu:804 | test_vanta_conversation.py | automated |
| `stealth` | stealth_desc | commands_supercomputer:292 | — | not exercised |
| `suggest_probe` | probe_suggest | commands_supercomputer:902 | — | not exercised |
| `suggest_run` | scrape_suggest | commands_supercomputer:997 | — | not exercised |
| `tags` | — | commands_advanced:563 | test_shared_repairs.py | automated |
| `track` | — | commands_market:458 | — | not exercised |
| `train` | retrain | commands_supercomputer:1077 | — | manual |
| `trends` | — | commands_market:169 | — | not exercised |
| `vacuum` | snipe | commands_supercomputer:132 | — | not exercised |
| `velocity` | — | commands_market:404 | — | not exercised |
| `verdict` | — | commands_intel:252 | test_identity_and_windows.py | automated |
| `verified_scan` | scan_verified | commands_intel:1919 | — | not exercised |
| `version` | ver, about | commands_supercomputer:2019 | — | not exercised |
| `visibility` | — | commands_visibility:6 | — | not exercised |
| `visibility_run` | — | commands_visibility:44 | — | not exercised |
| `visibility_seed` | — | commands_visibility:23 | — | not exercised |
| `watchlist` | — | commands_market:59 | — | not exercised |
| `whales` | whale | commands_supercomputer:58 | — | not exercised |
| `xray` | — | commands_xray:37 | — | not exercised |

## Notes
- Every command is registered through the real `register_*` wiring; aliases share the same callback.
- Automated coverage is command-family level (router, identity/windows, lifecycle, shared repairs),
  not per-command live execution. Mutating commands are intentionally not run against production.
- Conversational routes are covered by `test_vanta_conversation.py` (routing, memory round-trip,
  filler-only concepts, rename/selection, pending chain).