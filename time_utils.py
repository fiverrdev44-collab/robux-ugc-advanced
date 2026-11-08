"""Explicit UTC time semantics for VANTA 73.

Two categories are deliberately separated:

* ``ensure_utc`` only converts values that already carry an offset. A naive
  value of unknown provenance returns ``None`` rather than being guessed.
* ``db_utc`` is for the known-legacy database columns whose writers used the
  repository's UTC session policy (``SET TimeZone = 'UTC'``). It attaches UTC
  to those naive values explicitly.

New code should use ``utc_now`` and aware timestamps. Do not use
``datetime.utcnow()``.
"""
from datetime import datetime, timedelta, timezone

UTC = timezone.utc


def utc_now():
    return datetime.now(UTC)


def ensure_utc(value, naive_is_utc=False):
    """Return an aware UTC datetime, or None when provenance is unknown."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        if not naive_is_utc:
            return None
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def db_utc(value):
    """Coerce a legacy UTC-session database timestamp to aware UTC."""
    return ensure_utc(value, naive_is_utc=True)


def utc_day(value):
    """UTC calendar date for an instant (date object)."""
    aware = ensure_utc(value, naive_is_utc=True)
    return aware.date() if aware else None


def age_days(value, now=None, naive_is_utc=True):
    """Age in days; naive input is only interpreted when provenance is known."""
    aware = ensure_utc(value, naive_is_utc=naive_is_utc)
    if aware is None:
        return None
    reference = ensure_utc(now) or utc_now()
    return (reference - aware).total_seconds() / 86400.0


def within_window(value, days, now=None, naive_is_utc=True):
    age = age_days(value, now=now, naive_is_utc=naive_is_utc)
    return age is not None and 0 <= age <= float(days)


def deadline_after(days, now=None):
    reference = ensure_utc(now) or utc_now()
    return reference + timedelta(days=float(days))
