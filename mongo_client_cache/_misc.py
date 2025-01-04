from datetime import UTC, datetime


def dt_milliseconds_precision() -> datetime:
    dt = datetime.now(UTC)
    return dt.replace(tzinfo=None, microsecond=round(dt.microsecond, 3))
