# F-05 Remediation Evidence — Unified Roblox API Safety

- Baseline: `df325a3d0b584b7933dd55ca035380b8d0369531`
- Branch: `fix/f05-unified-roblox-api-safety`
- Scope: active Roblox HTTP paths only; no feature work, no schema changes.

## Request inventory (before → after)

| Path | Method / destination | Caller | State | Before | After |
|---|---|---|---|---|---|
| `live_market._get_with_backoff` | GET catalog search | `!creative`, `!desc_forge`, `!intel`, convergence | Active | Direct `requests.get`, local 3-attempt loop, no shared circuit | `safe_roblox.get("catalog_search")`; shared pacing, circuit, Retry-After |
| `convergence_live.verify_niche` | GET catalog search | `!converge` | Active | Local scheduler + private circuit | Shared transport + shared circuit checks/trip |
| `scanner.try_api` | GET catalog search | scan scheduler, `!scan` | Active | 3×cookie workers, round-robin cookies, rotate on 429, local retry | Single primary session, 3 workers, shared GET/circuit, partial results |
| `creator_tracker._get_json` | GET catalog search | creator tracker, ORACLE | Active | 3 local retries, numeric Retry-After, cookie rotation | Shared GET; one 429 → `RateLimited`; no rotation |
| `creator_tracker.verify_creator_badge` | GET users/groups | creator verification | Active | Direct `session.get` | `safe_roblox.get("users"/"groups")` |
| `search_visibility._fetch_query` | GET catalog search | visibility scheduler, `!visibility` | Active | Direct `session.get`, 3 local retries | `safe_roblox.get`; explicit `completed/partial/rate_limited/deferred/timed_out/unavailable` |
| `live_enrich._search_keyword` | GET catalog search | smart pipeline | Active | Page-by-page session rotation, local circuit, sleeps | Primary session, shared GET/circuit, no rotation |
| `live_enrich._fetch_item_details` | GET economy details + catalog favorites | smart pipeline | Active | Tried every session, 429 sleeps, favorites defaulted to 0 | Primary session, shared GET, no rotation, missing favorites stay `None` |
| `snapshot.fetch_fresh_favs` | GET catalog favorites | snapshot helper | Dormant | Multi-session loop, 429 sleeps | Primary + anonymous only after 401/403; shared GET; no rate-limit rotation |
| `enricher.fetch_worker` / `fetch_favorites` / `get_csrf_token` | GET/POST legacy enrichment | legacy helpers | Dormant | Local retries, 429 sleeps | Shared GET/POST; 429 defers; CSRF session preserved |
| `roblox_batch_client._post` | POST catalog details | enricher, snapshot, ORACLE | Active | 5 attempts incl. 429 sleeps; numeric Retry-After only | Shared circuit before each attempt; 429 trips and defers immediately; HTTP-date parsing; 3 attempts; CSRF preserved |
| `backfill_dates.fetch_created_date` | GET economy details | scheduled backfill script | Active | Direct `session.get`, 0.35s loop, no circuit | `safe_roblox.get("catalog_details")`; shared circuit stops loop |
| `recovery_brain.*` | GET economy/catalog | autopsy/recovery commands | Active | Already used `safe_roblox` | Inherits upgraded shared transport and global 429 trip |
| `commands_sales` probes | GET/POST sales endpoints | sales commands | Active | Already used `safe_roblox` | Inherits shared circuit/POST budget; CSRF headers preserved |
| `scheduler._notify_alert` | POST Discord webhook | scheduler alerts | Active | Direct `requests.post` | Out of scope: non-Roblox provider |
| Test-only HTTP helpers | GET economy/catalog | test scripts | Test-only | Local test sessions | Out of scope; never contact production in offline suite |

## Shared protection contract

- `safe_roblox` owns the shared scheduler, endpoint budgets, 429 handling,
  HTTP-date/numeric `Retry-After`, and the global circuit.
- A 429 on any shared catalog endpoint opens the global circuit; all callers
  that consult `shared_circuit_open()` defer without a request.
- No active path rotates accounts, cookies, proxies or sessions to bypass a
  rate limit. Only one primary session is used per worker module.
- Missing data is returned as `None`/explicit state, never as zero or complete
  coverage.
- CSRF headers and authenticated session cookies are preserved; error strings
  contain only exception types/status codes, never cookie or token values.

## Tests

- `test_f05_api_safety.py`: 16 tests covering 200, 400/403, numeric and
  HTTP-date 429, 500/503, timeout, invalid JSON, circuit open/recovery,
  deferred requests, shared concurrency, retry exhaustion, auth-session
  preservation, CSRF, secret redaction, partial results, budget compatibility,
  and no-rotation behavior.
- Existing offline suite: 33/33 scripts pass.
- Command contracts: 90/90 pass.
- New safety test wired into `.github/workflows/survival-tests.yml`.
- PostgreSQL integration runs in `.github/workflows/phase2-postgres.yml` on
  this branch.

## Unresolved limitations

- Dormant legacy helpers in `enricher.py` and `snapshot.fetch_fresh_favs` are
  migrated for safety but are not exercised by the active enrichment/snapshot
  paths; those active paths use the batch client.
- Discord webhook alerts remain direct non-Roblox requests by design.
- No production smoke or live scraping was performed.

## Verdict

`F-05 CLOSED — VERIFIED` for the audited active Roblox paths.

Overall VANTA 73 certification remains **NO-GO** pending the other independent
audit findings and production smoke/review requirements.
