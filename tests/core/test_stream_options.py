from __future__ import annotations

from typing import cast
from unittest.mock import Mock

import pytest

from client_query_cache._core.errors import CacheConfigurationError
from client_query_cache._core.stream_options import (
    MAX_AWAIT_TIME_MS,
    validate_max_await_time_ms,
)
from client_query_cache._types import MaxAwaitTimeMs
from client_query_cache.asynchronous.manager import CacheManager as AsyncCacheManager
from client_query_cache.synchronous.manager import CacheManager

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "manager_type", [CacheManager, AsyncCacheManager], ids=["sync", "async"]
)
@pytest.mark.parametrize(
    "invalid",
    [True, False, None, 0, -1, 1.5, "1000", MAX_AWAIT_TIME_MS + 1],
    ids=["true", "false", "none", "zero", "negative", "float", "string", "too-large"],
)
def test_rejects_invalid_await_time_before_using_client(
    manager_type: type[
        CacheManager[dict[str, object]] | AsyncCacheManager[dict[str, object]]
    ],
    invalid: object,
) -> None:
    client = Mock()
    with pytest.raises(CacheConfigurationError, match="max_await_time_ms"):
        manager_type(client, max_await_time_ms=cast("int", invalid))
    assert client.mock_calls == []


@pytest.mark.parametrize(
    "valid",
    [1, 1_000, 5_000, MAX_AWAIT_TIME_MS],
    ids=["minimum", "baseline", "larger", "maximum"],
)
def test_accepts_supported_await_time(valid: MaxAwaitTimeMs) -> None:
    validate_max_await_time_ms(valid)
