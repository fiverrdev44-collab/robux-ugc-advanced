"""Algorithmic outcome journey: chain run -> launch ledger -> answer.

Offline simulation with a scripted cursor; no production writes.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import creator_memory as cm


class ScriptedCur:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql.strip().lower(), params))

    def fetchone(self):
        return self.responses.pop(0)

    def fetchall(self):
        row = self.responses.pop(0)
        return row or []


def main():
    # 1) Mock !chain generation records the run.
    rec = ScriptedCur([(42,)])
    run_id = cm.record_run(rec, "super saiyan battle pose",
                           ["Super Saiyan Battle Pose", "Anime Battle Pose"],
                           "Super Saiyan Battle Pose", asset_type="emotes")
    assert run_id == 42
    assert "insert into astra_runs" in rec.calls[0][0]
    print("PASS chain run recorded (astra_runs id=42)")

    # 2) Launch ledger has the launched item with 120 favorites.
    outcome_cur = ScriptedCur([
        (42, 99610366014241, "Super Saiyan Battle Pose",
         "super saiyan battle pose", "2026-11-02"),
        (99610366014241, "Super Saiyan Battle Pose", 120, 240, 26, 33,
         391, 497, None),
    ])
    out = cm.algorithm_outcome(outcome_cur, 42)
    assert out["found"] and out["launched"] is True
    assert out["favs_d7"] == 120 and out["favs_d30"] == 240
    msg = out["message"]
    assert "Recommendation 42" in msg
    assert "240 favorites" in msg
    assert "33 units" in msg
    print("PASS algorithmic outcome:", msg)

    # 3) Unlaunched recommendation is reported honestly.
    pending = ScriptedCur([(43, None, "Another Pose", "another pose", "2026-11-02"),
                           None, None])
    out2 = cm.algorithm_outcome(pending, 43)
    assert out2["launched"] is False
    assert "No launch is tracked" in out2["message"]
    print("PASS unlaunched recommendation reported honestly")

    print("ALL ALGORITHM JOURNEY TESTS PASSED")


if __name__ == "__main__":
    main()
