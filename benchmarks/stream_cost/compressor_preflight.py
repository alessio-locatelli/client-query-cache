from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from benchmarks.stream_cost.client import WireCompressor
from benchmarks.stream_cost.errors import BenchmarkSetupError
from client_query_cache._types import NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pymongo import MongoClient

_PYMONGO_COMPRESSOR_NAMES: dict[WireCompressor, str] = {
    WireCompressor.SNAPPY: "snappy",
    WireCompressor.ZLIB: "zlib",
    WireCompressor.ZSTD: "zstd",
}

_PREFLIGHT_DOCUMENT_COUNT = 50
_PREFLIGHT_PADDING_BYTES = 4_096
_PREFLIGHT_COLLECTION_NAME = "compressor_preflight"
PREFLIGHT_PAYLOAD_BYTES = _PREFLIGHT_DOCUMENT_COUNT * _PREFLIGHT_PADDING_BYTES


@dataclass(frozen=True, slots=True)
class CompressorPreflightResult:
    compressor: WireCompressor
    counter_deltas: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "counter_deltas", MappingProxyType(dict(self.counter_deltas))
        )


def _compression_counters(
    admin_client: MongoClient[dict[str, Any]],
) -> Mapping[str, Mapping[str, Mapping[str, NonNegativeInt]]]:
    status = admin_client.admin.command("serverStatus")
    compression = status["network"]["compression"]
    assert isinstance(compression, dict)
    return compression


def _counter_bytes_in(
    counters: Mapping[str, Mapping[str, Mapping[str, NonNegativeInt]]], name: str
) -> NonNegativeInt:
    entry = counters[name]
    return entry["compressor"]["bytesIn"] + entry["decompressor"]["bytesIn"]


def _counter_deltas(
    before: Mapping[str, Mapping[str, Mapping[str, NonNegativeInt]]],
    after: Mapping[str, Mapping[str, Mapping[str, NonNegativeInt]]],
) -> dict[str, int]:
    return {
        name: _counter_bytes_in(after, name) - _counter_bytes_in(before, name)
        for name in before
    }


def verify_compressor_negotiation(
    measured_client: MongoClient[dict[str, Any]],
    admin_client: MongoClient[dict[str, Any]],
    *,
    compressor: WireCompressor,
    database_name: str,
) -> CompressorPreflightResult:
    collection = measured_client[database_name][_PREFLIGHT_COLLECTION_NAME]
    collection.drop()
    documents = [
        {"_id": index, "padding": "x" * _PREFLIGHT_PADDING_BYTES}
        for index in range(_PREFLIGHT_DOCUMENT_COUNT)
    ]
    before = _compression_counters(admin_client)
    collection.insert_many(documents)
    list(collection.find({}))
    collection.drop()
    after = _compression_counters(admin_client)
    deltas = _counter_deltas(before, after)

    carried = sorted(
        name for name, delta in deltas.items() if delta >= PREFLIGHT_PAYLOAD_BYTES
    )

    if compressor is WireCompressor.NONE:
        if carried:
            message = (
                "no compression was requested for this preflight, but the "
                f"server's compression counter(s) for {carried} advanced by at least "
                "the preflight payload; the connection was not verified as "
                "uncompressed"
            )
            raise BenchmarkSetupError(message)
        return CompressorPreflightResult(compressor=compressor, counter_deltas=deltas)

    expected_name = _PYMONGO_COMPRESSOR_NAMES[compressor]
    if expected_name not in carried:
        message = (
            f"the {compressor.value!r} compressor was requested but its "
            "server-side compression counter did not advance by the preflight "
            "payload; negotiation likely fell back to no compression"
        )
        raise BenchmarkSetupError(message)
    other_carried = [name for name in carried if name != expected_name]
    if other_carried:
        message = (
            f"the {compressor.value!r} compressor was requested but "
            f"{other_carried} also advanced by the preflight payload, so the "
            "negotiated compressor could not be verified unambiguously"
        )
        raise BenchmarkSetupError(message)
    return CompressorPreflightResult(compressor=compressor, counter_deltas=deltas)
