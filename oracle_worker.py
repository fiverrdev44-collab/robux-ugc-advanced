"""oracle_worker.py — Project ORACLE Phase 2 scan worker.

Discovery (true itemCreatedUtc) → one shared batch fetch → per-creator
transactions with SQL-computed deltas and favorites/day velocity.
Never calls sys.exit; safe to run inside the scheduler process.
"""
import json
import os
import time
from datetime import datetime, timezone

try:
    from psycopg2.extras import Json
except Exception:  # pragma: no cover
    Json = None

ADVISORY_LOCK_KEY = 773311
DEFAULT_DISCOVERY_PAGES = int(os.getenv("ORACLE_DISCOVERY_PAGES", "4"))
DEFAULT_MAX_ITEM_AGE_DAYS = int(os.getenv("ORACLE_MAX_ITEM_AGE_DAYS", "30"))
PAGE_SIZE = 30


class OracleDisabled(Exception):
    pass


class PostgresStore:
    def __init__(self, db_factory=None):
        if db_factory is None:
            from bot_core import get_db as db_factory
        self.db_factory = db_factory
        self.conn = self.db_factory()
        self.conn.autocommit = True

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def try_lock(self):
        cur = self.conn.cursor()
        try:
            cur.execute("select pg_try_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
            return bool(cur.fetchone()[0])
        finally:
            cur.close()

    def release_lock(self):
        cur = self.conn.cursor()
        try:
            cur.execute("select pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
        except Exception:
            pass
        finally:
            cur.close()

    def create_scan_run(self, cohort_ref=None):
        cur = self.conn.cursor()
        try:
            cur.execute("""
                insert into trend_scan_runs (status, cohort_snapshot_ref)
                values ('running', %s) returning scan_run_id
            """, (cohort_ref,))
            return cur.fetchone()[0]
        finally:
            cur.close()

    def latest_cohort(self):
        cur = self.conn.cursor()
        try:
            cur.execute("select max(cohort_id) from trend_creator_cohorts")
            row = cur.fetchone()
            ref = row[0] if row else None
            if not ref:
                return None, []
            cur.execute("""
                select creator_id, cohort_type, creator_type
                from trend_creator_cohorts where cohort_id = %s
            """, (ref,))
            return ref, cur.fetchall()
        finally:
            cur.close()

    def creator_types(self, creator_ids):
        types = {}
        cur = self.conn.cursor()
        try:
            cur.execute("""
                select creator_id, creator_type from tracked_creators
                where creator_id = any(%s) and creator_type is not null
            """, (list(creator_ids),))
            for cid, ctype in cur.fetchall():
                types[cid] = ctype
            cur.execute("""
                select creator_id, creator_type from trend_creator_cohorts
                where creator_id = any(%s) and creator_type is not null
            """, (list(creator_ids),))
            for cid, ctype in cur.fetchall():
                types.setdefault(cid, ctype)
        finally:
            cur.close()
        return types

    def insert_for_creator(self, creator_id, items, scan_run_id):
        """One transaction per creator; rolls back only this creator."""
        counts = {"inserted": 0, "too_recent": 0, "duplicate": 0}
        conn = self.db_factory()
        try:
            with conn:
                cur = conn.cursor()
                try:
                    for it in items:
                        status = self._insert_one(cur, scan_run_id, it)
                        counts[status] = counts.get(status, 0) + 1
                finally:
                    cur.close()
        finally:
            conn.close()
        return counts

    def _insert_one(self, cur, scan_run_id, it):
        item_id = it.get("id")
        cur.execute("""
            select extract(epoch from (now() - observed_at)) / 3600.0
            from trend_item_observations
            where item_id = %s order by observed_at desc limit 1
        """, (item_id,))
        row = cur.fetchone()
        if row and row[0] is not None and float(row[0]) < 1.0:
            return "too_recent"

        favorites = it.get("favorite_count")
        price = None if it.get("price_missing") else it.get("price")
        status = "known" if favorites is not None else "missing"
        cur.execute("""
            WITH base AS (
                SELECT (array_agg(favorites ORDER BY observed_at DESC))[1]
                           AS favorites,
                       extract(epoch FROM (now() -
                           (array_agg(observed_at ORDER BY observed_at DESC))[1]
                       )) / 3600.0 AS hours
                FROM trend_item_observations
                WHERE item_id = %s AND favorites IS NOT NULL
            )
            INSERT INTO trend_item_observations
              (item_id, creator_id, observed_at, scan_run_id, favorites,
               title, description, price, created_at, item_type,
               sales_count, favorites_delta, hours_since_last,
               favorites_velocity, favorite_data_status)
            SELECT %s, %s, now(), %s, %s, %s, %s, %s, %s, %s, NULL,
                   CASE WHEN base.favorites IS NULL OR %s IS NULL THEN NULL
                        ELSE %s::int - base.favorites END,
                   base.hours,
                   CASE WHEN base.hours IS NULL OR base.hours < 0.5
                             OR base.favorites IS NULL OR %s IS NULL
                        THEN NULL
                        ELSE (%s::int - base.favorites) / (base.hours / 24.0)
                   END,
                   %s
            FROM base
            ON CONFLICT (scan_run_id, item_id) DO NOTHING
        """, (item_id, item_id, it.get("creator_id"), scan_run_id, favorites,
              (it.get("name") or "")[:500],
              (it.get("description") or "")[:5000], price,
              it.get("created_at"), it.get("item_type"),
              favorites, favorites, favorites, favorites, status))
        return "inserted" if cur.rowcount else "duplicate"

    def update_scan_run(self, scan_run_id, summary):
        conn = self.db_factory()
        try:
            with conn:
                cur = conn.cursor()
                try:
                    cur.execute("""
                        update trend_scan_runs set
                          finished_at = now(), status = %s,
                          cohort_snapshot_ref = %s,
                          creators_eligible = %s, creators_scanned = %s,
                          creators_errored = %s, items_discovered = %s,
                          items_in_window = %s, observations_inserted = %s,
                          skipped_too_recent = %s, skipped_rate_limited = %s,
                          skipped_unavailable = %s, skipped_unknown_type = %s,
                          truncated_creators = %s, error_summary = %s
                        where scan_run_id = %s
                    """, (
                        summary["status"], summary.get("cohort_snapshot_ref"),
                        summary["creators_eligible"], summary["creators_scanned"],
                        summary["creators_errored"], summary["items_discovered"],
                        summary["items_in_window"], summary["observations_inserted"],
                        summary["skipped_too_recent"],
                        summary["skipped_rate_limited"],
                        summary["skipped_unavailable"],
                        summary["skipped_unknown_type"],
                        Json(summary["truncated_creators"]) if Json else
                        json.dumps(summary["truncated_creators"]),
                        Json(summary.get("error_summary") or {}) if Json else
                        json.dumps(summary.get("error_summary") or {}),
                        scan_run_id))
                finally:
                    cur.close()
        finally:
            conn.close()


def _item_type(asset_type_id):
    try:
        from category_configs import detect_family_from_asset_type
        return detect_family_from_asset_type(asset_type_id)
    except Exception:
        return None


def _age_days(created_at, now):
    if created_at is None:
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (now - created_at).total_seconds() / 86400.0


def run_oracle_scan(store=None, search_fn=None, batch_fn=None,
                    session_fn=None):
    """One ORACLE scan. Returns a summary dict; never exits the process."""
    if os.getenv("ORACLE_ENABLED") != "1":
        return {"status": "disabled", "scanned": 0}

    if store is None:
        store = PostgresStore()
    if search_fn is None:
        from creator_tracker import search_creator_complete as search_fn
    if batch_fn is None:
        from roblox_batch_client import fetch_many_items_sync as batch_fn
    if session_fn is None:
        from creator_tracker import _session as session_fn

    started = time.time()
    summary = {
        "status": "failed", "scan_run_id": None, "cohort_snapshot_ref": None,
        "creators_eligible": 0, "creators_scanned": 0, "creators_errored": 0,
        "items_discovered": 0, "items_in_window": 0,
        "observations_inserted": 0, "skipped_too_recent": 0,
        "skipped_rate_limited": 0, "skipped_unavailable": 0,
        "skipped_unknown_type": 0, "truncated_creators": {},
        "per_cohort": {"elite": 0, "emerging": 0, "control": 0},
    }
    lock_acquired = False
    scan_run_id = None
    try:
        lock_acquired = bool(store.try_lock())
        if not lock_acquired:
            summary["status"] = "skipped_locked"
            return summary
        ref, cohort_rows = store.latest_cohort()
        summary["cohort_snapshot_ref"] = ref
        creators, seen = [], set()
        for cid, ctype, ccreator in cohort_rows:
            if cid in seen:
                continue
            seen.add(cid)
            creators.append({"creator_id": cid, "cohort_type": ctype})
            key = (ctype or "").lower()
            if key in summary["per_cohort"]:
                summary["per_cohort"][key] += 1
        summary["creators_eligible"] = len(creators)
        scan_run_id = store.create_scan_run(ref)
        summary["scan_run_id"] = scan_run_id

        types = store.creator_types([c["creator_id"] for c in creators])
        pages = max(DEFAULT_DISCOVERY_PAGES, 1)
        max_age = DEFAULT_MAX_ITEM_AGE_DAYS
        now = datetime.now(timezone.utc)
        mapping = {}
        discovery_rate_limited = False
        session = None

        for c in creators:
            cid = c["creator_id"]
            ctype = types.get(cid)
            if not ctype:
                summary["skipped_unknown_type"] += 1
                continue
            try:
                if session is None:
                    session = session_fn()
                discovery = search_fn(
                    session, cid, creator_type=ctype, max_pages=pages
                ) or {}
                if isinstance(discovery, dict):
                    results = discovery.get("items") or []
                    was_truncated = bool(discovery.get("truncated"))
                    pages_fetched = int(discovery.get("pages") or 0)
                else:
                    # Backward-compatible fallback for injected/legacy list APIs.
                    results = discovery or []
                    pages_fetched = min(
                        pages, (len(results) + PAGE_SIZE - 1) // PAGE_SIZE
                    )
                    was_truncated = len(results) >= pages * PAGE_SIZE
            except Exception as e:
                from creator_tracker import RateLimited
                if isinstance(e, RateLimited):
                    discovery_rate_limited = True
                    summary["truncated_creators"][str(cid)] = (
                        "discovery_rate_limited")
                    break
                summary["creators_errored"] += 1
                summary.setdefault("error_summary", {})
                summary["error_summary"][f"discovery:{cid}"] = (
                    f"{type(e).__name__}: {e}")
                continue
            summary["creators_scanned"] += 1
            if was_truncated:
                summary["truncated_creators"][str(cid)] = {
                    "reason": "page_cap_reached",
                    "pages_fetched": pages_fetched,
                    "items_returned": len(results),
                }
            for it in results:
                created = it.get("created_at")
                age = _age_days(created, now)
                if age is not None and age > max_age:
                    continue
                if it.get("id") is None:
                    continue
                mapping[int(it["id"])] = {
                    "creator_id": cid, "cohort_type": c["cohort_type"],
                    "created_at": created,
                }
        summary["items_discovered"] = len(mapping)
        summary["items_in_window"] = len(mapping)

        items, failed = ({}, {})
        if mapping:
            items, failed = batch_fn(list(mapping.keys()))

        by_creator = {}
        for iid, batch_item in (items or {}).items():
            meta = mapping.get(int(iid))
            if not meta:
                continue
            enriched = dict(batch_item)
            enriched["creator_id"] = meta["creator_id"]
            enriched["created_at"] = meta["created_at"]
            enriched["item_type"] = _item_type(
                batch_item.get("asset_type_id"))
            by_creator.setdefault(meta["creator_id"], []).append(enriched)

        for cid, rows in by_creator.items():
            try:
                counts = store.insert_for_creator(cid, rows, scan_run_id)
                summary["observations_inserted"] += counts.get("inserted", 0)
                summary["skipped_too_recent"] += counts.get("too_recent", 0)
            except Exception as e:
                summary["creators_errored"] += 1
                summary.setdefault("error_summary", {})
                summary["error_summary"][f"insert:{cid}"] = (
                    f"{type(e).__name__}: {e}")

        for fid, reason in (failed or {}).items():
            text = str(reason).lower()
            if "429" in text or "rate" in text:
                summary["skipped_rate_limited"] += 1
            else:
                summary["skipped_unavailable"] += 1

        if (discovery_rate_limited
                or summary["creators_errored"]
                or summary["skipped_unknown_type"]
                or summary["truncated_creators"]
                or failed):
            summary["status"] = "partial"
        else:
            summary["status"] = "success"

        summary["duration_seconds"] = round(time.time() - started, 2)
        store.update_scan_run(scan_run_id, summary)
        print(f"[oracle] scan {scan_run_id}: {summary}", flush=True)
        return summary
    except Exception as e:
        summary["status"] = "failed"
        summary["duration_seconds"] = round(time.time() - started, 2)
        summary.setdefault("error_summary", {})["fatal"] = (
            f"{type(e).__name__}: {e}")
        # A scan-run row is created before discovery. Best-effort finalization
        # prevents fatal errors from leaving status='running' indefinitely.
        if scan_run_id is not None:
            try:
                store.update_scan_run(scan_run_id, summary)
            except Exception as finalize_error:
                summary["error_summary"]["finalize"] = (
                    f"{type(finalize_error).__name__}: {finalize_error}")
        print(f"[oracle] fatal: {type(e).__name__}: {e}", flush=True)
        return summary
    finally:
        if lock_acquired:
            try:
                store.release_lock()
            except Exception:
                pass
        try:
            store.close()
        except Exception:
            pass


if __name__ == "__main__":
    # Manual smoke-run entry point. It respects ORACLE_ENABLED and prints a
    # machine-readable summary; migrations are deliberately never applied here.
    result = run_oracle_scan()
    print(json.dumps(result, default=str, sort_keys=True), flush=True)
