"""
sales_listener.py — reads Roblox sale webhook embeds from Discord,
saves to my_sales, and provides summary functions.

Ingestion identity model
------------------------
Each *individual* sale embed gets a deterministic ``source_event_id``:

  * ``txn:<provider>:<transaction_id>``  when a provider transaction ID is
    present in the embed (preferred — stable across reposts);
  * ``discord:<message_id>:<embed_index>`` otherwise (embed index makes two
    same-price sales inside one Discord message distinct).

Legacy rows imported before this change carry the old format
``discord:<message_id>:<item_name>:<amount_robux>``. They are never blindly
re-imported: a message whose legacy ID already exists is treated as already
captured (see ``duplicate_reason``) and flagged in the reconciliation report
instead of silently re-adding rows.

Timestamps
----------
``sale_time`` is the *marketplace* transaction timestamp when the webhook
provides one (a dated field, ``embed.timestamp``, or the message time as a
last resort). ``notification_time`` always records the Discord notification
timestamp, so the two are never conflated. ``sale_date`` is the UTC calendar
date of ``sale_time``.

All DB writes batch or run via asyncio.to_thread — no event loop blocking.
"""
import os
import re
import asyncio
from datetime import datetime, timezone

from bot_core import get_db


# ════════════════════════════════════════════════════════════════════
# Event identity
# ════════════════════════════════════════════════════════════════════

# Legacy format: discord:<message_id>:<item_name>:<amount>
LEGACY_EVENT_RE = re.compile(r"^discord:(\d+):(.+):(\d+)$")
# v2 embed-index format: discord:<message_id>:<embed_index>
V2_EVENT_RE = re.compile(r"^discord:(\d+):(\d+)$")
# Transaction format: txn:<provider>:<transaction_id>
TXN_EVENT_RE = re.compile(r"^txn:([^:]+):(.+)$")


def legacy_source_event_id(message_id, item_name, amount_robux):
    """Recreate the historical (v1) source event id for a message+embed."""
    return f"discord:{message_id}:{item_name}:{amount_robux}"


def build_source_event_id(message_id, embed_index, transaction_id=None,
                          provider="roblox"):
    """Deterministic, per-embed id. Provider transaction id wins."""
    if transaction_id:
        return f"txn:{provider}:{transaction_id}"
    return f"discord:{message_id}:{embed_index}"


def is_legacy_event_id(value):
    return bool(value) and LEGACY_EVENT_RE.match(str(value)) is not None


def is_v2_event_id(value):
    return bool(value) and V2_EVENT_RE.match(str(value)) is not None


def is_txn_event_id(value):
    return bool(value) and TXN_EVENT_RE.match(str(value)) is not None


# ════════════════════════════════════════════════════════════════════
# Field parsing helpers
# ════════════════════════════════════════════════════════════════════

TXN_TIME_FIELD_NAMES = (
    "date", "time", "sold at", "purchased at", "purchase time", "sale time",
    "transaction date", "transaction time", "transaction timestamp",
    "created at", "timestamp", "when", "completed at", "purchase date",
)

TXN_ID_FIELD_KEYS = (
    "transaction id", "transaction", "order id", "order", "order number",
    "sale id", "purchase id", "receipt id", "receipt", "txn id",
    "transaction number",
)

ASSET_FIELD_KEYS = ("asset id", "item id", "asset", "catalog id", "assetid")
GROUP_FIELD_KEYS = ("group id", "group", "groupid", "seller id")

TXN_ID_TEXT_RE = re.compile(
    r"(?:transaction|order|sale|purchase|receipt|txn)\s*"
    r"(?:id|no\.?|number|#)?\s*[:#]\s*([A-Za-z0-9][A-Za-z0-9_\-]{3,})",
    re.IGNORECASE,
)

ASSET_URL_RE = re.compile(r"roblox\.com/(?:catalog|library)/(\d+)", re.IGNORECASE)

_DT_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%y %H:%M:%S",
    "%m/%d/%y %H:%M",
    "%b %d, %Y %I:%M %p",
    "%B %d, %Y %I:%M %p",
    "%b %d, %Y",
    "%B %d, %Y",
    "%Y-%m-%d",
)


def _parse_revenue(raw):
    """Parse a Robux amount. Handles thousands separators, ignores decimals."""
    if not raw:
        return 0
    m = re.search(r"([0-9][0-9,]*)", str(raw))
    if not m:
        return 0
    return int(m.group(1).replace(",", ""))


def _strip_emoji(s):
    if not s:
        return ""
    return re.sub(r"^[^\w]+", "", str(s)).strip()


def _safe_str(v):
    """Convert any value to a stripped string, or '' for None."""
    if v is None:
        return ""
    return str(v).strip()


def _embed_footer(embed):
    footer = getattr(embed, "footer", None)
    return _safe_str(getattr(footer, "text", None))


def _parse_datetime(value):
    """Parse a webhook timestamp into a tz-aware UTC datetime, or None."""
    s = str(value).strip()
    if not s:
        return None

    m = re.match(r"<t:(\d+)(?::[a-zA-Z])?>", s)
    if m:
        return _epoch_to_utc(m.group(1))
    if re.match(r"^\d{9,13}$", s):
        return _epoch_to_utc(s)

    dt = None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    if dt is None:
        for fmt in _DT_FORMATS:
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _epoch_to_utc(epoch_str):
    try:
        v = float(epoch_str)
    except (TypeError, ValueError):
        return None
    if v > 1e11:  # milliseconds
        v /= 1000.0
    return datetime.fromtimestamp(v, tz=timezone.utc)


def _extract_transaction_id(embed, title, desc):
    """Provider transaction ID from fields, footer, or body text."""
    for field in (embed.fields or []):
        name = _safe_str(field.name).lower()
        if any(k in name for k in TXN_ID_FIELD_KEYS) or name.strip() == "id":
            val = _safe_str(field.value)
            m = re.search(r"([A-Za-z0-9][A-Za-z0-9_\-]{3,})", val)
            if m:
                return m.group(1)
    text = "\n".join(x for x in (desc, title, _embed_footer(embed)) if x)
    m = TXN_ID_TEXT_RE.search(text)
    return m.group(1) if m else None


def _extract_asset_id(embed, title, desc):
    """Roblox catalog asset id from fields or URLs."""
    for field in (embed.fields or []):
        name = _safe_str(field.name).lower()
        if any(k in name for k in ASSET_FIELD_KEYS):
            m = re.search(r"(\d{6,})", _safe_str(field.value))
            if m:
                return int(m.group(1))
    for text in (title, desc):
        m = ASSET_URL_RE.search(text or "")
        if m:
            return int(m.group(1))
    return None


def _extract_group_id(embed, title):
    for field in (embed.fields or []):
        name = _safe_str(field.name).lower()
        if any(k in name for k in GROUP_FIELD_KEYS):
            m = re.search(r"(\d{4,})", _safe_str(field.value))
            if m:
                return int(m.group(1))
    m = re.search(r"group\s*(?:id)?\s*[:#]?\s*(\d{4,})", title or "",
                  re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _extract_buyer_id(embed):
    for field in (embed.fields or []):
        name = _safe_str(field.name).lower()
        if any(k in name for k in ("buyer id", "user id", "customer id")):
            m = re.search(r"(\d{4,})", _safe_str(field.value))
            if m:
                return int(m.group(1))
    return None


def _as_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ════════════════════════════════════════════════════════════════════
# Embed -> sale
# ════════════════════════════════════════════════════════════════════

def _extract_sale_from_embed(embed, message, embed_index=0):
    if not embed:
        return None

    title = _safe_str(embed.title)
    desc = _safe_str(embed.description)
    tl = title.lower()
    dl = desc.lower()

    sale_markers = (
        "new sale", "thank you for your purchase", "purchase",
        "sold", "sale", "transaction", "order",
    )
    is_sale = any(m in tl or m in dl for m in sale_markers)
    if not is_sale:
        print(f"[sales_listener] not a sale — title={title[:60]!r}", flush=True)
        return None

    item_name = ""
    raw_item_name = ""
    revenue = 0
    buyer = ""
    group_name = ""

    if "—" in title:
        group_name = title.split("—", 1)[1].strip()
    elif "-" in title and "new sale" in tl:
        group_name = title.split("-", 1)[1].strip()

    for field in (embed.fields or []):
        name = _safe_str(field.name).lower()
        value = _safe_str(field.value)
        if not value:
            continue
        item_like = (
            "item" in name or "product" in name or "asset" in name
            or name.strip() in ("name", "item name", "product name")
        )
        if not item_name and item_like:
            raw_item_name = value
            item_name = _strip_emoji(value)
        elif revenue == 0 and any(k in name for k in
                                  ("revenue", "amount", "price", "robux", "total")):
            revenue = _parse_revenue(value)
        elif not buyer and any(k in name for k in
                               ("buyer", "user", "customer", "source")):
            buyer = _strip_emoji(value)
        elif not group_name and any(k in name for k in
                                    ("group", "seller", "store")):
            group_name = _strip_emoji(value)

    if not item_name:
        m = re.search(r"item[:\s]+(.+?)(?:\n|$)", desc, re.IGNORECASE)
        if m:
            raw_item_name = m.group(1).strip()
            item_name = _strip_emoji(raw_item_name)

    if not item_name:
        print(f"[sales_listener] SKIP — no item name found. "
              f"title={title[:60]!r} fields="
              f"{[(f.name, f.value[:30]) for f in (embed.fields or [])]}",
              flush=True)
        return None

    transaction_id = _extract_transaction_id(embed, title, desc)
    asset_id = _extract_asset_id(embed, title, desc)
    group_id = _extract_group_id(embed, title)
    buyer_id = _extract_buyer_id(embed)

    notification_time = _as_utc(getattr(message, "created_at", None))

    # Marketplace transaction time: dated field > embed.timestamp > message time.
    sale_time = None
    time_source = "message_created"
    for field in (embed.fields or []):
        name = _safe_str(field.name).lower()
        if name.strip() in TXN_TIME_FIELD_NAMES:
            parsed = _parse_datetime(field.value)
            if parsed is not None:
                sale_time = parsed
                time_source = "transaction_field"
                break
    if sale_time is None:
        embed_ts = getattr(embed, "timestamp", None)
        if isinstance(embed_ts, datetime):
            sale_time = _as_utc(embed_ts)
            time_source = "embed_timestamp"
    if sale_time is None:
        sale_time = notification_time or _as_utc(datetime.now(timezone.utc))
        time_source = "message_created"

    message_id = str(getattr(message, "id", ""))
    return {
        "sale_date": sale_time.date(),
        "sale_time": sale_time,                 # marketplace transaction time
        "notification_time": notification_time, # Discord notification time
        "time_source": time_source,
        "item_name": item_name,
        "raw_item_name": raw_item_name or item_name,
        "buyer": buyer,
        "amount_robux": revenue,
        "status": "Complete",
        "group_name": group_name,
        "transaction_id": transaction_id,
        "asset_id": asset_id,
        "group_id": group_id,
        "buyer_id": buyer_id,
        "embed_index": embed_index,
        "message_id": message_id,
        "source_event_id": build_source_event_id(
            message_id, embed_index, transaction_id),
        "source_event_version": "v2",
        "source": "discord",
        "_legacy_id": legacy_source_event_id(message_id, item_name, revenue)
        if message_id else None,
    }


def extract_sales_from_message(message):
    """Parse every sale embed in a message with a stable per-embed index."""
    sales = []
    for index, embed in enumerate(message.embeds or []):
        try:
            sale = _extract_sale_from_embed(embed, message, embed_index=index)
        except Exception as e:
            print(f"[sales_listener] embed parse failed: "
                  f"{type(e).__name__}: {e}", flush=True)
            continue
        if sale:
            sales.append(sale)
    return sales


# ════════════════════════════════════════════════════════════════════
# Deduplication / conflict resolution
# ════════════════════════════════════════════════════════════════════

def duplicate_reason(sale, existing_rows):
    """Return a string reason if ``sale`` is already represented by an
    existing row, else None. Never flags two rows with distinct stable
    event ids as duplicates.

    Legacy ids and fingerprints are buyer-sensitive: two different buyers
    purchasing the same item at the same price never collapse just because
    they share a legacy source-event id.
    """
    sid = sale.get("source_event_id")
    txid = sale.get("transaction_id")
    legacy = sale.get("_legacy_id")
    buyer = sale.get("buyer")
    ntime = sale.get("notification_time")
    stime = sale.get("sale_time")

    for r in existing_rows:
        rsid = r.get("source_event_id")

        if sid and rsid == sid:
            return "source_event_id"
        if txid and r.get("transaction_id") == txid:
            return "transaction_id"

        # A stable, non-legacy id that differs is a *different* sale.
        if rsid and not is_legacy_event_id(rsid):
            if sid and sid != rsid:
                continue
            if not sid and txid and r.get("transaction_id") != txid:
                continue

        # Same buyer required before treating a legacy id as already captured.
        if (legacy and rsid == legacy
                and _same_buyer(buyer, r.get("buyer"))):
            return "legacy_source_event_id"

        # Fingerprint fallback only applies to legacy/unknown rows, and only
        # when the buyer is consistent (unknown buyer is not a distinguishing
        # signal, so it still matches).
        if (ntime is not None and r.get("notification_time") is not None
                and _same_buyer(buyer, r.get("buyer"))):
            if _same_instant(ntime, r["notification_time"]):
                return "notification_fingerprint"
        if (stime is not None and r.get("sale_time") is not None
                and ntime is None and r.get("notification_time") is None
                and _same_buyer(buyer, r.get("buyer"))):
            if _same_instant(stime, r["sale_time"]):
                return "sale_time_fingerprint"

    return None


def _same_buyer(a, b):
    """Buyers match when both are empty or equal (case-insensitive)."""
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    if not a or not b:
        return True
    return a == b


def _same_instant(a, b):
    if a is None or b is None:
        return False
    try:
        return _as_utc(a) == _as_utc(b)
    except (TypeError, ValueError):
        return a == b


# ════════════════════════════════════════════════════════════════════
# Schema awareness + insert
# ════════════════════════════════════════════════════════════════════

_BASE_COLUMNS = ("sale_date", "sale_time", "item_name", "buyer",
                 "amount_robux", "status")

# python key -> column name (only inserted when the column exists)
_OPTIONAL_COLUMNS = (
    ("source_event_id", "source_event_id"),
    ("source", "source"),
    ("group_name", "group_name"),
    ("notification_time", "notification_time"),
    ("transaction_id", "transaction_id"),
    ("source_event_version", "source_event_version"),
    ("embed_index", "embed_index"),
    ("asset_id", "asset_id"),
    ("group_id", "group_id"),
    ("buyer_id", "buyer_id"),
    ("raw_item_name", "raw_item_name"),
    ("time_source", "time_source"),
)

_DEFAULT_COLUMNS = set(_BASE_COLUMNS) | {"source_event_id", "source"}


def _sales_columns(cur):
    """Detect which my_sales columns exist so inserts work pre/post migration."""
    try:
        cur.execute(
            "select column_name from information_schema.columns "
            "where table_name = 'my_sales'"
        )
        rows = cur.fetchall()
        cols = {r[0] for r in (rows or [])}
    except Exception:
        cols = set()
    if not cols:
        cols = set(_DEFAULT_COLUMNS)
    return cols


def _conflict_rows(cur, sale, columns):
    """Fetch existing rows that could represent the same sale."""
    clauses = []
    params = []
    if "source_event_id" in columns:
        clauses.append("source_event_id = %s")
        params.append(sale.get("source_event_id"))
    if "transaction_id" in columns and sale.get("transaction_id"):
        clauses.append("transaction_id = %s")
        params.append(sale["transaction_id"])
    if sale.get("item_name") and sale.get("amount_robux") is not None:
        clauses.append(
            "(item_name IS NOT DISTINCT FROM %s "
            "AND amount_robux IS NOT DISTINCT FROM %s)"
        )
        params += [sale["item_name"], sale["amount_robux"]]
    if not clauses:
        return []

    select = ["source_event_id", "sale_time", "item_name", "buyer",
              "amount_robux"]
    for col in ("transaction_id", "notification_time", "source_event_version"):
        if col in columns:
            select.append(col)

    cur.execute(
        "select " + ", ".join(select) + " from my_sales where "
        + " or ".join(clauses),
        params,
    )
    rows = cur.fetchall() or []
    return [dict(zip(select, r)) for r in rows]


def _do_insert(cur, sale, columns):
    cols = []
    vals = []
    for col in _BASE_COLUMNS:
        if col in columns:
            cols.append(col)
            vals.append(sale.get(col))
    for py_key, col in _OPTIONAL_COLUMNS:
        if col in columns and py_key in sale:
            cols.append(col)
            vals.append(sale[py_key])
    if not cols:
        return 0
    placeholders = ", ".join(["%s"] * len(cols))
    cur.execute(
        f"insert into my_sales ({', '.join(cols)}) "
        f"values ({placeholders}) on conflict do nothing",
        vals,
    )
    return cur.rowcount > 0


def _insert_sale_result(cur, sale, columns=None):
    """Insert if not already present. Returns (inserted: bool, reason: str)."""
    columns = columns or _sales_columns(cur)
    existing = _conflict_rows(cur, sale, columns)
    reason = duplicate_reason(sale, existing)
    if reason:
        return False, reason
    inserted = _do_insert(cur, sale, columns)
    return (True, "inserted") if inserted else (False, "unique_conflict")


def _insert_sale(cur, sale):
    """Backwards-compatible single-sale insert. Returns True if inserted."""
    inserted, _ = _insert_sale_result(cur, sale)
    return inserted


# ════════════════════════════════════════════════════════════════════
# Persistence
# ════════════════════════════════════════════════════════════════════

def _save_sales_batch(sales_list):
    """Insert many sales with ONE connection. Returns (inserted, skipped)."""
    if not sales_list:
        return 0, 0

    print(f"[sales_listener] batch starting — {len(sales_list)} rows",
          flush=True)

    conn = None
    cur = None
    inserted = 0
    skipped = 0
    try:
        conn = get_db()
        cur = conn.cursor()
        columns = _sales_columns(cur)
        for sale in sales_list:
            try:
                cur.execute("SAVEPOINT sp_sale")
                ok, reason = _insert_sale_result(cur, sale, columns)
                if ok:
                    inserted += 1
                else:
                    print(f"[sales_listener] skip ({reason}): "
                          f"{sale.get('item_name', '?')[:40]}", flush=True)
                    skipped += 1
                cur.execute("RELEASE SAVEPOINT sp_sale")
            except Exception as e:
                try:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_sale")
                except Exception:
                    pass
                print(f"[sales_listener] row failed for "
                      f"'{sale.get('item_name', '?')[:40]}': "
                      f"{type(e).__name__}: {e}", flush=True)
                skipped += 1
        conn.commit()
        print(f"[sales_listener] batch done — inserted {inserted} · "
              f"skipped {skipped}", flush=True)
    except Exception as e:
        print(f"[sales_listener] batch COMMIT failed: "
              f"{type(e).__name__}: {e}", flush=True)
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
    finally:
        try:
            if cur: cur.close()
        except Exception:
            pass
        try:
            if conn: conn.close()
        except Exception:
            pass
    return inserted, skipped


def _save_sale_single(sale):
    """Single-sale save (used by live listener). Runs in thread."""
    if not sale:
        return False
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor()
        ok, reason = _insert_sale_result(cur, sale)
        conn.commit()
        if not ok:
            print(f"[sales_listener] dup ({reason}): "
                  f"{sale.get('item_name', '?')[:40]}", flush=True)
        return ok
    except Exception as e:
        print(f"[sales_listener] save failed for "
              f"'{sale.get('item_name', '?')[:40]}': "
              f"{type(e).__name__}: {e}", flush=True)
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        return False
    finally:
        try:
            if cur: cur.close()
        except Exception:
            pass
        try:
            if conn: conn.close()
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════
# Live listener + backfill
# ════════════════════════════════════════════════════════════════════

async def handle_sale_message(message):
    """Called from on_message — runs DB writes off the event loop."""
    if not message.embeds:
        return False
    saved_any = False
    for sale in extract_sales_from_message(message):
        is_new = await asyncio.to_thread(_save_sale_single, sale)
        if is_new:
            print(
                f"[sales_listener] OK {sale['item_name'][:40]} "
                f"R${sale['amount_robux']} "
                f"({sale.get('group_name', '?')}) "
                f"idx={sale['embed_index']}",
                flush=True,
            )
            saved_any = True
    return saved_any


async def backfill_channel(bot, channel_id, limit=200):
    """
    Read past messages, extract sales, batch-insert.
    Uses ONE DB connection for the whole batch.
    """
    print(f"[backfill] starting — channel={channel_id} limit={limit}",
          flush=True)

    try:
        ch = bot.get_channel(int(channel_id))
        if not ch:
            print(f"[backfill] channel {channel_id} not found", flush=True)
            return 0, 0
        print(f"[backfill] found channel #{ch.name}", flush=True)
    except Exception as e:
        print(f"[backfill] channel lookup failed: {e}", flush=True)
        return 0, 0

    scanned = 0
    sales_batch = []
    try:
        async for msg in ch.history(limit=limit):
            scanned += 1
            sales_batch.extend(extract_sales_from_message(msg))
    except Exception as e:
        print(f"[backfill] history read failed: {e}", flush=True)
        return scanned, 0

    print(f"[backfill] scanned {scanned} messages · "
          f"found {len(sales_batch)} sales", flush=True)

    if not sales_batch:
        return scanned, 0

    inserted, skipped = await asyncio.to_thread(
        _save_sales_batch, sales_batch
    )
    return scanned, inserted


async def auto_backfill(bot, limit=500):
    """Import sales posted while the bot was offline.

    Runs on startup and right before every report, so nobody has to type
    !sales_backfill. Inserts are deduped, so repeated calls are harmless.
    """
    channel_id = os.getenv("SALES_CHANNEL_ID", "").strip()
    if not channel_id:
        print("[auto-backfill] SALES_CHANNEL_ID not set — skipping", flush=True)
        return 0, 0
    try:
        scanned, saved = await backfill_channel(bot, channel_id, limit=limit)
        print(f"[auto-backfill] scanned {scanned} · imported {saved}", flush=True)
        return scanned, saved
    except Exception as e:
        print(f"[auto-backfill] failed: {type(e).__name__}: {e}", flush=True)
        return 0, 0


# ════════════════════════════════════════════════════════════════════
# Summary queries
# ════════════════════════════════════════════════════════════════════

def window_coverage_stats(cur, start, end):
    """Read-only, window-scoped counts of how complete/trustworthy totals are.

    Distinguishes *event-id completeness* (every row in the window has a
    source_event_id) from *source-history completeness* (every row has an id
    AND there are no duplicate ids or legacy fingerprints in the window).
    """
    where = "sale_date >= %s and sale_date < %s"
    p = (start, end)

    def _one(sql, params=()):
        try:
            cur.execute(sql, params)
            return int(cur.fetchone()[0] or 0)
        except Exception:
            return 0

    total = _one(f"select count(*) from my_sales where {where}", p)
    event_id = _one(
        f"select count(*) from my_sales where {where} "
        f"and source_event_id is not null", p)
    legacy = _one(
        f"select count(*) from my_sales where {where} "
        f"and source_event_id is not null "
        f"and source_event_id ~ '^discord:[0-9]+:[^:]+:[0-9]+$'", p)
    v2 = _one(
        f"select count(*) from my_sales where {where} "
        f"and source_event_id is not null "
        f"and source_event_id ~ '^discord:[0-9]+:[0-9]+$'", p)
    txn = _one(
        f"select count(*) from my_sales where {where} "
        f"and source_event_id is not null "
        f"and source_event_id ~ '^txn:'", p)
    dup_event = _one(
        f"select count(*) from ("
        f"select source_event_id from my_sales where {where} "
        f"and source_event_id is not null "
        f"group by 1 having count(*) > 1) t", p)
    dup_fp = _one(
        f"select count(*) from ("
        f"select sale_time, item_name, buyer, amount_robux from my_sales "
        f"where {where} and source_event_id is null "
        f"group by 1, 2, 3, 4 having count(*) > 1) t", p)

    has_txn = "transaction_id" in _sales_columns(cur)
    transaction_evidence = _one(
        f"select count(*) from my_sales where {where} "
        f"and transaction_id is not null", p) if has_txn else 0

    fallback = total - event_id
    return {
        "total": total,
        "event_id": event_id,
        "fallback_fingerprint": fallback,
        "legacy_event_ids": legacy,
        "v2_event_ids": v2,
        "txn_event_ids": txn,
        "transaction_evidence": transaction_evidence,
        "duplicate_event_ids": dup_event,
        "duplicate_fingerprints": dup_fp,
        "coverage_pct": round(100.0 * event_id / max(total, 1), 1),
        "event_id_complete": total > 0 and event_id == total,
        "source_complete": (
            total > 0 and event_id == total
            and dup_event == 0 and dup_fp == 0
        ),
    }


def _coverage_note(cov):
    parts = []
    if not cov.get("source_complete"):
        parts.append("source history incomplete")
    if cov.get("fallback_fingerprint"):
        parts.append(f"{cov['fallback_fingerprint']} rows lack a source event id")
    if cov.get("duplicate_event_ids"):
        parts.append(f"{cov['duplicate_event_ids']} duplicate event id groups")
    if cov.get("duplicate_fingerprints"):
        parts.append(f"{cov['duplicate_fingerprints']} duplicate legacy fingerprints")
    return "; ".join(parts) or "source history complete"


def sales_summary(days=30):
    conn = None; cur = None
    try:
        conn = get_db()
        cur = conn.cursor()

        from reporting import window_bounds, describe_window, AMOUNT_SEMANTICS
        from item_resolver import sales_breakdown

        start, end, anchor = window_bounds(cur, days)
        data = sales_breakdown(cur, start, end)
        totals = data["totals"]

        cur.execute("""
            select sale_date, count(*), coalesce(sum(amount_robux), 0)
            from my_sales
            where sale_date >= %s and sale_date < %s
            group by sale_date
            order by sale_date desc
            limit 14
        """, (start, end))
        daily = cur.fetchall()

        top_items = [(g["name"], g["records"], g["robux"])
                     for g in data["items"][:10] if g["item_id"]]
        unresolved = [g for g in data["items"] if not g["item_id"]]

        coverage = window_coverage_stats(cur, start, end)
        coverage.update(totals)
        coverage["complete"] = coverage["source_complete"]
        coverage["note"] = _coverage_note(coverage)

        return {
            "days": days,
            "window": describe_window(start, end, anchor),
            "total_units": totals["records"],
            "total_robux": totals["robux"],
            "top_items": top_items,
            "unresolved": unresolved,
            "coverage": coverage,
            "amount_semantics": AMOUNT_SEMANTICS,
            "daily": daily,
        }
    finally:
        try:
            if cur: cur.close()
        except Exception:
            pass
        try:
            if conn: conn.close()
        except Exception:
            pass


def item_sales_summary(item_name, days=30):
    if not item_name:
        return None
    conn = None; cur = None
    try:
        conn = get_db()
        cur = conn.cursor()

        from reporting import window_bounds, AMOUNT_SEMANTICS
        from item_resolver import (normalize_name, resolve_name,
                                   sales_breakdown)

        start, end, anchor = window_bounds(cur, days)
        target = resolve_name(cur, item_name)
        data = sales_breakdown(cur, start, end)

        match = None
        if target.get("item_id"):
            match = next((g for g in data["items"]
                          if g["item_id"] == target["item_id"]), None)
        if match is None:
            wanted = normalize_name(item_name)
            for g in data["items"]:
                if any(normalize_name(a) == wanted for a in g["aliases"]):
                    match = g
                    break

        if match:
            return {
                "units": match["records"],
                "robux": match["robux"],
                "last_sale": match["last_sale"],
                "days": days,
                "name": match["name"],
                "status": match["status"],
                "amount_semantics": AMOUNT_SEMANTICS,
                "window": (str(start), str(end)),
            }

        # Preserve the old fuzzy behaviour for names we cannot resolve.
        like = f"%{item_name[:20]}%"
        cur.execute("""
            select count(*), coalesce(sum(amount_robux), 0), max(sale_time)
            from my_sales
            where lower(item_name) like lower(%s)
              and sale_date >= %s and sale_date < %s
        """, (like, start, end))
        units, robux, last = cur.fetchone()
        if not units:
            return None
        return {
            "units": units, "robux": robux or 0,
            "last_sale": last, "days": days,
            "name": item_name,
            "status": "unresolved_fuzzy",
            "amount_semantics": AMOUNT_SEMANTICS,
            "window": (str(start), str(end)),
        }
    finally:
        try:
            if cur: cur.close()
        except Exception:
            pass
        try:
            if conn: conn.close()
        except Exception:
            pass
