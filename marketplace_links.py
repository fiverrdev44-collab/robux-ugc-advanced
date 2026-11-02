"""marketplace_links.py — Roblox Marketplace Links attribution.

Tracks per-link traffic and purchases so the bot can answer which promotion
brought buyers versus clicks without purchases. Schema creation is idempotent
and intended to run through the migration flag, not on every bot start.
"""
import csv

SCHEMA = """
create table if not exists marketplace_links (
    link_id text primary key,
    item_id bigint,
    source text,
    clicks integer not null default 0,
    unique_clickers integer not null default 0,
    purchases integer not null default 0,
    spend_robux integer not null default 0,
    observed_at timestamptz default now(),
    raw jsonb
);
create index if not exists idx_marketplace_links_item
    on marketplace_links (item_id);
"""

FIELDS = ("link_id", "item_id", "source", "clicks", "unique_clickers",
          "purchases", "spend_robux")


def ensure_schema(cur, conn=None):
    cur.execute(SCHEMA)
    if conn is not None:
        conn.commit()


def _int(value, default=0):
    try:
        return int(float(str(value).strip() or default))
    except (TypeError, ValueError):
        return default


def parse_csv(path_or_file):
    """Parse a Marketplace Links CSV into normalized rows."""
    f = open(path_or_file, newline="", encoding="utf-8-sig") \
        if isinstance(path_or_file, (str, bytes)) else path_or_file
    rows = []
    for raw in csv.DictReader(f):
        row = {k: (raw.get(k) or "").strip() for k in FIELDS}
        if not row["link_id"]:
            continue
        row["item_id"] = _int(row["item_id"], None)
        for k in ("clicks", "unique_clickers", "purchases", "spend_robux"):
            row[k] = _int(row[k])
        rows.append(row)
    if f is not path_or_file:
        f.close()
    return rows


def ingest_rows(cur, rows):
    count = 0
    for r in rows:
        cur.execute("""
            insert into marketplace_links
              (link_id, item_id, source, clicks, unique_clickers, purchases,
               spend_robux, observed_at, raw)
            values (%s, %s, %s, %s, %s, %s, %s, now(), %s::jsonb)
            on conflict (link_id) do update set
                item_id = excluded.item_id,
                source = excluded.source,
                clicks = excluded.clicks,
                unique_clickers = excluded.unique_clickers,
                purchases = excluded.purchases,
                spend_robux = excluded.spend_robux,
                observed_at = now(),
                raw = excluded.raw
        """, (r["link_id"], r["item_id"], r["source"], r["clicks"],
              r["unique_clickers"], r["purchases"], r["spend_robux"],
              str(r)))
        count += 1
    return count


def ingest_csv(cur, path_or_file):
    return ingest_rows(cur, parse_csv(path_or_file))


def summary(cur):
    cur.execute("""
        select link_id, item_id, source, clicks, unique_clickers,
               purchases, spend_robux
        from marketplace_links
        order by purchases desc, clicks desc
    """)
    rows = [{
        "link_id": r[0], "item_id": r[1], "source": r[2], "clicks": r[3],
        "unique_clickers": r[4], "purchases": r[5], "spend_robux": r[6],
    } for r in cur.fetchall()]
    buyers = [r for r in rows if r["purchases"] > 0]
    click_only = [r for r in rows if r["clicks"] > 0 and r["purchases"] == 0]
    return {
        "links": len(rows),
        "buyers": buyers,
        "clicks_without_purchase": click_only,
        "totals": {
            "clicks": sum(r["clicks"] for r in rows),
            "purchases": sum(r["purchases"] for r in rows),
            "spend_robux": sum(r["spend_robux"] for r in rows),
        },
        "conversion": (
            round(sum(r["purchases"] for r in rows) /
                  max(sum(r["clicks"] for r in rows), 1), 3)),
    }


def format_summary(data):
    lines = [f"**Marketplace Links:** {data['links']} links · "
             f"{data['totals']['clicks']} clicks · "
             f"{data['totals']['purchases']} purchases · "
             f"conversion {data['conversion']:.1%}"]
    if data["buyers"]:
        lines.append("\n**Brought buyers:**")
        for r in data["buyers"][:5]:
            lines.append(f"- `{r['link_id']}` — {r['purchases']} purchases / "
                         f"{r['clicks']} clicks")
    if data["clicks_without_purchase"]:
        lines.append("\n**Clicks without purchases:**")
        for r in data["clicks_without_purchase"][:5]:
            lines.append(f"- `{r['link_id']}` — {r['clicks']} clicks, 0 purchases")
    if not data["links"]:
        lines.append("No Marketplace Links data ingested yet.")
    return "\n".join(lines)
