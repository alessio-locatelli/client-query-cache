from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest

from benchmarks.stream_cost.client import (
    BenchmarkClientTopologyConfig,
    WireCompressor,
    build_dedicated_client,
)
from benchmarks.stream_cost.compressor_preflight import verify_compressor_negotiation
from benchmarks.stream_cost.errors import BenchmarkSetupError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pymongo import MongoClient

    from tests.conftest import MongoDbUri

pytestmark = pytest.mark.integration


def _topology(compressor: WireCompressor) -> BenchmarkClientTopologyConfig:
    return BenchmarkClientTopologyConfig(
        tls_enabled=False,
        compressor=compressor,
        discovery_enabled=False,
        shared_connections=False,
    )


@pytest.fixture
def admin_client(mongodb_uri: MongoDbUri) -> Iterator[MongoClient[dict[str, Any]]]:
    with build_dedicated_client(mongodb_uri, _topology(WireCompressor.NONE)) as client:
        yield client


@pytest.mark.parametrize(
    "compressor",
    [WireCompressor.SNAPPY, WireCompressor.ZLIB, WireCompressor.ZSTD],
)
def test_verify_compressor_negotiation_accepts_each_negotiated_mode(
    mongodb_uri: MongoDbUri,
    admin_client: MongoClient[dict[str, Any]],
    compressor: WireCompressor,
) -> None:
    with build_dedicated_client(mongodb_uri, _topology(compressor)) as measured_client:
        preflight_result = verify_compressor_negotiation(
            measured_client,
            admin_client,
            compressor=compressor,
            database_name=f"preflight_{uuid.uuid4().hex}",
        )
    assert preflight_result.compressor is compressor
    assert preflight_result.counter_deltas[compressor.value] > 0


def test_verify_compressor_negotiation_accepts_an_uncompressed_connection(
    mongodb_uri: MongoDbUri,
    admin_client: MongoClient[dict[str, Any]],
) -> None:
    with build_dedicated_client(
        mongodb_uri, _topology(WireCompressor.NONE)
    ) as measured_client:
        preflight_result = verify_compressor_negotiation(
            measured_client,
            admin_client,
            compressor=WireCompressor.NONE,
            database_name=f"preflight_{uuid.uuid4().hex}",
        )
    assert preflight_result.compressor is WireCompressor.NONE
    assert all(delta == 0 for delta in preflight_result.counter_deltas.values())


def test_verify_compressor_negotiation_rejects_an_unnegotiated_mode(
    mongodb_uri: MongoDbUri,
    admin_client: MongoClient[dict[str, Any]],
) -> None:
    with (
        build_dedicated_client(
            mongodb_uri, _topology(WireCompressor.NONE)
        ) as uncompressed_client,
        pytest.raises(BenchmarkSetupError, match="fell back to no compression"),
    ):
        verify_compressor_negotiation(
            uncompressed_client,
            admin_client,
            compressor=WireCompressor.ZSTD,
            database_name=f"preflight_{uuid.uuid4().hex}",
        )
