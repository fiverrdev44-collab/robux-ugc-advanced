"""Astra spec mock tests (offline; no DB writes)."""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import astra
import marketplace_links as ml
import creator_memory as cm


class FakeCur:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []
        self.row = None

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if sql.strip().lower().startswith("select"):
            self.row = None
        return None

    def fetchall(self):
        return self.rows

    def fetchone(self):
        if self.row is not None:
            return self.row
        return (1,) if self.calls else (0,)


def test_rankability_super_saiyan():
    results = [
        {"name": "Super Saiyan Battle Pose", "assetType": 61},
        {"name": "Super Saiyan Aura Pose", "assetType": 61},
        {"name": "Battle Pose", "assetType": 61},
        {"name": "Random Hat", "assetType": 8},
        {"name": "Super Saiyan Death Pose", "assetType": 61},
    ]
    h = astra.rankability_heuristic(
        results, "Super Saiyan Battle Pose", asset_type=61,
        exact_count=1, checked=len(results))
    assert h["available"] is True and h["label"] == "heuristic"
    assert h["not_probability"] is True
    assert 0 <= h["score"] <= 100
    assert set(h["components"]) == {"relevance", "product_fit", "motion_fit",
                                    "differentiation", "coverage"}
    assert h["components"]["differentiation"] < 1.0  # exact match penalized
    assert h["components"]["product_fit"] == 0.8     # 4/5 emotes
    assert h["checked"] == 5
    print("PASS rankability heuristic (Super Saiyan Battle Pose)")

    down = astra.rankability_heuristic(None, "x", ok=False)
    assert down["available"] is False and down["label"] == "heuristic"
    assert "score" not in down
    print("PASS rankability unavailable without live evidence")


def test_platform_guard():
    banned = [
        "T.i.k.T.o.k Super Saiyan Battle Pose",
        "Super Saiyan YouTube Pose",
        "Super Saiyan VIRAL pose",
        "Trending Battle Pose",
    ]
    for t in banned:
        assert astra.contains_banned_platform(t), t
    assert not astra.contains_banned_platform("Super Saiyan Battle Pose")
    print("PASS separator-tolerant platform guard")


def test_identity_lock():
    concept = "super saiyan battle pose"
    assert astra.identity_lock_ok(concept, "Super Saiyan Battle Pose")
    assert not astra.identity_lock_ok(concept, "Super Saiyan Death Pose")
    assert not astra.identity_lock_ok(concept, "Super Saiyan Battle Stance")
    print("PASS identity lock keeps the requested motion")


def test_provider_configs():
    g = astra.provider_json_config("gemini")
    d = astra.provider_json_config("deepseek")
    assert g == {"response_mime_type": "application/json"}
    assert d == {"response_format": {"type": "json_object"}}
    print("PASS provider-specific JSON configuration")


def test_astra_structure():
    titles = [
        {"title": "Super Saiyan Battle Pose", "angle": "safe"},
        {"title": "Anime Battle Pose", "angle": "differentiated"},
        {"title": "Dragon Battle Pose", "angle": "longtail"},
    ]
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


def test_marketplace_links_parse_and_summary():
    csv_text = ("link_id,item_id,source,clicks,unique_clickers,purchases,spend_robux\n"
                "L1,123,discord,100,80,4,500\n"
                "L2,123,discord,60,55,0,200\n")
    rows = ml.parse_csv(io.StringIO(csv_text))
    assert rows[0]["clicks"] == 100 and rows[0]["purchases"] == 4
    cur = FakeCur(rows=[("L1", 123, "discord", 100, 80, 4, 500),
                        ("L2", 123, "discord", 60, 55, 0, 200)])
    data = ml.summary(cur)
    assert data["links"] == 2
    assert [r["link_id"] for r in data["buyers"]] == ["L1"]
    assert [r["link_id"] for r in data["clicks_without_purchase"]] == ["L2"]
    assert data["totals"]["purchases"] == 4
    text = ml.format_summary(data)
    assert "Brought buyers" in text and "Clicks without purchases" in text
    print("PASS marketplace links parse + buyer/click-only summary")


def test_creator_memory_record():
    cur = FakeCur()
    cur.row = (7,)
    rid = cm.record_run(cur, 123, "super saiyan battle pose",
                        ["safe", "differentiated"],
                        ["Super Saiyan Battle Pose"], "v1", "L1")
    assert rid == 7
    assert any("insert into astra_runs" in c[0].lower() for c in cur.calls)
    print("PASS creator memory records angles/titles/preview/link")


if __name__ == "__main__":
    test_rankability_super_saiyan()
    test_platform_guard()
    test_identity_lock()
    test_provider_configs()
    test_astra_structure()
    test_marketplace_links_parse_and_summary()
    test_creator_memory_record()
    print("ALL ASTRA TESTS PASSED")
