from datetime import UTC, datetime


def utc_now() -> datetime:
    """Server UTC time. All persisted timestamps come from here, never from a client clock."""
    return datetime.now(UTC)
