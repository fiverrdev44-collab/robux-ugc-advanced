"""Shared creator-identity parsing for every ingestion path.

The Roblox catalog details/search responses expose creator identity differently
from the economy details response. These helpers preserve only values the API
actually supplied: missing IDs/types stay NULL, and verification stays tri-state
(True / False / None). They never invent a User/Group type or a False badge.
"""


def _positive_int(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _optional_text(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def catalog_identity(payload):
    """Identity from catalog details/search rows (creatorTargetId fields)."""
    badge = payload.get("creatorHasVerifiedBadge")
    return {
        "creator_id": _positive_int(payload.get("creatorTargetId")),
        "creator_type": _optional_text(payload.get("creatorType")),
        "creator_verified": badge if isinstance(badge, bool) else None,
    }


def economy_identity(payload):
    """Identity from economy /v2/assets/{id}/details rows, when present."""
    creator = payload.get("Creator") or {}
    if not isinstance(creator, dict):
        creator = {}
    badge = payload.get("creatorHasVerifiedBadge")
    return {
        "creator_id": _positive_int(
            creator.get("Id")
            or creator.get("TargetId")
            or creator.get("CreatorTargetId")
        ),
        "creator_type": _optional_text(
            creator.get("CreatorType")
            or creator.get("Type")
            or payload.get("CreatorType")
        ),
        "creator_verified": badge if isinstance(badge, bool) else None,
    }


def has_creator_type(cur):
    """True only when the additive M2 items.creator_type column exists."""
    try:
        cur.execute(
            "select 1 from information_schema.columns "
            "where table_schema = current_schema() "
            "and table_name = 'items' and column_name = 'creator_type'")
        return cur.fetchone() is not None
    except Exception:
        return False
