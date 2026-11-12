# VANTA Conversation 2.0 — candidate release

This is an **isolated feature branch**. Changes are not deployed to Oracle by this PR alone.

**Rollout gate:** `VANTA_CONVERSATION_V2_ROLLOUT` defaults to `owner`. In this mode only the configured owner sees V2 behavior. `off` disables V2 for everyone; `all` requires a separate intentional rollout. Existing non-owner conversations retain the legacy 24-hour memory policy. This flag does not automatically grant permissions or bypass the existing command allowlist.

## New user experience

- Casual requests such as `hi i need smth` now receive an open-ended reply, without wasting an AI planner call or invoking an arbitrary command.
- Follow-up category messages such as `backgrounds` are interpreted in context after `I need help`, rather than being fed into a UGC creation engine.
- Small talk, fatigue, and requests to recall active context use bounded truthful responses. The bot never invents market metrics or item IDs.
- Explicit conversation memory controls for the current thread or DM: `clear conversation`, `turn off memory`, `turn on memory`, `what do you remember`.
- Memory stores bounded context for up to seven days, with the last 12 user snippets and six engine-output snippets; the opt-out setting persists independently. `clear conversation` deletes the stored context and resets in-memory state, **not Discord message history or other data tables**.

## Safety / performance

- Existing authorized allow-list command dispatch is unchanged.
- Natural-language social intents are handled before the LLM planner and are never interpreted as shell or database actions.
- Model-generated privacy or social actions are rejected, so destructive memory controls require exact user input.
- Test suite `test_vanta_conversation_v2.py` evaluates **500 distinct deterministic three-turn combinations** (not an independently sampled model-language benchmark), plus privacy, context, task-precedence, and unauthorized-action regressions.
- The 500-case suite is deterministic. It **does not** establish LLM response quality, 100% user understanding, live Discord behavior, or a measured CTR/sales increase.

## Deployment gate

Require CI PASS, reviewer approval, and staging/Discord tests with isolated tokens and database before any future production release. Do not merge to `main` until ready; the production deployment remains manual and schema-gated.
