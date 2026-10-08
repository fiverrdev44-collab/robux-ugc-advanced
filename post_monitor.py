"""
post_monitor.py — Frequent polling for published UGC items (clothing excluded).
"""
import os
import time
import requests
from datetime import datetime, timezone
from monitoring_config import is_excluded

ROBLOX_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

SPIKE_PCT = 25.0
ALERT_COOLDOWN_MIN = 45
_GROUP_SALES_CACHE = {}
_GROUP_SALES_TTL = 900


def ensure_tables(cur):
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS my_portfolio (
                item_id BIGINT PRIMARY KEY,
                name TEXT,
                asset_type_id BIGINT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_refresh TIMESTAMP,
                notes TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS post_snapshots (
                id BIGSERIAL PRIMARY KEY,
                item_id BIGINT NOT NULL,
                favorite_count BIGINT, price BIGINT,
                total_sales BIGINT, sales_24h BIGINT, revenue_24h BIGINT,
                fetched_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""CREATE INDEX IF NOT EXISTS idx_post_snap_item_time
                       ON post_snapshots(item_id, fetched_at DESC)""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS post_events (
                id BIGSERIAL PRIMARY KEY,
                item_id BIGINT, event_type TEXT, severity TEXT,
                old_value BIGINT, new_value BIGINT, delta_pct NUMERIC(8,2),
                message TEXT,
                detected_at TIMESTAMPTZ DEFAULT NOW(),
                alerted BOOLEAN DEFAULT FALSE
            )
        """)
        cur.execute("""CREATE INDEX IF NOT EXISTS idx_post_events_alerted
                       ON post_events(alerted, detected_at DESC)""")
        cur.connection.commit()
    except Exception as e:
        print(f"[post_monitor] ensure_tables: {e}", flush=True)


def _cookie():
    return os.getenv("ROBLOSECURITY_COOKIE_1") or os.getenv("ROBLOSECURITY_COOKIE")


def _user_id():
    return os.getenv("ROBLOX_USER_ID") or None


def _group_ids():
    raw = os.getenv("ROBLOX_GROUP_IDS", "")
    return [g.strip() for g in raw.split(",") if g.strip().isdigit()]


def _filtered_portfolio(cur):
    cur.execute("SELECT item_id, name FROM my_portfolio")
    rows = cur.fetchall()
    out = []
    for iid, name in rows:
        try:
            cur.execute("SELECT asset_type_id FROM items WHERE id = %s", (iid,))
            r = cur.fetchone()
            atype = r[0] if r else 0
        except Exception:
            atype = 0
        if not is_excluded(atype):
            out.append((iid, name))
    return out


def fetch_public(item_id, cookie=None):
    headers = {"User-Agent": ROBLOX_UA, "Accept": "application/json"}
    if cookie:
        headers["Cookie"] = f".ROBLOSECURITY={cookie}"
    out = {"favs": 0, "price": 0, "name": None, "ok": False}
    try:
        r = requests.get(f"https://economy.roblox.com/v2/assets/{item_id}/details",
                         headers=headers, timeout=10)
        if r.status_code == 200:
            d = r.json()
            out["name"] = (d.get("Name") or "")[:200]
            out["price"] = d.get("PriceInRobux") or 0
            out["ok"] = True
    except Exception:
        pass
    try:
        r = requests.get(f"https://catalog.roblox.com/v1/favorites/assets/{item_id}/count",
                         headers=headers, timeout=10)
        if r.status_code == 200:
            out["favs"] = r.json()
    except Exception:
        pass
    return out


def _extract_tx_item_id(tx):
    """
    Find the item ID inside a transaction record.
    Group endpoint nests it as item.id; user endpoint uses assetId or id.
    """
    # Direct
    v = tx.get("assetId") or tx.get("itemId")
    if v:
        return v
    # Nested under "item"
    item = tx.get("item")
    if isinstance(item, dict):
        v = item.get("id") or item.get("assetId")
        if v:
            return v
    # Fallback: "id" if it looks like an asset (long number)
    v = tx.get("id")
    if v:
        return v
    return None


def _extract_tx_amount(tx):
    cur = tx.get("currency")
    if isinstance(cur, dict):
        return int(cur.get("amount") or 0)
    v = tx.get("amount")
    if v:
        return int(v)
    return 0


def _extract_tx_created(tx):
    return tx.get("created") or tx.get("createdAt") or tx.get("createdUtc")


def fetch_group_sales(cookie, group_id, max_pages=4):
    """Fetch sales from group. Cached 15 min. Logs raw response for debugging."""
    if not cookie or not group_id:
        return []

    cached = _GROUP_SALES_CACHE.get(group_id)
    if cached and (time.time() - cached[0]) < _GROUP_SALES_TTL:
        return cached[1]

    headers = {
        "User-Agent": ROBLOX_UA,
        "Accept": "application/json",
        "Cookie": f".ROBLOSECURITY={cookie}",
    }
    url = (
        f"https://economy.roblox.com/v2/groups/{group_id}/transactions"
        f"?transactionType=Sale&limit=100"
    )

    all_sales, cursor = [], ""
    for page in range(max_pages):
        u = f"{url}&cursor={cursor}" if cursor else url
        try:
            r = requests.get(u, headers=headers, timeout=12)
            if r.status_code == 429:
                print(f"[post_monitor] group {group_id} rate limited", flush=True)
                break
            if r.status_code in (401, 403):
                print(f"[post_monitor] group {group_id} auth failed (HTTP {r.status_code})", flush=True)
                break
            if r.status_code != 200:
                print(f"[post_monitor] group {group_id} HTTP {r.status_code}", flush=True)
                break
            d = r.json()
            page_data = d.get("data") or []
            if page == 0:
                print(f"[post_monitor] group {group_id} page0 keys: {list(d.keys())}", flush=True)
                if page_data:
                    print(f"[post_monitor] group {group_id} sample tx: {page_data[0]}", flush=True)
            all_sales.extend(page_data)
            cursor = d.get("nextPageCursor")
            if not cursor:
                break
        except Exception as e:
            print(f"[post_monitor] group {group_id}: {e}", flush=True)
            break
        time.sleep(2.0)

    print(f"[post_monitor] group {group_id} total tx fetched: {len(all_sales)}", flush=True)
    _GROUP_SALES_CACHE[group_id] = (time.time(), all_sales)
    return all_sales


def fetch_my_sales(cookie, user_id, max_pages=4):
    """Fetch sales from personal account + all configured groups."""
    if not cookie:
        return []

    all_sales = []

    if user_id:
        headers = {"User-Agent": ROBLOX_UA, "Accept": "application/json",
                   "Cookie": f".ROBLOSECURITY={cookie}"}
        url = f"https://economy.roblox.com/v2/users/{user_id}/transactions?transactionType=Sale&limit=100"
        cursor = ""
        for _ in range(max_pages):
            u = f"{url}&cursor={cursor}" if cursor else url
            try:
                r = requests.get(u, headers=headers, timeout=12)
                if r.status_code != 200:
                    break
                d = r.json()
                all_sales.extend(d.get("data") or [])
                cursor = d.get("nextPageCursor")
                if not cursor:
                    break
            except Exception:
                break
            time.sleep(1.5)

    for gid in _group_ids():
        try:
            group_sales = fetch_group_sales(cookie, gid, max_pages=4)
            all_sales.extend(group_sales)
        except Exception as e:
            print(f"[post_monitor] group {gid} sales failed: {e}", flush=True)

    print(f"[post_monitor] total sales records: {len(all_sales)}", flush=True)
    return all_sales


def _sales_for_item(sales_list, item_id, hours=24):
    """Count sales + revenue for one item in window. Robust matching."""
    if not sales_list:
        return 0, 0
    cutoff = datetime.now(timezone.utc).timestamp() - (hours * 3600)
    count, revenue = 0, 0
    for s in sales_list:
        try:
            tx_item = _extract_tx_item_id(s)
            if tx_item is None:
                continue
            if str(tx_item) != str(item_id):
                continue
            created = _extract_tx_created(s)
            if not created:
                continue
            created = str(created).replace("Z", "+00:00")
            ts = datetime.fromisoformat(created).timestamp()
            if ts < cutoff:
                continue
            count += 1
            revenue += _extract_tx_amount(s)
        except Exception:
            continue
    return count, revenue


def _last_snapshot(cur, item_id):
    try:
        cur.execute("""
            SELECT favorite_count, price, total_sales, sales_24h, revenue_24h
            FROM post_snapshots WHERE item_id = %s ORDER BY fetched_at DESC LIMIT 1
        """, (item_id,))
        r = cur.fetchone()
        if r:
            return {"favs": r[0] or 0, "price": r[1] or 0,
                    "total_sales": r[2] or 0, "sales_24h": r[3] or 0,
                    "revenue_24h": r[4] or 0}
    except Exception:
        pass
    return None


def _recent_event(cur, item_id, etype):
    try:
        cur.execute("""
            SELECT 1 FROM post_events
            WHERE item_id = %s AND event_type = %s
              AND detected_at >= NOW() - INTERVAL '%s minutes'
            LIMIT 1
        """, (item_id, etype, ALERT_COOLDOWN_MIN))
        return cur.fetchone() is not None
    except Exception:
        return False


def _record_event(cur, item_id, etype, sev, old_v, new_v, pct, msg):
    try:
        cur.execute("""
            INSERT INTO post_events
                (item_id, event_type, severity, old_value, new_value, delta_pct, message)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (item_id, etype, sev, old_v, new_v, pct, msg))
    except Exception as e:
        print(f"[post_monitor] event: {e}", flush=True)


def poll_all(get_db):
    conn = get_db(); cur = conn.cursor()
    alerts = []
    try:
        ensure_tables(cur)
        portfolio = _filtered_portfolio(cur)
        if not portfolio:
            return []

        cookie = _cookie()
        uid = _user_id()
        sales_list = fetch_my_sales(cookie, uid) if cookie else []

        for item_id, pname in portfolio:
            try:
                live = fetch_public(item_id, cookie)
                if not live["ok"]:
                    continue
                favs = live["favs"] or 0
                price = live["price"] or 0
                name = pname or live.get("name") or f"Item {item_id}"
                s24, r24 = _sales_for_item(sales_list, item_id, hours=24)
                s_all, _ = _sales_for_item(sales_list, item_id, hours=24 * 365)
                last = _last_snapshot(cur, item_id)

                try:
                    cur.execute("""
                        INSERT INTO post_snapshots
                            (item_id, favorite_count, price, total_sales, sales_24h, revenue_24h)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (item_id, favs, price, s_all, s24, r24))
                except Exception:
                    pass

                if not last:
                    continue

                old_f = last["favs"]
                if old_f > 0 and favs > old_f:
                    gained = favs - old_f
                    pct = (gained / old_f) * 100
                    if pct >= SPIKE_PCT and gained >= 5 and not _recent_event(cur, item_id, "fav_spike"):
                        sev = "critical" if pct >= 100 else "warning"
                        msg = f"Favorites +{gained:,} ({pct:+.0f}%) — now {favs:,}"
                        _record_event(cur, item_id, "fav_spike", sev, old_f, favs, round(pct, 2), msg)
                        alerts.append({"item_id": item_id, "name": name, "type": "fav_spike",
                                       "severity": sev, "message": msg, "pct": round(pct, 2)})

                old_s = last["sales_24h"]
                if old_s > 0 and s24 > old_s:
                    gained = s24 - old_s
                    pct = (gained / old_s) * 100
                    if pct >= SPIKE_PCT and gained >= 2 and not _recent_event(cur, item_id, "sales_spike"):
                        sev = "critical" if pct >= 100 else "warning"
                        msg = f"Sales +{gained} ({pct:+.0f}%)"
                        _record_event(cur, item_id, "sales_spike", sev, old_s, s24, round(pct, 2), msg)
                        alerts.append({"item_id": item_id, "name": name, "type": "sales_spike",
                                       "severity": sev, "message": msg, "pct": round(pct, 2)})

                old_p = last["price"]
                if old_p > 0 and price != old_p and not _recent_event(cur, item_id, "price_change"):
                    pct = ((price - old_p) / old_p) * 100
                    msg = f"Price R${old_p} → R${price} ({pct:+.1f}%)"
                    _record_event(cur, item_id, "price_change", "info", old_p, price, round(pct, 2), msg)
                    alerts.append({"item_id": item_id, "name": name, "type": "price_change",
                                   "severity": "info", "message": msg, "pct": round(pct, 2)})
            except Exception as e:
                print(f"[post_monitor] item {item_id}: {e}", flush=True)

        conn.commit()
        return alerts
    finally:
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass


def get_pulse(get_db, hours=24):
    conn = get_db(); cur = conn.cursor()
    try:
        ensure_tables(cur)
        portfolio = _filtered_portfolio(cur)
        if not portfolio:
            return []

        cookie = _cookie()
        uid = _user_id()
        sales_list = fetch_my_sales(cookie, uid) if cookie else []

        out = []
        for item_id, pname in portfolio:
            live = fetch_public(item_id, cookie)
            favs = live["favs"] or 0
            price = live["price"] or 0
            name = pname or live.get("name") or f"Item {item_id}"
            s24, r24 = _sales_for_item(sales_list, item_id, hours=24)
            s6, r6 = _sales_for_item(sales_list, item_id, hours=6)
            s1, r1 = _sales_for_item(sales_list, item_id, hours=1)
            s_all, r_all = _sales_for_item(sales_list, item_id, hours=24 * 365)

            try:
                cur.execute("""
                    SELECT favorite_count FROM post_snapshots
                    WHERE item_id = %s AND fetched_at <= NOW() - INTERVAL '24 hours'
                    ORDER BY fetched_at DESC LIMIT 1
                """, (item_id,))
                r = cur.fetchone()
                favs_24h_ago = r[0] if r else favs
            except Exception:
                favs_24h_ago = favs

            fav_vel = max(0, favs - favs_24h_ago)
            conv = (s24 / favs * 100) if favs > 0 else 0

            out.append({
                "item_id": item_id, "name": name, "favs": favs,
                "fav_velocity": fav_vel, "price": price,
                "sales_1h": s1, "sales_6h": s6, "sales_24h": s24,
                "sales_all": s_all, "revenue_all": r_all,
                "revenue_1h": r1, "revenue_6h": r6, "revenue_24h": r24,
                "conversion_pct": round(conv, 2),
            })
        return out
    finally:
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass


def get_recent_events(get_db, hours=24, only_unalerted=False):
    conn = get_db(); cur = conn.cursor()
    try:
        ensure_tables(cur)
        where = "detected_at >= NOW() - INTERVAL '%s hours'" % int(hours)
        if only_unalerted:
            where += " AND alerted = FALSE"
        cur.execute(f"""
            SELECT id, item_id, event_type, severity, old_value, new_value,
                   delta_pct, message, detected_at
            FROM post_events WHERE {where}
            ORDER BY detected_at DESC LIMIT 100
        """)
        return [{"id": r[0], "item_id": r[1], "type": r[2], "severity": r[3],
                 "old": r[4], "new": r[5], "pct": float(r[6]) if r[6] else 0,
                 "message": r[7], "at": r[8]} for r in cur.fetchall()]
    finally:
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass
