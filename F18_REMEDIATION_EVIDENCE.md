# F-18 Remediation Evidence — Trusted Sales Source Enforcement

## A. Final SHA

- Remediation code commit under certification:
  `a241a10b574a13d64fec905c6bc63381a4c9b563`
- Branch: `fix/f18-sales-source-authentication`
- Baseline: `9342b1357547636917e3bad285a3325790e169b2`
- Frozen audit branch: `df325a3d0b584b7933dd55ca035380b8d0369531`
  (untouched)

## B. Root-cause analysis

- `discord_ugc_bot.on_message()` gated sales ingestion only by
  `SALES_CHANNEL_ID` and `message.embeds`.
- `handle_sale_message()` and `backfill_channel()` parsed every embed and wrote
  sale rows without checking `message.webhook_id`, author identity, bot status,
  guild, or an approved allowlist.
- The prepared validator was not wired into any ingestion path and had a
  precedence defect: an unapproved webhook could fall through to a trusted
  bot-author check.
- Startup, pre-report, `!sales_backfill`, and `!sales_post_now` all reached the
  same unvalidated parser. Direct persistence helpers also had no validation
  marker guard.

## C. Sales ingestion call-site inventory

| Route | Path | Validation after F-18 |
|---|---|---|
| Live Discord message | `discord_ugc_bot.on_message` → `handle_sale_message` | Central validator before `message.embeds`/`extract_sales_from_message` |
| Startup recovery | `_startup_sales_backfill` → `auto_backfill` → `backfill_channel` | Per-message central validation |
| `!sales_backfill` | `commands_sales` → `backfill_channel` | Per-message central validation |
| `!sales_post_now` | `commands_sales` → `auto_backfill` → `backfill_channel` | Per-message central validation |
| Daily pre-report sync | `post_monitor.send_daily_report` → `auto_backfill` | Per-message central validation |
| Direct single save | `_save_sale_single` | Refuses sales without `_source_validated` |
| Direct batch save | `_save_sales_batch` | Filters unvalidated sales before DB access |
| Legacy test/admin helper | `_insert_sale` | Requires explicit `validated=True` or marker |
| Parse-only helper | `extract_sales_from_message` | No DB writes; never marks validation |
| Reconciliation/reporting | `sales_reconciliation`, `commands_sales` reads | Read-only |

## D. Changed files

- `sales_source_validation.py` — central configuration, validation, webhook
  precedence, diagnostics and safe logging.
- `sales_listener.py` — validation before parsing/DB writes in live and
  backfill paths; `_source_validated` marker; persistence-helper guards.
- `test_f18_sales_source_security.py` — 14 integration/security tests.
- `test_integrity_upgrades.py` — explicit validated=True for the legacy
  admin insert helper.
- CI workflows — F-18 branch trigger and security test step.

No schema migration, Discord command, creator identity, API budget, M4 flag,
or historical sales row was changed.

## E. Source-authentication architecture

- `SourceConfig` is loaded only from explicitly approved environment
  configuration.
- `validate_message()` evaluates actual Discord metadata: channel ID, guild ID,
  `webhook_id`, author ID, and `author.bot`.
- Webhook identity has strict precedence:
  - If `webhook_id` is present, only that webhook allowlist decides trust.
  - An unapproved webhook can never fall through to an approved bot author ID.
  - Without a webhook ID, only an explicitly approved bot/application sender
    is trusted.
  - A human user is never trusted merely because their numeric ID is in the
    sender list.
- Enforce mode rejects before `extract_sales_from_message()` and before
  `_save_sale_single()`/`_save_sales_batch()`.
- Accepted parsed sales receive `_source_validated=True` and a safe
  `_source_kind` marker. Persistence helpers refuse unmarked sales.
- Diagnostics record safe aggregates: evaluated, allowed, would-reject,
  rejected, accepted webhook/bot, disabled, and reason counts.

## F. Configuration contract

| Variable | Meaning |
|---|---|
| `SALES_SOURCE_MODE` | `off`, `dry-run`, or `enforce`; default `off` |
| `SALES_CHANNEL_ID` | Required approved channel in enforce |
| `SALES_GUILD_ID` | Optional approved guild; enforced when set |
| `SALES_WEBHOOK_IDS` | Comma/space-separated approved webhook snowflakes |
| `SALES_SOURCE_USER_IDS` | Comma/space-separated approved bot/application IDs |

- IDs must be numeric Discord snowflakes; malformed entries are configuration
  errors, not silently ignored.
- Enforce mode fails closed if the channel or both allowlists are missing.
- Invalid mode fails closed for the central evaluator; the legacy wrapper
  raises a hard configuration error.
- No production IDs are hardcoded or invented.
- Enforce is never enabled automatically.

## G. Bypass-prevention evidence

Tests prove:

- Approved webhook in the approved channel is accepted.
- Approved bot sender is accepted; a human with the same numeric ID is not.
- Unapproved webhook + matching trusted bot author ID is rejected as webhook.
- Wrong channel, wrong guild, and missing source metadata are rejected.
- Empty/malformed configuration fails closed in enforce.
- Enforce rejects before embed parsing and before DB access.
- Live listener, startup/manual backfill, and auto-backfill use the same
  validator.
- Direct `_save_sale_single`, `_save_sales_batch`, and `_insert_sale` refuse
  unvalidated sales without touching the DB.
- `!sales_backfill` and `!sales_post_now` delegate to the validated listener
  paths, not to the parser.

## H. Tests and CI

- Complete offline suite: **37/37 scripts passed**.
- F-18 security suite: **14/14 passed**.
- Existing sales-source suite: **5/5 passed**.
- Sales integrity suite: **20/20 passed**.
- F-10 timestamp: **10/10 offline + 5/5 PostgreSQL** passed.
- F-09 ORACLE recovery: **12/12 offline + 3/3 PostgreSQL** passed.
- F-07/F-08 identity: **13/13 offline + 5/5 PostgreSQL** passed.
- F-05 API safety: **16/16 passed**.
- Command contracts: **90/90 passed**.
- Public/restricted callback suites passed.

Final code-commit CI:

- Survival Intelligence Tests (`offline-regression`): **success** —
  https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42519397743
  - Confirmed step: `Run F-18 sales source security regressions`.
- Phase 2 PostgreSQL Integration (`phase2-postgres`): **success** —
  https://github.com/fiverrdev44-collab/robux-ugc-advanced/actions/runs/42519397742

## I. Historical sales preservation

- Source validation runs before parsing and does not mutate or delete sale
  rows.
- `source_event_id`, transaction IDs, timestamps, UTC sale dates, item/buyer/
  group attribution, amounts, and deduplication behavior are untouched.
- The validation identity test confirms a parsed sale remains byte-for-byte
  unchanged.
- Existing sales integrity and reconciliation tests pass unchanged.
- No database migration was required or applied.

## J. Rollout and enforcement approval

- **Stage A — Configuration review:** identify legitimate webhook IDs, bot
  identities, channel, and guild. No IDs were invented.
- **Stage B — Dry-run:** deploy with `SALES_SOURCE_MODE=dry-run` and approved
  configuration; observe aggregate would-reject and reason counts.
- **Stage C — Enforcement approval:** review dry-run evidence and obtain
  explicit approval.
- **Stage D — Controlled enforcement:** set `SALES_SOURCE_MODE=enforce` only
  through a separately approved production configuration change; monitor
  rejection/missing-sale counts and roll back by setting `off`.
- Production is not in enforce mode. No production configuration was changed.

## K. Remaining limitations

- Real trusted webhook/sender IDs and the production rollout have not been
  approved, so production enforcement is **not** active or verified.
- Default mode remains `off`; until Stage C/D, unapproved channel messages can
  still be ingested in production.
- An approved webhook identifies the Discord notification source; it does not
  independently prove that Roblox completed a transaction. Marketplace
  reconciliation remains a separate control.
- No live Discord or production database test was performed.
- Discord gateway/webhook signature verification is outside this application;
  the allowlist is the application-level trust boundary.

## L. F-18 verdict

**F-18 PARTIALLY CLOSED**

Implementation is verified: every active sales-ingestion path applies one
central trusted-source contract, enforcement rejects before parsing/DB access,
and bypass paths are guarded. Production enforcement cannot be marked complete
until approved trusted-source identities and the dry-run/enforce rollout gates
are completed.

## Overall release verdict

**Overall VANTA 73 certification remains NO-GO** until F-18 production
enforcement and the remaining audit/release gates are completed. No merge,
deployment, production configuration change, M4 activation, new command, or
frozen-branch modification was performed.
