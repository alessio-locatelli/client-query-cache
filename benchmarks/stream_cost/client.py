from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pymongo import MongoClient

_COMPRESSOR = "zstd"


@dataclass(frozen=True, slots=True)
class BenchmarkClientTopologyConfig:
    tls_enabled: bool
    compression_enabled: bool
    discovery_enabled: bool
    shared_connections: bool


def build_dedicated_client(
    uri: str, config: BenchmarkClientTopologyConfig
) -> MongoClient[dict[str, Any]]:
    kwargs: dict[str, Any] = {
        "directConnection": not config.discovery_enabled,
        "tls": config.tls_enabled,
        "compressors": _COMPRESSOR if config.compression_enabled else None,
    }
    return MongoClient[dict[str, Any]](uri, **kwargs)
