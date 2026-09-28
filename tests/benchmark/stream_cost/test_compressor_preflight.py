from __future__ import annotations

from typing import Any

import pytest

from benchmarks.stream_cost.client import WireCompressor
from benchmarks.stream_cost.compressor_preflight import (
    CompressorPreflightResult,
    verify_compressor_negotiation,
)
from benchmarks.stream_cost.errors import BenchmarkSetupError

pytestmark = pytest.mark.unit

_Counters = dict[str, dict[str, dict[str, int]]]

_ZERO_COUNTERS: _Counters = {
    name: {"compressor": {"bytesIn": 0}, "decompressor": {"bytesIn": 0}}
    for name in ("snappy", "zlib", "zstd")
}


def _counters(**advanced: int) -> _Counters:
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
def test_verify_compressor_negotiation_accepts_a_clean_match(
    compressor: WireCompressor,
) -> None:
    preflight_result, collection = _run(
        compressor, _ZERO_COUNTERS, _counters(**{compressor.value: 1_000})
    )
    assert preflight_result.compressor is compressor
    assert preflight_result.counter_deltas[compressor.value] == 1_000
    assert collection.dropped == 2


def test_verify_compressor_negotiation_accepts_a_clean_no_compression_match() -> None:
    preflight_result, _collection = _run(
        WireCompressor.NONE, _ZERO_COUNTERS, _ZERO_COUNTERS
    )
    assert preflight_result.compressor is WireCompressor.NONE
    assert all(delta == 0 for delta in preflight_result.counter_deltas.values())


def test_verify_compressor_negotiation_rejects_fallback_to_no_compression() -> None:
    with pytest.raises(BenchmarkSetupError, match="fell back to no compression"):
        _run(WireCompressor.ZSTD, _ZERO_COUNTERS, _ZERO_COUNTERS)


def test_verify_compressor_negotiation_rejects_a_mislabeled_compressor() -> None:
    with pytest.raises(BenchmarkSetupError, match="fell back to no compression"):
        _run(WireCompressor.ZSTD, _ZERO_COUNTERS, _counters(snappy=500))


def test_verify_compressor_negotiation_rejects_ambiguous_negotiation() -> None:
    with pytest.raises(BenchmarkSetupError, match="could not be verified"):
        _run(WireCompressor.ZSTD, _ZERO_COUNTERS, _counters(zstd=500, snappy=200))


def test_verify_compressor_negotiation_rejects_unexpected_compression() -> None:
    with pytest.raises(BenchmarkSetupError, match="was not verified as uncompressed"):
        _run(WireCompressor.NONE, _ZERO_COUNTERS, _counters(zlib=300))
