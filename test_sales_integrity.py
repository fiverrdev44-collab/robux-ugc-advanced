"""Regression tests for the VANTA 73 sales-integrity repair.

Offline: no database or network required. Exercises the parser, the event-id
model, dedupe evidence, and the reconciliation engine.

Run:
    python -m unittest test_sales_integrity -v
"""
import os
import sys
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sales_listener as sl
import sales_reconciliation as sr
from item_resolver import normalize_name


def field(name, value):
    return SimpleNamespace(name=name, value=value)


def embed(title, description="", fields=(), timestamp=None, footer=None):
    return SimpleNamespace(
        title=title, description=description, fields=list(fields),
        timestamp=timestamp, footer=footer,
    )


def message(message_id, created_at, embeds):
    return SimpleNamespace(id=message_id, created_at=created_at, embeds=embeds)


def dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class EventIdTests(unittest.TestCase):
    def test_multiple_same_price_sales_one_message(self):
        msg = message("111111", dt("2026-11-01T12:00:00Z"), [
            embed("New Sale", fields=[
                field("Item", "Cute Hat"),
                field("Amount", "75"),
                field("Buyer", "buyer1"),
            ]) for _ in range(3)
        ])
        sales = sl.extract_sales_from_message(msg)
        self.assertEqual(len(sales), 3)
        ids = [s["source_event_id"] for s in sales]
        self.assertEqual(ids, [
            "discord:111111:0", "discord:111111:1", "discord:111111:2",
        ])
        self.assertEqual(len(set(ids)), 3)
        # Legacy id is identical for all three (why the old code collapsed them).
        legacy = [s["_legacy_id"] for s in sales]
        self.assertEqual(len(set(legacy)), 1)
        for s in sales:
            self.assertEqual(s["amount_robux"], 75)
            self.assertEqual(s["notification_time"], dt("2026-11-01T12:00:00Z"))

    def test_provider_transaction_id_preferred(self):
        msg = message("222222", dt("2026-11-01T12:00:00Z"), [
            embed("New Sale", fields=[
                field("Item", "Beanie"),
                field("Amount", "100"),
                field("Transaction ID", "TXN-ABC-123"),
            ]),
        ])
        sale = sl.extract_sales_from_message(msg)[0]
        self.assertEqual(sale["transaction_id"], "TXN-ABC-123")
        self.assertEqual(sale["source_event_id"], "txn:roblox:TXN-ABC-123")

    def test_transaction_id_from_description(self):
        msg = message("333333", dt("2026-11-01T12:00:00Z"), [
            embed("Purchase", description="Thanks! Transaction ID: ORD-456",
                  fields=[field("Item", "Shirt"), field("Amount", "50")]),
        ])
        sale = sl.extract_sales_from_message(msg)[0]
        self.assertEqual(sale["transaction_id"], "ORD-456")

    def test_delayed_notification_utc_boundary(self):
        # Marketplace timestamp is Oct 31 23:59Z, notification arrives Nov 1.
        msg = message("444444", dt("2026-11-01T00:10:00Z"), [
            embed("New Sale", fields=[
                field("Item", "Emote"),
                field("Amount", "80"),
                field("Date", "2026-10-31T23:59:00Z"),
            ]),
        ])
        sale = sl.extract_sales_from_message(msg)[0]
        self.assertEqual(sale["sale_time"], dt("2026-10-31T23:59:00Z"))
        self.assertEqual(sale["notification_time"], dt("2026-11-01T00:10:00Z"))
        self.assertEqual(sale["sale_date"].isoformat(), "2026-10-31")
        self.assertEqual(sale["time_source"], "transaction_field")

    def test_renamed_item_preserves_original_name(self):
        msg = message("555555", dt("2026-11-01T12:00:00Z"), [
            embed("New Sale", fields=[
                field("Item", "NAME  : ⭐Smooth 360 flip Rizz"),
                field("Amount", "16"),
            ]),
        ])
        sale = sl.extract_sales_from_message(msg)[0]
        self.assertEqual(sale["raw_item_name"], "NAME  : ⭐Smooth 360 flip Rizz")
        # item_name is preserved verbatim; canonical identity is resolved later.
        self.assertEqual(sale["item_name"], "NAME  : ⭐Smooth 360 flip Rizz")
        self.assertEqual(
            normalize_name(sale["item_name"]),
            normalize_name("Smooth 360 flip Rizz"),
        )

    def test_asset_id_extracted_from_url(self):
        msg = message("666666", dt("2026-11-01T12:00:00Z"), [
            embed("New Sale", description="https://www.roblox.com/catalog/130928797494687/X",
                  fields=[field("Item", "Beanie"), field("Amount", "90")]),
        ])
        sale = sl.extract_sales_from_message(msg)[0]
        self.assertEqual(sale["asset_id"], 130928797494687)


class DedupeTests(unittest.TestCase):
    def test_repost_same_transaction_id_is_duplicate(self):
        existing = [{"source_event_id": "txn:roblox:TXN-1",
                     "transaction_id": "TXN-1", "notification_time": None,
                     "sale_time": dt("2026-10-31T10:00:00Z"),
                     "item_name": "Hat", "buyer": "b", "amount_robux": 50}]
        repost = {"source_event_id": "discord:999:0", "transaction_id": "TXN-1",
                  "notification_time": dt("2026-11-01T10:00:00Z"),
                  "sale_time": dt("2026-10-31T10:00:00Z"),
                  "item_name": "Hat", "buyer": "b", "amount_robux": 50,
                  "_legacy_id": None}
        self.assertEqual(sl.duplicate_reason(repost, existing), "transaction_id")

    def test_legit_repeat_purchase_not_duplicate(self):
        # Same item/price/buyer, but distinct transaction ids and times.
        existing = [{"source_event_id": "txn:roblox:TXN-1",
                     "transaction_id": "TXN-1", "notification_time": None,
                     "sale_time": dt("2026-10-31T10:00:00Z"),
                     "item_name": "Hat", "buyer": "b", "amount_robux": 50}]
        later = {"source_event_id": "txn:roblox:TXN-2",
                 "transaction_id": "TXN-2",
                 "notification_time": dt("2026-11-02T10:00:00Z"),
                 "sale_time": dt("2026-11-02T10:00:00Z"),
                 "item_name": "Hat", "buyer": "b", "amount_robux": 50,
                 "_legacy_id": None}
        self.assertIsNone(sl.duplicate_reason(later, existing))

    def test_legacy_source_event_id_recognised(self):
        existing = [{"source_event_id": "discord:123:My Hat:50",
                     "transaction_id": None, "notification_time": None,
                     "sale_time": dt("2026-10-31T10:00:00Z"),
                     "item_name": "My Hat", "buyer": "b", "amount_robux": 50}]
        reimport = {"source_event_id": "discord:123:0",
                    "transaction_id": None,
                    "notification_time": dt("2026-10-31T10:00:00Z"),
                    "sale_time": dt("2026-10-31T10:00:00Z"),
                    "item_name": "My Hat", "buyer": "b", "amount_robux": 50,
                    "_legacy_id": "discord:123:My Hat:50"}
        self.assertEqual(sl.duplicate_reason(reimport, existing),
                         "legacy_source_event_id")

    def test_legacy_null_event_id_fingerprint(self):
        existing = [{"source_event_id": None, "transaction_id": None,
                     "notification_time": dt("2026-10-31T10:00:00Z"),
                     "sale_time": dt("2026-10-31T10:00:00Z"),
                     "item_name": "Hat", "buyer": "b", "amount_robux": 50}]
        reimport = {"source_event_id": "discord:456:0", "transaction_id": None,
                    "notification_time": dt("2026-10-31T10:00:00Z"),
                    "sale_time": dt("2026-10-31T10:00:00Z"),
                    "item_name": "Hat", "buyer": "b", "amount_robux": 50,
                    "_legacy_id": "discord:456:Hat:50"}
        self.assertEqual(sl.duplicate_reason(reimport, existing),
                         "notification_fingerprint")

    def test_distinct_stable_ids_never_collide(self):
        existing = [{"source_event_id": "__event_a__", "transaction_id": None,
                     "notification_time": None, "sale_time": dt("2026-10-31T10:00:00Z"),
                     "item_name": "Hat", "buyer": "b", "amount_robux": 50}]
        other = {"source_event_id": "__event_b__", "transaction_id": None,
                 "notification_time": None, "sale_time": dt("2026-10-31T10:00:00Z"),
                 "item_name": "Hat", "buyer": "b", "amount_robux": 50,
                 "_legacy_id": None}
        self.assertIsNone(sl.duplicate_reason(other, existing))

    def test_legacy_same_item_price_different_buyers_not_collapsed(self):
        # Two buyers bought the same item at the same price in one message.
        # They share a legacy id but must not collapse into one sale.
        existing = [{"source_event_id": "discord:123:My Hat:50",
                     "transaction_id": None, "notification_time": None,
                     "sale_time": dt("2026-10-31T10:00:00Z"),
                     "item_name": "My Hat", "buyer": "buyerA", "amount_robux": 50}]
        incoming = {"source_event_id": "discord:123:0", "transaction_id": None,
                    "notification_time": dt("2026-10-31T10:00:00Z"),
                    "sale_time": dt("2026-10-31T10:00:00Z"),
                    "item_name": "My Hat", "buyer": "buyerB", "amount_robux": 50,
                    "_legacy_id": "discord:123:My Hat:50"}
        self.assertIsNone(sl.duplicate_reason(incoming, existing))

    def test_legacy_same_buyer_still_deduplicated(self):
        existing = [{"source_event_id": "discord:123:My Hat:50",
                     "transaction_id": None, "notification_time": None,
                     "sale_time": dt("2026-10-31T10:00:00Z"),
                     "item_name": "My Hat", "buyer": "buyerA", "amount_robux": 50}]
        incoming = {"source_event_id": "discord:123:0", "transaction_id": None,
                    "notification_time": dt("2026-10-31T10:00:00Z"),
                    "sale_time": dt("2026-10-31T10:00:00Z"),
                    "item_name": "My Hat", "buyer": "buyerA", "amount_robux": 50,
                    "_legacy_id": "discord:123:My Hat:50"}
        self.assertEqual(sl.duplicate_reason(incoming, existing),
                         "legacy_source_event_id")

    def test_missing_buyer_legacy_is_ambiguous(self):
        existing = [{"source_event_id": "discord:123:My Hat:50",
                     "transaction_id": None, "notification_time": None,
                     "sale_time": dt("2026-10-31T10:00:00Z"),
                     "item_name": "My Hat", "buyer": None, "amount_robux": 50}]
        incoming = {"source_event_id": "discord:123:0", "transaction_id": None,
                    "notification_time": dt("2026-10-31T10:00:00Z"),
                    "sale_time": dt("2026-10-31T10:00:00Z"),
                    "item_name": "My Hat", "buyer": "buyerA", "amount_robux": 50,
                    "_legacy_id": "discord:123:My Hat:50"}
        self.assertEqual(sl.duplicate_reason(incoming, existing),
                         "ambiguous_buyer")

    def test_both_missing_buyer_is_ambiguous(self):
        existing = [{"source_event_id": "discord:123:My Hat:50",
                     "transaction_id": None, "notification_time": None,
                     "sale_time": dt("2026-10-31T10:00:00Z"),
                     "item_name": "My Hat", "buyer": "", "amount_robux": 50}]
        incoming = {"source_event_id": "discord:123:0", "transaction_id": None,
                    "notification_time": dt("2026-10-31T10:00:00Z"),
                    "sale_time": dt("2026-10-31T10:00:00Z"),
                    "item_name": "My Hat", "buyer": "", "amount_robux": 50,
                    "_legacy_id": "discord:123:My Hat:50"}
        self.assertEqual(sl.duplicate_reason(incoming, existing),
                         "ambiguous_buyer")


class ReconciliationTests(unittest.TestCase):
    def test_reconcile_counts_and_duplicates(self):
        db_rows = [
            {"id": 1, "source_event_id": "txn:roblox:T1", "transaction_id": "T1",
             "sale_time": "2026-10-31T10:00:00Z", "item_name": "Hat",
             "amount_robux": 50},
            {"id": 2, "source_event_id": "txn:roblox:T1", "transaction_id": "T1",
             "sale_time": "2026-10-31T10:00:00Z", "item_name": "Hat",
             "amount_robux": 50},
            {"id": 3, "source_event_id": "discord:5:0", "transaction_id": None,
             "sale_time": "2026-11-01T10:00:00Z", "item_name": "Extra",
             "amount_robux": 10},
        ]
        export_rows = [
            {"source_event_id": "txn:roblox:T1", "transaction_id": "T1",
             "transaction_time": "2026-10-31T10:00:00Z", "item_name": "Hat",
             "amount_robux": 50},
            {"source_event_id": "discord:9:0", "transaction_id": "T9",
             "transaction_time": "2026-11-02T10:00:00Z", "item_name": "Missing",
             "amount_robux": 99},
        ]
        r = sr.reconcile(db_rows, export_rows)
        self.assertEqual(r["matched"], 1)
        self.assertEqual(len(r["missing_in_db"]), 1)
        self.assertEqual(len(r["extra_in_db"]), 2)  # dup T1 + Extra
        self.assertIn("T1", r["duplicate_transaction_ids"])
        self.assertEqual(r["totals"]["db_rows"], 3)
        self.assertEqual(r["totals"]["export_rows"], 2)
        self.assertEqual(r["totals"]["row_delta"], 1)

    def test_utc_date_boundary_discrepancy(self):
        db_rows = [{
            "id": 1, "source_event_id": "discord:7:0", "transaction_id": None,
            "sale_time": "2026-10-31T23:59:00Z",
            "notification_time": "2026-11-01T00:10:00Z",
            "item_name": "Hat", "amount_robux": 50,
        }]
        export_rows = [{
            "source_event_id": "discord:7:0", "transaction_id": None,
            "transaction_time": "2026-10-31T23:59:00Z",
            "item_name": "Hat", "amount_robux": 50,
        }]
        r = sr.reconcile(db_rows, export_rows)
        self.assertEqual(r["matched"], 1)
        kinds = {d.get("kind") for d in r["timestamp_discrepancies"]}
        self.assertIn("utc_date_boundary", kinds)

    def test_transaction_id_match_ignores_timestamp(self):
        db_rows = [{
            "id": 1, "source_event_id": "txn:roblox:T1", "transaction_id": "T1",
            "sale_time": "2026-10-31T10:00:00Z", "item_name": "Hat",
            "amount_robux": 50,
        }]
        export_rows = [{
            "source_event_id": "txn:roblox:T1", "transaction_id": "T1",
            "transaction_time": "2026-11-02T18:00:00Z", "item_name": "Hat",
            "amount_robux": 50,
        }]
        r = sr.reconcile(db_rows, export_rows)
        self.assertEqual(r["matched"], 1)
        self.assertEqual(len(r["missing_in_db"]), 0)
        self.assertEqual(len(r["extra_in_db"]), 0)
        self.assertTrue(any(d.get("delta_seconds")
                            for d in r["timestamp_discrepancies"]))

    def test_fingerprint_does_not_pair_different_buyers(self):
        db_rows = [{
            "id": 1, "source_event_id": "discord:1:0", "transaction_id": None,
            "sale_time": "2026-10-31T10:00:00Z", "item_name": "Hat",
            "buyer": "buyerA", "amount_robux": 50,
        }]
        export_rows = [{
            "source_event_id": "discord:2:0", "transaction_id": None,
            "transaction_time": "2026-10-31T10:00:00Z", "item_name": "Hat",
            "buyer": "buyerB", "amount_robux": 50,
        }]
        r = sr.reconcile(db_rows, export_rows)
        self.assertEqual(r["matched"], 0)
        self.assertEqual(len(r["missing_in_db"]), 1)
        self.assertEqual(len(r["extra_in_db"]), 1)

    def test_delayed_txn_match_reserved_before_fingerprint(self):
        # One DB record is claimable by a delayed transaction-id match AND by
        # a fingerprint-only competitor. The txn-id match must reserve the row
        # first, leaving the fingerprint competitor unmatched.
        db_rows = [{
            "id": 1, "source_event_id": "txn:roblox:T1", "transaction_id": "T1",
            "sale_time": "2026-10-31T10:00:00Z", "item_name": "Hat",
            "amount_robux": 50,
        }]
        export_rows = [
            {"source_event_id": "txn:roblox:T1", "transaction_id": "T1",
             "transaction_time": "2026-11-02T18:00:00Z", "item_name": "Hat",
             "amount_robux": 50},
            {"source_event_id": "discord:9:0", "transaction_id": None,
             "transaction_time": "2026-10-31T10:00:00Z", "item_name": "Hat",
             "amount_robux": 50},
        ]
        r = sr.reconcile(db_rows, export_rows)
        self.assertEqual(r["matched"], 1)
        self.assertEqual(len(r["missing_in_db"]), 1)  # fingerprint competitor
        self.assertEqual(len(r["extra_in_db"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
