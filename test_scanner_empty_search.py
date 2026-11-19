"""Offline scanner regression: zero search IDs must not disable ID stepping."""
import os
from unittest.mock import patch

# scanner.py validates presence of one cookie at import time. No network access
# occurs in these tests; do not load or print production cookies.
os.environ.setdefault("ROBLOSECURITY_COOKIE", "offline-test-not-a-real-cookie")
import scanner


class Cursor:
    def __init__(self):
        self.rowcount = 0
    def close(self):
        pass


class Connection:
    def __init__(self):
        self.cursor_obj = Cursor()
        self.commits = 0
        self.rollbacks = 0
    def cursor(self):
        return self.cursor_obj
    def commit(self):
        self.commits += 1
    def rollback(self):
        self.rollbacks += 1
    def close(self):
        pass


def test_search_empty_still_runs_bounded_id_stepper():
    conn = Connection()
    with (patch.object(scanner, "setup_database"),
          patch.object(scanner, "build_all_queries", return_value=[]),
          patch.object(scanner, "get_db_connection", return_value=conn),
          patch.object(scanner, "scan_id_window",
                       return_value=(4000000, 2, 28)) as stepping,
          patch.object(scanner, "execute_values") as insert):
        result = scanner.run_scanner()
    assert stepping.call_count == 1
    assert insert.call_count == 0
    assert conn.commits == 1
    assert result["search_ids_found"] == 0
    assert result["id_window_start"] == 4000000
    assert result["id_window_upserted"] == 2


def test_search_results_persist_then_id_window_runs():
    conn = Connection()
    def do_insert(cur, sql, rows, **kwargs):
        assert "ON CONFLICT" in sql
        cur.rowcount = len(rows)
    with (patch.object(scanner, "setup_database"),
          patch.object(scanner, "build_all_queries", return_value=[{"keyword": "test"}]),
          patch.object(scanner, "scan_query", return_value={1234567, 2345678}),
          patch.object(scanner, "get_db_connection", return_value=conn),
          patch.object(scanner, "execute_values", side_effect=do_insert),
          patch.object(scanner, "scan_id_window",
                       return_value=(4000000, 1, 29)) as stepping):
        result = scanner.run_scanner()
    assert stepping.call_count == 1
    assert result["search_ids_found"] == 2
    assert result["search_ids_inserted"] == 2
    assert conn.commits == 2


def test_search_empty_and_id_window_failure_reported_not_silently_successful():
    conn = Connection()
    with (patch.object(scanner, "setup_database"),
          patch.object(scanner, "build_all_queries", return_value=[]),
          patch.object(scanner, "get_db_connection", return_value=conn),
          patch.object(scanner, "scan_id_window",
                       side_effect=RuntimeError("temporary endpoint failure"))):
        result = scanner.run_scanner()
    assert result["id_window_upserted"] == 0
    assert result["id_window_start"] is None
    assert conn.rollbacks == 1


if __name__ == "__main__":
    test_search_empty_still_runs_bounded_id_stepper()
    test_search_results_persist_then_id_window_runs()
    test_search_empty_and_id_window_failure_reported_not_silently_successful()
    print("PASS scanner zero-results independent ID-window fallback")
