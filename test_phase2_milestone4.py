"""VANTA 73 M4 original-concept engine tests (offline, synthetic evidence)."""
import asyncio
import copy
import json
import os
import sys
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import execution_policy as ep  # noqa: E402
import original_concept_engine as m4  # noqa: E402

NOW = datetime(2026, 11, 6, 16, 0, tzinfo=timezone.utc)


def _evidence(category="emotes", request=None, m3=None, **overrides):
    if request is None:
        request = ("smooth futuristic levitation dance" if category == "emotes"
                   else "fantasy crystal wings")
    if category == "back":
        top = [{"id": 2, "name": "Ember Plume", "favorites": 80,
                "price": 40}]
        competitor_names = ["Ember Plume", "Silver Halo"]
        evidence_ids = ["db:item:2"]
        median = 20.0
        sample_n = 7
        asset_ids = [46]
    else:
        top = [{"id": 1, "name": "Skyward Glide", "favorites": 120,
                "price": 50}]
        competitor_names = ["Skyward Glide", "Orbit Step"]
        evidence_ids = ["db:item:1"]
        median = 25.0
        sample_n = 8
        asset_ids = [61]
    base = {
        "schema_version": "m4.market_evidence.v1",
        "category": category,
        "category_label": m4.category_label(category),
        "asset_type_ids": asset_ids,
        "request": request,
        "source": "items table; bounded popularity sample; no live request",
        "sample_window_days": 180,
        "sample_n": sample_n,
        "undated_excluded_n": 0,
        "median_favorites": median,
        "favorite_distribution": {
            "available": True, "sample_n": sample_n, "min": 5,
            "p25": 10, "median": median, "p75": 40, "p90": 90,
            "max": 120, "top_item_share": 0.3,
        },
        "recent_observations": {"last_14d": 4, "last_30d": 6,
                                "sample_n": sample_n},
        "price_distribution": {"available": True, "sample_n": sample_n,
                               "min": 5, "median": 20, "p75": 40},
        "item_age_distribution": {"available": True, "sample_n": sample_n,
                                  "min": 1, "median": 5, "p75": 20},
        "creator": {
            "numeric_creator_count": 3,
            "identified_creator_count": 3,
            "unknown_identity_items": 0,
            "unknown_creator_type_items": 0,
            "resolved_composite_coverage_pct": 100.0,
            "numeric_id_coverage_pct": 100.0,
            "creator_concentration_identified": 0.4,
            "verification_counts": {"verified": 2, "nonverified": 1,
                                    "unknown": 0},
        },
        "registry": {"available": False, "reason": "missing_table"},
        "top_competitors": top,
        "competitor_names": competitor_names,
        "evidence_ids": evidence_ids,
        "limitations": [
            "Database observations are a bounded popularity sample.",
            "No live marketplace request was made by M4.",
            "Favorites are not sales.",
            "Text similarity cannot prove global originality or legal clearance.",
        ],
        "evidence_status": "SAMPLED",
        "m3_verdict": (m3 or {}).get("investigation_verdict"),
        "sales": {
            "available": False, "status": "unavailable",
            "confirmed_units": None, "confirmed_robux": None,
            "limitations": ["Attributable sales evidence unavailable."],
        },
        "marketplace": (m3 or {}).get("marketplace")
        or {"available": False},
    }
    base.update(overrides)
    base["supporting_observations"] = m4._supporting_observations(base, m3)
    base["competition_findings"] = m4._competition_findings(base, m3)
    base["market_validation_status"] = m4._market_status(base, m3)
    return base


def _emote_spec():
    return {
        "core_movement_identity": "Weightless lateral shuffle",
        "starting_pose": "Neutral R15 stance with knees slightly bent.",
        "movement_sequence": (
            "0.0-0.5s shift weight left; 0.5-1.2s right foot slides; "
            "1.2-1.8s torso leans back and arms rise; 1.8-2.4s recover."),
        "body_part_actions": "Hip shift, ankle slide, shoulder lift, head bob.",
        "rhythm_timing": "Two beats per side, 120 BPM.",
        "looping": "Loopable after 2.4 seconds.",
        "ending_pose": "Return to a balanced neutral stance.",
        "personality": "Playful, light, futuristic.",
        "r15_considerations": "Use R15 limb motors and verify foot contact.",
        "animation_difficulties": "Foot sliding and weight-shift timing.",
    }


def _emote_payload(name="Zero-Gravity Levitation Shuffle", description=None):
    if description is None:
        description = (
            "A smooth futuristic levitation dance that shifts weight into a "
            "short lateral slide and a controlled recovery.")
    return {"concepts": [{
        "concept_name": name,
        "original_description": description,
        "intended_audience": "Players who enjoy playful sci-fi dance emotes "
                             "(hypothesis).",
        "design_specification": (
            "R15 full-body levitation dance with controlled weight shift, "
            "lateral slide, and a clear recovery beat."),
        "creative_differentiation": (
            "The zero-gravity weight shift and lateral slide replace a "
            "standard wave-and-spin loop."),
        "implementation_difficulty": "Medium",
        "production_notes": "Prototype in R15; test foot contact and timing.",
        "validation_experiment": (
            "Prototype the first 3 seconds; compare with a matched dance "
            "emote; measure favorites and confirmed sales if available."),
        "evidence_ids": ["db:item:1"],
        "emote_specification": _emote_spec(),
        "creative_rationale": "Built from the requested levitation dance idea.",
    }]}


def _accessory_spec():
    return {
        "accessory_category": "Back accessory",
        "theme": "Fantasy crystal wings",
        "shape_silhouette": "Layered swept-back wing silhouette.",
        "visual_elements": "Faceted crystal shards and a central spine.",
        "materials": "Translucent crystal with metallic trim.",
        "color_palette": "Ice blue, violet, silver.",
        "distinctive_features": "Asymmetric crystal shard pattern.",
        "avatar_compatibility": "R15 and R6 back attachment.",
        "modeling_complexity": "Medium",
        "clipping_concerns": "Check shoulder and torso clipping during idle.",
        "studio_considerations": "Use separate transparent and opaque meshes.",
        "title_options": ["Astral Crystal Wing Harness", "Prism Wing Harness"],
    }


def _accessory_payload():
    return {"concepts": [{
        "concept_name": "Astral Crystal Wing Harness",
        "original_description": (
            "A fantasy crystal wings back accessory with layered translucent "
            "shards and a dark metallic spine."),
        "intended_audience": "Fantasy avatar stylists (hypothesis).",
        "design_specification": (
            "Crystal wing back accessory with asymmetric shards and a "
            "swept-back silhouette."),
        "creative_differentiation": (
            "Asymmetric crystal shards and a visible spine instead of a "
            "symmetric feather wing."),
        "implementation_difficulty": "Medium",
        "production_notes": "Prototype transparent materials and clipping.",
        "validation_experiment": (
            "Prototype the mesh; compare against three matched back "
            "accessories; measure favorites and confirmed sales if available."),
        "evidence_ids": ["db:item:2"],
        "accessory_specification": _accessory_spec(),
    }]}


def _generate(payload, evidence=None, category="emotes", request=None,
              now=NOW, m3=None):
    evidence = evidence or _evidence(category, request)
    if request is None:
        request = evidence["request"]
    return m4.generate_concept_package(
        category, request, evidence, m3_bundle=m3,
        ai_generator=lambda prompt: payload, now=now)


def test_category_resolution_and_supported_scope():
    assert m4.resolve_concept_category("emote") == "emotes"
    assert m4.resolve_concept_category("EMOTES") == "emotes"
    assert m4.resolve_concept_category("hat") == "headwear"
    assert m4.resolve_concept_category("wings") == "back"
    assert m4.resolve_concept_category("waist") == "waist"
    assert m4.resolve_concept_category("accessory") is None
    assert m4.resolve_concept_category("clothing") is None
    print("PASS category resolution and supported scope")


def test_normal_emote_request():
    result = _generate(_emote_payload())
    assert result["error"] is None
    assert len(result["concepts"]) == 1
    concept = result["concepts"][0]
    assert concept["category"] == "emotes"
    assert concept["emote_specification"]["movement_sequence"]
    assert concept["market_validation_status"] in {
        "INVESTIGATE", "EXPLORATORY", "EXPERIMENT CANDIDATE"}
    print("PASS normal emote request")


def test_normal_accessory_request():
    payload = _accessory_payload()
    result = _generate(payload, _evidence("back"), "back")
    assert result["error"] is None
    assert len(result["concepts"]) == 1
    concept = result["concepts"][0]
    assert concept["category"] == "back"
    assert concept["accessory_specification"]["shape_silhouette"]
    print("PASS normal accessory request")


def test_empty_request_and_ai_failures():
    empty = m4.generate_concept_package(
        "emotes", "", _evidence(), ai_generator=lambda prompt: None, now=NOW)
    assert empty["error"] == "creative request is empty"
    assert empty["concepts"] == []

    unavailable = _generate(None)
    assert unavailable["ai_status"] == "unavailable"
    assert unavailable["concepts"] == []

    def timeout(prompt):
        raise TimeoutError("AI timeout")

    timed_out = m4.generate_concept_package(
        "emotes", "levitation dance", _evidence(),
        ai_generator=timeout, now=NOW)
    assert timed_out["ai_status"] == "unavailable"
    assert timed_out["concepts"] == []
    print("PASS empty request and AI failure handling")


def test_invalid_json_and_missing_fields():
    invalid = _generate("not-json")
    assert invalid["ai_status"] == "invalid_json"
    assert invalid["concepts"] == []

    missing = _emote_payload()
    del missing["concepts"][0]["design_specification"]
    result = _generate(missing)
    assert result["concepts"] == []
    assert result["rejected_concepts"]
    assert "design_specification missing" in result["rejected_concepts"][0]["reason"]
    print("PASS invalid JSON and missing field rejection")


def test_missing_m3_evidence_and_creator_registry():
    result = _generate(_emote_payload())
    assert result["evidence_status"] == "SAMPLED"
    assert result["evidence"]["registry"]["available"] is False
    concept = result["concepts"][0]
    assert any("Creator Registry" in x for x in concept["confidence_limitations"])
    print("PASS missing M3 evidence and Creator Registry stay explicit")


def test_sparse_snapshots_and_http_429():
    m3 = {
        "investigation_verdict": "INSUFFICIENT EVIDENCE",
        "evidence": {"quality": "LOW"},
        "missing_evidence": ["measured_snapshot_growth"],
        "marketplace": {"available": False, "error_category": "HTTP_429"},
        "confidence_limitations": ["no qualifying snapshot pair"],
    }
    evidence = _evidence(m3=m3)
    result = _generate(_emote_payload(), evidence, m3=m3)
    concept = result["concepts"][0]
    assert concept["market_validation_status"] == "EXPLORATORY"
    assert any("HTTP_429" in x for x in concept["competition_findings"])
    assert any("no qualifying snapshot pair" in x
               for x in concept["confidence_limitations"])
    print("PASS sparse snapshots and HTTP 429 evidence")


def test_capped_marketplace_and_favorites_without_sales():
    m3 = {
        "investigation_verdict": "INSUFFICIENT EVIDENCE",
        "evidence": {"quality": "LOW"},
        "missing_evidence": ["complete_marketplace_sample"],
        "marketplace": {"available": True, "sampled_results": 30,
                        "category_correct": 0, "capped": True,
                        "partial": True},
        "confidence_limitations": ["live sample capped"],
    }
    evidence = _evidence(m3=m3)
    result = _generate(_emote_payload(), evidence, m3=m3)
    concept = result["concepts"][0]
    text = "\n".join(concept["competition_findings"])
    assert "Zero correct-category matches" in text
    assert "capped" in text.lower()
    assert any("Favorites are not sales" in x
               for x in concept["confidence_limitations"])
    print("PASS capped marketplace and favorites without sales")


def test_exact_and_near_duplicate_titles():
    exact = _emote_payload(name="Skyward Glide")
    result = _generate(exact)
    assert result["concepts"] == []
    assert "near-duplicate" in result["rejected_concepts"][0]["reason"]

    near = _emote_payload(name="Skyward Glider")
    result = _generate(near)
    assert result["concepts"] == []
    print("PASS exact and near-duplicate competitor titles rejected")


def test_copied_choreography_and_accessory_design():
    payload = _emote_payload()
    payload["concepts"][0]["emote_specification"]["movement_sequence"] = (
        "0.0-0.5s Skyward Glide sequence with a lateral slide; "
        "0.5-1.0s recover.")
    result = _generate(payload)
    assert result["concepts"] == []
    assert "reproduces distinctive competitor wording" in (
        result["rejected_concepts"][0]["reason"])

    accessory = _accessory_payload()
    accessory["concepts"][0]["design_specification"] = (
        "A direct copy of the Ember Plume silhouette.")
    result = _generate(accessory, _evidence("back"), "back")
    assert result["concepts"] == []
    print("PASS copied choreography and accessory design rejected")


def test_unrelated_substituted_concept():
    payload = _emote_payload(
        name="Strawberry Crown Delight",
        description="A cute strawberry crown accessory with no movement.")
    item = payload["concepts"][0]
    item["design_specification"] = (
        "A strawberry crown accessory with a rounded silhouette.")
    item["creative_differentiation"] = "A sweet crown shape."
    item["emote_specification"] = {
        "core_movement_identity": "Strawberry crown pose",
        "starting_pose": "Stands still.",
        "movement_sequence": (
            "0.0-0.5s stands; 0.5-1.0s tilts head; 1.0-1.5s returns."),
        "body_part_actions": "Head tilt only.",
        "rhythm_timing": "Slow.",
        "looping": "Non-looping.",
        "ending_pose": "Stands still.",
        "personality": "Sweet.",
        "r15_considerations": "Head movement only.",
        "animation_difficulties": "Minimal.",
    }
    result = _generate(payload)
    assert result["concepts"] == []
    assert any("unrelated" in r["reason"]
               for r in result["rejected_concepts"])
    print("PASS unrelated substituted concept rejected")


def test_duplicate_concepts_and_three_concept_limit():
    first = _emote_payload("Orbit Waltz",
                           "A levitation dance with wide circular arms.")
    second = copy.deepcopy(first)
    duplicate = {"concepts": first["concepts"] + second["concepts"]}
    result = _generate(duplicate)
    assert len(result["concepts"]) == 1
    assert result["rejected_concepts"]

    names = ["Orbit Waltz", "Gravity Bloom", "Hover Skip", "Weightless Drift"]
    descriptions = [
        "A levitation dance with wide circular arms.",
        "A levitation dance that unfolds from a low crouch.",
        "A levitation dance made of light skipping steps.",
        "A levitation dance with slow floating turns.",
    ]
    concepts = []
    for name, description in zip(names, descriptions):
        item = _emote_payload(name, description)["concepts"][0]
        item["design_specification"] += f" Distinct beat pattern: {name}."
        item["creative_differentiation"] += f" Unique timing for {name}."
        item["emote_specification"]["core_movement_identity"] = (
            f"{name} weight-shift identity")
        item["emote_specification"]["movement_sequence"] = (
            f"0.0-0.5s {name} shifts weight; 0.5-1.2s {name} slides; "
            "1.2-1.8s arms rise; 1.8-2.4s recover.")
        concepts.append(item)
    result = _generate({"concepts": concepts})
    assert len(result["concepts"]) == 3
    assert any("maximum" in r["reason"]
               for r in result["rejected_concepts"])
    print("PASS duplicate concepts rejected and max three enforced")


def test_search_anchor_extraction_is_bounded_and_generic_safe():
    assert m4.extract_search_terms(
        "emotes", "smooth futuristic levitation dance") == [
            "smooth", "futuristic", "levitation"]
    assert m4.extract_search_terms("emotes", "cool hat") == []
    assert m4.extract_search_terms("emotes", "dance emote") == []
    assert m4.extract_search_terms(
        "back", "fantasy crystal wings") == ["crystal", "fantasy"]
    print("PASS search anchors are bounded, deterministic, and generic-safe")


def test_token_matching_is_labelled_not_exact_phrase():
    evidence = _evidence(
        query_terms=["smooth", "levitation"],
        match_mode="token_or_terms", exact_phrase_match=False,
        top_competitors=[{"id": 1, "name": "Smooth Levitation",
                          "favorites": 120, "price": 50,
                          "matched_terms": ["smooth", "levitation"]}])
    observations = m4._supporting_observations(evidence)
    findings = m4._competition_findings(evidence)
    assert evidence["exact_phrase_match"] is False
    assert any("token level" in x and "not an exact-phrase" in x
               for x in observations)
    assert any("matched smooth, levitation" in x for x in findings)
    print("PASS token-level matches are labelled, not exact phrase")


def test_metric_specific_cross_metric_collisions():
    sales_payload = _emote_payload(description="The niche has 8 sales.")
    assert _generate(sales_payload)["concepts"] == []

    creator_evidence = _evidence(creator={
        "numeric_creator_count": 8,
        "identified_creator_count": 3,
        "unknown_identity_items": 0,
        "unknown_creator_type_items": 0,
        "resolved_composite_coverage_pct": 37.5,
        "numeric_id_coverage_pct": 100.0,
        "creator_concentration_identified": 0.4,
        "verification_counts": {"verified": 2, "nonverified": 1,
                                "unknown": 0},
    })
    creator_payload = _emote_payload(
        description="8 creators already participate.")
    assert _generate(creator_payload, creator_evidence)["concepts"] == []

    favorites_payload = _emote_payload(description="Only 8 favorites.")
    assert _generate(favorites_payload)["concepts"] == []

    competitor_payload = _emote_payload(
        description="8 competitors were observed.")
    assert _generate(competitor_payload)["concepts"] == []

    demand_payload = _emote_payload(description="8 searches per day.")
    assert _generate(demand_payload)["concepts"] == []

    confirmed = _evidence(sales={
        "available": True, "status": "confirmed",
        "confirmed_units": 5, "confirmed_robux": 500,
        "limitations": [],
    })
    confirmed_payload = _emote_payload(
        description="The niche has 5 confirmed sales.")
    assert len(_generate(confirmed_payload, confirmed)["concepts"]) == 1

    hypothetical = _emote_payload()
    hypothetical["concepts"][0]["validation_experiment"] = (
        "Measure confirmed sales after launch against a matched cohort.")
    assert len(_generate(hypothetical)["concepts"]) == 1

    coverage_payload = _emote_payload(
        description="The niche has 100% creator coverage.")
    assert len(_generate(coverage_payload)["concepts"]) == 1
    concentration_payload = _emote_payload(
        description="The niche has 100% creator concentration.")
    assert _generate(concentration_payload)["concepts"] == []
    print("PASS metric-specific claims reject cross-metric collisions")


def test_unsupported_sales_and_invented_metrics():
    for text in (
            "This guarantees sales and profit.",
            "This will sell 10,000 favorites.",
            "A 90% proven conversion winner.",
            "This is 10x better than competitors."):
        payload = _emote_payload(description=text)
        result = _generate(payload)
        assert result["concepts"] == [], text
    print("PASS unsupported sales and invented metrics rejected")


def test_unsupported_audience_claim():
    payload = _emote_payload()
    payload["concepts"][0]["intended_audience"] = (
        "Guaranteed all players will buy this.")
    result = _generate(payload)
    assert result["concepts"] == []
    assert any("commercial" in r["reason"]
               for r in result["rejected_concepts"])
    print("PASS unsupported audience claim rejected")


def test_emote_and_accessory_spec_completeness():
    payload = _emote_payload()
    del payload["concepts"][0]["emote_specification"]["r15_considerations"]
    assert _generate(payload)["concepts"] == []

    accessory = _accessory_payload()
    del accessory["concepts"][0]["accessory_specification"]["materials"]
    result = _generate(accessory, _evidence("back"), "back")
    assert result["concepts"] == []
    print("PASS emote and accessory specification completeness")


def test_evidence_provenance_and_audience_label():
    result = _generate(_emote_payload())
    concept = result["concepts"][0]
    assert concept["evidence_ids"] == ["db:item:1"]
    assert all("SAMPLED" in x for x in concept["supporting_observations"]
               if "observed" in x.lower() or "matching" in x.lower())
    text = m4.format_concept_report(result)
    assert "Audience Hypothesis" in text
    assert "Validation:" in text
    assert "Market Status:" in text
    assert "Favorites are not sales" in text
    print("PASS evidence provenance and audience hypothesis labeling")


def test_missing_evidence_is_exploratory():
    evidence = _evidence(
        sample_n=0, median_favorites=None,
        favorite_distribution={"available": False, "sample_n": 0},
        recent_observations={"last_14d": 0, "last_30d": 0, "sample_n": 0},
        price_distribution={"available": False, "sample_n": 0},
        item_age_distribution={"available": False, "sample_n": 0},
        creator={
            "numeric_creator_count": 0, "identified_creator_count": 0,
            "unknown_identity_items": 0, "unknown_creator_type_items": 0,
            "resolved_composite_coverage_pct": 0,
            "verification_counts": {"verified": 0, "nonverified": 0,
                                    "unknown": 0},
        },
        top_competitors=[], competitor_names=[], evidence_ids=[],
        evidence_status="UNKNOWN",
        limitations=["No matching database observations; no live request."])
    payload = _emote_payload()
    payload["concepts"][0]["evidence_ids"] = []
    result = _generate(payload, evidence)
    concept = result["concepts"][0]
    assert result["evidence_status"] == "UNKNOWN"
    assert concept["market_validation_status"] == "UNKNOWN"
    assert any("No matching database observations" in x
               for x in concept["supporting_observations"])
    print("PASS missing evidence remains exploratory")


def test_creator_uncertainty_and_graceful_failure():
    evidence = _evidence(creator={
        "numeric_creator_count": 4, "identified_creator_count": 0,
        "unknown_identity_items": 1, "unknown_creator_type_items": 3,
        "resolved_composite_coverage_pct": 0,
        "verification_counts": {"verified": 0, "nonverified": 0,
                                "unknown": 4},
    })
    result = _generate(_emote_payload(), evidence)
    concept = result["concepts"][0]
    assert concept["market_validation_status"] != "EXPERIMENT CANDIDATE"
    assert any("unresolved-type" in x
               for x in concept["supporting_observations"])
    print("PASS creator uncertainty remains visible")


def test_banned_platform_and_protected_terms():
    for name, description in (
            ("TikTok Levitation Shuffle",
             "A TikTok viral levitation dance."),
            ("Sonic Crystal Wings",
             "A fantasy crystal wings accessory inspired by Sonic.")):
        payload = _emote_payload(name=name, description=description)
        result = _generate(payload)
        assert result["concepts"] == [], name
    print("PASS banned platform and protected-character references rejected")


def test_empty_candidates_and_rejected_report():
    result = _generate({"concepts": []})
    assert result["concepts"] == []
    assert result["ai_status"] == "empty"
    text = m4.format_concept_report(result)
    assert "No safe concepts" in text
    print("PASS empty candidate set is an honest result")


def test_m3_flag_on_off_does_not_change_generation():
    for flag in ("0", "1"):
        with mock.patch.dict(os.environ, {"PHASE2_M3_ENABLED": flag}):
            result = _generate(_emote_payload())
        assert len(result["concepts"]) == 1
    print("PASS M4 works with M3 flag ON or OFF")


def test_deterministic_validation_and_format():
    first = _generate(_emote_payload())
    second = _generate(_emote_payload())
    assert first["concepts"] == second["concepts"]
    assert first["rejected_concepts"] == second["rejected_concepts"]
    assert first["generated_at"] == second["generated_at"]
    text = m4.format_concept_report(first)
    assert text == m4.format_concept_report(second)
    print("PASS deterministic validation and formatting")


def test_safe_discord_chunking():
    result = _generate(_emote_payload())
    text = m4.format_concept_report(result)
    chunks = [text[i:i + 1900] for i in range(0, len(text), 1900)]
    assert chunks
    assert all(len(chunk) <= 1900 for chunk in chunks)
    print("PASS safe Discord output chunking")


class FakeBot:
    def __init__(self):
        self.commands = {}

    def command(self, name=None, **kwargs):
        def decorator(fn):
            self.commands[name or kwargs.get("name")] = fn
            return fn
        return decorator


class FakeCtx:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append(content)


def test_feature_flag_off_and_on_command():
    from commands_concept import register_concept_commands

    with mock.patch.dict(os.environ, {"PHASE2_M4_ENABLED": "0"}):
        bot = FakeBot()
        register_concept_commands(bot, lambda: None)
        ctx = FakeCtx()
        asyncio.run(bot.commands["concept"](ctx, text="emotes | levitation"))
        assert any("disabled" in str(x).lower() for x in ctx.sent)

    with mock.patch.dict(os.environ, {"PHASE2_M4_ENABLED": "1"}):
        bot = FakeBot()
        register_concept_commands(bot, lambda: None)
        ctx = FakeCtx()
        with mock.patch("commands_concept.render_concept_request",
                        return_value="OK") as render:
            asyncio.run(bot.commands["concept"](
                ctx, text="emotes | levitation dance"))
        assert render.called
        assert "OK" in ctx.sent
    print("PASS M4 feature flag OFF and ON command behavior")


def test_unsupported_and_empty_command_requests():
    from commands_concept import register_concept_commands

    with mock.patch.dict(os.environ, {"PHASE2_M4_ENABLED": "1"}):
        bot = FakeBot()
        register_concept_commands(bot, lambda: None)
        with mock.patch("commands_concept.render_concept_request",
                        side_effect=AssertionError("must not generate")):
            for text in ("clothing | shirt", "accessory | wings",
                         "emotes | ", "just a request"):
                ctx = FakeCtx()
                asyncio.run(bot.commands["concept"](ctx, text=text))
                assert ctx.sent
    print("PASS unsupported and empty command requests are rejected")


def test_existing_command_registration_unchanged():
    from commands_concept import register_concept_commands

    bot = FakeBot()
    for name in ("brainstorm", "chain", "revive", "converge"):
        bot.commands[name] = object()
    register_concept_commands(bot, lambda: None)
    for name in ("brainstorm", "chain", "revive", "converge", "concept"):
        assert name in bot.commands
    assert ep.classify("concept") == ep.AI_REASONING
    print("PASS existing command registration remains intact")


def test_no_extra_marketplace_network_calls():
    with mock.patch("convergence_live.verify_niche",
                    side_effect=AssertionError("network call attempted")):
        result = _generate(_emote_payload())
    assert result["concepts"]
    print("PASS M4 makes no marketplace network calls")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_")]
    for test in tests:
        test()
    print(f"ALL {len(tests)} M4 TESTS PASSED")
