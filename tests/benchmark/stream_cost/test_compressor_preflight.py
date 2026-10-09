from __future__ import annotations

from typing import Any

import pytest

from benchmarks.stream_cost.client import WireCompressor
from benchmarks.stream_cost.compressor_preflight import (
    PREFLIGHT_PAYLOAD_BYTES,
    CompressorPreflightResult,
    verify_compressor_negotiation,
)
from benchmarks.stream_cost.errors import BenchmarkSetupError
from client_query_cache._types import NonNegativeInt

pytestmark = pytest.mark.unit

_Counters = dict[str, dict[str, dict[str, NonNegativeInt]]]

_BACKGROUND_TRAFFIC_BYTES = 512

_ZERO_COUNTERS: _Counters = {
    name: {"compressor": {"bytesIn": 0}, "decompressor": {"bytesIn": 0}}
    for name in ("snappy", "zlib", "zstd")
}


def _counters(**advanced: NonNegativeInt) -> _Counters:
    counters: _Counters = {
        name: {"compressor": {"bytesIn": 0}, "decompressor": {"bytesIn": 0}}
        for name in ("snappy", "zlib", "zstd")
    }
    for name, delta in advanced.items():
        counters[name] = {
            "compressor": {"bytesIn": delta},
            "decompressor": {"bytesIn": 0},
        }
    return counters


class _FakeCollection:
    __slots__ = ("dropped",)

    def __init__(self) -> None:
        self.dropped = 0

    def drop(self) -> None:
        self.dropped += 1

    @staticmethod
    def insert_many(documents: list[dict[str, object]]) -> None:
        del documents

    @staticmethod
    def find(query: dict[str, object]) -> list[object]:
        del query
        return []


class _FakeDatabase:
    __slots__ = ("_collections",)

    def __init__(self) -> None:
        self._collections: dict[str, _FakeCollection] = {}

    def __getitem__(self, name: str) -> _FakeCollection:
        return self._collections.setdefault(name, _FakeCollection())


class _FakeMeasuredClient:
    __slots__ = ("_databases",)

    def __init__(self) -> None:
        self._databases: dict[str, _FakeDatabase] = {}

    def __getitem__(self, name: str) -> _FakeDatabase:
        return self._databases.setdefault(name, _FakeDatabase())


class _FakeAdmin:
    __slots__ = ("_responses",)

    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._responses = iter(responses)

    def command(self, name: str) -> dict[str, object]:
        assert name == "serverStatus"
        return next(self._responses)


class _FakeAdminClient:
    __slots__ = ("admin",)

    def __init__(self, *counter_snapshots: _Counters) -> None:
        self.admin = _FakeAdmin(
            [{"network": {"compression": snapshot}} for snapshot in counter_snapshots]
        )


def _run(
    compressor: WireCompressor, before: _Counters, after: _Counters
) -> tuple[CompressorPreflightResult, _FakeCollection]:
    measured_client: Any = _FakeMeasuredClient()
    admin_client: Any = _FakeAdminClient(before, after)
    preflight_result = verify_compressor_negotiation(
        measured_client,
        admin_client,
        compressor=compressor,
        database_name="preflight_db",
    )
    collection = measured_client["preflight_db"]["compressor_preflight"]
    return preflight_result, collection


@pytest.mark.parametrize(
    "compressor",
    [WireCompressor.SNAPPY, WireCompressor.ZLIB, WireCompressor.ZSTD],
)
@pytest.mark.parametrize(
    "background",
    [{}, {"snappy": _BACKGROUND_TRAFFIC_BYTES, "zlib": _BACKGROUND_TRAFFIC_BYTES}],
    ids=["quiet_server", "background_traffic"],
)
def test_verify_compressor_negotiation_accepts_a_clean_match(
    compressor: WireCompressor, background: dict[str, NonNegativeInt]
) -> None:
    advanced = {**background, compressor.value: PREFLIGHT_PAYLOAD_BYTES}
    preflight_result, collection = _run(
        compressor, _ZERO_COUNTERS, _counters(**advanced)
    )
    assert preflight_result.compressor is compressor
    assert preflight_result.counter_deltas[compressor.value] == PREFLIGHT_PAYLOAD_BYTES
    assert collection.dropped == 2


@pytest.mark.parametrize(
    "after",
    [_ZERO_COUNTERS, _counters(snappy=_BACKGROUND_TRAFFIC_BYTES)],
    ids=["quiet_server", "background_traffic"],
)
def test_verify_compressor_negotiation_accepts_a_clean_no_compression_match(
    after: _Counters,
) -> None:
    preflight_result, _collection = _run(WireCompressor.NONE, _ZERO_COUNTERS, after)
    assert preflight_result.compressor is WireCompressor.NONE
    assert all(
        delta < PREFLIGHT_PAYLOAD_BYTES
        for delta in preflight_result.counter_deltas.values()
    )


@pytest.mark.parametrize(
    ("compressor", "after", "match"),
    [
        pytest.param(
            WireCompressor.ZSTD,
            _ZERO_COUNTERS,
            "fell back to no compression",
            id="fallback_to_no_compression",
        ),
        pytest.param(
            WireCompressor.ZSTD,
            _counters(zstd=PREFLIGHT_PAYLOAD_BYTES - 1),
            "fell back to no compression",
            id="less_than_the_preflight_payload",
        ),
        pytest.param(
            WireCompressor.ZSTD,
            _counters(snappy=PREFLIGHT_PAYLOAD_BYTES),
            "fell back to no compression",
            id="mislabeled_compressor",
        ),
        pytest.param(
            WireCompressor.ZSTD,
            _counters(zstd=PREFLIGHT_PAYLOAD_BYTES, snappy=PREFLIGHT_PAYLOAD_BYTES),
            "could not be verified",
            id="ambiguous_negotiation",
        ),
        pytest.param(
            WireCompressor.NONE,
            _counters(zlib=PREFLIGHT_PAYLOAD_BYTES),
            "was not verified as uncompressed",
            id="unexpected_compression",
        ),
    ],
)
def test_verify_compressor_negotiation_rejects_a_bad_negotiation(
    compressor: WireCompressor, after: _Counters, match: str
) -> None:
    with pytest.raises(BenchmarkSetupError, match=match):
        _run(compressor, _ZERO_COUNTERS, after)
