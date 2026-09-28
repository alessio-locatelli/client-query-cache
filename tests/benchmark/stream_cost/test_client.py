from __future__ import annotations

import warnings
from typing import Any
from unittest import mock

import pytest

from benchmarks.stream_cost.client import (
    BenchmarkClientTopologyConfig,
    WireCompressor,
    build_dedicated_client,
)
from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)

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


def _topology(**overrides: object) -> BenchmarkClientTopologyConfig:
    defaults: dict[str, object] = {
        "tls_enabled": False,
        "compressor": WireCompressor.NONE,
        "discovery_enabled": False,
        "shared_connections": False,
    }
    defaults.update(overrides)
    return BenchmarkClientTopologyConfig(**defaults)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("config", "expected_kwargs"),
    [
        (
            _topology(),
            {
                "directConnection": True,
                "tls": False,
                "event_listeners": [],
            },
        ),
        (
            _topology(
                tls_enabled=True,
                compressor=WireCompressor.ZSTD,
                discovery_enabled=True,
            ),
            {
                "directConnection": False,
                "tls": True,
                "compressors": "zstd",
                "zlibCompressionLevel": -1,
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


@pytest.mark.parametrize(
    ("compressor", "expected_name"),
    [
        (WireCompressor.SNAPPY, "snappy"),
        (WireCompressor.ZLIB, "zlib"),
        (WireCompressor.ZSTD, "zstd"),
    ],
)
def test_build_dedicated_client_requests_each_compressor_mode(
    monkeypatch: pytest.MonkeyPatch,
    compressor: WireCompressor,
    expected_name: str,
) -> None:
    monkeypatch.setattr("benchmarks.stream_cost.client.MongoClient", _StubClient)
    build_dedicated_client("mongodb://example/", _topology(compressor=compressor))
    assert _StubClient.last_kwargs is not None
    assert _StubClient.last_kwargs["compressors"] == expected_name


def test_build_dedicated_client_passes_through_event_listeners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("benchmarks.stream_cost.client.MongoClient", _StubClient)
    listener = object()
    build_dedicated_client(
        "mongodb://example/", _topology(), event_listeners=[listener]
    )
    assert _StubClient.last_kwargs is not None
    assert _StubClient.last_kwargs["event_listeners"] == [listener]


def test_build_dedicated_client_rejects_shared_connections() -> None:
    config = _topology(shared_connections=True)
    with pytest.raises(BenchmarkConfigurationError, match="shared_connections"):
        build_dedicated_client("mongodb://example/", config)


def test_build_dedicated_client_fails_visibly_when_compressor_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _WarningStubClient(_StubClient):
        def __init__(self, uri: str, **kwargs: object) -> None:
            warnings.warn(
                "Wire protocol compression with zstandard is not available. "
                "The compression.zstd module is not available.",
                UserWarning,
                stacklevel=2,
            )
            super().__init__(uri, **kwargs)

    monkeypatch.setattr("benchmarks.stream_cost.client.MongoClient", _WarningStubClient)
    with pytest.raises(BenchmarkSetupError, match="silently fallen back"):
        build_dedicated_client(
            "mongodb://example/", _topology(compressor=WireCompressor.ZSTD)
        )


def test_build_dedicated_client_fails_visibly_when_pymongo_lacks_the_module() -> None:
    with (
        mock.patch("pymongo.compression_support._have_zstd", return_value=False),
        pytest.raises(BenchmarkSetupError, match="zstd"),
    ):
        build_dedicated_client(
            "mongodb://127.0.0.1:1/", _topology(compressor=WireCompressor.ZSTD)
        )
