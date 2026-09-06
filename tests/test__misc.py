from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from mongo_client_cache import _misc

pytestmark = pytest.mark.unit


def test_dt_now(monkeypatch: pytest.MonkeyPatch) -> None:
    current_datetime = datetime(2026, 9, 6, 12, 34, 56, 4_567, tzinfo=UTC)
    monkeypatch.setattr(
        _misc,
        "datetime",
        Mock(now=Mock(return_value=current_datetime)),
    )

    expected_datetime = current_datetime.replace(tzinfo=None, microsecond=4_000)
    assert _misc.dt_now() == expected_datetime
