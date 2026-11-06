"""VANTA 73 M4 — original UGC concept generation and validation.

M4 is an additive creative layer over existing evidence. It reuses the M3
bounded item sample and optional M3 evidence, calls the existing AI provider
only when the user explicitly invokes !concept, and never performs Roblox
marketplace requests.

The module separates four kinds of claims:
- SAMPLED/OBSERVED database facts from the bounded item sample
- HEURISTIC signals inherited from M3
- PROPOSED creative hypotheses from the AI
- UNKNOWN measurements that remain explicitly unavailable

Text similarity is a safety aid, not proof of global originality or legal
clearance.
"""
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher

from astra import contains_banned_platform
from category_configs import (
    get_concept_vocab,
    get_filler_block,
    get_type_words_for,
)
from opportunity_validation import (
    build_category_context,
    count_undated_matches,
    fetch_item_sample,
    summarize_item_sample,
)

M4_FLAG_ENV = "PHASE2_M4_ENABLED"
SCHEMA_VERSION = "m4.original_concept.v1"
DEFAULT_SAMPLE_LIMIT = 200
DEFAULT_WINDOW_DAYS = 180
MAX_CONCEPTS = 3

CATEGORY_SPECS = {
    "emotes": {"label": "Emote / Dance", "asset_type_ids": [61],
               "kind": "emote"},
    "headwear": {"label": "Hat / Headwear", "asset_type_ids": [8],
                 "kind": "accessory"},
    "hair": {"label": "Hair", "asset_type_ids": [41], "kind": "accessory"},
    "face": {"label": "Face Accessory", "asset_type_ids": [42, 76, 77],
             "kind": "accessory"},
    "neck": {"label": "Neck Accessory", "asset_type_ids": [43],
             "kind": "accessory"},
    "shoulder": {"label": "Shoulder Accessory", "asset_type_ids": [44],
                 "kind": "accessory"},
    "front": {"label": "Front Accessory", "asset_type_ids": [45],
              "kind": "accessory"},
    "back": {"label": "Back Accessory", "asset_type_ids": [46],
             "kind": "accessory"},
    "waist": {"label": "Waist Accessory", "asset_type_ids": [47],
              "kind": "accessory"},
}

CATEGORY_ALIASES = {
    "emote": "emotes", "emotes": "emotes", "dance": "emotes",
    "animation": "emotes", "anim": "emotes",
    "hat": "headwear", "hats": "headwear", "cap": "headwear",
    "caps": "headwear", "crown": "headwear", "beanie": "headwear",
    "headwear": "headwear",
    "hair": "hair", "hairs": "hair",
    "face": "face", "mask": "face", "masks": "face",
    "glasses": "face", "eyewear": "face",
    "neck": "neck", "necklace": "neck", "chain": "neck",
    "collar": "neck",
    "shoulder": "shoulder", "shoulders": "shoulder",
    "front": "front", "chest": "front",
    "back": "back", "wings": "back", "wing": "back",
    "backpack": "back", "tail": "back",
    "waist": "waist", "belt": "waist", "belts": "waist",
}

SUPPORTED_CATEGORY_TEXT = (
    "emotes, headwear, hair, face, neck, shoulder, front, back, waist")

PROTECTED_TERMS = {
    "sonic", "mario", "luigi", "pokemon", "pikachu", "naruto", "sasuke",
    "hello kitty", "spider-man", "spiderman", "batman", "superman",
    "disney", "marvel", "minecraft", "fortnite", "squid game",
    "huggy wuggy", "among us", "roblox noob", "kpop demon hunters",
}

CLAIM_RE = re.compile(
    r"\b(guarantee(?:d)?|will sell|will buy|proven|profit|revenue|roi|"
    r"conversion|viral|top seller|official|licensed|copyrighted|trademark|"
    r"everyone will)\b",
    re.IGNORECASE)
UNIQUENESS_RE = re.compile(
    r"\b(guaranteed unique|globally unique|never seen before|"
    r"copyright[- ]safe|trademark[- ]free|legally clear(?:ed)?)\b",
    re.IGNORECASE)
MARKET_CONTEXT_RE = re.compile(
    r"\b(favorites?|sales?|sold|revenue|profit|demand|competitors?|market|"
    r"conversion|success|growth|audience|better)\b",
    re.IGNORECASE)
PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*%")
MULTIPLIER_RE = re.compile(r"\b\d+(?:\.\d+)?x\b", re.IGNORECASE)
MARKET_NUMBER_RE = re.compile(
    r"(\d[\d,.]*)\s*(favorites?|sales?|sold|revenue|profit|competitors?|"
    r"items?|creators?|demand|searches?)", re.IGNORECASE)
SALES_CLAIM_RE = re.compile(
    r"(\d[\d,.]*)\s*(sales?|sold|revenue)\b", re.IGNORECASE)
FAVORITE_CLAIM_RE = re.compile(
    r"(\d[\d,.]*)\s*favorites?\b", re.IGNORECASE)
CREATOR_CLAIM_RE = re.compile(
    r"(\d[\d,.]*)\s*(creators?|creator identities?)\b", re.IGNORECASE)
DEMAND_CLAIM_RE = re.compile(
    r"(\d[\d,.]*)\s*(demand|searches?|search volume)\b", re.IGNORECASE)
COMPETITOR_CLAIM_RE = re.compile(
    r"(\d[\d,.]*)\s*competitors?\b", re.IGNORECASE)

STOPWORDS = {
    "the", "and", "for", "with", "your", "you", "a", "an", "of", "in",
    "on", "to", "my", "is", "it", "as", "at", "by", "that", "this",
    "from", "into", "make", "made", "create", "original", "concept",
    "emote", "emotes", "dance", "hat", "hair", "face", "neck", "shoulder",
    "front", "back", "waist", "accessory", "item", "ugc",
}

REQUEST_SYNONYMS = (
    {"levitation", "levitate", "float", "floating", "weightless", "hover",
     "hovering", "zero", "gravity", "antigravity"},
    {"dance", "shuffle", "groove", "move", "movement", "choreography",
     "routine", "sway", "step"},
    {"futuristic", "cyber", "neon", "scifi", "sci", "tech", "holographic",
     "zero", "gravity"},
    {"cute", "kawaii", "sweet", "adorable", "pastel", "coquette", "soft"},
    {"strawberry", "berry", "strawberries"},
    {"crystal", "gem", "diamond", "jewel", "prism", "glass"},
    {"wings", "wing", "feather", "feathers", "flight", "angelic"},
    {"crown", "tiara", "diadem"},
    {"wizard", "mage", "magic", "magical", "sorcerer"},
    {"victory", "win", "winner", "triumph"},
    {"awkward", "funny", "silly", "goofy", "comic"},
)

EMOTE_SPEC_KEYS = (
    "core_movement_identity", "starting_pose", "movement_sequence",
    "body_part_actions", "rhythm_timing", "looping", "ending_pose",
    "personality", "r15_considerations", "animation_difficulties",
)

ACCESSORY_SPEC_KEYS = (
    "accessory_category", "theme", "shape_silhouette", "visual_elements",
    "materials", "color_palette", "distinctive_features",
    "avatar_compatibility", "modeling_complexity", "clipping_concerns",
    "studio_considerations", "title_options",
)

GENERIC_CONCEPT_WORDS = {
    "cool", "nice", "awesome", "good", "amazing", "special", "unique",
    "cute", "pretty", "beautiful", "epic", "best", "new", "trendy",
}

GENERIC_ANCHORS = GENERIC_CONCEPT_WORDS | {
    "themed", "style", "styled", "looking", "inspired", "roblox", "ugc",
    "item", "thing", "stuff", "concept", "idea",
}
MAX_SEARCH_TERMS = 4


def m4_enabled():
    return os.getenv(M4_FLAG_ENV, "0").strip().lower() in {
        "1", "true", "yes", "on"}


def resolve_concept_category(raw):
    key = str(raw or "").strip().lower()
    return CATEGORY_ALIASES.get(key)


def category_label(category):
    return CATEGORY_SPECS.get(category, {}).get("label", "UGC")


def extract_search_terms(category, request):
    """Bounded deterministic anchors from the request and category vocabulary.

    These are token-level anchors. They are never reported as exact-phrase
    matches, and generic/type/filler words are removed.
    """
    if category not in CATEGORY_SPECS:
        return []
    vocab = get_concept_vocab(category)
    filler = get_filler_block(category) | get_type_words_for(category)
    aliases = set(CATEGORY_ALIASES) | set(CATEGORY_ALIASES.values())
    scored = []
    seen = set()
    for index, token in enumerate(_tokens(request)):
        if (len(token) < 3 or token in STOPWORDS or token in filler
                or token in GENERIC_ANCHORS or token in aliases):
            continue
        if token in seen:
            continue
        seen.add(token)
        scored.append((0 if token in vocab else 1, index, token))
    scored.sort()
    return [token for _, _, token in scored[:MAX_SEARCH_TERMS]]


def _now_iso(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(
        timezone.utc).isoformat()


def _norm(text):
    return unicodedata.normalize("NFKC", str(text or "")).casefold()


def _squash(text):
    return re.sub(r"[^a-z0-9]+", "", _norm(text))


def _tokens(text):
    return re.findall(r"[a-z0-9]+", _norm(text))


def _similarity(left, right):
    a, b = _squash(left), _squash(right)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _jaccard(left, right):
    a = set(_tokens(left)) - STOPWORDS
    b = set(_tokens(right)) - STOPWORDS
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _contains_protected(text):
    normalized = " " + _norm(text) + " "
    for term in PROTECTED_TERMS:
        if " " in term:
            if f" {term} " in normalized:
                return True
        elif re.search(rf"\b{re.escape(term)}\b", normalized):
            return True
    return False


def _parse_number(value):
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _evidence_numbers(evidence, m3_bundle=None):
    values = set()

    def add(value):
        number = _parse_number(value)
        if number is not None:
            values.add(round(number, 4))

    for key in ("sample_n",):
        add(evidence.get(key))
    for dist_key in ("favorite_distribution", "price_distribution",
                     "item_age_distribution"):
        dist = evidence.get(dist_key) or {}
        for key in ("sample_n", "min", "p25", "median", "p75", "p90", "max"):
            add(dist.get(key))
    for key in ("last_14d", "last_30d", "sample_n"):
        add((evidence.get("recent_observations") or {}).get(key))
    creator = evidence.get("creator") or {}
    for key in ("numeric_creator_count", "identified_creator_count",
                "unknown_identity_items", "unknown_creator_type_items"):
        add(creator.get(key))
    for competitor in evidence.get("top_competitors") or []:
        add(competitor.get("favorites"))
        add(competitor.get("price"))
    sales = evidence.get("sales") or {}
    add(sales.get("confirmed_units"))
    add(sales.get("confirmed_robux"))
    marketplace = evidence.get("marketplace") or {}
    add(marketplace.get("category_correct"))
    add(marketplace.get("sampled_results"))
    for key in ("demand", "demand_live", "demand_volume"):
        add(evidence.get(key))
    if m3_bundle:
        for key in ("sample_size", "distribution_sample_size"):
            add((m3_bundle.get("database") or {}).get(key))
        add(((m3_bundle.get("database") or {}).get(
            "snapshot_growth") or {}).get("snapshot_item_count"))
        add(((m3_bundle.get("marketplace") or {}).get(
            "category_correct")))
        add(((m3_bundle.get("marketplace") or {}).get(
            "sampled_results")))
        add((m3_bundle.get("evidence") or {}).get("checks_available"))
    return values


def _claim_reasons(text, allowed_numbers):
    reasons = []
    if not text:
        return reasons
    if CLAIM_RE.search(text) or UNIQUENESS_RE.search(text):
        reasons.append("unsupported commercial/ownership claim")
    market_context = bool(MARKET_CONTEXT_RE.search(text))
    if market_context and MULTIPLIER_RE.search(text):
        reasons.append("unsupported multiplier claim")
    for match in MARKET_NUMBER_RE.finditer(text):
        number = _parse_number(match.group(1))
        if number is None:
            continue
        if round(number, 4) not in allowed_numbers:
            reasons.append(
                f"unsupported market metric: {match.group(0)}")
            break
    return reasons


def _request_alignment(request, concept_text):
    request_tokens = set(_tokens(request)) - STOPWORDS
    if not request_tokens:
        return True
    concept_tokens = set(_tokens(concept_text)) - STOPWORDS
    if request_tokens & concept_tokens:
        return True
    for group in REQUEST_SYNONYMS:
        if (request_tokens & group) and (concept_tokens & group):
            return True
    return False


def _competitor_similarity(concept_text, competitor_names):
    best = (0.0, None)
    for name in competitor_names:
        ratio = max(_similarity(concept_text, name),
                    _jaccard(concept_text, name))
        if ratio > best[0]:
            best = (ratio, name)
    return best


def _reproduces_phrase(text, competitor_names):
    text_tokens = set(_tokens(text)) - STOPWORDS
    for name in competitor_names:
        name_tokens = set(_tokens(name)) - STOPWORDS
        if len(name_tokens) >= 2 and name_tokens.issubset(text_tokens):
            return name
    return None


def _ai_text_fields(concept):
    fields = [
        concept.get("concept_name"),
        concept.get("original_description"),
        concept.get("intended_audience"),
        concept.get("design_specification"),
        concept.get("creative_differentiation"),
        concept.get("production_notes"),
        concept.get("creative_rationale"),
    ]
    for key in ("emote_specification", "accessory_specification"):
        spec = concept.get(key)
        if isinstance(spec, dict):
            for value in spec.values():
                if isinstance(value, (list, tuple)):
                    fields.extend(str(item) for item in value)
                else:
                    fields.append(str(value))
    return [str(text or "") for text in fields]


def _validate_claims(concept, allowed_numbers):
    for text in _ai_text_fields(concept):
        reasons = _claim_reasons(text, allowed_numbers)
        if reasons:
            return reasons
    experiment = str(concept.get("validation_experiment") or "")
    if CLAIM_RE.search(experiment):
        return ["unsupported commercial/ownership claim in validation plan"]
    return []


def _favorite_observations(evidence):
    values = set()
    dist = evidence.get("favorite_distribution") or {}
    for key in ("min", "p25", "median", "p75", "p90", "max"):
        number = _parse_number(dist.get(key))
        if number is not None:
            values.add(round(number, 4))
    for competitor in evidence.get("top_competitors") or []:
        number = _parse_number(competitor.get("favorites"))
        if number is not None:
            values.add(round(number, 4))
    return values


def _validate_metric_claims(concept, evidence):
    """Each factual metric may use only its own evidence category."""
    reasons = []
    sales = evidence.get("sales") or {}
    sales_confirmed = sales.get("status") == "confirmed"
    sales_units = _parse_number(sales.get("confirmed_units"))
    sales_robux = _parse_number(sales.get("confirmed_robux"))
    favorite_values = _favorite_observations(evidence)
    creator = evidence.get("creator") or {}
    confirmed_creators = _parse_number(
        creator.get("identified_creator_count")) or 0
    marketplace = evidence.get("marketplace") or {}
    category_correct = _parse_number(marketplace.get("category_correct"))
    demand_evidence = _parse_number(evidence.get("demand"))

    for text in _ai_text_fields(concept):
        for match in SALES_CLAIM_RE.finditer(text):
            number = _parse_number(match.group(1))
            noun = match.group(2).lower()
            if not sales_confirmed:
                reasons.append(
                    "sales claim without attributable sales evidence")
                break
            expected = sales_units if noun in ("sale", "sales", "sold") \
                else sales_robux
            if number is None or expected is None or round(number, 4) != round(
                    expected, 4):
                reasons.append(
                    f"sales claim not supported by attributable evidence: "
                    f"{match.group(0)}")
                break
        for match in FAVORITE_CLAIM_RE.finditer(text):
            number = _parse_number(match.group(1))
            if number is None or round(number, 4) not in favorite_values:
                reasons.append(
                    f"favorite claim without favorite observation: "
                    f"{match.group(0)}")
                break
        for match in CREATOR_CLAIM_RE.finditer(text):
            number = _parse_number(match.group(1))
            if (number is None or confirmed_creators <= 0
                    or round(number, 4) != round(confirmed_creators, 4)):
                reasons.append(
                    f"creator claim without confirmed composite evidence: "
                    f"{match.group(0)}")
                break
        for match in DEMAND_CLAIM_RE.finditer(text):
            number = _parse_number(match.group(1))
            if (number is None or demand_evidence is None
                    or round(number, 4) != round(demand_evidence, 4)):
                reasons.append(
                    f"demand claim without demand evidence: {match.group(0)}")
                break
        for match in COMPETITOR_CLAIM_RE.finditer(text):
            number = _parse_number(match.group(1))
            if (not marketplace.get("available")
                    or number is None or category_correct is None
                    or round(number, 4) != round(category_correct, 4)):
                reasons.append(
                    "competitor claim without sampled marketplace evidence: "
                    f"{match.group(0)}")
                break
        percentages = [m for m in PERCENT_RE.finditer(text)]
        if percentages:
            lowered = text.lower()
            if re.search(r"\b(original|unique|guaranteed|proven)\b", lowered):
                reasons.append("unsupported originality percentage claim")
                break
            allowed = set()
            if "concentration" in lowered:
                for key in ("creator_concentration_identified",
                            "creator_concentration_name_approx"):
                    number = _parse_number(creator.get(key))
                    if number is not None:
                        allowed.add(round(number * 100.0, 4))
            elif ("creator" in lowered or "identity" in lowered
                    or "coverage" in lowered):
                for key in ("resolved_composite_coverage_pct",
                            "numeric_id_coverage_pct"):
                    number = _parse_number(creator.get(key))
                    if number is not None:
                        allowed.add(round(number, 4))
            if not allowed:
                if MARKET_CONTEXT_RE.search(lowered):
                    reasons.append(
                        "percentage claim without a corresponding calculation")
                    break
                # Technical percentages (e.g. material transparency) are not
                # market claims and remain allowed.
                continue
            for match in percentages:
                number = _parse_number(match.group(0).replace("%", "").strip())
                if number is None or round(number, 4) not in allowed:
                    reasons.append(
                        f"percentage claim not supported by corresponding "
                        f"evidence: {match.group(0)}")
                    break
        if reasons:
            break
    return reasons


def _validate_emote_spec(spec):
    if not isinstance(spec, dict):
        return ["missing emote_specification"]
    reasons = []
    for key in EMOTE_SPEC_KEYS:
        if not str(spec.get(key) or "").strip():
            reasons.append(f"emote_specification.{key} missing")
    sequence = str(spec.get("movement_sequence") or "")
    if sequence and not re.search(r"\d", sequence):
        reasons.append("emote movement_sequence lacks timing detail")
    if sequence and len(sequence) < 30:
        reasons.append("emote movement_sequence too short")
    return reasons


def _validate_accessory_spec(spec):
    if not isinstance(spec, dict):
        return ["missing accessory_specification"]
    reasons = []
    for key in ACCESSORY_SPEC_KEYS:
        value = spec.get(key)
        if isinstance(value, (list, tuple)):
            if not value:
                reasons.append(f"accessory_specification.{key} missing")
        elif not str(value or "").strip():
            reasons.append(f"accessory_specification.{key} missing")
    return reasons


def _validate_required_text(concept):
    reasons = []
    required = (
        "concept_name", "original_description", "intended_audience",
        "design_specification", "creative_differentiation",
        "implementation_difficulty", "production_notes",
        "validation_experiment",
    )
    for key in required:
        if not str(concept.get(key) or "").strip():
            reasons.append(f"{key} missing")
    name = str(concept.get("concept_name") or "")
    if name and (len(name) < 3 or len(name) > 80):
        reasons.append("concept_name length out of bounds")
    description = str(concept.get("original_description") or "")
    if description and (len(description) < 20 or len(description) > 1500):
        reasons.append("original_description length out of bounds")
    tokens = [t for t in _tokens(name) if t not in STOPWORDS]
    if len(tokens) <= 1 and tokens and tokens[0] in GENERIC_CONCEPT_WORDS:
        reasons.append("generic single-word concept")
    return reasons


def _normalize_difficulty(value):
    text = str(value or "").strip().lower()
    if "low" in text:
        return "Low"
    if "medium" in text or "moderate" in text:
        return "Medium"
    if "high" in text:
        return "High"
    return None


def _validate_concept(raw, category, request, evidence, seen, allowed_ids,
                      allowed_numbers):
    if not isinstance(raw, dict):
        return None, ["concept is not an object"], []
    reasons = _validate_required_text(raw)
    difficulty = _normalize_difficulty(raw.get("implementation_difficulty"))
    if not difficulty:
        reasons.append("implementation_difficulty must be Low/Medium/High")
    spec = CATEGORY_SPECS[category]
    if spec["kind"] == "emote":
        reasons.extend(_validate_emote_spec(raw.get("emote_specification")))
    else:
        reasons.extend(_validate_accessory_spec(
            raw.get("accessory_specification")))
    reasons.extend(_validate_claims(raw, allowed_numbers))
    reasons.extend(_validate_metric_claims(raw, evidence))

    name = str(raw.get("concept_name") or "").strip()
    spec_payload = (raw.get("emote_specification")
                    or raw.get("accessory_specification") or {})
    spec_text_parts = []
    if isinstance(spec_payload, dict):
        for value in spec_payload.values():
            if isinstance(value, (list, tuple)):
                spec_text_parts.extend(str(item) for item in value)
            else:
                spec_text_parts.append(str(value or ""))
    combined = " ".join(
        [str(raw.get(k) or "") for k in (
            "concept_name", "original_description", "design_specification",
            "creative_differentiation")]
        + spec_text_parts)
    if _contains_protected(combined):
        reasons.append("contains a protected-character reference")
    if contains_banned_platform(combined):
        reasons.append("contains a banned platform reference")
    if not _request_alignment(request, combined):
        reasons.append("concept is unrelated to the user request")

    competitor_names = evidence.get("competitor_names") or []
    best_ratio, best_name = _competitor_similarity(name, competitor_names)
    if best_name and (_squash(name) == _squash(best_name)
                      or best_ratio >= 0.88):
        reasons.append(
            f"exact or near-duplicate of competitor title: {best_name}")
    reproduced = _reproduces_phrase(combined, competitor_names)
    if reproduced:
        reasons.append(
            f"reproduces distinctive competitor wording: {reproduced}")

    evidence_ids = raw.get("evidence_ids")
    if evidence_ids is None:
        evidence_ids = []
    if not isinstance(evidence_ids, list):
        reasons.append("evidence_ids must be a list")
        evidence_ids = []
    unknown_ids = [str(x) for x in evidence_ids if str(x) not in allowed_ids]
    if unknown_ids:
        reasons.append("unknown evidence_ids: " + ", ".join(unknown_ids[:3]))

    normalized_name = _squash(name)
    for prior in seen:
        if (normalized_name == prior["name"]
                or _similarity(name, prior["name"]) >= 0.85
                or _similarity(combined, prior["text"]) >= 0.90):
            reasons.append("duplicate concept within the response")
            break

    if reasons:
        return None, reasons, []

    similarity_risks = []
    if best_name and best_ratio >= 0.65:
        similarity_risks.append(
            f"Similar wording to competitor `{best_name}` "
            f"(text similarity {best_ratio:.2f}); manual review required.")
    similarity_risks.append(
        "Text similarity checks cannot prove global originality, copyright "
        "clearance, or trademark clearance.")

    extra_limitations = []
    registry = evidence.get("registry") or {}
    if not registry.get("available"):
        extra_limitations.append(
            "Creator Registry is unavailable; creator analysis is limited to "
            "the bounded item sample.")
    creator = evidence.get("creator") or {}
    if ((creator.get("unknown_creator_type_items") or 0) > 0
            or (creator.get("resolved_composite_coverage_pct") or 0) < 50):
        extra_limitations.append(
            "Creator identity/type coverage is incomplete; creator "
            "participation and concentration may be unreliable.")
    concept = {
        "concept_name": name,
        "category": category,
        "original_description": str(raw["original_description"]).strip(),
        "intended_audience": str(raw["intended_audience"]).strip(),
        "design_specification": str(raw["design_specification"]).strip(),
        "creative_differentiation": str(
            raw["creative_differentiation"]).strip(),
        "supporting_observations": evidence["supporting_observations"],
        "competition_findings": evidence["competition_findings"],
        "confidence_limitations": list(dict.fromkeys(
            list(evidence["limitations"]) + extra_limitations
            + similarity_risks)),
        "similarity_risks": similarity_risks,
        "implementation_difficulty": difficulty,
        "production_notes": str(raw["production_notes"]).strip(),
        "validation_experiment": str(raw["validation_experiment"]).strip(),
        "evidence_ids": (list(evidence_ids) if evidence_ids
                         else list(evidence.get("evidence_ids") or [])),
        "market_validation_status": evidence["market_validation_status"],
    }
    if spec["kind"] == "emote":
        concept["emote_specification"] = raw["emote_specification"]
    else:
        concept["accessory_specification"] = raw["accessory_specification"]
    if raw.get("creative_rationale"):
        concept["creative_rationale"] = str(
            raw["creative_rationale"]).strip()
    seen.append({"name": normalized_name, "text": combined})
    return concept, [], similarity_risks


def _supporting_observations(evidence, m3_bundle=None):
    observations = []
    sample_n = evidence.get("sample_n") or 0
    terms = evidence.get("query_terms") or []
    if terms:
        observations.append(
            "SAMPLED: Search anchors "
            + ", ".join(f"`{term}`" for term in terms)
            + " were matched at token level; this is not an exact-phrase "
            "match.")
    else:
        observations.append(
            "UNKNOWN: No safe search anchors survived generic/filler "
            "filtering; no item sample was queried.")
    if sample_n:
        observations.append(
            f"SAMPLED: {sample_n} matching {evidence.get('category')} items "
            f"in a bounded popularity sample "
            f"(last {evidence.get('sample_window_days')} days); median "
            f"favorites {evidence.get('median_favorites')}.")
        recent = evidence.get("recent_observations") or {}
        observations.append(
            f"SAMPLED: {recent.get('last_14d', 0)} of the sampled items "
            "were created in the last 14 days.")
        creator = evidence.get("creator") or {}
        observations.append(
            "SAMPLED: "
            f"{creator.get('identified_creator_count', 0)} confirmed composite "
            f"creators; identity coverage "
            f"{creator.get('resolved_composite_coverage_pct')}%; "
            f"{creator.get('unknown_creator_type_items', 0)} unresolved-type "
            "items.")
    else:
        observations.append(
            "UNKNOWN: No matching database observations were available; this "
            "concept is creatively proposed, not market-validated.")
    if evidence.get("undated_excluded_n"):
        observations.append(
            f"LIMITED: {evidence['undated_excluded_n']} matching items lacked "
            "creation timestamps and were excluded from the bounded sample.")
    sales = evidence.get("sales") or {}
    if sales.get("status") == "confirmed":
        observations.append(
            "OBSERVED: confirmed attributable sales "
            f"{sales.get('confirmed_units')} units / "
            f"{sales.get('confirmed_robux')} R$ via exact asset IDs.")
    else:
        observations.append(
            "UNKNOWN: Attributable sales evidence unavailable.")
    if m3_bundle:
        observations.append(
            f"HEURISTIC: M3 verdict {m3_bundle.get('investigation_verdict')}; "
            f"evidence quality "
            f"{(m3_bundle.get('evidence') or {}).get('quality')}.")
    return observations


def _competition_findings(evidence, m3_bundle=None):
    findings = []
    competitors = evidence.get("top_competitors") or []
    if competitors:
        names = ", ".join(
            f"{c.get('name')} ({c.get('favorites')}♥"
            + (f"; matched {', '.join(c.get('matched_terms') or [])}"
               if c.get("matched_terms") else "")
            + ")"
            for c in competitors[:3])
        findings.append(
            "SAMPLED: Observed competitors in the bounded token-matched item "
            f"sample: {names}.")
    else:
        findings.append(
            "UNKNOWN: No correct-category competitors were observed in the "
            "available sample; this is not proof of category-wide absence.")
    if m3_bundle:
        market = m3_bundle.get("marketplace") or {}
        if market.get("available"):
            findings.append(
                "SAMPLED: M3 observed "
                f"{market.get('category_correct')} correct-category results "
                f"from {market.get('sampled_results')} sampled marketplace "
                "results.")
            if (market.get("category_correct") or 0) == 0:
                findings.append(
                    "LIMITED: Zero correct-category matches in the observed "
                    "live sample; not proof that the category has no "
                    "competitors.")
            if market.get("capped"):
                findings.append(
                    "LIMITED: M3 marketplace sample was capped before the "
                    "catalog was exhausted.")
            if market.get("partial"):
                findings.append(
                    "LIMITED: M3 marketplace verification was partial.")
        else:
            findings.append(
                "UNKNOWN: M3 live verification was unavailable "
                f"({market.get('error_category') or 'not verified'}).")
    return findings


def _market_status(evidence, m3_bundle=None):
    if m3_bundle:
        verdict = str(m3_bundle.get("investigation_verdict") or "")
        if verdict == "VALIDATE EXPERIMENTALLY":
            return "EXPERIMENT CANDIDATE"
        if verdict == "INVESTIGATE":
            return "INVESTIGATE"
        if verdict in ("INSUFFICIENT EVIDENCE", "REJECT / AVOID"):
            return "EXPLORATORY"
    if not (evidence.get("sample_n") or 0):
        return "UNKNOWN"
    creator = evidence.get("creator") or {}
    recent = evidence.get("recent_observations") or {}
    if (evidence["sample_n"] >= 5
            and (creator.get("identified_creator_count") or 0) >= 3
            and (creator.get("resolved_composite_coverage_pct") or 0) >= 50
            and (recent.get("last_14d") or 0) > 0):
        return "INVESTIGATE"
    return "EXPLORATORY"


def collect_market_evidence(cur, category, request, sample_limit=(
        DEFAULT_SAMPLE_LIMIT), window_days=DEFAULT_WINDOW_DAYS,
        m3_bundle=None):
    spec = CATEGORY_SPECS.get(category)
    if spec is None:
        raise ValueError(f"unsupported category: {category}")
    terms = extract_search_terms(category, request)
    if terms:
        rows = fetch_item_sample(
            cur, family=category, limit=sample_limit,
            sample_window_days=window_days,
            asset_type_ids=spec["asset_type_ids"], terms=terms)
        undated = count_undated_matches(
            cur, family=category, limit=sample_limit,
            asset_type_ids=spec["asset_type_ids"], terms=terms)
    else:
        rows = []
        undated = {"count": 0, "capped": False, "limit": sample_limit}
    summary = summarize_item_sample(
        rows, sample_limit=sample_limit,
        undated_matches=undated.get("count", 0),
        undated_capped=undated.get("capped", False),
        sample_window_days=window_days)
    try:
        context = build_category_context(cur, category)
    except Exception as exc:
        context = {"registry": {"available": False,
                                "error": type(exc).__name__}}
    top = sorted(rows, key=lambda r: -int(r.get("favorite_count") or 0))[:5]

    def matched_terms(name):
        normalized = _norm(name)
        return [term for term in terms
                if re.search(rf"\b{re.escape(term)}\b", normalized)]

    evidence_ids = [f"db:item:{r['id']}" for r in top
                    if r.get("id") is not None]
    creator = summary["creator"]
    sales = dict((m3_bundle or {}).get("sales") or {})
    if not sales:
        sales = {
            "available": False, "status": "unavailable",
            "attribution": None, "confirmed_units": None,
            "confirmed_robux": None,
            "limitations": ["Attributable sales evidence unavailable."],
        }
    sales_limitations = list(sales.get("limitations") or [])
    limitations = [
        "Database observations are a bounded, popularity-ordered sample, not "
        "a complete category census.",
        "M4 did not make a live Roblox marketplace request; live verification "
        "is unavailable unless supplied through an M3 bundle.",
        "Text similarity cannot prove global originality or legal clearance.",
    ]
    if sales.get("status") == "confirmed":
        limitations.append(
            "Favorites are not sales; confirmed sales evidence is limited to "
            "exact attributable records.")
    else:
        limitations.append(
            "Favorites are not sales; attributable sales evidence is "
            "unavailable.")
    if terms:
        limitations.append(
            "Item matching is token-level OR matching on "
            + ", ".join(f"`{t}`" for t in terms)
            + "; it is not an exact-phrase match.")
    else:
        limitations.append(
            "No safe search anchors survived generic/filler filtering; no "
            "item sample was queried.")
    if not summary["sample_items"]:
        limitations.append(
            "No matching database observations were found; the creative "
            "concept is not market-validated.")
    if summary["undated_excluded_n"]:
        limitations.append(
            f"{summary['undated_excluded_n']} matching items without creation "
            "timestamps were excluded from the bounded sample.")
    if not (context.get("registry") or {}).get("available"):
        limitations.append(
            "Creator Registry is unavailable; creator identity is limited to "
            "the bounded item sample.")
    if m3_bundle:
        limitations.extend(m3_bundle.get("confidence_limitations") or [])
    evidence = {
        "schema_version": "m4.market_evidence.v1",
        "category": category,
        "category_label": spec["label"],
        "asset_type_ids": list(spec["asset_type_ids"]),
        "request": request,
        "query_terms": list(terms),
        "match_mode": "token_or_terms" if terms else "no_safe_anchor",
        "exact_phrase_match": False,
        "source": (
            "items table; bounded token-level OR sample; no live request"
            if terms else
            "items table; no safe search anchors; no live request"),
        "sample_window_days": window_days,
        "sample_n": summary["sample_items"],
        "undated_excluded_n": summary["undated_excluded_n"],
        "median_favorites": summary["favorite_distribution"].get("median"),
        "favorite_distribution": summary["favorite_distribution"],
        "recent_observations": summary["recent_observations"],
        "price_distribution": summary["price_distribution"],
        "item_age_distribution": summary["item_age_distribution"],
        "creator": creator,
        "registry": context.get("registry") or {"available": False},
        "marketplace": (m3_bundle or {}).get("marketplace")
        or {"available": False},
        "top_competitors": [{
            "id": r.get("id"),
            "name": r.get("name"),
            "favorites": int(r.get("favorite_count") or 0),
            "price": r.get("price"),
            "matched_terms": matched_terms(r.get("name")),
        } for r in top],
        "competitor_names": [r.get("name") for r in rows if r.get("name")],
        "evidence_ids": evidence_ids,
        "sales": sales,
        "limitations": list(dict.fromkeys(
            limitations + sales_limitations)),
        "evidence_status": "SAMPLED" if summary["sample_items"] else "UNKNOWN",
        "m3_verdict": (m3_bundle or {}).get("investigation_verdict"),
    }
    evidence["supporting_observations"] = _supporting_observations(
        evidence, m3_bundle)
    evidence["competition_findings"] = _competition_findings(
        evidence, m3_bundle)
    evidence["market_validation_status"] = _market_status(evidence, m3_bundle)
    return evidence


def _output_schema(category):
    spec = CATEGORY_SPECS[category]
    concept = {
        "concept_name": "string",
        "original_description": "string",
        "intended_audience": "hypothesis only",
        "design_specification": "string",
        "creative_differentiation": "string",
        "implementation_difficulty": "Low|Medium|High",
        "production_notes": "string",
        "validation_experiment": "specific bounded test",
        "evidence_ids": ["use only supplied evidence IDs"],
    }
    if spec["kind"] == "emote":
        concept["emote_specification"] = {
            key: "string" for key in EMOTE_SPEC_KEYS}
    else:
        concept["accessory_specification"] = {
            key: "string or string list" for key in ACCESSORY_SPEC_KEYS}
    return {"concepts": [concept]}


def _build_prompt(category, request, evidence, constraints=None,
                  m3_bundle=None):
    spec = CATEGORY_SPECS[category]
    evidence_summary = {
        "category": spec["label"],
        "asset_type_ids": spec["asset_type_ids"],
        "sample_n": evidence.get("sample_n"),
        "median_favorites": evidence.get("median_favorites"),
        "favorite_distribution": evidence.get("favorite_distribution"),
        "recent_observations": evidence.get("recent_observations"),
        "price_distribution": evidence.get("price_distribution"),
        "creator": evidence.get("creator"),
        "top_competitors": evidence.get("top_competitors"),
        "evidence_ids": evidence.get("evidence_ids"),
        "limitations": evidence.get("limitations"),
        "m3_verdict": evidence.get("m3_verdict"),
    }
    if m3_bundle:
        evidence_summary["m3"] = {
            "verdict": m3_bundle.get("investigation_verdict"),
            "evidence_quality": (m3_bundle.get("evidence") or {}).get(
                "quality"),
            "missing_evidence": m3_bundle.get("missing_evidence"),
            "marketplace": m3_bundle.get("marketplace"),
        }
    protected_note = ""
    if _contains_protected(request):
        protected_note = (
            "The request references a protected character. Do not reproduce "
            "its distinctive protected appearance, name, or branding; propose "
            "an independent original direction.\n")
    if spec["kind"] == "emote":
        spec_instruction = (
            "Provide an actionable R15 emote specification with a timestamped "
            "movement_sequence, starting pose, body-part actions, timing, "
            "looping behavior, ending pose, personality, R15 considerations, "
            "and animation difficulties. Do not reproduce a competitor's "
            "choreography.")
    else:
        spec_instruction = (
            "Provide a feasible accessory specification with silhouette, "
            "visual elements, materials, colors, distinctive features, avatar "
            "compatibility, modeling complexity, clipping risks, and Studio "
            "considerations. Do not claim the design is unique merely because "
            "its name differs.")
    constraints_text = (
        f"\nAdditional user constraints: {constraints}\n" if constraints else "")
    return f"""You are a Roblox UGC creative director. Generate original,
prototype-feasible concepts for the requested category.

Category: {spec['label']}
User request: {request}
{constraints_text}{protected_note}
EVIDENCE (use only these facts; never invent market metrics):
{json.dumps(evidence_summary, ensure_ascii=False, indent=2)}

RULES:
- Return 1 to {MAX_CONCEPTS} differentiated concepts, or an empty list if no
  safe concept can be produced.
- Every market observation must reference the supplied evidence IDs; do not
  claim sales, profit, guaranteed success, viral status, or ownership.
- Do not copy competitor titles, designs, or choreography.
- Clearly treat audience statements as hypotheses.
- {spec_instruction}
- Do not include hidden reasoning. Return JSON only.

OUTPUT JSON SHAPE:
{json.dumps(_output_schema(category), ensure_ascii=False, indent=2)}
"""


def _parse_json(raw):
    if isinstance(raw, dict):
        return raw
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None


def _default_ai_generator(prompt, **kwargs):
    from gemini_brain import _generate
    return _generate(prompt, json_mode=True, temperature=0.8,
                     max_tokens=2400)


def generate_concept_package(category, request, evidence,
                             ai_generator=None, constraints=None,
                             m3_bundle=None, now=None):
    generated_at = _now_iso(now)
    request = str(request or "").strip()
    base = {
        "schema_version": SCHEMA_VERSION,
        "category": category,
        "user_intent": request,
        "concepts": [],
        "evidence_status": evidence.get("evidence_status", "UNKNOWN"),
        "market_limitations": evidence.get("limitations") or [],
        "rejected_concepts": [],
        "generated_at": generated_at,
        "ai_status": "not_called",
        "error": None,
        "evidence": evidence,
    }
    if not request:
        base.update({"ai_status": "invalid_request",
                     "error": "creative request is empty"})
        return base
    allowed_ids = set(evidence.get("evidence_ids") or [])
    allowed_numbers = _evidence_numbers(evidence, m3_bundle)
    prompt = _build_prompt(category, request, evidence,
                           constraints=constraints, m3_bundle=m3_bundle)
    generator = ai_generator or _default_ai_generator
    try:
        raw = generator(prompt)
    except Exception as exc:
        base.update({"ai_status": "unavailable",
                     "error": f"AI provider unavailable: {type(exc).__name__}"})
        return base
    if raw is None or str(raw).strip() == "":
        base.update({"ai_status": "unavailable",
                     "error": "AI provider unavailable or timed out"})
        return base
    payload = _parse_json(raw)
    if not isinstance(payload, dict):
        base.update({"ai_status": "invalid_json",
                     "error": "AI response was not valid JSON"})
        return base
    raw_concepts = payload.get("concepts")
    if not isinstance(raw_concepts, list):
        base.update({"ai_status": "invalid_json",
                     "error": "AI response missing concepts list"})
        return base
    if not raw_concepts:
        base.update({"ai_status": "empty",
                     "error": None})
        return base
    concepts = []
    rejected = []
    seen = []
    for index, raw_concept in enumerate(raw_concepts):
        if index >= MAX_CONCEPTS:
            name = (raw_concept.get("concept_name")
                    if isinstance(raw_concept, dict) else f"concept {index + 1}")
            rejected.append({
                "concept_name": name,
                "reason": f"exceeds maximum of {MAX_CONCEPTS} concepts",
            })
            continue
        concept, reasons, _ = _validate_concept(
            raw_concept, category, request, evidence, seen, allowed_ids,
            allowed_numbers)
        if concept is None:
            name = (raw_concept.get("concept_name")
                    if isinstance(raw_concept, dict) else f"concept {index + 1}")
            rejected.append({
                "concept_name": name or f"concept {index + 1}",
                "reason": "; ".join(reasons),
            })
        else:
            concepts.append(concept)
    if m3_bundle:
        m3_limitations = list(m3_bundle.get("confidence_limitations") or [])
        m3_missing = list(m3_bundle.get("missing_evidence") or [])
        for concept in concepts:
            concept["confidence_limitations"] = list(dict.fromkeys(
                list(concept.get("confidence_limitations") or [])
                + m3_limitations
                + [f"Missing M3 evidence: {item}" for item in m3_missing]))
    base["concepts"] = concepts
    base["rejected_concepts"] = rejected
    base["ai_status"] = "generated" if concepts else "all_rejected"
    return base


def _format_emote_spec(spec):
    if not isinstance(spec, dict):
        return "unavailable"
    return (
        f"Core movement: {spec.get('core_movement_identity')}\n"
        f"Start: {spec.get('starting_pose')}\n"
        f"Sequence: {spec.get('movement_sequence')}\n"
        f"Body parts: {spec.get('body_part_actions')}\n"
        f"Timing: {spec.get('rhythm_timing')} · looping: {spec.get('looping')}\n"
        f"End: {spec.get('ending_pose')}\n"
        f"Personality: {spec.get('personality')}\n"
        f"R15 notes: {spec.get('r15_considerations')}\n"
        f"Animation risks: {spec.get('animation_difficulties')}")


def _format_accessory_spec(spec):
    if not isinstance(spec, dict):
        return "unavailable"
    def value(key):
        item = spec.get(key)
        if isinstance(item, (list, tuple)):
            return ", ".join(str(x) for x in item)
        return str(item or "unavailable")
    return (
        f"Category: {value('accessory_category')} · theme: {value('theme')}\n"
        f"Silhouette: {value('shape_silhouette')}\n"
        f"Visual elements: {value('visual_elements')}\n"
        f"Materials: {value('materials')} · palette: {value('color_palette')}\n"
        f"Distinctive features: {value('distinctive_features')}\n"
        f"Avatar compatibility: {value('avatar_compatibility')}\n"
        f"Modeling complexity: {value('modeling_complexity')}\n"
        f"Clipping risks: {value('clipping_concerns')}\n"
        f"Studio notes: {value('studio_considerations')}\n"
        f"Title options: {value('title_options')}")


def format_concept_report(result):
    if result.get("error"):
        return f"⚠️ M4 concept generation unavailable: {result['error']}"
    if not result.get("concepts"):
        lines = [
            "# 🎨 VANTA ORIGINAL CONCEPT",
            "No safe concepts passed validation. No concept was forced.",
        ]
        for rejected in (result.get("rejected_concepts") or [])[:4]:
            lines.append(
                f"• `{rejected.get('concept_name')}` — "
                f"{rejected.get('reason')}")
        lines.append(
            "_Similarity checks are textual only and cannot prove global "
            "originality or legal clearance._")
        return "\n".join(lines)
    category = result.get("category")
    lines = [f"# 🎨 VANTA ORIGINAL CONCEPT — {category_label(category)}"]
    lines.append(
        "_Creative proposals are clearly separated from sampled database "
        "evidence. Favorites are not sales._")
    for concept in result["concepts"]:
        lines.append("")
        lines.append(f"## {concept['concept_name']}")
        lines.append(f"Category: {category_label(category)}")
        lines.append(f"Creative Direction: {concept['original_description']}")
        if CATEGORY_SPECS[category]["kind"] == "emote":
            lines.append("Movement:\n" + _format_emote_spec(
                concept.get("emote_specification")))
        else:
            lines.append("Design:\n" + _format_accessory_spec(
                concept.get("accessory_specification")))
        lines.append(
            f"Audience Hypothesis: {concept['intended_audience']}")
        lines.append(
            "Evidence:\n" + "\n".join(
                f"• {x}" for x in concept.get("supporting_observations", [])))
        lines.append(
            "Competition:\n" + "\n".join(
                f"• {x}" for x in concept.get("competition_findings", [])))
        lines.append(
            f"Differentiation: {concept['creative_differentiation']}")
        lines.append(
            "Risks:\n" + "\n".join(
                f"• {x}" for x in concept.get("confidence_limitations", [])[:4]))
        lines.append(
            f"Implementation: {concept['implementation_difficulty']} · "
            f"{concept['production_notes']}")
        lines.append(
            f"Validation: {concept['validation_experiment']}")
        lines.append(
            f"Market Status: {concept['market_validation_status']}")
    rejected = result.get("rejected_concepts") or []
    if rejected:
        lines.append("")
        lines.append("Rejected:")
        for item in rejected[:3]:
            lines.append(
                f"• `{item.get('concept_name')}` — {item.get('reason')}")
    lines.append("")
    lines.append(
        "_Text similarity cannot prove global originality, copyright "
        "clearance, or trademark clearance._")
    return "\n".join(lines)


def render_concept_request(category, request, get_db, ai_generator=None,
                           constraints=None, m3_bundle=None,
                           sample_limit=DEFAULT_SAMPLE_LIMIT,
                           window_days=DEFAULT_WINDOW_DAYS):
    if not m4_enabled():
        return ("⚠️ M4 original concept generation is disabled. "
                "Set PHASE2_M4_ENABLED=1 in a controlled environment.")
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        evidence = collect_market_evidence(
            cur, category, request, sample_limit=sample_limit,
            window_days=window_days, m3_bundle=m3_bundle)
        result = generate_concept_package(
            category, request, evidence, ai_generator=ai_generator,
            constraints=constraints, m3_bundle=m3_bundle)
        return format_concept_report(result)
    except Exception as exc:
        return f"❌ M4 concept generation unavailable: {type(exc).__name__}"
    finally:
        try:
            if cur is not None:
                cur.close()
        except Exception:
            pass
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass
