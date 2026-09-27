from __future__ import annotations

import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING

import pytest

from tests.benchmark.real_server.workers import (
    ReadPhaseResult,
    drop_benchmark_collection,
    read_documents_repeatedly,
    write_documents_until_stopped,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from tests.benchmark.real_server.env import RealMongoDbUri

pytestmark = pytest.mark.benchmark

_DOCUMENT_COUNT = 18
_WARMUP_CYCLES = 2
_MEASURED_CYCLES = 4
_WRITER_UPDATE_INTERVAL_SECONDS = 0.1
_WRITER_SEED_SETTLE_SECONDS = 1.0
_READER_PHASE_TIMEOUT_SECONDS = 15.0
_MAXIMUM_TOTAL_DURATION_SECONDS = 20.0

_MINIMUM_CACHE_SPEEDUP_FACTOR = 2.0

_FIRST_MEASURED_UNCACHED_DURATION_SECONDS = 5.7138
_FIRST_MEASURED_CACHED_FIND_COMMAND_COUNT = 0

_DURATION_CEILING_MARGIN_FACTOR = 3.0
_CACHED_FIND_COMMAND_COUNT_MARGIN = 5

_UNCACHED_FIND_COMMAND_COUNT = _DOCUMENT_COUNT * _MEASURED_CYCLES
_CACHED_FIND_COMMAND_COUNT_CEILING = (
    _FIRST_MEASURED_CACHED_FIND_COMMAND_COUNT + _CACHED_FIND_COMMAND_COUNT_MARGIN
)

_UNCACHED_DURATION_CEILING_SECONDS = (
    _FIRST_MEASURED_UNCACHED_DURATION_SECONDS * _DURATION_CEILING_MARGIN_FACTOR
)
_MEASURED_SECONDS_PER_UNCACHED_FIND = (
    _FIRST_MEASURED_UNCACHED_DURATION_SECONDS / _UNCACHED_FIND_COMMAND_COUNT
)
_CACHED_DURATION_CEILING_SECONDS = (
    _CACHED_FIND_COMMAND_COUNT_CEILING
    * _MEASURED_SECONDS_PER_UNCACHED_FIND
    * _DURATION_CEILING_MARGIN_FACTOR
)


def _run_reader_phase(
    uri: RealMongoDbUri, document_ids: list[str], *, use_cache: bool
) -> ReadPhaseResult:
    with ProcessPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            read_documents_repeatedly,
            uri,
            document_ids,
            use_cache=use_cache,
            warmup_cycles=_WARMUP_CYCLES,
            measured_cycles=_MEASURED_CYCLES,
        )
        return future.result(timeout=_READER_PHASE_TIMEOUT_SECONDS)


def test_cache_provides_at_least_2x_benefit_over_direct_pymongo(
    real_mongodb_uri: RealMongoDbUri, make_fake_document: Callable[..., dict[str, Any]]
) -> None:
    seed_documents = [make_fake_document() for _ in range(_DOCUMENT_COUNT)]
    document_ids = [document["_id"] for document in seed_documents]

    stop_event = multiprocessing.Event()
    writer = multiprocessing.Process(
        target=write_documents_until_stopped,
        args=(
            real_mongodb_uri,
            seed_documents,
            document_ids,
            _WRITER_UPDATE_INTERVAL_SECONDS,
            stop_event,
        ),
    )
    overall_start = time.perf_counter()
    writer.start()
    time.sleep(_WRITER_SEED_SETTLE_SECONDS)

    try:
        cached_result = _run_reader_phase(
            real_mongodb_uri, document_ids, use_cache=True
        )
        uncached_result = _run_reader_phase(
            real_mongodb_uri, document_ids, use_cache=False
        )
    finally:
        stop_event.set()
        writer.join()
        drop_benchmark_collection(real_mongodb_uri)

    overall_duration = time.perf_counter() - overall_start

    assert overall_duration < _MAXIMUM_TOTAL_DURATION_SECONDS
    assert (
        cached_result.duration_seconds * _MINIMUM_CACHE_SPEEDUP_FACTOR
        <= uncached_result.duration_seconds
    )
    assert cached_result.duration_seconds <= _CACHED_DURATION_CEILING_SECONDS
    assert uncached_result.duration_seconds <= _UNCACHED_DURATION_CEILING_SECONDS
    assert uncached_result.find_command_count == _UNCACHED_FIND_COMMAND_COUNT
    assert cached_result.find_command_count <= _CACHED_FIND_COMMAND_COUNT_CEILING
