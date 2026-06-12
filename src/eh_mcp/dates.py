"""Small date helpers for the KPI computations.

Employment Hero returns dates as ISO date or datetime strings. These parse
defensively (returning None on anything unparseable rather than raising) so a
single malformed record cannot crash a whole aggregate.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime


def parse_date(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip()
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        return None


def add_months(d: date, months: int) -> date:
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def days_between(start: date, end: date) -> int:
    return (end - start).days


def add_days(d: date, n: int) -> date:
    return date.fromordinal(d.toordinal() + n)


def overlap_days(a_start: date, a_end: date, b_start: date, b_end: date) -> int:
    """Inclusive day overlap between two date ranges (0 if disjoint)."""
    lo = max(a_start, b_start)
    hi = min(a_end, b_end)
    return max(0, (hi - lo).days + 1)
