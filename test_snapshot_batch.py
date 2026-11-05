"""Snapshot batch-client tests (offline; no DB writes)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import snapshot


class FakeCursor:
    def __init__(self, has_type=True):
        self.calls = []
        self.history = []
        self.fetchall_count = 0
        self.has_type = has_type
        self.connection = self
        self.encoding = "utf-8"

    def execute(self, sql, params=None):
        self.calls.append((" ".join(str(sql).split()), params))

    def fetchone(self):
        return (1,) if self.has_type else None

    def mogrify(self, template, args):
        return template

    def commit(self):
        pass

    def rollback(self):
        pass

    def executemany(self, sql, seq):
        self.calls.append((" ".join(str(sql).split()), None))
        self.history.extend(seq)

    def fetchall(self):
        if self.fetchall_count == 0:
            self.fetchall_count += 1
            return [(101, 5, 65), (102, 0, 65)]
        return []

    def close(self):
        pass


class FakeConn:
    def __init__(self, has_type=True):
        self.cur = FakeCursor(has_type=has_type)
        self.commits = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def test_snapshot_uses_batch_client():
    fake = FakeConn()
    original_conn = snapshot.get_db_connection
    snapshot.get_db_connection = lambda: fake

    import roblox_batch_client
    original_fetch = roblox_batch_client.fetch_many_items_sync
    calls = {}

    def fake_fetch(ids, **kwargs):
        calls["ids"] = list(ids)
        calls["kwargs"] = kwargs
        return ({
            101: {"favorite_count": 12, "price": 70,
                  "creator_id": 501, "creator_type": "User",
                  "creator_verified": True},
            102: {"favorite_count": 3, "price": 65,
                  "creator_id": None, "creator_type": None,
                  "creator_verified": None},
        }, {})

    roblox_batch_client.fetch_many_items_sync = fake_fetch
    try:
        assert snapshot._snapshot_top_items_inner() is True
    finally:
        snapshot.get_db_connection = original_conn
        roblox_batch_client.fetch_many_items_sync = original_fetch

    assert calls["kwargs"].get("max_batch") == 30
    assert sorted(calls["ids"]) == [101, 102]
    # Bulk item update, not one UPDATE per item.
    update_calls = [c for c in fake.cur.calls
                    if c[0].upper().startswith("UPDATE")]
    assert any("FROM (SELECT unnest" in s for s, _ in update_calls)
    bulk = next(c for c in update_calls if "FROM (SELECT unnest" in c[0])
    assert "creator_id = COALESCE" in bulk[0]
    assert "creator_type = COALESCE" in bulk[0]
    assert "creator_verified = COALESCE" in bulk[0]
    assert bulk[1][3] == [501, None]
    assert bulk[1][4] == ["User", None]
    assert bulk[1][5] == [True, None]
    # History rows carry the fresh favorite counts and prices.
    rows = {r[0]: r for r in fake.cur.history}
    assert rows[101][1] == 12 and rows[101][3] == 70
    assert rows[102][1] == 3 and rows[102][3] == 65
    print("PASS snapshot fetches via 30-item batch and bulk-upserts history")


def test_snapshot_identity_update_pre_migration():
    fake = FakeConn(has_type=False)
    original_conn = snapshot.get_db_connection
    snapshot.get_db_connection = lambda: fake

    import roblox_batch_client
    original_fetch = roblox_batch_client.fetch_many_items_sync

    def fake_fetch(ids, **kwargs):
        return ({
            101: {"favorite_count": 12, "price": 70,
                  "creator_id": 501, "creator_type": "User",
                  "creator_verified": False},
            102: {"favorite_count": 3, "price": 65,
                  "creator_id": None, "creator_type": None,
                  "creator_verified": None},
        }, {})

    roblox_batch_client.fetch_many_items_sync = fake_fetch
    try:
        assert snapshot._snapshot_top_items_inner() is True
    finally:
        snapshot.get_db_connection = original_conn
        roblox_batch_client.fetch_many_items_sync = original_fetch

    bulk = next(c for c in fake.cur.calls
                if c[0].upper().startswith("UPDATE")
                and "FROM (SELECT unnest" in c[0])
    assert "creator_id = COALESCE" in bulk[0]
    assert "creator_verified = COALESCE" in bulk[0]
    assert "creator_type" not in bulk[0]
    assert bulk[1][3] == [501, None]
    assert bulk[1][4] == [False, None]
    print("PASS snapshot identity update is pre-migration compatible")


def test_half_life_selection_preserved():
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "snapshot.py"), encoding="utf-8").read()
    assert "WITH ranked_items" in src
    assert "WHERE tier < 99" in src
    assert "tier0_priority" in src
    assert "CASE WHEN tier = 0 THEN tier0_priority ELSE 2 END ASC" in src
    assert "LIMIT %s" in src
    assert "fetch_many_items_sync" in src
    print("PASS half-life CTE selection preserved with recent-first tier 0")


if __name__ == "__main__":
    test_snapshot_uses_batch_client()
    test_snapshot_identity_update_pre_migration()
    test_half_life_selection_preserved()
    print("ALL SNAPSHOT BATCH TESTS PASSED")
