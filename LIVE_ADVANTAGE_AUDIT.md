# LIVE ADVANTAGE AUDIT — VANTA 73

**Collected:** 2026-10-31T08:40Z (UTC)
**Mode:** read-only (DB read-only session; GET-only live calls; no item changes)
**Commit:** `fd2904c` at collection, deployed
**Live API status during audit:** catalog search returned **HTTP 400** (without sort) and **HTTP 429** (with sort) from the production host. Live assertions below are marked **Blocked by Roblox API** rather than guessed.

| Command | Bot's claim | Live API reality | Pass | Freshness / action |
|---|---|---|---|---|
| `!meta_sniper` / `!vacuum` (gap) | For `cute emote`, top gap word = **`pants`** (13 suggestions, 0/20 top-title coverage, 6 family matches) | Live search for `pants` **Blocked (HTTP 400/429)** | ❌ **FAIL (internal logic)** | `pants` is classic-clothing demand leaking into an emote niche. Candidate words are harvested from suggestions matching **any** niche token (including the generic `cute`), so "cute pants" becomes an emote "gap". Family `use` ≥ 5 did not prevent it. |
| `!chain` (champion + exact rank) | `kawaii sway emote` → **no champion**; run aborted with `Intent extraction failed. Try a clearer description.` | Not reached (no title to test) | ❌ **FAIL (reliability)** | AI intent extraction failed (provider error/quota) and `run_chain` returns an error instead of a deterministic fallback. Earlier runs on this build did produce champions (e.g., 8 scored titles), so the pipeline works when the provider responds. Exact-match claim therefore **unverified**. |
| `!early` / `!momentum` (velocity) | DB: 19 favorites / 181.5 d = **0.105 favs/day** (`130928797494687`) | Live: 19 favorites / 181.5 d = **0.105 favs/day** | ✅ **PASS** | Favorites and created date match exactly; no freshness warning. |

## Details

### 1. Gap finding (`!meta_sniper` / `!vacuum`)
- Internal run with niche `aura emote` and `dance emote` produced **no gap** (suggestions thin).
- Niche `cute emote` produced `pants` (suggestions 13, top-20 title coverage 0, family matches 6).
- The word is not an emote concept; the live check could not run because Roblox rate-limited/refused the request.
- **Verdict:** the gap claim is not trustworthy for emotes even before the live check — it is a cross-category token. This is a logic defect, not just staleness.

### 2. Chain title/rank (`!chain`)
- Concept `kawaii sway emote` returned `{"error": "Intent extraction failed. Try a clearer description."}` in **1.8 s**; `scored_titles` was empty.
- Cause: `gemini_brain.extract_keywords` failed (provider/rate limit). The pipeline has no deterministic fallback for intent extraction, so the whole command fails.
- Earlier in this session the same build produced 8 verified titles for another concept, so this is availability-dependent, not a permanent code break.
- Exact-match verification could not be performed (no champion + live search blocked).

### 3. Velocity (`!early` / `!momentum`)
- Asset `130928797494687` (Cute Kitty Fluffy Beanie):
  - DB: `favorite_count = 19`, `created_at` → age 181.5 days → 0.105 favs/day.
  - Live: `favoriteCount = 19`, `Created` → age 181.5 days → 0.105 favs/day.
- **Verdict:** the favorites/age math matches live exactly. Note this is the simple lifetime rate; windowed momentum still depends on snapshot coverage (33 days, 6 items with ≥30 days).

## Actions / recommendations
1. Restrict gap candidates to **family-specific** suggestions: require the suggestion to contain the niche's head noun (`emote`/`dance`), not just any token such as `cute`. This removes `pants`-type leaks.
2. Add a deterministic fallback for `extract_keywords` failures so `!chain` degrades to a concept-derived title instead of erroring out.
3. Re-run this audit when the catalog API is not rate-limiting the host; exact-match counts remain unverified until then.

No live Roblox item was modified. 429/404 responses are marked, not faked.
