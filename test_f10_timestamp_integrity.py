"""F-10 timestamp integrity tests (offline, deterministic)."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import creator_tracker as ct
import oracle_worker as ow
import sales_listener as sl
import trend_radar as tr
from time_utils import (
    UTC,
    age_days,
    db_utc,
    deadline_after,
    ensure_utc,
    utc_day,
    utc_now,
    within_window,
)


def test_aware_utc_and_naive_provenance():
    assert utc_now().tzinfo is UTC
    aware = datetime(2026, 3, 8, 12, 0, tzinfo=UTC)
    assert ensure_utc(aware) == aware
    assert ensure_utc(datetime(2026, 3, 8, 12, 0)) is None
    assert db_utc(datetime(2026, 3, 8, 12, 0)) == aware
    assert db_utc(None) is None
    print("PASS aware UTC, verified naive UTC, unknown naive")


def test_offsets_and_boundaries():
    plus = ensure_utc("2026-03-08T10:00:00+05:30")
    minus = ensure_utc("2026-03-08T00:30:00-08:00")
    assert plus == datetime(2026, 3, 8, 4, 30, tzinfo=UTC)
    assert minus == datetime(2026, 3, 8, 8, 30, tzinfo=UTC)

    day = ensure_utc("2026-03-08T23:30:00-08:00")
    assert utc_day(day).isoformat() == "2026-03-09"
    month = ensure_utc("2026-01-31T23:30:00-08:00")
    assert utc_day(month).isoformat() == "2026-02-01"
    year = ensure_utc("2026-12-31T23:30:00-08:00")
    assert utc_day(year).isoformat() == "2027-01-01"
    leap = ensure_utc("2024-02-29T23:30:00+00:00")
    assert utc_day(leap).isoformat() == "2024-02-29"
    print("PASS offsets, day/month/year boundaries and leap day")


def test_dst_offsets_are_explicit():
    # 2026-03-08 01:30 EST (-05:00) and 03:30 EDT (-04:00) are distinct
    # instants; a normalization must not invent or drop an hour.
    est = datetime(2026, 3, 8, 1, 30, tzinfo=timezone(timedelta(hours=-5)))
    edt = datetime(2026, 3, 8, 3, 30, tzinfo=timezone(timedelta(hours=-4)))
    assert ensure_utc(est) == datetime(2026, 3, 8, 6, 30, tzinfo=UTC)
    assert ensure_utc(edt) == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)
    assert ensure_utc(est) != ensure_utc(edt)
    print("PASS DST boundary offsets remain distinct")


def test_ordering_freshness_and_growth_windows():
    values = [
        ensure_utc("2026-03-08T10:00:00+05:30"),
        ensure_utc("2026-03-08T00:30:00-08:00"),
        ensure_utc("2026-03-09T00:00:00+00:00"),
    ]
    assert sorted(values) == [
        datetime(2026, 3, 8, 4, 30, tzinfo=UTC),
        datetime(2026, 3, 8, 8, 30, tzinfo=UTC),
        datetime(2026, 3, 9, 0, 0, tzinfo=UTC),
    ]
    now = datetime(2026, 3, 9, 12, 0, tzinfo=UTC)
    assert age_days(datetime(2026, 3, 8, 12, 0), now=now) == 1.0
    assert within_window(datetime(2026, 3, 8, 12, 0), 2, now=now)
    assert not within_window(datetime(2026, 3, 1, 12, 0), 2, now=now)
    print("PASS ordering, freshness and growth windows")


def test_experiment_deadline_and_recovery_timestamp():
    now = datetime(2026, 3, 8, 12, 0, tzinfo=UTC)
    assert deadline_after(7, now=now) == datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    payload = ow._recovery_payload(
        "C1", 7, ["User:1"], ["Group:2"], "partial", "rate_limited", now)
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)
    assert decoded["updated_at"].endswith("+00:00")
    assert decoded["remaining"] == ["Group:2"]
    assert ow._age_days(datetime(2026, 3, 7, 12, 0), now) == 1.0
    assert ow._age_days(datetime(2026, 3, 7, 12, 0, tzinfo=UTC), now) == 1.0
    print("PASS experiment deadlines and ORACLE recovery timestamps")


def test_sales_offsets_and_utc_date():
    a = sl._parse_datetime("2026-03-08T10:00:00+05:30")
    b = sl._parse_datetime("2026-03-08T08:30:00-08:00")
    assert a == datetime(2026, 3, 8, 4, 30, tzinfo=UTC)
    assert b == datetime(2026, 3, 8, 16, 30, tzinfo=UTC)
    assert a != b
    # The same instant expressed with different offsets normalizes equally.
    c = sl._parse_datetime("2026-03-08T00:30:00-04:00")
    d = sl._parse_datetime("2026-03-08T06:30:00+02:00")
    assert c == d == datetime(2026, 3, 8, 4, 30, tzinfo=UTC)
    assert a.date().isoformat() == "2026-03-08"
    print("PASS sales offsets normalize to UTC without changing identity")


def test_snapshot_observation_as_utc():
    aware = datetime(2026, 3, 8, 4, 30, tzinfo=UTC)
    naive = datetime(2026, 3, 8, 4, 30)
    assert tr._as_utc(aware) == aware
    assert tr._as_utc(naive) == aware
    assert tr._as_utc("2026-03-08T04:30:00+00:00") == aware
    print("PASS observation timestamps normalize to UTC")


def test_creator_cooldown_accepts_aware_and_legacy_naive():
    class Cur:
        def __init__(self, value):
            self.value = value

        def execute(self, *a, **k):
            pass

        def fetchone(self):
            return (self.value,)

    future = (utc_now() + timedelta(minutes=10)).isoformat()
    legacy = (utc_now() + timedelta(minutes=10)).replace(tzinfo=None).isoformat()
    assert ct._cooldown_remaining(Cur(future)) > 0
    assert ct._cooldown_remaining(Cur(legacy)) > 0
    assert ct._cooldown_remaining(Cur("not-a-date")) == 0
    print("PASS creator cooldown handles aware and UTC-session naive values")


def test_sql_contracts_use_explicit_utc():
    database = Path("database.py").read_text(encoding="utf-8")
    migration = Path(
        "migrations/2026-11-08_f10_timestamp_integrity.sql").read_text(
            encoding="utf-8")
    confidence = Path("confidence.py").read_text(encoding="utf-8")
    velocity = Path("market_velocity.py").read_text(encoding="utf-8")
    cohorts = Path("trend_cohorts.py").read_text(encoding="utf-8")
    assert "snapshot_at AT TIME ZONE 'UTC'" in database
    assert "AT TIME ZONE 'UTC'" in migration
    assert "idx_item_history_daily" in migration
    assert "duplicate item_history rows share a UTC calendar" in migration
    assert "created_at AT TIME ZONE 'UTC'" in confidence
    assert "sale_time AT TIME ZONE 'UTC'" in confidence
    assert "created_at AT TIME ZONE 'UTC'" in velocity
    assert "snapshot_at AT TIME ZONE 'UTC'" in cohorts
    print("PASS SQL contracts use explicit UTC expressions")


def test_migration_is_guarded_idempotent_and_rollback_documented():
    migration = Path(
        "migrations/2026-11-08_f10_timestamp_integrity.sql").read_text(
            encoding="utf-8")
    assert "CREATE OR REPLACE FUNCTION _f10_utc_column" in migration
    assert "timestamp without time zone" in migration
    assert "RAISE EXCEPTION" in migration
    assert "pg_get_indexdef" in migration
    assert "Rollback (manual" in migration
    assert "SET LOCAL TIME ZONE 'UTC'" in migration
    assert "DROP FUNCTION _f10_utc_column" in migration
    print("PASS migration is guarded, idempotent and rollback-documented")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL {len(tests)} F-10 TIMESTAMP TESTS PASSED")
