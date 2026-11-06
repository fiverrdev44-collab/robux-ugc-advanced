"""VANTA 73 M3 opportunity-validation tests (synthetic, no production access)."""
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import opportunity_validation as ov  # noqa: E402

NOW = datetime(2026, 11, 6, 4, 0, tzinfo=timezone.utc)


def _dt(days_ago):
    return NOW - timedelta(days=days_ago)


def _item(item_id, favs, price, age_days, creator_id, creator_type,
          verified, name, creator_name):
    return {
        "id": item_id,
        "name": name,
        "favorite_count": favs,
        "price": price,
        "created_at": _dt(age_days) if age_days is not None else None,
        "creator_id": creator_id,
        "creator_type": creator_type,
        "creator_verified": verified,
        "creator_name": creator_name,
        "fetched_at": _dt(0),
    }


def _good_rows():
    return [
        _item(1, 10, 10, 1, 101, "User", True, "Floating A", "Alpha"),
        _item(2, 15, 12, 2, 102, "User", False, "Floating B", "Beta"),
        _item(3, 20, 15, 3, 103, "Group", None, "Floating C", "Gamma"),
        _item(4, 25, 18, 5, 101, "User", True, "Floating D", "Alpha"),
        _item(5, 30, 20, 8, 102, "User", False, "Floating E", "Beta"),
        _item(6, 40, 25, 12, 103, "Group", None, "Floating F", "Gamma"),
    ]


def _candidate(**overrides):
    base = {
        "keyword": "floating emote",
        "family": "emotes",
        "score": 62.5,
        "demand": 12,
        "supply": 6,
        "median_favs": 25.0,
        "p90_favs": 40.0,
        "recent": 3,
        "velocity": 2.0,
        "velocity_measured": True,
        "observations": 3,
        "stale": False,
        "freshness": "recent",
        "concentration": 0.4,
    }
    base.update(overrides)
    return base


def _live(**overrides):
    base = {
        "ok": True,
        "sampled_results": 30,
        "category_correct": 20,
        "category_mismatched": 10,
        "exact_title_matches": 1,
        "conceptual_matches": 8,
        "capped": False,
        "pages": 1,
        "sample_note": "first 60 results sampled",
        "verification_timestamp": NOW.isoformat(),
        "top_competitors": [],
    }
    base.update(overrides)
    return base


def _context(available=False):
    return {
        "generated_at": NOW.isoformat(),
        "registry": {"available": available, "creators": 0}
        if available else {"available": False, "reason": "missing_table"},
        "comparison": {"creators": 0} if available else {},
        "snapshot_coverage": {
            "recent_items": 6, "no_snapshots": 0,
            "valid_growth_items": 3,
        },
    }


def _sales(**overrides):
    base = {
        "available": False,
        "status": "unavailable",
        "attribution": None,
        "confirmed_units": None,
        "confirmed_robux": None,
        "window_days": 90,
        "window_end": NOW.isoformat(),
        "limitations": [ov.SALES_UNAVAILABLE],
    }
    base.update(overrides)
    return base


def _bundle(rows=None, live=None, context=None, sales=None, candidate=None,
            sample_window_days=180, undated_matches=0):
    return ov.build_evidence_bundle(
        candidate or _candidate(),
        live if live is not None else _live(),
        rows if rows is not None else _good_rows(),
        context if context is not None else _context(),
        sales if sales is not None else _sales(),
        sample_limit=200,
        sample_window_days=sample_window_days,
        undated_matches=undated_matches,
        now=NOW,
    )


def test_missing_registry_does_not_crash():
    bundle = _bundle(context=_context(False))
    assert bundle["creator"]["registry_available"] is False
    assert "creator_registry" in bundle["missing_evidence"]
    assert bundle["investigation_verdict"] in {
        ov.VERDICT_VALIDATE, ov.VERDICT_INVESTIGATE,
        ov.VERDICT_INSUFFICIENT, ov.VERDICT_REJECT}
    print("PASS missing creator registry")


def test_empty_registry():
    bundle = _bundle(context=_context(True))
    assert bundle["creator"]["registry_available"] is True
    assert bundle["creator"]["registry_comparison"]["creators"] == 0
    print("PASS empty creator registry")


def test_duplicate_creator_names_are_distinct_ids():
    rows = _good_rows()
    rows[0]["creator_id"] = 201
    rows[0]["creator_name"] = "Same"
    rows[1]["creator_id"] = 202
    rows[1]["creator_name"] = "Same"
    bundle = _bundle(rows=rows)
    assert bundle["creator"]["identified_creator_count"] >= 3
    dup = bundle["creator"]["duplicate_names_distinct_ids"]
    assert any("User:201" in d["creator_keys"]
               and "User:202" in d["creator_keys"] for d in dup)
    print("PASS duplicate names do not collapse identities")


def test_user_group_numeric_id_collision_stays_separate():
    rows = [
        _item(1, 10, 10, 1, 777, "User", True, "A", "One"),
        _item(2, 20, 12, 2, 777, "Group", True, "B", "Two"),
    ]
    bundle = _bundle(rows=rows)
    assert bundle["creator"]["identified_creator_count"] == 2
    print("PASS User/Group numeric-ID collision stays separate")


def test_numeric_ids_without_types_are_unresolved():
    rows = [_item(i, 10 + i, 10, 1, 500 + i, None, None,
                  f"I{i}", f"C{i}") for i in range(1, 4)]
    bundle = _bundle(rows=rows)
    assert bundle["creator"]["numeric_creator_count"] == 3
    assert bundle["creator"]["numeric_id_coverage_pct"] == 100.0
    assert bundle["creator"]["identified_creator_count"] == 0
    assert bundle["creator"]["resolved_composite_coverage_pct"] == 0.0
    assert bundle["creator"]["unknown_creator_type_items"] == 3
    assert bundle["investigation_verdict"] != ov.VERDICT_VALIDATE
    assert "creator_type_unknown" in bundle["missing_evidence"]
    print("PASS unknown creator types never become confirmed identities")


def test_three_known_composites_can_validate():
    bundle = _bundle()
    assert bundle["creator"]["numeric_creator_count"] == 3
    assert bundle["creator"]["identified_creator_count"] == 3
    assert bundle["creator"]["resolved_composite_coverage_pct"] == 100.0
    assert bundle["investigation_verdict"] == ov.VERDICT_VALIDATE
    print("PASS three confirmed composite identities can validate")


def test_same_numeric_id_user_group_remains_separate():
    rows = [
        _item(1, 10, 10, 1, 777, "User", True, "A", "One"),
        _item(2, 20, 12, 2, 777, "Group", True, "B", "Two"),
    ]
    bundle = _bundle(rows=rows)
    assert bundle["creator"]["numeric_creator_count"] == 1
    assert bundle["creator"]["identified_creator_count"] == 2
    assert bundle["creator"]["numeric_ids_with_multiple_types"] == [
        {"creator_id": 777, "types": ["Group", "User"]}]
    print("PASS User/Group collision keeps two confirmed composites")


def test_multiple_names_share_unresolved_numeric_id():
    rows = [
        _item(1, 10, 10, 1, 888, None, None, "A", "Name A"),
        _item(2, 20, 12, 2, 888, None, None, "B", "Name B"),
    ]
    bundle = _bundle(rows=rows)
    assert bundle["creator"]["numeric_creator_count"] == 1
    assert bundle["creator"]["identified_creator_count"] == 0
    unresolved = bundle["creator"]["unresolved_numeric_id_display_names"]
    assert unresolved and unresolved[0]["creator_id"] == 888
    assert set(unresolved[0]["display_names"]) == {"Name A", "Name B"}
    print("PASS duplicate display names do not resolve an unknown type")


def test_sample_window_metadata_matches_enforced_window():
    bundle = _bundle(sample_window_days=90, undated_matches=2)
    db = bundle["database"]
    assert db["sample_window_days"] == 90
    assert db["sample_window_enforced"] is True
    assert db["bounded_item_sample"]["window_days"] == 90
    assert db["bounded_item_sample"]["representative"] is False
    assert db["undated_matches_excluded"] == 2
    assert db["favorite_distribution"]["window_days"] == 90
    assert db["favorite_distribution"]["ordering"] == (
        "favorite_count_desc_convenience")
    assert db["item_age_distribution"]["missing_created_at_n"] == 2
    assert db["item_age_distribution"]["missing_created_at_included"] is False
    print("PASS reported sample window matches the enforced contract")


def test_missing_creator_ids():
    rows = [_item(i, 10 + i, 10, 1, None, None, None, f"I{i}", None)
            for i in range(1, 5)]
    bundle = _bundle(rows=rows)
    assert bundle["creator"]["identity_coverage_pct"] == 0.0
    assert bundle["creator"]["identified_creator_count"] == 0
    assert bundle["creator"]["unknown_identity_items"] == 4
    print("PASS missing creator IDs stay unknown")


def test_missing_verification():
    rows = [_item(i, 10 + i, 10, 1, 300 + i, "User", None,
                  f"I{i}", f"C{i}") for i in range(1, 4)]
    bundle = _bundle(rows=rows)
    assert bundle["creator"]["verification_counts"]["unknown"] == 3
    assert "unavailable" in bundle["creator"][
        "creator_verification_uncertainty"]
    print("PASS missing verification is uncertain")


def test_no_snapshots_and_one_snapshot_are_not_growth():
    for observations in (0, 1):
        bundle = _bundle(candidate=_candidate(
            velocity=None, velocity_measured=False,
            observations=observations, freshness="none"))
        assert bundle["database"]["snapshot_growth"]["measured"] is False
        assert bundle["database"]["snapshot_growth"]["velocity_per_day"] is None
        assert bundle["investigation_verdict"] != ov.VERDICT_VALIDATE
    print("PASS zero/one snapshot is unavailable growth, not zero growth")


def test_two_valid_snapshots_can_validate():
    bundle = _bundle(candidate=_candidate(
        velocity=2.0, velocity_measured=True, observations=4,
        freshness="recent", stale=False))
    assert bundle["database"]["snapshot_growth"]["measured"] is True
    assert bundle["database"]["snapshot_growth"]["snapshot_item_count"] == 4
    assert bundle["investigation_verdict"] == ov.VERDICT_VALIDATE
    print("PASS two valid snapshots support experimental validation")


def test_flat_or_negative_growth_is_not_positive():
    for velocity in (0.0, -1.0):
        bundle = _bundle(candidate=_candidate(
            velocity=velocity, velocity_measured=True, observations=3))
        assert bundle["investigation_verdict"] == ov.VERDICT_INSUFFICIENT
    print("PASS flat/negative growth does not become opportunity")


def test_high_favorites_without_sales_are_not_proven():
    rows = [dict(r) for r in _good_rows()]
    for r in rows:
        r["favorite_count"] = (r["favorite_count"] or 0) * 100
    bundle = _bundle(rows=rows, sales=_sales())
    assert bundle["sales"]["status"] == "unavailable"
    assert bundle["sales"]["confirmed_units"] is None
    text = ov.format_bundle(bundle)
    assert "Attributable sales evidence unavailable." in text
    assert "confirmed 0 units" not in text.lower()
    assert "profit" not in text.lower()
    assert "guaranteed" not in text.lower()

    no_growth = _bundle(
        rows=rows, sales=_sales(),
        candidate=_candidate(velocity=None, velocity_measured=False,
                             observations=0, freshness="none", recent=0))
    assert no_growth["investigation_verdict"] != ov.VERDICT_VALIDATE
    assert no_growth["sales"]["status"] == "unavailable"
    assert no_growth["sales"]["confirmed_units"] is None
    print("PASS high favorites do not fabricate sales or unsupported verdicts")


def test_creator_concentration_distortion():
    rows = [
        _item(1, 1000, 10, 1, 1, "User", True, "A", "A"),
        _item(2, 10, 10, 2, 2, "User", True, "B", "B"),
        _item(3, 10, 10, 3, 3, "User", True, "C", "C"),
    ]
    bundle = _bundle(rows=rows)
    assert "creator_concentration" in bundle["contradictory_evidence"]
    assert bundle["investigation_verdict"] != ov.VERDICT_VALIDATE
    print("PASS creator concentration downgrades")


def test_single_item_outlier_distortion():
    rows = [
        _item(1, 10000, 10, 1, 1, "User", True, "A", "A"),
        _item(2, 10, 10, 2, 2, "User", True, "B", "B"),
        _item(3, 10, 10, 3, 3, "User", True, "C", "C"),
    ]
    bundle = _bundle(rows=rows)
    assert "outlier_dependence" in bundle["contradictory_evidence"]
    assert bundle["investigation_verdict"] != ov.VERDICT_VALIDATE
    print("PASS single-item outlier downgrades")


def test_live_429_preserves_error_category():
    bundle = _bundle(live=_live(ok=False, error="rate limited (429)"))
    assert bundle["marketplace"]["available"] is False
    assert bundle["marketplace"]["error_category"] == "HTTP_429"
    assert bundle["investigation_verdict"] == ov.VERDICT_INSUFFICIENT
    print("PASS HTTP 429 is unavailable evidence")


def test_cached_marketplace_evidence_is_labeled():
    live = _live(cached=True, cache_age_seconds=12.5,
                 observed_at=NOW.isoformat(),
                 verification_timestamp=NOW.isoformat())
    bundle = _bundle(live=live)
    assert bundle["marketplace"]["cached"] is True
    assert bundle["marketplace"]["cache_age_seconds"] == 12.5
    text = ov.format_bundle(bundle)
    assert "cached" in text.lower()
    assert "12.50s" in text
    print("PASS cached marketplace evidence is labeled with age")


def test_partial_marketplace_results():
    bundle = _bundle(live=_live(deferred=True, retry_after=30))
    assert bundle["marketplace"]["partial"] is True
    assert bundle["investigation_verdict"] != ov.VERDICT_VALIDATE
    print("PASS partial marketplace results downgrade")


def test_capped_samples_are_not_population():
    bundle = _bundle(live=_live(capped=True))
    assert bundle["marketplace"]["capped"] is True
    assert "complete_marketplace_sample" in bundle["missing_evidence"]
    assert bundle["investigation_verdict"] != ov.VERDICT_VALIDATE
    print("PASS capped sample is not total supply")


def test_wrong_category_competitors():
    bundle = _bundle(live=_live(category_correct=0,
                                category_mismatched=30,
                                exact_title_matches=0,
                                conceptual_matches=0))
    assert bundle["investigation_verdict"] == ov.VERDICT_INSUFFICIENT
    print("PASS wrong-category results do not prove zero competition")


def test_stale_observations():
    bundle = _bundle(candidate=_candidate(stale=True, freshness="stale"))
    assert bundle["investigation_verdict"] != ov.VERDICT_VALIDATE
    assert "stale" in bundle["database"]["snapshot_growth"]["freshness"]
    print("PASS stale observations downgrade")


def test_missing_price():
    rows = _good_rows()
    for row in rows:
        row["price"] = None
    bundle = _bundle(rows=rows)
    assert bundle["database"]["price_distribution"]["sample_n"] == 0
    assert "price_evidence" in bundle["missing_evidence"]
    assert bundle["investigation_verdict"] != ov.VERDICT_VALIDATE
    print("PASS missing price remains missing")


def test_missing_creation_timestamp():
    rows = _good_rows()
    for row in rows:
        row["created_at"] = None
    bundle = _bundle(rows=rows)
    assert bundle["database"]["item_age_distribution"]["sample_n"] == 0
    assert "creation_timestamp_evidence" in bundle["missing_evidence"]
    assert bundle["investigation_verdict"] != ov.VERDICT_VALIDATE
    print("PASS missing creation timestamp remains missing")


def test_unresolved_sales_attribution():
    bundle = _bundle(sales=_sales(
        status="unavailable", limitations=["my_sales.asset_id missing"]))
    assert bundle["sales"]["status"] == "unavailable"
    assert "Attributable sales evidence unavailable." in ov.format_bundle(bundle)
    print("PASS unresolved sales are not zero sales")


def test_real_attributable_sales():
    bundle = _bundle(sales=_sales(
        available=True, status="confirmed", attribution="exact_asset_id",
        confirmed_units=5, confirmed_robux=500,
        limitations=["exact asset ID only"]))
    assert bundle["sales"]["status"] == "confirmed"
    assert bundle["sales"]["confirmed_units"] == 5
    assert "confirmed 5 units" in ov.format_bundle(bundle)
    print("PASS exact attributable sales are represented")


def test_conflicting_signals():
    bundle = _bundle(candidate=_candidate(demand=50, median_favs=10.0,
                                          recent=0))
    assert "high_autocomplete_weak_engagement" in bundle["contradictory_evidence"]
    assert bundle["investigation_verdict"] != ov.VERDICT_VALIDATE
    print("PASS conflicting autocomplete/engagement downgrades")


def test_empty_shortlist():
    text = ov.format_validation_report([], "emotes")
    assert "No qualifying candidates" in text
    assert "Verdict:" not in text
    print("PASS empty shortlist is valid")


def test_complete_bundle_contract_and_provenance():
    bundle = _bundle(sales=_sales(
        available=True, status="confirmed", attribution="exact_asset_id",
        confirmed_units=2, confirmed_robux=200,
        limitations=[]))
    required = {
        "candidate", "database", "marketplace", "creator", "sales",
        "source_timestamps", "missing_evidence", "contradictory_evidence",
        "confidence_limitations", "investigation_verdict", "verdict_reasons",
        "next_validation", "evidence",
    }
    assert required.issubset(bundle)
    assert bundle["source_timestamps"]["database_sampled_at"] == NOW.isoformat()
    assert bundle["database"]["snapshot_growth"]["measurement_window"]
    assert bundle["candidate"]["score_label"].startswith(
        "existing convergence heuristic")
    print("PASS complete evidence bundle with provenance")


class _RecordingCursor:
    def __init__(self, fetchall_values=None, fetchone_values=None):
        self.sql = []
        self._fetchall = list(fetchall_values or [])
        self._fetchone = list(fetchone_values or [])

    def execute(self, sql, params=None):
        self.sql.append((str(sql), params))

    def fetchall(self):
        return self._fetchall.pop(0) if self._fetchall else []

    def fetchone(self):
        return self._fetchone.pop(0) if self._fetchone else None

    def close(self):
        pass


def test_read_only_queries():
    rows = _good_rows()
    cur = _RecordingCursor(
        fetchall_values=[[(r["id"], r["name"], r["favorite_count"],
                           r["price"], r["created_at"], r["creator_id"],
                           r["creator_type"], r["creator_verified"],
                           r["creator_name"], r["fetched_at"])
                          for r in rows]],
        fetchone_values=[(1,)],
    )
    ov.fetch_item_sample(cur, "floating emote", "emotes", limit=10)
    for sql, _ in cur.sql:
        upper = sql.strip().upper()
        assert upper.startswith("SELECT") or upper.startswith("WITH")
        assert not any(word in upper for word in (
            "INSERT ", "UPDATE ", "DELETE ", "ALTER ", "DROP ", "TRUNCATE "))

    sales_cur = _RecordingCursor(
        fetchall_values=[[("asset_id",), ("sale_time",), ("amount_robux",)]],
        fetchone_values=[(2, 200, NOW, NOW), (1,)],
    )
    ov.fetch_sales_evidence(sales_cur, [1, 2], days=90, now=NOW)
    for sql, _ in sales_cur.sql:
        upper = sql.strip().upper()
        assert upper.startswith("SELECT") or upper.startswith("WITH")
        assert not any(word in upper for word in (
            "INSERT ", "UPDATE ", "DELETE ", "ALTER ", "DROP ", "TRUNCATE "))
    print("PASS M3 database reads are read-only")


def test_no_additional_network_requests():
    with patch.dict(os.environ, {ov.M3_FLAG_ENV: "1"}):
        with patch("convergence_live.verify_niche",
                   side_effect=AssertionError("network call attempted")):
            with patch("opportunity_validation.build_validation_bundles",
                       return_value=[_bundle()]):
                conn = type("C", (), {
                    "cursor": lambda self: _RecordingCursor(),
                    "close": lambda self: None})()
                text = ov.render_converge_report(
                    {}, {}, "emotes", lambda: conn, lambda *a: "legacy")
    assert "VANTA OPPORTUNITY VALIDATION" in text
    print("PASS no additional marketplace requests")


def test_feature_flag_defaults_off():
    with patch.dict(os.environ, {}, clear=True):
        assert ov.m3_enabled() is False
    with patch.dict(os.environ, {ov.M3_FLAG_ENV: "1"}):
        assert ov.m3_enabled() is True
    print("PASS M3 feature flag defaults OFF")


def test_legacy_behavior_flag_off():
    with patch.dict(os.environ, {ov.M3_FLAG_ENV: "0"}):
        def must_not_connect():
            raise AssertionError("M3 opened a DB connection when disabled")
        text = ov.render_converge_report(
            {"shortlist": []}, {}, "emotes", must_not_connect,
            lambda detailed, verified, family: "LEGACY")
    assert text == "LEGACY"
    print("PASS legacy !converge behavior when flag is OFF")


def test_safe_m3_behavior_flag_on_and_deterministic():
    with patch.dict(os.environ, {ov.M3_FLAG_ENV: "1"}):
        with patch("opportunity_validation.build_validation_bundles",
                   return_value=[_bundle()]):
            conn = type("C", (), {
                "cursor": lambda self: _RecordingCursor(),
                "close": lambda self: None})()
            first = ov.render_converge_report(
                {}, {}, "emotes", lambda: conn, lambda *a: "legacy")
            second = ov.render_converge_report(
                {}, {}, "emotes", lambda: conn, lambda *a: "legacy")
    assert first == second
    assert "VANTA OPPORTUNITY VALIDATION" in first
    assert "Verdict:" in first
    assert "creator_registry" in first
    assert "Attributable sales evidence unavailable." in first
    print("PASS flag ON report preserves missing-evidence limitations")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL {len(tests)} M3 TESTS PASSED")
