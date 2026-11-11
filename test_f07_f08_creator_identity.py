"""F-07/F-08 creator identity integrity tests (offline, synthetic)."""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import creator_brain
import creator_identity as ci
import creator_tracker as ct
import oracle_worker as ow
import trend_cohorts as tc
import trend_radar as tr

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


class IdentityCursor:
    def __init__(self, composite=True, existing=None):
        self.composite = composite
        self.existing = set(existing or [])
        self.calls = []
        self.rowcount = 0
        self._one = None
        self._all = []
        self.connection = self

    def execute(self, sql, params=None):
        self.calls.append((str(sql), params))
        text = " ".join(str(sql).lower().split())
        if "pg_constraint" in text:
            self._one = (1,) if self.composite else None
        elif "select 1 from tracked_creators" in text:
            if "creator_type = %s and creator_id" in text:
                self._one = ((1,) if (params[0], params[1]) in self.existing
                             else None)
            else:
                self._one = ((1,) if any(cid == params[0]
                                         for _, cid in self.existing)
                             else None)
        elif "insert into tracked_creators" in text:
            cid, ctype = params[0], params[1]
            key = (ctype, cid)
            self.rowcount = 0 if key in self.existing else 1
            self.existing.add(key)
        elif "update tracked_creators" in text:
            self.rowcount = 1
        else:
            self.rowcount = 0

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


class StubCursor:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((str(sql), params))

    def fetchall(self):
        return self.results.pop(0) if self.results else []

    def fetchone(self):
        if not self.results:
            return None
        row = self.results.pop(0)
        return row[0] if isinstance(row, list) and row else row


def test_creator_identity_helpers():
    assert ci.normalize_creator_type(" user ") == "User"
    assert ci.normalize_creator_type("GROUP") == "Group"
    assert ci.normalize_creator_type("team") is None
    assert ci.stored_creator_type(None) == "unknown"
    assert ci.stored_creator_type("group") == "Group"
    assert ci.creator_key("User", 123) == "User:123"
    assert ci.creator_key("Group", 123) == "Group:123"
    assert ci.creator_key("User", 123) != ci.creator_key("Group", 123)
    assert ci.creator_key(None, 123) == "unknown:123"
    assert ci.parse_creator_key("Group:123") == ("Group", 123)
    assert ci.is_known_creator_type("User")
    assert not ci.is_known_creator_type("unknown")
    print("PASS composite identity helpers")


def test_ensure_creators_allows_user_group_same_numeric_id():
    cur = IdentityCursor(composite=True)
    added = ct.ensure_creators(
        cur, {(123, "User"): "StarWorks", (123, "Group"): "StarWorks"})
    assert added == 2
    assert ("User", 123) in cur.existing and ("Group", 123) in cur.existing
    inserts = [c for c in cur.calls
               if c[0].strip().lower().startswith("insert")]
    assert len(inserts) == 2
    assert all("on conflict (creator_type, creator_id)" in
               " ".join(c[0].lower().split()) for c in inserts)
    print("PASS User and Group 123 coexist")


def test_ensure_creators_is_idempotent_per_typed_identity():
    cur = IdentityCursor(composite=True)
    creators = {(123, "User"): "A", (123, "Group"): "B",
                (456, "User"): "C", (456, "Group"): "D"}
    assert ct.ensure_creators(cur, creators) == 4
    assert ct.ensure_creators(cur, creators) == 0
    print("PASS repeated discovery is idempotent per typed identity")


def test_unknown_type_is_not_silently_user():
    cur = IdentityCursor(composite=True)
    assert ct.ensure_creators(cur, {(900, None): "Mystery"}) == 1
    insert = next(c for c in cur.calls
                  if c[0].strip().lower().startswith("insert"))
    assert insert[1][1] == "unknown"
    assert insert[1][3] is False
    assert ct.search_creator(object(), 900, None) == []
    assert ct.verify_creator_badge(object(), 900, None) is None
    out = ct.search_creator_complete(object(), 900, None)
    assert out["items"] == [] and out["creator_type"] is None
    print("PASS unknown types are explicit and never default to User")


def test_discover_verified_keeps_both_types_and_skips_unknown():
    payload = {"data": [
        {"id": 1, "creatorTargetId": 123, "creatorType": "User",
         "creatorName": "StarWorks", "creatorHasVerifiedBadge": True},
        {"id": 2, "creatorTargetId": 123, "creatorType": "Group",
         "creatorName": "StarWorks", "creatorHasVerifiedBadge": True},
        {"id": 3, "creatorTargetId": 456, "creatorType": None,
         "creatorName": "Unknown", "creatorHasVerifiedBadge": True},
    ], "nextPageCursor": None}
    with mock.patch.object(ct, "_get_json", return_value=payload):
        found = ct.discover_verified(object(), keywords=("x",), pages=1)
    assert found == {(123, "User"): "StarWorks",
                     (123, "Group"): "StarWorks"}
    print("PASS discovery preserves User/Group collision and skips unknown")


def test_mark_scanned_is_typed_and_verified_state_is_preserved():
    cur = IdentityCursor(composite=True)
    ct.mark_scanned(cur, 123, "User")
    sql, params = cur.calls[-1]
    assert "creator_type = %s" in sql and "creator_id = %s" in sql
    assert params == ("User", 123)

    cur2 = IdentityCursor(composite=True)
    with mock.patch.object(ct, "verify_creator_badge", return_value=True):
        ct.ensure_creators(cur2, {(1, "User"): "Verified"}, session=object())
    verified_insert = next(c for c in cur2.calls
                           if c[0].strip().lower().startswith("insert"))
    assert verified_insert[1][3] is True

    cur3 = IdentityCursor(composite=True)
    with mock.patch.object(ct, "verify_creator_badge", return_value=False):
        assert ct.ensure_creators(
            cur3, {(2, "User"): "NotVerified"}, session=object()) == 0
    print("PASS typed scan updates and verified-state preservation")


def test_creator_brain_separates_same_display_name_and_renames():
    rows = [
        ("User", 100, "StarWorks", 10, 500, True),
        ("Group", 200, "StarWorks", 6, 100, False),
        ("User", 300, "STARWORKS", 5, 50, False),
    ]
    result = creator_brain.build_comparison_cohorts(
        StubCursor([rows]), min_items=1, has_type=True)
    assert result["creators"] == 3
    assert result["segments"]["established"]["creators"] == 3
    assert result["selection"]["identity_key"] == "(creator_type, creator_id)"
    sampled = result["sampled_identities"]["established"]
    assert len({(s["creator_type"], s["creator_id"]) for s in sampled}) == 3

    renamed = [("User", 100, "Renamed Studio", 12, 500, True)]
    cohort = creator_brain.build_cohort(
        StubCursor([renamed]), min_items=1, has_type=True)
    assert len(cohort) == 1
    assert cohort[0][0] == "User" and cohort[0][1] == 100
    print("PASS display-name collisions do not merge; rename keeps identity")


def test_creator_brain_medians_and_identity_coverage():
    cohort = [("User", 100, "alice", 4, 500, 900),
              ("Group", 123, "starworks", 3, 50, 80)]
    items = [("glow hat", 100, 50, 10.0), ("glow cap", 300, 20, 12.0),
             ("plain hat", 20, 0, 30.0)]
    comparison = [("User", 100, "alice", 4, 500, True),
                  ("Group", 123, "starworks", 3, 50, False)]
    coverage = [(2, 7, 2, 11)]
    findings = creator_brain.learn(
        StubCursor([cohort, items, comparison, coverage]),
        min_items=1, has_type=True)
    assert findings["median_favs"] == 100
    assert findings["cohort_size"] == 2
    assert findings["identity_coverage"]["typed_coverage_pct"] == 63.6
    assert findings["identity_coverage"]["unresolved_items"] == 4
    report = creator_brain.format_report(findings)
    assert "Typed creator identity coverage" in report
    assert "unresolved items" in report

    source = Path("creator_brain.py").read_text(encoding="utf-8")
    assert "GROUP BY lower(creator_name)" not in source
    assert "WHERE lower(creator_name) = ANY" not in source
    print("PASS typed medians, coverage disclosure, no name grouping")


def test_creator_registry_ambiguous_name_match_is_not_guessed():
    source = Path("creator_registry.py").read_text(encoding="utf-8")
    assert source.count("HAVING count(DISTINCT t2.creator_type) = 1") >= 2
    assert "ORDER BY t2.creator_type" not in source
    print("PASS registry type inference fails closed on ambiguity")


def test_oracle_cohort_selection_is_typed():
    class Cursor:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append((str(sql), params))

        def fetchall(self):
            return [("User", 123, 9.0, 6), ("Group", 123, 4.0, 5)]

    cur = Cursor()
    elite = tc.select_elite(cur)
    assert {r["creator_key"] for r in elite} == {"User:123", "Group:123"}
    sql = cur.calls[-1][0]
    assert "i.creator_type IN ('User', 'Group')" in sql
    assert "GROUP BY i.creator_type, i.creator_id" in sql
    print("PASS ORACLE elite selection uses typed identities")


def test_oracle_worker_keeps_user_group_collision_separate():
    class Store:
        def __init__(self):
            self.rows = [(123, "ELITE", "User"), (123, "CONTROL", "Group")]

        def try_lock(self): return True
        def release_lock(self): pass
        def close(self): pass
        def latest_cohort(self): return "C", self.rows
        def creator_types(self, keys):
            return {k: k[0] for k in keys if k[1] == 123}
        def create_scan_run(self, ref): return 1
        def update_scan_run(self, rid, summary): self.summary = summary
        def insert_for_creator(self, ctype, cid, items, rid):
            assert ctype in ("User", "Group")
            return {"inserted": 0, "too_recent": 0}

    calls = []

    def search(session, cid, creator_type=None, max_pages=4):
        calls.append((cid, creator_type))
        return {"items": [], "pages": 0, "truncated": False}

    os.environ["ORACLE_ENABLED"] = "1"
    try:
        out = ow.run_oracle_scan(
            store=Store(), search_fn=search,
            batch_fn=lambda ids: ({}, {}), session_fn=lambda: object())
    finally:
        os.environ.pop("ORACLE_ENABLED", None)
    assert out["creators_eligible"] == 2
    assert out["skipped_unknown_type"] == 0
    assert set(calls) == {(123, "User"), (123, "Group")}
    print("PASS ORACLE worker keeps User/Group 123 separate")


def test_trend_observation_writes_creator_type():
    cur = StubCursor([])
    tr.record_observation(
        cur, 7, {"id": 1, "creator_id": 123, "creator_type": "Group",
                 "favorites": 1})
    sql, params = cur.executed[-1]
    assert "creator_type" in sql
    assert params[2] == "Group"
    print("PASS trend observations persist creator_type")


def test_migrations_are_expand_contract_and_guarded():
    expand = Path(
        "migrations/2026-11-08_f07_creator_identity_expand.sql").read_text(
            encoding="utf-8")
    contract = Path(
        "migrations/2026-11-08_f07_creator_identity_contract.sql").read_text(
            encoding="utf-8")
    oracle = Path(
        "migrations/2026-11-08_f07_oracle_identity_additive.sql").read_text(
            encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS type_provenance" in expand
    assert "legacy_unknown" in expand and "legacy_stored" in expand
    assert "ALTER COLUMN creator_type DROP DEFAULT" in expand
    assert "PRIMARY KEY (creator_type, creator_id)" in contract
    assert "duplicate composite identities" in contract
    assert "rollback blocked" in contract
    assert "creator_key" in oracle and "unknown:" in oracle
    assert "UNIQUE (cohort_id, creator_id)" in oracle
    print("PASS migrations are additive, guarded and documented")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL {len(tests)} F-07/F-08 OFFLINE TESTS PASSED")
