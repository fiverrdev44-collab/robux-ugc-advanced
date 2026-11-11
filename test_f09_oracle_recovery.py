"""F-09 ORACLE discovery recovery and scan-continuity tests (offline)."""
import os
import sys
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ROBLOSECURITY_COOKIE", "test-cookie")

import creator_tracker as ct  # noqa: E402
import oracle_worker as ow  # noqa: E402
import safe_roblox  # noqa: E402
import scanner  # noqa: E402
import roblox_batch_client as rbc  # noqa: E402

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def _item(item_id, favorites=10):
    return {
        "id": item_id,
        "name": f"Item {item_id}",
        "description": "",
        "favorite_count": favorites,
        "asset_type_id": 61,
        "price": 10,
        "created_at": NOW - timedelta(days=5),
    }


class Response:
    def __init__(self, status=200, payload=None, headers=None,
                 json_error=False, error=None):
        self.status_code = status
        self.payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.json_error = json_error
        self.error = error

    def json(self):
        if self.json_error:
            raise ValueError("invalid json")
        return self.payload


class RecoveryStore:
    """In-memory store whose persistence survives a simulated restart."""

    def __init__(self, rows, types, state=None):
        self.rows = rows
        self.types = types
        self.state = state if state is not None else {
            "persisted": None,
            "scan_runs": [],
            "observations": {},
            "seen": set(),
            "duplicates": 0,
            "commits": [],
            "rollbacks": [],
            "released": False,
            "locked": False,
            "updates": [],
            "fail_creators": set(),
        }

    def try_lock(self):
        self.state["locked"] = True
        return True

    def release_lock(self):
        self.state["released"] = True

    def close(self):
        pass

    def latest_cohort(self):
        return "C1", list(self.rows)

    def creator_types(self, keys):
        return {k: self.types[k] for k in keys if k in self.types}

    def create_scan_run(self, ref):
        rid = 100 + len(self.state["scan_runs"])
        self.state["scan_runs"].append(
            {"scan_run_id": rid, "ref": ref, "status": "running"})
        return rid

    def mark_scan_running(self, scan_run_id):
        for run in self.state["scan_runs"]:
            if run["scan_run_id"] == scan_run_id:
                run["status"] = "running"

    def update_scan_run(self, scan_run_id, summary):
        self.state["updates"].append(dict(summary))
        for run in self.state["scan_runs"]:
            if run["scan_run_id"] == scan_run_id:
                run["status"] = summary["status"]

    def load_recovery_state(self):
        return self.state["persisted"]

    def save_recovery_state(self, payload):
        self.state["persisted"] = dict(payload)
        return True

    def clear_recovery_state(self):
        self.state["persisted"] = None
        return True

    def insert_for_creator(self, creator_type, creator_id, items, scan_run_id):
        if creator_id in self.state["fail_creators"]:
            self.state["rollbacks"].append((creator_type, creator_id))
            raise RuntimeError("simulated creator transaction failure")
        counts = {"inserted": 0, "too_recent": 0}
        for item in items:
            key = (scan_run_id, item["id"])
            if key in self.state["seen"]:
                self.state["duplicates"] += 1
                continue
            self.state["seen"].add(key)
            row = dict(item)
            row["scan_run_id"] = scan_run_id
            row["creator_type"] = creator_type
            row["creator_id"] = creator_id
            self.state["observations"].setdefault(item["id"], []).append(row)
            counts["inserted"] += 1
        self.state["commits"].append((creator_type, creator_id))
        return counts


def _complete_search(calls=None):
    calls = calls if calls is not None else []

    def search(session, cid, creator_type=None, max_pages=4):
        calls.append((cid, creator_type))
        return {
            "creator_id": cid, "creator_type": creator_type,
            "items": [_item(cid * 10 + 1)], "pages": 1,
            "truncated": False, "complete": True, "status": "complete",
            "error": None, "retry_after": None, "partial": False,
        }
    search.calls = calls
    return search


def _batch(ids):
    return ({int(i): _item(int(i)) for i in ids}, {})


def _run(store, search, batch=None, session_fn=None):
    os.environ["ORACLE_ENABLED"] = "1"
    try:
        return ow.run_oracle_scan(
            store=store, search_fn=search, batch_fn=batch or _batch,
            session_fn=session_fn or (lambda: object()))
    finally:
        os.environ.pop("ORACLE_ENABLED", None)


def _base_rows():
    return [(123, "ELITE", "User"), (456, "EMERGING", "User"),
            (789, "CONTROL", "Group")]


def _base_types():
    return {("User", 123): "User", ("User", 456): "User",
            ("Group", 789): "Group"}


def test_discovery_outcomes_preserve_partial_pages():
    def run_with(responses, max_pages=4):
        with mock.patch.object(ct, "safe_get", side_effect=responses):
            return ct.search_creator_complete(
                object(), 123, creator_type="User", max_pages=max_pages)

    complete = run_with([Response(200, {
        "data": [{"id": 1, "name": "A", "creatorType": "User"}],
        "nextPageCursor": None})])
    assert complete["status"] == "complete" and complete["complete"]
    assert len(complete["items"]) == 1

    partial = run_with([
        Response(200, {"data": [{"id": 1, "name": "A"}],
                       "nextPageCursor": "next"}),
        Response(429, {}, {"Retry-After": "5"}),
    ])
    assert partial["status"] == "rate_limited"
    assert partial["partial"] is True and len(partial["items"]) == 1
    assert partial["retry_after"] == 5.0

    future = format_datetime(
        datetime.now(timezone.utc) + timedelta(seconds=30), usegmt=True)
    dated = run_with([
        Response(200, {"data": [{"id": 1, "name": "A"}],
                       "nextPageCursor": "next"}),
        Response(429, {}, {"Retry-After": future}),
    ])
    assert dated["status"] == "rate_limited"
    assert dated["retry_after"] and dated["retry_after"] > 0

    with mock.patch.object(ct, "shared_circuit_open", return_value=True):
        deferred = ct.search_creator_complete(
            object(), 123, creator_type="User")
    assert deferred["status"] == "deferred"

    with mock.patch.object(ct, "safe_get",
                           side_effect=TimeoutError("timed out")):
        timeout = ct.search_creator_complete(
            object(), 123, creator_type="User")
    assert timeout["status"] == "timeout"

    invalid = run_with([Response(200, {"unexpected": True})])
    assert invalid["status"] == "invalid_response"

    cap = run_with([Response(200, {
        "data": [{"id": 1, "name": "A"}],
        "nextPageCursor": "next"})], max_pages=1)
    assert cap["status"] == "page_cap_reached" and cap["truncated"]
    print("PASS discovery outcome contract preserves valid pages")


def test_all_creators_complete_normally():
    state = {}
    store = RecoveryStore(_base_rows(), _base_types())
    calls = []
    out = _run(store, _complete_search(calls))
    assert out["status"] == "success"
    assert out["creators_completed"] == 3
    assert out["creators_attempted"] == 3
    assert out["coverage_pct"] == 100.0
    assert len(calls) == 3
    assert len(store.state["observations"]) == 3
    assert store.state["persisted"] is None
    print("PASS all creators complete normally")


def test_first_middle_and_final_creator_rate_limits():
    ordered_rows = [(123, "ELITE", "User"), (456, "EMERGING", "User"),
                    (789, "CONTROL", "User")]
    ordered_types = {("User", 123): "User", ("User", 456): "User",
                     ("User", 789): "User"}
    for fail_at, expected_completed, expected_remaining in (
            (123, 0, 3), (456, 1, 2), (789, 2, 1)):
        def search(session, cid, creator_type=None, max_pages=4):
            if cid == fail_at:
                return {"status": "rate_limited", "items": [_item(cid * 10 + 1)],
                        "pages": 1, "complete": False, "partial": True,
                        "error": "rate limited (429)", "retry_after": 5,
                        "creator_id": cid, "creator_type": creator_type}
            return {"status": "complete", "items": [_item(cid * 10 + 1)],
                    "pages": 1, "complete": True, "partial": False,
                    "error": None, "retry_after": None,
                    "creator_id": cid, "creator_type": creator_type}
        store = RecoveryStore(ordered_rows, ordered_types)
        out = _run(store, search)
        assert out["status"] == "partial"
        assert out["creators_completed"] == expected_completed
        assert out["creators_unprocessed"] == expected_remaining
        assert out["deferred"] is True
        assert store.state["persisted"] is not None
        assert len(store.state["persisted"]["remaining"]) == expected_remaining
    print("PASS first/middle/final creator rate limits defer accurately")


def test_circuit_open_before_discovery_stops_requests():
    store = RecoveryStore(_base_rows(), _base_types())
    calls = []
    with mock.patch.object(ow, "shared_circuit_open", return_value=True):
        out = _run(store, _complete_search(calls))
    assert out["status"] == "partial"
    assert out["deferred"] is True
    assert out["creators_attempted"] == 0
    assert not calls
    assert store.state["persisted"]["reason"] == "circuit_open"
    print("PASS open circuit before discovery issues no requests")


def test_circuit_opens_during_pagination_and_preserves_partial():
    def search(session, cid, creator_type=None, max_pages=4):
        if cid == 456:
            return {"status": "deferred", "items": [_item(4561)],
                    "pages": 1, "complete": False, "partial": True,
                    "error": "circuit open", "retry_after": 30,
                    "creator_id": cid, "creator_type": creator_type}
        return {"status": "complete", "items": [_item(cid * 10 + 1)],
                "pages": 1, "complete": True, "partial": False,
                "error": None, "retry_after": None,
                "creator_id": cid, "creator_type": creator_type}
    store = RecoveryStore(
        [(123, "ELITE", "User"), (456, "EMERGING", "User"),
         (789, "CONTROL", "User")],
        {("User", 123): "User", ("User", 456): "User",
         ("User", 789): "User"})
    out = _run(store, search)
    assert out["status"] == "partial"
    assert out["creators_completed"] == 1
    assert out["creators_unprocessed"] == 2
    assert 4561 in store.state["observations"]
    assert store.state["persisted"]["remaining"] == ["User:456", "User:789"]
    print("PASS circuit during pagination preserves partial results")


def test_timeout_invalid_response_and_page_cap():
    def search(session, cid, creator_type=None, max_pages=4):
        if cid == 123:
            return {"status": "timeout", "items": [], "pages": 1,
                    "complete": False, "partial": False, "error": "TimeoutError",
                    "retry_after": None, "creator_id": cid,
                    "creator_type": creator_type}
        if cid == 456:
            return {"status": "invalid_response", "items": [], "pages": 1,
                    "complete": False, "partial": False, "error": "bad JSON",
                    "retry_after": None, "creator_id": cid,
                    "creator_type": creator_type}
        return {"status": "page_cap_reached", "items": [_item(7891)],
                "pages": 4, "truncated": True, "complete": False,
                "partial": True, "error": "page cap", "retry_after": None,
                "creator_id": cid, "creator_type": creator_type}
    store = RecoveryStore(_base_rows(), _base_types())
    out = _run(store, search, batch=lambda ids: (
        {int(i): _item(int(i)) for i in ids}, {}))
    assert out["status"] == "partial"
    assert out["creators_unprocessed"] >= 1
    assert "discovery:User:456" in out["error_summary"]
    assert "Group:789" in out["truncated_creators"]
    assert out["creators_incomplete"] >= 1
    print("PASS timeout, invalid response and page cap are distinct")


def test_rate_limit_is_bounded_and_not_retried_immediately():
    calls = []

    def search(session, cid, creator_type=None, max_pages=4):
        calls.append((cid, creator_type))
        if cid == 123:
            return {"status": "rate_limited", "items": [], "pages": 0,
                    "complete": False, "partial": False,
                    "error": "rate limited (429)", "retry_after": 45,
                    "creator_id": cid, "creator_type": creator_type}
        return {"status": "complete", "items": [_item(cid * 10 + 1)],
                "pages": 1, "complete": True, "partial": False,
                "error": None, "retry_after": None,
                "creator_id": cid, "creator_type": creator_type}
    store = RecoveryStore(
        [(123, "ELITE", "User"), (456, "EMERGING", "User"),
         (789, "CONTROL", "User")],
        {("User", 123): "User", ("User", 456): "User",
         ("User", 789): "User"})
    out = _run(store, search)
    assert out["rate_limited_requests"] == 1
    assert len(calls) == 1  # no immediate retry or remaining creators
    assert out["creators_unprocessed"] == 3
    assert out["deferred"] is True
    print("PASS 429 stops requests and respects the shared circuit")


def test_recovery_after_circuit_expiry_and_restart():
    rows = [(123, "ELITE", "User"), (456, "EMERGING", "User"),
            (789, "CONTROL", "User")]
    types = {("User", 123): "User", ("User", 456): "User",
             ("User", 789): "User"}
    state = {
        "persisted": None, "scan_runs": [], "observations": {}, "seen": set(),
        "duplicates": 0, "commits": [], "rollbacks": [], "released": False,
        "locked": False, "updates": [], "fail_creators": set(),
    }
    first_store = RecoveryStore(rows, types, state)

    def limited_search(session, cid, creator_type=None, max_pages=4):
        if cid == 456:
            return {"status": "rate_limited", "items": [_item(4561)],
                    "pages": 1, "complete": False, "partial": True,
                    "error": "rate limited (429)", "retry_after": 5,
                    "creator_id": cid, "creator_type": creator_type}
        return {"status": "complete", "items": [_item(cid * 10 + 1)],
                "pages": 1, "complete": True, "partial": False,
                "error": None, "retry_after": None,
                "creator_id": cid, "creator_type": creator_type}

    first = _run(first_store, limited_search)
    assert first["status"] == "partial"
    first_scan_id = first["scan_run_id"]
    assert state["persisted"]["completed"] == ["User:123"]

    # Simulated process restart: a new store object shares only durable state.
    second_store = RecoveryStore(rows, types, state)
    second = _run(second_store, _complete_search())
    assert second["scan_run_id"] == first_scan_id
    assert second["recovery_attempts"] == 1
    assert second["resumed_creators"] == 1
    assert second["status"] == "success"
    assert second["coverage_pct"] == 100.0
    assert state["persisted"] is None
    assert state["duplicates"] >= 1  # resumed creator items were deduplicated
    print("PASS recovery survives simulated restart and reuses scan run")


def test_duplicate_observations_are_prevented_during_resume():
    state = {
        "persisted": None, "scan_runs": [], "observations": {}, "seen": set(),
        "duplicates": 0, "commits": [], "rollbacks": [], "released": False,
        "locked": False, "updates": [], "fail_creators": set(),
    }
    rows = [(123, "ELITE", "User")]
    types = {("User", 123): "User"}
    first = RecoveryStore(rows, types, state)

    def partial(session, cid, creator_type=None, max_pages=4):
        return {"status": "rate_limited", "items": [_item(1231)],
                "pages": 1, "complete": False, "partial": True,
                "error": "rate limited", "retry_after": 5,
                "creator_id": cid, "creator_type": creator_type}

    _run(first, partial)
    assert len(state["observations"][1231]) == 1
    second = RecoveryStore(rows, types, state)
    _run(second, _complete_search())
    assert len(state["observations"][1231]) == 1
    assert state["duplicates"] >= 1
    print("PASS duplicate observations are prevented on resume")


def test_user_group_collision_and_unknown_type():
    rows = [(123, "ELITE", "User"), (123, "CONTROL", "Group"),
            (999, "EMERGING", None)]
    types = {("User", 123): "User", ("Group", 123): "Group"}
    store = RecoveryStore(rows, types)
    calls = []
    out = _run(store, _complete_search(calls))
    assert out["creators_eligible"] == 3
    assert out["creators_eligible_typed"] == 2
    assert out["creators_skipped_unknown"] == 1
    assert out["skipped_unknown_type"] == 1
    assert set(calls) == {(123, "User"), (123, "Group")}
    assert out["status"] == "partial"
    print("PASS User/Group 123 stay separate; unknown type is skipped")


def test_transaction_rollback_is_isolated_and_lock_released():
    store = RecoveryStore(_base_rows(), _base_types())
    store.state["fail_creators"] = {456}
    out = _run(store, _complete_search())
    assert out["status"] == "partial"
    assert out["creators_errored"] == 1
    assert (456, "User") in [(cid, t) for t, cid in
                             store.state["rollbacks"]] or store.state["rollbacks"]
    assert any(row["creator_id"] == 123
               for rows in store.state["observations"].values() for row in rows)
    assert store.state["released"] is True
    print("PASS creator transaction failure is isolated; lock released")

    fatal_store = RecoveryStore(_base_rows(), _base_types())
    with mock.patch.object(fatal_store, "creator_types",
                           side_effect=RuntimeError("fatal cohort lookup")):
        fatal = _run(fatal_store, _complete_search())
    assert fatal["status"] == "failed"
    assert fatal_store.state["released"] is True
    assert fatal_store.state["updates"][-1]["status"] == "failed"
    print("PASS fatal path finalizes scan and releases advisory lock")


def test_existing_budgets_and_no_rotation():
    assert safe_roblox._ENDPOINTS["catalog_search"]["rate_per_min"] == 30
    assert scanner.MAX_PAGES_PER_QUERY == 6
    assert rbc.MAX_BATCH == 30
    source = open("creator_tracker.py", encoding="utf-8").read()
    assert "rotating to cookie" not in source
    assert "session_idx" not in source

    sessions = []

    def session_fn():
        sessions.append(object())
        return sessions[-1]

    store = RecoveryStore(_base_rows(), _base_types())
    _run(store, _complete_search(), session_fn=session_fn)
    assert len(sessions) == 1
    print("PASS API budgets unchanged and no session rotation")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL {len(tests)} F-09 RECOVERY TESTS PASSED")
