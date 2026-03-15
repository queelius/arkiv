"""Temporal filtering helpers for time-bounded exports.

Provides ISO 8601 prefix arithmetic and SQL WHERE clause generation
for filtering records by timestamp ranges.
"""

import calendar
from typing import List, Optional, Tuple


def increment_iso_prefix(value: str) -> str:
    """Increment the least-significant component of an ISO 8601 prefix.

    Examples:
        "2024"       -> "2025"
        "2024-12"    -> "2025-01"
        "2024-12-31" -> "2025-01-01"

    Handles month/year rollover and leap years.
    """
    parts = value.split("-")

    if len(parts) == 1:
        # Year only
        return str(int(parts[0]) + 1)

    year = int(parts[0])
    month = int(parts[1])

    if len(parts) == 2:
        # Year-month: increment month, roll over at 12
        if month == 12:
            return f"{year + 1:04d}-01"
        return f"{year:04d}-{month + 1:02d}"

    # Year-month-day: increment day, roll over at month end
    day = int(parts[2])
    _, days_in_month = calendar.monthrange(year, month)

    if day >= days_in_month:
        # Roll to first of next month
        if month == 12:
            return f"{year + 1:04d}-01-01"
        return f"{year:04d}-{month + 1:02d}-01"

    return f"{year:04d}-{month:02d}-{day + 1:02d}"


def build_time_filter(
    since: Optional[str] = None, until: Optional[str] = None
) -> Tuple[str, List[str]]:
    """Build SQL WHERE clause for timestamp filtering.

    NULL timestamps always pass (permissive filtering).

    Args:
        since: Inclusive lower bound (records with timestamp >= since).
        until: Upper bound. If it contains 'T' (full timestamp), uses
               inclusive <= comparison. Otherwise treats as a date prefix
               and uses exclusive < with increment_iso_prefix().

    Returns:
        Tuple of (WHERE clause fragment, list of parameter values).
        Returns ("", []) if both arguments are None.
    """
    clauses = []
    params: List[str] = []

    if since is not None:
        clauses.append("(timestamp IS NULL OR timestamp >= ?)")
        params.append(since)

    if until is not None:
        if "T" in until:
            clauses.append("(timestamp IS NULL OR timestamp <= ?)")
            params.append(until)
        else:
            clauses.append("(timestamp IS NULL OR timestamp < ?)")
            params.append(increment_iso_prefix(until))

    if not clauses:
        return ("", [])

    return (" AND ".join(clauses), params)
