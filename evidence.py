"""evidence.py — shared, traceable evidence records.

Every analytical number should be representable as an Evidence record so the
bot can separate observed facts from interpretations and mark missing/stale
data instead of silently reporting zero.
"""
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone

VALIDITY = {"observed", "missing", "stale", "partial", "estimated", "inferred"}
UNITS = {"count", "robux", "percent", "ratio", "days", "rank", "score", "text"}


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Evidence:
    metric: str
    value: object
    unit: str
    source: str
    observed_at: str = field(default_factory=utc_now_iso)
    asset_id: int | None = None
    category: str | None = None
    window: dict | None = None
    coverage: dict | None = None
    validity: str = "observed"
    note: str = ""

    def __post_init__(self):
        if self.unit not in UNITS:
            raise ValueError(f"unknown unit: {self.unit}")
        if self.validity not in VALIDITY:
            raise ValueError(f"unknown validity: {self.validity}")

    def to_dict(self):
        return asdict(self)

    def line(self):
        """Compact one-line rendering for prompts and logs."""
        mark = "" if self.validity == "observed" else f" [{self.validity}]"
        win = ""
        if self.window:
            win = f" ({self.window.get('start')}..{self.window.get('end_exclusive')})"
        return f"{self.metric}={self.value}{self.unit}{win} <- {self.source}{mark}"


def observed(metric, value, unit, source, **kw):
    return Evidence(metric, value, unit, source, **kw)


def missing(metric, unit, source, reason=""):
    return Evidence(metric, None, unit, source, validity="missing", note=reason)


def stale(metric, value, unit, source, observed_at, reason=""):
    return Evidence(metric, value, unit, source, observed_at=observed_at,
                    validity="stale", note=reason)


def partial(metric, value, unit, source, coverage=None, note=""):
    return Evidence(metric, value, unit, source, coverage=coverage,
                    validity="partial", note=note)


def numeric(evidence, expected_metric=None):
    """Return the numeric value only when the record is a valid number."""
    if expected_metric and evidence.metric != expected_metric:
        raise ValueError(
            f"claim metric mismatch: {evidence.metric} != {expected_metric}")
    if evidence.validity == "missing" or evidence.value is None:
        return None
    if not isinstance(evidence.value, (int, float)):
        raise ValueError("non-numeric evidence used as a number")
    return evidence.value
