"""Rename tracking tests (offline)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import creator_memory as cm


class ScriptedCur:
    def __init__(self, ones=None):
        self.ones = list(ones or [])
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql.strip().lower(), params))

    def fetchone(self):
        return self.ones.pop(0) if self.ones else None

    def fetchall(self):
        return []


def test_link_old_item_baseline_now():
    # Run 7 exists; the item is months old with current 250 favorites.
    cur = ScriptedCur([
        (7, "Meme Sign", "cool sign"),
        (250, 12, "Meme Sign"),        # favorite_count, total_sales, name
        (9,),                          # astra_outcomes id
    ])
    res = cm.link_run(cur, 7, 555, heuristic_version="astra-fit-v1")
    assert res["ok"] and res["baseline_favorites"] == 250
    assert res["baseline_sales"] == 12
    sql = " ".join(c[0] for c in cur.calls)
    assert "launched_at" in sql and "now()" in sql
    assert "linked_item_id" in sql
    print("PASS old item baseline uses current values and launch=now")


def test_applied_rename_detection():
    assert cm.is_applied_rename(
        {"recommended_name": "Meme Sign"}, {"name": "Meme Sign"})
    assert not cm.is_applied_rename(
        {"recommended_name": "Meme Sign"}, {"name": "Cool Sign"})
    print("PASS applied-rename detection is exact on the current title")


def test_outcome_uses_launch_time():
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "creator_memory.py"), encoding="utf-8").read()
    start = src.index("def outcome_report")
    end = src.index("def recent_runs", start)
    body = src[start:end]
    assert "launched_at" in body
    assert "created_at" not in body
    print("PASS outcome deltas anchor on launched_at, not created_at")


def test_rename_command_and_auto_pass():
    reg = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "commands_astra.py"), encoding="utf-8").read()
    assert 'name="rename"' in reg
    assert "Baseline captured for rename" in reg
    auto = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "creator_memory.py"), encoding="utf-8").read()
    assert "rec_type = 'rename'" in auto
    assert "is_applied_rename" in auto
    print("PASS !rename command and rename auto-link pass present")


if __name__ == "__main__":
    test_link_old_item_baseline_now()
    test_applied_rename_detection()
    test_outcome_uses_launch_time()
    test_rename_command_and_auto_pass()
    print("ALL RENAME TRACKING TESTS PASSED")
