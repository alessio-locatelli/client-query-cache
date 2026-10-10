from __future__ import annotations

import enum
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pymongo import MongoClient

from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)
from client_query_cache._types import BsonDict

if TYPE_CHECKING:
    from collections.abc import Sequence


class WireCompressor(enum.Enum):
    NONE = "none"
    SNAPPY = "snappy"
    ZLIB = "zlib"
    ZSTD = "zstd"


_PYMONGO_COMPRESSOR_NAMES: dict[WireCompressor, str] = {
    WireCompressor.SNAPPY: "snappy",
    WireCompressor.ZLIB: "zlib",
    WireCompressor.ZSTD: "zstd",
}

_ZLIB_COMPRESSION_LEVEL = -1


@dataclass(frozen=True, slots=True)
class BenchmarkClientTopologyConfig:
    tls_enabled: bool
    compressor: WireCompressor
    discovery_enabled: bool
    shared_connections: bool


def build_dedicated_client(
    uri: str,
    config: BenchmarkClientTopologyConfig,
    *,
    event_listeners: Sequence[object] = (),
) -> MongoClient[BsonDict]:
    if config.shared_connections:
        message = (
            "build_dedicated_client only builds a client not shared with other "
            "processes; a topology declaring shared_connections=True cannot be "
            "measured through this dedicated client"
        )
        raise BenchmarkConfigurationError(message)
    kwargs: dict[str, Any] = {
        "directConnection": not config.discovery_enabled,
        "tls": config.tls_enabled,
        "event_listeners": list(event_listeners),
    }
    if config.compressor is not WireCompressor.NONE:
        kwargs["compressors"] = _PYMONGO_COMPRESSOR_NAMES[config.compressor]
        kwargs["zlibCompressionLevel"] = _ZLIB_COMPRESSION_LEVEL
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        try:
            return MongoClient[BsonDict](uri, **kwargs)
        except UserWarning as error:
            message = (
                f"the {config.compressor.value!r} wire compressor was requested "
                "but PyMongo could not use it in this Python build, so the "
                f"connection would have silently fallen back to no compression: "
                f"{error}"
            )
            raise BenchmarkSetupError(message) from error
