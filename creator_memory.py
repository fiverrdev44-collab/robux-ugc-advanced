import os
from difflib import SequenceMatcher

"""creator_memory.py — Astra runs, asset linking, and launch outcomes.

A generated recommendation is not applied automatically. !link connects a run
to the uploaded asset and stores the baseline; !outcome reports deltas from
item_history and recorded sales. External link tracking is intentionally absent.
"""
SCHEMA = """
create table if not exists astra_runs (
    id bigserial primary key,
    item_id bigint,
    linked_item_id bigint,
    concept text,
    asset_type text,
    angles jsonb,
    titles jsonb,
    chosen_title text,
    preview_version text,
    created_at timestamptz default now(),
    linked_at timestamptz
);
create index if not exists idx_astra_runs_item on astra_runs (item_id);
create index if not exists idx_astra_runs_linked on astra_runs (linked_item_id);

create table if not exists astra_outcomes (
    id bigserial primary key,
    run_id bigint not null unique,
    item_id bigint not null,
    baseline_favorites integer,
    baseline_sales integer,
    baseline_captured_at timestamptz default now(),
    launched_at timestamptz default now(),
    heuristic_version text,
    created_at timestamptz default now()
);
create index if not exists idx_astra_outcomes_item on astra_outcomes (item_id);
"""


def ensure_schema(cur, conn=None):
    cur.execute(SCHEMA)
    if conn is not None:
        conn.commit()


def record_run(cur, concept, titles, chosen_title=None, asset_type=None,
               angles=None, item_id=None, preview_version=None):
    cur.execute("""
        insert into astra_runs
          (item_id, concept, asset_type, angles, titles, chosen_title,
           preview_version)
        values (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
        returning id
    """, (item_id, (concept or "")[:300], asset_type,
          str(angles or []), str(list(titles or [])[:5]),
          (chosen_title or "")[:200], (preview_version or "")[:120]))
    return cur.fetchone()[0]


def link_run(cur, run_id, item_id, heuristic_version=None):
    """Link a run to an uploaded asset and snapshot the launch baseline."""
    cur.execute("""
        select id, chosen_title, concept from astra_runs where id = %s
    """, (run_id,))
    run = cur.fetchone()
    if not run:
        return {"ok": False, "error": "run not found"}
    cur.execute("""
        select coalesce(favorite_count, 0), coalesce(total_sales, 0), name
        from items where id = %s
    """, (item_id,))
    item = cur.fetchone()
    if not item:
        return {"ok": False, "error": "asset not found in catalog"}
    baseline_favs, baseline_sales, name = item
    cur.execute("""
        update astra_runs
        set linked_item_id = %s, item_id = %s, linked_at = now()
        where id = %s
    """, (item_id, item_id, run_id))
    cur.execute("""
        insert into astra_outcomes
          (run_id, item_id, baseline_favorites, baseline_sales,
           baseline_captured_at, launched_at, heuristic_version)
        values (%s, %s, %s, %s, now(), now(), %s)
        on conflict (run_id) do nothing
        returning id
    """, (run_id, item_id, baseline_favs, baseline_sales, heuristic_version))
    row = cur.fetchone()
    return {"ok": True, "run_id": run_id, "item_id": item_id,
            "title": run[1], "name": name,
            "baseline_favorites": baseline_favs,
            "baseline_sales": baseline_sales,
            "outcome_row": row[0] if row else None}


def outcome_report(cur, run_id):
    """Deltas since launch from astra_outcomes + item_history + my_sales."""
    cur.execute("""
        select o.run_id, o.item_id, o.baseline_favorites, o.baseline_sales,
               o.launched_at, r.chosen_title, i.name
        from astra_outcomes o
        join astra_runs r on r.id = o.run_id
        left join items i on i.id = o.item_id
        where o.run_id = %s
    """, (run_id,))
    row = cur.fetchone()
    if not row:
        return {"found": False, "run_id": run_id}
    (rid, item_id, base_favs, base_sales, launched, title, name) = row
    base_favs = int(base_favs or 0)
    cur.execute("""
        select favorite_count, snapshot_at from item_history
        where item_id = %s order by snapshot_at desc limit 1
    """, (item_id,))
    latest = cur.fetchone()
    latest_favs = int(latest[0]) if latest and latest[0] is not None else None

    cur.execute("""
        select favorite_count from item_history
        where item_id = %s and snapshot_at <= %s + interval '7 days'
        order by snapshot_at desc limit 1
    """, (item_id, launched))
    d7 = cur.fetchone()
    d7_favs = int(d7[0]) if d7 and d7[0] is not None else None

    cur.execute("""
        select count(*), coalesce(sum(s.amount_robux), 0)
        from my_sales s
        join items i on lower(i.name) = lower(s.item_name)
        where i.id = %s
          and s.sale_date >= (%s at time zone 'UTC')::date
    """, (item_id, launched))
    units, robux = cur.fetchone()
    units = int(units or 0)

    from datetime import datetime, timezone
    if isinstance(launched, str):
        launched = datetime.fromisoformat(launched)
    if launched.tzinfo is None:
        launched = launched.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - launched).total_seconds() / 86400

    delta = (d7_favs if d7_favs is not None else latest_favs)
    delta = (delta - base_favs) if delta is not None else None
    if days >= 30:
        status = "D30 window reached (compare against baseline)"
    elif days >= 7:
        status = "Tracking (D30 pending)"
    else:
        status = "Tracking (D7 pending)"
    label = title or name or f"run {rid}"
    fav_text = f"{delta:+d}" if delta is not None else "unknown"
    message = (f"Recommendation: '{label}'. Launched on "
               f"{launched.strftime('%b %d') if hasattr(launched, 'strftime') else launched}. "
               f"D7 Favorites: {fav_text}. Units Sold: {units}. Status: {status}.")
    return {
        "found": True, "run_id": rid, "item_id": item_id, "title": label,
        "launched_at": str(launched), "baseline_favorites": base_favs,
        "baseline_sales": int(base_sales or 0),
        "latest_favorites": latest_favs, "d7_favorites": d7_favs,
        "favorites_delta": delta, "units_since_launch": units,
        "robux_since_launch": int(robux or 0), "days_since_launch": round(days, 1),
        "status": status, "message": message,
    }


def recent_runs(cur, item_id=None, limit=20):
    if item_id:
        cur.execute("""
            select id, item_id, concept, asset_type, angles, titles,
                   chosen_title, preview_version, created_at, linked_item_id
            from astra_runs where item_id = %s
            order by created_at desc limit %s
        """, (item_id, int(limit)))
    else:
        cur.execute("""
            select id, item_id, concept, asset_type, angles, titles,
                   chosen_title, preview_version, created_at, linked_item_id
            from astra_runs order by created_at desc limit %s
        """, (int(limit),))
    return [{
        "id": r[0], "item_id": r[1], "concept": r[2], "asset_type": r[3],
        "angles": r[4], "titles": r[5], "chosen_title": r[6],
        "preview_version": r[7], "created_at": str(r[8]),
        "linked_item_id": r[9],
    } for r in cur.fetchall()]


def algorithm_outcome(cur, run_id):
    """Legacy launch_ledger answer (kept for existing callers)."""
    cur.execute("""
        select id, item_id, linked_item_id, chosen_title, concept, created_at
        from astra_runs where id = %s
    """, (run_id,))
    run = cur.fetchone()
    if not run:
        return {"found": False, "run_id": run_id}
    rid, item_id, linked, title, concept, created = run
    target = linked or item_id
    ledger = None
    if target:
        cur.execute("""
            select item_id, title, favs_d7, favs_d30, units_d7, units_d30,
                   revenue_d7, revenue_d30, label_beat_median
            from launch_ledger where item_id = %s
        """, (target,))
        ledger = cur.fetchone()
    if not ledger and title:
        cur.execute("""
            select item_id, title, favs_d7, favs_d30, units_d7, units_d30,
                   revenue_d7, revenue_d30, label_beat_median
            from launch_ledger where lower(title) = lower(%s)
            order by launched_at desc limit 1
        """, (title,))
        ledger = cur.fetchone()
    if not ledger:
        return {"found": True, "run_id": rid, "item_id": target,
                "title": title or concept, "launched": False,
                "message": (f"Recommendation {rid} ({title or concept}) was "
                            f"generated. No launch is tracked for it yet.")}
    (l_item, l_title, d7, d30, u7, u30, r7, r30, beat) = ledger
    favs = d30 if d30 is not None else d7
    return {"found": True, "launched": True, "run_id": rid, "item_id": l_item,
            "title": title or l_title, "launch_title": l_title,
            "favs_d7": d7, "favs_d30": d30, "units_d30": u30,
            "revenue_d30": r30, "beat_median": beat,
            "message": (f"Recommendation {rid} ({title or l_title}) was generated. "
                        f"When launched, it achieved {favs if favs is not None else 'no'} "
                        f"favorites"
                        + (f" and {u30} units (D30)" if u30 is not None else "")
                        + ".")}


def outcome_summary(cur, item_id=None, limit=10):
    where = ("measured_at is not null and outcome is not null "
             "and coalesce(maturity,'pending') in ('mature','partial')")
    if item_id:
        cur.execute(f"""select id, item_id, maturity, outcome, measured_at
                        from recommendation_ledger
                        where {where} and item_id = %s
                        order by measured_at desc limit %s""",
                    (item_id, int(limit)))
    else:
        cur.execute(f"""select id, item_id, maturity, outcome, measured_at
                        from recommendation_ledger
                        where {where}
                        order by measured_at desc limit %s""",
                    (int(limit),))
    return [{"rec_id": r[0], "item_id": r[1], "maturity": r[2],
             "outcome": r[3], "measured_at": str(r[4])}
            for r in cur.fetchall()]


# ── Auto-linker (Phase 3 automation) ──

def _norm_family(family):
    f = (family or "").lower()
    if f in ("emote", "emotes"):
        return "emote"
    if f in ("clothing", "classic", "tops", "shirt", "pants", "jacket"):
        return "clothing"
    if f in ("accessory", "waist", "neck", "back", "front", "shoulder",
             "gear", "back accessory"):
        return "accessory"
    if f in ("hat", "hats"):
        return "headwear"
    return f


def match_run_to_items(run, items, threshold=0.80):
    """Best matching owned item for one run, respecting family."""
    title = (run.get("chosen_title") or run.get("concept") or "").strip()
    if not title:
        return None
    run_fam = _norm_family(run.get("asset_type"))
    best = None
    for it in items:
        from category_configs import detect_family_from_asset_type
        item_fam = _norm_family(
            detect_family_from_asset_type(it.get("asset_type_id")))
        if run_fam and item_fam and run_fam != item_fam:
            continue
        ratio = SequenceMatcher(
            None, title.lower(), (it.get("name") or "").lower()).ratio()
        if ratio >= threshold and (best is None or ratio > best["ratio"]):
            best = {"item": it, "ratio": round(ratio, 3)}
    return best


def _owned_items(cur):
    """Portfolio ids plus group-owned catalog items."""
    items = {}
    try:
        cur.execute("select item_id from my_portfolio")
        ids = [r[0] for r in cur.fetchall() if r[0]]
    except Exception:
        ids = []
    if ids:
        cur.execute("""
            select id, name, favorite_count, total_sales, created_at,
                   asset_type_id
            from items where id = any(%s)
        """, (ids,))
        for r in cur.fetchall():
            items[r[0]] = {"id": r[0], "name": r[1], "favorite_count": r[2],
                           "total_sales": r[3], "created_at": r[4],
                           "asset_type_id": r[5]}
    groups = [g.strip() for g in
              (os.getenv("MY_GROUP_NAMES") or "").split(",") if g.strip()]
    if groups:
        cur.execute("""
            select id, name, favorite_count, total_sales, created_at,
                   asset_type_id
            from items where creator_name = any(%s)
        """, (groups,))
        for r in cur.fetchall():
            items[r[0]] = {"id": r[0], "name": r[1], "favorite_count": r[2],
                           "total_sales": r[3], "created_at": r[4],
                           "asset_type_id": r[5]}
    return list(items.values())


def auto_link_recent_runs(days=30, threshold=0.80, notifier=None,
                          db_factory=None):
    """Match recent unlinked chain runs to owned, newer catalog items."""
    if db_factory is None:
        from bot_core import get_db as db_factory
    conn = db_factory(); cur = conn.cursor()
    matches = []
    try:
        cur.execute("SET statement_timeout='20s'")
        cur.execute("""
            select id, chosen_title, asset_type, created_at, concept
            from astra_runs
            where linked_item_id is null
              and created_at > now() - make_interval(days => %s)
            order by created_at
        """, (int(days),))
        runs = [{"id": r[0], "chosen_title": r[1], "asset_type": r[2],
                 "created_at": r[3], "concept": r[4]} for r in cur.fetchall()]
        if not runs:
            return {"runs": 0, "matches": []}
        items = _owned_items(cur)
        used = set()
        for run in runs:
            candidates = [it for it in items
                          if it["id"] not in used
                          and (it.get("created_at") is None
                               or run["created_at"] is None
                               or it["created_at"] >= run["created_at"])]
            best = match_run_to_items(run, candidates, threshold=threshold)
            if not best:
                continue
            item = best["item"]
            res = link_run(cur, run["id"], item["id"],
                           heuristic_version="astra-fit-v1")
            if res.get("ok"):
                used.add(item["id"])
                matches.append({
                    "run_id": run["id"], "title": run["chosen_title"],
                    "item_id": item["id"], "item_name": item["name"],
                    "ratio": best["ratio"],
                })
        conn.commit()
        for m in matches:
            text = (f"🤖 Auto-Linked! Run #{m['run_id']} "
                    f"('{m['title']}') was matched to your new item "
                    f"'{m['item_name']}' (ID: {m['item_id']}). "
                    f"Tracking started.")
            if notifier:
                try:
                    notifier(text)
                except Exception as e:
                    print(f"[auto-link] notify failed: {e}", flush=True)
            print(f"[auto-link] {text}", flush=True)
        return {"runs": len(runs), "matches": matches}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[auto-link] failed: {type(e).__name__}: {e}", flush=True)
        return {"error": f"{type(e).__name__}: {e}", "matches": []}
    finally:
        try:
            cur.close(); conn.close()
        except Exception:
            pass
