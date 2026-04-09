"""Temporal filtering helpers for time-bounded exports.

Provides ISO 8601 prefix arithmetic and SQL WHERE clause generation
for filtering records by timestamp ranges.
"""

import calendar
import re
from typing import List, Optional, Tuple

# YYYY, YYYY-MM, or YYYY-MM-DD
_ISO_PREFIX_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")


def _parse_iso_prefix(value: str) -> Tuple[int, Optional[int], Optional[int]]:
    """Parse a valid ISO 8601 date prefix into (year, month, day).

    Raises ValueError on any malformed input. month and day are None
    if the prefix is less precise.
    """
    if not isinstance(value, str):
        raise ValueError(f"date prefix must be a string, got {type(value).__name__}")
    match = _ISO_PREFIX_RE.match(value)
    if not match:
        raise ValueError(
            f"invalid ISO 8601 date prefix: {value!r} "
            "(expected YYYY, YYYY-MM, or YYYY-MM-DD)"
        )
    year = int(match.group(1))
    month = int(match.group(2)) if match.group(2) else None
    day = int(match.group(3)) if match.group(3) else None
    if month is not None and not (1 <= month <= 12):
        raise ValueError(f"invalid month in {value!r}: {month}")
    if day is not None:
        _, days_in_month = calendar.monthrange(year, month)
        if not (1 <= day <= days_in_month):
            raise ValueError(
                f"invalid day in {value!r}: {day} "
                f"(month {month} has {days_in_month} days)"
            )
    return (year, month, day)


def increment_iso_prefix(value: str) -> str:
    """Increment the least-significant component of an ISO 8601 prefix.

    Examples:
        "2024"       -> "2025"
        "2024-12"    -> "2025-01"
        "2024-12-31" -> "2025-01-01"

    Handles month/year rollover and leap years. Raises ValueError on
    malformed input.
    """
    year, month, day = _parse_iso_prefix(value)

    if month is None:
        # Year only
        return str(year + 1)

    if day is None:
        # Year-month: increment month, roll over at 12
        if month == 12:
            return f"{year + 1:04d}-01"
        return f"{year:04d}-{month + 1:02d}"

    # Year-month-day: increment day, roll over at month end
    _, days_in_month = calendar.monthrange(year, month)

    if day >= days_in_month:
        if month == 12:
            return f"{year + 1:04d}-01-01"
        return f"{year:04d}-{month + 1:02d}-01"

    return f"{year:04d}-{month:02d}-{day + 1:02d}"


def _validate_time_arg(name: str, value: str) -> None:
    """Validate a --since/--until value. Full ISO 8601 timestamps (with T)
    are accepted as-is; date prefixes are validated via _parse_iso_prefix."""
    if "T" in value:
        # Full timestamp: accept any non-empty string, SQLite will compare
        # lexicographically. We do a minimal sanity check: at least YYYY prefix.
        if not re.match(r"^\d{4}", value):
            raise ValueError(
                f"{name} must start with a 4-digit year: {value!r}"
            )
    else:
        # Date prefix: full validation.
        try:
            _parse_iso_prefix(value)
        except ValueError as e:
            raise ValueError(f"{name}: {e}") from None


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
        _validate_time_arg("since", since)
        clauses.append("(timestamp IS NULL OR timestamp >= ?)")
        params.append(since)

    if until is not None:
        _validate_time_arg("until", until)
        if "T" in until:
            clauses.append("(timestamp IS NULL OR timestamp <= ?)")
            params.append(until)
        else:
            clauses.append("(timestamp IS NULL OR timestamp < ?)")
            params.append(increment_iso_prefix(until))

    if not clauses:
        return ("", [])

    return (" AND ".join(clauses), params)
