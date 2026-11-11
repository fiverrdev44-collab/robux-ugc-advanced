"""Phase 2 Milestone 2 — real PostgreSQL integration tests.

Safety contract
---------------
* Only PHASE2_TEST_DATABASE_URL is used; there is no fallback to the
  application's DATABASE_URL.
* The URL must be local, its database name must contain "test", and
  PHASE2_TEST_DB_CONFIRM must equal "disposable". Otherwise the suite fails
  closed before connecting or executing any DDL.
* All objects live in a generated isolated schema. No DROP TABLE / TRUNCATE is
  ever issued against the public schema; cleanup drops only the generated
  test schema.
* Synthetic data only. Never point this at production credentials.
"""
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

import psycopg2
from psycopg2 import sql

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import creator_registry as cr

MIGRATION = Path(__file__).with_name("migrations").joinpath(
    "2026-11-05_creator_registry.sql")


def validate_test_database_url(url, confirm):
    """Return an error string for unsafe config; never include credentials."""
    if not url:
        return "missing PHASE2_TEST_DATABASE_URL"
    try:
        parts = urlsplit(url)
    except Exception:
        return "malformed test database URL"
    if parts.scheme not in ("postgres", "postgresql"):
        return "unsupported database scheme"
    host = (parts.hostname or "").lower()
    if host not in ("localhost", "127.0.0.1", "::1"):
        return "test database host must be local"
    dbname = (parts.path or "").lstrip("/")
    if not dbname or "test" not in dbname.lower():
        return "test database name must contain 'test'"
    if confirm != "disposable":
        return "PHASE2_TEST_DB_CONFIRM must equal 'disposable'"
    return None


def open_test_connection(connect_fn=None):
    url = os.getenv("PHASE2_TEST_DATABASE_URL", "").strip()
    require = os.getenv("PHASE2_REQUIRE_PG") == "1"
    if not url:
        if require:
            raise RuntimeError("PHASE2_TEST_DATABASE_URL is required")
        raise unittest.SkipTest("PHASE2_TEST_DATABASE_URL not set")
    error = validate_test_database_url(
        url, os.getenv("PHASE2_TEST_DB_CONFIRM", ""))
    if error:
        raise RuntimeError(f"unsafe test database configuration: {error}")
    return (connect_fn or psycopg2.connect)(url)


_BASE_SCHEMA_SQL = """
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
        favorite_status TEXT
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
    CREATE TABLE launch_ledger (
        item_id BIGINT PRIMARY KEY,
        launched_at TIMESTAMPTZ
    );
    CREATE TABLE my_sales (
        id SERIAL PRIMARY KEY,
        sale_date DATE,
        sale_time TIMESTAMPTZ,
        item_name TEXT,
        buyer TEXT,
        amount_robux INTEGER,
        status TEXT,
        asset_id BIGINT,
        source_event_id TEXT
    );
"""


class ConfigSafetyTests(unittest.TestCase):
    def test_missing_url_fails_before_connect_in_ci(self):
        fake_connect = mock.Mock()
        with mock.patch.dict(os.environ, {"PHASE2_REQUIRE_PG": "1"},
                             clear=True), \
                mock.patch.object(psycopg2, "connect", fake_connect):
            with self.assertRaises(RuntimeError):
                open_test_connection()
        fake_connect.assert_not_called()

    def test_missing_url_skips_locally_before_connect(self):
        fake_connect = mock.Mock()
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(psycopg2, "connect", fake_connect):
            with self.assertRaises(unittest.SkipTest):
                open_test_connection()
        fake_connect.assert_not_called()

    def test_production_host_is_rejected(self):
        err = validate_test_database_url(
            "postgresql://user:secret@db.example.com/production",
            "disposable")
        self.assertIsNotNone(err)
        self.assertIn("local", err)
        self.assertNotIn("secret", err)
        self.assertNotIn("db.example.com", err)

    def test_non_test_database_name_is_rejected(self):
        err = validate_test_database_url(
            "postgresql://user:secret@localhost/production", "disposable")
        self.assertIsNotNone(err)
        self.assertIn("contain 'test'", err)

    def test_missing_confirmation_is_rejected(self):
        err = validate_test_database_url(
            "postgresql://user:secret@localhost/vanta_test", "yes")
        self.assertIsNotNone(err)
        self.assertIn("disposable", err)

    def test_valid_local_test_config_is_accepted(self):
        url = "postgresql://user:secret@localhost/vanta_test"
        self.assertIsNone(validate_test_database_url(url, "disposable"))
        sentinel = object()
        fake_connect = mock.Mock(return_value=sentinel)
        with mock.patch.dict(os.environ, {
                "PHASE2_TEST_DATABASE_URL": url,
                "PHASE2_TEST_DB_CONFIRM": "disposable"}, clear=True):
            self.assertIs(open_test_connection(fake_connect), sentinel)
        fake_connect.assert_called_once_with(url)


class Phase2PostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = open_test_connection()
        cls.conn.autocommit = True
        cls.cur = cls.conn.cursor()
        cls.schema = "phase2_m2_" + uuid.uuid4().hex[:12]
        cls.cur.execute(sql.SQL("CREATE SCHEMA {}").format(
            sql.Identifier(cls.schema)))
        cls.cur.execute("SELECT set_config('search_path', %s, false)",
                        (cls.schema,))
        cls.cur.execute(_BASE_SCHEMA_SQL)
        cls.cur.execute(MIGRATION.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        try:
            cls.cur.execute("SELECT set_config('search_path', %s, false)",
                            ("public",))
            cls.cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(cls.schema)))
        except Exception:
            pass
        try:
            cls.cur.close()
            cls.conn.close()
        except Exception:
            pass

    def setUp(self):
        self.cur = self.conn.cursor()
        self.cur.execute(
            "TRUNCATE creator_registry, item_history, tracked_creators, "
            "launch_ledger, my_sales, items RESTART IDENTITY CASCADE")

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
            VALUES (%s, %s, '', %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s)
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
            WHERE table_schema = current_schema()
              AND table_name = 'items' AND column_name = 'creator_type'
        """)
        self.assertIsNotNone(self.cur.fetchone())
        self.cur.execute("SELECT to_regclass('creator_registry')")
        self.assertIsNotNone(self.cur.fetchone())

        self._item(1, 300, "User", "Same", True)
        self._item(2, 300, "Group", "Same", None)
        self._item(3, 400, None, "Fallback")
        self._tracked(400, "Group", "Fallback", True)
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
            VALUES (20, 10, %s), (20, 15, %s), (20, 20, %s)
        """, (now - timedelta(hours=3), now - timedelta(hours=1), now))
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
        self.assertEqual(self._registry("User", 800)[0], "Old Name")

        self.cur.execute("""
            UPDATE items SET creator_name = 'New Name', fetched_at = NOW()
            WHERE id = 30
        """)
        self._refresh()
        changed = self._registry("User", 800)
        self.assertEqual(changed[0], "New Name")
        self.assertIn("Old Name", changed[4])
        self.assertNotIn("New Name", changed[4])

        self._refresh()
        self._refresh()
        stable = self._registry("User", 800)
        self.assertEqual(stable[4].count("Old Name"), 1)
        self.assertEqual(stable[3], changed[3])
        self.assertEqual(stable[5], changed[5])
        self.assertEqual(stable[6], changed[6])

    def test_null_display_name_does_not_enter_history(self):
        self._item(100, 1100, "User", "Current Name", True)
        self._refresh()
        row = {
            "creator_type": "User", "creator_id": 1100,
            "display_name": None, "verification_status": "unknown",
            "verification_provenance": "missing",
            "type_provenance": "item_catalog",
            "first_seen": datetime.now(timezone.utc),
            "last_seen": datetime.now(timezone.utc), "item_count": 1,
            "category_counts": {"61": 1}, "price_counts": {"30_to_60": 1},
            "median_favorites": 100, "median_price": 50,
            "median_age_days": 1.0, "snapshot_item_count": 0,
            "max_snapshots": 0, "missing_favorite_items": 0,
            "previous_names": [],
        }
        cr.upsert_registry(self.cur, [row])
        cr.upsert_registry(self.cur, [row])
        current = self._registry("User", 1100)
        self.assertEqual(current[0], "Current Name")
        self.assertEqual(current[4], [])
        self.assertNotIn("Current Name", current[4])

        self.cur.execute("""
            UPDATE items SET creator_name = 'Renamed', fetched_at = NOW()
            WHERE id = 100
        """)
        self._refresh()
        renamed = self._registry("User", 1100)
        self.assertEqual(renamed[0], "Renamed")
        self.assertIn("Current Name", renamed[4])
        self.assertNotIn("Renamed", renamed[4])

        cr.upsert_registry(self.cur, [row])
        cr.upsert_registry(self.cur, [row])
        stable = self._registry("User", 1100)
        self.assertEqual(stable[0], "Renamed")
        self.assertEqual(stable[4].count("Current Name"), 1)
        self.assertNotIn("Renamed", stable[4])

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
        self.assertEqual(
            summary["segments"]["unknown_verification"]["creators"], 1)
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
        self.cur.execute(
            "SELECT creator_type, creator_verified FROM items WHERE id = 80")
        self.assertEqual(self.cur.fetchone(), ("Group", None))

        upsert_items(self.cur, [{
            "id": 80, "name": "Ingested", "description": "",
            "favorite_count": 10, "price": 50, "creator_name": "Composite",
            "creator_id": 950, "creator_type": None,
            "creator_verified": False, "asset_type_id": 61,
            "created_at": datetime.now(timezone.utc),
        }])
        self.cur.execute(
            "SELECT creator_type, creator_verified FROM items WHERE id = 80")
        self.assertEqual(self.cur.fetchone(), ("Group", False))

    def _item_identity(self, item_id):
        self.cur.execute(
            "SELECT creator_id, creator_type, creator_verified, creator_name "
            "FROM items WHERE id = %s", (item_id,))
        return self.cur.fetchone()

    def test_ingestion_pipelines_preserve_creator_identity(self):
        os.environ.setdefault("ROBLOSECURITY_COOKIE", "test-cookie")
        from roblox_batch_client import _normalize
        from creator_identity import economy_identity
        from enricher import _upsert_rows as enrich_upsert
        from enricher import _item_row as enrich_row
        from market_research_worker import _upsert as research_upsert
        from market_research_worker import _item_row as research_row
        from scanner import _upsert_items as scanner_upsert
        from scanner import _item_row as scanner_row
        from live_enrich import _upsert_item
        from creator_tracker import upsert_items, _to_item

        self._item(200, 700, "User", "Known", True)

        # Raw Roblox response -> normalize -> worker row -> PostgreSQL upsert.
        weak_raw = {
            "id": 200, "name": "Weak", "favoriteCount": 10,
            "price": 20, "assetType": 61,
        }
        weak = _normalize(weak_raw)
        for upsert, row in (
                (lambda items: enrich_upsert(self.cur, items, True,
                                             self.conn),
                 enrich_row(200, weak)),
                (lambda items: research_upsert(self.cur, items,
                                               has_type=True),
                 research_row(200, weak)),
                (lambda items: scanner_upsert(self.cur, items, True),
                 scanner_row(200, weak))):
            upsert([row])
            self.assertEqual(self._item_identity(200),
                             (700, "User", True, "Known"))

        _upsert_item(self.cur, {
            "id": 200, "name": "Live", "favorite_count": 7, "price": 10,
            "total_sales": 0, "description": "", "creator_name": "",
            "creator_id": None, "creator_type": None,
            "creator_verified": None, "asset_type_id": 61,
            "created_at": datetime.now(timezone.utc),
        }, True)
        self.assertEqual(self._item_identity(200), (700, "User", True, "Known"))

        upsert_items(self.cur, [_to_item({
            "id": 200, "name": "Tracker", "favoriteCount": 5,
            "price": 10, "assetType": 61,
        })])
        self.assertEqual(self._item_identity(200), (700, "User", True, "Known"))

        # Complete identity, including explicit nonverified status.
        group_raw = {
            "id": 201, "name": "Rich", "favoriteCount": 1, "price": 2,
            "assetType": 61, "creatorName": "Rich",
            "creatorTargetId": 701, "creatorType": "Group",
            "creatorHasVerifiedBadge": False,
        }
        normal = _normalize(group_raw)
        enrich_upsert(self.cur, [enrich_row(201, normal)], True, self.conn)
        self.assertEqual(self._item_identity(201),
                         (701, "Group", False, "Rich"))

        user_raw = dict(group_raw, id=202, creatorTargetId=702,
                        creatorType="User", creatorHasVerifiedBadge=True)
        user_normal = _normalize(user_raw)
        research_upsert(self.cur, [research_row(202, user_normal)],
                        has_type=True)
        self.assertEqual(self._item_identity(202),
                         (702, "User", True, "Rich"))

        scanner_raw = dict(group_raw, id=203, creatorTargetId=703,
                           creatorHasVerifiedBadge=True)
        scanner_normal = _normalize(scanner_raw)
        scanner_upsert(self.cur, [scanner_row(203, scanner_normal)], True)
        self.assertEqual(self._item_identity(203),
                         (703, "Group", True, "Rich"))

        live_identity = economy_identity({
            "Creator": {"Id": 704, "CreatorType": "User"}})
        _upsert_item(self.cur, {
            "id": 204, "name": "Rich", "favorite_count": 1, "price": 2,
            "total_sales": 0, "description": "", "creator_name": "Rich",
            "asset_type_id": 61, "created_at": datetime.now(timezone.utc),
            **live_identity,
        }, True)
        self.assertEqual(self._item_identity(204),
                         (704, "User", None, "Rich"))

        upsert_items(self.cur, [_to_item(dict(
            group_raw, id=205, creatorTargetId=705,
            creatorHasVerifiedBadge=True))])
        self.assertEqual(self._item_identity(205),
                         (705, "Group", True, "Rich"))

        # Same numeric ID must remain separate by creator type.
        enrich_upsert(self.cur, [enrich_row(206, _normalize(dict(
            group_raw, id=206, creatorTargetId=900, creatorType="User")))],
            True, self.conn)
        enrich_upsert(self.cur, [enrich_row(207, _normalize(dict(
            group_raw, id=207, creatorTargetId=900, creatorType="Group")))],
            True, self.conn)
        self.assertEqual(self._item_identity(206), (900, "User", False, "Rich"))
        self.assertEqual(self._item_identity(207),
                         (900, "Group", False, "Rich"))

    def test_ingestion_pre_migration_without_creator_type(self):
        os.environ.setdefault("ROBLOSECURITY_COOKIE", "test-cookie")
        from roblox_batch_client import _normalize
        from enricher import _upsert_rows as enrich_upsert
        from enricher import _item_row as enrich_row
        from market_research_worker import _upsert as research_upsert
        from market_research_worker import _item_row as research_row
        from scanner import _upsert_items as scanner_upsert
        from scanner import _item_row as scanner_row
        from live_enrich import _upsert_item
        from creator_tracker import upsert_items

        class NoopConn:
            def commit(self):
                pass

            def rollback(self):
                pass

        premig = "phase2_premig_" + uuid.uuid4().hex[:10]
        self.conn.autocommit = False
        try:
            self.cur.execute(sql.SQL("CREATE SCHEMA {}").format(
                sql.Identifier(premig)))
            self.cur.execute("SELECT set_config('search_path', %s, true)",
                             (premig,))
            self.cur.execute(_BASE_SCHEMA_SQL)
            self.cur.execute("""
                INSERT INTO items (id, name, creator_name, creator_id,
                                   creator_verified, favorite_status)
                VALUES (300, 'Known', 'Known', 900, TRUE, 'known')
            """)
            weak = _normalize({
                "id": 300, "name": "Weak", "favoriteCount": 10,
                "price": 20, "assetType": 61,
            })
            enrich_upsert(self.cur, [enrich_row(300, weak)], False,
                          NoopConn())
            research_upsert(self.cur, [research_row(300, weak)],
                            has_type=False)
            scanner_upsert(self.cur, [scanner_row(300, weak)], False)
            _upsert_item(self.cur, {
                "id": 300, "name": "Live", "favorite_count": 7, "price": 10,
                "total_sales": 0, "description": "", "creator_name": "",
                "creator_id": None, "creator_type": None,
                "creator_verified": None, "asset_type_id": 61,
                "created_at": datetime.now(timezone.utc),
            }, False)
            upsert_items(self.cur, [{
                "id": 300, "name": "Tracker", "description": "",
                "favorite_count": 5, "price": 10, "creator_name": "",
                "creator_id": None, "creator_type": None,
                "creator_verified": None, "asset_type_id": 61,
                "created_at": datetime.now(timezone.utc),
            }])
            self.cur.execute("""
                SELECT creator_id, creator_verified, creator_name
                FROM items WHERE id = 300
            """)
            self.assertEqual(self.cur.fetchone(), (900, True, "Known"))

            rich = _normalize({
                "id": 301, "name": "Rich", "favoriteCount": 1,
                "price": 2, "assetType": 61, "creatorName": "Rich",
                "creatorTargetId": 902, "creatorType": "Group",
                "creatorHasVerifiedBadge": False,
            })
            enrich_upsert(self.cur, [enrich_row(301, rich)], False,
                          NoopConn())
            self.cur.execute("""
                SELECT creator_id, creator_verified, creator_name
                FROM items WHERE id = 301
            """)
            self.assertEqual(self.cur.fetchone(), (902, False, "Rich"))
            self.conn.rollback()
        finally:
            try:
                self.conn.rollback()
            except Exception:
                pass
            self.conn.autocommit = True
            self.cur.execute("SELECT set_config('search_path', %s, false)",
                             (self.schema,))

    def test_snapshot_selection_prioritizes_launch_then_recent(self):
        self.cur.execute("""
            INSERT INTO items (id, name, favorite_count, price, total_sales,
                               created_at, fetched_at)
            VALUES
              (1001, 'Recent', 10, 5, 0, NOW() - INTERVAL '1 hour',
               NOW() - INTERVAL '30 minutes'),
              (1002, 'OldTier0', 2000, 5, 0, NOW() - INTERVAL '30 days',
               NOW() - INTERVAL '3 hours'),
              (1003, 'Launch', 2000, 5, 0, NOW() - INTERVAL '30 days',
               NOW() - INTERVAL '4 hours'),
              (1004, 'Tier1', 500, 5, 0, NOW() - INTERVAL '30 days',
               NOW() - INTERVAL '5 hours')
        """)
        self.cur.execute(
            "INSERT INTO launch_ledger (item_id, launched_at) "
            "VALUES (1003, NOW())")
        import snapshot
        self.cur.execute(snapshot._SELECTION_SQL, (2,))
        ids = [row[0] for row in self.cur.fetchall()]
        self.assertEqual(ids, [1003, 1001])

    def test_m3_evidence_bridge_read_only(self):
        import opportunity_validation as ov
        now = datetime.now(timezone.utc)
        rows = [
            (9001, "floating emote A", 10, 10, 1, 101, "User", True, "Alpha"),
            (9002, "floating emote B", 15, 12, 2, 102, "Group", None, "Beta"),
            (9003, "floating emote C", 20, 15, 3, 103, "User", False,
             "Gamma"),
            (9004, "floating emote D", 25, 18, 4, 777, "User", True,
             "SameName"),
            (9005, "floating emote E", 30, 20, 5, 777, "Group", True,
             "SameName"),
            (9006, "floating emote F", 40, 25, 6, None, None, None, None),
        ]
        for (iid, name, favs, price, age, cid, ctype, verified,
             cname) in rows:
            self.cur.execute("""
                INSERT INTO items (id, name, favorite_count, price,
                    created_at, fetched_at, creator_id, creator_type,
                    creator_verified, creator_name, asset_type_id,
                    favorite_status)
                VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s, 61,
                        'known')
            """, (iid, name, favs, price, now - timedelta(days=age),
                  cid, ctype, verified, cname))
        sale_time = now - timedelta(minutes=1)
        self.cur.execute("""
            INSERT INTO my_sales (sale_time, item_name, amount_robux,
                                  asset_id)
            VALUES (%s, 'floating emote A', 100, 9001),
                   (%s, 'floating emote B', 200, 9002),
                   (%s, 'unresolved', 300, NULL)
        """, (sale_time, sale_time, sale_time))
        before_items = self._count("items")
        before_sales = self._count("my_sales")
        candidate = {
            "keyword": "floating emote", "family": "emotes", "score": 60,
            "demand": 12, "supply": 6, "median_favs": 22.5, "recent": 6,
            "velocity": 2.0, "velocity_measured": True, "observations": 3,
            "stale": False, "freshness": "recent", "concentration": 0.3,
        }
        live = {
            "ok": True, "sampled_results": 30, "category_correct": 20,
            "category_mismatched": 10, "exact_title_matches": 1,
            "conceptual_matches": 8, "capped": False, "pages": 1,
            "sample_note": "first 60 results sampled",
            "verification_timestamp": now.isoformat(), "top_competitors": [],
        }
        bundles = ov.build_validation_bundles(
            {"shortlist": [candidate]}, {"floating emote": live},
            "emotes", self.cur, now=now)
        assert len(bundles) == 1
        bundle = bundles[0]
        assert bundle["creator"]["identified_creator_count"] == 5
        assert bundle["creator"]["identity_coverage_pct"] == 83.3
        assert any("SameName" == d["display_name"]
                   for d in bundle["creator"]["duplicate_names_distinct_ids"])
        assert bundle["sales"]["status"] == "confirmed"
        assert bundle["sales"]["confirmed_units"] == 2
        assert bundle["sales"]["confirmed_robux"] == 300
        assert bundle["sales"]["unresolved_transactions"] == 1
        assert bundle["investigation_verdict"] == ov.VERDICT_VALIDATE
        assert self._count("items") == before_items
        assert self._count("my_sales") == before_sales

    def test_m3_item_sample_enforces_reported_window(self):
        import opportunity_validation as ov
        now = datetime.now(timezone.utc)
        recent_created = now - timedelta(days=10)
        old_created = now - timedelta(days=400)
        self.cur.execute("""
            INSERT INTO items (id, name, favorite_count, price, created_at,
                fetched_at, creator_id, creator_type, creator_verified,
                creator_name, asset_type_id, favorite_status)
            VALUES
              (9201, 'floating emote recent', 100, 10, %s, NOW(), 601,
               'User', TRUE, 'Recent', 61, 'known'),
              (9202, 'floating emote old', 10000, 99, %s, NOW(), 602,
               'User', TRUE, 'Old', 61, 'known'),
              (9203, 'floating emote undated', 9000, 50, NULL, NOW(), 603,
               'User', TRUE, 'Undated', 61, 'known')
        """, (recent_created, old_created))
        rows = ov.fetch_item_sample(
            self.cur, "floating emote", "emotes", limit=50,
            sample_window_days=180)
        assert [r["id"] for r in rows] == [9201]
        assert max(r["favorite_count"] for r in rows) == 100

        undated = ov.count_undated_matches(
            self.cur, "floating emote", "emotes", limit=50)
        assert undated == {"count": 1, "capped": False, "limit": 50}

        summary = ov.summarize_item_sample(
            rows, now=now, sample_limit=50, undated_matches=1,
            sample_window_days=180)
        assert summary["sample_items"] == 1
        assert summary["sample_window_days"] == 180
        assert summary["undated_excluded_n"] == 1
        assert summary["favorite_distribution"]["max"] == 100
        assert summary["favorite_distribution"]["window_days"] == 180
        assert summary["item_age_distribution"]["sample_n"] == 1
        assert summary["item_age_distribution"]["missing_created_at_n"] == 1
        returned_min = datetime.fromisoformat(
            summary["sample_created_at_min"])
        assert abs((returned_min - recent_created).total_seconds()) < 2

        candidate = {
            "keyword": "floating emote", "family": "emotes", "score": 50,
            "demand": 12, "supply": 3, "median_favs": 100, "recent": 1,
            "velocity": 1.0, "velocity_measured": True, "observations": 2,
            "stale": False, "freshness": "recent",
        }
        live = {
            "ok": True, "sampled_results": 30, "category_correct": 20,
            "category_mismatched": 10, "exact_title_matches": 0,
            "conceptual_matches": 8, "capped": False, "pages": 1,
            "sample_note": "first 60 results sampled",
            "verification_timestamp": now.isoformat(), "top_competitors": [],
        }
        bundle = ov.build_validation_bundles(
            {"shortlist": [candidate]}, {"floating emote": live},
            "emotes", self.cur, now=now)[0]
        assert bundle["database"]["sample_window_days"] == 180
        assert bundle["database"]["distribution_sample_size"] == 1
        assert bundle["database"]["undated_matches_excluded"] == 1
        assert bundle["database"]["favorite_distribution"]["max"] == 100
        assert bundle["database"]["bounded_item_sample"]["representative"] is False

    def _count(self, table):
        self.cur.execute(f"SELECT count(*) FROM {table}")
        return self.cur.fetchone()[0]

    def test_m3_missing_registry_context(self):
        import opportunity_validation as ov
        premig = "m3_noreg_" + uuid.uuid4().hex[:10]
        self.conn.autocommit = False
        try:
            self.cur.execute(sql.SQL("CREATE SCHEMA {}").format(
                sql.Identifier(premig)))
            self.cur.execute("SELECT set_config('search_path', %s, true)",
                             (premig,))
            self.cur.execute(_BASE_SCHEMA_SQL)
            self.cur.execute("""
                INSERT INTO items (id, name, favorite_count, price,
                    created_at, fetched_at, creator_id, creator_verified,
                    creator_name, asset_type_id, favorite_status)
                VALUES (9101, 'floating emote no registry', 10, 10, NOW(),
                        NOW(), 501, TRUE, 'Alpha', 61, 'known')
            """)
            context = ov.build_category_context(self.cur, "emotes")
            assert context["registry"]["available"] is False
            now = datetime.now(timezone.utc)
            rows = ov.fetch_item_sample(
                self.cur, "floating emote", "emotes", limit=10,
                sample_window_days=180)
            assert len(rows) == 1
            assert rows[0]["creator_id"] == 501
            assert rows[0]["creator_type"] is None
            summary = ov.summarize_item_sample(rows, now=now)
            assert summary["creator"]["numeric_creator_count"] == 1
            assert summary["creator"]["identified_creator_count"] == 0
            assert summary["creator"]["unknown_creator_type_items"] == 1
            bundle = ov.build_evidence_bundle(
                {"keyword": "floating emote", "family": "emotes",
                 "supply": 1, "median_favs": 10, "recent": 1,
                 "velocity": None, "velocity_measured": False,
                 "observations": 0, "stale": False, "freshness": "none",
                 "score": 10, "demand": 1},
                None, rows, context, None, now=now)
            assert bundle["creator"]["registry_available"] is False
            assert bundle["creator"]["identified_creator_count"] == 0
            assert bundle["creator"]["unknown_creator_type_items"] == 1
            assert bundle["investigation_verdict"] != ov.VERDICT_VALIDATE
            self.conn.rollback()
        finally:
            try:
                self.conn.rollback()
            except Exception:
                pass
            self.conn.autocommit = True
            self.cur.execute("SELECT set_config('search_path', %s, false)",
                             (self.schema,))

    def test_sales_dedupe_preserves_distinct_event_ids(self):
        import database
        now = datetime.now(timezone.utc)
        self.cur.execute("""
            INSERT INTO my_sales
                (sale_time, item_name, buyer, amount_robux, source_event_id)
            VALUES (%s, 'Same Item', 'Buyer', 50, 'event-a'),
                   (%s, 'Same Item', 'Buyer', 50, 'event-b')
        """, (now, now))
        self.cur.execute(database.MY_SALES_DEDUPE_SQL)
        self.cur.execute("""
            SELECT count(*), array_agg(source_event_id ORDER BY source_event_id)
            FROM my_sales
        """)
        assert self.cur.fetchone() == (2, ["event-a", "event-b"])

        self.cur.execute("""
            INSERT INTO my_sales
                (sale_time, item_name, buyer, amount_robux, source_event_id)
            VALUES (%s, 'Duplicate', 'Buyer', 50, 'event-dup'),
                   (%s, 'Duplicate', 'Buyer', 50, 'event-dup')
        """, (now, now))
        self.cur.execute(database.MY_SALES_DEDUPE_SQL)
        self.cur.execute("""
            SELECT count(*) FROM my_sales WHERE source_event_id = 'event-dup'
        """)
        assert self.cur.fetchone()[0] == 1

    def test_m4_market_evidence_exact_category_and_read_only(self):
        import original_concept_engine as m4
        now = datetime.now(timezone.utc)
        created = now - timedelta(days=10)
        self.cur.execute("""
            INSERT INTO items (id, name, favorite_count, price, created_at,
                fetched_at, creator_id, creator_type, creator_verified,
                creator_name, asset_type_id, favorite_status)
            VALUES
              (9301, 'floating crystal wings', 100, 50, %s, NOW(), 701,
               'User', TRUE, 'BackMaker', 46, 'known'),
              (9302, 'floating crystal wings', 9999, 10, %s, NOW(), 702,
               'User', TRUE, 'EmoteMaker', 61, 'known'),
              (9303, 'floating crystal wings', 200, 20, %s, NOW(), 703,
               'Group', TRUE, 'NeckMaker', 43, 'known'),
              (9304, 'simple levitation', 50, 15, %s, NOW(), 704,
               'User', TRUE, 'EmoteMaker2', 61, 'known')
        """, (created, created, created, created))
        before_items = self._count("items")
        before_sales = self._count("my_sales")
        evidence = m4.collect_market_evidence(
            self.cur, "back", "floating crystal wings",
            sample_limit=50, window_days=180)
        assert evidence["asset_type_ids"] == [46]
        assert evidence["sample_n"] == 1
        assert evidence["top_competitors"][0]["id"] == 9301
        assert evidence["top_competitors"][0]["favorites"] == 100
        assert evidence["evidence_ids"] == ["db:item:9301"]
        assert 9302 not in [x.get("id") for x in evidence["top_competitors"]]
        assert 9303 not in [x.get("id") for x in evidence["top_competitors"]]
        assert evidence["evidence_status"] == "SAMPLED"
        assert evidence["market_validation_status"] == "EXPLORATORY"
        assert evidence["match_mode"] == "token_or_terms"
        assert evidence["exact_phrase_match"] is False
        assert "crystal" in evidence["query_terms"]
        assert "floating" in evidence["query_terms"]
        assert set(evidence["top_competitors"][0]["matched_terms"]) >= {
            "crystal", "floating"}

        natural = m4.collect_market_evidence(
            self.cur, "emotes", "smooth futuristic levitation dance",
            sample_limit=50, window_days=180)
        assert natural["sample_n"] == 1
        assert natural["top_competitors"][0]["id"] == 9304
        assert "levitation" in natural["query_terms"]
        assert natural["match_mode"] == "token_or_terms"
        assert natural["exact_phrase_match"] is False
        assert "levitation" in natural["top_competitors"][0]["matched_terms"]
        assert self._count("items") == before_items
        assert self._count("my_sales") == before_sales

    def test_missing_registry_does_not_abort_transaction(self):
        """P1: autocommit=False, safe availability check, later queries work."""
        premig = "phase2_premig_" + uuid.uuid4().hex[:10]
        self.conn.autocommit = False
        try:
            self.cur.execute(sql.SQL("CREATE SCHEMA {}").format(
                sql.Identifier(premig)))
            self.cur.execute("SELECT set_config('search_path', %s, true)",
                             (premig,))
            self.cur.execute(_BASE_SCHEMA_SQL)
            evidence = cr.creator_evidence(self.cur)
            self.assertFalse(evidence["registry"]["available"])
            self.assertEqual(evidence["registry"]["reason"], "missing_table")
            self.assertIn("comparison", evidence)
            self.assertIn("snapshot_coverage", evidence)
            self.cur.execute("SELECT 1")
            self.assertEqual(self.cur.fetchone()[0], 1)
            self.conn.rollback()
        finally:
            try:
                self.conn.rollback()
            except Exception:
                pass
            self.conn.autocommit = True
            self.cur.execute("SELECT set_config('search_path', %s, false)",
                             (self.schema,))

    def test_evidence_in_normal_transaction(self):
        self._item(120, 1200, "User", "TX", True)
        self._refresh()
        self.conn.autocommit = False
        try:
            evidence = cr.creator_evidence(self.cur)
            self.assertNotEqual(evidence["registry"].get("available"), False)
            self.cur.execute("SELECT 1")
            self.assertEqual(self.cur.fetchone()[0], 1)
        finally:
            self.conn.rollback()
            self.conn.autocommit = True

    def test_transaction_rollback(self):
        self._item(90, 990, "User", "Rollback", True)
        self.conn.autocommit = False
        try:
            self._refresh()
            self.assertIsNotNone(self._registry("User", 990))
            self.conn.rollback()
            self.assertIsNone(self._registry("User", 990))
        finally:
            self.conn.rollback()
            self.conn.autocommit = True


if __name__ == "__main__":
    unittest.main(verbosity=2)
