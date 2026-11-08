"""Disposable-PostgreSQL tests for F-09 ORACLE recovery persistence."""
import os
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_phase2_pg_integration import open_test_connection  # noqa: E402

ROOT = Path(__file__).resolve().parent
MIGRATIONS = ROOT / "migrations"


def _migration(name):
    return (MIGRATIONS / name).read_text(encoding="utf-8")


class OracleRecoveryPostgresTests(unittest.TestCase):
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
        self.schema = "f09_" + uuid.uuid4().hex[:12]
        self.cur.execute(f'CREATE SCHEMA "{self.schema}"')
        self.cur.execute(f'SET search_path TO "{self.schema}"')
        self.cur.execute("""
            CREATE TABLE items (
                id BIGINT PRIMARY KEY, name TEXT, description TEXT,
                favorite_count INTEGER, price INTEGER, total_sales INTEGER,
                creator_name TEXT, creator_id BIGINT, creator_verified BOOLEAN,
                asset_type_id INTEGER, created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ, fetched_at TIMESTAMPTZ,
                favorite_status TEXT
            );
            CREATE TABLE tracked_creators (
                creator_id BIGINT NOT NULL,
                creator_type TEXT NOT NULL DEFAULT 'unknown',
                creator_name TEXT, verified BOOLEAN DEFAULT TRUE,
                last_scanned TIMESTAMPTZ, added_at TIMESTAMPTZ DEFAULT now(),
                type_provenance TEXT,
                PRIMARY KEY (creator_type, creator_id)
            );
            CREATE TABLE creator_patterns (
                pattern_key TEXT PRIMARY KEY,
                pattern_value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        self.cur.execute(_migration("2026-11-05_creator_registry.sql"))
        self.cur.execute(_migration(
            "2026-11-02_project_oracle_phase1.sql"))
        self.cur.execute(_migration(
            "2026-11-02_project_oracle_phase2.sql"))
        self.cur.execute(_migration(
            "2026-11-08_f07_oracle_identity_additive.sql"))

    def tearDown(self):
        try:
            self.cur.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
        except Exception:
            pass

    def _factory(self):
        conn = open_test_connection()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(f'SET search_path TO "{self.schema}"')
        cur.close()
        return conn

    def _store(self, conn=None):
        import oracle_worker
        return oracle_worker.PostgresStore(
            db_factory=(lambda: conn) if conn is not None else self._factory)

    def test_recovery_state_survives_new_store_instance(self):
        store = self._store()
        state = {
            "cohort_id": "C1",
            "scan_run_id": 7,
            "completed": ["User:123"],
            "remaining": ["Group:123"],
            "status": "partial",
            "reason": "rate_limited",
        }
        try:
            assert store.save_recovery_state(state)
            restarted = self._store()
            try:
                assert restarted.load_recovery_state() == state
                assert restarted.clear_recovery_state()
                assert restarted.load_recovery_state() is None
            finally:
                restarted.close()
        finally:
            store.close()
        print("PASS recovery state survives store/process restart")

    def test_scan_reuse_and_observation_idempotency(self):
        import trend_radar as tr
        store = self._store()
        try:
            rid = store.create_scan_run("C1")
            store.mark_scan_running(rid)
            item = {"id": 1, "creator_id": 123, "creator_type": "User",
                    "favorites": 5, "name": "A"}
            tr.record_observation(self.cur, rid, item)
            tr.record_observation(self.cur, rid, item)
            self.cur.execute(
                "select count(*) from trend_item_observations "
                "where scan_run_id=%s", (rid,))
            assert self.cur.fetchone()[0] == 1
            summary = {
                "status": "partial", "cohort_snapshot_ref": "C1",
                "creators_eligible": 2, "creators_scanned": 1,
                "creators_errored": 0, "items_discovered": 1,
                "items_in_window": 1, "observations_inserted": 1,
                "skipped_too_recent": 0, "skipped_rate_limited": 1,
                "skipped_unavailable": 0, "skipped_unknown_type": 0,
                "truncated_creators": {},
                "error_summary": {"recovery": {"remaining": ["Group:123"]}},
            }
            store.update_scan_run(rid, summary)
            store.mark_scan_running(rid)
            self.cur.execute(
                "select status, finished_at from trend_scan_runs "
                "where scan_run_id=%s", (rid,))
            status, finished = self.cur.fetchone()
            assert status == "running" and finished is None
            self.cur.execute(
                "select count(*) from trend_item_observations "
                "where scan_run_id=%s", (rid,))
            assert self.cur.fetchone()[0] == 1
        finally:
            store.close()
        print("PASS scan-run reuse + duplicate observation prevention")

    def test_advisory_lock_release_after_exception_path(self):
        conn2 = self._factory()
        try:
            first = self._store()
            second = self._store(conn2)
            try:
                assert first.try_lock()
                assert second.try_lock() is False
                first.release_lock()
                assert second.try_lock() is True
                second.release_lock()
            finally:
                first.close()
        finally:
            conn2.close()
        print("PASS advisory lock released and reacquirable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
