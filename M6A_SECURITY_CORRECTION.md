# VANTA 73 — M6-A Security Correction

- **Baseline:** `4399eaeea4195b550b8f5f2c77086fb9104ce6c3`
- **Branch:** `fix/m6a-security-authorization`
- **Implementation commit:** `0e19be91da10b7fed859ef9a8ba32acb98419bcd`
- **Scope:** F-01 command authorization, F-02 secret protection, and F-14 AI-cost authorization risks.
- **Out of scope and unchanged:** ORACLE algorithms, autonomous learning, sales attribution, `!emote_title`, M4 activation, database schemas, environment variables, Roblox API budgets.
- **Production state:** unchanged. No merge or deploy.

## M6-A.1 follow-up (included in this branch)

- Conversation-planner AI is now bounded by process-global per-user and
  global limits before `_planner_ai()` is invoked:
  - non-owner: 20 attempts/hour
  - owner: 100 attempts/hour
  - global: 200 attempts/hour
  - window: 3600 seconds
- Attempts are counted before the provider call, including provider failures,
  timeouts, and invalid responses. The deterministic fast path still returns
  without any AI call.
- The limiter is keyed by Discord user, not conversation state, so new threads
  or sessions cannot reset a user's allowance.
- Actual `before_invoke` and conversation-router integration tests were added,
  not just helper-level tests.
- Sales embed source authentication is missing. The finding and a proposed
  allowlist/dry-run design are documented in
  `M6A1_SALES_SOURCE_REVIEW.md`; production ingestion was **not** changed.

## 1. Exact files modified

**New**
- `command_security.py`
- `test_m6a_security.py`
- `M6A_SECURITY_CORRECTION.md`
- `M6A1_SALES_SOURCE_REVIEW.md`

**Modified**
- `commands_ai.py`
- `discord_ugc_bot.py`
- `vanta_conversation.py`
- `.github/workflows/survival-tests.yml`
- `.github/workflows/phase2-postgres.yml`

## 2. Central authorization

`command_security.py` defines an explicit policy for all **90** registered commands:

- **52 owner-only** commands: mutating, administrative, sensitive diagnostics, live-API diagnostics, and costly AI paths.
- **38 public read-only** commands: safe lookups, status, history, title utilities, and read-only sales summaries.
- **19 AI-cost** commands: all owner-authorized and additionally rate-limited.
- Unknown commands fail closed as owner-only.
- Aliases are canonicalized before policy lookup, so aliases cannot bypass restrictions.
- The policy marks each command's side effects: mutating, AI cost, external API, and sensitive.

Authorization is enforced in two paths:

1. `discord_ugc_bot.py` global `before_invoke` guard for normal `!command` execution.
2. `vanta_conversation._run_registry()` guard before direct callback invocation.

Denied commands never reach the callback, so they cannot open a database connection, call Roblox, or invoke an AI provider.

## 3. Secret protection

`!ai_debug`:

- No longer prints key prefixes, key lengths, or any key material.
- Reports only `configured` / `not configured`.
- Remains owner-only through the central policy.
- Redacts configured secret values and common API-key formats from exception messages and the final response.
- Counts as an AI-cost command for rate limiting.

`redact_secrets()` covers configured Gemini/OpenRouter keys, Discord token, Roblox cookies, database URL, and `AIza…`/`sk-…` patterns.

## 4. AI abuse and cost controls

- Per-user AI limit: default **5** per window for non-owner use.
- Owner AI limit: default **20** per window.
- Global AI limit: default **30** per window.
- Window: default **600 seconds**.
- Configurable only through optional `M6_AI_*` environment settings; no production environment was modified.
- Unauthorized users are denied before the limiter is consulted, so they consume no quota.
- Denied or rate-limited AI commands make zero provider calls.

Conversation-planner controls (M6-A.1):

- Non-owner planner limit: **20 attempts/hour**.
- Owner planner limit: **100 attempts/hour**.
- Global planner limit: **200 attempts/hour**.
- Planner limits are process-global per Discord user, so new threads/sessions
  cannot reset them.
- The attempt is recorded before `_planner_ai()` runs; provider failures,
  timeouts, and invalid responses are charged once.
- Deterministic fast paths return before the planner budget/provider call.
- No additional AI operation is charged for a single planner call.

Commands classified as AI-cost include `!concept`, `!brainstorm`, `!rescue`, `!analyze_image`, `!chain`, `!creative`, `!creative_raw`, `!desc_analyze`, `!desc_forge`, `!autopsy`, `!revive`, `!path`, `!playbook`, `!meta_sniper`, `!stealth`, `!revsim`, `!sales_keywords`, `!tags`, and `!ai_debug`.

## 5. Before/after behavior

| Scenario | Before | After |
|---|---|---|
| `!snapshot_now` by non-owner | Ran API/DB path | Owner-only; denied before callback |
| `!sales_backfill` / `!sales_post_now` by non-owner | Ran mutation path | Owner-only; denied |
| `!visibility_seed` / `!visibility_run` by non-owner | Ran write/API path | Owner-only; denied |
| `!dbtest` by non-owner | Printed DB diagnostics | Owner-only; denied |
| `!concept` by non-owner | Would spend AI quota | Owner-only; denied before AI |
| `!brainstorm` by non-owner | Would spend AI quota | Owner-only; denied before AI |
| `!ai_debug` by non-owner | Printed key prefixes/lengths | Owner-only; no secret material |
| `!guide`, `!help`, `!version`, `!watchlist`, `!track`, `!sales_report`, `!converge` | Public | Still public |
| Aliased restricted command | Alias reached callback | Alias canonicalized and denied |
| Owner AI command above limit | No limit | Bounded per-user/global rejection |
| Owner AI command under limit | Worked | Still works |
| Planner AI for non-owner, new thread | Per-state 20/hour could reset | Process-global 20/hour per user |
| Planner provider fails or returns invalid JSON | Not charged in old state list | Counted once before provider |
| Planner over limit | Could still call provider in some paths | Deterministic route; zero provider calls |
| Sales embed from unapproved sender | Accepted by channel check alone | Finding documented; ingestion unchanged |

## 6. Security test results

`python test_m6a_security.py` — **15/15 passed**:

- Every command has an explicit policy.
- Owner-only commands deny non-owners and allow owners.
- Public read-only commands remain available.
- Aliases cannot bypass authorization.
- Unknown command names fail closed.
- Denial happens before callback work.
- Per-user and global AI limits reject excess invocations.
- Unauthorized AI requests consume no quota.
- Secret redaction removes keys and cookies.
- `!ai_debug` source contains no key prefix/length output.
- Mock API keys never appear in the Discord response.
- AI-cost and mutating commands are owner-only.
- The real `before_invoke` hook denies restricted commands and enforces AI limits.
- The real conversation router denies before callback and allows owners.
- Planner limits are global per user, survive new sessions, and count failed
  provider attempts.

## 7. Existing regression results

Full offline suite run (25 suites, all exit 0):

- Project ORACLE, ORACLE worker, rename watcher/tracking, survival intelligence, JARVIS, shared repairs.
- Convergence, execution policy, command cancellation.
- M6-A security and Vanta conversation routing.
- Emote title/quality/held-out suites.
- Creator intelligence Phase 1, M1, M2, identity persistence, M3, M4, snapshot batch.
- Astra, product understanding, recommendation lifecycle.
- `test_recommendation_lifecycle.py` skipped DB fixtures without `DATABASE_URL`; its non-DB cases passed.

Disposable PostgreSQL 16.2:

```text
Ran 23 tests in 1.482s
OK
PG_TEST_RETURN_CODE=0
```

No production database or Roblox API was used.

## 8. Remaining risks

These are outside M6-A scope and remain open:

- Public read-only commands such as `!converge` can still trigger live Roblox requests within their existing budget.
- Direct Roblox HTTP paths identified in F-05 are not rerouted by this correction.
- `main` remains unprotected and auto-deploy behavior is unchanged.
- Legacy probability/expected-sales language in F-03/F-04 is unchanged.
- `tracked_creators`/Creator Brain identity issues and ORACLE rate-limit behavior are unchanged.
- M4 remains disabled (`PHASE2_M4_ENABLED=0`) and is not activated.
- Sales embeds are not authenticated against a trusted webhook/sender. The
  finding and a proposed dry-run/enforce allowlist design are documented in
  `M6A1_SALES_SOURCE_REVIEW.md`; production ingestion behavior is unchanged.
- A determined operator with owner credentials can still consume owner AI limits; limits are bounded but not a security boundary against the owner.
- Planner limits are process-local; a multi-process deployment would need a
  shared store to enforce a single global budget.

## 9. Recommendation

**Controlled pull-request review is appropriate.**

The correction closes the requested P1 authorization, secret-disclosure, and AI-cost gaps without touching ORACLE, autonomous learning, sales attribution, `!emote_title`, database schemas, or production environment settings. Merge and deployment remain blocked pending explicit approval and CI results from the new branch.
