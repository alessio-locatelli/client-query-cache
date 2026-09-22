from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pymongo import MongoClient

from benchmarks.stream_cost.errors import BenchmarkConfigurationError

if TYPE_CHECKING:
    from collections.abc import Sequence

_COMPRESSOR = "zstd"


@dataclass(frozen=True, slots=True)
class BenchmarkClientTopologyConfig:
    tls_enabled: bool
    compression_enabled: bool
    discovery_enabled: bool
    shared_connections: bool


def build_dedicated_client(
    uri: str,
    config: BenchmarkClientTopologyConfig,
    *,
    event_listeners: Sequence[object] = (),
) -> MongoClient[dict[str, Any]]:
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
        "compressors": _COMPRESSOR if config.compression_enabled else None,
        "event_listeners": list(event_listeners),
    }
    return MongoClient[dict[str, Any]](uri, **kwargs)
