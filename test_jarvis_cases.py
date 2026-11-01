"""Regression cases for interpretation, evidence, memory, and creativity."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import chain
import evidence
import learning
import vanta_conversation as vc


class _Cur:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, *a, **k):
        return None

    def fetchall(self):
        return self.rows


def test_evidence_semantics():
    e = evidence.observed("favorites", 11, "count", "items.favorite_count",
                          asset_id=86973415376933)
    assert evidence.numeric(e, "favorites") == 11
    m = evidence.missing("sales_30d", "count", "my_sales", "no rows in window")
    assert evidence.numeric(m) is None
    p = evidence.partial("favorites", 11, "count", "items", coverage={"known": 1})
    assert p.validity == "partial"
    try:
        evidence.Evidence("x", 1, "bananas", "src")
        raise AssertionError("invalid unit accepted")
    except ValueError:
        pass
    print("PASS evidence semantics")


def test_learning_filters_insufficient():
    rows = [
        (10, 86973415376933, "revive", "applied", "partial",
         {"post_favs": 4, "post_units": 2, "days": 9}, None, 0, None, "2026-11-01"),
        (11, 121930221694467, "rename", "applied", "mature",
         {"post_favs": 30, "days": 30},
         {"insufficient": True, "reason": "treatment lacks pre/post snapshots"},
         0, None, "2026-11-01"),
    ]
    out = learning.load_measured_outcomes(_Cur(rows), item_id=86973415376933)
    assert len(out) == 1 and out[0]["rec_id"] == 10
    block = learning.format_learning_context(_Cur(rows), item_id=86973415376933)
    assert "post_favs=4" in block and "insufficient" not in block.lower()
    assert learning.format_learning_context(_Cur([])) == ""
    print("PASS learning excludes insufficient outcomes")


def test_diversity_filter():
    titles = [
        "Cute Kawaii Fluffy Beanie",
        "Cute Kawaii Fluffy Hat",
        "Wooden Picket Fence Belt",
        "Retro Pop Star Aura Belt",
    ]
    kept = chain._diverse_titles(titles, max_shared=2)
    assert titles[0] in kept
    assert titles[1] not in kept          # near-duplicate stack rejected
    assert titles[2] in kept and titles[3] in kept
    print("PASS title diversity filter")


def test_memory_roundtrip():
    state = vc.ConversationState(user_id=7)
    state.last_item_id = 130928797494687
    state.last_concept = "personal space fence"
    state.pending_chain = {"concept": "waist: wooden fence", "family": "waist"}
    state.item_titles = {130928797494687: "Cute Kitty Fluffy Beanie"}
    state.messages = ["hi", "rename it"]
    data = vc._state_to_dict(state)
    restored = vc._state_from_dict(7, data)
    assert restored.last_item_id == state.last_item_id
    assert restored.pending_chain == state.pending_chain
    assert restored.item_titles == state.item_titles
    assert restored.messages == state.messages
    print("PASS conversation memory round-trip")


def test_no_compulsory_business_instruction():
    import recovery_brain as rb
    body = rb.format_scale_protocol("KEEP", 6, {"favs": 11, "age_days": 182})
    low = body.lower()
    assert "options, not" in low
    for banned in ("do this", "kill", "scale protocol", "must "):
        assert banned not in low, banned
    print("PASS analytical output is not a directive")


def test_original_wording_survives_diversity():
    novel = "Neon Picket Fence Stand"
    kept = chain._diverse_titles([novel, "Wooden Fence Sign"])
    assert novel in kept
    print("PASS original wording is not filtered as non-historical")


if __name__ == "__main__":
    test_evidence_semantics()
    test_learning_filters_insufficient()
    test_diversity_filter()
    test_memory_roundtrip()
    test_no_compulsory_business_instruction()
    test_original_wording_survives_diversity()
    print("ALL JARVIS CASE TESTS PASSED")
