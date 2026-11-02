"""Offline regression tests for maturity-aware survival intelligence."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from intel_common import decide_verdict, d30_milestone_probability
from gemini_brain import autopsy_maturity_prompt, guard_immature_autopsy_output


class FakeCur:
    def __init__(self, values):
        self.values = values
        self.sql = None
        self.params = None

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return [(value,) for value in self.values]


def test_under_14_is_too_early_unless_viral():
    state, _, reason = decide_verdict(10, age_days=8, favs=4, velocity=0.5,
                                      total_sales=0, sample_size=100)
    assert state == "TOO_EARLY", state
    assert "too young to judge" in reason.lower()
    assert "WATCH it for another 6 days" in reason

    state, _, _ = decide_verdict(10, age_days=8, favs=100, velocity=12,
                                 total_sales=0, sample_size=100)
    assert state == "WINNER", state

    state, _, _ = decide_verdict(10, age_days=8, favs=4, velocity=0.5,
                                 total_sales=3, sample_size=100)
    assert state == "WINNER", state
    print("PASS under-14 maturity gate and viral exception")


def test_14_to_30_positive_velocity_is_recovering_or_watch():
    recovering = decide_verdict(35, age_days=20, favs=20, velocity=0.5,
                                total_sales=0, sample_size=100)[0]
    watch = decide_verdict(20, age_days=20, favs=4, velocity=0.1,
                           total_sales=0, sample_size=100)[0]
    assert recovering == "RECOVERING", recovering
    assert watch == "WATCH", watch
    print("PASS 14-30 day recovery/watch states")


def test_after_30_flat_trajectory_is_stagnating_or_candidate():
    stagnating = decide_verdict(35, age_days=35, favs=20, velocity=0.0,
                                total_sales=0, sample_size=100)[0]
    candidate = decide_verdict(10, age_days=60, favs=10, velocity=0.0,
                               total_sales=0, sample_size=100)[0]
    assert stagnating == "STAGNATING", stagnating
    assert candidate == "KILL_CANDIDATE", candidate
    print("PASS mature flatline states")


def test_sales_and_top_percentile_can_be_winners():
    sales_winner = decide_verdict(50, age_days=40, favs=100, velocity=1,
                                  total_sales=3, sample_size=100)[0]
    percentile_winner = decide_verdict(96, age_days=40, favs=100, velocity=1,
                                       total_sales=0, sample_size=100)[0]
    assert sales_winner == "WINNER"
    assert percentile_winner == "WINNER"
    print("PASS mature winner signals")


def test_d30_family_cohort_requires_minimum_and_uses_family_only():
    small = FakeCur(range(19))
    result = d30_milestone_probability(small, "emote", favs=10, age_days=10,
                                       velocity=1)
    assert result["available"] is False and result["cohort_n"] == 19
    assert "at least 20" in result["reason"]
    assert "lower(trim(family))" in small.sql
    assert small.params == ("emote",)

    mature = FakeCur(range(0, 200, 10))
    result = d30_milestone_probability(mature, "emote", favs=50, age_days=10,
                                        velocity=5)
    assert result["available"] is True, result
    assert result["cohort_n"] == 20
    assert result["milestone_favs"] == 95
    assert result["projected_favs_d30"] == 150
    assert 50 < result["probability"] <= 100
    assert result["not_calibrated"] is True
    print("PASS family D30 milestone and conservative cohort guard")


def test_immature_autopsy_prompt_and_output_guard():
    prompt = autopsy_maturity_prompt(8)
    assert "too young to judge" in prompt.lower()
    assert "WATCH it for another 6 days" in prompt
    assert "Do not use the words KILL or failure" in prompt
    data = guard_immature_autopsy_output({
        "summary": "This is a failure; KILL the item.",
        "titles": ["Cute Hat"],
    }, 8)
    combined = str(data).lower()
    assert "failure" not in combined and "kill" not in combined, data
    assert data["titles"] == ["Cute Hat"]
    assert guard_immature_autopsy_output({"summary": "KILL"}, 20)["summary"] == "KILL"
    print("PASS immature prompt and output language guard")


if __name__ == "__main__":
    test_under_14_is_too_early_unless_viral()
    test_14_to_30_positive_velocity_is_recovering_or_watch()
    test_after_30_flat_trajectory_is_stagnating_or_candidate()
    test_sales_and_top_percentile_can_be_winners()
    test_d30_family_cohort_requires_minimum_and_uses_family_only()
    test_immature_autopsy_prompt_and_output_guard()
    print("ALL SURVIVAL INTELLIGENCE TESTS PASSED")
