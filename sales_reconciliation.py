"""
sales_reconciliation.py — read-only reconciliation between my_sales and a
Discord channel export.

Never writes, deletes, or deduplicates. Produces a dry-run report of:

  * matched transactions (by provider transaction id, source event id, then
    a timestamp-tolerated fingerprint);
  * records missing from the database (present in the export only);
  * records in the database not present in the export;
  * possible duplicates (shared transaction id / event id / legacy message);
  * timestamp discrepancies (marketplace vs notification time, UTC date drift);
  * unresolved identities (via item_resolver, DB mode only);
  * total-count and total-amount deltas explaining why historical DB totals
    differ from the export.

Modes
-----
  --export CSV/JSON      compare the DB against an export file
  --db-json FILE         use an offline JSON dump of my_sales instead of a
                         live database (dry-run without DB access)
  --self-check           DB-only integrity check (no export required)

The core reconcile() is pure and testable: pass lists of row dicts.
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone

try:
    from bot_core import get_db
except Exception:  # pragma: no cover - offline dry run
    get_db = None

TOLERANCE_DEFAULT = 300  # seconds


# ════════════════════════════════════════════════════════════════════
# Normalisation
# ════════════════════════════════════════════════════════════════════

def _as_dt(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _canonical_name(name):
    return str(name or "").strip().lower()


def _norm_row(row):
    """Normalise one export or DB row into a comparable dict."""
    return {
        "event_id": row.get("source_event_id") or row.get("event_id"),
        "transaction_id": row.get("transaction_id"),
        "notification_time": _as_dt(row.get("notification_time")),
        "sale_time": _as_dt(row.get("sale_time")
                            or row.get("transaction_time")),
        "item_name": row.get("item_name"),
        "buyer": row.get("buyer"),
        "amount_robux": _as_int(row.get("amount_robux")),
        "group_name": row.get("group_name"),
        "asset_id": row.get("asset_id"),
    }


# ════════════════════════════════════════════════════════════════════
# Matching
# ════════════════════════════════════════════════════════════════════

def _fingerprint_key(r):
    if r["item_name"] is None and r["amount_robux"] is None:
        return None
    return (_canonical_name(r["item_name"]), r["amount_robux"])


def _within(a, b, tol_seconds):
    if a is None or b is None:
        return False
    return abs((a - b).total_seconds()) <= tol_seconds


def _pop_index(lst, idx):
    return lst.pop(idx)


def _buyer_consistent(dr, er):
    a = (dr.get("buyer") or "").strip().lower()
    b = (er.get("buyer") or "").strip().lower()
    return (not a or not b) or a == b


def _group_consistent(dr, er):
    a = (dr.get("group_name") or "").strip().lower()
    b = (er.get("group_name") or "").strip().lower()
    return (not a or not b) or a == b


def _fp_consistent(dr, er):
    return _buyer_consistent(dr, er) and _group_consistent(dr, er)


def _match_one_round(db_rows, export_rows, keyfn, time_key, tol, verify=None):
    """Match export rows to DB rows on keyfn.

    tol=None disables the time constraint (used for transaction-id and
    event-id matching, which must hold regardless of timestamp). ``verify``
    is an optional extra predicate for fingerprint rounds.
    """
    matched = []
    db_by_key = {}
    for r in db_rows:
        k = keyfn(r)
        if k is None:
            continue
        db_by_key.setdefault(k, []).append(r)
    for er in export_rows:
        k = keyfn(er)
        bucket = db_by_key.get(k)
        if not bucket:
            continue
        hit = None
        hit_i = None
        for i, dr in enumerate(bucket):
            if tol is not None and not _within(dr[time_key], er[time_key], tol):
                continue
            if verify is not None and not verify(dr, er):
                continue
            hit, hit_i = dr, i
            break
        if hit is not None:
            matched.append((er, _pop_index(bucket, hit_i)))
    return matched


def _dedupe_matched(matched):
    """Ensure each DB row is matched at most once across rounds."""
    return matched


def reconcile(db_rows, export_rows, tolerance=TOLERANCE_DEFAULT):
    """Pure reconciliation. Returns a structured report dict."""
    db = [_norm_row(r) for r in db_rows]
    ex = [_norm_row(r) for r in export_rows]

    matched = []
    used_db = set()

    # Round 1: transaction id (authoritative; ignores timestamps entirely).
    txn_pairs = _match_one_round(
        db,
        [er for er in ex if er["transaction_id"]],
        lambda r: r["transaction_id"], "sale_time", None)
    # Round 2: source event id (exact, ignores timestamps).
    ev_pairs = _match_one_round(
        [dr for dr in db if id(dr) not in used_db],
        [er for er in ex if not er.get("_matched") and er["event_id"]],
        lambda r: r["event_id"], "sale_time", None)
    # Round 3: timestamp-tolerated fingerprint, buyer/group-consistent.
    fp_pairs = _match_one_round(
        [dr for dr in db if id(dr) not in used_db],
        [er for er in ex if not er.get("_matched")],
        _fingerprint_key, "sale_time", tolerance, verify=_fp_consistent)

    for pairs, method in ((txn_pairs, "transaction_id"),
                          (ev_pairs, "source_event_id"),
                          (fp_pairs, "fingerprint")):
        for er, dr in pairs:
            if id(dr) in used_db or er.get("_matched"):
                continue
            used_db.add(id(dr))
            er["_matched"] = True
            dr["_matched"] = True
            matched.append({"export": er, "db": dr, "method": method})

    missing_in_db = [er for er in ex if not er.get("_matched")]
    extra_in_db = [dr for dr in db if id(dr) not in used_db]

    # Duplicate detection.
    def _dup_groups(rows, keyfn, label):
        groups = {}
        for r in rows:
            k = keyfn(r)
            if k is None:
                continue
            groups.setdefault(k, []).append(r)
        return {k: v for k, v in groups.items() if len(v) > 1}

    dup_txn = _dup_groups(db, lambda r: r["transaction_id"], "transaction_id")
    dup_event = _dup_groups(db, lambda r: r["event_id"], "event_id")

    legacy_multi = {}
    for r in db:
        eid = r["event_id"] or ""
        if eid.startswith("discord:") and ":" in eid:
            parts = eid.split(":")
            if len(parts) >= 4 and parts[1].isdigit():
                legacy_multi.setdefault(parts[1], []).append(r)
    legacy_multi = {k: v for k, v in legacy_multi.items() if len(v) > 1}

    # Timestamp discrepancies among matched pairs.
    discrepancies = []
    for m in matched:
        er, dr = m["export"], m["db"]
        if er["sale_time"] and dr["sale_time"]:
            delta = abs((er["sale_time"] - dr["sale_time"]).total_seconds())
            if delta > tolerance:
                discrepancies.append({
                    "event_id": dr["event_id"],
                    "transaction_id": dr["transaction_id"],
                    "delta_seconds": round(delta, 1),
                    "export_time": er["sale_time"].isoformat(),
                    "db_time": dr["sale_time"].isoformat(),
                })
        if dr["sale_time"] and dr["notification_time"]:
            sd = dr["sale_time"].date()
            nd = dr["notification_time"].date()
            if sd != nd:
                discrepancies.append({
                    "event_id": dr["event_id"],
                    "transaction_id": dr["transaction_id"],
                    "kind": "utc_date_boundary",
                    "export_time": nd.isoformat(),
                    "db_time": sd.isoformat(),
                })

    db_total = len(db)
    db_amount = sum(r["amount_robux"] or 0 for r in db)
    ex_total = len(ex)
    ex_amount = sum(r["amount_robux"] or 0 for r in ex)

    return {
        "matched": len(matched),
        "missing_in_db": missing_in_db,
        "extra_in_db": extra_in_db,
        "duplicate_transaction_ids": dup_txn,
        "duplicate_event_ids": dup_event,
        "legacy_multi_embed": legacy_multi,
        "timestamp_discrepancies": discrepancies,
        "totals": {
            "db_rows": db_total,
            "db_amount": db_amount,
            "export_rows": ex_total,
            "export_amount": ex_amount,
            "row_delta": db_total - ex_total,
            "amount_delta": db_amount - ex_amount,
        },
    }


# ════════════════════════════════════════════════════════════════════
# Loaders
# ════════════════════════════════════════════════════════════════════

_EXPORT_HEADER_ALIASES = {
    "message_id": "message_id",
    "messageid": "message_id",
    "embed_index": "embed_index",
    "embedindex": "embed_index",
    "transaction_id": "transaction_id",
    "transactionid": "transaction_id",
    "txn_id": "transaction_id",
    "order_id": "transaction_id",
    "sale_id": "transaction_id",
    "transaction_time": "transaction_time",
    "transaction_timestamp": "transaction_time",
    "sold_at": "transaction_time",
    "date": "transaction_time",
    "notification_time": "notification_time",
    "message_time": "notification_time",
    "item_name": "item_name",
    "item": "item_name",
    "name": "item_name",
    "buyer": "buyer",
    "buyer_name": "buyer",
    "amount_robux": "amount_robux",
    "amount": "amount_robux",
    "robux": "amount_robux",
    "gross_robux": "amount_robux",
    "group_name": "group_name",
    "group": "group_name",
    "asset_id": "asset_id",
    "item_id": "asset_id",
}


def load_export(path):
    """Load a CSV or JSON export file into a list of row dicts."""
    if path.endswith(".json"):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("sales", data.get("rows", []))
        return data
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row = {}
            for k, v in raw.items():
                canon = _EXPORT_HEADER_ALIASES.get(k.strip().lower(), k.strip())
                row[canon] = v
            rows.append(row)
    return rows


def load_db_offline(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("sales", data.get("rows", []))
    return data


def _read_db_rows(cur):
    """Read my_sales rows (read-only) with whatever columns exist."""
    from sales_listener import _sales_columns
    cols = _sales_columns(cur)
    select = ["id", "sale_time", "sale_date", "item_name", "buyer",
              "amount_robux"]
    for col in ("source_event_id", "transaction_id", "notification_time",
                "group_name", "asset_id", "source_event_version",
                "embed_index"):
        if col in cols:
            select.append(col)
    cur.execute("select " + ", ".join(select) + " from my_sales order by id")
    rows = cur.fetchall() or []
    out = []
    for r in rows:
        row = dict(zip(select, r))
        if "sale_time" in row and row["sale_time"] is None:
            row["sale_time"] = row.get("sale_date")
        out.append(row)
    return out


# ════════════════════════════════════════════════════════════════════
# Report formatting
# ════════════════════════════════════════════════════════════════════

def _brief(rows, limit=8):
    lines = []
    for r in rows[:limit]:
        lines.append(
            f"  • {r.get('item_name') or '?'} · "
            f"R${r.get('amount_robux') or 0} · "
            f"txn={r.get('transaction_id') or '-'} · "
            f"evt={r.get('event_id') or '-'} · "
            f"time={r.get('sale_time') or r.get('notification_time') or '-'}"
        )
    if len(rows) > limit:
        lines.append(f"  … and {len(rows) - limit} more")
    return "\n".join(lines)


def format_report(result, identity_statuses=None, export_path=None):
    t = result["totals"]
    lines = [
        "# SALES RECONCILIATION (dry-run, read-only)",
        "",
        "## Totals",
        f"• Database:   **{t['db_rows']:,}** rows · R${t['db_amount']:,}",
        f"• Export:     **{t['export_rows']:,}** rows · R${t['export_amount']:,}",
        f"• Row delta:  **{t['row_delta']:+,}** · "
        f"Amount delta: **R${t['amount_delta']:+,}**",
        f"• Matched:    **{result['matched']:,}** · "
        f"Missing in DB: **{len(result['missing_in_db']):,}** · "
        f"Extra in DB: **{len(result['extra_in_db']):,}**",
        "",
    ]

    if result["duplicate_transaction_ids"]:
        lines.append("## Possible duplicates (shared transaction id)")
        for k, rows in result["duplicate_transaction_ids"].items():
            lines.append(f"  • txn `{k}` × {len(rows)}")
        lines.append("")
    if result["duplicate_event_ids"]:
        lines.append("## Possible duplicates (shared source event id)")
        for k, rows in result["duplicate_event_ids"].items():
            lines.append(f"  • evt `{k}` × {len(rows)}")
        lines.append("")
    if result["legacy_multi_embed"]:
        lines.append("## Legacy messages with multiple rows (embed collision)")
        for mid, rows in result["legacy_multi_embed"].items():
            lines.append(f"  • message `{mid}` × {len(rows)} rows")
        lines.append("")

    if result["timestamp_discrepancies"]:
        lines.append("## Timestamp discrepancies")
        for d in result["timestamp_discrepancies"][:10]:
            if d.get("kind") == "utc_date_boundary":
                lines.append(f"  • UTC date drift: sale {d.get('db_time')} vs "
                             f"notification {d.get('export_time')} "
                             f"({d.get('event_id') or '-'})")
            else:
                lines.append(f"  • Δ{d['delta_seconds']}s export "
                             f"{d['export_time']} vs db {d['db_time']} "
                             f"({d.get('transaction_id') or d.get('event_id') or '-'})")
        lines.append("")

    if result["missing_in_db"]:
        lines.append("## Missing from database (in export only)")
        lines.append(_brief(result["missing_in_db"]))
        lines.append("")
    if result["extra_in_db"]:
        lines.append("## In database but not in export")
        lines.append(_brief(result["extra_in_db"]))
        lines.append("")

    if identity_statuses:
        lines.append("## Unresolved identities")
        for s, c in sorted(identity_statuses.items()):
            lines.append(f"  • {s}: {c} names")
        lines.append("")

    lines.append("_Nothing was written, deleted, or deduplicated._")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--export", help="CSV/JSON channel export")
    ap.add_argument("--db-json", help="offline JSON dump of my_sales")
    ap.add_argument("--self-check", action="store_true",
                    help="DB-only integrity check")
    ap.add_argument("--tolerance", type=int, default=TOLERANCE_DEFAULT,
                    help="timestamp tolerance seconds (default 300)")
    args = ap.parse_args(argv)

    export_rows = []
    if args.export:
        export_rows = load_export(args.export)

    db_rows = []
    identity_statuses = None
    if args.db_json:
        db_rows = load_db_offline(args.db_json)
    elif get_db is not None:
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("BEGIN TRANSACTION READ ONLY")
            db_rows = _read_db_rows(cur)
            # Resolve every distinct name BEFORE the read-only transaction is
            # closed, so the cursor stays valid for the resolver.
            try:
                from collections import Counter
                from item_resolver import resolve_name
                names = {r.get("item_name") for r in db_rows
                         if r.get("item_name")}
                if export_rows:
                    names |= {r.get("item_name") for r in export_rows
                              if r.get("item_name")}
                statuses = Counter()
                for n in names:
                    statuses[resolve_name(cur, n).get("status", "unknown")] += 1
                identity_statuses = statuses
            except Exception:
                identity_statuses = None
            if args.self_check and not export_rows:
                export_rows = db_rows  # compare DB against itself
        finally:
            conn.rollback()
            cur.close()
            conn.close()
    else:
        print("No --db-json and no live DATABASE_URL; nothing to reconcile.",
              file=sys.stderr)
        return 2

    result = reconcile(db_rows, export_rows, args.tolerance)
    print(format_report(result, identity_statuses=identity_statuses,
                        export_path=args.export))
    return 0


if __name__ == "__main__":
    sys.exit(main())
