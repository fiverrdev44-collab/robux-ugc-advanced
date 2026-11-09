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
import market_xray  # noqa: E402
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


class EarlyCursor:
    """Routes background early-winner queries without touching a database."""

    def __init__(self, candidates=None, history=None):
        self.candidates = candidates or []
        self.history = history or []
        self.queries = []
        self.result = []
        self.connection = self

    def execute(self, sql, params=None):
        self.queries.append((str(sql), params))
        if "WITH candidates AS" in sql:
            self.result = self.candidates
        elif "FROM item_history" in sql and "item_id = ANY" in sql:
            self.result = self.history
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


def _early_candidates():
    return [
        (101, "Moonlit Shrine Avatar Background", "alice", 1000, 150,
         5.0, NOW - timedelta(days=5), 92, 4),
        (102, "Neon Rain City Background", "", 500, 0,
         3.0, NOW - timedelta(days=3), 92, 3),
        (103, "Cozy Library Background", "carol", 50, 25,
         1.0, NOW - timedelta(days=1), 92, 1),
    ]


def _early_history():
    return [
        (101, 400, NOW - timedelta(days=5)),
        (101, 600, NOW - timedelta(days=3)),
        (101, 800, NOW - timedelta(days=1)),
        (101, 1000, NOW),
        (102, 100, NOW - timedelta(days=3)),
        (102, 150, NOW - timedelta(days=2)),
        (102, 250, NOW),
        (103, 50, NOW - timedelta(hours=12)),
    ]


def test_background_early_winners_use_measured_growth_only():
    cur = EarlyCursor(candidates=_early_candidates(), history=_early_history())
    data = ab.find_background_early_winners(cur, days=7, now=NOW)
    assert data["status"] == "ok"
    assert data["candidate_window"] == 3
    assert data["usable_history"] == 2
    assert data["coverage_pct"] == 66.7
    assert [item["id"] for item in data["ranked"]] == [101, 102]
    assert all(item["asset_type_id"] == 92 for item in data["ranked"])

    first = data["ranked"][0]
    assert first["measured_favorites_gained"] == 600
    assert first["measured_favs_per_day"] == 120.0
    assert first["lifetime_favs_per_day"] == 200.0
    assert first["measured_favs_per_day"] != first["lifetime_favs_per_day"]
    assert first["observations"] == 4
    assert first["observation_days"] == 5.0
    assert first["acceleration_favs_per_day"] == 100.0
    assert first["price"] == 150
    assert first["creator"] == "alice"
    assert first["url"] == "https://www.roblox.com/catalog/101"
    assert first["observation_period"].startswith("20")
    assert first["thumbnail_request_url"].startswith(
        "https://thumbnails.roblox.com/v1/assets")
    assert "assetIds=101" in first["thumbnail_request_url"]
    assert first["visual_analysis"] == "not_analyzed"

    second = data["ranked"][1]
    assert second["measured_favorites_gained"] == 150
    assert second["measured_favs_per_day"] == 50.0
    assert second["price"] is None
    assert second["creator"] == ""
    assert any("price unavailable" in warning
               for warning in second["missing_data"])

    assert data["text_themes"]
    assert {theme["theme"] for theme in data["text_themes"]} >= {
        "moonlit", "shrine"}
    assert data["visual_analysis"]["status"] == "not_analyzed"
    assert data["insufficient_count"] == 1

    item_queries = [sql for sql, _ in cur.queries if "FROM items" in sql]
    assert len(item_queries) == 1
    assert "asset_type_id = 92" in item_queries[0]
    assert len(cur.queries) == 2

    report = ab.format_background_early_winners(data, days=7)
    assert "BACKGROUND EARLY WINNERS" in report
    assert "R$150" in report
    assert "creator unavailable" in report
    assert "price unavailable" in report
    assert "lifetime avg" in report
    assert "Text-derived title themes (not visual analysis)" in report
    assert "Visual image analysis is not enabled" in report
    assert "No CTR" in report


def test_background_early_winners_insufficient_history_is_honest():
    candidate = _early_candidates()[2]
    cur = EarlyCursor(
        candidates=[candidate],
        history=[(103, 50, NOW - timedelta(hours=12))],
    )
    data = ab.find_background_early_winners(cur, days=7, now=NOW)
    assert data["status"] == "insufficient_history"
    assert data["ranked"] == []
    assert data["candidate_window"] == 1
    assert data["usable_history"] == 0
    assert data["coverage_pct"] == 0.0
    assert data["insufficient_count"] == 1
    report = ab.format_background_early_winners(data, days=7)
    assert "No background had at least two valid favorite observations" in report
    assert "No ranking is claimed" in report
    assert len(cur.queries) == 1


def test_background_early_winners_empty_category_has_no_fallback():
    cur = EarlyCursor(candidates=[], history=[])
    data = ab.find_background_early_winners(cur, days=7, now=NOW)
    assert data["status"] == "no_recent_backgrounds"
    assert data["ranked"] == []
    assert len(cur.queries) == 1
    assert "asset_type_id = 92" in cur.queries[0][0]
    report = ab.format_background_early_winners(data, days=7)
    assert "No Avatar Backgrounds were published" in report
    assert "No ranking is claimed" in report


def test_background_early_winners_price_and_creator_labels():
    cur = EarlyCursor(candidates=_early_candidates(), history=_early_history())
    data = ab.find_background_early_winners(cur, days=7, now=NOW)
    report = ab.format_background_early_winners(data, days=7)
    assert "R$150" in report
    assert "by `alice`" in report
    assert "price unavailable" in report
    assert "creator unavailable" in report
    assert "500 current favorites" in report


def test_convergence_clause_and_xray_section():
    clause, params = ce._family_clause("backgrounds")
    assert "asset_type_id in (%s)" in clause
    assert params == [92]
    clause, params = ce._family_clause("background")
    assert params == [92]
    clause, params = ce._family_clause("avatar backgrounds")
    assert params == [92]

    cur = FakeCursor(items=_sample_rows(25), history=_history_rows())
    xray = {
        "health": {},
        "categories": [],
        "backgrounds": ab.analyze_market(cur, now=NOW),
    }
    report = market_xray.format_xray(xray)
    assert "Avatar Backgrounds" in report
    assert "Favorites are not sales" in report


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


def test_background_discovery_filters_and_defers_on_429():
    background = {"id": 128422266252520, "assetType": 92, "itemType": "Asset"}
    hair = {"id": 451221329, "assetType": 41, "itemType": "Asset"}
    session = _Session([])
    calls = []
    class Response:
        status_code = 200
        def json(self):
            return {"data": [background, hair], "nextPageCursor": None}
    with mock.patch.object(scanner, "get_session", return_value=session), \
         mock.patch.object(scanner, "shared_circuit_open", return_value=False), \
         mock.patch.object(scanner, "safe_get", side_effect=lambda endpoint, url, **kwargs: (calls.append(kwargs), Response())[1]):
        found, ok = scanner.try_api("https://example.invalid/catalog",
                                  {"keyword": "avatar background", "_asset_type_filter": 92})
    assert ok and found == {128422266252520}
    assert len(calls) == 1
    assert all("_asset_type_filter" not in kwargs.get("params", {}) for kwargs in calls)

    class Limited:
        status_code = 429
    calls.clear()
    with mock.patch.object(scanner, "get_session", return_value=session), \
         mock.patch.object(scanner, "shared_circuit_open", return_value=False), \
         mock.patch.object(scanner, "safe_get", side_effect=lambda *args, **kwargs: (calls.append(kwargs), Limited())[1]):
        found, ok = scanner.try_api("https://example.invalid/catalog",
                                  {"keyword": "avatar background", "_asset_type_filter": 92})
    assert found == set() and not ok and len(calls) == 1



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
