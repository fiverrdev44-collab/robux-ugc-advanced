"""reporting.py — one definition of reporting windows and money semantics.

Windows are UTC calendar dates with an inclusive start and exclusive end.
`anchor` is the current UTC date on the database, so the bot and SQL agree.

For `days=7` on 2026-10-30 the window is 2026-10-24..2026-10-31 (exclusive),
i.e. seven full UTC dates and a partial current day. This matches the frozen
audit fixtures (Oct 24-30: 27 records / 422 Robux).
"""
from datetime import date, timedelta

# amount_robux comes from parsed Discord embeds. Its meaning (buyer price vs
# creator proceeds vs something else) has not been verified against Roblox
# transaction exports, so reports must not call it revenue or profit.
AMOUNT_SEMANTICS = "recorded_amount_unverified"


def window_bounds(cur, days, anchor=None):
    """Return (start_date, end_date_exclusive, anchor_date) in UTC."""
    days = max(1, int(days))
    if anchor is None:
        cur.execute("select (now() at time zone 'utc')::date")
        anchor = cur.fetchone()[0]
    if isinstance(anchor, str):
        anchor = date.fromisoformat(anchor)
    start = anchor - timedelta(days=days - 1)
    end = anchor + timedelta(days=1)
    return start, end, anchor


def describe_window(start, end, anchor):
    partial = anchor == (end - timedelta(days=1))
    return {
        "start": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "anchor": anchor.isoformat(),
        "days": (end - start).days,
        "today_partial": partial,
        "timezone": "UTC",
    }
