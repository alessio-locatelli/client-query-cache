"""Shared workload inputs for production invalidation measurements."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from benchmarks.stream_cost.client import BenchmarkClientTopologyConfig, WireCompressor
from client_query_cache._types import NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Callable

    from client_query_cache import CacheManager
    from client_query_cache._types import BsonDict

CLASSES = ("feed", "count", "own", "by_id")
WARMUP = 512
DOCUMENTS = 20_000
AUTHORS = 500
HOT_AUTHORS = 32
FEED_LIMIT = 20
TOPOLOGY = BenchmarkClientTopologyConfig(
    tls_enabled=False,
    compressor=WireCompressor.NONE,
    discovery_enabled=False,
    shared_connections=False,
)


@dataclass(frozen=True, slots=True)
class Write:
    mix: Literal["insert", "update"]
    identity: NonNegativeInt
    author: NonNegativeInt
    created: NonNegativeInt


def newest_documents() -> dict[NonNegativeInt, list[NonNegativeInt]]:
    return {
        author: list(range(author, DOCUMENTS, AUTHORS))[-FEED_LIMIT:]
        for author in range(HOT_AUTHORS)
    }


def read_key(index: NonNegativeInt) -> tuple[str, NonNegativeInt]:
    return CLASSES[index % len(CLASSES)], (index // len(CLASSES)) % HOT_AUTHORS


def await_warm(
    manager: CacheManager[BsonDict], operation: Callable[[], object]
) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        before = manager.snapshot().hits
        operation()
        if manager.snapshot().hits > before:
            return
        time.sleep(0.01)
    raise RuntimeError("Cache did not become warm within 30 seconds")
