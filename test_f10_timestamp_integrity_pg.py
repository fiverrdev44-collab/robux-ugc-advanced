"""Disposable-PostgreSQL tests for F-10 timestamp migration and indexes."""
import os
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_phase2_pg_integration import open_test_connection  # noqa: E402

ROOT = Path(__file__).resolve().parent
MIGRATION = (ROOT / "migrations" /
             "2026-11-08_f10_timestamp_integrity.sql").read_text(
                 encoding="utf-8")


class TimestampPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = open_test_connection()
        cls.conn.autocommit = True
        cls.cur = cls.conn.cursor()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.cur.close()
            cls.conn.close()
        except Exception:
            pass

    def setUp(self):
        self.schema = "f10_" + uuid.uuid4().hex[:12]
        self.cur.execute(f'CREATE SCHEMA "{self.schema}"')
        self.cur.execute(f'SET search_path TO "{self.schema}"')
        self.cur.execute("""
            CREATE TABLE items (
                id BIGINT PRIMARY KEY,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE item_history (
                id SERIAL PRIMARY KEY,
                item_id BIGINT,
                snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX idx_item_history_daily
                ON item_history (item_id, (snapshot_at::date));
            CREATE TABLE failed_items (
                id BIGINT PRIMARY KEY, last_tried TIMESTAMP);
            CREATE TABLE search_suggestions (
                id SERIAL PRIMARY KEY, fetched_at TIMESTAMP);
            CREATE TABLE learned_keywords (
                id SERIAL PRIMARY KEY, learned_at TIMESTAMP);
            CREATE TABLE user_profiles (
                discord_id BIGINT PRIMARY KEY,
                first_seen TIMESTAMP, last_active TIMESTAMP);
            CREATE TABLE saved_consultations (
                id SERIAL PRIMARY KEY, created_at TIMESTAMP);
            CREATE TABLE watchlist (
                id SERIAL PRIMARY KEY, added_at TIMESTAMP,
                last_checked TIMESTAMP);
            CREATE TABLE competitor_tracking (
                id SERIAL PRIMARY KEY, added_at TIMESTAMP);
            CREATE TABLE item_tracker (
                id SERIAL PRIMARY KEY, added_at TIMESTAMP);
            CREATE TABLE my_portfolio (
                item_id BIGINT PRIMARY KEY, added_at TIMESTAMP);
            CREATE TABLE launch_ledger (
                item_id BIGINT PRIMARY KEY, launched_at TIMESTAMP,
                last_synced TIMESTAMP);
            CREATE TABLE creator_patterns (
                pattern_key TEXT PRIMARY KEY, pattern_value TEXT,
                updated_at TIMESTAMP);
            CREATE TABLE tracked_creators (
                creator_id BIGINT NOT NULL, creator_type TEXT NOT NULL,
                last_scanned TIMESTAMP, added_at TIMESTAMP,
                PRIMARY KEY (creator_type, creator_id));
            CREATE TABLE predictor_weights (
                id SERIAL PRIMARY KEY, trained_at TIMESTAMP);
            CREATE TABLE my_sales (
                id SERIAL PRIMARY KEY, sale_date DATE,
                sale_time TIMESTAMPTZ, source_event_id TEXT,
                item_name TEXT, buyer TEXT, amount_robux INTEGER);
            CREATE UNIQUE INDEX idx_my_sales_event_id
                ON my_sales (source_event_id)
                WHERE source_event_id IS NOT NULL;
        """)

    def tearDown(self):
        try:
            self.cur.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
        except Exception:
            pass

    def _apply_migration(self):
        conn = open_test_connection()
        conn.autocommit = False
        try:
            cur = conn.cursor()
            cur.execute(f'SET search_path TO "{self.schema}"')
            cur.execute(MIGRATION)
            conn.commit()
            cur.close()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _seed(self):
        self.cur.execute("""
            INSERT INTO items (id, created_at, updated_at, fetched_at)
            VALUES (1, '2026-03-08 01:30:00', '2026-03-08 02:00:00',
                    '2026-03-08 02:15:00'),
                   (2, '2026-12-31 23:30:00', NULL, NULL)
        """)
        self.cur.execute("""
            INSERT INTO item_history (item_id, snapshot_at)
            VALUES (1, '2026-03-08 23:30:00'),
                   (1, '2026-03-09 00:30:00'),
                   (2, '2026-03-09 01:30:00')
        """)
        self.cur.execute("""
            INSERT INTO my_sales
              (sale_date, sale_time, source_event_id, item_name, buyer, amount_robux)
            VALUES ('2026-03-08', '2026-03-08T10:00:00+05:30', 'evt-1',
                    'Item', 'Buyer', 10)
        """)

    def test_migration_preserves_utc_instants_and_index(self):
        self._seed()
        self.cur.execute("SELECT count(*) FROM items")
        items_before = self.cur.fetchone()[0]
        self.cur.execute("SELECT count(*) FROM item_history")
        history_before = self.cur.fetchone()[0]
        self._apply_migration()

        for table, column in (
                ("items", "created_at"), ("items", "updated_at"),
                ("items", "fetched_at"), ("item_history", "snapshot_at")):
            self.cur.execute("""
                SELECT data_type FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = %s AND column_name = %s
            """, (table, column))
            assert self.cur.fetchone()[0] == "timestamp with time zone"

        self.cur.execute(
            "SELECT created_at AT TIME ZONE 'UTC' FROM items WHERE id=1")
        assert self.cur.fetchone()[0].isoformat() == "2026-03-08T01:30:00"
        self.cur.execute("SELECT count(*) FROM items")
        assert self.cur.fetchone()[0] == items_before
        self.cur.execute("SELECT count(*) FROM item_history")
        assert self.cur.fetchone()[0] == history_before

        self.cur.execute("""
            SELECT pg_get_indexdef(to_regclass('idx_item_history_daily'))
        """)
        index_def = self.cur.fetchone()[0]
        assert "AT TIME ZONE" in index_def and "UTC" in index_def

        # Re-running the migration is safe.
        self._apply_migration()
        print("PASS migration preserves UTC instants, rows and UTC index")

    def test_utc_day_uniqueness_under_non_utc_session(self):
        self._seed()
        self._apply_migration()
        self.cur.execute("SET TIME ZONE '-05:00'")
        try:
            self.cur.execute("""
                SELECT (snapshot_at AT TIME ZONE 'UTC')::date,
                       snapshot_at::date
                FROM item_history WHERE item_id=1
                ORDER BY snapshot_at ASC LIMIT 1
            """)
            utc_day, local_day = self.cur.fetchone()
            assert utc_day.isoformat() == "2026-03-08"
            assert local_day.isoformat() == "2026-03-09"

            # Same UTC day must collide, despite the non-UTC session.
            with self.assertRaises(Exception):
                self.cur.execute("""
                    INSERT INTO item_history (item_id, snapshot_at)
                    VALUES (1, '2026-03-08 12:00:00+00')
                """)
            # Different UTC day is accepted.
            self.cur.execute("""
                INSERT INTO item_history (item_id, snapshot_at)
                VALUES (1, '2026-03-10 12:00:00+00')
            """)
        finally:
            self.cur.execute("SET TIME ZONE 'GMT'")
        print("PASS UTC-day uniqueness is independent of session timezone")

    def test_duplicate_utc_days_abort_transactionally(self):
        self.cur.execute("DROP INDEX idx_item_history_daily")
        self.cur.execute("""
            INSERT INTO item_history (item_id, snapshot_at)
            VALUES (9, '2026-05-01 01:00:00'),
                   (9, '2026-05-01 23:00:00')
        """)
        with self.assertRaises(Exception):
            self._apply_migration()
        self.cur.execute("""
            SELECT data_type FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name='item_history' AND column_name='snapshot_at'
        """)
        assert self.cur.fetchone()[0] == "timestamp without time zone"
        self.cur.execute("SELECT count(*) FROM item_history WHERE item_id=9")
        assert self.cur.fetchone()[0] == 2
        print("PASS duplicate UTC days abort without data loss")

    def test_rollback_restores_naive_utc_and_old_index(self):
        self._seed()
        self._apply_migration()
        self.cur.execute("DROP INDEX idx_item_history_daily")
        self.cur.execute("""
            ALTER TABLE items
              ALTER COLUMN created_at TYPE timestamp
              USING created_at AT TIME ZONE 'UTC'
        """)
        self.cur.execute("""
            ALTER TABLE item_history
              ALTER COLUMN snapshot_at TYPE timestamp
              USING snapshot_at AT TIME ZONE 'UTC'
        """)
        self.cur.execute("""
            CREATE UNIQUE INDEX idx_item_history_daily
            ON item_history (item_id, (snapshot_at::date))
        """)
        self.cur.execute("""
            SELECT data_type FROM information_schema.columns
            WHERE table_schema=current_schema()
              AND table_name='items' AND column_name='created_at'
        """)
        assert self.cur.fetchone()[0] == "timestamp without time zone"
        self.cur.execute(
            "SELECT created_at FROM items WHERE id=1")
        assert self.cur.fetchone()[0].isoformat() == "2026-03-08T01:30:00"
        print("PASS rollback restores naive UTC values and old index")

    def test_sales_offsets_remain_distinct_from_notification(self):
        self._seed()
        self._apply_migration()
        self.cur.execute("""
            SELECT sale_time AT TIME ZONE 'UTC', sale_date
            FROM my_sales WHERE source_event_id='evt-1'
        """)
        sale_utc, sale_date = self.cur.fetchone()
        assert sale_utc.isoformat() == "2026-03-08T04:30:00"
        assert sale_date.isoformat() == "2026-03-08"
        with self.assertRaises(Exception):
            self.cur.execute("""
                INSERT INTO my_sales
                  (sale_date, sale_time, source_event_id, item_name, buyer,
                   amount_robux)
                VALUES ('2026-03-08', '2026-03-08T04:30:00+00', 'evt-1',
                        'Item', 'Buyer', 10)
            """)
        print("PASS sales instant/date identity and event dedup preserved")


if __name__ == "__main__":
    unittest.main(verbosity=2)
