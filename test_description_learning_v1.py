"""Offline contract tests for measured breakout description learning."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import description_learning as dl
import desc_forge

NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=2)
RECENT = NOW - timedelta(hours=1)

def item(i, title, desc, start_fav, end_fav, first=OLD, last=RECENT, favorites=None):
    return (i, title, desc, end_fav if favorites is None else favorites,
            200, start_fav, first, end_fav, last)

def test_growth_is_measured_and_recent_not_lifetime_rate():
    rows = [
        item(10, "Sunny House Background", "A colorful house with purple roof.", 12, 412),
        item(11, "Old But Famous", "An established evergreen popular backdrop.", 999, 999),
        item(12, "Decreasing", "A sunset scene overlooking a misty garden.", 70, 20),
        item(13, "Too short", "A quiet forest with bright blue river.", 0, 70,
             NOW - timedelta(hours=3), NOW - timedelta(hours=2)),
        item(14, "Stale", "A lovely blue moonlit house with stone walls.", 0, 700,
             NOW - timedelta(days=10), NOW - timedelta(days=5)),
        item(15, "Race", "An old red racing city with neon windows.", 0, 200,
             NOW - timedelta(days=3), NOW - timedelta(days=1)),
    ]
    result = dl.measured_favorite_growth(rows, now=NOW)
    assert [x["item_id"] for x in result] == [10, 15], result
    assert result[0]["delta_favorites"] == 400
    assert result[0]["favorites_per_day"] > result[1]["favorites_per_day"]
    assert result[0]["observation_days"] > 1
    assert all(x["delta_favorites"] > 0 for x in result)

def test_category_scope_and_bounded_parameterized_sql():
    class Cursor:
        def __init__(self):
            self.sql = None
            self.params = None
        def execute(self, sql, params):
            self.sql, self.params = sql, params
        def fetchall(self):
            return [item(20, "Sunny House Background", "Cartoon home in a pretty garden.", 5, 95)]
    cur = Cursor()
    result = dl.query_rising_descriptions(
        cur, ["sunny", "house", "sunny", "%' OR 1=1 --"], "backgrounds",
        now=NOW
    )
    assert result["status"] == "measured", result
    assert result["category_ids"] == [92]
    assert cur.params[0] == [92]
    assert cur.params[2] <= dl.CANDIDATE_LIMIT
    assert r"\%" in cur.params[1][2]
    assert "item_history" in cur.sql
    assert "JOIN LATERAL" in cur.sql
    assert "asset_type_id = ANY" in cur.sql
    assert "%' OR 1=1" not in cur.sql
    assert dl.family_asset_ids("emote") == [61]
    assert dl.family_asset_ids("headwear") == [8]
    assert dl.family_asset_ids("bogus_unrecognized_family") == []
    assert dl.family_asset_ids(None) == []

    missing = dl.query_rising_descriptions(cur, ["sunny"], "unrecognized", now=NOW)
    assert missing["rising"] == []
    assert missing["status"] == "unavailable"
    assert missing["reason"] == "unknown_or_unscoped_family"

def test_duplicate_rising_and_mature_coverage():
    established = [
        ("Popular Blue Scene", "Bright blue moon and twinkling stones.", 5500, 200),
        ("Another Old Scene", "Old village sunset and round cobbled fountain.", 3000, 200),
        ("Third Established", "Little brick house and white picket fence.", 2200, 100),
    ]
    rising = [
        {"row": ("Popular Blue Scene", "Recent version of same listing.", 5500, 200)},
        {"row": ("New Moon House", "Little silver moon above a quiet house.", 300, 200)},
        {"row": ("New Garden Scene", "Bright flowers around a pretty gate.", 120, 200)},
    ]
    combined = dl.combine_cohorts(established, rising, limit=4)
    assert len(combined) == 4, combined
    assert len({x[0] for x in combined}) == 4
    assert "Another Old Scene" in [x[0] for x in combined]
    assert "New Moon House" in [x[0] for x in combined]

def test_forge_merges_cohorts_and_exposes_provenance():
    good = "A purple roof above a sunny cartoon garden and bright awnings."
    mature = ("Classic Sunny House", good, 2000, 200)
    rising = {
        "item_id": 123, "row": ("Brand New House", good, 300, 100),
        "delta_favorites": 100, "observation_days": 1.5,
        "favorites_per_day": 66.67,
    }
    class Cursor:
        def close(self): pass
    class Conn:
        def cursor(self): return Cursor()
        def close(self): pass
    with (patch.object(desc_forge, "_fetch_top_descriptions", return_value=[mature]),
          patch.object(desc_forge, "_candidate_keywords", return_value=["house"]),
          patch.object(desc_forge, "get_db", return_value=Conn()),
          patch("description_learning.query_rising_descriptions", return_value={
              "status": "measured", "rising": [rising], "sampled": 2,
              "window_days": 14, "minimum_observation_hours": 6,
          })):
        rows, evidence = desc_forge._fetch_description_cohorts(
            "cartoon house", family="backgrounds", limit=3
        )
    assert len(rows) == 2, rows
    assert evidence["measured_rising_candidates"] == 1
    assert evidence["established_candidates"] == 1
    assert rows[0][0] == "Brand New House"
    assert evidence["featured_rising"][0]["item_id"] == 123

def test_no_growth_and_no_db_do_not_fabricate_winners():
    class Cur:
        def execute(self, sql, params): pass
        def fetchall(self): return []
    report = dl.query_rising_descriptions(Cur(), ["house"], "backgrounds", now=NOW)
    assert report["status"] == "insufficient_history"
    assert report["rising"] == []
    assert dl.measured_favorite_growth([], now=NOW) == []
    with (patch.object(desc_forge, "_fetch_top_descriptions", return_value=[]),
          patch.object(desc_forge, "get_db", side_effect=RuntimeError("down"))):
        rows, evidence = desc_forge._fetch_description_cohorts(
            "cartoon house", family="backgrounds"
        )
    assert rows == []
    assert evidence["rising_status"] == "unavailable"
    assert evidence["rising_reason"] == "RuntimeError"

if __name__ == "__main__":
    test_growth_is_measured_and_recent_not_lifetime_rate()
    test_category_scope_and_bounded_parameterized_sql()
    test_duplicate_rising_and_mature_coverage()
    test_forge_merges_cohorts_and_exposes_provenance()
    test_no_growth_and_no_db_do_not_fabricate_winners()
    print("PASS description measured breakout learning regressions")
