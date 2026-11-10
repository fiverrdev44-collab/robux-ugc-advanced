"""Disposable-PostgreSQL tests for release/preflight.sql UTC-day correctness."""
import os
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_phase2_pg_integration import open_test_connection  # noqa: E402

ROOT = Path(__file__).resolve().parent
PREFLIGHT = (ROOT / "release" / "preflight.sql").read_text(encoding="utf-8")
START = PREFLIGHT.index("-- 3. UTC duplicate snapshot days")
END = PREFLIGHT.index("-- 4. Current daily index")
DUPLICATE_SQL = PREFLIGHT[START:END]


class PreflightUtcDayTests(unittest.TestCase):
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

    def _schema(self, column_type):
        schema = "preflight_" + uuid.uuid4().hex[:10]
        self.cur.execute(f'CREATE SCHEMA "{schema}"')
        self.cur.execute(f'SET search_path TO "{schema}"')
        self.cur.execute(f"""
            CREATE TABLE item_history (
                id SERIAL PRIMARY KEY,
                item_id BIGINT,
                snapshot_at {column_type}
            )
        """)
        return schema

    def _seed(self, timestamps):
        for item_id, value in timestamps:
            self.cur.execute(
                "INSERT INTO item_history (item_id, snapshot_at) VALUES (%s, %s)",
                (item_id, value))

    def _duplicates(self):
        self.cur.execute(DUPLICATE_SQL)
        return self.cur.fetchall()

    def test_legacy_timestamp_under_non_utc_sessions(self):
        schema = self._schema("TIMESTAMP")
        try:
            # Same UTC day, different local dates under some sessions.
            self._seed([
                (1, "2026-03-08 00:30:00"),
                (1, "2026-03-08 23:30:00"),
                (2, "2026-03-08 23:30:00"),
                (2, "2026-03-09 00:30:00"),
            ])
            expected = None
            for tz in ("-05:00", "+05:30", "GMT"):
                self.cur.execute(f"SET TIME ZONE '{tz}'")
                rows = self._duplicates()
                if expected is None:
                    expected = rows
                assert rows == expected, (tz, rows, expected)
                assert rows == [(1, __import__("datetime").date(2026, 3, 8), 2)]
        finally:
            self.cur.execute("SET TIME ZONE 'GMT'")
            self.cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
        print("PASS legacy TIMESTAMP UTC-day check is session-independent")

    def test_timestamptz_under_non_utc_sessions(self):
        schema = self._schema("TIMESTAMPTZ")
        try:
            self._seed([
                (1, "2026-03-08 00:30:00+00"),
                (1, "2026-03-08 23:30:00+00"),
                (2, "2026-03-08 23:30:00+00"),
                (2, "2026-03-09 00:30:00+00"),
                (3, "2026-03-08 23:30:00-05:00"),  # Mar 9 UTC
                (3, "2026-03-09 04:30:00+00"),
            ])
            expected = None
            for tz in ("-05:00", "+05:30", "GMT"):
                self.cur.execute(f"SET TIME ZONE '{tz}'")
                rows = self._duplicates()
                if expected is None:
                    expected = rows
                assert rows == expected, (tz, rows, expected)
                assert (1, __import__("datetime").date(2026, 3, 8), 2) in rows
                assert (3, __import__("datetime").date(2026, 3, 9), 2) in rows
        finally:
            self.cur.execute("SET TIME ZONE 'GMT'")
            self.cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
        print("PASS TIMESTAMPTZ UTC-day check is session-independent")

    def test_sales_preflight_supports_legacy_and_migrated_tables(self):
        start = PREFLIGHT.index("-- 7. Sales identity/duplicate inventory.")
        end = PREFLIGHT.index("-- 8. Migration-readiness markers.")
        statements = [s.strip() for s in PREFLIGHT[start:end].split(";") if s.strip()]
        self.assertEqual(len(statements), 3)
        for transaction_column in (False, True):
            schema = "preflight_sales_" + uuid.uuid4().hex[:10]
            self.cur.execute(f'CREATE SCHEMA "{schema}"')
            try:
                self.cur.execute(f'SET search_path TO "{schema}"')
                extra_column = ", transaction_id TEXT" if transaction_column else ""
                self.cur.execute(
                    "CREATE TABLE my_sales ("
                    "source_event_id TEXT, sale_time TIMESTAMPTZ"
                    + extra_column + ")"
                )
                if transaction_column:
                    self.cur.execute(
                        "INSERT INTO my_sales (source_event_id, transaction_id) "
                        "VALUES ('event-a', 'txn-a'), ('event-b', 'txn-a')"
                    )
                else:
                    self.cur.execute(
                        "INSERT INTO my_sales (source_event_id) "
                        "VALUES ('event-a'), ('event-b')"
                    )
                for statement in statements:
                    self.cur.execute(statement)
                    self.cur.fetchall()
                self.assertEqual(self.cur.rowcount, 0)
            finally:
                self.cur.execute("SET search_path TO public")
                self.cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
        print("PASS sales preflight supports missing and present transaction_id")

    def test_preflight_remains_read_only(self):
        stripped = PREFLIGHT.upper()
        for keyword in ("INSERT ", "UPDATE ", "DELETE ", "ALTER ",
                        "CREATE ", "DROP ", "TRUNCATE ", "VACUUM "):
            assert keyword not in stripped, keyword
        assert "CASE" in PREFLIGHT and "pg_typeof" in PREFLIGHT
        print("PASS preflight remains read-only and type-aware")


if __name__ == "__main__":
    unittest.main(verbosity=2)
