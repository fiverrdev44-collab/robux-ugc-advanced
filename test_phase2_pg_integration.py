"""Phase 2 Milestone 2 — real PostgreSQL integration tests.

Runs only against a disposable database supplied via DATABASE_URL. In CI,
PHASE2_REQUIRE_PG=1 makes a missing DATABASE_URL a failure instead of a skip.
Never point this at production credentials.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import creator_registry as cr

MIGRATION = Path(__file__).with_name("migrations").joinpath(
    "2026-11-05_creator_registry.sql")


class Phase2PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.getenv("DATABASE_URL")
        if not url:
            if os.getenv("PHASE2_REQUIRE_PG") == "1":
                raise RuntimeError("DATABASE_URL is required for PG tests")
            raise unittest.SkipTest("DATABASE_URL not set")
        cls.conn = psycopg2.connect(url)
        cls.conn.autocommit = True
        cls.cur = cls.conn.cursor()
        cls.cur.execute("""
            DROP TABLE IF EXISTS creator_registry CASCADE;
            DROP TABLE IF EXISTS item_history CASCADE;
            DROP TABLE IF EXISTS tracked_creators CASCADE;
            DROP TABLE IF EXISTS items CASCADE;
            CREATE TABLE items (
                id BIGINT PRIMARY KEY,
                name TEXT,
                description TEXT,
                favorite_count INTEGER,
                price INTEGER,
                total_sales INTEGER,
                creator_name TEXT,
                creator_id BIGINT,
                creator_verified BOOLEAN,
                asset_type_id INTEGER,
                created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ,
                fetched_at TIMESTAMPTZ,
                favorite_status TEXT,
                creator_type TEXT
            );
            CREATE TABLE tracked_creators (
                creator_id BIGINT PRIMARY KEY,
                creator_type TEXT,
                creator_name TEXT,
                verified BOOLEAN,
                last_scanned TIMESTAMPTZ
            );
            CREATE TABLE item_history (
                id SERIAL PRIMARY KEY,
                item_id BIGINT,
                favorite_count INTEGER,
                total_sales INTEGER,
                price INTEGER,
                snapshot_at TIMESTAMPTZ
            );
        """)
        cls.cur.execute(MIGRATION.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        try:
            cls.cur.close()
            cls.conn.close()
        except Exception:
            pass

    def setUp(self):
        self.cur = self.conn.cursor()
        self.cur.execute(
            "TRUNCATE creator_registry, item_history, tracked_creators, "
            "items RESTART IDENTITY CASCADE")

    def tearDown(self):
        try:
            self.cur.close()
        except Exception:
            pass

    def _item(self, item_id, creator_id, creator_type=None,
              creator_name="Creator", verified=None, favs=100, price=50,
              asset=61, age_days=1):
        created = datetime.now(timezone.utc) - timedelta(days=age_days)
        self.cur.execute("""
            INSERT INTO items (id, name, description, favorite_count, price,
                creator_name, creator_id, creator_type, creator_verified,
                asset_type_id, created_at, fetched_at, favorite_status)
            VALUES (%s, %s, '', %s, %s, %s, %s, %s, %s, %s, %s, NOW(),
                    %s)
        """, (item_id, f"Item {item_id}", favs, price, creator_name,
              creator_id, creator_type, verified, asset, created,
              "known" if favs is not None else "missing"))

    def _tracked(self, creator_id, creator_type, creator_name,
                 verified=None):
        self.cur.execute("""
            INSERT INTO tracked_creators
                (creator_id, creator_type, creator_name, verified)
            VALUES (%s, %s, %s, %s)
        """, (creator_id, creator_type, creator_name, verified))

    def _refresh(self, **kwargs):
        kwargs.setdefault("batch_size", 100)
        return cr.refresh_from_items(self.cur, **kwargs)

    def _registry(self, creator_type, creator_id):
        self.cur.execute("""
            SELECT display_name, verification_status, type_provenance,
                   item_count, previous_names, first_seen, last_seen
            FROM creator_registry
            WHERE creator_type = %s AND creator_id = %s
        """, (creator_type, creator_id))
        return self.cur.fetchone()

    def test_migration_and_composite_identity(self):
        self.cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'items' AND column_name = 'creator_type'
        """)
        self.assertIsNotNone(self.cur.fetchone())
        self.cur.execute("SELECT to_regclass('public.creator_registry')")
        self.assertIsNotNone(self.cur.fetchone())

        # Same numeric ID, different verified composite types.
        self._item(1, 300, "User", "Same", True)
        self._item(2, 300, "Group", "Same", None)
        # Missing item type, tracked name corroborates.
        self._item(3, 400, None, "Fallback")
        self._tracked(400, "Group", "Fallback", True)
        # Missing item type, tracked name does NOT corroborate.
        self._item(4, 500, None, "Mismatch")
        self._tracked(500, "User", "Other", True)

        totals = self._refresh()
        self.assertTrue(totals["done"])
        self.assertIsNotNone(self._registry("User", 300))
        self.assertIsNotNone(self._registry("Group", 300))
        fallback = self._registry("Group", 400)
        self.assertIsNotNone(fallback)
        self.assertEqual(fallback[2], "tracked_name_match")
        mismatch = self._registry("unknown", 500)
        self.assertIsNotNone(mismatch)
        self.assertEqual(mismatch[2], "missing")

    def test_verification_tristate_and_snapshot_coverage(self):
        self._item(10, 600, "User", "V", True)
        self._item(11, 601, "User", "N", False)
        self._item(12, 602, "User", "U", None)
        self._refresh()
        self.assertEqual(self._registry("User", 600)[1], "verified")
        self.assertEqual(self._registry("User", 601)[1], "nonverified")
        self.assertEqual(self._registry("User", 602)[1], "unknown")

        now = datetime.now(timezone.utc)
        self._item(20, 700, "User", "Snap", True)
        self.cur.execute("""
            INSERT INTO item_history (item_id, favorite_count, snapshot_at)
            VALUES (20, 10, %s), (20, 15, %s), (20, 1, %s)
        """, (now - timedelta(hours=3), now - timedelta(hours=1),
              now - timedelta(hours=2)))
        self.cur.execute("""
            INSERT INTO item_history (item_id, favorite_count, snapshot_at)
            VALUES (20, 20, %s)
        """, (now,))
        # A recent item with one snapshot and one with none.
        self._item(21, 701, "User", "One", True)
        self.cur.execute("""
            INSERT INTO item_history (item_id, favorite_count, snapshot_at)
            VALUES (21, 5, %s)
        """, (now,))
        self._item(22, 702, "User", "None", True)

        coverage = cr.snapshot_coverage(self.cur, 48)
        self.assertGreaterEqual(coverage["recent_items"], 3)
        self.assertGreaterEqual(coverage["valid_growth_items"], 1)
        self.assertGreaterEqual(coverage["one_snapshot"], 1)
        self.assertGreaterEqual(coverage["no_snapshots"], 1)
        self.assertFalse(coverage["missing_evidence"])

    def test_upsert_idempotency_and_name_history(self):
        self._item(30, 800, "User", "Old Name", True)
        self._refresh()
        first = self._registry("User", 800)
        self.assertEqual(first[0], "Old Name")

        self.cur.execute("""
            UPDATE items SET creator_name = 'New Name', fetched_at = NOW()
            WHERE id = 30
        """)
        self._refresh()
        changed = self._registry("User", 800)
        self.assertEqual(changed[0], "New Name")
        self.assertIn("Old Name", changed[4])
        self.assertNotIn("New Name", changed[4])

        # Repeated identical refresh: no duplicate history, stable counts.
        self._refresh()
        self._refresh()
        stable = self._registry("User", 800)
        self.assertEqual(stable[4].count("Old Name"), 1)
        self.assertEqual(stable[3], changed[3])
        self.assertEqual(stable[5], changed[5])
        self.assertEqual(stable[6], changed[6])

    def test_resumable_multiple_invocations(self):
        self._item(40, 10, "Group", "G10")
        self._item(41, 20, "Group", "G20")
        self._item(42, 30, "User", "U30")
        first = self._refresh(batch_size=1, max_batches=1)
        self.assertFalse(first["done"])
        self.assertIsNotNone(first["next_cursor"])
        second = self._refresh(batch_size=1, max_batches=1,
                               cursor=first["next_cursor"])
        self.assertFalse(second["done"])
        third = self._refresh(batch_size=1, cursor=second["next_cursor"])
        self.assertTrue(third["done"])
        self.assertEqual(self._registry("Group", 10)[3], 1)
        self.assertEqual(self._registry("Group", 20)[3], 1)
        self.assertEqual(self._registry("User", 30)[3], 1)

    def test_category_comparison_sql(self):
        for i in range(5):
            self._item(50 + i, 900, "User", "A", True, favs=500, age_days=20)
        for i in range(2):
            self._item(60 + i, 901, "Group", "B", None, favs=5, age_days=5)
        for i in range(3):
            self._item(70 + i, 902, "User", "C", False, favs=50, age_days=40)
        summary = cr.creator_comparison(
            self.cur, family="emotes", days=365, limit=100)
        self.assertEqual(summary["creators"], 3)
        self.assertEqual(summary["segments"]["established"]["creators"], 1)
        self.assertEqual(summary["segments"]["emerging"]["creators"], 2)
        self.assertEqual(summary["segments"]["verified"]["creators"], 1)
        self.assertEqual(summary["segments"]["nonverified"]["creators"], 1)
        self.assertEqual(summary["segments"]["unknown_verification"]["creators"], 1)
        self.assertEqual(summary["sample"]["order"], "item_id")
        self.assertFalse(summary["sample"]["representative"])

    def test_tracker_upsert_preserves_tristate_and_type(self):
        from creator_tracker import upsert_items
        upsert_items(self.cur, [{
            "id": 80, "name": "Ingested", "description": "",
            "favorite_count": 10, "price": 50, "creator_name": "Composite",
            "creator_id": 950, "creator_type": "Group",
            "creator_verified": None, "asset_type_id": 61,
            "created_at": datetime.now(timezone.utc),
        }])
        self.cur.execute("""
            SELECT creator_type, creator_verified FROM items WHERE id = 80
        """)
        self.assertEqual(self.cur.fetchone(), ("Group", None))

        upsert_items(self.cur, [{
            "id": 80, "name": "Ingested", "description": "",
            "favorite_count": 10, "price": 50, "creator_name": "Composite",
            "creator_id": 950, "creator_type": None,
            "creator_verified": False, "asset_type_id": 61,
            "created_at": datetime.now(timezone.utc),
        }])
        self.cur.execute("""
            SELECT creator_type, creator_verified FROM items WHERE id = 80
        """)
        self.assertEqual(self.cur.fetchone(), ("Group", False))

    def test_missing_table_before_migration(self):
        self.cur.execute("CREATE SCHEMA IF NOT EXISTS phase2_premig")
        self.cur.execute("SET search_path TO phase2_premig")
        self.cur.execute("""
            CREATE TABLE items (
                id BIGINT PRIMARY KEY, name TEXT, favorite_count INTEGER,
                price INTEGER, creator_name TEXT, creator_id BIGINT,
                creator_verified BOOLEAN, asset_type_id INTEGER,
                created_at TIMESTAMPTZ, fetched_at TIMESTAMPTZ
            );
            CREATE TABLE tracked_creators (
                creator_id BIGINT PRIMARY KEY, creator_type TEXT,
                creator_name TEXT, verified BOOLEAN
            );
            CREATE TABLE item_history (
                item_id BIGINT, favorite_count INTEGER, snapshot_at TIMESTAMPTZ
            );
        """)
        evidence = cr.creator_evidence(self.cur)
        self.assertFalse(evidence["registry"]["available"])
        with self.assertRaises(Exception):
            cr.refresh_from_items(self.cur)
        self.cur.execute("SET search_path TO public")
        self.cur.execute("DROP SCHEMA phase2_premig CASCADE")

    def test_transaction_rollback(self):
        self._item(90, 990, "User", "Rollback", True)
        self.conn.autocommit = False
        try:
            self._refresh()
            self.assertIsNotNone(self._registry("User", 990))
            self.conn.rollback()
            self.assertIsNone(self._registry("User", 990))
        finally:
            try:
                self.conn.rollback()
            except Exception:
                pass
            self.conn.autocommit = True


if __name__ == "__main__":
    unittest.main(verbosity=2)
