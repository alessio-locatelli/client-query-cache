from __future__ import annotations

import cProfile
import gc
import json
import pstats
import statistics
import tracemalloc
from time import perf_counter
from typing import TYPE_CHECKING, Literal, TypedDict

import pytest

from client_query_cache._core import manager as core_module
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.find_reads import find_read_shape
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCore
from client_query_cache._types import NonNegativeFloat, NonNegativeInt
from tests.call_counting import count_current_thread_calls

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.benchmark, pytest.mark.timeout(180)]
HEAP_NAMESPACE = NamespaceId("heap", "empty")


@pytest.fixture
def traced_family_core() -> Iterator[CacheCore]:
    core = CacheCore()
    core.admit_namespace(
        core.capture_namespace_generation(NamespaceId("warm", "codec")), "warm", []
    )
    core.clear_namespace(NamespaceId("warm", "codec"))
    core._namespace(HEAP_NAMESPACE)
    gc.collect()
    yield core
    tracemalloc.stop()
    core.close()


def family_predicate(branches: Literal[8, 1024]) -> object:
    return {
        "$or": [
            {f"field_{number}": {"$in": [number, number + 1, number + 2]}}
            for number in range(branches)
        ]
    }


def populate_sources(
    core: CacheCore,
    count: Literal[1, 16, 64],
    *,
    indexed: bool,
    predicate: object,
    descending: bool = False,
) -> None:
    limits = range(100, 100 + count)
    for limit in reversed(limits) if descending else limits:
        shape = find_read_shape(
            predicate, None, {"_id": 1}, 0, limit, collation=None, codec="codec"
        )
        assert (
            core.admit_namespace(
                core.capture_namespace_generation(HEAP_NAMESPACE),
                shape.discriminator,
                [],
                find_source=shape.source if indexed else None,
            )
            is AdmissionOutcome.ADMITTED
        )


class HeapMeasurement(TypedDict):
    retained_heap_bytes: NonNegativeInt
    payload_bytes: NonNegativeInt
    after_clear_heap_bytes: NonNegativeInt


def measure_heap(
    core: CacheCore, count: Literal[1, 16, 64], *, indexed: bool
) -> HeapMeasurement:
    gc.collect()
    before = tracemalloc.get_traced_memory()[0]
    populate_sources(core, count, indexed=indexed, predicate=family_predicate(1024))
    gc.collect()
    retained = tracemalloc.get_traced_memory()[0] - before
    snapshot = core.snapshot()
    tokens = sum(
        len(bucket) for bucket in core._namespace(HEAP_NAMESPACE).find_families.values()
    )
    assert snapshot.entry_count == count
    assert tokens == (count if indexed else 0)
    core.clear_namespace(HEAP_NAMESPACE)
    gc.collect()
    cleared = tracemalloc.get_traced_memory()[0] - before
    assert not core._namespace(HEAP_NAMESPACE).find_families
    return {
        "retained_heap_bytes": retained,
        "payload_bytes": snapshot.used_bytes,
        "after_clear_heap_bytes": cleared,
    }


@pytest.mark.parametrize("count", [1, 16, 64], ids=["single", "sixteen", "sixty-four"])
def test_retained_family_heap(
    traced_family_core: CacheCore, count: Literal[1, 16, 64]
) -> None:
    tracemalloc.start()
    exact_only = measure_heap(traced_family_core, count, indexed=False)
    indexed = measure_heap(traced_family_core, count, indexed=True)
    added_heap = indexed["retained_heap_bytes"] - exact_only["retained_heap_bytes"]
    print(
        json.dumps(
            {
                "limits": count,
                "exact_only": exact_only,
                "indexed": indexed,
                "additional_index_heap_bytes": added_heap,
            }
        )
    )
    assert indexed["payload_bytes"] == exact_only["payload_bytes"]
    # Allow ample bookkeeping margin while detecting retained megabyte query copies.
    assert added_heap < 8 * 1024 + count * 1024


@pytest.mark.parametrize("count", [1, 16, 64], ids=["single", "sixteen", "sixty-four"])
@pytest.mark.parametrize("branches", [8, 1024], ids=["small-query", "large-query"])
@pytest.mark.parametrize("descending", [False, True], ids=["ascending", "descending"])
def test_find_family_lookup(
    traced_family_core: CacheCore,
    count: Literal[1, 16, 64],
    branches: Literal[8, 1024],
    descending: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = traced_family_core
    predicate = family_predicate(branches)
    populate_sources(
        core, count, indexed=True, predicate=predicate, descending=descending
    )
    request = find_read_shape(
        predicate, None, {"_id": 1}, 0, 10, collation=None, codec="codec"
    )
    before = core.snapshot()
    timings: list[NonNegativeFloat] = []
    for _ in range(21):
        started = perf_counter()
        lookup = core.lookup_find(HEAP_NAMESPACE, request)
        timings.append(perf_counter() - started)
        assert lookup.hit
        assert lookup.value == []
    tracemalloc.start()
    assert core.lookup_find(HEAP_NAMESPACE, request).hit
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    profiler = cProfile.Profile()
    profiler.enable()
    assert core.lookup_find(HEAP_NAMESPACE, request).hit
    profiler.disable()
    probes = count_current_thread_calls(
        monkeypatch, type(core), "_probe_namespace_entry"
    )
    discriminators = count_current_thread_calls(
        monkeypatch, core_module, "find_discriminator"
    )
    assert core.lookup_find(HEAP_NAMESPACE, request).hit
    print(
        json.dumps(
            {
                "limits": count,
                "predicate_branches": branches,
                "admission_order": "descending" if descending else "ascending",
                "lookup_median_us": round(statistics.median(timings[1:]) * 1e6, 1),
                "lookup_peak_bytes": peak,
                "lru_probes": probes.count,
                "discriminator_builds": discriminators.count,
            }
        )
    )
    pstats.Stats(profiler).sort_stats("tottime").print_stats(5)
    assert probes.count == 2
    assert discriminators.count == 2
    assert core.snapshot().used_bytes == before.used_bytes
    assert core.snapshot().entry_count == before.entry_count
