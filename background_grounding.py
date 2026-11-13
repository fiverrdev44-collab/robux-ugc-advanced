"""Conservative, read-only reconciliation for Avatar Background visual claims.

Creator notes, initial image interpretation and independent image-only inspection
have separate provenance. Disagreements are reported rather than resolved by
guessing; no unrelated asset, platform metrics or image-edit advice.
"""
import re

from background_intelligence import observations, _short_text, _is_untrusted_instruction

_LOCATIONS = {
    "window": ("window", "glass pane", "windowpane"),
    "poster": ("poster", "painting", "framed picture", "photograph",
               "printed image", "wall art", "portrait"),
    "screen": ("monitor", "computer screen", "screen", "television", "tv display"),
    "doorway": ("doorway", "door opening", "doorframe", "entrance"),
    "wall": ("on the wall", "wall mounted", "wall-mounted"),
    "unknown": (),
}
_SUBJECT_GROUPS = {
    "bear": ("bear", "fazbear", "freddy", "teddy"),
    "animatronic": ("animatronic", "robotic figure", "robot bear"),
    "person": ("person", "human", "man", "woman", "character"),
    "moon": ("moon", "lunar"),
    "portal": ("portal", "gateway"),
}
_STRIP_WORDS = {"poster", "painting", "framed", "picture", "window",
                "glass", "doorway", "screen", "monitor"}
_DEFINITIVE = ("confirmed", "definitely", "certainly", "clearly a")


def _clean(value, max_len=250):
    value = _short_text(value, max_len)
    return "" if _is_untrusted_instruction(value) else value


def _find_relation(value):
    if not value:
        return None
    low = " ".join(re.findall(r"[a-z]+", value.lower()))
    if not low or low in {"unknown", "unclear", "not visible", "not sure"}:
        return None
    # Poster/screen beat 'window' when e.g. 'a poster beside the window'.
    for key in ("poster", "screen", "doorway", "window", "wall"):
        if any(re.search(r"\b" + re.escape(word) + r"\b", low)
               for word in _LOCATIONS[key]):
            return key
    return None


def _subject_groups(value):
    low = " ".join(re.findall(r"[a-z]+", (value or "").lower()))
    return {group for group, names in _SUBJECT_GROUPS.items()
            if any(re.search(r"\b" + re.escape(name) + r"\b", low) for name in names)}


def _subject_context(vision):
    o = observations(vision)
    subj = _clean((vision or {}).get("primary_subject"), 90)
    # Keep relation anchored to named subject and description; unrelated
    # background windows or wall details are not proof of subject placement.
    relation = _clean((vision or {}).get("subject_relation"), 120)
    if not relation:
        relation = _clean(o["visual_summary"], 220)
    return subj or _clean(o["visual_summary"], 150), _find_relation(relation)


def _safe_features(value):
    return [x for x in observations(value)["distinctive_features"]
            if x and not _is_untrusted_instruction(x)]


def reconcile_background_vision(first, second, creator_notes=""):
    """Return reconciled vision and short evidence warnings.

    Second pass must be a true separate image-only interpretation to count as
    verification. Missing/failed second pass is NOT agreement.
    """
    if not isinstance(first, dict) or not first:
        return {"status": "unavailable", "vision": {}, "notes": []}
    first = dict(first)
    second = second if isinstance(second, dict) else {}
    independent = bool(second and (
        _clean(second.get("primary_subject")) or
        _clean(second.get("visual_summary")) or
        _safe_features(second)))
    verified = bool(independent)
    creator = _clean(creator_notes, 380)
    subject_a, relation_a = _subject_context(first)
    subject_b, relation_b = _subject_context(second) if independent else ("", None)
    creator_groups = _subject_groups(creator)
    groups_a, groups_b = _subject_groups(subject_a), _subject_groups(subject_b)
    subject_conflict = bool(groups_a and groups_b and not (groups_a & groups_b))
    relation_conflict = bool(relation_a and relation_b and relation_a != relation_b)
    creator_relation = _find_relation(creator)
    creator_conflict = bool(creator_relation and relation_a and creator_relation != relation_a)
    if relation_b and creator_relation and creator_relation != relation_b:
        creator_conflict = True

    notes = []
    if not independent:
        notes.append("Independent image-only subject check unavailable; visual claims are tentative.")
    if subject_conflict:
        notes.append("Image checks disagree on the prominent subject; avoid specific subject-based titles.")
    if relation_conflict:
        notes.append("Image checks disagree about the subject's location or depiction "
                     f"({relation_a} versus {relation_b}); do not claim either is verified.")
    if creator_conflict:
        notes.append("Creator description and visual interpretation disagree on "
                     "window/poster/screen or placement; no location is verified.")
    if not (subject_conflict or relation_conflict or creator_conflict) and verified:
        notes.append("Independent image-only subject check completed; "
                     "agreeing interpretations are still fallible.")

    out = dict(first)
    out["item_type_visual"] = "background"
    out["visual_verification"] = (
        "conflict" if (subject_conflict or relation_conflict or creator_conflict)
        else "cross_checked" if verified else "unverified"
    )
    out["visual_verification_notes"] = notes
    if subject_conflict or relation_conflict or creator_conflict:
        # Some details may be correct but a plausible relation can be wrong.
        # Strip *placement-dependent* features, avoid simply replacing poster
        # with window or injecting the creator description as observed fact.
        bad_rels = {k for k in (relation_a, relation_b, creator_relation) if k}
        out["distinctive_features"] = [
            x for x in _safe_features(first)
            if not any(re.search(r"\b" + re.escape(term) + r"\b", x.lower())
                       for rel in bad_rels for term in _LOCATIONS[rel])
        ]
        # A neutral subject may survive only if BOTH vision passes identify it.
        common = groups_a & groups_b if verified else set()
        # Creator-only named identity may be considered search context but not
        # a witnessed image fact; we do not add it to visual evidence.
        if common:
            common_label = ("bear" if "bear" in common else
                            "animatronic" if "animatronic" in common else
                            sorted(common)[0])
            out["distinctive_features"] = [
                f for f in out["distinctive_features"]
                if not any(word in f.lower() for word in _STRIP_WORDS)
            ]
            out["distinctive_features"].insert(0, common_label)
        out["search_description"] = _clean(
            first.get("search_description") or "Avatar Background", 130)
        # Do not reuse an unsupported placement claim in the model context.
        summary = _clean(first.get("visual_summary"), 220)
        for rel in bad_rels:
            for term in _LOCATIONS[rel]:
                summary = re.sub(r"\b" + re.escape(term) + r"\b",
                                 "", summary, flags=re.I)
        out["visual_summary"] = " ".join(summary.split()).strip(" .,")
    out["uncertain_elements"] = [
        _clean(x, 140) for x in (second.get("uncertain_elements") or [])[:4]
        if isinstance(x, str) and _clean(x, 140)
    ] if independent else []
    return {
        "status": out["visual_verification"], "vision": out, "notes": notes,
        "independent_checked": verified, "relation_conflict": relation_conflict,
        "subject_conflict": subject_conflict,
        "creator_conflict": creator_conflict,
    }


def format_visual_verification(result):
    """Concise Discord disclosure. Not a redesign or Photopea suggestion."""
    lines = ["**Image evidence check**"]
    for note in (result.get("notes") or [])[:3]:
        lines.append("• " + _clean(note, 220))
    uncertain = (result.get("vision") or {}).get("uncertain_elements") or []
    if uncertain:
        lines.append("• Ambiguous image details: " + ", ".join(uncertain[:2]))
    if len(lines) == 1:
        lines.append("• Subject positioning remains tentative.")
    return "\n".join(lines)
