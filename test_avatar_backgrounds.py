"""Avatar Backgrounds (AssetType 92) category regressions.

All tests are offline: no Roblox requests, no production database, and no AI
provider calls. The marketplace probes used to validate AssetType 92 were
performed manually and are documented in the delivery notes.
"""
import os
import struct
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

os.environ.setdefault("ROBLOSECURITY_COOKIE", "test-cookie")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import avatar_backgrounds as ab  # noqa: E402
import category_configs as cc  # noqa: E402
import convergence_engine as ce  # noqa: E402
import original_concept_engine as oce  # noqa: E402
import product_understanding as pu  # noqa: E402
import scanner  # noqa: E402
import ugc_playbook  # noqa: E402
import vanta_conversation as vc  # noqa: E402

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, items=None, history=None):
        self.items = items or []
        self.history = history or []
        self.queries = []
        self.result = []
        self.connection = self

    def execute(self, sql, params=None):
        self.queries.append((str(sql), params))
        if "FROM item_history" in sql:
            self.result = self.history
        elif "FROM items" in sql:
            self.result = self.items
        else:
            self.result = []

    def fetchall(self):
        return list(self.result)

    def rollback(self):
        pass


def _sample_rows(n=25):
    rows = []
    for i in range(n):
        rows.append((
            1000 + i,
            f"Moonlit Shrine Background {i}",
            "moonlit shrine scene with soft glow",
            100 + i,
            50 + i * 10,
            i % 5,
            "User",
            f"Creator {i % 5}",
            NOW - timedelta(days=i + 1),
        ))
    return rows


def _history_rows():
    return [
        (1000, 50, NOW - timedelta(days=5)),
        (1000, 100, NOW),
        (1001, 100, NOW - timedelta(days=4)),
        (1001, 140, NOW),
    ]


def test_asset_type_92_and_alias_resolution():
    assert cc.detect_family_from_asset_type(92) == "backgrounds"
    assert cc.detect_family_from_asset_type("92") == "backgrounds"
    cfg = cc.get_category_config("backgrounds")
    assert cfg["asset_type_ids"] == [92]
    for alias in ("background", "backgrounds", "avatarbackground",
                  "avatar_background", "avatar backgrounds"):
        assert cc.resolve_family_name(alias) == "backgrounds", alias
    assert cc.to_convergence_family("backgrounds") == "backgrounds"
    assert cc.to_category_family("backgrounds") == "backgrounds"


def test_category_isolation_and_existing_families():
    expected_conv = {
        61: "emotes", 41: "hair", 8: "headwear", 42: "face",
        43: "neck", 46: "back", 45: "front", 19: "gear",
    }
    expected_category = {
        61: "emote", 41: "hair", 8: "headwear", 42: "face",
        43: "accessory", 46: "accessory", 45: "accessory", 19: "gear",
    }
    for asset_id, family in expected_conv.items():
        assert ce.family_for_asset(asset_id) == family, asset_id
        assert cc.detect_family_from_asset_type(asset_id) == (
            expected_category[asset_id]), asset_id
    assert ce.FAMILIES["backgrounds"] == [92]
    assert ce.family_for_asset(92) == "backgrounds"
    assert ce.resolve_family_ids("background") == [92]
    assert ce.resolve_family_ids("avatar_background") == [92]
    assert ce.resolve_family_ids("backgrounds") == [92]
    assert ce.resolve_family_ids("emote") == [61]
    assert ce.resolve_family_ids("hair") == [41]


def test_catalog_item_filter_rejects_other_types():
    background = {"id": 128422266252520, "assetType": 92, "itemType": "Asset"}
    hair = {"id": 451221329, "assetType": 41, "itemType": "Asset"}
    assert scanner.accepts_catalog_item(background, 92)
    assert not scanner.accepts_catalog_item(hair, 92)
    assert scanner.accepts_catalog_item(hair, 41)
    assert not scanner.accepts_catalog_item(background, 41)
    assert not scanner.accepts_catalog_item({"id": 1}, 92)


def test_background_discovery_query_uses_keyword_and_post_filter():
    with mock.patch.object(scanner, "get_dynamic_keywords", return_value=[]):
        queries = scanner.build_all_queries()
    background_queries = [
        q for q in queries if q.get("_asset_type_filter") == 92
    ]
    assert len(background_queries) == 1
    assert background_queries[0]["keyword"] == "avatar background"
    assert background_queries[0]["limit"] == 30


class _Resp:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = responses
        self.calls = 0
        self.params = []

    def get(self, url, params=None, timeout=None):
        self.params.append(dict(params or {}))
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


def test_rate_limited_discovery_filters_and_recovers():
    background = {"id": 128422266252520, "assetType": 92, "itemType": "Asset"}
    hair = {"id": 451221329, "assetType": 41, "itemType": "Asset"}
    session = _Session([
        _Resp(429, {"errors": [{"message": "rate limited"}]},
              {"Retry-After": "0"}),
        _Resp(200, {"data": [background, hair], "nextPageCursor": None}),
    ])
    old_get_session = scanner.get_session
    old_sleep = scanner.time.sleep
    scanner.get_session = lambda: session
    scanner.time.sleep = lambda *args: None
    try:
        found, ok = scanner.try_api(
            "https://example.invalid/catalog",
            {"keyword": "avatar background", "_asset_type_filter": 92},
        )
    finally:
        scanner.get_session = old_get_session
        scanner.time.sleep = old_sleep
    assert ok
    assert found == {128422266252520}
    assert session.calls == 2
    assert all("_asset_type_filter" not in params for params in session.params)


def test_market_analysis_uses_only_asset_type_92():
    cur = FakeCursor(items=_sample_rows(25), history=_history_rows())
    data = ab.analyze_market(cur, now=NOW)
    sql = "\n".join(query for query, _ in cur.queries)
    assert "asset_type_id = 92" in sql
    assert data["sample_n"] == 25
    assert data["evidence_status"] == "observed"
    assert data["prices"]["available"]
    assert data["favorites"]["available"]
    assert data["creators"]["unique"] == 5
    assert data["creators"]["identity_reliable"] is True
    assert data["favorite_velocity"]["available"] is True
    assert data["favorite_velocity"]["median_per_day"] > 0
    report = ab.format_market_report(data)
    assert "Avatar Backgrounds" in report
    assert "Favorites are not sales" in report
    assert "CTR" in report and "revenue" in report


def test_empty_and_small_category_handling():
    empty = ab.analyze_market(FakeCursor(), now=NOW)
    assert empty["sample_n"] == 0
    assert empty["evidence_status"] == "insufficient_evidence"
    assert empty["favorite_velocity"]["available"] is False
    assert any("Only 0 sampled" in line for line in empty["limitations"])

    small = ab.analyze_market(FakeCursor(items=_sample_rows(2)), now=NOW)
    assert small["sample_n"] == 2
    assert small["evidence_status"] == "insufficient_evidence"
    assert any("Only 2 sampled" in line for line in small["limitations"])


def _png(width=2560, height=1440, color_type=2, bit_depth=8, srgb=True):
    def chunk(tag, body):
        return (struct.pack(">I", len(body)) + tag + body
                + b"\x00\x00\x00\x00")
    ihdr = struct.pack(">IIBBBBB", width, height, bit_depth, color_type,
                       0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
    if srgb:
        data += chunk(b"sRGB", b"\x00")
    return data + chunk(b"IEND", b"")


def _jpeg(width=2560, height=1440):
    sof = (b"\x08" + struct.pack(">HH", height, width) + b"\x03"
           + b"\x01\x11\x00" * 3)
    return (b"\xff\xd8" + b"\xff\xc0" + struct.pack(">H", len(sof) + 2)
            + sof + b"\xff\xd9")


def _bmp(width=2560, height=1440, bpp=24):
    data = bytearray(54)
    data[0:2] = b"BM"
    struct.pack_into("<I", data, 2, 54)
    struct.pack_into("<I", data, 10, 54)
    struct.pack_into("<I", data, 14, 40)
    struct.pack_into("<ii", data, 18, width, height)
    struct.pack_into("<HH", data, 26, 1, bpp)
    struct.pack_into("<I", data, 30, 0)
    return bytes(data)


def _tga(width=2560, height=1440, bpp=24, image_type=2, alpha_bits=0):
    data = bytearray(18)
    data[2] = image_type
    struct.pack_into("<H", data, 12, width)
    struct.pack_into("<H", data, 14, height)
    data[16] = bpp
    data[17] = alpha_bits
    return bytes(data)


def test_image_validator_accepts_required_files():
    png = ab.validate_image(_png())
    assert png["ok"] and png["format"] == "PNG"
    assert png["width"] == 2560 and png["height"] == 1440
    assert png["rgb"] is True and png["alpha"] is False
    assert png["srgb"] is True

    jpeg = ab.validate_image(_jpeg())
    assert jpeg["ok"] and jpeg["format"] == "JPEG"
    assert jpeg["srgb"] is True

    bmp = ab.validate_image(_bmp())
    assert bmp["ok"] and bmp["format"] == "BMP"
    assert bmp["warnings"]

    tga = ab.validate_image(_tga())
    assert tga["ok"] and tga["format"] == "TGA"
    assert tga["warnings"]


def test_image_validator_rejects_wrong_size_alpha_and_format():
    wrong = ab.validate_image(_png(width=1920, height=1080))
    assert not wrong["ok"]
    assert any("2560x1440" in error for error in wrong["errors"])

    rgba = ab.validate_image(_png(color_type=6))
    assert not rgba["ok"]
    assert any("alpha" in error for error in rgba["errors"])

    bmp32 = ab.validate_image(_bmp(bpp=32))
    assert not bmp32["ok"]
    assert any("24-bit" in error for error in bmp32["errors"])

    tga32 = ab.validate_image(_tga(bpp=32, alpha_bits=8))
    assert not tga32["ok"]
    assert any("24-bit" in error for error in tga32["errors"])


def test_image_validator_rejects_unsupported_extension():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "background.gif"
        path.write_bytes(_png())
        result = ab.validate_image(path)
    assert not result["ok"]
    assert any("unsupported extension" in error for error in result["errors"])

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "background.png"
        path.write_bytes(_jpeg())
        mismatch = ab.validate_image(path)
    assert not mismatch["ok"]
    assert any("does not match" in error for error in mismatch["errors"])


def test_creative_brief_preserves_identity_and_scene_semantics():
    brief = ab.build_creative_brief("Moonlit Shrine", title="Moonlit Shrine")
    assert brief["category"] == "backgrounds"
    assert brief["identity_preserved"] is True
    assert "Moonlit Shrine" in brief["title_suggestions"][0]
    assert "Avatar Background" in brief["title_suggestions"][0]
    for key in ("composition", "lighting", "colour_palette", "atmosphere",
                "avatar_placement", "ground_horizon", "mobile_readability",
                "desktop_readability"):
        assert brief[key], key
    assert "movement_sequence" not in brief
    assert "wearable" not in str(brief).lower()
    assert brief["image_requirements"]["edge_fade"]


def test_vision_and_title_validation_do_not_require_motion():
    assert pu.motion_allowed("backgrounds") is False
    family, score = pu.classify_family("Moonlit Shrine Avatar Background")
    assert family == "backgrounds" and score > 0
    ok, reason = pu.validate_title(
        "Floating Sky Islands", "Floating Sky Islands",
        family="backgrounds")
    assert ok, reason


def test_dormant_m4_background_integration():
    old = os.environ.pop("PHASE2_M4_ENABLED", None)
    try:
        assert oce.m4_enabled() is False
    finally:
        if old is not None:
            os.environ["PHASE2_M4_ENABLED"] = old
    assert oce.resolve_concept_category("backgrounds") == "backgrounds"
    assert oce.resolve_concept_category("avatar_background") == "backgrounds"
    assert oce.CATEGORY_SPECS["backgrounds"]["asset_type_ids"] == [92]
    schema = oce._output_schema("backgrounds")["concepts"][0]
    assert "background_specification" in schema
    complete = {key: "value" for key in oce.BACKGROUND_SPEC_KEYS}
    assert oce._validate_background_spec(complete) == []
    assert oce._validate_background_spec({})


def test_conversation_and_playbook_recognize_backgrounds():
    assert vc.detect_family("make an avatar background") == "backgrounds"
    assert vc._convergence_family("backgrounds") == "backgrounds"
    assert ugc_playbook.resolve_topic("backgrounds") == "backgrounds"
    assert any("2560x1440" in tip
               for tip in ugc_playbook.TOPICS["backgrounds"])


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL {len(tests)} AVATAR BACKGROUND TESTS PASSED")
