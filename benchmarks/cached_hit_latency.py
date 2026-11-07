from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from pymongo import MongoClient

from benchmarks.stream_cost.generators import (
    SMALL_DOCUMENT_PROFILE,
    generate_seeded_documents,
)
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache import CacheCoreConfig
from client_query_cache._types import (
    BsonDict,
    NonNegativeFloat,
    PositiveFloat,
    PositiveInt,
)
from client_query_cache.synchronous.manager import CacheManager

_DOCUMENT_COUNT: PositiveInt = 100
_DOCUMENT_SEED = 3
_MEASURED_CYCLES: PositiveInt = 10
_CPU_BUSY_SECONDS: PositiveFloat = 0.5
_DATABASE_NAME = "cached_hit_latency"
_COLLECTION_NAME = "documents"


def _keep_cpu_busy() -> None:
    deadline = time.perf_counter() + _CPU_BUSY_SECONDS
    while time.perf_counter() < deadline:
        pass


def measure_hit_seconds(uri: str) -> list[NonNegativeFloat]:
    documents = generate_seeded_documents(
        SMALL_DOCUMENT_PROFILE, count=_DOCUMENT_COUNT, seed=_DOCUMENT_SEED
    )
    filters = [{"_id": document["_id"]} for document in documents]
    with (
        MongoClient[BsonDict](uri) as client,
        CacheManager(
            client, cache_config=CacheCoreConfig(enable_telemetry=True)
        ) as manager,
    ):
        collection = client[_DATABASE_NAME][_COLLECTION_NAME]
        collection.insert_many(documents)
        cached_collection = manager.get_cached_collection(collection)
        for query in filters:
            cached_collection.find_one(query)
        _keep_cpu_busy()
        before = manager.cache_core.snapshot()
        hit_seconds: list[NonNegativeFloat] = []
        for _ in range(_MEASURED_CYCLES):
            for query in filters:
                start = time.perf_counter()
                cached_collection.find_one(query)
                hit_seconds.append(time.perf_counter() - start)
        after = manager.cache_core.snapshot()
    hits = after.hits - before.hits
    if hits != len(hit_seconds):
        message = (
            f"expected {len(hit_seconds)} cache hits, recorded {hits}; "
            "the change stream may not have been ready"
        )
        raise SystemExit(message)
    return hit_seconds


def write_report(output: Path) -> None:
    with IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="1g")) as replica_set:
        hit_seconds = measure_hit_seconds(replica_set.uri)
    report = {
        "median_hit_seconds": statistics.median(hit_seconds),
        "sample_count": len(hit_seconds),
    }
    output.write_text(json.dumps(report) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure cached find_one latency on a busy CPU."
    )
    parser.add_argument("--output", type=Path, required=True)
    write_report(parser.parse_args().output)


if __name__ == "__main__":
    main()
