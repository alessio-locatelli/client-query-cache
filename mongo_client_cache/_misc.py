from datetime import UTC, datetime


def dt_now() -> datetime:
    """
    Use milliseconds precision to be compatible with MongoDB.
    Otherwise we can get a wrong order of dates, such as:
        1. Local: datetime.datetime(2025, 1, 6, 7, 55, 12, 214169, tzinfo=datetime.timezone.utc)
        2. MongoDB: datetime.datetime(2025, 1, 6, 7, 55, 12, 214000, tzinfo=datetime.timezone.utc)
    Where (2) happened after (1), but MongoDB strips microseconds and later the client can
    have a wrong assumption that (2) happened before (1).
    """
    dt = datetime.now(UTC)
    return dt.replace(tzinfo=None, microsecond=round(dt.microsecond, 3))
