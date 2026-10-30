"""item_resolver.py — canonical sales-to-asset identity.

Names are mutable attributes. Asset IDs are identity. This module keeps an
explicit alias table with provenance instead of silently joining sale names to
catalog titles, and it never merges two creators' products by title alone.

Resolution states:
  confirmed  — creator-confirmed or verified transaction export
  candidate  — normalised/exact name match, not independently verified
  ambiguous  — a name maps to more than one catalog asset
  unresolved — no mapping

Only `confirmed` rows may be treated as the same product by reports.
"""
import re

# Creator-confirmed on 2026-10-30: these two names are ONE product.
# Historical buckets: 108 records / 3,142 R$ + 31 records / 903 R$ = 139 / 4,045.
CONFIRMED_ALIASES = {
    "cute beanie w paws": (
        130928797494687,
        "creator-confirmed rename to Cute Kitty Fluffy Beanie (2026-10-30)",
    ),
    "cute kitty fluffy beanie": (
        130928797494687,
        "creator-confirmed rename from Cute Beanie w paws (2026-10-30)",
    ),
}

# Strong but unverified: ledger asset for the same title; sales predate the
# recorded ledger launch date, so this stays a candidate, not confirmed.
CANDIDATE_ALIASES = {
    "smooth 360 flip rizz": (
        92364796546749,
        "title match to launch_ledger asset; sales start 2026-07-09, "
        "ledger launched_at 2026-10-19",
    ),
    "name smooth 360 flip rizz": (
        92364796546749,
        "sales-channel prefix variant of Smooth 360 flip Rizz",
    ),
}

_EMOJI_OR_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_PREFIX = re.compile(r"^\s*name\s*:\s*", re.IGNORECASE)
_SPACES = re.compile(r"\s+")

SCHEMA = """
create table if not exists sales_name_aliases (
    alias text primary key,
    item_id bigint not null,
    status text not null,
    evidence_source text not null,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);
create index if not exists idx_sales_alias_item
    on sales_name_aliases (item_id);
"""


def normalize_name(name):
    s = (name or "").strip().lower()
    s = _PREFIX.sub("", s)
    s = _EMOJI_OR_PUNCT.sub(" ", s)
    return _SPACES.sub(" ", s).strip()


def ensure_schema(cur, conn=None):
    cur.execute(SCHEMA)
    for alias, (item_id, source) in CONFIRMED_ALIASES.items():
        cur.execute(
            """insert into sales_name_aliases
                   (alias, item_id, status, evidence_source)
               values (%s, %s, 'confirmed', %s)
               on conflict (alias) do nothing""",
            (alias, item_id, source),
        )
    for alias, (item_id, source) in CANDIDATE_ALIASES.items():
        cur.execute(
            """insert into sales_name_aliases
                   (alias, item_id, status, evidence_source)
               values (%s, %s, 'candidate', %s)
               on conflict (alias) do nothing""",
            (alias, item_id, source),
        )
    if conn is not None:
        conn.commit()


def resolve_name(cur, name, use_cache=None):
    """Resolve a sale name to an asset. Returns a dict, never raises on no match."""
    alias = normalize_name(name)
    if use_cache is not None and alias in use_cache:
        return use_cache[alias]

    cur.execute(
        "select item_id, status, evidence_source from sales_name_aliases where alias = %s",
        (alias,),
    )
    row = cur.fetchone()
    if row:
        out = {"alias": alias, "item_id": row[0], "status": row[1],
               "source": row[2]}
    else:
        cur.execute(
            "select id from items where lower(trim(name)) = lower(trim(%s))",
            (name or "",),
        )
        ids = {r[0] for r in cur.fetchall()}
        if len(ids) == 1:
            out = {"alias": alias, "item_id": ids.pop(), "status": "candidate",
                   "source": "exact catalog title"}
        elif len(ids) > 1:
            out = {"alias": alias, "item_id": None, "status": "ambiguous",
                   "source": f"{len(ids)} catalog items share this title"}
        else:
            out = {"alias": alias, "item_id": None, "status": "unresolved",
                   "source": "no alias and no exact title"}

    if use_cache is not None:
        use_cache[alias] = out
    return out


def sales_breakdown(cur, start, end):
    """Aggregate my_sales into canonical products plus explicit unresolved rows.

    Totals always cover every record: mapped + unresolved = all.
    """
    cur.execute(
        """select item_name, count(*), coalesce(sum(amount_robux),0),
                  max(sale_time)
           from my_sales
           where sale_date >= %s and sale_date < %s
           group by item_name""",
        (start, end),
    )
    rows = cur.fetchall()

    cache = {}
    groups = {}
    totals = {"records": 0, "robux": 0, "mapped_records": 0, "mapped_robux": 0,
              "unresolved_records": 0, "unresolved_robux": 0,
              "ambiguous_records": 0, "ambiguous_robux": 0}

    for name, records, robux, last_sale in rows:
        records = int(records or 0)
        robux = int(robux or 0)
        res = resolve_name(cur, name, use_cache=cache)
        totals["records"] += records
        totals["robux"] += robux

        if res["item_id"]:
            key = ("item", int(res["item_id"]))
            status = res["status"]
        else:
            key = ("unresolved", res["alias"] or (name or "").lower())
            status = res["status"]

        g = groups.get(key)
        if not g:
            g = {"item_id": res["item_id"], "status": status,
                 "records": 0, "robux": 0, "last_sale": last_sale,
                 "aliases": []}
            groups[key] = g
        g["records"] += records
        g["robux"] += robux
        if last_sale and (g["last_sale"] is None or last_sale > g["last_sale"]):
            g["last_sale"] = last_sale
        if name not in g["aliases"]:
            g["aliases"].append(name)

        if not res["item_id"]:
            if res["status"] == "ambiguous":
                totals["ambiguous_records"] += records
                totals["ambiguous_robux"] += robux
            else:
                totals["unresolved_records"] += records
                totals["unresolved_robux"] += robux
        else:
            totals["mapped_records"] += records
            totals["mapped_robux"] += robux

    ids = [g["item_id"] for g in groups.values() if g["item_id"]]
    titles = {}
    if ids:
        cur.execute("select id, name from items where id = any(%s)", (ids,))
        titles = {r[0]: r[1] for r in cur.fetchall()}

    items = []
    for g in groups.values():
        canonical = titles.get(g["item_id"]) or (g["aliases"][0] if g["aliases"] else "?")
        g["name"] = canonical
        items.append(g)
    items.sort(key=lambda x: x["robux"], reverse=True)
    return {"totals": totals, "items": items, "window": (str(start), str(end))}
