# VANTA 73 — Sales Integrity Repair (dry-run)

Branch: `fix/sales-integrity-repair`
Scope: read-only investigation + additive code/migration + tests. **No production
sales data was modified, deleted, or re-keyed.** No destructive deduplication ran.

---

## 1. Audit findings

| # | Defect | Where | Effect |
|---|---|---|---|
| 1 | `source_event_id = discord:<msgid>:<item_name>:<amount>` collapses two same-price sales in one message | `sales_listener._extract_sale_from_embed` | distinct embeds overwrite/dedupe each other |
| 2 | Dedup relied on `(sale_time, item_name, buyer, amount_robux)`; `sale_time` was the *notification* time, so delayed webhooks shifted the "sale" to the wrong UTC day | old listener + `database.py` unique constraint | under/over-count across UTC date boundaries |
| 3 | No provider transaction ID was captured, so a reposted notification and a legitimate repeat purchase were indistinguishable | listener | silent drops or false duplicates |
| 4 | No embed index, no marketplace timestamp, no asset/group/buyer ids preserved | listener | identity loss; `item_name` only |
| 5 | Legacy rows have no stable event id (or a legacy-format id); blind re-import under a new id format would duplicate them | listener + backfill | double counting |
| 6 | `on conflict do nothing` with no conflict target silently skips inserts when the unique index is missing | `_insert_sale` | every insert fails silently |

## 2. Why historical DB totals differ from the channel export

Given the audit snapshot (`665` rows / `11,841` R$ recorded; `627` mapped, `38`
unresolved) the discrepancy against a full channel export is explained by a
combination of:

- **Multi-embed same-price collapse** (finding 1) — one message with N identical
  sales stored at most one row.
- **Name-in-ID fragility** (finding 1) — a renamed item changes the legacy id,
  so a re-backfill can add a *new* row for an already-seen sale.
- **Notification-vs-transaction time** (finding 2) — a sale completed at
  `23:59 UTC` but notified after midnight is bucketed on the wrong day; the
  export counts it on the marketplace date.
- **Partial backfill** — `!sales_backfill`/`auto_backfill` read a capped history
  (`limit 200/500/1000`); deleted or edited messages are unrecoverable.
- **Silent skip** (finding 6) — on a table lacking the unique index, inserts
  were discarded without a log entry.
- **Unresolved names** — `38` rows resolve to no asset and are counted
  separately, not merged into an item's lifetime total.

The reconciliation CLI below makes these gaps explicit and quantifiable per
message/transaction.

## 3. Changes

- `sales_listener.py`
  - Deterministic per-embed id: `txn:<provider>:<id>` when a transaction id is
    present, else `discord:<msgid>:<embed_index>`.
  - `notification_time` (Discord) kept separate from `sale_time` (marketplace);
    `sale_date` derives from `sale_time` in UTC.
  - Transaction id / asset id / group id / buyer id extraction from fields,
    footer, and description text.
  - Adaptive insert: only uses columns that exist, so it runs pre- and
    post-migration; `_insert_sale(cur, sale)` keeps its old signature/return.
  - `duplicate_reason()` dedupes on evidence: exact event id → transaction id →
    legacy id → legacy/unknown-row fingerprints. Distinct stable ids are never
    merged, so legitimate repeat purchases survive.
  - `sales_summary()` now returns a `coverage` block (event-id coverage, legacy
    vs txn vs missing, completeness flag and note).
- `migrations/2026-11-03_sales_integrity_columns.sql` (additive only)
  - Adds nullable `notification_time, transaction_id, source_event_version,
    embed_index, asset_id, group_id, buyer_id, raw_item_name, time_source,
    group_name` plus non-unique indexes. **Not executed.**
- `sales_reconciliation.py` (read-only CLI + pure `reconcile()`)
- `commands_sales.py` — `!sales_report` prints coverage and an explicit
  incomplete-coverage warning; `sales_scan` passes the embed index.
- `post_monitor.py` — `analyze_sales`/`format_report` include a Coverage block
  and the same recorded-amount semantics, so `!sales_post_now` and
  conversational `sales_report` requests stay consistent.

## 4. Dry-run reconciliation output (offline fixture)

```
# SALES RECONCILIATION (dry-run, read-only)

## Totals
• Database:   4 rows · R$210
• Export:     3 rows · R$184
• Row delta:  +1 · Amount delta: R$+26
• Matched:    2 · Missing in DB: 1 · Extra in DB: 2

## Possible duplicates (shared transaction id)
  • txn `T1` × 2

## Possible duplicates (shared source event id)
  • evt `txn:roblox:T1` × 2

## Timestamp discrepancies
  • UTC date drift: sale 2026-11-02 vs notification 2026-11-03 (discord:222:0)

## Missing from database (in export only)
  • Missing From DB · R$99 · txn=T2 · evt=- · time=2026-11-02 10:00:00+00:00

## In database but not in export
  • Smooth 360 flip Rizz · R$75 · txn=T1 · evt=txn:roblox:T1 · time=2026-10-31 10:00:00+00:00
  • Cute Hat · R$50 · txn=- · evt=discord:111:0 · time=2026-11-01 09:00:00+00:00

_Nothing was written, deleted, or deduplicated._
```

Run against production (read-only) with:

```bash
python sales_reconciliation.py --export /path/to/channel_export.csv
python sales_reconciliation.py --self-check
```

The CLI opens a `BEGIN TRANSACTION READ ONLY` and rolls back; it never writes.

## 5. Test results

New suite `test_sales_integrity.py` (13 tests) — all passing:

```
python -m unittest test_sales_integrity
Ran 13 tests in 0.001s
OK
```

Coverage of the required regression scenarios:

| Scenario | Test |
|---|---|
| Multiple same-price sales in one message | `test_multiple_same_price_sales_one_message` |
| Provider transaction id preferred | `test_provider_transaction_id_preferred`, `..._from_description` |
| Delayed notification / UTC boundary | `test_delayed_notification_utc_boundary`, `test_utc_date_boundary_discrepancy` |
| Duplicate repost vs legitimate repeat purchase | `test_repost_same_transaction_id_is_duplicate`, `test_legit_repeat_purchase_not_duplicate` |
| Renamed item name preservation | `test_renamed_item_preserves_original_name` |
| Legacy records / legacy ids | `test_legacy_source_event_id_recognised`, `test_legacy_null_event_id_fingerprint`, `test_distinct_stable_ids_never_collide` |
| Asset identity from URL | `test_asset_id_extracted_from_url` |
| Reconciliation engine | `test_reconcile_counts_and_duplicates` |

Existing offline suites still pass: `test_identity_and_windows.py`,
`test_shared_repairs.py` (`ALL ... PASSED`; DB fixtures skipped — no
`DATABASE_URL`).

## 6. Safety status & next steps (need approval)

- [x] Worked on a separate branch (`fix/sales-integrity-repair`).
- [x] No production data modified/deleted/migrated.
- [x] No destructive deduplication run.
- [ ] **Awaiting approval** to apply `migrations/2026-11-03_sales_integrity_columns.sql`
      (additive columns + indexes only).
- [ ] After the reconciliation report shows `duplicate_event_ids = 0` and
      `duplicate_fingerprints = 0`, optionally create the unique index
      documented in the migration (comment).
- [ ] Once live, re-running `auto_backfill` will not change verified totals:
      legacy rows match their legacy id, and v2/txn ids are idempotent.
