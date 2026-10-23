"""search_visibility.py — sampled, timestamped marketplace search observations.

This records what the public catalog search API returned for a query. It is
not a hidden ranking score, and it is not browser-UI personalization.
"""
import json
import os
import re
import time

import requests

SEARCH_URL = "https://catalog.roblox.com/v1/search/items/details"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}
PAGE_LIMIT = 30
DELAY = float(os.getenv("VISIBILITY_DELAY", "1.0"))
MAX_PAGES = int(os.getenv("VISIBILITY_MAX_PAGES", "3"))


def normalize_query(query):
    return re.sub(r"\s+", " ", (query or "").strip().lower())


def ensure_query(cur, query, family=None, source="manual", weight=1.0):
    q = normalize_query(query)
    if not q:
        return None
    cur.execute("""
        INSERT INTO search_queries (query, family, source, weight)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (query) DO UPDATE SET
            family = COALESCE(EXCLUDED.family, search_queries.family),
            updated_at = now()
        RETURNING id
    """, (q, family, source, weight))
    return cur.fetchone()[0]


def seed_queries(cur, limit=50):
    """Seed from live suggestions, highest volume first."""
    cur.execute("""
        SELECT suggestion, max(search_volume) AS vol
        FROM search_suggestions
        WHERE seed_keyword IS DISTINCT FROM '__db_mined__'
          AND suggestion IS NOT NULL
        GROUP BY suggestion
        ORDER BY vol DESC NULLS LAST
        LIMIT %s
    """, (int(limit),))
    added = 0
    for suggestion, _vol in cur.fetchall():
        if ensure_query(cur, suggestion, source="suggestions"):
            added += 1
    return added


def _fetch_query(session, query, max_pages=MAX_PAGES):
    rows = []
    pages = 0
    cursor = None
    error = None
    status = "completed"
    while pages < max_pages:
        params = {
            "Keyword": query,
            "Limit": PAGE_LIMIT,
            "SortType": "Relevance",
        }
        if cursor:
            params["Cursor"] = cursor
        response = None
        for attempt in range(3):
            try:
                response = session.get(SEARCH_URL, params=params,
                                       headers=HEADERS, timeout=15)
            except Exception as e:
                error = f"{type(e).__name__}"
                response = None
            if response is not None and response.status_code == 200:
                break
            if response is not None and response.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            if response is not None:
                error = f"HTTP {response.status_code}"
                break
            time.sleep(2 ** attempt)
        if response is None or response.status_code != 200:
            status = "failed" if not rows else "partial"
            break
        try:
            data = response.json()
        except Exception:
            error = "bad JSON"
            status = "failed" if not rows else "partial"
            break
        for item in data.get("data") or []:
            rows.append((pages + 1, item))
        pages += 1
        cursor = data.get("nextPageCursor")
        if not cursor:
            break
        time.sleep(DELAY)
    return rows, pages, status, error


def collect(cur, limit=20, max_pages=MAX_PAGES):
    cur.execute("""
        SELECT q.id, q.query
        FROM search_queries q
        WHERE q.enabled IS TRUE
          AND NOT EXISTS (
              SELECT 1 FROM search_runs r
              WHERE r.query_id = q.id
                AND r.started_at > now() - interval '6 hours'
          )
        ORDER BY q.weight DESC, q.id
        LIMIT %s
    """, (int(limit),))
    queries = cur.fetchall()
    session = requests.Session()
    completed = 0
    for query_id, query in queries:
        cur.execute("""
            INSERT INTO search_runs
              (query_id, status, endpoint, sort_type, filters, source)
            VALUES (%s, 'running', %s, 'Relevance', %s::jsonb, 'catalog_api')
            RETURNING id
        """, (query_id, SEARCH_URL,
              json.dumps({"keyword": query, "limit": PAGE_LIMIT})))
        run_id = cur.fetchone()[0]
        rows, pages, status, error = _fetch_query(
            session, query, max_pages=max_pages
        )
        seen = 0
        for position, (page, item) in enumerate(rows, 1):
            item_id = item.get("id")
            if not item_id:
                continue
            cur.execute("""
                INSERT INTO search_observations
                  (run_id, query_id, item_id, position, page, name,
                   favorite_count, price, is_exact, observed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (run_id, item_id) DO NOTHING
            """, (
                run_id, query_id, item_id, position, page,
                (item.get("name") or "")[:500],
                item.get("favoriteCount"),
                item.get("price"),
                (item.get("name") or "").strip().lower()
                == normalize_query(query),
            ))
            seen += 1
        cur.execute("""
            UPDATE search_runs SET
                finished_at = now(), status = %s, pages = %s,
                results_seen = %s, error = %s
            WHERE id = %s
        """, (status, pages, seen, error, run_id))
        completed += 1
        time.sleep(DELAY)
    return completed


def coverage(cur):
    cur.execute("SELECT count(*) FROM search_queries WHERE enabled IS TRUE")
    queries = cur.fetchone()[0] or 0
    cur.execute("SELECT count(*) FROM search_runs")
    runs = cur.fetchone()[0] or 0
    cur.execute("SELECT count(*) FROM search_observations")
    observations = cur.fetchone()[0] or 0
    cur.execute("SELECT max(finished_at) FROM search_runs")
    last = cur.fetchone()[0]
    cur.execute("""
        SELECT count(*) FROM search_queries q
        WHERE q.enabled IS TRUE AND NOT EXISTS (
            SELECT 1 FROM search_runs r
            WHERE r.query_id = q.id
              AND r.started_at > now() - interval '24 hours'
        )
    """)
    stale = cur.fetchone()[0] or 0
    return {
        "queries": int(queries),
        "runs": int(runs),
        "observations": int(observations),
        "last_run": last,
        "stale_queries": int(stale),
    }


def format_coverage(cov):
    lines = [
        "# 🔎 SEARCH VISIBILITY",
        f"• Enabled queries: **{cov['queries']}**",
        f"• Runs stored: **{cov['runs']}** · observations: "
        f"**{cov['observations']:,}**",
        f"• Last run: **{cov['last_run'] or 'never'}**",
        f"• Queries stale >24h: **{cov['stale_queries']}**",
        "",
        "_Observed catalog-API results. Not a hidden ranking score, "
        "impressions, or CTR._",
    ]
    return "\n".join(lines)
