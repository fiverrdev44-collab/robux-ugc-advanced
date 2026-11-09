"""Release migration-manifest rehearsal on disposable PostgreSQL.

Applies the ordered release migrations to realistic legacy fixtures, verifies
data preservation after each critical phase, and re-runs the manifest for
idempotency.
"""
import json
import os
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_phase2_pg_integration import open_test_connection  # noqa: E402

ROOT = Path(__file__).resolve().parent
MIGRATIONS = [
    "2026-11-01_items_name_lower_trim_index.sql",
    "2026-11-02_astra_tables.sql",
    "2026-11-02_astra_outcomes.sql",
    "2026-11-02_project_oracle_phase1.sql",
    "2026-11-02_project_oracle_phase2.sql",
    "2026-11-03_sales_integrity_columns.sql",
    "2026-11-05_creator_registry.sql",
    "2026-11-05_golden_hour_indexes.sql",
    "2026-11-08_f07_creator_identity_expand.sql",
    "2026-11-08_f07_oracle_identity_additive.sql",
    "2026-11-08_f07_creator_identity_contract.sql",
    "2026-11-08_f10_timestamp_integrity.sql",
]


class ReleaseMigrationManifestTests(unittest.TestCase):
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
        self.schema = "release_" + uuid.uuid4().hex[:10]
        self.cur.execute(f'CREATE SCHEMA "{self.schema}"')
        self.cur.execute(f'SET search_path TO "{self.schema}"')
        self.cur.execute("""
            CREATE TABLE items (
                id BIGINT PRIMARY KEY, name TEXT, description TEXT,
                favorite_count INTEGER, price INTEGER, total_sales INTEGER,
                creator_name TEXT, creator_id BIGINT, creator_verified BOOLEAN,
                asset_type_id INTEGER, created_at TIMESTAMP,
                updated_at TIMESTAMP, fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE item_history (
                id SERIAL PRIMARY KEY, item_id BIGINT,
                favorite_count INTEGER, total_sales INTEGER, price INTEGER,
                snapshot_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX idx_item_history_daily
                ON item_history (item_id, (snapshot_at::date));
            CREATE TABLE tracked_creators (
                creator_id BIGINT PRIMARY KEY,
                creator_type TEXT DEFAULT 'User',
                creator_name TEXT, verified BOOLEAN DEFAULT TRUE,
                last_scanned TIMESTAMP, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE creator_patterns (
                pattern_key TEXT PRIMARY KEY, pattern_value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE predictor_weights (
                id SERIAL PRIMARY KEY, model_version TEXT, weights JSONB,
                trained_on_count INTEGER, accuracy DOUBLE PRECISION,
                trained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE my_sales (
                id SERIAL PRIMARY KEY, sale_date DATE, sale_time TIMESTAMPTZ,
                item_name TEXT, buyer TEXT, amount_robux INTEGER, status TEXT,
                source_event_id TEXT, source TEXT
            );
        """)
        self.cur.execute("""
            INSERT INTO items
              (id, name, description, favorite_count, price, total_sales,
               creator_name, creator_id, creator_verified, asset_type_id,
               created_at, updated_at, fetched_at)
            VALUES
              (1, 'Moonlit Background', 'scene', 120, 150, 0,
               'StarWorks', 123, TRUE, 92,
               '2026-03-08 01:30:00', '2026-03-08 02:00:00',
               '2026-03-08 02:15:00'),
              (2, 'Neon Background', 'scene', 40, 80, 0,
               'GroupCo', 456, TRUE, 92,
               '2026-12-31 23:30:00', NULL, NULL)
        """)
        self.cur.execute("""
            INSERT INTO item_history (item_id, snapshot_at)
            VALUES (1, '2026-03-08 23:30:00'),
                   (1, '2026-03-09 00:30:00'),
                   (2, '2026-03-09 01:30:00')
        """)
        self.cur.execute("""
            INSERT INTO tracked_creators
              (creator_id, creator_type, creator_name, verified, last_scanned)
            VALUES
              (123, 'User', 'StarWorks', TRUE, '2026-03-08 01:30:00'),
              (456, NULL, 'Mystery', TRUE, '2026-03-08 01:30:00'),
              (789, 'Group', 'GroupCo', TRUE, NULL)
        """)
        self.cur.execute("""
            INSERT INTO creator_patterns (pattern_key, pattern_value)
            VALUES ('oracle_recovery',
                    '{"cohort_id":"C1","completed":["User:123"],"remaining":[]}')
        """)
        self.cur.execute("""
            INSERT INTO predictor_weights
              (model_version, weights, trained_on_count, accuracy)
            VALUES ('v1', '{}', 10, 0.5)
        """)
        self.cur.execute("""
            INSERT INTO my_sales
              (sale_date, sale_time, item_name, buyer, amount_robux,
               status, source_event_id, source)
            VALUES ('2026-03-08', '2026-03-08T10:00:00+05:30',
                    'Moonlit Background', 'Buyer One', 10, 'Complete',
                    'txn:roblox:legacy-1', 'discord')
        """)

    def tearDown(self):
        try:
            self.cur.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
        except Exception:
            pass

    def _apply(self, name):
        conn = open_test_connection()
        conn.autocommit = True
        try:
            cur = conn.cursor()
            cur.execute(f'SET search_path TO "{self.schema}"')
            cur.execute((ROOT / "migrations" / name).read_text(encoding="utf-8"))
            cur.close()
        finally:
            conn.close()

    def _factory(self):
        conn = open_test_connection()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(f'SET search_path TO "{self.schema}"')
        cur.close()
        return conn

    def _apply_through(self, last_name):
        for name in MIGRATIONS:
            self._apply(name)
            if name == last_name:
                return

    def test_manifest_order_preserves_data_and_integrity(self):
        # Prerequisites through ORACLE phase 2, then seed legacy ORACLE rows.
        self._apply_through("2026-11-02_project_oracle_phase2.sql")
        self.cur.execute("""
            INSERT INTO trend_creator_cohorts
              (cohort_id, creator_id, creator_type, cohort_type,
               selection_score, selection_reason, cohort_period_start,
               cohort_period_end)
            VALUES ('C1', 123, 'User', 'ELITE', 1.0, 'legacy',
                    now() - interval '30 days', now())
        """)
        self.cur.execute("""
            INSERT INTO trend_item_observations
              (item_id, creator_id, observed_at, scan_run_id, favorites,
               title, favorite_data_status)
            VALUES (1, 123, now() - interval '1 day', 7, 120,
                    'Moonlit Background', 'known')
        """)

        self._apply("2026-11-03_sales_integrity_columns.sql")
        self._apply("2026-11-05_creator_registry.sql")
        self._apply("2026-11-05_golden_hour_indexes.sql")
        self._apply("2026-11-08_f07_creator_identity_expand.sql")
        # Expand phase is additive/compatible with the old PK.
        self.cur.execute("""
            SELECT creator_id, creator_type, type_provenance, last_scanned
            FROM tracked_creators ORDER BY creator_id
        """)
        rows = self.cur.fetchall()
        assert rows[0][1] == "User" and rows[0][3] is not None
        assert rows[1][1] == "unknown" and rows[1][2] == "legacy_unknown"
        assert rows[2][1] == "Group"

        self._apply("2026-11-08_f07_oracle_identity_additive.sql")
        self._apply("2026-11-08_f07_creator_identity_contract.sql")
        self._apply("2026-11-08_f10_timestamp_integrity.sql")

        # Composite creator identity permits the same numeric ID across types.
        self.cur.execute("""
            INSERT INTO tracked_creators
              (creator_id, creator_type, creator_name, verified)
            VALUES (123, 'Group', 'StarWorks Group', TRUE)
        """)
        self.cur.execute(
            "SELECT count(*) FROM tracked_creators WHERE creator_id=123")
        assert self.cur.fetchone()[0] == 2

        # Existing values and row counts survive timestamp conversion.
        self.cur.execute("""
            SELECT count(*), max(fetched_at) FROM items
        """)
        item_count, fetched = self.cur.fetchone()
        assert item_count == 2 and fetched is not None
        self.cur.execute(
            "SELECT created_at AT TIME ZONE 'UTC' FROM items WHERE id=1")
        assert self.cur.fetchone()[0].isoformat() == "2026-03-08T01:30:00"
        self.cur.execute("SELECT count(*) FROM item_history")
        assert self.cur.fetchone()[0] == 3
        self.cur.execute(
            "SELECT pg_get_indexdef(to_regclass('idx_item_history_daily'))")
        assert "AT TIME ZONE" in self.cur.fetchone()[0]

        # Existing ORACLE data is preserved and can now represent both types.
        self.cur.execute("""
            SELECT cohort_id, creator_id, creator_type, creator_key
            FROM trend_creator_cohorts
            WHERE cohort_id='C1' AND cohort_type='ELITE'
        """)
        cohort = self.cur.fetchone()
        assert cohort[:3] == ("C1", 123, "User")
        assert cohort[3] == "User:123"
        self.cur.execute("""
            INSERT INTO trend_creator_cohorts
              (cohort_id, creator_id, creator_type, creator_key, cohort_type,
               cohort_period_start, cohort_period_end)
            VALUES ('C1', 123, 'Group', 'Group:123', 'CONTROL', now(), now())
        """)
        self.cur.execute("""
            SELECT count(*) FROM trend_creator_cohorts WHERE creator_id=123
        """)
        assert self.cur.fetchone()[0] == 2
        self.cur.execute("""
            SELECT creator_id, favorites FROM trend_item_observations
            WHERE scan_run_id=7
        """)
        assert self.cur.fetchone() == (123, 120)

        # Sales history and recovery payload remain unchanged.
        self.cur.execute("""
            SELECT sale_date, sale_time AT TIME ZONE 'UTC', source_event_id,
                   item_name, buyer, amount_robux
            FROM my_sales WHERE source_event_id='txn:roblox:legacy-1'
        """)
        sale = self.cur.fetchone()
        assert sale[0].isoformat() == "2026-03-08"
        assert sale[1].isoformat() == "2026-03-08T04:30:00"
        assert sale[2:] == ("txn:roblox:legacy-1", "Moonlit Background",
                            "Buyer One", 10)
        self.cur.execute("""
            SELECT pattern_value FROM creator_patterns
            WHERE pattern_key='oracle_recovery'
        """)
        payload = json.loads(self.cur.fetchone()[0])
        assert payload["completed"] == ["User:123"]
        self.cur.execute("""
            SELECT data_type FROM information_schema.columns
            WHERE table_schema=current_schema()
              AND table_name='creator_patterns' AND column_name='updated_at'
        """)
        assert self.cur.fetchone()[0] == "timestamp with time zone"

        # Astra and sales-integrity migrations are present.
        for table in ("astra_runs", "astra_outcomes"):
            self.cur.execute("SELECT to_regclass(%s)", (table,))
            assert self.cur.fetchone()[0] is not None
        self.cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema=current_schema() AND table_name='my_sales'
              AND column_name IN ('transaction_id', 'embed_index', 'buyer_id')
        """)
        assert {r[0] for r in self.cur.fetchall()} == {
            "transaction_id", "embed_index", "buyer_id"}

        print("PASS ordered manifest preserves catalog, ORACLE, sales, recovery")

    def test_manifest_is_rerunnable_where_designed(self):
        self._apply_through(MIGRATIONS[-1])
        counts = {}
        for table in ("items", "item_history", "tracked_creators",
                      "trend_creator_cohorts", "trend_item_observations",
                      "my_sales", "creator_patterns"):
            self.cur.execute(f"SELECT count(*) FROM {table}")
            counts[table] = self.cur.fetchone()[0]
        # Re-run the entire manifest, including the CONCURRENTLY index.
        self._apply_through(MIGRATIONS[-1])
        for table, before in counts.items():
            self.cur.execute(f"SELECT count(*) FROM {table}")
            assert self.cur.fetchone()[0] == before, table
        print("PASS manifest re-run is idempotent for data counts")

    def test_application_read_paths_work_after_manifest(self):
        self._apply_through(MIGRATIONS[-1])
        import creator_brain
        import creator_tracker as ct
        import oracle_worker as ow
        import sales_listener as sl
        import trend_radar as tr

        self.cur.execute("""
            UPDATE items SET creator_type='User', creator_verified=TRUE
            WHERE creator_id IN (123, 456)
        """)
        cohort = creator_brain.build_cohort(
            self.cur, min_items=1, top_n=10, has_type=True)
        assert cohort

        self.cur.execute("""
            INSERT INTO trend_creator_cohorts
              (cohort_id, creator_id, creator_type, creator_key, cohort_type,
               cohort_period_start, cohort_period_end)
            VALUES ('C1', 123, 'User', 'User:123', 'ELITE', now(), now())
        """)
        batch = ct.pick_batch(self.cur, limit=10)
        assert batch and all(row[1] in ("User", "Group") for row in batch)

        store = ow.PostgresStore(db_factory=self._factory)
        try:
            _ref, rows = store.latest_cohort()
            assert rows
        finally:
            store.close()

        tr.record_observation(
            self.cur, 99, {"id": 1, "creator_id": 123,
                           "creator_type": "User", "favorites": 5})
        tr.record_observation(
            self.cur, 99, {"id": 1, "creator_id": 123,
                           "creator_type": "User", "favorites": 5})
        self.cur.execute("""
            SELECT count(*) FROM trend_item_observations WHERE scan_run_id=99
        """)
        assert self.cur.fetchone()[0] == 1

        # A validated sale can be inserted; an unvalidated one is refused.
        sale = {
            "sale_date": datetime(2026, 3, 8, tzinfo=timezone.utc).date(),
            "sale_time": datetime(2026, 3, 8, 4, 30, tzinfo=timezone.utc),
            "item_name": "release-fixture", "buyer": "buyer",
            "amount_robux": 10, "status": "Complete",
            "source_event_id": "txn:roblox:release-1", "source": "discord",
        }
        sl._mark_source_validated(sale, "webhook")
        assert sl._insert_sale(self.cur, sale) is True
        assert sl._insert_sale(self.cur, dict(sale)) is False
        print("PASS application read/write paths work after manifest")


if __name__ == "__main__":
    unittest.main(verbosity=2)
