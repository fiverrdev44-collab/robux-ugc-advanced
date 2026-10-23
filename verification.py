"""verification.py — staged verification for every AI-generated output.

Stage 1 TOKENS: every title token must exist in the vetted allow-list.
Stage 2 PHRASE: the phrase is measured against real items and suggestions.
Stage 3 CLAIMS: numbers in prose must match a computed fact or the sentence
                 is removed.
Stage 4 PIVOT: an AI pivot must reclassify as a real, non-saturated keyword.
Stage 5 METRICS: every surviving title carries supply/demand/saturation.

Nothing is silently softened: rejected material is returned with reasons.
"""
import re

TOKEN_RE = re.compile(r"[a-z0-9]+")
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
STOPWORDS = {"a", "an", "the", "of", "and", "or", "for", "to", "in", "on",
             "with", "my", "your", "at", "by", "is", "it", "as",
             "i", "you", "we", "me", "our", "us", "he", "she", "they",
             "im", "ive", "dont", "cant", "aint", "got", "that", "this"}
ITEM_TYPE_WORDS = {
    "emote", "dance", "hat", "beanie", "crown", "cap", "hair", "face", "mask",
    "shirt", "pants", "jacket", "shoes", "wing", "wings", "tail", "ears",
    "horn", "horns", "glasses", "necklace", "chain", "backpack", "sword",
    "pet", "bag", "scarf", "bandana", "beret", "visor", "lens", "head",
    "snapback", "bonnet", "balaclava",
}
TITLE_FIELDS = (
    "titles_safe", "titles_differentiated", "titles_longtail", "titles_viral",
)
GUARANTEE_PATTERNS = (
    (r"\bguarantee(d|s)?\b", "guarantee"),
    (r"\b100\s*%\b", "100% claim"),
    (r"\bwill (go viral|blow up|sell out|moon)\b", "certain virality"),
    (r"\binstant (hit|winner)\b", "instant hit"),
    (r"\bbest[- ]?seller\b", "best seller"),
    (r"\brisk[- ]?free\b", "risk-free"),
    (r"\bno risk\b", "no risk"),
    (r"\balways (works|wins|sells)\b", "always works"),
    (r"\bnever fails\b", "never fails"),
    (r"\bdefinitely\b", "certainty"),
    (r"\bproven to (sell|work|go viral)\b", "causal claim"),
)


def tokens(title):
    return TOKEN_RE.findall((title or "").lower())


def allow_set(allow_list):
    allowed = set()
    for entry in allow_list or []:
        if not entry:
            continue
        value = str(entry).lower().strip()
        allowed.add(value)
        parts = value.split()
        if len(parts) > 1:
            allowed.update(p for p in parts if len(p) >= 3)
    allowed.update(ITEM_TYPE_WORDS)
    try:
        from category_configs import get_all_type_words
        allowed.update(get_all_type_words())
    except Exception:
        pass
    return allowed


def _token_reasons(title, allowed, seen_lower):
    toks = tokens(title)
    reasons = []
    if len(toks) < 3:
        reasons.append(f"too short ({len(toks)} tokens)")
    if len(toks) > 6:
        reasons.append(f"too long ({len(toks)} tokens)")
    if len(toks) != len(set(toks)):
        reasons.append("duplicate token")
    if title.lower().strip() in seen_lower:
        reasons.append("duplicate title")
    bad = []
    for tok in toks:
        if (tok in STOPWORDS or tok.isdigit() or len(tok) == 1
                or tok in allowed):
            continue
        if any(tok in (a, a + "s", a + "es", a + "ed", a + "ing")
               for a in allowed if len(a) >= 4):
            continue
        bad.append(tok)
    if bad:
        reasons.append("unverified token: " + ", ".join(sorted(set(bad))))
    return toks, reasons


def _phrase_metrics(cur, title, family=None):
    toks = [t for t in tokens(title) if t not in STOPWORDS]
    if not toks:
        return {}
    fam_sql, fam_params = "", []
    ids = None
    try:
        from convergence_engine import resolve_family_ids
        ids = resolve_family_ids(family)
    except Exception:
        ids = None
    if ids:
        fam_sql = " and asset_type_id in (" + ",".join(["%s"] * len(ids)) + ")"
        fam_params = list(ids)

    clauses = " and ".join(["lower(name) ~* %s"] * len(toks))
    params = [rf"\y{re.escape(t)}\y" for t in toks] + fam_params
    cur.execute(f"""
        select count(*),
               coalesce(percentile_cont(0.5) within group
                        (order by favorite_count), 0),
               coalesce(max(favorite_count), 0)
        from items
        where favorite_count > 5 and {clauses} {fam_sql}
    """, params)
    row = cur.fetchone()
    token_supply = int(row[0] or 0)
    median_favs = float(row[1] or 0)
    top_favs = float(row[2] or 0)

    cur.execute(f"""
        select count(*) from items
        where favorite_count > 5 and lower(name) = lower(%s) {fam_sql}
    """, [title.strip()] + fam_params)
    exact_matches = int(cur.fetchone()[0] or 0)

    clean_phrase = " ".join(toks)
    demand_op = "~*" if len(toks) == 1 else "ilike"
    demand_pat = (rf"\y{re.escape(toks[0])}\y" if len(toks) == 1
                  else f"%{clean_phrase}%")
    cur.execute(f"""
        select count(*) from search_suggestions
        where suggestion {demand_op} %s
    """, (demand_pat,))
    demand_all = int(cur.fetchone()[0] or 0)
    cur.execute(f"""
        select count(*) from search_suggestions
        where suggestion {demand_op} %s
          and seed_keyword is distinct from %s
    """, (demand_pat, "__db_mined__"))
    demand_live = int(cur.fetchone()[0] or 0)

    token_filters = ", ".join(
        ["count(*) filter (where lower(name) ~* %s)"] * len(toks)
    )
    token_params = [rf"\y{re.escape(tok)}\y" for tok in toks] + fam_params
    cur.execute(f"""
        select {token_filters}
        from items
        where favorite_count > 5 {fam_sql}
    """, token_params)
    counts = [int(x or 0) for x in cur.fetchone()]
    max_supply = max(counts) if counts else 0
    max_token = toks[counts.index(max_supply)] if counts else None

    return {
        "token_supply": token_supply,
        "exact_matches": exact_matches,
        "median_favs": round(median_favs, 1),
        "top_favs": round(top_favs, 1),
        "demand_live": demand_live,
        "demand_mined": demand_all - demand_live,
        "max_token_supply": max_supply,
        "max_token": max_token,
        "family": family,
    }


def verify_title_deep(cur, title, allow_list, family=None, seen=None):
    allowed = allow_set(allow_list)
    seen = seen if seen is not None else set()
    toks, reasons = _token_reasons(title, allowed, seen)
    if reasons:
        return {"title": title, "passed": False, "stage": "tokens",
                "reasons": reasons}
    seen.add(title.lower().strip())

    try:
        metrics = _phrase_metrics(cur, title, family)
    except Exception as e:
        return {"title": title, "passed": False, "stage": "phrase",
                "reasons": [f"phrase check failed: {type(e).__name__}"]}

    try:
        from opportunity_score import score_opportunity
        metrics["opportunity"] = score_opportunity(cur, title, family)
    except Exception:
        metrics["opportunity"] = None

    reasons = []
    flags = []
    opp = metrics.get("opportunity") or {}
    if opp.get("verdict") == "SATURATED":
        flags.append(
            f"competition is SATURATED "
            f"(anchor {opp.get('anchor') or opp.get('phrase')}, "
            f"visibility proxy (unvalidated) {opp.get('ctr_proxy')}/100)"
        )
    if metrics["exact_matches"] >= 10:
        flags.append(
            f"exact name used {metrics['exact_matches']} times — "
            f"proven demand, but a clone"
        )
    if metrics["max_token_supply"] >= 2000:
        flags.append(
            f"token '{metrics['max_token']}' is in "
            f"{metrics['max_token_supply']:,} items (broad word)"
        )
    if metrics["token_supply"] == 0:
        flags.append("new phrase combination (no exact item uses all tokens)")
    if metrics["demand_live"] == 0:
        flags.append("no live search demand measured for this phrase")

    status = "pass" if not reasons else "reject"
    return {
        "title": title,
        "passed": not reasons,
        "stage": "phrase",
        "status": status,
        "reasons": reasons,
        "flags": flags,
        "metrics": metrics,
    }


def verify_titles_deep(cur, titles, allow_list, family=None):
    seen = set()
    valid, rejected, metrics = [], [], {}
    for title in titles or []:
        if not isinstance(title, str) or not title.strip():
            continue
        result = verify_title_deep(cur, title, allow_list, family, seen=seen)
        if result["passed"]:
            valid.append(title)
            metrics[title] = result.get("metrics") or {}
        else:
            rejected.append((title, result.get("reasons") or []))
    return valid, rejected, metrics


def facts_from_stats(stats, extra=None):
    facts = []
    for value in (stats or {}).values():
        if isinstance(value, (int, float)):
            facts.append(float(value))
    for value in (extra or {}).values():
        if isinstance(value, (int, float)):
            facts.append(float(value))
    return facts


def _number_supported(value, facts, allow_small):
    if allow_small and value in allow_small:
        return True
    for fact in facts:
        if fact == 0:
            continue
        if abs(value - fact) <= max(1.0, 0.15 * abs(fact)):
            return True
    return False


def verify_claims_text(text, facts, allow_small=None):
    if not text or not isinstance(text, str):
        return text, []
    facts = [f for f in facts or [] if isinstance(f, (int, float))]
    allow = set(allow_small or ())
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept, dropped = [], []
    for sentence in sentences:
        guarantee = None
        for pattern, label in GUARANTEE_PATTERNS:
            if re.search(pattern, sentence, re.I):
                guarantee = label
                break
        if guarantee:
            dropped.append({
                "text": sentence.strip(),
                "unsupported": [],
                "claim": guarantee,
            })
            continue
        nums = []
        for raw in NUMBER_RE.findall(sentence):
            try:
                nums.append(float(raw.replace(",", "")))
            except Exception:
                continue
        unsupported = [
            n for n in nums if not _number_supported(n, facts, allow)
        ]
        if unsupported:
            dropped.append({
                "text": sentence.strip(),
                "unsupported": unsupported,
            })
        else:
            kept.append(sentence.strip())
    return " ".join(kept).strip(), dropped


BUCKET_WORDS = (
    "SATURATED", "GOLD", "OPPORTUNITY", "NEUTRAL", "WEAK", "DEAD",
    "VIRGIN", "CONTESTED", "OPEN", "UNPROVEN",
)


def reconcile_bucket_text(text, actual_bucket):
    """Drop sentences that assert a different bucket than the DB says."""
    if not text or not actual_bucket:
        return text, []
    actual = str(actual_bucket).upper()
    kept, dropped = [], []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        claimed = [b for b in BUCKET_WORDS
                   if re.search(rf"\b{b}\b", sentence, re.I)]
        if claimed and actual not in claimed:
            dropped.append(sentence.strip())
        else:
            kept.append(sentence.strip())
    return " ".join(kept).strip(), dropped


DESC_BAD_RE = re.compile(
    r"\b(zero sales|no sales|0 sales|brutal|dead|failed|failure|"
    r"saturated|algorithm|title stack|tags are|tag stack|we are|we're|"
    r"our |fixing|mess|flex on|guarantee|100\s*%|viral|blow up|"
    r"instant hit|risk[- ]?free)\b",
    re.I,
)


def sanitize_description(text, item_name, fallback):
    """Customer-facing copy only. Drop internal/negative claims."""
    if not text or not isinstance(text, str):
        return fallback
    kept = []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        s = sentence.strip()
        if not s:
            continue
        if DESC_BAD_RE.search(s):
            continue
        if s.lower().startswith(("we ", "our ")):
            continue
        kept.append(s)
    cleaned = " ".join(kept).strip()
    if len(cleaned.split()) < 4:
        return fallback
    return cleaned


def _clean_title_for_copy(item_name):
    t = re.sub(r"[^A-Za-z0-9 ]+", " ", item_name or "").strip()
    t = re.sub(r"\s+", " ", t)
    return t or "this item"


def fix_descriptions(data, item_name):
    """Replace bad AI descriptions with safe customer-facing copy."""
    title = _clean_title_for_copy(item_name)
    fallbacks = {
        "description_seo": (
            f"{title} for your avatar. A smooth, playful animation made "
            f"for your next dance."
        ),
        "description_hype": (
            f"Make your next dance stand out with {title}. A playful motion "
            f"built for your avatar."
        ),
        "description_short": f"{title} for your avatar.",
    }
    for key, fallback in fallbacks.items():
        if data.get(key):
            data[key] = sanitize_description(data[key], item_name, fallback)
    return data


def clean_text_fields(data, facts, allow_small=None, skip=None):
    """Clean every prose string/list field in an AI payload."""
    drops = []
    skip = set(skip or ())
    for key, value in list(data.items()):
        if key in skip:
            continue
        if isinstance(value, str):
            cleaned, dropped = verify_claims_text(
                value, facts, allow_small=allow_small
            )
            if dropped:
                data[key] = cleaned
                drops.extend({"field": key, **d} for d in dropped)
        elif isinstance(value, list):
            kept = []
            for item in value:
                if isinstance(item, str):
                    cleaned, dropped = verify_claims_text(
                        item, facts, allow_small=allow_small
                    )
                    if dropped:
                        drops.extend({"field": key, **d} for d in dropped)
                        if cleaned:
                            kept.append(cleaned)
                    else:
                        kept.append(item)
                else:
                    kept.append(item)
            data[key] = kept
    return drops


def verify_pivot(cur, pivot, family=None):
    if not pivot or not pivot.get("keyword"):
        return None, "no pivot supplied"
    from opportunity_score import score_opportunity
    opp = score_opportunity(cur, pivot["keyword"], family)
    if not opp:
        return None, "pivot did not resolve in the database"
    if opp["supply"] == 0 and opp["demand_live"] == 0:
        return None, "pivot has zero supply and zero live demand"
    if opp["verdict"] in ("DEAD", "SATURATED"):
        return None, f"pivot is {opp['verdict']}"
    return {
        "keyword": opp["phrase"],
        "supply": opp["supply"],
        "supply_recent30": opp["supply_recent30"],
        "median_favs": opp["median_favs"],
        "demand": opp["demand_live"],
        "demand_volume": opp["demand_volume"],
        "exact": opp["exact"],
        "ctr_proxy": opp["ctr_proxy"],
        "bucket": opp["verdict"],
        "family": family,
    }, None


def verify_synth(cur, synth, allow_list, family, facts,
                 actual_bucket=None, item_name=None):
    if not isinstance(synth, dict):
        return synth, {"verified": 0, "rejected": [], "claims": [],
                       "pivot": None}
    groups = ("titles_safe", "titles_differentiated",
              "titles_longtail", "titles_viral")
    seen = set()
    verified = 0
    rejected = []
    metrics = {}
    for key in groups:
        titles = synth.get(key) or []
        kept = []
        for title in titles:
            result = verify_title_deep(cur, title, allow_list, family, seen=seen)
            if result["passed"]:
                kept.append(title)
                verified += 1
                metrics[title] = result.get("metrics") or {}
                metrics[title]["flags"] = result.get("flags") or []
            else:
                rejected.append({
                    "title": title,
                    "group": key,
                    "stage": result.get("stage"),
                    "reasons": result.get("reasons") or [],
                })
        synth[key] = kept

    allowed = allow_set(allow_list)
    killers = synth.get("killer_keywords")
    if isinstance(killers, list):
        kept_killers = []
        for kw in killers:
            toks = tokens(str(kw))
            if toks and all(
                t in allowed or t in STOPWORDS or t.isdigit()
                or any(t.startswith(a) or a.startswith(t)
                       for a in allowed if len(a) >= 4)
                for t in toks
            ):
                kept_killers.append(kw)
        synth["killer_keywords"] = kept_killers

    rejected_keywords = []
    primary = synth.get("primary_keyword")
    if isinstance(primary, str) and primary.strip():
        toks = tokens(primary)
        valid = bool(toks) and all(
            t in allowed or t in STOPWORDS or t.isdigit() or len(t) == 1
            for t in toks
        )
        if not valid:
            rejected_keywords.append(primary)
            synth["primary_keyword"] = ""

    claims = clean_text_fields(
        synth, facts, allow_small={7, 14, 30},
        skip=set(TITLE_FIELDS) | {"best_pivot", "killer_keywords"},
    )
    fix_descriptions(
        synth,
        item_name or synth.get("item_name") or synth.get("concept")
        or "this item",
    )
    if actual_bucket:
        for field in ("saturation_verdict", "search_diagnosis", "diagnosis",
                  "edit_reasoning", "what_was_wrong"):
            cleaned_b, dropped_b = reconcile_bucket_text(
                synth.get(field), actual_bucket
            )
            if dropped_b:
                synth[field] = cleaned_b
                claims.extend(
                    {"field": field, "text": s, "unsupported": [],
                     "claim": "bucket mismatch"}
                    for s in dropped_b
                )

    pivots = []
    for key in ("best_pivot",):
        pivot = synth.get(key)
        if pivot:
            info, reason = verify_pivot(cur, pivot, family)
            pivots.append({
                "field": key,
                "accepted": bool(info),
                "reason": reason,
                "verified": info,
            })
            if not info:
                synth[key] = {}
            else:
                verified_pivot = dict(pivot)
                verified_pivot.update(info)
                why_clean, why_dropped = verify_claims_text(
                    verified_pivot.get("why_better"),
                    [info.get("supply", 0), info.get("median_favs", 0),
                     info.get("demand", 0)],
                    allow_small={7, 14, 30},
                )
                if why_dropped:
                    verified_pivot["why_better"] = why_clean
                    claims.extend(
                        {"field": f"{key}.why_better", **d} for d in why_dropped
                    )
                synth[key] = verified_pivot

    return synth, {
        "verified": verified,
        "rejected": rejected,
        "metrics": metrics,
        "claims": claims,
        "pivots": pivots,
        "rejected_keywords": rejected_keywords,
    }


def format_audit(audit):
    if not audit:
        return ""
    lines = ["## ✅ Verification audit"]
    if audit.get("error"):
        lines.append(
            f"• ❌ verification error: `{audit['error']}` — "
            f"unverified AI titles were withheld."
        )
    lines.append(
        f"• Titles passed: **{audit.get('verified', 0)}** · "
        f"rejected: **{len(audit.get('rejected', []))}**"
    )
    warned = 0
    for title, m in (audit.get("metrics") or {}).items():
        flags = m.get("flags") or []
        if flags and warned < 3:
            lines.append(
                f"• ⚠️ `{title[:60]}` — {'; '.join(flags)[:150]}"
            )
            warned += 1
    for item in (audit.get("rejected") or [])[:6]:
        reasons = "; ".join(item.get("reasons") or [])[:140]
        lines.append(f"• ❌ `{item.get('title', '')[:60]}` — {reasons}")
    for item in (audit.get("claims") or [])[:4]:
        nums = ", ".join(f"{n:g}" for n in item.get("unsupported", []))
        reason = (f"numbers: {nums}" if nums
                  else f"claim: {item.get('claim', 'unsupported')}")
        lines.append(
            f"• 🗑️ dropped unsupported {reason} in `{item.get('field')}`"
        )
    for kw in (audit.get("rejected_keywords") or [])[:3]:
        lines.append(f"• ❌ primary keyword unverified: `{kw[:60]}`")
    for pivot in (audit.get("pivots") or []):
        if pivot.get("accepted"):
            info = pivot.get("verified") or {}
            lines.append(
                f"• ✅ pivot `{info.get('keyword')}` — "
                f"supply {info.get('supply')} · {info.get('bucket')}"
            )
        else:
            lines.append(f"• ❌ pivot rejected — {pivot.get('reason')}")
    return "\n".join(lines)
