"""
sales_listener.py — reads Roblox sale webhook embeds from Discord,
saves to my_sales, and provides summary functions.

All DB writes batch or run via asyncio.to_thread — no event loop blocking.
Verbose logging so we can trace exactly what happens.
"""
import re
import asyncio
from datetime import datetime, timezone
from bot_core import get_db


def _parse_revenue(raw):
    if not raw:
        return 0
    m = re.search(r"(\d+)", str(raw))
    return int(m.group(1)) if m else 0


def _strip_emoji(s):
    if not s:
        return ""
    return re.sub(r"^[^\w]+", "", str(s)).strip()


def _safe_str(v):
    """Convert any value to a stripped string, or '' for None."""
    if v is None:
        return ""
    return str(v).strip()


def _extract_sale_from_embed(embed, message):
    if not embed:
        return None

    title = _safe_str(embed.title)
    desc = _safe_str(embed.description)
    tl = title.lower()
    dl = desc.lower()

    # Match on title OR description. Broader than before: sale webhooks
    # change wording ("purchase", "sold", "transaction", "order"), and a
    # strict match silently drops every new sale.
    sale_markers = (
        "new sale", "thank you for your purchase", "purchase",
        "sold", "sale", "transaction", "order",
    )
    is_sale = any(m in tl or m in dl for m in sale_markers)
    if not is_sale:
        print(f"[sales_listener] not a sale — title={title[:60]!r}", flush=True)
        return None

    item_name = ""
    revenue = 0
    buyer = ""
    group_name = ""

    # Group from title: "💰 New Sale — Eroseris UGC Group"
    if "—" in title:
        group_name = title.split("—", 1)[1].strip()
    elif "-" in title and "new sale" in tl:
        group_name = title.split("-", 1)[1].strip()

    # Parse fields
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

    # Fallback: try to extract item name from title/description
    if not item_name:
        # Try "Item: X" pattern
        m = re.search(r"item[:\s]+(.+?)(?:\n|$)", desc, re.IGNORECASE)
        if m:
            item_name = _strip_emoji(m.group(1))

    if not item_name:
        # Last resort: log the embed so we can see what we missed
        print(f"[sales_listener] SKIP — no item name found. "
              f"title={title[:60]!r} fields="
              f"{[(f.name, f.value[:30]) for f in (embed.fields or [])]}",
              flush=True)
        return None

    sale_time = message.created_at
    if sale_time.tzinfo is None:
        sale_time = sale_time.replace(tzinfo=timezone.utc)

    return {
        "sale_date": sale_time.date(),
        "sale_time": sale_time,
        "item_name": item_name,
        "buyer": buyer,
        "amount_robux": revenue,
        "status": "Complete",
        "group_name": group_name,
    }


def _insert_sale(cur, sale):
    """Insert one sale without relying on an ON CONFLICT unique constraint.

    A hand-created my_sales table may lack the unique index that
    ON CONFLICT requires, which makes every insert fail silently.
    """
    params = (
        sale["sale_date"], sale["sale_time"], sale["item_name"],
        sale["buyer"], sale["amount_robux"], sale["status"],
    )
    cur.execute("""
        insert into my_sales
          (sale_date, sale_time, item_name, buyer, amount_robux, status)
        select %s, %s, %s, %s, %s, %s
        where not exists (
            select 1 from my_sales
            where sale_time::timestamptz = %s::timestamptz
              and item_name is not distinct from %s
              and buyer is not distinct from %s
              and amount_robux is not distinct from %s
        )
    """, params + (
        sale["sale_time"], sale["item_name"],
        sale["buyer"], sale["amount_robux"],
    ))
    return cur.rowcount > 0


def _save_sales_batch(sales_list):
    """
    Insert many sales with ONE connection. Used by backfill.
    Returns (inserted, skipped).
    """
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
        for sale in sales_list:
            try:
                cur.execute("SAVEPOINT sp_sale")
                if _insert_sale(cur, sale):
                    inserted += 1
                else:
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
        is_new = _insert_sale(cur, sale)
        conn.commit()
        return is_new
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


async def handle_sale_message(message):
    """Called from on_message — runs DB write off the event loop."""
    if not message.embeds:
        return False
    saved_any = False
    for embed in message.embeds:
        try:
            sale = _extract_sale_from_embed(embed, message)
            if not sale:
                continue
            is_new = await asyncio.to_thread(_save_sale_single, sale)
            if is_new:
                print(
                    f"[sales_listener] OK {sale['item_name'][:40]} "
                    f"R${sale['amount_robux']} "
                    f"({sale.get('group_name', '?')})",
                    flush=True,
                )
                saved_any = True
            else:
                print(f"[sales_listener] dup: "
                      f"{sale['item_name'][:40]}", flush=True)
        except Exception as e:
            print(f"[sales_listener] embed parse failed: "
                  f"{type(e).__name__}: {e}", flush=True)
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
            for embed in (msg.embeds or []):
                try:
                    sale = _extract_sale_from_embed(embed, msg)
                    if sale:
                        sales_batch.append(sale)
                except Exception as e:
                    print(f"[backfill] parse err on msg {msg.id}: {e}",
                          flush=True)
                    continue
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


# ════════════════════════════════════════════════════════════════════
# Summary queries
# ════════════════════════════════════════════════════════════════════

def sales_summary(days=30):
    conn = None; cur = None
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            select count(*), coalesce(sum(amount_robux), 0)
            from my_sales
            where sale_date > (now() AT TIME ZONE 'UTC')::date - %s
        """, (days,))
        total_units, total_robux = cur.fetchone()

        cur.execute("""
            select item_name, count(*) as units,
                   coalesce(sum(amount_robux), 0) as robux
            from my_sales
            where sale_date > (now() AT TIME ZONE 'UTC')::date - %s
            group by item_name
            order by robux desc
            limit 10
        """, (days,))
        top_items = cur.fetchall()

        cur.execute("""
            select sale_date, count(*), coalesce(sum(amount_robux), 0)
            from my_sales
            where sale_date > (now() AT TIME ZONE 'UTC')::date - %s
            group by sale_date
            order by sale_date desc
            limit 14
        """, (days,))
        daily = cur.fetchall()

        return {
            "days": days,
            "total_units": total_units or 0,
            "total_robux": total_robux or 0,
            "top_items": top_items,
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
        like = f"%{item_name[:20]}%"
        cur.execute("""
            select count(*), coalesce(sum(amount_robux), 0), max(sale_time)
            from my_sales
            where lower(item_name) like lower(%s)
              and sale_date > (now() AT TIME ZONE 'UTC')::date - %s
        """, (like, days))
        units, robux, last = cur.fetchone()
        if not units:
            return None
        return {
            "units": units, "robux": robux or 0,
            "last_sale": last, "days": days,
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
