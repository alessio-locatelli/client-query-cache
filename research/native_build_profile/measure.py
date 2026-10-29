from __future__ import annotations

import argparse
import gc
import hashlib
import inspect
import json
import resource
import statistics
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from client_query_cache import _shared_index as native
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCoreConfig
from scripts import pgo_training
from scripts.pgo_training import (
    CLEANUP,
    NAMESPACE,
    RESIDENT_KEYS,
    SMALL_BYTES,
    documents,
    new_core,
    populated_identity_core,
)
from scripts.pgo_training import (
    WORKLOADS as TRAINED,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from types import ModuleType

    from scripts.pgo_training import Pass, Workload

BATCH_SECONDS = 0.02
BATCHES = 31
WARMUP_BATCHES = 3
LIFECYCLE_NAMESPACES = 64


def accept_previous_budget_keyword[Config](
    training: ModuleType, config_class: Callable[..., Config]
) -> None:
    if "budget_bytes" in inspect.signature(config_class).parameters:
        return

    def previous_keyword(**fields: int) -> Config:
        fields["shared_budget_bytes"] = fields.pop("budget_bytes")
        return config_class(**fields)

    vars(training)["CacheCoreConfig"] = previous_keyword


def snapshot() -> Workload:
    core, _shape, _payloads = populated_identity_core(
        documents(SMALL_BYTES, RESIDENT_KEYS)
    )
    take = core.snapshot

    def run() -> None:
        for _ in range(RESIDENT_KEYS):
            take()

    return run, RESIDENT_KEYS


def namespace_lifecycle() -> Workload:
    core = new_core()
    shape_documents = documents(SMALL_BYTES, LIFECYCLE_NAMESPACES)
    namespaces = [
        NamespaceId(NAMESPACE.database, f"collection-{index}")
        for index in range(LIFECYCLE_NAMESPACES)
    ]

    def run() -> None:
        for namespace, document in zip(namespaces, shape_documents, strict=True):
            core.create_namespace(namespace)
            capture = core.begin_identity_admission(namespace, document["_id"])
            core.admit_identity_encoded(capture, "shape", b"\x05\x00\x00\x00\x00")
            core.set_database_available(namespace.database, available=False)
            core.set_database_available(namespace.database, available=True)
            core.clear_namespace(namespace)
            core.drop_namespace(namespace)

    run()
    return run, LIFECYCLE_NAMESPACES


WORKLOADS: dict[str, Callable[[], Workload]] = {
    **TRAINED,
    "snapshot": snapshot,
    "namespace_lifecycle": namespace_lifecycle,
}


def passes_per_batch(run: Pass) -> int:
    started = time.perf_counter()
    run()
    elapsed = time.perf_counter() - started
    return max(1, round(BATCH_SECONDS / max(elapsed, 1e-9)))


def batch_nanoseconds(run: Pass, operations: int, passes: int) -> Iterator[float]:
    for _ in range(WARMUP_BATCHES):
        for _ in range(passes):
            run()
    for _ in range(BATCHES):
        started = time.perf_counter_ns()
        for _ in range(passes):
            run()
        yield (time.perf_counter_ns() - started) / (passes * operations)


def measure(name: str) -> dict[str, float]:
    run, operations = WORKLOADS[name]()
    passes = passes_per_batch(run)
    gc.collect()
    gc.disable()
    try:
        samples = sorted(batch_nanoseconds(run, operations, passes))
    finally:
        gc.enable()
    return {
        "median_ns": statistics.median(samples),
        "p10_ns": samples[len(samples) // 10],
        "min_ns": samples[0],
    }


def extension_sha256() -> str:
    return hashlib.sha256(Path(native.__file__).read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Time native extension entry points on realistic call sequences"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workloads", nargs="*", default=list(WORKLOADS))
    arguments = parser.parse_args()
    accept_previous_budget_keyword(pgo_training, CacheCoreConfig)
    with CLEANUP:
        timings = {name: measure(name) for name in arguments.workloads}
    report = {
        "extension": native.__file__,
        "extension_sha256": extension_sha256(),
        "extension_bytes": Path(native.__file__).stat().st_size,
        "interpreter": sys.version,
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "results": timings,
    }
    arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
