"""
monitoring_config.py — Shared config for the monitoring system.

Excludes clothing categories so this bot only tracks UGC emotes, bundles,
accessories, hair, hats, face items. Not shirts/pants/jackets/shoes.
"""

# Roblox asset types the monitoring system will IGNORE
EXCLUDED_ASSET_IDS = {
    11, 12, 13,           # classic Shirt / Pants / T-Shirt
    64, 65, 66, 67, 68,   # layered: T-Shirt, Shirt, Pants, Jacket, Sweater
    69, 70, 71, 72,       # Shorts, Left Shoe, Right Shoe, Dress/Skirt
}


def is_excluded(asset_type_id) -> bool:
    try:
        return int(asset_type_id or 0) in EXCLUDED_ASSET_IDS
    except Exception:
        return False
