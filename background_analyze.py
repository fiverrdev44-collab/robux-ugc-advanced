"""Background-specific analysis coordinator.

Reuses the existing vision provider, live convergence verifier, category
configuration and avatar-background helpers. It does not create a second
marketplace crawler or a second image provider.
"""
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone

import avatar_backgrounds as ab
import convergence_live as cl
from gemini_brain import (
    _BACKGROUND_VISION_PROMPT,
    _BACKGROUND_VERIFY_PROMPT,
    analyze_image_for_ugc,
)

ASSET_TYPE = 92
LAST_ANALYSIS_TTL_SECONDS = 1800
_LAST = OrderedDict()
_LAST_LOCK = threading.Lock()

FRANCHISE_RE = re.compile(
    r"\b(oggy|fnaf|five nights at freddy'?s|tf2|team fortress(?: 2)?|"
    r"hello kitty|sonic|mario|pok[eé]mon|minecraft|among us|squid game|"
    r"spongebob|simpsons|marvel|dc comics|star wars|harry potter)\b",
    re.IGNORECASE,
)


def _now():
    return datetime.now(timezone.utc)


def _clip(value, limit=120):
    return str(value or "").strip()[:limit]


def _scene_text(vision, notes):
    parts = [
        vision.get("visual_summary"),
        vision.get("background_setting"),
        " ".join(vision.get("background_landmarks") or []),
        vision.get("background_lighting"),
        " ".join(vision.get("background_palette") or []),
        vision.get("background_atmosphere"),
        vision.get("composition_notes"),
        notes,
    ]
    return " | ".join(_clip(p, 220) for p in parts if _clip(p))


def _first(value):
    if isinstance(value, (list, tuple)):
        return _clip(value[0] if value else "")
    return _clip(value)


def _title_seed(vision, notes):
    seed = (_clip(vision.get("visual_title_seed"))
            or _first(vision.get("background_landmarks"))
            or _clip(vision.get("background_setting"))
            or _clip(notes))
    seed = re.sub(r"\b(avatar\s+)?background\b", "", seed, flags=re.I)
    seed = re.sub(r"[^A-Za-z0-9' -]+", " ", seed)
    words = [w for w in seed.split() if w][:6]
    return " ".join(words).strip() or "Original Scene"


def _title_case(text):
    return " ".join(w.capitalize() if w.islower() else w
                    for w in str(text or "").split())


def _franchise(notes):
    match = FRANCHISE_RE.search(notes or "")
    return match.group(1) if match else ""


def _dedupe(values):
    seen, out = set(), []
    for value in values:
        key = value.strip().lower()
        if value and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _editorial_score(title, scene, live_names):
    words = re.findall(r"[a-z0-9']+", title.lower())
    scene_tokens = set(re.findall(r"[a-z0-9']+", scene.lower()))
    live_tokens = set()
    for name in live_names:
        live_tokens.update(re.findall(r"[a-z0-9']+", (name or "").lower()))
    descriptive = min(5, 1 + len(set(words) & scene_tokens))
    search = min(5, 1 + len(set(words) & live_tokens))
    brevity = 5 if len(words) <= 6 else 4 if len(words) <= 8 else 3
    differentiation = 1 if title.lower() in {
        n.lower() for n in live_names} else 5
    recognizability = 4 if "background" in words else 3
    total = descriptive + search + brevity + differentiation + recognizability
    return {
        "recognizability": recognizability,
        "descriptive_accuracy": descriptive,
        "brevity": brevity,
        "search_relevance": search,
        "differentiation": differentiation,
        "editorial_total": total,
    }


def build_titles(vision, notes, live_entries):
    """Exactly one preferred title and two genuinely different alternatives."""
    seed = _title_case(_title_seed(vision, notes))
    mood = _title_case(_first(vision.get("background_atmosphere"))
                       or _first(vision.get("visual_mood")))
    landmark = _title_case(_first(vision.get("background_landmarks"))
                           or _first(vision.get("distinctive_features")))
    setting = _title_case(vision.get("background_setting"))

    preferred = f"{seed} Avatar Background"
    first_alt = (f"{mood} {seed} Background"
                 if mood and mood.lower() not in seed.lower()
                 else f"{setting} {seed} Background")
    second_alt = (f"{landmark} {seed} Background"
                  if landmark and landmark.lower() not in seed.lower()
                  else f"{setting} Scene Background")
    franchise = _franchise(notes)
    ip_warning = ""
    if franchise:
        second_alt = f"{_title_case(franchise)}-Inspired {seed} Background"
        ip_warning = (
            f"`{franchise}` is a third-party media reference. The option is "
            "generated only as a recognition hypothesis; authorization, "
            "licensing and marketplace policy are NOT verified."
        )

    candidates = _dedupe([preferred, first_alt, second_alt])
    while len(candidates) < 3:
        candidates.append(f"{seed} Scene Option {len(candidates) + 1}")
    candidates = candidates[:3]
    live_names = []
    for entry in live_entries:
        for comp in entry.get("competitors") or []:
            live_names.append(comp.get("name") or "")
    scene = _scene_text(vision, notes)
    scored = []
    for title in candidates:
        scores = _editorial_score(title, scene, live_names)
        scored.append({"title": title, **scores,
                       "franchise_reference": bool(
                           franchise and franchise.lower() in title.lower())})
    preferred_item = max(
        [x for x in scored if not x["franchise_reference"]] or scored,
        key=lambda x: x["editorial_total"])
    alternatives = [x for x in scored if x is not preferred_item]
    return {
        "preferred": preferred_item,
        "alternatives": alternatives,
        "all": [preferred_item] + alternatives,
        "ip_warning": ip_warning,
        "franchise_reference": franchise,
        "criteria_note": (
            "Editorial comparison only: recognizability, descriptive accuracy, "
            "brevity, search relevance and differentiation. Not measured CTR, "
            "ranking or algorithmic superiority."),
    }


def build_description(vision, notes, preferred_title):
    setting = _clip(vision.get("background_setting"))
    landmarks = ", ".join(_clip(x) for x in
                          (vision.get("background_landmarks") or [])[:4])
    lighting = _clip(vision.get("background_lighting"))
    palette = ", ".join(_clip(x) for x in
                        (vision.get("background_palette") or [])[:5])
    atmosphere = _clip(vision.get("background_atmosphere"))
    composition = _clip(vision.get("background_composition")
                        or vision.get("composition_notes"))
    fallback = ab.build_creative_brief(
        _title_seed(vision, notes), title=preferred_title)
    lines = [
        f"{preferred_title} is an original avatar-background scene.",
        (f"Setting: {setting or fallback['environment_theme']}."
         + (f" Landmarks: {landmarks}." if landmarks else "")),
        (f"Lighting: {lighting or fallback['lighting']}. "
         f"Palette: {palette or fallback['colour_palette']}. "
         f"Atmosphere: {atmosphere or fallback['atmosphere']}."),
        (f"Composition: {composition or fallback['composition']} "
         f"{fallback['avatar_placement']}"),
        (f"Mobile: {fallback['mobile_readability']} "
         f"Desktop: {fallback['desktop_readability']}"),
        ("Export 2560x1440 sRGB flattened RGB with no alpha. Roblox applies "
         "edge fading automatically; avatar placement and cropping vary by "
         "surface, and a local preview may not match final rendering."),
    ]
    return "\n".join(line for line in lines if line.strip())


def search_terms(vision, notes, limit=10):
    text = _scene_text(vision, notes).lower()
    tokens = re.findall(r"[a-z][a-z0-9'-]{2,}", text)
    stop = {"with", "that", "this", "from", "into", "your", "avatar",
            "background", "scene", "image", "looks", "very", "the", "and"}
    counts = {}
    for token in tokens:
        if token in stop:
            continue
        counts[token] = counts.get(token, 0) + 1
    ordered = sorted(counts, key=lambda t: (-counts[t], t))
    return ordered[:max(4, min(int(limit), 12))]


def live_search(vision, notes, max_queries=2):
    queries = _dedupe([
        _clip(vision.get("search_description")),
        f"{_title_seed(vision, notes)} background",
        _clip(notes) if len(_clip(notes)) <= 90 else "",
    ])[:max_queries]
    entries = []
    for query in queries:
        started = _now().isoformat()
        try:
            result = cl.verify_niche(
                query, family="backgrounds", limit=30, max_pages=1,
                timeout=12, use_cache=False)
        except Exception as exc:
            result = {"ok": False, "error": type(exc).__name__,
                      "status": "unavailable"}
        status = "ok" if result.get("ok") else (
            "rate_limited" if result.get("retry_after") is not None
            else "deferred" if result.get("deferred")
            else "empty" if result.get("ok") else "unavailable")
        comps = result.get("competitors") or result.get("top_competitors") or []
        if result.get("ok") and not comps:
            status = "empty"
        entries.append({
            "query": query,
            "checked_at": result.get("verification_timestamp") or started,
            "status": status,
            "ok": bool(result.get("ok")),
            "error": _clip(result.get("error"), 100),
            "cached": bool(result.get("cached")),
            "pages": result.get("pages"),
            "sampled_results": result.get("sampled_results"),
            "category_correct": result.get("category_correct"),
            "exact_title_matches": result.get("exact_title_matches", 0),
            "competitors": comps[:8],
            "stored_snapshot_used": False,
        })
        if status in ("rate_limited", "deferred"):
            break
    return entries


def analyze(images, notes="", verify=True):
    """Actual-byte background analysis with explicit evidence labels."""
    if not images:
        return {"ok": False, "error": "image attachment required",
                "status": "missing_image"}
    notes = _clip(notes, 500)
    validation = {}
    try:
        validation = ab.validate_image(images[0]["bytes"])
    except Exception as exc:
        validation = {"ok": False, "errors": [type(exc).__name__]}

    try:
        first = analyze_image_for_ugc(
            images, notes,
            prompt_text=_BACKGROUND_VISION_PROMPT.format(desc=notes or "(none)"))
    except Exception:
        first = {}
    if not first:
        return {
            "ok": False, "status": "vision_failed", "notes": notes,
            "image_validation": validation,
            "error": "independent vision provider returned no result",
            "evidence_label": "creator notes only; no visual verification",
        }

    verification = {}
    verification_status = "first_pass_only"
    if verify:
        try:
            verification = analyze_image_for_ugc(
                images, notes,
                prompt_text=_BACKGROUND_VERIFY_PROMPT.format(
                    desc=notes or "(none)"))
        except Exception:
            verification = {}
        verification_status = (
            _clip(verification.get("verification_status")).lower()
            or ("uncertain" if verification else "failed"))

    live = live_search(first, notes)
    titles = build_titles(first, notes, live)
    preferred = titles["preferred"]["title"]
    description = build_description(first, notes, preferred)
    return {
        "ok": True,
        "status": "ok",
        "asset_type": ASSET_TYPE,
        "category": "backgrounds",
        "notes": notes,
        "image_validation": validation,
        "vision": first,
        "verification": verification,
        "verification_status": verification_status,
        "vision_label": (
            "first-pass vision observations"
            if not verification else
            f"first-pass vision + {verification_status} independent check"),
        "live": live,
        "titles": titles,
        "description": description,
        "search_terms": search_terms(first, notes),
        "ip_warning": titles.get("ip_warning", ""),
        "checked_at": _now().isoformat(),
        "chain_context": _scene_text(first, notes),
    }


def format_report(data):
    if not data:
        return "No background analysis available."
    if not data.get("ok"):
        return (f"❌ **BACKGROUND ANALYZE — {data.get('status', 'failed')}**\n"
                f"{data.get('error', 'No analysis produced.')}\n"
                "_No visual accuracy, market demand, sales or CTR is claimed._")
    vision = data.get("vision") or {}
    validation = data.get("image_validation") or {}
    lines = [
        "# 🌌 BACKGROUND ANALYZE — AssetType 92",
        f"_Checked {data.get('checked_at', '—')} · category `backgrounds` "
        "only_",
        "",
        "## 👁️ Image evidence",
        f"• Evidence: **{data.get('vision_label')}**",
        f"• Structural file check: "
        f"{'PASS' if validation.get('ok') else 'WARN'} · "
        f"{validation.get('format') or 'unknown format'} · "
        f"{validation.get('width')}x{validation.get('height')} · "
        f"alpha={validation.get('alpha')} · sRGB={validation.get('srgb')}",
        f"• Scene: {_clip(vision.get('visual_summary'), 500) or '—'}",
        f"• Setting: {_clip(vision.get('background_setting'), 180) or '—'}",
        f"• Landmarks: {', '.join((vision.get('background_landmarks') or [])[:6]) or '—'}",
        f"• Lighting/palette: {_clip(vision.get('background_lighting'), 160) or '—'} · "
        f"{', '.join((vision.get('background_palette') or [])[:6]) or '—'}",
        f"• Atmosphere/composition: {_clip(vision.get('background_atmosphere'), 160) or '—'} · "
        f"{_clip(vision.get('background_composition') or vision.get('composition_notes'), 220) or '—'}",
    ]
    verification = data.get("verification") or {}
    if verification:
        lines += [
            "## 🔎 Independent verification",
            f"• Status: **{data.get('verification_status', 'uncertain')}**",
            f"• Verified setting: {_clip(verification.get('verified_setting'), 220) or '—'}",
            f"• Discrepancies: {', '.join(verification.get('discrepancies') or []) or 'none reported'}",
        ]
    else:
        lines += [
            "## 🔎 Independent verification",
            "• Status: **first-pass only** — independent visual verification "
            "was not produced; creator notes are not treated as verification.",
        ]
    lines += ["", "## 🛰️ LIVE marketplace evidence (AssetType 92 only)",
              "_These are live search results, not stored snapshots. Favorites "
              "are not sales and search matches are not verified demand._"]
    if not data.get("live"):
        lines.append("• No live query was run.")
    for entry in data.get("live") or []:
        lines.append(
            f"• Query `{entry['query']}` · **{entry['status']}** · "
            f"{entry['sampled_results'] or 0} sampled · "
            f"{entry['category_correct'] or 0} type-92 · "
            f"{entry['exact_title_matches'] or 0} exact · {entry['checked_at']}")
        if not entry.get("ok"):
            lines.append(f"  - Live unavailable: `{entry.get('error') or entry['status']}`; "
                         "no stored match was substituted.")
            continue
        if not entry.get("competitors"):
            lines.append("  - No type-92 competitors returned; no demand claim made.")
            continue
        for comp in entry["competitors"][:5]:
            created = comp.get("created_at") or "publication date unavailable"
            creator = comp.get("creator") or "creator unavailable"
            lines.append(
                f"  - [{comp.get('name') or 'Untitled'}]"
                f"(https://www.roblox.com/catalog/{comp.get('id') or 0}) · "
                f"{creator} · {int(comp.get('favorites') or 0):,} ♥ · "
                f"R${int(comp.get('price') or 0)} · {created}")
    titles = data.get("titles") or {}
    lines += ["", "## 🏷️ Title options — one preferred, two alternatives"]
    preferred = titles.get("preferred") or {}
    if preferred:
        lines.append(f"**Preferred:** **{preferred.get('title')}**")
    for i, alt in enumerate(titles.get("alternatives") or [], 1):
        lines.append(f"**Alternative {i}:** {alt.get('title')}")
    lines.append("")
    lines.append("_Editorial comparison only — not measured CTR, ranking or "
                 "algorithmic superiority._")
    for item in titles.get("all") or []:
        lines.append(
            f"• {item.get('title')} — rec {item.get('recognizability')}/5 · "
            f"scene {item.get('descriptive_accuracy')}/5 · "
            f"brief {item.get('brevity')}/5 · search {item.get('search_relevance')}/5 · "
            f"differentiation {item.get('differentiation')}/5")
    if data.get("ip_warning"):
        lines += ["", "## ⚠️ IP / franchise reference",
                  data["ip_warning"]]
    lines += ["", "## 📝 Listing description", data.get("description", "—"),
              "", "## 🔎 Search terms",
              ", ".join(f"`{t}`" for t in (data.get("search_terms") or [])) or "—",
              "", "_No sales, revenue, CTR, impressions, conversion or verified "
              "marketplace demand is claimed. An approved Discord source is not "
              "proof of a completed Roblox transaction._"]
    return "\n".join(lines)


def store_last(user_id, channel_id, data):
    key = (str(user_id), str(channel_id))
    with _LAST_LOCK:
        _LAST[key] = {"at": time.time(), "data": data}
        while _LAST:
            oldest_key, oldest = next(iter(_LAST.items()))
            if time.time() - oldest["at"] <= LAST_ANALYSIS_TTL_SECONDS:
                break
            _LAST.pop(oldest_key, None)


def get_last(user_id, channel_id, max_age=LAST_ANALYSIS_TTL_SECONDS):
    key = (str(user_id), str(channel_id))
    with _LAST_LOCK:
        entry = _LAST.get(key)
        if not entry or time.time() - entry["at"] > max_age:
            return None
        return entry["data"]


def last_visual_context(user_id, channel_id):
    data = get_last(user_id, channel_id)
    return (data or {}).get("chain_context") or ""
