from datetime import UTC, datetime
from math import floor, log10

from mongo_client_cache._misc import dt_now


def test_dt_now() -> None:
    dt_with_milliseconds_precision = dt_now()
    microsecond = dt_with_milliseconds_precision.microsecond
    assert str(microsecond).endswith("000")
    assert floor(log10(microsecond)) + 1 == 6

    dt = datetime.now(UTC)
    assert dt_with_milliseconds_precision.hour == dt.hour
    assert dt_with_milliseconds_precision.minute == dt.minute
    if dt.second > dt_with_milliseconds_precision.second:
        assert dt.microsecond < dt_with_milliseconds_precision.microsecond
