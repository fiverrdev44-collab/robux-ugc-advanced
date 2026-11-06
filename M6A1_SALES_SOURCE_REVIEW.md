# VANTA 73 — M6-A.1 Sales Source Trust Review

- **Branch:** `fix/m6a-security-authorization`
- **Reviewed files:** `discord_ugc_bot.py`, `sales_listener.py`
- **Mode:** read-only review; no ingestion behavior changed.
- **Finding severity:** **P2 — unauthenticated sales-embed source**
  - Escalate to P1 if the configured sales channel is writable by users or webhooks that are not fully trusted.

## Finding

`discord_ugc_bot.on_message()` accepts any message in `SALES_CHANNEL_ID` with embeds and passes it to `sales_listener.handle_sale_message()`:

- `discord_ugc_bot.py:80-93` checks only `message.channel.id == SALES_CHANNEL_ID`.
- `sales_listener.handle_sale_message()` (`sales_listener.py:699-715`) parses every embed and writes each parsed sale.
- `extract_sales_from_message()` does not check `message.webhook_id`, sender identity, bot identity, or a webhook allowlist.
- `backfill_channel()` applies the same embed parser to historical channel messages.
- Saved rows receive `source="discord"` and a deterministic `source_event_id`; the source is not authenticated.

There is no Discord-side signature available to the bot beyond the gateway’s authentication of the webhook message. The missing control is an allowlist binding the channel to an approved webhook ID or approved sender.

## Impact

A user who can post in the configured sales channel, or any other webhook able to post there, can create embeds that are recorded as sales. This can distort sales totals, attribution, reporting, and any downstream evidence/experiment decisions. It does not expose secrets or execute code.

## Source-validation design (proposed, not implemented)

### Configuration
Add, in a separately reviewed rollout:

- `SALES_SOURCE_MODE`: `off`, `dry-run`, or `enforce` (default `dry-run` for rollout).
- `SALES_WEBHOOK_IDS`: comma-separated trusted webhook IDs.
- `SALES_SOURCE_USER_IDS`: optional allowlist for approved bot/user embeds.
- Keep `SALES_CHANNEL_ID` as the first gate.

No new environment variable is required by this correction; this is a proposal for approval.

### Validation

For every incoming or backfilled message:

1. Require the exact configured `SALES_CHANNEL_ID`.
2. In `enforce` mode:
   - Accept only if `message.webhook_id` is in `SALES_WEBHOOK_IDS`; or
   - Accept only if `message.author.id` is in `SALES_SOURCE_USER_IDS` and the author is the expected bot/application identity.
3. Reject messages with no approved source before parsing embeds.
4. Log only safe metadata: channel ID, message ID, webhook ID presence, decision reason. Never log message contents or secrets.
5. Apply the same validator to `backfill_channel()` and any manual sales-posting path.

### Rollout

1. `dry-run`: ingest as today, log would-reject messages and source IDs.
2. Review a representative window; confirm legitimate sales are not rejected.
3. `enforce`: reject unapproved sources before `_extract_sale_from_embed`/DB writes.
4. Keep the existing `source_event_id` and schema unchanged.
5. Roll back by setting `SALES_SOURCE_MODE=off`.

## Why this is not implemented here

M6-A.1 is scoped to planner budget and authorization integration. Changing ingestion would require new production configuration and a separate reviewed rollout; doing so now would violate the instruction to preserve production ingestion behavior.
