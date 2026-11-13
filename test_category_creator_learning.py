"""Cross-category creator learning tests. No live Roblox calls or DB writes."""
from datetime import datetime, timedelta, timezone
from category_creator_learning import (
    learn_from_rows, learn_category_creators, lookup_creator_learning,
    title_pattern_bonus, format_creator_learning,
)
from test_background_visual_intelligence import VISION

NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)


def sample(family="backgrounds"):
    # Six independent typed User and Group creators, two items each; one
    # repeated naming feature across multiple leading creators.
    rows = []
    for i, (ctype, cid, fav, word) in enumerate([
        ("Group", 101, 120, "Moonlit"),
        ("User", 102, 95, "Moonlit"),
        ("Group", 103, 80, "Moonlit"),
        ("User", 104, 15, "Plain"),
        ("Group", 105, 10, "Plain"),
        ("User", 106, 5, "Plain"),
    ]):
        for n in range(2):
            rows.append((
                1000+i*10+n, f"{word} Shrine Background" if family == "backgrounds"
                else f"{word} Sway Emote", ctype, cid, f"Creator {cid}",
                i == 0, fav+n, 200, NOW-timedelta(days=10+n),
            ))
    return rows


def test_repeated_creator_phrases_not_single_hit():
    data = learn_from_rows(sample(), "backgrounds")
    assert data["status"] == "observed", data
    assert data["eligible_creators"] == 6
    assert len(data["leaders"]) == 2
    assert data["leaders"][0]["id"] == 101
    assert any(p["term"] == "moonlit" and p["creators"] == 2
               for p in data["patterns"]), data
    assert not any(p["term"] == "fnaf" for p in data["patterns"])
    assert data["sales_verified"] is False and data["causal"] is False
    assert "Favorites are not sales" in format_creator_learning(data)


def test_group_user_ids_not_collapsed():
    rows = sample()
    rows[0] = (rows[0][0], rows[0][1], "User", 101, rows[0][4],
               rows[0][5], rows[0][6], rows[0][7], rows[0][8])
    out = learn_from_rows(rows, "backgrounds")
    assert out["eligible_creators"] >= 5


def test_sparse_creator_data_never_claims_learned_winner():
    out = learn_from_rows(sample()[:5], "backgrounds")
    assert out["status"] == "insufficient"
    assert not out["patterns"] and not out["leaders"]
    assert "Too few repeat creators" in format_creator_learning(out)


def test_growth_requires_multiple_distinct_snapshots():
    rows = sample()
    earlier = NOW-timedelta(days=2)
    history = [(1000, 3, earlier), (1000, 6, NOW),
               (1001, 2, NOW), (1010, 3, NOW-timedelta(hours=2)),
               (1010, 500, NOW)]
    out = learn_from_rows(rows, "backgrounds", history)
    assert out["measured_items"] == 1
    assert out["measured_positive"] == 1


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
    def execute(self, sql, args):
        self.calls.append((sql, args))
        assert not any(op in sql.upper() for op in
                       ("INSERT ", "UPDATE ", "DELETE ", "DROP "))
    def fetchall(self):
        return self.rows if len(self.calls) == 1 else []
    def close(self):
        pass


def test_query_category_isolation_for_backgrounds_and_emotes():
    for family, asset in [("backgrounds", [92]), ("emote", [61])]:
        c = FakeCursor(sample(family))
        learned = learn_category_creators(c, family)
        assert learned["family"] == family
        assert len(c.calls) == 2
        assert "asset_type_id = ANY(%s)" in c.calls[0][0]
        assert c.calls[0][1] == (asset, 1400)
        assert len(c.calls[1][1][0]) == len(c.rows)
        assert learned["eligible_creators"] == 6


def test_visual_grounding_only_small_tie_breaker():
    finding = learn_from_rows(sample(), "backgrounds")
    assert title_pattern_bonus(
        "Moonlit Shrine Background", VISION, finding) == 2
    assert title_pattern_bonus(
        "Plain Shrine Background", VISION, finding) == 0
    assert title_pattern_bonus(
        "Moonlit Shrine Background", {},
        finding) == 0


def test_missing_db_fails_soft():
    def bad_db():
        raise RuntimeError("unavailable")
    out = lookup_creator_learning("backgrounds", db_factory=bad_db)
    assert out["status"] == "unavailable"
    assert "unavailable" in format_creator_learning(out)


if __name__ == "__main__":
    test_repeated_creator_phrases_not_single_hit()
    test_group_user_ids_not_collapsed()
    test_sparse_creator_data_never_claims_learned_winner()
    test_growth_requires_multiple_distinct_snapshots()
    test_query_category_isolation_for_backgrounds_and_emotes()
    test_visual_grounding_only_small_tie_breaker()
    test_missing_db_fails_soft()
    print("PASS same-category creator cohort learning")
