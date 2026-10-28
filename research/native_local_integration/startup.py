"""Measure fresh imports and empty manager construction without database I/O."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import psutil


def checkpoint(phase: str) -> dict[str, object]:
    memory = psutil.Process().memory_full_info()
    return {
        "phase": phase,
        "wall_seconds": time.perf_counter(),
        "cpu_seconds": time.process_time(),
        "rss_bytes": memory.rss,
        "pss_bytes": memory.pss,
    }


async def measure(model: str) -> list[dict[str, object]]:
    checkpoints = [checkpoint("before_import")]
    from pymongo import AsyncMongoClient, MongoClient  # noqa: PLC0415 - Load both clients within the measured import boundary.

    import client_query_cache  # noqa: PLC0415 - The fresh import is the operation being measured.

    checkpoints.append(checkpoint("imported"))
    from benchmarks.implementation import implementation  # noqa: PLC0415 - Collect provenance after measuring the library import.

    if model == "sync":
        with MongoClient(connect=False) as client:
            with client_query_cache.CacheManager(client) as manager:
                checkpoints.append(checkpoint("constructed"))
                checkpoints[-1]["implementation"] = implementation(manager.cache_core)
            checkpoints.append(checkpoint("closed"))
    else:
        from client_query_cache.asynchronous import CacheManager  # noqa: PLC0415 - Resolve the requested API after the shared import boundary.

        async with AsyncMongoClient(connect=False) as async_client:
            async with CacheManager(async_client) as async_manager:
                checkpoints.append(checkpoint("constructed"))
                checkpoints[-1]["implementation"] = implementation(
                    async_manager.cache_core
                )
            checkpoints.append(checkpoint("closed"))
    assert all(
        Path(str(checkpoints[-2]["implementation"][field])).is_relative_to(sys.prefix)
        for field in ("library", "extension")
    )
    return checkpoints


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=("sync", "async"))
    print(json.dumps(asyncio.run(measure(parser.parse_args().model))))


if __name__ == "__main__":
    main()
