from __future__ import annotations

from datetime import datetime, timezone


def parse_ts(value: str) -> datetime:
    """Parse an ISO-8601 timestamp (trailing 'Z' ok) into an aware UTC datetime."""
    v = (value or "").strip()
    if not v:
        raise ValueError("空时间戳")
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def norm_ts(value: str) -> str:
    """Normalize any accepted ISO-8601 input to canonical '...Z' form."""
    return fmt_ts(parse_ts(value))


def is_valid_ts(value: str) -> bool:
    try:
        parse_ts(value)
        return True
    except (ValueError, TypeError):
        return False
