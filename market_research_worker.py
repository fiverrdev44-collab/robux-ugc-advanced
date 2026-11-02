"""market_research_worker.py — priority-based marketplace refresh.

Runs from the scheduler every 6 hours (not on the Discord event loop):
HIGH   active experiments + own launched items (launch_ledger)
MEDIUM recent launches / high-favorite catalog items
LOW    broad exploratory catalog sample

Bounded (<=300 ids/cycle, 30-item batches, concurrency 3), Retry-After handled
by RobloxBatchClient, idempotent upserts, simple circuit breaker. No cookie
rotation. Never blocks Discord command handling.
"""
import os
import time

MAX_PER_CYCLE = int(os.getenv("RESEARCH_MAX_IDS", "300"))
HIGH_LIMIT = int(os.getenv("RESEARCH_HIGH_LIMIT", "60"))
MEDIUM_LIMIT = int(os.getenv("RESEARCH_MEDIUM_LIMIT", "120"))
LOW_LIMIT = int(os.getenv("RESEARCH_LOW_LIMIT", "120"))
CIRCUIT_THRESHOLD = int(os.getenv("RESEARCH_CIRCUIT_FAILS", "5"))
CIRCUIT_COOLDOWN_S = int(os.getenv("RESEARCH_CIRCUIT_SECONDS", "1800"))

_circuit = {"failures": 0, "open_until": 0.0}


def circuit_open():
    return time.time() < _circuit["open_until"]


def _record_failure():
    _circuit["failures"] += 1
    if _circuit["failures"] >= CIRCUIT_THRESHOLD:
        _circuit["open_until"] = time.time() + CIRCUIT_COOLDOWN_S


def _record_success():
    _circuit["failures"] = 0
    _circuit["open_until"] = 0.0


def select_priority_ids(cur, high=HIGH_LIMIT, medium=MEDIUM_LIMIT,
                        low=LOW_LIMIT):
    """Return (ids, tiers) ordered HIGH -> MEDIUM -> LOW, deduped."""
    buckets = []
    cur.execute("""
        select item_id from launch_ledger
        order by launched_at desc nulls last limit %s
    """, (int(high),))
    buckets.append(("high", [r[0] for r in cur.fetchall() if r[0]]))

    cur.execute("""
        select id from items
        where created_at > now() - interval '30 days'
          and coalesce(favorite_count, 0) > 0
        order by favorite_count desc nulls last
        limit %s
    """, (int(medium),))
    buckets.append(("medium", [r[0] for r in cur.fetchall() if r[0]]))

    cur.execute("""
        select id from items
        where favorite_count is null
        order by id desc
        limit %s
    """, (int(low),))
    buckets.append(("low", [r[0] for r in cur.fetchall() if r[0]]))

    seen, ids, tiers = set(), [], []
    for tier, rows in buckets:
        for iid in rows:
            if iid in seen:
                continue
            seen.add(iid)
            ids.append(iid)
            tiers.append(tier)
            if len(ids) >= MAX_PER_CYCLE:
                return ids, tiers
    return ids, tiers


def _upsert(cur, rows):
    if not rows:
        return 0
    from psycopg2.extras import execute_values
    template = "(%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)"
    execute_values(cur, """
        INSERT INTO items (id, name, favorite_count, price, description,
                           creator_name, asset_type_id, favorite_status,
                           fetched_at)
        VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            favorite_count = EXCLUDED.favorite_count,
            favorite_status = EXCLUDED.favorite_status,
            price = EXCLUDED.price,
            description = EXCLUDED.description,
            name = EXCLUDED.name,
            asset_type_id = EXCLUDED.asset_type_id,
            fetched_at = CURRENT_TIMESTAMP
    """, rows, template=template, page_size=100)
    return len(rows)


def run_cycle(db_factory=None):
    """One research cycle. Returns a small summary dict."""
    if circuit_open():
        return {"skipped": "circuit_open",
                "retry_in_s": int(_circuit["open_until"] - time.time())}
    if db_factory is None:
        from bot_core import get_db as db_factory
    try:
        conn = db_factory()
        cur = conn.cursor()
        cur.execute("SET statement_timeout='20s'")
        ids, tiers = select_priority_ids(cur)
        cur.close()
        if not ids:
            conn.close(); _record_success()
            return {"ids": 0, "tiers": {}}
        from roblox_batch_client import fetch_many_items_sync
        items, failed = fetch_many_items_sync(
            ids, max_batch=30, rate_per_min=60, max_concurrency=3)
        rows = []
        for iid, d in items.items():
            favs = d.get("favorite_count")
            rows.append((iid, (d.get("name") or "")[:500], favs,
                         d.get("price") or 0,
                         (d.get("description") or "")[:5000],
                         (d.get("creator_name") or "")[:200],
                         d.get("asset_type_id") or 0,
                         "known" if favs is not None else "missing"))
        cur = conn.cursor()
        written = _upsert(cur, rows)
        conn.commit()
        cur.close(); conn.close()
        if failed and not items:
            _record_failure()
        else:
            _record_success()
        counts = {t: tiers.count(t) for t in set(tiers)}
        return {"ids": len(ids), "written": written,
                "failed": len(failed), "tiers": counts,
                "circuit_failures": _circuit["failures"]}
    except Exception as e:
        _record_failure()
        print(f"[research] cycle failed: {type(e).__name__}: {e}", flush=True)
        return {"error": f"{type(e).__name__}: {e}",
                "circuit_failures": _circuit["failures"]}
