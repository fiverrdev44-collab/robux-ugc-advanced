"""Snapshot batch-client tests (offline; no DB writes)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import snapshot


class FakeCursor:
    def __init__(self):
        self.calls = []
        self.history = []
        self.fetchall_count = 0
        self.connection = self
        self.encoding = "utf-8"

    def execute(self, sql, params=None):
        self.calls.append((" ".join(str(sql).split()), params))

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
    def __init__(self):
        self.cur = FakeCursor()
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
        return ({101: {"favorite_count": 12, "price": 70},
                 102: {"favorite_count": 3, "price": 65}}, {})

    roblox_batch_client.fetch_many_items_sync = fake_fetch
    try:
        assert snapshot._snapshot_top_items_inner() is True
    finally:
        snapshot.get_db_connection = original_conn
        roblox_batch_client.fetch_many_items_sync = original_fetch

    assert calls["kwargs"].get("max_batch") == 30
    assert sorted(calls["ids"]) == [101, 102]
    # Bulk item update, not one UPDATE per item.
    update_sqls = [c[0] for c in fake.cur.calls if c[0].upper().startswith("UPDATE")]
    assert any("FROM (SELECT unnest" in s for s in update_sqls)
    # History rows carry the fresh favorite counts and prices.
    rows = {r[0]: r for r in fake.cur.history}
    assert rows[101][1] == 12 and rows[101][3] == 70
    assert rows[102][1] == 3 and rows[102][3] == 65
    print("PASS snapshot fetches via 30-item batch and bulk-upserts history")


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
    test_half_life_selection_preserved()
    print("ALL SNAPSHOT BATCH TESTS PASSED")
