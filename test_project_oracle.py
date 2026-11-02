"""Project ORACLE Phase 1 tests (offline; additive subsystem)."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import creator_tracker
import trend_cohorts as tc
import trend_radar as tr


class FakeCur:
    def __init__(self, one=None, all_rows=None, fail_insert=False):
        self.one = one
        self.all_rows = list(all_rows or [])
        self.calls = []
        self.fail_insert = fail_insert
        self.rowcount = 1
        self.connection = self
        self.committed = 0
        self.rolled_back = 0

    def execute(self, sql, params=None):
        s = " ".join(str(sql).split())
        self.calls.append((s, params))
        if self.fail_insert and s.upper().startswith("INSERT"):
            raise RuntimeError("simulated insert failure")

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.all_rows.pop(0) if self.all_rows else []

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1


def test_cohorts_freeze_and_counts():
    now = datetime.now(timezone.utc)
    cur = FakeCur(one=(1,))
    out = tc.build_cohorts(cur, period_start=now - timedelta(days=90),
                           period_end=now)
    assert out["frozen"] is True
    assert not any(c[0].upper().startswith("INSERT") for c in cur.calls)
    print("PASS cohort freezing (existing cohort is not reselected)")

    orig = (tc.select_elite, tc.select_emerging, tc.select_control)
    tc.select_elite = lambda cur_, limit=50: [
        {"creator_id": i, "score": 1.0, "reason": "elite"} for i in range(50)]
    tc.select_emerging = lambda cur_, limit=25, exclude=None: [
        {"creator_id": 100 + i, "score": 0.5, "reason": "emerging"}
        for i in range(25)]
    tc.select_control = lambda cur_, limit=25, exclude=None, seed="oracle-v1": [
        {"creator_id": 200 + i, "score": None, "reason": "control"}
        for i in range(25)]
    try:
        cur = FakeCur(one=(0,))
        out = tc.build_cohorts(cur, force=True)
        assert out["counts"] == {"ELITE": 50, "EMERGING": 25, "CONTROL": 25}
        inserts = [c for c in cur.calls if c[0].upper().startswith("INSERT")]
        assert len(inserts) == 100
        assert all("ON CONFLICT (COHORT_ID, CREATOR_ID) DO NOTHING" in c[0].upper()
                   for c in inserts)
        print("PASS cohort selection counts + unique constraint")
    finally:
        tc.select_elite, tc.select_emerging, tc.select_control = orig


def test_cohort_rollback():
    orig = (tc.select_elite, tc.select_emerging, tc.select_control)
    tc.select_elite = lambda cur_, limit=50: [
        {"creator_id": 1, "score": 1.0, "reason": "elite"}]
    tc.select_emerging = lambda cur_, limit=25, exclude=None: []
    tc.select_control = lambda cur_, limit=25, exclude=None, seed="x": []
    try:
        cur = FakeCur(one=(0,), fail_insert=True)
        out = tc.build_cohorts(cur, force=True)
        assert "error" in out and out["frozen"] is False
        assert cur.rolled_back == 1
        print("PASS cohort insert failure rolls back")
    finally:
        tc.select_elite, tc.select_emerging, tc.select_control = orig


def test_discovery_timestamps():
    now = datetime.now(timezone.utc)
    items = [
        {"id": 1, "created_at": now - timedelta(days=2)},
        {"id": 2, "created_at": now - timedelta(days=45)},
        {"id": 3, "created_at": None},
    ]
    fresh = creator_tracker.filter_recent_assets(items, max_age_days=30, now=now)
    assert [i["id"] for i in fresh] == [1]
    print("PASS creation-date filter (actual timestamps, missing excluded)")

    pages = [
        {"data": [{"id": 10, "name": "A", "favoriteCount": 5,
                   "itemCreatedUtc": "2026-10-30T10:00:00Z",
                   "assetType": 8}], "nextPageCursor": "next"},
        {"data": [{"id": 11, "name": "B", "favoriteCount": 2,
                   "itemCreatedUtc": "2026-10-29T10:00:00Z",
                   "assetType": 8}], "nextPageCursor": None},
    ]
    original = creator_tracker._get_json
    creator_tracker._get_json = lambda s, p: pages.pop(0) if pages else None
    try:
        out = creator_tracker.search_creator_complete(
            object(), 123, max_pages=1)
        assert out["truncated"] is True and out["pages"] == 1
        assert out["items"][0]["created_at"].year == 2026
        print("PASS pagination truncation + itemCreatedUtc preserved")
    finally:
        creator_tracker._get_json = original


def test_observations_append_only():
    cur = FakeCur()
    item = {"id": 7, "creator_id": 9, "name": "Pose", "description": "d",
            "price": 5, "favorites": None, "created_at": None,
            "favorite_data_status": "unknown"}
    tr.record_observation(cur, 42, item)
    sql = cur.calls[-1][0].upper()
    assert "INSERT INTO TREND_ITEM_OBSERVATIONS" in sql
    assert "ON CONFLICT (SCAN_RUN_ID, ITEM_ID) DO NOTHING" in sql
    assert "UPDATE" not in " ".join(c[0].upper() for c in cur.calls)
    assert cur.calls[-1][1][4] is None  # unknown stays NULL, never 0
    item["favorites"] = 0
    item["favorite_data_status"] = "known"
    tr.record_observation(cur, 43, item)
    assert cur.calls[-1][1][4] == 0
    print("PASS append-only observations; unknown != zero")


def test_velocity_24h_and_windows():
    now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    obs = [
        {"observed_at": now - timedelta(days=30), "favorites": 50},
        {"observed_at": now - timedelta(days=7), "favorites": 80},
        {"observed_at": now - timedelta(days=3), "favorites": 90},
        {"observed_at": now - timedelta(days=1), "favorites": 120},
        {"observed_at": now, "favorites": 150},
    ]
    v = tr.compute_velocity(obs)
    assert v["available"] is True
    assert v["velocity_per_day"] == 30.0       # (150-120)/1 day
    assert v["windows"]["d3"]["delta"] == 60
    assert v["windows"]["d7"]["delta"] == 70
    assert v["windows"]["d30"]["delta"] == 100
    print("PASS 24h velocity + D3/D7/D30 windows")

    single = tr.compute_velocity([{"observed_at": now, "favorites": 10}])
    assert single["available"] is False and "insufficient" in single["reason"]
    missing = tr.compute_velocity([
        {"observed_at": now - timedelta(days=1), "favorites": None},
        {"observed_at": now, "favorites": 10},
    ])
    assert missing["available"] is False
    same_ts = tr.compute_velocity([
        {"observed_at": now, "favorites": 10},
        {"observed_at": now, "favorites": 12},
    ])
    assert same_ts["available"] is False and "24h" in same_ts["reason"]
    print("PASS insufficient coverage / unknown favorites / zero elapsed")


def test_observation_from_preserves_created_at():
    created = datetime(2026, 5, 1, tzinfo=timezone.utc)
    obs = tr.observation_from(
        {"id": 1, "creator_id": 2, "name": "Old", "created_at": created,
         "favorites": 5},
        {"name": "Renamed", "favorite_count": 10, "price": 50},
        scan_run_id=9, observed_at=datetime.now(timezone.utc))
    assert obs["created_at"] == created      # batch has no created timestamp
    assert obs["name"] == "Renamed"
    assert obs["favorites"] == 10 and obs["favorite_data_status"] == "known"
    print("PASS discovery timestamp preserved when merging batch data")


def test_existing_creator_system_intact():
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "commands_intel.py"), encoding="utf-8").read()
    for name in ('name="verified_scan"', 'name="creator_brain"'):
        assert name in src, name
    sched = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "scheduler.py"), encoding="utf-8").read()
    assert "verified_scan" in sched
    assert 'ORACLE_ENABLED' in sched
    for fn in ("search_creator", "discover_verified", "run_batch",
               "verify_creator_badge"):
        assert hasattr(creator_tracker, fn), fn
    print("PASS existing verified-creator commands, jobs, and tracker intact")


if __name__ == "__main__":
    test_cohorts_freeze_and_counts()
    test_cohort_rollback()
    test_discovery_timestamps()
    test_observations_append_only()
    test_velocity_24h_and_windows()
    test_observation_from_preserves_created_at()
    test_existing_creator_system_intact()
    print("ALL PROJECT ORACLE PHASE 1 TESTS PASSED")
