"""Disposable PostgreSQL tests for F-07/F-08 creator identity migrations.

Runs only when PHASE2_TEST_DATABASE_URL is configured for a disposable test
database. All rows are synthetic; no production connection is attempted.
"""
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_phase2_pg_integration import open_test_connection  # noqa: E402

ROOT = Path(__file__).resolve().parent
MIGRATIONS = ROOT / "migrations"


def _migration(name):
    return (MIGRATIONS / name).read_text(encoding="utf-8")


class CreatorIdentityPostgresTests(unittest.TestCase):
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
        self.schema = "f07_" + uuid.uuid4().hex[:12]
        self.cur.execute(f'CREATE SCHEMA "{self.schema}"')
        self.cur.execute(f'SET search_path TO "{self.schema}"')
        self.cur.execute("""
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
                creator_type TEXT DEFAULT 'User',
                creator_name TEXT,
                verified BOOLEAN DEFAULT TRUE,
                last_scanned TIMESTAMPTZ,
                added_at TIMESTAMPTZ DEFAULT now()
            );
            CREATE TABLE item_history (
                id SERIAL PRIMARY KEY,
                item_id BIGINT,
                favorite_count INTEGER,
                total_sales INTEGER,
                price INTEGER,
                snapshot_at TIMESTAMPTZ
            );
            CREATE TABLE trend_creator_cohorts (
                id bigserial PRIMARY KEY,
                cohort_id text NOT NULL,
                creator_id bigint NOT NULL,
                cohort_type text NOT NULL
                    CHECK (cohort_type IN ('ELITE', 'EMERGING', 'CONTROL')),
                selected_at timestamptz NOT NULL DEFAULT now(),
                selection_score double precision,
                selection_reason text,
                cohort_period_start timestamptz NOT NULL,
                cohort_period_end timestamptz NOT NULL,
                UNIQUE (cohort_id, creator_id)
            );
            CREATE TABLE trend_item_observations (
                id bigserial PRIMARY KEY,
                item_id bigint NOT NULL,
                creator_id bigint,
                observed_at timestamptz NOT NULL DEFAULT now(),
                scan_run_id bigint NOT NULL,
                favorites integer,
                title text,
                description text,
                price integer,
                created_at timestamptz,
                favorite_data_status text NOT NULL DEFAULT 'unknown',
                UNIQUE (scan_run_id, item_id)
            );
        """)

    def tearDown(self):
        try:
            self.cur.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
        except Exception:
            pass

    def apply_creator_migrations(self):
        self.cur.execute(_migration(
            "2026-11-05_creator_registry.sql"))
        self.cur.execute(_migration(
            "2026-11-08_f07_creator_identity_expand.sql"))
        self.cur.execute(_migration(
            "2026-11-08_f07_creator_identity_contract.sql"))
        self.cur.execute(_migration(
            "2026-11-02_project_oracle_phase1.sql"))
        self.cur.execute(_migration(
            "2026-11-02_project_oracle_phase2.sql"))
        self.cur.execute(_migration(
            "2026-11-08_f07_oracle_identity_additive.sql"))

    def test_empty_tables_upgrade_and_migrations_are_idempotent(self):
        self.apply_creator_migrations()
        self.apply_creator_migrations()  # idempotent rehearsal
        self.cur.execute("""
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            WHERE c.conrelid = 'tracked_creators'::regclass
              AND c.contype = 'p'
        """)
        assert self.cur.fetchone()[0] == \
            "PRIMARY KEY (creator_type, creator_id)"
        self.cur.execute("""
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            WHERE c.conrelid = 'trend_creator_cohorts'::regclass
              AND c.contype = 'u'
              AND pg_get_constraintdef(c.oid) = 'UNIQUE (cohort_id, creator_id)'
        """)
        assert self.cur.fetchone() is None
        print("PASS empty upgrade + idempotent migrations")

    def test_legacy_rows_preserved_and_collisions_coexist(self):
        old = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.cur.execute("""
            INSERT INTO tracked_creators
              (creator_id, creator_type, creator_name, verified, last_scanned)
            VALUES
              (123, 'User', 'StarWorks', TRUE, %s),
              (456, NULL, 'Mystery', TRUE, %s),
              (789, 'Group', 'GroupCo', TRUE, NULL)
        """, (old, old))
        self.apply_creator_migrations()
        self.cur.execute("""
            SELECT creator_id, creator_type, type_provenance, last_scanned
            FROM tracked_creators ORDER BY creator_id
        """)
        rows = self.cur.fetchall()
        by_id = {r[0]: r for r in rows}
        assert by_id[456][1] == "unknown"
        assert by_id[456][2] == "legacy_unknown"
        assert by_id[123][2] == "legacy_stored"
        assert by_id[123][3] == old

        # Composite identity permits User 123 and Group 123 to coexist.
        self.cur.execute("""
            INSERT INTO tracked_creators
              (creator_id, creator_type, creator_name, verified)
            VALUES (123, 'Group', 'StarWorks Group', TRUE)
        """)
        self.cur.execute("""
            SELECT count(*) FROM tracked_creators WHERE creator_id = 123
        """)
        assert self.cur.fetchone()[0] == 2
        with self.assertRaises(Exception):
            self.cur.execute("""
                INSERT INTO tracked_creators
                  (creator_id, creator_type, creator_name, verified)
                VALUES (123, 'User', 'duplicate', TRUE)
            """)
        print("PASS legacy preservation + User/Group collision coexistence")

    def test_tracking_updates_only_intended_typed_creator(self):
        self.apply_creator_migrations()
        import creator_tracker as ct
        self.cur.execute("""
            INSERT INTO tracked_creators
              (creator_id, creator_type, creator_name, verified)
            VALUES (123, 'User', 'U', TRUE), (123, 'Group', 'G', TRUE)
        """)
        added = ct.ensure_creators(
            self.cur, {(123, "User"): "U", (123, "Group"): "G"})
        assert added == 0
        ct.mark_scanned(self.cur, 123, "User")
        self.cur.execute("""
            SELECT creator_type, last_scanned FROM tracked_creators
            WHERE creator_id = 123 ORDER BY creator_type
        """)
        rows = self.cur.fetchall()
        assert rows[0][0] == "Group" and rows[0][1] is None
        assert rows[1][0] == "User" and rows[1][1] is not None
        assert ct.pick_batch(self.cur, limit=10)
        print("PASS mark_scanned updates only the typed identity")

    def test_creator_brain_typed_cohorts_and_coverage(self):
        self.apply_creator_migrations()
        import creator_brain
        now = datetime.now(timezone.utc)
        rows = [
            (1, "Shrine One", 100, 100, "User", 100, "StarWorks"),
            (2, "Shrine Two", 80, 100, "User", 100, "Renamed Studio"),
            (3, "City One", 10, 100, "Group", 200, "StarWorks"),
            (4, "City Two", 20, 100, "Group", 200, "STARWORKS"),
            (5, "Unknown", 999, 100, None, 300, "StarWorks"),
        ]
        for iid, name, favs, price, ctype, cid, cname in rows:
            self.cur.execute("""
                INSERT INTO items
                  (id, name, description, favorite_count, price,
                   creator_name, creator_id, creator_type, creator_verified,
                   asset_type_id, created_at, fetched_at)
                VALUES (%s, %s, '', %s, %s, %s, %s, %s, TRUE, 8, %s, now())
            """, (iid, name, favs, price, cname, cid, ctype,
                  now - timedelta(days=10)))
        cohort = creator_brain.build_cohort(
            self.cur, min_items=1, top_n=10, has_type=True)
        assert len(cohort) == 2
        identities = {(r[0], r[1]) for r in cohort}
        assert identities == {("User", 100), ("Group", 200)}
        comparison = creator_brain.build_comparison_cohorts(
            self.cur, min_items=1, has_type=True)
        assert comparison["creators"] == 2
        assert comparison["selection"]["identity_key"] == \
            "(creator_type, creator_id)"
        findings = creator_brain.learn(
            self.cur, min_items=1, top_n=10, has_type=True)
        assert findings["cohort_size"] == 2
        assert findings["median_favs"] == 50
        cov = findings["identity_coverage"]
        assert cov["typed_items"] == 4 and cov["unresolved_items"] == 1
        assert cov["typed_coverage_pct"] == 80.0
        print("PASS Creator Brain typed cohorts, medians and coverage")

    def test_oracle_typed_collision_and_observation_type(self):
        self.apply_creator_migrations()
        import trend_cohorts as tc
        import trend_radar as tr
        now = datetime.now(timezone.utc)
        for i in range(5):
            self.cur.execute("""
                INSERT INTO items
                  (id, name, favorite_count, creator_id, creator_type,
                   created_at)
                VALUES (%s, %s, %s, 123, 'User', %s), 
                       (%s, %s, %s, 123, 'Group', %s)
            """, (100 + i, f"u{i}", 100 + i, now - timedelta(days=40),
                  200 + i, f"g{i}", 50 + i, now - timedelta(days=40)))
        elite = tc.select_elite(self.cur, limit=10)
        keys = {r["creator_key"] for r in elite}
        assert "User:123" in keys and "Group:123" in keys

        tr.record_observation(
            self.cur, 77, {"id": 100, "creator_id": 123,
                           "creator_type": "User", "favorites": 5})
        self.cur.execute("""
            SELECT creator_id, creator_type FROM trend_item_observations
            WHERE scan_run_id = 77
        """)
        assert self.cur.fetchone() == (123, "User")

        # After the migration, both typed rows can share a cohort period.
        self.cur.execute("""
            INSERT INTO trend_creator_cohorts
              (cohort_id, creator_id, creator_type, creator_key, cohort_type,
               cohort_period_start, cohort_period_end)
            VALUES
              ('C1', 123, 'User', 'User:123', 'ELITE', now(), now()),
              ('C1', 123, 'Group', 'Group:123', 'CONTROL', now(), now())
        """)
        import oracle_worker
        store = oracle_worker.PostgresStore(
            db_factory=lambda: self.conn)
        ref, rows = store.latest_cohort()
        assert ref == "C1"
        assert {(r[2]) for r in rows} == {"User", "Group"}
        types = store.creator_types([("User", 123), ("Group", 123)])
        assert types[("User", 123)] == "User"
        assert types[("Group", 123)] == "Group"
        print("PASS ORACLE typed collision and observation type")


if __name__ == "__main__":
    unittest.main(verbosity=2)
