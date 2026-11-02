"""Phase 2 tests: research worker priority queue + analyst report."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astra_report
import market_research_worker as mrw


class QueueCur:
    def __init__(self, batches):
        self.batches = list(batches)
        self.rows = []
        self.calls = 0

    def execute(self, sql, params=None):
        self.calls += 1
        self.rows = self.batches.pop(0) if self.batches else []

    def fetchall(self):
        return self.rows


def test_priority_selection():
    cur = QueueCur([
        [(1,), (2,), (3,)],                      # HIGH launch ledger
        [(3,), (4,), (5,)],                      # MEDIUM recent (3 deduped)
        [(6,), (7,), (1,)],                      # LOW null favorites (1 deduped)
    ])
    ids, tiers = mrw.select_priority_ids(cur, high=3, medium=3, low=3)
    assert ids == [1, 2, 3, 4, 5, 6, 7], ids
    assert tiers[:3] == ["high", "high", "high"]
    assert tiers[3:5] == ["medium", "medium"]
    assert tiers[5:] == ["low", "low"]
    assert len(set(ids)) == len(ids)
    print("PASS priority selection HIGH -> MEDIUM -> LOW with dedupe")


def test_circuit_breaker():
    for _ in range(mrw.CIRCUIT_THRESHOLD):
        mrw._record_failure()
    assert mrw.circuit_open()
    out = mrw.run_cycle(db_factory=lambda: (_ for _ in ()).throw(
        RuntimeError("should not run")))
    assert out.get("skipped") == "circuit_open"
    mrw._record_success()
    assert not mrw.circuit_open()
    print("PASS circuit breaker opens and resets")


def test_scheduler_job_present():
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "scheduler.py"), encoding="utf-8").read()
    assert 'id="market_research"' in src
    assert 'hour="*/6"' in src
    print("PASS scheduler registers 6-hour research job")


def test_analyst_report():
    result = {
        "family": "headwear",
        "concept": "blue hat",
        "merged_description": "Blue hat. Soft fabric. Fits casual outfits.",
        "stats": {"count": 120, "avg_favs": 50, "median_favs": 20,
                  "winner_favs": 400, "price_avg": 65},
        "scored_titles": [
            {"title": "Blue Hat", "opportunity": {"verdict": "CONTESTED",
             "demand_volume": 100, "supply": 3, "exact": 1},
             "exact_matches": 1, "breakdown": [{"word": "blue"}]},
            {"title": "Cozy Blue Hat", "opportunity": {"verdict": "OPEN"},
             "exact_matches": 0, "breakdown": [{"word": "cozy"}]},
        ],
    }
    live = {"ok": True, "results": 5, "pages": 1, "exact": 1}
    chunks = astra_report.build_analyst_report(
        result, live=live, understanding={"family": "headwear",
                                          "colors": [{"value": "blue"}],
                                          "details": [], "motion": [],
                                          "unknowns": ["shape not stated"]})
    text = "\n".join(chunks)
    for section in ("A. PRODUCT UNDERSTANDING", "B. MARKET EVIDENCE",
                    "C. POSITIONING ANGLES", "D. RECOMMENDED FIRST TEST",
                    "E. DESCRIPTION", "F. PREVIEW BRIEF", "G. MEASUREMENT PLAN"):
        assert section in text, section
    assert "blue hat" in text.lower()
    assert "static accessory" in text.lower()
    assert all(len(c) <= 1900 for c in chunks)
    print("PASS analyst report has 7 sections and static preview rule")

    emote = dict(result, family="emotes", concept="super saiyan battle pose")
    etext = "\n".join(astra_report.build_analyst_report(
        emote, live={"ok": False}, understanding={"family": "emotes",
                                                  "motion": []}))
    assert "not evidence of movement" in etext
    assert "Live search failed" in etext
    print("PASS emote rules and failed-live disclosure")


if __name__ == "__main__":
    test_priority_selection()
    test_circuit_breaker()
    test_scheduler_job_present()
    test_analyst_report()
    print("ALL PHASE 2 TESTS PASSED")
