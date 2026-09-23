from __future__ import annotations

from typing import Any

import pytest

from benchmarks.stream_cost.client import (
    BenchmarkClientTopologyConfig,
    build_dedicated_client,
)
from benchmarks.stream_cost.errors import BenchmarkConfigurationError

pytestmark = pytest.mark.unit


class _StubClient:
    __slots__ = ()
    last_uri: str | None = None
    last_kwargs: dict[str, Any] | None = None

    def __class_getitem__(cls, item: object) -> type[_StubClient]:
        return cls

    def __init__(self, uri: str, **kwargs: object) -> None:
        type(self).last_uri = uri
        type(self).last_kwargs = kwargs


@pytest.mark.parametrize(
    ("config", "expected_kwargs"),
    [
        (
            BenchmarkClientTopologyConfig(
                tls_enabled=False,
                compression_enabled=False,
                discovery_enabled=False,
                shared_connections=False,
            ),
            {
                "directConnection": True,
                "tls": False,
                "event_listeners": [],
            },
        ),
        (
            BenchmarkClientTopologyConfig(
                tls_enabled=True,
                compression_enabled=True,
                discovery_enabled=True,
                shared_connections=False,
            ),
            {
                "directConnection": False,
                "tls": True,
                "compressors": "zstd",
                "event_listeners": [],
            },
        ),
    ],
)
def test_build_dedicated_client_passes_expected_kwargs(
    monkeypatch: pytest.MonkeyPatch,
    config: BenchmarkClientTopologyConfig,
    expected_kwargs: dict[str, Any],
) -> None:
    monkeypatch.setattr("benchmarks.stream_cost.client.MongoClient", _StubClient)
    build_dedicated_client("mongodb://example/", config)
    assert _StubClient.last_uri == "mongodb://example/"
    assert _StubClient.last_kwargs == expected_kwargs


def test_build_dedicated_client_passes_through_event_listeners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("benchmarks.stream_cost.client.MongoClient", _StubClient)
    listener = object()
    config = BenchmarkClientTopologyConfig(
        tls_enabled=False,
        compression_enabled=False,
        discovery_enabled=False,
        shared_connections=False,
    )
    build_dedicated_client("mongodb://example/", config, event_listeners=[listener])
    assert _StubClient.last_kwargs is not None
    assert _StubClient.last_kwargs["event_listeners"] == [listener]


def test_build_dedicated_client_rejects_shared_connections() -> None:
    config = BenchmarkClientTopologyConfig(
        tls_enabled=False,
        compression_enabled=False,
        discovery_enabled=False,
        shared_connections=True,
    )
    with pytest.raises(BenchmarkConfigurationError, match="shared_connections"):
        build_dedicated_client("mongodb://example/", config)
