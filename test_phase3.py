"""Phase 3 tests: asset linking, outcome deltas, evaluation guard."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astra
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


def test_chain_run_linking():
    # record_run -> id 7
    cur = ScriptedCur([(7,)])
    rid = cm.record_run(cur, "anime aura pose", ["Anime Aura Pose"],
                        "Anime Aura Pose", asset_type="emotes")
    assert rid == 7
    assert any("insert into astra_runs" in c[0] for c in cur.calls)
    print("PASS chain run recorded (run 7)")

    launched = datetime.now(timezone.utc) - timedelta(days=10)
    cur = ScriptedCur([
        (7, "Anime Aura Pose", "anime aura pose"),   # run
        (10, 0, "Anime Aura Pose"),                  # item baseline
        (5,),                                        # astra_outcomes id
        # outcome_report:
        (7, 999, 10, 0, launched, "Anime Aura Pose", "Anime Aura Pose"),
        (25, launched),                              # latest history
        (20, launched + timedelta(days=7)),          # D7 history
        (3, 450),                                    # sales since launch
    ])
    res = cm.link_run(cur, 7, 999, heuristic_version="astra-fit-v1")
    assert res["ok"] and res["baseline_favorites"] == 10
    assert any("insert into astra_outcomes" in c[0] for c in cur.calls)
    print("PASS !link snapshots baseline (10 favorites)")

    out = cm.outcome_report(cur, 7)
    assert out["found"] is True
    assert out["favorites_delta"] == 10       # D7: 20 - baseline 10
    assert out["units_since_launch"] == 3
    assert "D7 Favorites: +10" in out["message"]
    assert "Units Sold: 3" in out["message"]
    assert "Tracking (D30 pending)" in out["message"]
    print("PASS !outcome delta:", out["message"])


def test_no_linked_outcome():
    cur = ScriptedCur([None])
    out = cm.outcome_report(cur, 999)
    assert out["found"] is False
    print("PASS unlinked run reports no outcome")


def test_evaluation_guard_and_frozen_version():
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "chain.py"), encoding="utf-8").read()
    assert 'ASTRA_LEARNING_IN_GENERATION' in src
    assert '"0"' in src  # default off
    h = astra.algorithmic_fit_heuristic(
        [{"name": "Anime Aura Pose", "assetType": 61}],
        "Anime Aura Pose", asset_type=61, checked=1, results_count=1)
    assert h["heuristic_version"] == "astra-fit-v1"
    print("PASS evaluation guard default-off and frozen heuristic version")


def test_link_and_outcome_commands_exist():
    reg = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "commands_astra.py"), encoding="utf-8").read()
    assert 'name="link"' in reg and 'name="outcome"' in reg
    entry = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "discord_ugc_bot.py"), encoding="utf-8").read()
    assert "register_astra_commands" in entry
    print("PASS !link/!outcome registered")


if __name__ == "__main__":
    test_chain_run_linking()
    test_no_linked_outcome()
    test_evaluation_guard_and_frozen_version()
    test_link_and_outcome_commands_exist()
    print("ALL PHASE 3 TESTS PASSED")
