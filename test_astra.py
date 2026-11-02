"""Astra spec mock tests (offline; no DB writes)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astra
import creator_memory as cm


class FakeCur:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []
        self.row = None

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


def test_algorithmic_fit_super_saiyan():
    results = [
        {"name": "Super Saiyan Battle Pose", "assetType": 61},
        {"name": "Super Saiyan Aura Pose", "assetType": 61},
        {"name": "Battle Pose", "assetType": 61},
        {"name": "Random Hat", "assetType": 8},
        {"name": "Super Saiyan Death Pose", "assetType": 61},
    ]
    h = astra.algorithmic_fit_heuristic(
        results, "Super Saiyan Battle Pose", asset_type=61,
        exact_count=1, checked=5, results_count=5)
    assert h["available"] is True
    assert h["label"] == "algorithmic_fit_heuristic"
    assert h["not_probability"] is True
    assert 0 <= h["score"] <= 100
    assert set(h["components"]) == {"relevance", "product_fit", "motion_fit",
                                    "differentiation", "retrieval_completeness"}
    assert h["components"]["differentiation"] < 1.0
    assert h["components"]["product_fit"] == 0.8
    assert h["components"]["retrieval_completeness"] == 1.0
    assert h["result_count"] == 5 and h["checked"] == 5
    print("PASS algorithmic fit (5 exist, 5 checked)")

    down = astra.algorithmic_fit_heuristic(None, "x", ok=False)
    assert down["available"] is False and "score" not in down
    print("PASS algorithmic fit unavailable without live evidence")


def test_platform_guard():
    for t in ("T.i.k.T.o.k Battle Pose", "Super Saiyan YouTube Pose",
              "Super Saiyan VIRAL pose", "Trending Battle Pose"):
        assert astra.contains_banned_platform(t), t
    assert not astra.contains_banned_platform("Super Saiyan Battle Pose")
    print("PASS separator-tolerant platform guard")


def test_identity_lock_override():
    pose = "super saiyan battle pose"
    assert astra.identity_lock_ok(pose, "Super Saiyan Battle Pose")
    assert not astra.identity_lock_ok(pose, "Super Saiyan Death Pose")
    # Explicit user wording is the override: asking for stance allows stance.
    stance = "super saiyan battle stance"
    assert astra.identity_lock_ok(stance, "Super Saiyan Battle Stance")
    assert not astra.identity_lock_ok(stance, "Super Saiyan Death Stance")
    print("PASS identity lock with explicit wording override")


def test_provider_configs():
    assert astra.provider_json_config("gemini") == {
        "response_mime_type": "application/json"}
    assert astra.provider_json_config("deepseek") == {
        "response_format": {"type": "json_object"}}
    print("PASS provider-specific JSON configuration")


def test_astra_structure():
    titles = [{"title": "Super Saiyan Battle Pose", "angle": "safe"},
              {"title": "Anime Battle Pose", "angle": "differentiated"},
              {"title": "Dragon Battle Pose", "angle": "longtail"}]
    desc = "Super Saiyan Battle Pose. Battle-ready stance. Fits anime avatars. Extra."
    out = astra.format_astra(
        {"culture": "anime", "buyer_intent": "battle poses",
         "keyword_plan": "battle pose", "evidence_limits": "5 sampled"},
        titles, desc,
        {"showcase": "3-second reveal", "experiment": "7-day variant test"})
    for section in ("## Analysis Summary", "## Titles", "## Description",
                    "## Preview / Experiment Brief"):
        assert section in out, section
    body = out.split("## Description")[1].split("##")[0].strip()
    sentences = [s for s in body.replace("_(", "").split(".") if s.strip()]
    assert len(sentences) == 3, len(sentences)
    print("PASS Astra output structure with 3-sentence description")


def test_creator_memory_record():
    cur = FakeCur()
    cur.row = (7,)
    rid = cm.record_run(cur, "super saiyan battle pose",
                        ["Super Saiyan Battle Pose"], "Super Saiyan Battle Pose",
                        asset_type="emotes")
    assert rid == 7
    assert any("insert into astra_runs" in c[0].lower() for c in cur.calls)
    print("PASS creator memory records concept/titles/chosen")


if __name__ == "__main__":
    test_algorithmic_fit_super_saiyan()
    test_platform_guard()
    test_identity_lock_override()
    test_provider_configs()
    test_astra_structure()
    test_creator_memory_record()
    print("ALL ASTRA TESTS PASSED")
