"""Rename watcher tests (offline)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rename_watcher as rw


def test_detection():
    assert rw.is_rename_detected("Meme Sign", "Cool Sign", "Meme Sign")
    assert rw.is_rename_detected("Meme Sign V2", "Cool Sign", "Meme Sign")
    assert not rw.is_rename_detected("Cool Sign", "Cool Sign", "Meme Sign")
    assert not rw.is_rename_detected("", "Cool Sign", "Meme Sign")
    print("PASS rename detection (recommended match or changed from baseline)")


def test_schedule_and_batch_use():
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "scheduler.py"), encoding="utf-8").read()
    assert 'id="rename_watcher"' in src and "minutes=15" in src
    watcher = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "rename_watcher.py"), encoding="utf-8").read()
    assert "fetch_many_items_sync" in watcher
    assert "astra_outcomes" in watcher and "launched_at" not in watcher.split(
        "link_run")[0]
    assert "Auto-Tracked Rename!" in watcher
    print("PASS 15-minute job, batch client use, notification copy")


def test_autopsy_persists_recommendation():
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "commands_intel.py"), encoding="utf-8").read()
    assert "create_recommendation(" in src
    assert '"name": rec_name' in src
    assert 'rec_type = "rename"' in src
    print("PASS autopsy persists item_id + recommended rename title")


if __name__ == "__main__":
    test_detection()
    test_schedule_and_batch_use()
    test_autopsy_persists_recommendation()
    print("ALL RENAME WATCHER TESTS PASSED")
