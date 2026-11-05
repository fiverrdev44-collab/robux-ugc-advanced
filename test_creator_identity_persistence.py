"""Regression tests for creator identity persistence and snapshot selection."""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("ROBLOSECURITY_COOKIE", "test-cookie")

from creator_identity import catalog_identity, economy_identity  # noqa: E402
from roblox_batch_client import _normalize  # noqa: E402
import enricher  # noqa: E402
import live_enrich  # noqa: E402
import snapshot  # noqa: E402


def test_catalog_identity_preserves_only_explicit_values():
    full = catalog_identity({
        "creatorTargetId": 123,
        "creatorType": "Group",
        "creatorHasVerifiedBadge": False,
    })
    assert full == {"creator_id": 123, "creator_type": "Group",
                    "creator_verified": False}

    missing = catalog_identity({})
    assert missing == {"creator_id": None, "creator_type": None,
                       "creator_verified": None}

    unknown_badge = catalog_identity({
        "creatorTargetId": "456",
        "creatorType": " ",
        "creatorHasVerifiedBadge": "yes",
    })
    assert unknown_badge == {"creator_id": 456, "creator_type": None,
                             "creator_verified": None}
    print("PASS catalog identity preserves explicit values only")


def test_economy_identity_preserves_explicit_values():
    row = economy_identity({
        "Creator": {"Id": 987, "Name": "Studio", "CreatorType": "Group"},
    })
    assert row == {"creator_id": 987, "creator_type": "Group",
                   "creator_verified": None}
    assert economy_identity({}) == {"creator_id": None,
                                    "creator_type": None,
                                    "creator_verified": None}
    print("PASS economy identity preserves explicit values only")


def test_batch_normalize_keeps_creator_identity():
    item = _normalize({
        "id": 55,
        "name": "Item",
        "creatorName": "Creator",
        "creatorTargetId": 777,
        "creatorType": "User",
        "creatorHasVerifiedBadge": True,
        "favoriteCount": 10,
        "price": 5,
        "assetType": 61,
    })
    assert item["creator_id"] == 777
    assert item["creator_type"] == "User"
    assert item["creator_verified"] is True
    print("PASS batch normalize keeps creator identity")


def test_enricher_row_keeps_creator_identity():
    row = enricher._item_row(1, {
        "favorite_count": 10,
        "price": 5,
        "name": "Item",
        "creator_name": "Creator",
        "creatorTargetId": 888,
        "creatorType": "Group",
        "creatorHasVerifiedBadge": False,
        "asset_type_id": 61,
    })
    assert row[6:9] == (888, "Group", False)
    assert row[9] == 61 and row[10] == "known"

    missing = enricher._item_row(2, {"name": "Missing"})
    assert missing[6:9] == (None, None, None)
    print("PASS enricher rows keep creator identity and missing values")


def test_live_enrich_sql_preserves_identity_on_conflict():
    for sql in (live_enrich._UPSERT_WITH_TYPE,
                live_enrich._UPSERT_NO_TYPE):
        assert "creator_id = COALESCE(EXCLUDED.creator_id, items.creator_id)" in sql
        assert "creator_verified = COALESCE" in sql
    assert "creator_type = COALESCE" in live_enrich._UPSERT_WITH_TYPE
    print("PASS live enrich upserts cannot erase known identity")


def test_snapshot_selection_prioritizes_launch_then_recent():
    sql = snapshot._SELECTION_SQL
    assert "WITH ranked_items" in sql
    assert "WHERE tier < 99" in sql
    assert "tier0_priority" in sql
    assert "CASE WHEN tier = 0 THEN tier0_priority ELSE 2 END ASC" in sql
    assert "LIMIT %s" in sql
    assert sql.index("tier0_priority ELSE 2") < sql.index(
        "last_updated_at ASC NULLS FIRST")
    print("PASS snapshot selection preserves limit and prioritizes recent")


def test_diagnostics_are_read_only():
    root = os.path.dirname(os.path.abspath(__file__))
    for name in ("snapshot_selection_audit.sql",
                 "oracle_zero_observation_audit.sql"):
        with open(os.path.join(root, "diagnostics", name),
                  encoding="utf-8") as handle:
            text = handle.read().lower()
        assert "begin read only;" in text
        assert "rollback;" in text
        for forbidden in ("insert into", "update ", "delete from",
                          "alter table", "create table", "drop table",
                          "truncate "):
            assert forbidden not in text, (name, forbidden)
    with open(os.path.join(root, "diagnostics",
                           "snapshot_selection_audit.sql"),
              encoding="utf-8") as handle:
        text = handle.read().lower()
    assert "item_history" in text
    assert "attempted" in text
    print("PASS diagnostics are read-only and use stored snapshot rows")


if __name__ == "__main__":
    test_catalog_identity_preserves_only_explicit_values()
    test_economy_identity_preserves_explicit_values()
    test_batch_normalize_keeps_creator_identity()
    test_enricher_row_keeps_creator_identity()
    test_live_enrich_sql_preserves_identity_on_conflict()
    test_snapshot_selection_prioritizes_launch_then_recent()
    test_diagnostics_are_read_only()
    print("ALL CREATOR IDENTITY PERSISTENCE TESTS PASSED")
