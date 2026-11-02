"""Offline regression tests for the portfolio-wide change watcher."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rename_watcher as rw


class FakeConnection:
    def __init__(self, portfolio, items, history_sales=None, fail_on=None):
        self.portfolio = list(portfolio)
        self.items = {k: list(v) for k, v in items.items()}
        self.history_sales = dict(history_sales or {})
        self.runs, self.outcomes = [], []
        self.fail_on = fail_on
        self.next_run_id = 100
        self.rollbacks = 0
        self.snapshot = None

    def cursor(self):
        return FakeCursor(self)

    def __enter__(self):
        self.snapshot = (
            {k: list(v) for k, v in self.items.items()},
            list(self.runs), list(self.outcomes), self.next_run_id,
        )
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.rollbacks += 1
            (self.items, self.runs, self.outcomes,
             self.next_run_id) = self.snapshot
        self.snapshot = None
        return False

    def close(self):
        pass


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.one = None
        self.many = []

    def execute(self, sql, params=None):
        q = " ".join(sql.lower().split())
        p = params or ()
        if self.conn.fail_on and self.conn.fail_on in q:
            raise RuntimeError("simulated write failure")
        if q.startswith("set statement_timeout"):
            self.one, self.many = None, []
        elif "from my_portfolio" in q:
            self.many = [(i,) for i in self.conn.portfolio]
            self.one = None
        elif q.startswith("select name, description, favorite_count"):
            row = self.conn.items.get(p[0])
            self.one, self.many = (tuple(row), []) if row else (None, [])
        elif "from item_history" in q and "total_sales" in q:
            value = self.conn.history_sales.get(p[0])
            self.one = (value,) if value is not None else None
            self.many = []
        elif "from recommendation_ledger" in q:
            self.one, self.many = None, []
        elif q.startswith("insert into astra_runs"):
            rid = self.conn.next_run_id
            self.conn.next_run_id += 1
            self.conn.runs.append({"id": rid, "params": p})
            self.one, self.many = (rid,), []
        elif q.startswith("insert into astra_outcomes"):
            self.conn.outcomes.append(p)
            self.one, self.many = None, []
        elif q.startswith("update items"):
            iid = p[-1]
            old = self.conn.items[iid]
            self.conn.items[iid] = [
                p[0], p[1], p[2] if p[2] is not None else old[2],
                p[3] if p[3] is not None else old[3],
                old[4] if len(old) > 4 else None,
            ]
            self.one, self.many = None, []
        elif q.startswith("insert into items"):
            self.conn.items.setdefault(p[0], [p[1], p[2], p[3], p[4], None])
            self.one, self.many = None, []
        else:
            raise AssertionError(f"Unexpected SQL: {q}")

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many

    def close(self):
        pass


def test_change_classification():
    assert rw.classify_change("Old", "desc", "New", "desc") == "name_only"
    assert rw.classify_change("Old", "desc", "Old", "new") == "description_only"
    assert rw.classify_change("Old", "desc", "New", "new") == "both"
    assert rw.classify_change("Old", "desc", "Old", "desc") is None
    assert rw.classify_change("Old", None, "Old", "new") is None
    print("PASS change classification (including unknown/null old description)")


def test_all_items_event_baselines_and_duplicate_prevention():
    ids = list(range(1, 10))
    old = {i: [f"Item {i}", f"Desc {i}", 100+i, 61, 700+i] for i in ids}
    live = {
        i: {
            "id": i,
            "name": f"Item {i}" + (" new" if i in (1, 3) else ""),
            "description": f"Desc {i}" + (" new" if i in (2, 3) else ""),
            "favorite_count": 200+i,
            "asset_type_id": 61,
        } for i in ids
    }
    db = FakeConnection(ids, old, history_sales={1: 51, 3: 73})
    fetch_args, alerts = [], []

    def fetcher(asset_ids, **kwargs):
        fetch_args.append((list(asset_ids), kwargs))
        return live, {}

    first = rw.portfolio_change_watcher(
        db_factory=lambda: db, fetcher=fetcher, notifier=alerts.append
    )
    assert first["portfolio"] == 9 and first["checked"] == 9
    assert [e["change_type"] for e in first["captured"]] == [
        "name_only", "description_only", "both"
    ]
    assert len(db.runs) == len(db.outcomes) == len(alerts) == 3
    assert fetch_args[0][0] == ids and fetch_args[0][1]["max_batch"] == 30
    assert first["captured"][0]["baseline_sales"] == 51
    assert first["captured"][1]["baseline_sales"] is None
    assert first["captured"][2]["baseline_sales"] == 73
    assert any("name and description update" in a for a in alerts)
    assert all("Tracking D7/D30 outcomes now." in a for a in alerts)

    second = rw.portfolio_change_watcher(
        db_factory=lambda: db, fetcher=fetcher, notifier=alerts.append
    )
    assert second["captured"] == []
    assert len(db.runs) == len(db.outcomes) == len(alerts) == 3
    print("PASS 9-item portfolio, event-level runs/outcomes, NULL sales and dedupe")


def test_transaction_rolls_back_and_sends_no_alert():
    db = FakeConnection(
        [77], {77: ["Before", "Desc", 40, 61, None]},
        history_sales={77: 12}, fail_on="insert into astra_outcomes"
    )
    live = {77: {"id": 77, "name": "After", "description": "Desc",
                 "favorite_count": 50, "asset_type_id": 61}}
    alerts = []
    result = rw.portfolio_change_watcher(
        db_factory=lambda: db, fetcher=lambda ids, **kw: (live, {}),
        notifier=alerts.append
    )
    assert "error" in result
    assert db.items[77][0] == "Before"
    assert db.runs == [] and db.outcomes == [] and alerts == []
    assert db.rollbacks == 1
    print("PASS transactional rollback across run/outcome/item update and alert")


def test_scheduler_and_batch_wiring():
    root = os.path.dirname(os.path.abspath(__file__))
    scheduler = open(os.path.join(root, "scheduler.py"), encoding="utf-8").read()
    source = open(os.path.join(root, "rename_watcher.py"), encoding="utf-8").read()
    assert 'id="portfolio_change_watcher"' in scheduler
    assert "minutes=15" in scheduler
    assert "from rename_watcher import portfolio_change_watcher" in scheduler
    assert "FROM my_portfolio" in source
    assert "fetch_many_items_sync" in source and "max_batch=30" in source
    assert "FOR UPDATE" in source and "with conn:" in source
    assert "INSERT INTO astra_runs" in source
    assert "INSERT INTO astra_outcomes" in source
    assert "COALESCE(total_sales, 0)" not in source
    assert "Auto-Tracked Change!" in source
    print("PASS scheduler, full portfolio scan, batch limit and transaction wiring")


if __name__ == "__main__":
    test_change_classification()
    test_all_items_event_baselines_and_duplicate_prevention()
    test_transaction_rolls_back_and_sends_no_alert()
    test_scheduler_and_batch_wiring()
    print("ALL PORTFOLIO CHANGE WATCHER TESTS PASSED")
