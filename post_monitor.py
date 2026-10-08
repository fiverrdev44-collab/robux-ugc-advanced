"""
post_monitor.py — Group sales fetcher with multi-endpoint fallback.

Endpoints tried in order:
  1. /v2/groups/{id}/transactions (legacy, may 403 on cloud IPs)
  2. /v2/groups/{id}/revenue/summary/Day (summary, often works)
  3. /v2/users/{uid}/transactions (personal fallback)

Rotates between ROBLOX_COOKIE_1 and ROBLOX_COOKIE_2 if available.
"""
import os
import time
import requests
from datetime import datetime, timezone, timedelta
from monitoring_config import is_excluded

ROBLOX_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

SPIKE_PCT = 25.0
ALERT_COOLDOWN_MIN = 45
_GROUP_SALES_CACHE = {}
_GROUP_SALES_TTL = 900


# ──────────────────────────────────────────────────────────
# Cookie management
# ──────────────────────────────────────────────────────────
_COOKIE_INDEX = [0]


def _all_cookies():
    """Return all non-empty cookies from env."""
    out = []
    for key in ("ROBLOSECURITY_COOKIE_1", "ROBLOSECURITY_COOKIE_2",
                "ROBLOSECURITY_COOKIE_3", "ROBLOSECURITY_COOKIE"):
        v = os.getenv(key, "").strip()
        if v:
            out.append(v)
    return out


def _cookie():
    cookies = _all_cookies()
    if not cookies:
        return None
    return cookies[_COOKIE_INDEX[0] % len(cookies)]


def _rotate_cookie():
    """Try the next cookie on auth failure."""
    cookies = _all_cookies()
    if len(cookies) > 1:
        _COOKIE_INDEX[0] = (_COOKIE_INDEX[0] + 1) % len(cookies)
        print(f"[post_monitor] rotated to cookie index {_COOKIE_INDEX[0]}", flush=True)


def _user_id():
    return os.getenv("ROBLOX_USER_ID") or None


def _group_ids():
    raw = os.getenv("ROBLOX_GROUP_IDS", "")
    return [g.strip() for g in raw.split(",") if g.strip().isdigit()]


# ──────────────────────────────────────────────────────────
# Tables
# ──────────────────────────────────────────────────────────
def ensure_tables(cur):
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS my_portfolio (
                item_id BIGINT PRIMARY KEY,
                name TEXT, asset_type_id BIGINT,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_refresh TIMESTAMP, notes TEXT
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


# ──────────────────────────────────────────────────────────
# HTTP helpers
# ──────────────────────────────────────────────────────────
def _headers(cookie):
    h = {
        "User-Agent": ROBLOX_UA,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.roblox.com",
        "Referer": "https://www.roblox.com/",
    }
    if cookie:
        h["Cookie"] = f".ROBLOSECURITY={cookie}"
    return h


def _get(url, cookie, timeout=12):
    try:
        return requests.get(url, headers=_headers(cookie), timeout=timeout)
    except Exception as e:
        print(f"[post_monitor] GET {url[:80]}: {e}", flush=True)
        return None


# ──────────────────────────────────────────────────────────
# Group sales — 3 endpoints
# ──────────────────────────────────────────────────────────
def _try_transactions_endpoint(gid, cookie, max_pages=4):
    """Endpoint 1: /v2/groups/{gid}/transactions"""
    url = (
        f"https://economy.roblox.com/v2/groups/{gid}/transactions"
        f"?transactionType=Sale&limit=100"
    )
    all_tx, cursor = [], ""
    for page in range(max_pages):
        u = f"{url}&cursor={cursor}" if cursor else url
        r = _get(u, cookie)
        if r is None:
            return None
        if r.status_code == 401:
            return None  # cookie dead
        if r.status_code == 403:
            return []  # endpoint blocked (not cookie)
        if r.status_code == 429:
            print(f"[post_monitor] gid {gid} rate-limited", flush=True)
            return all_tx
        if r.status_code != 200:
            print(f"[post_monitor] gid {gid} tx HTTP {r.status_code}", flush=True)
            return []
        try:
            d = r.json()
        except Exception:
            return []
        page_data = d.get("data") or []
        if page == 0 and page_data:
            print(f"[post_monitor] gid {gid} tx sample: {str(page_data[0])[:200]}", flush=True)
        all_tx.extend(page_data)
        cursor = d.get("nextPageCursor")
        if not cursor:
            break
        time.sleep(2.0)
    return all_tx


def _try_revenue_summary(gid, cookie):
    """
    Endpoint 2: revenue summary.
    Doesn't give individual sales, but confirms the cookie has group access.
    """
    url = f"https://economy.roblox.com/v2/groups/{gid}/revenue/summary/Day"
    r = _get(url, cookie)
    if r is None:
        return None
    if r.status_code in (401, 403):
        print(f"[post_monitor] gid {gid} revenue HTTP {r.status_code}", flush=True)
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
        print(f"[post_monitor] gid {gid} revenue summary: {data}", flush=True)
        return data
    except Exception:
        return None


def _try_payouts(gid, cookie):
    """Endpoint 3: group payouts — alternative auth path."""
    url = f"https://groups.roblox.com/v1/groups/{gid}/payouts"
    r = _get(url, cookie)
    if r is None:
        return None
    if r.status_code != 200:
        print(f"[post_monitor] gid {gid} payouts HTTP {r.status_code}", flush=True)
        return None
    try:
        return r.json()
    except Exception:
        return None


def fetch_group_sales(group_id, max_pages=4):
    """
    Try multiple endpoints + rotate cookies on auth failure.
    Returns list of sale transactions (may be empty if endpoint blocked).
    """
    cached = _GROUP_SALES_CACHE.get(group_id)
    if cached and (time.time() - cached[0]) < _GROUP_SALES_TTL:
        return cached[1]

    cookies = _all_cookies()
    if not cookies:
        print(f"[post_monitor] gid {group_id}: no cookies available", flush=True)
        return []

    # Try each cookie, then each endpoint
    for cookie_idx, cookie in enumerate(cookies):
        print(f"[post_monitor] gid {group_id}: trying cookie #{cookie_idx}", flush=True)

        # Endpoint 1: transactions
        tx = _try_transactions_endpoint(group_id, cookie, max_pages=max_pages)
        if tx is not None and len(tx) > 0:
            print(f"[post_monitor] gid {group_id} OK via transactions: {len(tx)} records", flush=True)
            _GROUP_SALES_CACHE[group_id] = (time.time(), tx)
            return tx

        if tx is not None and len(tx) == 0:
            # Endpoint worked but group has no sales
            print(f"[post_monitor] gid {group_id}: 0 tx returned (no sales or empty)", flush=True)
            _GROUP_SALES_CACHE[group_id] = (time.time(), [])
            return []

        # Endpoint 2: revenue summary (auth check)
        summary = _try_revenue_summary(group_id, cookie)
        if summary is not None:
            print(f"[post_monitor] gid {group_id}: revenue summary OK, but tx endpoint blocked", flush=True)
            # Cookie works, but transactions endpoint is blocked. Return empty.
            _GROUP_SALES_CACHE[group_id] = (time.time(), [])
            return []

        # Endpoint 3: payouts
        payouts = _try_payouts(group_id, cookie)
        if payouts is not None:
            print(f"[post_monitor] gid {group_id}: payouts OK (alt endpoint)", flush=True)
            _GROUP_SALES_CACHE[group_id] = (time.time(), [])
            return []

        # All endpoints failed for this cookie → try next
        _rotate_cookie()

    print(f"[post_monitor] gid {group_id}: all cookies failed", flush=True)
    _GROUP_SALES_CACHE[group_id] = (time.time(), [])
    return []


def fetch_my_sales(cookie, user_id, max_pages=4):
    """Fetch personal + group sales."""
    cookies = _all_cookies()
    if not cookies:
        return []

    all_sales = []
    cookie = cookies[0]

    # Personal
    if user_id:
        url = f"https://economy.roblox.com/v2/users/{user_id}/transactions?transactionType=Sale&limit=100"
        cursor = ""
        for _ in range(max_pages):
            u = f"{url}&cursor={cursor}" if cursor else url
            r = _get(u, cookie)
            if r is None or r.status_code != 200:
                break
            try:
                d = r.json()
            except Exception:
                break
            all_sales.extend(d.get("data") or [])
            cursor = d.get("nextPageCursor")
            if not cursor:
                break
            time.sleep(1.5)

    # Groups
    for gid in _group_ids():
        try:
            group_sales = fetch_group_sales(gid, max_pages=max_pages)
            all_sales.extend(group_sales)
        except Exception as e:
            print(f"[post_monitor] gid {gid} failed: {e}", flush=True)

    print(f"[post_monitor] total sales records: {len(all_sales)}", flush=True)
    return all_sales


# ──────────────────────────────────────────────────────────
# Transaction parsing
# ──────────────────────────────────────────────────────────
def _extract_tx_item_id(tx):
    v = tx.get("assetId") or tx.get("itemId")
    if v:
        return v
    item = tx.get("item")
    if isinstance(item, dict):
        v = item.get("id") or item.get("assetId")
        if v:
            return v
    v = tx.get("id")
    if v:
        return v
    return None


def _extract_tx_amount(tx):
    c = tx.get("currency")
    if isinstance(c, dict):
        return int(c.get("amount") or 0)
    v = tx.get("amount")
    if v:
        return int(v)
    return 0


def _extract_tx_created(tx):
    return tx.get("created") or tx.get("createdAt") or tx.get("createdUtc")


def _sales_for_item(sales_list, item_id, hours=24):
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


# ──────────────────────────────────────────────────────────
# Public fetchers
# ──────────────────────────────────────────────────────────
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
    headers = _headers(cookie)
    out = {"favs": 0, "price": 0, "name": None, "ok": False}
    r = _get(f"https://economy.roblox.com/v2/assets/{item_id}/details", cookie)
    if r and r.status_code == 200:
        try:
            d = r.json()
            out["name"] = (d.get("Name") or "")[:200]
            out["price"] = d.get("PriceInRobux") or 0
            out["ok"] = True
        except Exception:
            pass
    r = _get(f"https://catalog.roblox.com/v1/favorites/assets/{item_id}/count", cookie)
    if r and r.status_code == 200:
        try:
            out["favs"] = r.json() or 0
        except Exception:
            pass
    return out


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
                s24, r24 = _sales_for_item(sales_list, item_id, hours=24)
                s_all, _ = _sales_for_item(sales_list, item_id, hours=24 * 365)
                try:
                    cur.execute("""
                        INSERT INTO post_snapshots
                            (item_id, favorite_count, price, total_sales, sales_24h, revenue_24h)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (item_id, favs, price, s_all, s24, r24))
                except Exception:
                    pass
            except Exception as e:
                print(f"[post_monitor] item {item_id}: {e}", flush=True)

        conn.commit()
        return alerts
    finally:
        try: cur.close()
        except Exception: pass
        try: conn.close()
        except Exception: pass
