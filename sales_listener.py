"""
sales_listener.py — reads Roblox sale webhook embeds from Discord,
saves to my_sales, and provides summary functions.
"""
import re
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


def _extract_sale_from_embed(embed, message):
    if not embed:
        return None

    title = (embed.title or "").strip()
    desc = (embed.description or "").strip()
    tl = title.lower()
    dl = desc.lower()

    is_sale = (
        "new sale" in tl
        or "thank you for your purchase" in tl
        or "new sale" in dl
        or "thank you for your purchase" in dl
    )
    if not is_sale:
        return None

    item_name = ""
    revenue = 0
    buyer = ""
    group_name = ""

    if "—" in title:
        group_name = title.split("—", 1)[1].strip()
    elif "-" in title and "new sale" in tl:
        group_name = title.split("-", 1)[1].strip()

    for field in (embed.fields or []):
        name = (field.name or "").strip().lower()
        value = (field.value or "").strip()
        if not value:
            continue
        if "item" in name:
            item_name = _strip_emoji(value)
        elif "revenue" in name or "amount" in name:
            revenue = _parse_revenue(value)
        elif "buyer" in name or "user" in name or "source" in name:
            buyer = _strip_emoji(value)
        elif "group" in name or "seller" in name:
            if not group_name:
                group_name = _strip_emoji(value)

    if not item_name:
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


def save_sale(sale):
    if not sale:
        return False
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            insert into my_sales
              (sale_date, sale_time, item_name, buyer, amount_robux, status)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (sale_time, item_name, buyer, amount_robux)
            do nothing
        """, (
            sale["sale_date"], sale["sale_time"], sale["item_name"],
            sale["buyer"], sale["amount_robux"], sale["status"],
        ))
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        print(f"[sales_listener] save failed: {e}", flush=True)
        return False
    finally:
        cur.close(); conn.close()


async def handle_sale_message(message):
    if not message.embeds:
        return False
    saved_any = False
    for embed in message.embeds:
        try:
            sale = _extract_sale_from_embed(embed, message)
            if not sale:
                continue
            is_new = save_sale(sale)
            if is_new:
                print(
                    f"[sales_listener] OK {sale['item_name'][:40]} "
                    f"R${sale['amount_robux']} ({sale.get('group_name', '?')})",
                    flush=True,
                )
                saved_any = True
            else:
                print(f"[sales_listener] dup: {sale['item_name'][:40]}", flush=True)
        except Exception as e:
            print(f"[sales_listener] embed parse failed: {e}", flush=True)
    return saved_any


async def backfill_channel(bot, channel_id, limit=500):
    """Read past messages from sales channel, parse and save all sales."""
    try:
        ch = bot.get_channel(int(channel_id))
        if not ch:
            return 0, 0
        scanned = 0
        saved = 0
        async for msg in ch.history(limit=limit):
            scanned += 1
            for embed in (msg.embeds or []):
                try:
                    sale = _extract_sale_from_embed(embed, msg)
                    if sale and save_sale(sale):
                        saved += 1
                except Exception:
                    continue
        return scanned, saved
    except Exception as e:
        print(f"[sales_listener] backfill failed: {e}", flush=True)
        return 0, 0


# ════════════════════════════════════════════════════════════════════
# Summary queries
# ════════════════════════════════════════════════════════════════════

def sales_summary(days=30):
    """Returns dict with totals + top items + daily trend."""
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            select count(*), coalesce(sum(amount_robux), 0)
            from my_sales
            where sale_date > current_date - %s
        """, (days,))
        total_units, total_robux = cur.fetchone()

        cur.execute("""
            select item_name, count(*) as units,
                   coalesce(sum(amount_robux), 0) as robux
            from my_sales
            where sale_date > current_date - %s
            group by item_name
            order by robux desc
            limit 10
        """, (days,))
        top_items = cur.fetchall()

        cur.execute("""
            select sale_date, count(*), coalesce(sum(amount_robux), 0)
            from my_sales
            where sale_date > current_date - %s
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
        cur.close(); conn.close()


def item_sales_summary(item_name, days=30):
    """Sales for a specific item by name (fuzzy match)."""
    if not item_name:
        return None
    conn = get_db(); cur = conn.cursor()
    try:
        like = f"%{item_name[:20]}%"
        cur.execute("""
            select count(*), coalesce(sum(amount_robux), 0), max(sale_time)
            from my_sales
            where lower(item_name) like lower(%s)
              and sale_date > current_date - %s
        """, (like, days))
        units, robux, last = cur.fetchone()
        if not units:
            return None
        return {
            "units": units, "robux": robux or 0,
            "last_sale": last, "days": days,
        }
    finally:
        cur.close(); conn.close()
