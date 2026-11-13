"""Offline category-92 evidence tests; no network, no database writes."""
from datetime import datetime, timedelta, timezone
from unittest import mock

from background_opportunities import (
    scene_angles, analyze_stored_backgrounds, format_opportunity_evidence,
    lookup_background_opportunities,
)
from background_review import build_multi_pass_review, format_multi_pass_review

NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)
VISION = {
    "visual_summary": "Dark blue security office with an animatronic bear.",
    "search_description": "Blue Security Office Background",
    "distinctive_features": [
        "animatronic bear peeking through window",
        "green lockers against the back wall",
        "illuminated computer on a desk",
    ],
    "avatar_clearance_notes": "central avatar blocks desk",
    "mobile_readability_notes": "bear eyes may be tiny",
}
NOTES = "FNAF blue security office"


class FakeCursor:
    def __init__(self, item_rows, history_rows):
        self.item_rows = item_rows
        self.history_rows = history_rows
        self.calls = []
    def execute(self, sql, params):
        self.calls.append((sql, params))
        assert "asset_type_id = 92" in sql if "FROM items" in sql else "item_id = ANY(%s)" in sql
        assert "INSERT" not in sql and "UPDATE" not in sql and "DELETE" not in sql
    def fetchall(self):
        return self.item_rows if len(self.calls) == 1 else self.history_rows


class FakeConnection:
    def __init__(self, cursor):
        self.obj = cursor
        self.closed = False
    def cursor(self):
        return self.obj
    def close(self):
        self.closed = True


def test_scene_angles_are_visual_and_bounded():
    angles = scene_angles(VISION, NOTES)
    assert "security office" in angles, angles
    assert "animatronic bear" in angles
    assert "fnaf security office" in angles
    assert len(angles) <= 6
    assert not scene_angles({}, ""), "no scene => no guessed market angle"


def test_matching_category_and_measured_growth():
    rows = [
        (101, "Blue Security Office Background", 70, 200, NOW-timedelta(days=2)),
        (102, "Animatronic Bear Background", 10, 150, NOW-timedelta(days=45)),
        (103, "Sunny Garden Background", 9000, 20, NOW-timedelta(days=4)),
    ]
    hist = [
        (101, 12, NOW-timedelta(days=3)),
        (101, 26, NOW-timedelta(days=2)),
        (102, 10, NOW-timedelta(days=1)),
    ]
    c = FakeCursor(rows, hist)
    out = analyze_stored_backgrounds(c, VISION, NOTES, now=NOW)
    assert out["status"] == "ok"
    assert out["asset_type_id"] == 92
    assert out["rows_scanned"] == 3
    assert len(c.calls) == 2
    assert c.calls[0][1][1] == 160
    assert set(c.calls[1][1][0]) == {101, 102, 103}
    by_phrase = {a["phrase"]: a for a in out["angles"]}
    assert by_phrase["security office"]["sample_matches"] == 1
    assert by_phrase["security office"]["recent_30d"] == 1
    assert by_phrase["security office"]["measured_positive"] == 1
    assert by_phrase["animatronic bear"]["measured_items"] == 0
    assert by_phrase["fnaf security office"]["sample_status"] == "no_match_not_proven_gap"
    report = format_opportunity_evidence(out)
    assert "not found in sample; demand unknown" in report
    assert "CTR" in report
    assert "9000" not in report
    assert all(len(x) <= 1800 for x in report.splitlines())


def test_one_snapshot_is_not_favorite_velocity():
    now = NOW
    row = (7, "Security Office Background", 9999, 200, now)
    c = FakeCursor([row], [(7, 1, now-timedelta(hours=1)),
                           (7, 9999, now)])
    out = analyze_stored_backgrounds(c, VISION, NOTES, now=now)
    sample = next(a for a in out["angles"] if a["phrase"] == "security office")
    assert sample["measured_items"] == 0
    assert sample["measured_positive"] == 0


def test_failed_db_fails_soft_without_gap_claim():
    def raise_db():
        raise RuntimeError("database unavailable")
    out = lookup_background_opportunities(VISION, NOTES, db_factory=raise_db)
    assert out["status"] == "unavailable"
    report = format_opportunity_evidence(out)
    assert "no gap asserted" in report
    assert "0 matched" not in report


def test_creative_pass_receives_market_context_without_extra_calls():
    market = {
        "status": "ok",
        "angles": [{"phrase": "security office", "sample_matches": 9,
                    "recent_30d": 2, "measured_positive": 1}],
    }
    prompts = []
    def text(prompt, **_):
        prompts.append(prompt)
        if len(prompts) == 1:
            return '{"titles":["Blue Security Office Background", "Animatronic Bear Security Office Background"]}'
        return ('{"winner":"Animatronic Bear Security Office Background",'
                '"alternatives":["Blue Security Office Background"],'
                '"challenge":"Bear may be too small on mobile.",'
                '"why_winner":"Bear is the visual hook.",'
                '"photopea_steps":["Preview a center avatar in Photopea",'
                '"Slightly lift Curves on the left window",'
                '"Check mobile crop on a scaled down image"],'
                '"description":"A dim blue security office with an animatronic bear near the window."}')
    output = build_multi_pass_review(
        VISION, [{"bytes": b"x", "mime": "image/png"}], NOTES,
        {"ok": False}, lambda *_: {}, text, market)
    assert len(prompts) == 2
    assert "sample_matches" in prompts[0]
    assert "sample_matches" in prompts[1]
    assert output["status"] == "ok"
    assert output["winner"] == "Animatronic Bear Security Office Background"
    summary = format_multi_pass_review(output)
    assert "Title-angle evidence" in summary
    assert "Not an estimated CTR" in summary
    assert len(output["alternatives"]) == 2 or len(output["alternatives"]) == 1


if __name__ == "__main__":
    test_scene_angles_are_visual_and_bounded()
    test_matching_category_and_measured_growth()
    test_one_snapshot_is_not_favorite_velocity()
    test_failed_db_fails_soft_without_gap_claim()
    test_creative_pass_receives_market_context_without_extra_calls()
    print("PASS background category opportunities")
