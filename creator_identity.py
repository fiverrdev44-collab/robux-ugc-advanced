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


def _creator_type(value):
    """Return only the explicit Roblox creator types, canonicalised."""
    text = _optional_text(value)
    if not text:
        return None
    lowered = text.lower()
    if lowered == "user":
        return "User"
    if lowered == "group":
        return "Group"
    return None


def catalog_identity(payload):
    """Identity from raw catalog rows or normalized batch-client dictionaries.

    Precedence policy: direct Roblox fields (creatorTargetId / creatorType /
    creatorHasVerifiedBadge) are authoritative because they are the original
    source evidence. Normalized fields (creator_id / creator_type /
    creator_verified) are used only when the raw field is absent or invalid.
    If both forms disagree, the raw value wins; contradictory normalized data
    is ignored rather than merged or invented.
    """
    raw_badge = payload.get("creatorHasVerifiedBadge")
    normalized_badge = payload.get("creator_verified")
    if isinstance(raw_badge, bool):
        verified = raw_badge
    elif isinstance(normalized_badge, bool):
        verified = normalized_badge
    else:
        verified = None

    raw_type = _creator_type(payload.get("creatorType"))
    normalized_type = _creator_type(payload.get("creator_type"))
    raw_id = _positive_int(payload.get("creatorTargetId"))
    normalized_id = _positive_int(payload.get("creator_id"))

    return {
        "creator_id": raw_id if raw_id is not None else normalized_id,
        "creator_type": raw_type if raw_type is not None else normalized_type,
        "creator_verified": verified,
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
