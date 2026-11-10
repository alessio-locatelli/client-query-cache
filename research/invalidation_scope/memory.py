"""Measure bounded production proof ownership through churn and namespace recreation."""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path

import psutil

from client_query_cache import CacheCore, CacheCoreConfig, SelectiveInvalidation
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.selective_invalidation import (
    normalize_invalidation,
    partition_scalar,
)
from client_query_cache._types import BsonDict, PositiveInt


def measure(
    rounds: PositiveInt, max_entries: PositiveInt | None, path_count: PositiveInt
) -> BsonDict:
    namespaces = tuple(NamespaceId("memory", f"posts_{index}") for index in range(64))
    policy = SelectiveInvalidation(
        insert_partition_field="author_id", update_dependencies_for_counts=True
    )
    core = CacheCore(
        CacheCoreConfig(max_entries=max_entries, enable_telemetry=True),
        invalidation=normalize_invalidation(
            {
                (namespace.database, namespace.collection): policy
                for namespace in namespaces
            }
        ),
    )
    process = psutil.Process()
    samples: list[BsonDict] = []
    dependencies = tuple(
        f"field_{index:02d}_".ljust(64, "x") for index in range(path_count)
    )
    try:
        for ordinal in range(rounds):
            captures = [
                core.capture_namespace_generation(
                    namespaces[index % len(namespaces)],
                    partition=partition_scalar(ordinal * 1280 + index),
                    dependencies=dependencies,
                )
                for index in range(1280)
            ]
            for namespace in namespaces:
                core.record_write(namespace, 0, partition=partition_scalar(-1))
            admitted = sum(
                core.admit_namespace(capture, (ordinal, index), index)
                is AdmissionOutcome.ADMITTED
                for index, capture in enumerate(captures)
            )
            assert admitted == 1024
            samples.append(
                {
                    "round": ordinal,
                    "phase": "occupied",
                    "rss_bytes": process.memory_info().rss,
                    "resident_bson_bytes": core.snapshot().used_bytes,
                }
            )
            # Write-only values must not extend the queried proof working set.
            for index in range(4096):
                core.record_write(
                    namespaces[index % len(namespaces)],
                    index,
                    partition=partition_scalar(1000000 + index),
                )
            for namespace in namespaces:
                core.drop_namespace(namespace)
            for capture in captures:
                assert (
                    core.admit_namespace(capture, "obsolete", 1)
                    is AdmissionOutcome.DECLINED_STALE
                )
            captures.clear()
            del capture
            gc.collect()
            assert core.snapshot().entry_count == 0
            samples.append(
                {
                    "round": ordinal,
                    "phase": "released",
                    "rss_bytes": process.memory_info().rss,
                    "resident_bson_bytes": core.snapshot().used_bytes,
                }
            )
    finally:
        core.close()
    return {
        "max_entries": max_entries,
        "path_count": path_count,
        "rounds": rounds,
        "samples": samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=16)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.rounds < 2:
        parser.error("at least two rounds are required")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as output:
        json.dump(
            [
                measure(args.rounds, limit, paths)
                for paths in (1, 32)
                for limit in (None, 64)
            ],
            output,
            indent=2,
        )


if __name__ == "__main__":
    main()
