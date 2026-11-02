"""Project ORACLE Phase 2 worker tests (offline, mocked network/DB)."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import oracle_worker as ow

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


class FakeStore:
    def __init__(self, cohort_rows, types, error_creators=None,
                 fail_creator_types=False):
        self.cohort_rows = cohort_rows
        self.types = types
        self.error_creators = set(error_creators or [])
        self.fail_creator_types = fail_creator_types
        self.observations = {}      # item_id -> [row dicts]
        self.inserted = []
        self.too_recent = 0
        self.locked = False
        self.released = False
        self.scan_runs = []
        self.updates = []
        self.commits = []
        self.rollbacks = []

    # lock/lifecycle
    def try_lock(self):
        self.locked = True
        return True

    def release_lock(self):
        self.released = True

    def close(self):
        pass

    def latest_cohort(self):
        return "ORACLE-20261101", self.cohort_rows

    def creator_types(self, ids):
        if self.fail_creator_types:
            raise RuntimeError("simulated fatal cohort-type lookup failure")
        return {cid: self.types[cid] for cid in ids if cid in self.types}

    def create_scan_run(self, ref):
        rid = 100 + len(self.scan_runs)
        self.scan_runs.append({"scan_run_id": rid, "ref": ref})
        return rid

    def insert_for_creator(self, creator_id, items, scan_run_id):
        if creator_id in self.error_creators:
            self.rollbacks.append(creator_id)
            raise RuntimeError("forced failure")
        counts = {"inserted": 0, "too_recent": 0}
        for it in items:
            iid = it["id"]
            prev = self.observations.get(iid, [])
            if prev:
                hours = (NOW - prev[-1]["observed_at"]).total_seconds() / 3600.0
                if hours < 1.0:
                    self.too_recent += 1
                    counts["too_recent"] += 1
                    continue
            baseline = next((r for r in reversed(prev)
                             if r["favorites"] is not None), None)
            favs = it.get("favorite_count")
            delta = hours_since = velocity = None
            if baseline:
                hours_since = round(
                    (NOW - baseline["observed_at"]).total_seconds() / 3600.0, 4)
                if favs is not None:
                    delta = favs - baseline["favorites"]
                if (delta is not None and hours_since is not None
                        and hours_since >= 0.5):
                    velocity = round(delta / (hours_since / 24.0), 3)
            row = {
                "item_id": iid, "creator_id": creator_id,
                "observed_at": NOW, "scan_run_id": scan_run_id,
                "favorites": favs,
                "title": it.get("name"), "description": it.get("description"),
                "price": None if it.get("price_missing") else it.get("price"),
                "created_at": it.get("created_at"),
                "item_type": it.get("item_type"),
                "sales_count": None,
                "favorites_delta": delta,
                "hours_since_last": hours_since,
                "favorites_velocity": velocity,
                "favorite_data_status": ("known" if favs is not None
                                         else "missing"),
            }
            self.observations.setdefault(iid, []).append(row)
            self.inserted.append(row)
            counts["inserted"] += 1
        self.commits.append(creator_id)
        return counts

    def update_scan_run(self, scan_run_id, summary):
        self.updates.append(dict(summary))


def make_worker(store, search_map=None, batch_items=None, failed=None,
                search_calls=None, batch_calls=None):
    search_map = search_map or {}
    batch_items = batch_items or {}
    failed = failed or {}
    search_calls = search_calls if search_calls is not None else []
    batch_calls = batch_calls if batch_calls is not None else []

    def search_fn(session, cid, creator_type="User", max_pages=4):
        search_calls.append({"creator_id": cid, "creator_type": creator_type,
                             "max_pages": max_pages})
        val = search_map.get(cid, [])
        if isinstance(val, Exception):
            raise val
        if isinstance(val, dict):
            return val
        return {"creator_id": cid, "items": val,
                "pages": (len(val) + 29) // 30, "truncated": False}

    def batch_fn(ids, **kwargs):
        batch_calls.append(list(ids))
        return (dict(batch_items), dict(failed))

    return dict(store=store, search_fn=search_fn, batch_fn=batch_fn,
                session_fn=lambda: object())


def enable(monkeypatch=None):
    os.environ["ORACLE_ENABLED"] = "1"


def disable():
    os.environ.pop("ORACLE_ENABLED", None)


def item(iid, name="Super Saiyan Battle Pose", favorites=10,
         length_delta_days=0, created_days_ago=5, price=65, price_missing=False):
    return {"id": iid, "name": name, "description": "desc",
            "favorite_count": favorites, "asset_type_id": 61,
            "price": price, "price_missing": price_missing,
            "created_at": NOW - timedelta(days=created_days_ago)}


def base_setup():
    rows = [(1, "ELITE", "User"), (2, "EMERGING", "User"),
            (2, "EMERGING", "User"), (3, "CONTROL", None)]
    types = {1: "User", 2: "User"}
    return rows, types


def test_t1_flag_gate():
    disable()
    store = FakeStore(*base_setup())
    out = ow.run_oracle_scan(**make_worker(store))
    assert out["status"] == "disabled" and out["scanned"] == 0
    assert store.locked is False and not store.inserted
    print("T1 PASS disabled gate, no writes, no exit")


def test_t2_first_observation_nulls():
    enable()
    rows, types = base_setup()
    store = FakeStore(rows, types)
    w = make_worker(store, search_map={1: [item(501)]},
                    batch_items={501: item(501)})
    out = ow.run_oracle_scan(**w)
    row = store.inserted[0]
    assert row["favorites_delta"] is None
    assert row["hours_since_last"] is None
    assert row["favorites_velocity"] is None
    print("T2 PASS first observation deltas are NULL")


def test_t3_six_hour_velocity():
    enable()
    rows, types = base_setup()
    store = FakeStore(rows, types)
    store.observations[501] = [{
        "favorites": 100, "observed_at": NOW - timedelta(hours=6)}]
    w = make_worker(store, search_map={1: [item(501, favorites=130)]},
                    batch_items={501: item(501, favorites=130)})
    ow.run_oracle_scan(**w)
    row = store.inserted[0]
    assert row["favorites_delta"] == 30
    assert row["hours_since_last"] == 6.0
    assert row["favorites_velocity"] == 120.0  # favorites per day
    print("T3 PASS 6h delta/velocity in favorites/day")


def test_t4_too_recent_skip():
    enable()
    rows, types = base_setup()
    store = FakeStore(rows, types)
    store.observations[501] = [{
        "favorites": 100, "observed_at": NOW - timedelta(minutes=45)}]
    w = make_worker(store, search_map={1: [item(501)]},
                    batch_items={501: item(501)})
    out = ow.run_oracle_scan(**w)
    assert out["skipped_too_recent"] == 1
    assert not store.inserted
    print("T4 PASS 45-minute-old observation skipped")


def test_t5_null_favorites_and_baseline():
    enable()
    rows, types = base_setup()
    store = FakeStore(rows, types)
    store.observations[501] = [{
        "favorites": 50, "observed_at": NOW - timedelta(hours=6)}]
    w = make_worker(store, search_map={1: [item(501, favorites=None)]},
                    batch_items={501: item(501, favorites=None)})
    ow.run_oracle_scan(**w)
    row = store.inserted[-1]
    assert row["favorites"] is None and row["favorites_delta"] is None
    assert row["favorite_data_status"] == "missing"
    print("T5 PASS NULL favorites inserted, delta NULL")


def test_t6_sales_count_always_null():
    enable()
    rows, types = base_setup()
    store = FakeStore(rows, types)
    w = make_worker(store, search_map={1: [item(501)]},
                    batch_items={501: item(501)})
    ow.run_oracle_scan(**w)
    assert all(r["sales_count"] is None for r in store.inserted)
    print("T6 PASS sales_count always NULL")


def test_t7_price_missing():
    enable()
    rows, types = base_setup()
    store = FakeStore(rows, types)
    w = make_worker(store, search_map={1: [item(501)]},
                    batch_items={501: item(501, price=0, price_missing=True)})
    ow.run_oracle_scan(**w)
    assert store.inserted[0]["price"] is None
    print("T7 PASS missing price stored NULL, not 0")


def test_t8_error_isolation():
    enable()
    rows, types = base_setup()
    store = FakeStore(rows, types, error_creators={1})
    w = make_worker(store, search_map={1: [item(501)], 2: [item(502)]},
                    batch_items={501: item(501), 502: item(502)})
    out = ow.run_oracle_scan(**w)
    assert out["status"] == "partial" and out["creators_errored"] == 1
    assert 2 in store.commits and 1 in store.rollbacks
    assert any(r["item_id"] == 502 for r in store.inserted)
    print("T8 PASS one creator error isolated, scan partial")


def test_t9_single_batch_call():
    enable()
    rows, types = base_setup()
    store = FakeStore(rows, types)
    calls = []
    w = make_worker(store, search_map={1: [item(501)], 2: [item(502)]},
                    batch_items={501: item(501), 502: item(502)},
                    batch_calls=calls)
    ow.run_oracle_scan(**w)
    assert len(calls) == 1
    print("T9 PASS shared batch client called exactly once")


def test_t10_discovery_created_at_preserved():
    enable()
    rows, types = base_setup()
    store = FakeStore(rows, types)
    created = NOW - timedelta(days=7)
    disc = item(501)
    disc["created_at"] = created
    batch = item(501)
    batch["created_at"] = None  # normalizer drops it
    w = make_worker(store, search_map={1: [disc]}, batch_items={501: batch},
                    search_calls=[])
    ow.run_oracle_scan(**w)
    assert store.inserted[0]["created_at"] == created
    print("T10 PASS discovery created_at attached despite normalizer")


def test_t11_truncation_flag():
    enable()
    rows, types = base_setup()
    store = FakeStore(rows, types)
    # The discovery API reports a remaining cursor even when a page is short.
    response = {"creator_id": 1, "items": [item(600)],
                "pages": 4, "truncated": True}
    w = make_worker(store, search_map={1: response},
                    batch_items={600: item(600)})
    out = ow.run_oracle_scan(**w)
    assert out["truncated_creators"]["1"]["reason"] == "page_cap_reached"
    assert out["status"] == "partial"
    print("T11 PASS exact API truncation flag makes scan partial")


def test_t12_failed_id_rate_limited():
    enable()
    rows, types = base_setup()
    store = FakeStore(rows, types)
    w = make_worker(store, search_map={1: [item(501)]},
                    batch_items={}, failed={501: "429"})
    out = ow.run_oracle_scan(**w)
    assert out["skipped_rate_limited"] == 1
    assert not store.inserted
    print("T12 PASS failed ID counted rate-limited, no zero observation")


def test_t13_rollback_isolation():
    enable()
    rows, types = base_setup()
    store = FakeStore(rows, types, error_creators={2})
    w = make_worker(store, search_map={1: [item(501)], 2: [item(502)]},
                    batch_items={501: item(501), 502: item(502)})
    ow.run_oracle_scan(**w)
    assert 2 in store.rollbacks and any(r["item_id"] == 501
                                        for r in store.inserted)
    assert not any(r["item_id"] == 502 for r in store.inserted)
    print("T13 PASS failed creator rolled back, others committed")


def test_t14_latest_cohort_dedup_counts():
    enable()
    rows, types = base_setup()  # creator 2 duplicated
    store = FakeStore(rows, types)
    w = make_worker(store)
    out = ow.run_oracle_scan(**w)
    assert out["cohort_snapshot_ref"] == "ORACLE-20261101"
    assert out["creators_eligible"] == 3
    assert out["per_cohort"] == {"elite": 1, "emerging": 1, "control": 1}
    print("T14 PASS latest cohort, deduped, accurate counts")


def test_t15_unknown_creator_type_skipped():
    enable()
    rows, types = base_setup()  # creator 3 has no type
    store = FakeStore(rows, types)
    calls = []
    w = make_worker(store, search_calls=calls)
    out = ow.run_oracle_scan(**w)
    assert out["skipped_unknown_type"] == 1
    assert all(c["creator_id"] != 3 for c in calls)
    assert out["status"] == "partial"
    print("T15 PASS unknown creator_type skipped and scan marked partial")


def test_t16_scan_run_id_shared():
    enable()
    rows, types = base_setup()
    store = FakeStore(rows, types)
    w = make_worker(store, search_map={1: [item(501)], 2: [item(502)]},
                    batch_items={501: item(501), 502: item(502)})
    out = ow.run_oracle_scan(**w)
    assert {r["scan_run_id"] for r in store.inserted} == {out["scan_run_id"]}
    print("T16 PASS every observation shares the run's scan_run_id")


def test_t17_existing_systems_regression():
    import creator_tracker
    import commands_intel
    src = open(commands_intel.__file__, encoding="utf-8").read()
    assert 'name="verified_scan"' in src and 'name="creator_brain"' in src
    for fn in ("search_creator", "search_creator_complete",
               "run_batch", "discover_verified"):
        assert hasattr(creator_tracker, fn)
    sched = open(os.path.join(os.path.dirname(creator_tracker.__file__),
                              "scheduler.py"), encoding="utf-8").read()
    assert "verified_scan_" in sched
    print("T17 PASS existing creator commands/tracker/scheduler intact")


def test_t18_fatal_run_is_finalized():
    enable()
    rows, types = base_setup()
    store = FakeStore(rows, types, fail_creator_types=True)
    out = ow.run_oracle_scan(**make_worker(store))
    assert out["status"] == "failed"
    assert store.scan_runs and store.scan_runs[0]["scan_run_id"] == out["scan_run_id"]
    assert store.updates and store.updates[-1]["status"] == "failed"
    assert store.updates[-1]["error_summary"]["fatal"]
    print("T18 PASS fatal scan updates trend_scan_runs to failed")


def test_t19_manual_module_entrypoint():
    import subprocess
    env = os.environ.copy()
    env.pop("ORACLE_ENABLED", None)
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run(
        [sys.executable, "-m", "oracle_worker"],
        cwd=repo_root, env=env, text=True, capture_output=True, timeout=15
    )
    assert proc.returncode == 0, proc.stderr
    assert '"status": "disabled"' in proc.stdout
    print("T19 PASS python oracle_worker.py executes safely with feature disabled")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_t")]
    for t in tests:
        t()
    print(f"ALL {len(tests)} ORACLE WORKER TESTS PASSED")
