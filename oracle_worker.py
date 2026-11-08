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

from creator_identity import creator_key, parse_creator_key
from safe_roblox import shared_circuit_open

ADVISORY_LOCK_KEY = 773311
RECOVERY_KEY = "oracle_recovery"
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
                order by creator_type nulls last, creator_id, cohort_type
            """, (ref,))
            return ref, cur.fetchall()
        finally:
            cur.close()

    def load_recovery_state(self):
        """Load the durable continuation state, if any."""
        cur = self.conn.cursor()
        try:
            cur.execute(
                "select pattern_value from creator_patterns where pattern_key = %s",
                (RECOVERY_KEY,))
            row = cur.fetchone()
            if not row or not row[0]:
                return None
            return json.loads(row[0])
        except Exception:
            return None
        finally:
            cur.close()

    def save_recovery_state(self, state):
        cur = self.conn.cursor()
        try:
            cur.execute("""
                insert into creator_patterns
                  (pattern_key, pattern_value, updated_at)
                values (%s, %s, CURRENT_TIMESTAMP)
                on conflict (pattern_key) do update set
                    pattern_value = excluded.pattern_value,
                    updated_at = CURRENT_TIMESTAMP
            """, (RECOVERY_KEY, json.dumps(state, sort_keys=True)))
            return True
        except Exception:
            return False
        finally:
            cur.close()

    def clear_recovery_state(self):
        cur = self.conn.cursor()
        try:
            cur.execute(
                "delete from creator_patterns where pattern_key = %s",
                (RECOVERY_KEY,))
            return True
        except Exception:
            return False
        finally:
            cur.close()

    def mark_scan_running(self, scan_run_id):
        cur = self.conn.cursor()
        try:
            cur.execute("""
                update trend_scan_runs
                set status = 'running', finished_at = NULL
                where scan_run_id = %s
            """, (scan_run_id,))
        finally:
            cur.close()

    def creator_types(self, creator_keys):
        """Resolve typed identities; ``creator_keys`` is [(type, id), ...]."""
        types = {}
        if not creator_keys:
            return types
        types_in = [t for t, _ in creator_keys]
        ids_in = [i for _, i in creator_keys]
        cur = self.conn.cursor()
        try:
            cur.execute("""
                select creator_type, creator_id from tracked_creators
                where creator_type in ('User', 'Group')
                  and (creator_type, creator_id) in (
                      select * from unnest(%s::text[], %s::bigint[])
                  )
            """, (types_in, ids_in))
            for ctype, cid in cur.fetchall():
                types[(ctype, cid)] = ctype
            cur.execute("""
                select creator_type, creator_id from trend_creator_cohorts
                where creator_type in ('User', 'Group')
                  and (creator_type, creator_id) in (
                      select * from unnest(%s::text[], %s::bigint[])
                  )
            """, (types_in, ids_in))
            for ctype, cid in cur.fetchall():
                types.setdefault((ctype, cid), ctype)
        finally:
            cur.close()
        return types

    def insert_for_creator(self, creator_type, creator_id, items, scan_run_id):
        """One transaction per creator; rolls back only this creator."""
        counts = {"inserted": 0, "too_recent": 0, "duplicate": 0}
        conn = self.db_factory()
        try:
            with conn:
                cur = conn.cursor()
                try:
                    for it in items:
                        status = self._insert_one(
                            cur, scan_run_id, it, creator_type)
                        counts[status] = counts.get(status, 0) + 1
                finally:
                    cur.close()
        finally:
            conn.close()
        return counts

    def _insert_one(self, cur, scan_run_id, it, creator_type):
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
              (item_id, creator_id, creator_type, observed_at, scan_run_id,
               favorites, title, description, price, created_at, item_type,
               sales_count, favorites_delta, hours_since_last,
               favorites_velocity, favorite_data_status)
            SELECT %s, %s, %s, now(), %s, %s, %s, %s, %s, %s, %s, NULL,
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
        """, (item_id, item_id, it.get("creator_type"), scan_run_id,
              favorites,
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
                    error_summary = dict(summary.get("error_summary") or {})
                    error_summary["recovery"] = {
                        key: summary.get(key) for key in (
                            "creators_completed", "creators_attempted",
                            "creators_deferred",
                            "creators_incomplete", "creators_unprocessed",
                            "creators_eligible_typed",
                            "creators_skipped_unknown",
                            "successful_observations",
                            "failed_observations",
                            "rate_limited_requests",
                            "recovery_attempts", "resumed_creators",
                            "coverage_pct", "recovery_persisted",
                            "stop_reason", "deferred",
                        )
                    }
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
                        Json(error_summary) if Json else
                        json.dumps(error_summary),
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


def _recovery_payload(ref, scan_run_id, completed, remaining, status, reason,
                      now):
    return {
        "cohort_id": ref,
        "scan_run_id": scan_run_id,
        "completed": sorted(completed),
        "remaining": list(remaining),
        "status": status,
        "reason": reason,
        "updated_at": now.isoformat(),
    }


def _save_recovery(store, payload):
    fn = getattr(store, "save_recovery_state", None)
    if fn is None:
        return False
    try:
        return bool(fn(payload))
    except Exception:
        return False


def _clear_recovery(store):
    fn = getattr(store, "clear_recovery_state", None)
    if fn is None:
        return
    try:
        fn()
    except Exception:
        pass


def run_oracle_scan(store=None, search_fn=None, batch_fn=None,
                    session_fn=None):
    """One resumable ORACLE scan. Returns a summary dict; never exits."""
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
    now = datetime.now(timezone.utc)
    summary = {
        "status": "failed", "scan_run_id": None, "cohort_snapshot_ref": None,
        "creators_eligible": 0, "creators_eligible_typed": 0,
        "creators_scanned": 0, "creators_attempted": 0,
        "creators_completed": 0,
        "creators_errored": 0, "creators_deferred": 0,
        "creators_incomplete": 0, "creators_unprocessed": 0,
        "creators_skipped_unknown": 0,
        "items_discovered": 0, "items_in_window": 0,
        "observations_inserted": 0, "successful_observations": 0,
        "failed_observations": 0, "skipped_too_recent": 0,
        "skipped_rate_limited": 0, "skipped_unavailable": 0,
        "skipped_unknown_type": 0, "truncated_creators": {},
        "rate_limited_requests": 0, "recovery_attempts": 0,
        "resumed_creators": 0, "coverage_pct": 0.0,
        "recovery_persisted": False, "stop_reason": None, "deferred": False,
        "per_cohort": {"elite": 0, "emerging": 0, "control": 0},
    }
    lock_acquired = False
    scan_run_id = None
    ref = None
    completed = set()
    resolved = set()
    remaining_keys = []
    try:
        lock_acquired = bool(store.try_lock())
        if not lock_acquired:
            summary["status"] = "skipped_locked"
            return summary

        ref, cohort_rows = store.latest_cohort()
        summary["cohort_snapshot_ref"] = ref
        creators = []
        seen = set()
        for cid, cohort_type, ctype in cohort_rows:
            ctype = ctype if ctype in ("User", "Group") else None
            key = (creator_key(ctype, cid) if ctype
                   else f"unknown:{cid}")
            if key in seen:
                continue
            seen.add(key)
            creators.append({
                "creator_id": cid,
                "creator_type": ctype,
                "creator_key": key,
                "cohort_type": cohort_type,
            })
            cohort_bucket = (cohort_type or "").lower()
            if cohort_bucket in summary["per_cohort"]:
                summary["per_cohort"][cohort_bucket] += 1

        recovery = None
        loader = getattr(store, "load_recovery_state", None)
        if loader is not None:
            try:
                recovery = loader()
            except Exception:
                recovery = None

        resume = bool(
            recovery
            and recovery.get("cohort_id") == ref
            and recovery.get("scan_run_id") is not None
        )
        if resume:
            scan_run_id = recovery["scan_run_id"]
            marker = getattr(store, "mark_scan_running", None)
            if marker is not None:
                try:
                    marker(scan_run_id)
                except Exception:
                    pass
        else:
            if recovery:
                _clear_recovery(store)
            scan_run_id = store.create_scan_run(ref)
        summary["scan_run_id"] = scan_run_id

        # Preserve the existing typed-resolution path and make its failures
        # fatal/finalized rather than silently dropping every creator.
        types = store.creator_types([
            (c["creator_type"], c["creator_id"]) for c in creators
        ])
        for creator in creators:
            if creator["creator_type"] not in ("User", "Group"):
                resolved_type = types.get(
                    (creator["creator_type"], creator["creator_id"]))
                if resolved_type in ("User", "Group"):
                    creator["creator_type"] = resolved_type
                    creator["creator_key"] = creator_key(
                        resolved_type, creator["creator_id"])

        typed = [c for c in creators
                 if c["creator_type"] in ("User", "Group")]
        unknown = [c for c in creators
                   if c["creator_type"] not in ("User", "Group")]
        creator_map = {c["creator_key"]: c for c in typed}
        typed_keys = set(creator_map)
        summary["creators_eligible"] = len(creators)
        summary["creators_eligible_typed"] = len(typed)
        summary["creators_skipped_unknown"] = len(unknown)
        summary["skipped_unknown_type"] = len(unknown)

        if resume:
            completed = {
                key for key in recovery.get("completed") or []
                if key in creator_map
            }
            stored_remaining = [
                key for key in recovery.get("remaining") or []
                if key in creator_map
            ]
            remaining_keys = stored_remaining or [
                key for key in sorted(typed_keys) if key not in completed
            ]
            summary["recovery_attempts"] = 1
            summary["resumed_creators"] = len(completed)
        else:
            completed = set()
            remaining_keys = sorted(typed_keys)

        summary["creators_completed"] = len(completed)
        summary["creators_unprocessed"] = len(remaining_keys)

        if remaining_keys and shared_circuit_open():
            summary["creators_deferred"] = len(remaining_keys)
            summary["creators_unprocessed"] = len(remaining_keys)
            summary["stop_reason"] = "circuit_open"
            summary["deferred"] = True
            summary["status"] = "partial"
            payload = _recovery_payload(
                ref, scan_run_id, completed, remaining_keys, "deferred",
                "circuit_open", now)
            summary["recovery_persisted"] = _save_recovery(store, payload)
            summary["duration_seconds"] = round(time.time() - started, 2)
            store.update_scan_run(scan_run_id, summary)
            return summary

        pages = max(DEFAULT_DISCOVERY_PAGES, 1)
        max_age = DEFAULT_MAX_ITEM_AGE_DAYS
        session = None
        attempted = 0
        stop_reason = None
        errored_keys = set()
        discovery_incomplete = set()
        discovered = {}

        for index, key in enumerate(remaining_keys):
            creator = creator_map.get(key)
            if creator is None:
                resolved.add(key)
                continue
            if shared_circuit_open():
                stop_reason = "circuit_open"
                break

            cid = creator["creator_id"]
            ctype = creator["creator_type"]
            attempted += 1
            summary["creators_attempted"] = attempted
            if session is None:
                session = session_fn()

            try:
                discovery = search_fn(
                    session, cid, creator_type=ctype, max_pages=pages
                ) or {}
            except Exception as exc:
                from creator_tracker import RateLimited
                if isinstance(exc, RateLimited):
                    summary["rate_limited_requests"] += 1
                    summary["skipped_rate_limited"] += 1
                    summary["truncated_creators"][key] = (
                        "discovery_rate_limited")
                    summary.setdefault("error_summary", {})[
                        f"discovery:{key}"] = "rate_limited"
                    discovery_incomplete.add(key)
                    stop_reason = "rate_limited"
                    break
                errored_keys.add(key)
                discovery_incomplete.add(key)
                summary.setdefault("error_summary", {})[
                    f"discovery:{key}"] = (
                        f"{type(exc).__name__}: {exc}")
                stop_reason = "unavailable"
                continue

            if isinstance(discovery, dict):
                items = discovery.get("items") or []
                status = discovery.get("status")
                if not status:
                    status = ("page_cap_reached"
                              if discovery.get("truncated") else "complete")
                pages_fetched = int(discovery.get("pages") or 0)
                was_truncated = bool(discovery.get("truncated"))
            else:
                # Backward-compatible injected list API.
                items = discovery or []
                pages_fetched = min(
                    pages, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
                was_truncated = len(items) >= pages * PAGE_SIZE
                status = "page_cap_reached" if was_truncated else "complete"

            for it in items:
                created = it.get("created_at")
                age = _age_days(created, now)
                if age is not None and age > max_age:
                    continue
                if it.get("id") is None:
                    continue
                discovered[int(it["id"])] = {
                    "creator_id": cid,
                    "creator_type": ctype,
                    "creator_key": key,
                    "cohort_type": creator["cohort_type"],
                    "created_at": created,
                }

            if status == "complete":
                completed.add(key)
            else:
                discovery_incomplete.add(key)
                if status in ("rate_limited", "deferred"):
                    if status == "rate_limited":
                        summary["rate_limited_requests"] += 1
                        summary["skipped_rate_limited"] += 1
                    stop_reason = status
                    break
                if status == "page_cap_reached" or was_truncated:
                    summary["truncated_creators"][key] = {
                        "reason": "page_cap_reached",
                        "pages_fetched": pages_fetched,
                        "items_returned": len(items),
                    }
                    resolved.add(key)
                elif status == "invalid_response":
                    resolved.add(key)
                    summary.setdefault("error_summary", {})[
                        f"discovery:{key}"] = "invalid_response"
                elif status in ("timeout", "unavailable"):
                    stop_reason = status
                else:
                    resolved.add(key)

            if stop_reason in ("rate_limited", "circuit_open"):
                break

        summary["items_discovered"] = len(discovered)
        summary["items_in_window"] = len(discovered)

        batch_failure_keys = set()
        if discovered:
            batch_items, failed = batch_fn(list(discovered.keys()))
            failed = failed or {}
            summary["failed_observations"] = len(failed)
            for iid, reason in failed.items():
                meta = discovered.get(int(iid))
                if not meta:
                    continue
                text = str(reason).lower()
                batch_failure_keys.add(meta["creator_key"])
                if "429" in text or "rate" in text or "circuit" in text:
                    summary["rate_limited_requests"] += 1
                    summary["skipped_rate_limited"] += 1
                    if stop_reason is None:
                        stop_reason = "rate_limited"
                else:
                    summary["skipped_unavailable"] += 1

            rows_by_key = {}
            for iid, batch_item in (batch_items or {}).items():
                meta = discovered.get(int(iid))
                if not meta:
                    continue
                enriched = dict(batch_item)
                enriched.update({
                    "creator_id": meta["creator_id"],
                    "creator_type": meta["creator_type"],
                    "created_at": meta["created_at"],
                })
                enriched["item_type"] = _item_type(
                    batch_item.get("asset_type_id"))
                rows_by_key.setdefault(meta["creator_key"], []).append(
                    enriched)

            for key, rows in rows_by_key.items():
                creator = creator_map.get(key)
                if creator is None:
                    continue
                try:
                    counts = store.insert_for_creator(
                        creator["creator_type"], creator["creator_id"],
                        rows, scan_run_id)
                    summary["observations_inserted"] += counts.get(
                        "inserted", 0)
                    summary["skipped_too_recent"] += counts.get(
                        "too_recent", 0)
                except Exception as insert_error:
                    errored_keys.add(key)
                    batch_failure_keys.add(key)
                    summary.setdefault("error_summary", {})[
                        f"insert:{key}"] = (
                        f"{type(insert_error).__name__}: {insert_error}")
                    if stop_reason is None:
                        stop_reason = "unavailable"

            for key in batch_failure_keys:
                completed.discard(key)
                resolved.discard(key)

        remaining = [
            k for k in remaining_keys
            if k not in completed and k not in resolved
        ]
        remaining_set = set(remaining)
        incomplete_keys = (
            (discovery_incomplete | batch_failure_keys | errored_keys)
            - remaining_set - completed
        )
        summary["creators_completed"] = len(completed)
        summary["creators_scanned"] = len(completed)
        summary["creators_errored"] = len(errored_keys)
        summary["creators_incomplete"] = len(incomplete_keys)
        summary["creators_unprocessed"] = len(remaining)
        summary["creators_deferred"] = (
            len(remaining)
            if stop_reason in ("rate_limited", "deferred", "circuit_open",
                               "timeout", "unavailable")
            else 0
        )
        summary["successful_observations"] = summary["observations_inserted"]
        summary["coverage_pct"] = round(
            100.0 * len(completed & typed_keys) / max(len(typed_keys), 1), 1)
        summary["stop_reason"] = stop_reason
        summary["deferred"] = bool(
            remaining and stop_reason in (
                "rate_limited", "deferred", "circuit_open", "timeout",
                "unavailable"))

        if (remaining or summary["creators_incomplete"]
              or summary["creators_errored"]
              or summary["creators_skipped_unknown"]
              or summary["truncated_creators"]
              or summary["failed_observations"]):
            summary["status"] = "partial"
        else:
            summary["status"] = "success"

        if remaining:
            payload = _recovery_payload(
                ref, scan_run_id, completed, remaining, summary["status"],
                stop_reason, now)
            summary["recovery_persisted"] = _save_recovery(store, payload)
        else:
            _clear_recovery(store)

        summary["duration_seconds"] = round(time.time() - started, 2)
        store.update_scan_run(scan_run_id, summary)
        print(f"[oracle] scan {scan_run_id}: {summary}", flush=True)
        return summary
    except Exception as exc:
        summary["status"] = "failed"
        summary["duration_seconds"] = round(time.time() - started, 2)
        summary.setdefault("error_summary", {})["fatal"] = (
            f"{type(exc).__name__}: {exc}")
        remaining = [
            key for key in remaining_keys
            if key not in completed and key not in resolved
        ]
        if ref is not None and scan_run_id is not None and remaining:
            try:
                summary["recovery_persisted"] = _save_recovery(
                    store, _recovery_payload(
                        ref, scan_run_id, completed, remaining, "failed",
                        "fatal", now))
            except Exception:
                pass
        if scan_run_id is not None:
            try:
                store.update_scan_run(scan_run_id, summary)
            except Exception as finalize_error:
                summary["error_summary"]["finalize"] = (
                    f"{type(finalize_error).__name__}: {finalize_error}")
        print(f"[oracle] fatal: {type(exc).__name__}: {exc}", flush=True)
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
