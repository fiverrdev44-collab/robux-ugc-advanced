"""Regression for real !revive chain formatter NameError.

The generator and formatter are separate functions. The formatter must import
its own dependencies and have complete family, concept and parent context
when invoked by !chain, !revive or a variant. No live Roblox or DB writes.
"""
from unittest import mock
import chain


class _Cursor:
    def close(self):
        pass


class _Connection:
    def __init__(self):
        self.cursor_instance = _Cursor()
        self.committed = False
    def cursor(self):
        return self.cursor_instance
    def commit(self):
        self.committed = True
    def close(self):
        pass


def _result(parent_id=None):
    return {
        "concept": "Jabba No Chill Hip Hop Street Dance",
        "family": "emotes",
        "item_type": "emotes",
        "type_override": None,
        "is_variant": parent_id is not None,
        "parent_id": parent_id,
        "parent_name": ("Jabba No Chill Hip Hop Street Dance"
                        if parent_id else None),
        "stats": {
            "count": 19, "avg_favs": 22, "median_favs": 8,
            "winner_favs": 170, "price_avg": 40,
        },
        "niche": [],
        "niche_intel": None,
        "top_items": [],
        "desc_examples": [],
        "best_niche_kw": None,
        "synth": {
            "titles_safe": ["Jabba Urban Street Dance",
                            "Streetwear Jabba Hip Hop Dance"],
            "titles_differentiated": [],
            "titles_longtail": [],
            "titles_viral": [],
            "market_diagnosis": "A hip hop dance for Roblox avatars.",
            "killer_keywords": ["dance", "streetwear"],
            "social_playbook": "Promote on TikTok",
        },
        "pipeline_report": None,
        "scored_titles": [],
        "merged_description": "Jabba Hip Hop Street Dance emote.",
        "description_audit": {},
        "verification": None,
        "confidence": None,
    }


def test_format_chain_executes_during_revive_without_name_errors():
    parent_id = 89559261140097
    connection = _Connection()
    with mock.patch.object(chain, "get_db", return_value=connection), \
         mock.patch("creator_memory.record_run") as saved:
        chunks = chain.format_chain(_result(parent_id))
    body = "\n".join(chunks)
    assert "CHAIN — VARIANT" in body
    assert "Jabba No Chill Hip Hop Street Dance" in body
    assert "Jabba Urban Street Dance" in body
    assert "Streetwear Jabba Hip Hop Dance" not in body
    assert "streetwear" not in body.lower()
    assert "TikTok" not in body
    assert "ASSESSMENT & OPTIONS" in body
    saved.assert_called_once()
    assert saved.call_args.kwargs["item_id"] == parent_id
    assert saved.call_args.kwargs["asset_type"] == "emotes"
    assert connection.committed


def test_format_chain_non_variant_is_independent_of_prior_context():
    connection = _Connection()
    with mock.patch.object(chain, "get_db", return_value=connection), \
         mock.patch("creator_memory.record_run") as saved:
        chunks = chain.format_chain(_result())
    body = "\n".join(chunks)
    assert "CHAIN — \`Jabba No Chill Hip Hop Street Dance\`" in body
    assert "ASSESSMENT & OPTIONS" in body
    saved.assert_called_once()
    assert saved.call_args.kwargs["item_id"] is None


def test_error_result_never_touches_database():
    with mock.patch.object(
        chain, "get_db", side_effect=AssertionError("No DB on error")
    ):
        assert chain.format_chain({"error": "Market unavailable"}) == [
            "❌ Market unavailable"
        ]


if __name__ == "__main__":
    test_format_chain_executes_during_revive_without_name_errors()
    test_format_chain_non_variant_is_independent_of_prior_context()
    test_error_result_never_touches_database()
    print("PASS revival and standard chain renderer")
