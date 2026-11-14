"""Avatar Background artwork intelligence: grounded, low-cost decision support.

Pure helpers only; callers handle image IO, AI and live API budget. AI vision
descriptions are observations to verify, not proof of an on-platform claim.
"""
import re
from background_niche import SCENE_ANCHORS
from product_understanding import validate_title

_SOURCE_MAX = 220
_FILLER = {
    "a", "an", "and", "the", "with", "at", "in", "on", "of", "for", "by",
    "is", "it", "to", "from", "my", "your", "our", "their", "avatar",
    "background", "backgrounds", "scene", "roblox", "ugc", "beautiful",
    "awesome", "stunning", "viral", "trending", "popular", "picture",
    "image", "this", "that", "style", "featuring", "has", "have", "there",
}
_BAD_SCENE_PARTS = {
    "ignore", "instructions", "assistant", "developer", "system", "prompt",
    "token", "password", "secret", "key", "execute", "javascript", "python",
}
_SCENE_FALLBACKS = ("shrine", "forest", "city", "space", "sky", "garden",
                    "portal", "room", "street", "beach", "cave", "castle")
_ALLOWED_OBS = (
    "visual_summary", "search_description", "composition_notes",
    "visual_colors", "visual_style", "distinctive_features",
    "visual_mood", "ip_reference_warning", "scene_focal_point",
    "avatar_clearance_notes", "ground_horizon_notes",
    "mobile_readability_notes", "depth_layers_notes",
    "lighting_notes",
)


def _short_text(value, max_chars=_SOURCE_MAX):
    """Treat model output as untrusted data: bound length and strip markup."""
    if isinstance(value, (list, dict)):
        return ""
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()
    return re.sub(r"\s+", " ", value).replace("\`", "")[:max_chars]


def _items(value, limit=4):
    if not isinstance(value, (list, tuple)):
        value = [value] if isinstance(value, str) else []
    return [_short_text(v, 54) for v in value[:limit] if _short_text(v, 54)]


def _is_untrusted_instruction(text):
    words = set(re.findall(r"[a-z]+", (text or "").lower()))
    return bool(words & _BAD_SCENE_PARTS)


def observations(vision):
    """Bound and normalize selected fields only, never accept arbitrary JSON."""
    v = vision if isinstance(vision, dict) else {}
    out = {}
    for key in _ALLOWED_OBS:
        out[key] = (_items(v.get(key))
                    if key in ("visual_colors", "visual_style",
                               "distinctive_features", "visual_mood")
                    else _short_text(v.get(key)))
    return out


def scene_phrase(vision, notes=""):
    """A conservative two- or three-word phrase, NOT a demand prediction."""
    o = observations(vision)
    # A verified contradiction takes precedence over the creator's proposed
    # keywords. We do not keep searching for a scene that the image passes
    # consistently contradicted.
    if isinstance(vision, dict) and vision.get("visual_scene_disagreement"):
        anchor = _short_text(vision.get("visual_scene_anchor"), 70)
        if anchor and not _is_untrusted_instruction(anchor):
            return anchor
    # Prefer creator notes, then visual description, and never guess a place
    # that neither the creator nor the vision provider mentioned.
    candidates = [_short_text(notes, 300), o["search_description"],
                  o["visual_summary"]] + o["distinctive_features"]
    for text in candidates:
        if _is_untrusted_instruction(text):
            continue
        toks = re.findall(r"[a-z]+", text.lower())
        for i, tok in enumerate(toks):
            if tok not in SCENE_ANCHORS and tok not in _SCENE_FALLBACKS:
                continue
            previous = (toks[i - 1] if i else "")
            following = (toks[i + 1] if i + 1 < len(toks) else "")
            if previous and previous not in _FILLER and len(previous) > 2:
                return f"{previous} {tok}"
            if following and following not in _FILLER and len(following) > 2:
                return f"{tok} {following}"
            return tok
    return None


def grounded_concept(vision, notes=""):
    """Conservative input for !chain; never claim visual facts are verified."""
    o = observations(vision)
    # Creator notes have priority; model annotations are clearly separated.
    user = _short_text(notes, 260)
    summary = o["visual_summary"]
    if _is_untrusted_instruction(summary):
        summary = ""
    features = [x for x in o["distinctive_features"]
                if not _is_untrusted_instruction(x)][:4]
    descriptors = [x for x in o["visual_colors"][:3] + o["visual_style"][:2]
                   if not _is_untrusted_instruction(x)]
    parts = []
    if user:
        parts.append(user)
    if summary:
        parts.append("AI image observations (check against artwork): " + summary)
    if features:
        parts.append("Reported visible details: " + ", ".join(features))
    if descriptors:
        parts.append("Reported colors/style: " + ", ".join(descriptors))
    return ". ".join(parts)[:580].strip(" .")


def candidate_titles(vision, notes="", limit=6, live=None):
    """Grounded candidate names; no CTR or uniqueness scoring fabricated."""
    o = observations(vision)
    seed = scene_phrase(vision, notes)
    if not seed:
        return []
    seed_words = seed.title()
    candidates = [
        f"{seed_words} Background",
        f"{seed_words} Avatar Background",
    ]
    features = o["distinctive_features"]
    for f in features[:4]:
        if _is_untrusted_instruction(f):
            continue
        words = [w for w in re.findall(r"[a-z]+", f.lower())
                 if w not in _FILLER and w not in _BAD_SCENE_PARTS]
        if not words:
            continue
        # A feature-based title must keep the original scene identity.
        prefix = " ".join(words[:2]).title()
        if prefix.lower() not in seed.lower() and len(prefix.split()) <= 2:
            candidates.append(f"{prefix} {seed_words} Background")
    # Avoid recommending an exact copy of a verified sampled listing.
    # This is NOT a marketplace-wide uniqueness check.
    known_titles = {row["name"].casefold()
                    for row in verified_background_competitors(live)}
    seen, out = set(), []
    for title in candidates:
        if len(title.split()) > 7 or len(title) > 65:
            continue
        key = title.casefold()
        if key in seen or key in known_titles:
            continue
        ok, _ = validate_title(notes, title, family="backgrounds")
        if not ok:
            continue
        seen.add(key)
        out.append(title)
        if len(out) >= max(1, min(limit, 8)):
            break
    return out


def listing_description(vision, notes=""):
    """Truthful short listing copy from observed details, not conversion hype."""
    anchor = scene_phrase(vision, notes)
    if not anchor:
        return None
    obs = observations(vision)
    details = []
    for feature in obs["distinctive_features"]:
        if _is_untrusted_instruction(feature):
            continue
        words = re.findall(r"[a-z]+", feature.lower())
        if any(w in SCENE_ANCHORS or w in ("glowing", "mist", "stars", "stone",
                                        "lantern", "moonlight", "rain",
                                        "snow", "neon", "portal", "sakura")
               for w in words):
            details.append(feature.lower())
        if len(details) >= 2:
            break
    scene = anchor.title()
    sentence = f"A {scene.lower()} scene for your Roblox avatar."
    if details:
        sentence += " Featuring " + " and ".join(details) + "."
    return sentence[:310]


def verified_background_competitors(live, limit=3):
    """Only trust category-explicit AssetType 92 results from a successful sample.

    Names are bounded because external catalog text is untrusted. Empty/missing
    metric values are UNKNOWN rather than fabricated zeros.
    """
    if not isinstance(live, dict) or live.get("ok") is not True:
        return []
    out, seen = [], set()
    for raw in (live.get("top_competitors") or [])[:10]:
        if not isinstance(raw, dict):
            continue
        try:
            asset_type = int(raw.get("asset_type_id"))
        except (TypeError, ValueError):
            continue
        if asset_type != 92:
            continue
        name = _short_text(raw.get("name"), 80)
        if not name or _is_untrusted_instruction(name):
            continue
        if name.casefold() in seen:
            continue
        seen.add(name.casefold())
        row = {"name": name}
        for field in ("favorites", "price"):
            try:
                value = int(raw.get(field))
            except (TypeError, ValueError):
                value = None
            row[field] = value if value is not None and 0 < value < 10**10 else None
        out.append(row)
        if len(out) >= limit:
            break
    return out


def title_sample_overlap(title, competitors):
    """Return descriptive token overlap, NEVER visual similarity or CTR."""
    def terms(value):
        return {t for t in re.findall(r"[a-z0-9]+", value.lower())
                if t not in _FILLER and t not in _BAD_SCENE_PARTS}
    desired = terms(title or "")
    best = {"ratio": 0.0, "name": None, "exact": False}
    for row in competitors or []:
        name = row.get("name") or ""
        comp = terms(name)
        if not desired or not comp:
            continue
        ratio = len(desired & comp) / len(desired | comp)
        exact = name.casefold().strip() == (title or "").casefold().strip()
        if exact or ratio > best["ratio"]:
            best = {"ratio": round(ratio, 2), "name": name,
                    "exact": exact}
    return best


def title_dry_run(vision, notes="", live=None):
    """Rank descriptive TITLE FIT only, never forecast CTR or favorites.

    A weighted, auditable copy checklist: scene identity (40 points),
    visible feature (20), readability (15), type clarity (10), and
    overlap with the *sampled* live competitors (15). Scores are
    editorial heuristics, not a fitted model or simulated purchase data.
    """
    titles = candidate_titles(vision, notes, live=live)
    anchor = scene_phrase(vision, notes)
    core = set(re.findall(r"[a-z]+", anchor or ""))
    features = observations(vision)["distinctive_features"]
    feature_words = set()
    for item in features:
        if not _is_untrusted_instruction(item):
            feature_words.update(
                w for w in re.findall(r"[a-z]+", item.lower())
                if w not in _FILLER and w not in _BAD_SCENE_PARTS)
    competitors = verified_background_competitors(live)
    ranked = []
    for title in titles:
        tokens = re.findall(r"[a-z]+", title.lower())
        searchable = set(tokens)
        covered = len(searchable & core)
        identity = (40 if core and covered == len(core)
                    else 20 if covered else 0)
        details = 20 if feature_words & searchable else 8
        readability = (15 if 3 <= len(tokens) <= 6
                       else 8 if 2 <= len(tokens) <= 7 else 0)
        type_score = 10 if title.lower().endswith(" background") else 0
        overlap = title_sample_overlap(title, competitors)
        distinct = (0 if overlap["exact"] else
                    5 if overlap["ratio"] >= .70 else
                    10 if overlap["ratio"] >= .45 else 15)
        total = identity + details + readability + type_score + distinct
        ranked.append({
            "title": title, "fit_score": total,
            "score_type": "editorial title-fit heuristic, not predicted CTR",
            "sample_overlap": overlap,
            "scene_anchor_preserved": identity == 40,
            "visible_feature_word": details == 20,
        })
    ranked.sort(key=lambda x: (-x["fit_score"], x["title"].casefold()))
    return ranked


_NAMED_IP_CUES = (
    "oggy", "fnaf", "five nights at freddy", "team fortress", "tf2",
    "bioshock", "spongebob", "simpsons", "pokemon",
)


def creator_named_subject(notes=""):
    """Explicit creator-provided franchise, NOT an AI-verified visual detail.

    Use only bounded known names. No external title, model text or live
    competitor name is allowed to insert a franchise identity.
    """
    user = _short_text(notes, 300).lower()
    if _is_untrusted_instruction(user):
        return None
    for term in sorted(_NAMED_IP_CUES, key=len, reverse=True):
        if re.search(r"\b" + re.escape(term) + r"\b", user):
            return term
    return None


def combine_background_live_checks(checks):
    """Collate 1-2 independently bounded AssetType 92 searches without
    inventing coverage or converting a failed request to zero competition.
    """
    report = []
    groups = []
    for raw in list(checks or [])[:2]:
        data = raw if isinstance(raw, dict) else {}
        ok = data.get("ok") is True
        label = _short_text(
            data.get("search_keyword") or data.get("keyword"), 80)
        check = {
            "query": label,
            "status": "ok" if ok else "unavailable",
            "cached": bool(data.get("cached")) if ok else None,
            "sampled_results": data.get("sampled_results") if ok else None,
            "asset_type_92_matches": data.get("category_correct") if ok else None,
            "pages": data.get("pages") if ok else None,
            "observed_at": _short_text(
                data.get("observed_at") or data.get("verification_timestamp"), 48)
                if ok else None,
            "error": _short_text(data.get("error"), 100) if not ok else None,
        }
        report.append(check)
        if not ok:
            groups.append([])
            continue
        valid = []
        for item in (data.get("top_competitors") or [])[:3]:
            if not isinstance(item, dict):
                continue
            try:
                if int(item.get("asset_type_id") or 0) != 92:
                    continue
            except (TypeError, ValueError):
                continue
            name = _short_text(item.get("name"), 80)
            if not name or _is_untrusted_instruction(name):
                continue
            valid.append(item)
        groups.append(valid)
    # Interleave rather than letting a broad scene query consume all three
    # display slots before the creator-named query gets represented.
    found = []
    seen = set()
    for position in range(3):
        for group in groups:
            if position >= len(group):
                continue
            item = group[position]
            name = _short_text(item.get("name"), 80)
            if name.casefold() in seen:
                continue
            seen.add(name.casefold())
            found.append(item)
    return {
        "ok": any(x["status"] == "ok" for x in report),
        "search_checks": report,
        "top_competitors": found[:6],
    }


def named_ip_caution(vision, notes=""):
    """Simple warning cue; not a complete trademark or legal determination."""
    obs = observations(vision)
    text = (str(notes or "")[:300] + " " + obs["visual_summary"] +
            " " + obs["ip_reference_warning"]).lower()
    return any(re.search(r"\b" + re.escape(term) + r"\b", text)
               for term in _NAMED_IP_CUES)


def format_background_dossier(vision, notes="", image_quality=None,
                              live=None, include_titles=True):
    """A readable audit with unknowns and externally measured facts separated."""
    o = observations(vision)
    parts = ["# 🌌 BACKGROUND ARTWORK INTELLIGENCE",
             "_AI image interpretation; verify details against your artwork. "
             "No measured CTR, impressions, conversion, or sales are inferred._"]
    parts.append("**Scene identity**")
    parts.append(
        "• " + (o["visual_summary"] or
                 "Not established; supply a clearer image or creator notes.")
    )
    phrase = scene_phrase(vision, notes)
    parts.append(f"• Searchable scene anchor: \`{phrase}\` (descriptive only)"
                 if phrase else "• Scene anchor unavailable; avoid guessing a niche.")
    parts.append("**Visual design**")
    parts.append("• Palette: " + (", ".join(o["visual_colors"]) or "not verified"))
    parts.append("• Style: " + (", ".join(o["visual_style"]) or "not verified"))
    parts.append("• Distinctive features: " + (
        ", ".join(o["distinctive_features"]) or "not verified"))
    for label, key in (
        ("Focal point", "scene_focal_point"),
        ("Avatar clearance", "avatar_clearance_notes"),
        ("Ground/horizon", "ground_horizon_notes"),
        ("Mobile cropping", "mobile_readability_notes"),
        ("Depth layers", "depth_layers_notes"),
        ("Lighting", "lighting_notes"),
    ):
        parts.append(f"• {label}: {o[key] or 'not determined—check manually'}")
    parts.append("**Export / publishing checks**")
    if isinstance(image_quality, dict):
        dims = (f"{image_quality.get('width') or '?'}×"
                f"{image_quality.get('height') or '?'}")
        fmt = image_quality.get("format") or "unknown"
        parts.append(f"• Image: {dims} · {fmt} · " +
                     ("format and dimensions passed" if image_quality.get("ok")
                      else "needs export review"))
        for err in (image_quality.get("errors") or [])[:4]:
            parts.append("• Fix: " + _short_text(err, 160))
        for warning in (image_quality.get("warnings") or [])[:3]:
            parts.append("• Note: " + _short_text(warning, 160))
    else:
        parts.append("• Upload source dimensions/alpha could not be validated.")
    parts.append("• Preview with a centered avatar on mobile and desktop; "
                 "an image alone cannot verify final Roblox crop.")
    if include_titles:
        titles = candidate_titles(vision, notes, live=live)
        competitors = verified_background_competitors(live)
        parts.append("**Naming decision — titles to test, not sales predictions**")
        if titles:
            parts.append("• First candidate: " + titles[0] +
                         " (scene-led, descriptive; validate the actual artwork).")
            for title in titles[1:5]:
                parts.append("• Alternative: " + title)
            overlap = title_sample_overlap(titles[0], competitors)
            if overlap["name"] and overlap["ratio"] >= 0.65:
                parts.append(
                    "• Similar sampled TITLE keywords: " + overlap["name"] +
                    " (overlap " + str(round(overlap["ratio"] * 100)) +
                    "%). Differentiate with a genuinely visible feature.")
            elif competitors:
                parts.append("• No close title-word overlap in these sampled "
                             "competitors; broader uniqueness is unknown.")
            else:
                parts.append("• Exact-title and similarity checks unavailable "
                             "without verified competitor names.")
            parts.append("• Choose a recognizable scene noun and truthful visual "
                         "hook; never insert unverified animation or 3D claims.")
        else:
            parts.append("• No defensible unique title from the supplied scene "
                         "and sampled competitors; adjust the concept details.")
    if include_titles:
        ranked = title_dry_run(vision, notes, live)
        if ranked:
            parts.append("**Title dry run — editorial fit, NOT CTR/favorite predictions**")
            for option in ranked[:4]:
                overlap = option["sample_overlap"]
                overlap_note = (
                    " · sampled title overlap " +
                    str(round(overlap["ratio"] * 100)) + "%"
                    if overlap["name"] else " · overlap unavailable")
                parts.append(
                    "• " + option["title"] + " — fit " +
                    str(option["fit_score"]) + "/100" + overlap_note)
            parts.append("• Fit scores check scene words, visible details, "
                         "readability and sampled names. No marketplace "
                         "impression or click data was used.")
            parts.append("• Favorites forecast: unavailable. A title alone "
                         "cannot establish expected purchases or favorites.")
    description = listing_description(vision, notes)
    parts.append("**Draft listing description (verify every detail)**")
    parts.append(description or "• Not enough verified visual detail to draft copy.")
    parts.append("**Background-only live marketplace sample**")
    if not live:
        parts.append("• Not checked. No competitor or demand claim.")
    elif not live.get("ok"):
        parts.append("• Unavailable (" +
                     _short_text(live.get("error") or "unknown", 80) +
                     "). Do not interpret a failed request as zero competitors.")
    else:
        count = int(live.get("category_correct") or 0)
        sampled = int(live.get("sampled_results") or 0)
        parts.append(f"• {count} verified AssetType 92 items in "
                     f"{sampled} sampled search results.")
        parts.append("• Sampled competitor counts do not prove full-category "
                     "absence, demand, sales, or title CTR.")
        verified = verified_background_competitors(live)
        for row in verified:
            fav = (str(row["favorites"]) + " favorites"
                   if row["favorites"] is not None else "favorites unavailable")
            price = ("R$" + str(row["price"])
                     if row["price"] is not None else "price unavailable")
            parts.append("• " + row["name"] + " — " + fav + " · " + price +
                         " (AssetType 92, sampled listing)")
        positive_prices = sorted(row["price"] for row in verified
                                 if row["price"] is not None)
        if positive_prices:
            from statistics import median
            parts.append(
                "• Sampled price reference: R$" + str(positive_prices[0]) +
                "–R$" + str(positive_prices[-1]) +
                " (median R$" + str(round(median(positive_prices))) +
                " from " + str(len(positive_prices)) +
                " listings with known positive prices). Not an optimal price.")
        else:
            parts.append("• No usable sampled price reference; do not guess a price.")
        parts.append("• Similar TITLE words do not prove copied artwork, and "
                     "sampled prices/favorites do not establish sales.")
    parts.append("**Pre-publish checklist**")
    parts.append("• Preview real avatar positioning and mobile crop; check "
                 "scene focal point, ground, horizon, contrast and edge fade.")
    parts.append("• Verify the final uploaded file and listing appearance on "
                 "Roblox. A PNG cannot become an animated GIF.")
    parts.append("**Launch measurement and next actions**")
    parts.append("• Compare title and thumbnail variants one change at a time. "
                 "Record favorites D1/D7/D14/D30 and real units D7/D30.")
    parts.append("• After publishing, use !launch <item_id>, !ledger_sync "
                 "and !verdict. Compare with other backgrounds, not a lone hit.")
    parts.append("• Only calculate CTR if actual impressions and clicks exist; "
                 "no wording can guarantee additional sales.")
    return "\n".join(parts)


def discord_chunks(text, limit=1800):
    """Split at line boundaries where possible; never exceed Discord limits."""
    lines = (text or "").split("\n")
    out, cur = [], ""
    for line in lines:
        while len(line) > limit:
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:limit])
            line = line[limit:]
        candidate = f"{cur}\n{line}" if cur else line
        if len(candidate) > limit:
            out.append(cur)
            cur = line
        else:
            cur = candidate
    if cur:
        out.append(cur)
    return out
