"""Auto-linker tests (offline)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import creator_memory as cm


def test_match_v2():
    run = {"id": 12, "chosen_title": "Super Saiyan Battle Pose",
           "asset_type": "emotes"}
    items = [
        {"id": 12345, "name": "Super Saiyan Battle Pose V2",
         "asset_type_id": 61},
        {"id": 999, "name": "Blue Hat", "asset_type_id": 8},
    ]
    best = cm.match_run_to_items(run, items)
    assert best and best["item"]["id"] == 12345
    assert best["ratio"] >= 0.80
    print("PASS auto-link matches '... Pose' to '... Pose V2' "
          f"(ratio {best['ratio']})")


def test_family_gate():
    run = {"chosen_title": "Super Saiyan Battle Pose", "asset_type": "emotes"}
    items = [{"id": 1, "name": "Super Saiyan Battle Pose", "asset_type_id": 8}]
    assert cm.match_run_to_items(run, items) is None
    print("PASS family mismatch rejected (emote run vs hat item)")


def test_low_similarity():
    run = {"chosen_title": "Super Saiyan Battle Pose", "asset_type": "emotes"}
    items = [{"id": 2, "name": "Random Idle Wave", "asset_type_id": 61}]
    assert cm.match_run_to_items(run, items) is None
    print("PASS low-similarity title rejected")


def test_family_normalization():
    assert cm._norm_family("emotes") == "emote"
    assert cm._norm_family("waist") == "accessory"
    assert cm._norm_family("hats") == "headwear"
    print("PASS family normalization")


def test_schedule_and_launch_copy():
    sched = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "scheduler.py"), encoding="utf-8").read()
    assert 'id="auto_link"' in sched and "hours=2" in sched
    assert "_run_auto_link" in sched
    launch = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "commands_supercomputer.py"),
                  encoding="utf-8").read()
    assert "automatically scan your catalog" in launch
    auto = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "creator_memory.py"), encoding="utf-8").read()
    assert "def auto_link_recent_runs" in auto
    print("PASS 2-hour job, launch copy, and auto-link entry point")


if __name__ == "__main__":
    test_match_v2()
    test_family_gate()
    test_low_similarity()
    test_family_normalization()
    test_schedule_and_launch_copy()
    print("ALL AUTO-LINK TESTS PASSED")
