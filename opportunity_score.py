"""opportunity_score.py — demand vs competition with an explicit reliability flag.

Demand is only treated as real when it comes from live Roblox suggestions.
The `__db_mined__` rows are item-derived, so they are reported but never used
as primary evidence. Novel multi-word names are scored on their strongest
anchor token so a new combination does not automatically look "unproven".
"""
import math
import re

TYPE_WORDS = {
    "emote", "dance", "animation", "hat", "beanie", "crown", "cap", "hair",
    "face", "mask", "shirt", "pants", "jacket", "shoes", "wing", "wings",
    "tail", "ears", "horn", "horns", "glasses", "necklace", "chain",
    "backpack", "sword", "pet", "bag", "scarf", "bandana", "beret", "visor",
    "lens", "head", "snapback", "bonnet", "balaclava",
}


def _is_type_word(word):
    if word in TYPE_WORDS:
        return True
    try:
        from category_configs import get_all_type_words
        return word in get_all_type_words()
    except Exception:
        return False


def _normalize_phrase(text):
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _match(phrase):
    clean = _normalize_phrase(phrase)
    if not clean:
        return None, None
    if " " in clean:
        return "ilike", f"%{clean}%"
    return "~*", rf"\y{re.escape(clean)}\y"


def _family_ids(family):
    try:
        from convergence_engine import resolve_family_ids
        return resolve_family_ids(family)
    except Exception:
        return None


def _family_median(cur, family):
    ids = _family_ids(family)
    if not ids:
        cur.execute("""
            select percentile_cont(0.5) within group (order by favorite_count)
            from items where favorite_count > 5
        """)
    else:
        ph = ",".join(["%s"] * len(ids))
        cur.execute(f"""
            select percentile_cont(0.5) within group (order by favorite_count)
            from items where favorite_count > 5
              and asset_type_id in ({ph})
        """, list(ids))
    row = cur.fetchone()
    return max(float((row or [0])[0] or 0), 25.0)


def _anchor_token(cur, toks, ids, fam_sql, fam_params):
    patterns = [rf"\y{re.escape(t)}\y" for t in toks]
    try:
        cur.execute("""
            select suggestion, search_volume, seed_keyword
            from search_suggestions
            where suggestion ~* any(%s)
            limit 5000
        """, (patterns,))
        rows = cur.fetchall()
    except Exception:
        rows = []

    volume = {t: 0 for t in toks}
    live = {t: 0 for t in toks}
    for suggestion, vol, seed in rows:
        sl = (suggestion or "").lower()
        for tok in toks:
            if re.search(rf"\b{re.escape(tok)}\b", sl):
                if seed != "__db_mined__":
                    live[tok] += 1
                    volume[tok] += int(vol or 0)
    if any(volume.values()) or any(live.values()):
        return max(toks, key=lambda t: (volume[t], live[t]))

    filters = ", ".join(
        ["count(*) filter (where lower(name) ~* %s)"] * len(toks)
    )
    params = list(patterns) + list(fam_params)
    try:
        cur.execute(f"""
            select {filters} from items
            where favorite_count > 5 {fam_sql}
        """, params)
        counts = [int(c or 0) for c in cur.fetchone()]
    except Exception:
        counts = []
    if counts and max(counts) > 0:
        return toks[counts.index(max(counts))]
    return None


def score_opportunity(cur, phrase, family=None):
    op, pat = _match(phrase)
    if not op:
        return None
    ids = _family_ids(family)
    fam_sql, fam_params = "", []
    if ids:
        fam_sql = " and asset_type_id in (" + ",".join(["%s"] * len(ids)) + ")"
        fam_params = list(ids)

    cur.execute(f"""
        select count(*),
               coalesce(percentile_cont(0.5) within group
                        (order by favorite_count), 0),
               coalesce(percentile_cont(0.9) within group
                        (order by favorite_count), 0),
               count(*) filter (where created_at > now() - make_interval(days => 30)),
               count(*) filter (where created_at > now() - make_interval(days => 14)),
               count(*) filter (where created_at <= now() - make_interval(days => 14)
                                  and created_at > now() - make_interval(days => 28))
        from items
        where name {op} %s and favorite_count > 5 {fam_sql}
    """, [pat] + fam_params)
    row = cur.fetchone()
    supply, median_favs, p90_favs, recent30, recent14, prior14 = row
    supply = int(supply or 0)

    cur.execute(f"""
        select count(*) from items
        where lower(name) = lower(%s) and favorite_count > 5 {fam_sql}
    """, [str(phrase).strip()] + fam_params)
    exact = int(cur.fetchone()[0] or 0)

    cur.execute(f"""
        select count(*) from search_suggestions
        where suggestion {op} %s
    """, (pat,))
    demand_all = int(cur.fetchone()[0] or 0)
    cur.execute(f"""
        select count(*),
               coalesce(sum(1.0 / greatest(rank, 1)), 0),
               coalesce(sum(search_volume), 0)
        from search_suggestions
        where suggestion {op} %s
          and seed_keyword is distinct from %s
    """, (pat, "__db_mined__"))
    demand_row = cur.fetchone()
    demand_live = int(demand_row[0] or 0)
    demand_weighted = float(demand_row[1] or 0)
    demand_volume = int(demand_row[2] or 0)

    is_phrase = " " in _normalize_phrase(phrase)
    if supply == 0 and is_phrase:
        toks = [t for t in re.findall(r"[a-z0-9]{3,}",
                                      _normalize_phrase(phrase))
                if not _is_type_word(t)]
        anchor = _anchor_token(cur, toks, ids, fam_sql, fam_params) if toks else None
        if anchor:
            base = score_opportunity(cur, anchor, family)
            if base and base.get("supply", 0) > 0:
                result = dict(base)
                result.update({
                    "phrase": phrase,
                    "exact": exact,
                    "phrase_supply": 0,
                    "basis": "token",
                    "anchor": anchor,
                    "reasons": (base.get("reasons") or []) + [
                        f"new phrase; scored on token '{anchor}'"
                    ],
                })
                if result.get("verdict") == "DEAD":
                    result["verdict"] = "UNPROVEN"
                return result

    fam_median = _family_median(cur, family)
    cur.execute(f"""
        select count(*) from items
        where name {op} %s and favorite_count >= %s {fam_sql}
    """, [pat, fam_median] + fam_params)
    strong = int(cur.fetchone()[0] or 0)

    cur.execute(f"""
        select coalesce(sum(favorite_count), 0), max(favorite_count)
        from items
        where name {op} %s and favorite_count > 5 {fam_sql}
    """, [pat] + fam_params)
    total_favs, top_favs = cur.fetchone()
    total_favs = float(total_favs or 0)
    concentration = (float(top_favs or 0) / total_favs) if total_favs else 0.0

    try:
        cur.execute(f"""
            with s as (
                select ih.item_id,
                       max(ih.favorite_count) - min(ih.favorite_count) as delta,
                       extract(epoch from
                           (max(ih.snapshot_at) - min(ih.snapshot_at)))/86400.0 as days
                from item_history ih
                join items i on i.id = ih.item_id
                where i.name {op} %s
                  and ih.snapshot_at > now() - make_interval(days => 14)
                  {fam_sql.replace('asset_type_id', 'i.asset_type_id')}
                group by ih.item_id
                having extract(epoch from
                       (max(ih.snapshot_at) - min(ih.snapshot_at)))/86400.0 >= 2
            )
            select avg(delta / days) from s where delta >= 1
        """, [pat] + fam_params)
        velocity = float(cur.fetchone()[0] or 0)
    except Exception:
        velocity = 0.0
    velocity = min(velocity, 20.0)

    supply_recent = int(recent30 or 0)
    heat = (float(recent14 or 0) / max(float(prior14 or 0), 1.0))
    reliable = demand_live > 0
    proof = strong >= 3

    if supply == 0 and demand_all == 0:
        verdict = "DEAD"
    elif supply >= 500 or (is_phrase and exact >= 10):
        verdict = "SATURATED"
    elif not proof:
        verdict = "UNPROVEN"
    elif reliable and demand_live >= 10 and supply <= 60 and strong <= 15:
        verdict = "OPEN"
    elif reliable and strong > max(25.0, demand_live * 3.0):
        verdict = "SATURATED"
    else:
        verdict = "CONTESTED"

    if reliable:
        count_score = min(math.log1p(demand_live) / math.log1p(50), 1.0)
        if demand_volume > 0:
            volume_score = min(
                math.log1p(demand_volume) / math.log1p(1_000_000), 1.0
            )
            demand_score = 0.6 * volume_score + 0.4 * count_score
        else:
            demand_score = count_score
    else:
        demand_score = 0.25 * min(math.log1p(demand_all) / math.log1p(50), 1.0)
    saturation_ratio = (strong / max(demand_live, 1)) if reliable else None
    openness = (1.0 / (1.0 + saturation_ratio)
                if reliable else
                max(0.0, 1.0 - min(supply / 500.0, 1.0)))
    heat_score = min(max(heat, 0.0) / 2.0, 1.0)
    proof_score = 1.0 if proof else 0.3
    ctr = 100.0 * (0.45 * demand_score + 0.30 * openness +
                   0.15 * heat_score + 0.10 * proof_score)
    if not reliable:
        ctr = min(ctr, 40.0)

    if reliable and demand_live >= 10 and supply >= 5:
        confidence = "HIGH"
    elif proof and demand_all >= 3:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    reasons = []
    if not reliable:
        reasons.append("no live demand measured (fallback is supply-derived)")
    if not proof:
        reasons.append("fewer than 3 items above the family median (no proof)")
    if exact >= 10 and is_phrase:
        reasons.append(f"{exact} exact-name competitors")
    if supply >= 500:
        reasons.append(f"{supply} matching items")
    if supply_recent >= 50:
        reasons.append(f"{supply_recent} new items in 30 days")

    return {
        "phrase": phrase,
        "family": family or "all",
        "basis": "phrase",
        "anchor": None,
        "demand": demand_all,
        "demand_live": demand_live,
        "demand_mined": demand_all - demand_live,
        "demand_volume": demand_volume,
        "demand_weighted": round(demand_weighted, 2),
        "demand_reliable": reliable,
        "supply": supply,
        "supply_recent30": supply_recent,
        "strong": strong,
        "exact": exact,
        "median_favs": round(float(median_favs or 0), 1),
        "p90_favs": round(float(p90_favs or 0), 1),
        "family_median": round(fam_median, 1),
        "velocity": round(velocity, 2),
        "heat": round(heat, 2),
        "concentration": round(concentration, 2),
        "proof": proof,
        "saturation": (round(saturation_ratio, 2)
                       if saturation_ratio is not None else None),
        "ctr_proxy": round(ctr, 1),
        "verdict": verdict,
        "confidence": confidence,
        "reasons": reasons,
    }
