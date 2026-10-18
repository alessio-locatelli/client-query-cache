from __future__ import annotations

import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.find_reads import FindSource
from client_query_cache._core.keys import NamespaceId, canonical_alias_key
from client_query_cache._core.manager import CacheCore, CacheCoreConfig
from client_query_cache._types import NonNegativeFloat, PositiveInt

_WRITES_PER_WORKER: PositiveInt = 2_048
_REPEATS: PositiveInt = 21
_FIND_FAMILIES: PositiveInt = 16


def write(
    core: CacheCore,
    namespace: NamespaceId,
    start_barrier: threading.Barrier,
    *,
    populated: bool,
) -> None:
    start_barrier.wait()
    for index in range(_WRITES_PER_WORKER):
        identity: object = f"document-{index}" if populated else index
        core.record_write(namespace, identity)


def measure(workers: PositiveInt, *, populated: bool) -> NonNegativeFloat:
    durations: list[NonNegativeFloat] = []
    for _repeat in range(_REPEATS):
        core = CacheCore(CacheCoreConfig())
        namespaces = tuple(
            NamespaceId("benchmark", f"namespace-{worker}") for worker in range(workers)
        )
        captures = tuple(core.capture_namespace_generation(ns) for ns in namespaces)
        if populated:
            for worker, capture in enumerate(captures):
                for index in range(_WRITES_PER_WORKER):
                    identity = f"document-{index}"
                    email = f"{identity}-{worker}@example.test"
                    alias = canonical_alias_key(("email",), (email,), None)
                    outcome = core.admit_unique_key_match(
                        capture,
                        (alias, "full"),
                        identity,
                        "full",
                        {"email": email},
                        alias=alias,
                    )
                    if outcome is not AdmissionOutcome.ADMITTED:
                        raise RuntimeError("benchmark metadata could not be populated")
                for family in range(_FIND_FAMILIES):
                    outcome = core.admit_namespace(
                        capture,
                        ("find", family),
                        [{"_id": family}],
                        find_source=FindSource(family, 1),
                    )
                    if outcome is not AdmissionOutcome.ADMITTED:
                        raise RuntimeError("could not populate benchmark find families")

        start_barrier = threading.Barrier(workers + 1)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = tuple(
                executor.submit(
                    write,
                    core,
                    namespaces[worker],
                    start_barrier,
                    populated=populated,
                )
                for worker in range(workers)
            )
            started = time.perf_counter()
            start_barrier.wait()
            for future in futures:
                future.result()
            durations.append(time.perf_counter() - started)
        core.close()

    writes = workers * _WRITES_PER_WORKER
    return writes / statistics.median(durations)


for _populated in (False, True):
    _mode = "cached_identity_and_families" if _populated else "empty_namespace"
    for _workers in (1, 2, 4, 8):
        _throughput = measure(_workers, populated=_populated)
        print(f"mode={_mode} workers={_workers} writes_per_second={_throughput:.0f}")
