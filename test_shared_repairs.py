"""Regression tests for shared repairs (no database, no network)."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import search_visibility as sv


class _Resp429:
    status_code = 429


class _Session429:
    def get(self, *a, **k):
        return _Resp429()


class _RespEmpty:
    status_code = 200

    def json(self):
        return {"data": [], "nextPageCursor": None}


class _SessionEmpty:
    def get(self, *a, **k):
        return _RespEmpty()


def test_fetch_query_429_sets_error():
    rows, pages, status, error = sv._fetch_query(_Session429(), "query")
    assert status == "failed"
    assert error == "HTTP 429 rate limited", error
    print("PASS visibility 429 error capture")


def test_fetch_query_empty_is_completed():
    rows, pages, status, error = sv._fetch_query(_SessionEmpty(), "query")
    assert status == "completed" and rows == [] and error is None
    print("PASS visibility empty completed")


if __name__ == "__main__":
    test_fetch_query_429_sets_error()
    test_fetch_query_empty_is_completed()
    print("ALL SHARED REPAIR TESTS PASSED")
