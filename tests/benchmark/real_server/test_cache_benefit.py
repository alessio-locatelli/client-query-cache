from __future__ import annotations

import logging
import multiprocessing
import time
from typing import TYPE_CHECKING

import pytest

from client_query_cache._types import NonNegativeFloat
from tests.benchmark.real_server.atlas_bandwidth import (
    collect_bandwidth_evidence,
    resolve_atlas_project_id,
)
from tests.benchmark.real_server.workers import (
    ReadPhaseResult,
    drop_benchmark_collection,
    read_documents_repeatedly_into_queue,
    run_preflight_and_start_clock,
    write_documents_until_stopped,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from faker import Faker

    from tests.benchmark.real_server.env import RealMongoDbUri

logger = logging.getLogger(__name__)

pytestmark = pytest.mark.benchmark

_DOCUMENT_COUNT = 18
_WARMUP_CYCLES = 2
_MEASURED_CYCLES = 4
_WRITER_UPDATE_INTERVAL_SECONDS = 0.1
_WRITER_SEED_TIMEOUT_SECONDS = 10.0
_READER_PHASE_TIMEOUT_SECONDS = 15.0
_WRITER_SHUTDOWN_TIMEOUT_SECONDS = 5.0
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


def _log_bandwidth_evidence_excluding_its_duration(
    atlas_project_id: str | None, mongodb_uri: str
) -> NonNegativeFloat:
    if atlas_project_id is None:
        return 0.0
    collection_start = time.perf_counter()
    logger.info(
        "Atlas bandwidth evidence covering both the cached and uncached reader "
        "phases (also includes the concurrent writer's traffic; the 1-minute "
        "granularity cannot attribute it to either phase alone): %s",
        collect_bandwidth_evidence(atlas_project_id, mongodb_uri),
    )
    return time.perf_counter() - collection_start


def _run_reader_phase(
    uri: RealMongoDbUri,
    document_ids: list[str],
    collection_name: str,
    *,
    use_cache: bool,
) -> ReadPhaseResult:
    result_queue: multiprocessing.Queue[ReadPhaseResult] = multiprocessing.Queue()
    reader = multiprocessing.Process(
        target=read_documents_repeatedly_into_queue,
        args=(result_queue, uri.get_secret_value(), document_ids),
        kwargs={
            "use_cache": use_cache,
            "warmup_cycles": _WARMUP_CYCLES,
            "measured_cycles": _MEASURED_CYCLES,
            "collection_name": collection_name,
        },
    )
    reader.start()
    try:
        reader.join(timeout=_READER_PHASE_TIMEOUT_SECONDS)
        if reader.is_alive():
            reader.terminate()  # pragma: no cover (requires a stalled real deployment)
            reader.join()  # pragma: no cover (requires a stalled real deployment)
            raise TimeoutError(
                "reader phase did not complete within its timeout"
            )  # pragma: no cover (requires a stalled real deployment)
        return result_queue.get_nowait()
    finally:
        result_queue.close()


def test_cache_provides_at_least_2x_benefit_over_direct_pymongo(
    real_mongodb_uri: RealMongoDbUri,
    make_fake_document: Callable[..., dict[str, Any]],
    faker: Faker,
) -> None:
    collection_name = f"documents-{faker.uuid4()}"
    seed_documents = [make_fake_document() for _ in range(_DOCUMENT_COUNT)]
    document_ids = [document["_id"] for document in seed_documents]

    stop_event = multiprocessing.Event()
    ready_event = multiprocessing.Event()
    writer = multiprocessing.Process(
        target=write_documents_until_stopped,
        args=(real_mongodb_uri.get_secret_value(), seed_documents, document_ids),
        kwargs={
            "update_interval_seconds": _WRITER_UPDATE_INTERVAL_SECONDS,
            "stop_event": stop_event,
            "collection_name": collection_name,
            "ready_event": ready_event,
        },
    )
    overall_start = run_preflight_and_start_clock(real_mongodb_uri.get_secret_value())
    bandwidth_evidence_overhead_seconds = 0.0

    try:
        writer.start()
        if not ready_event.wait(timeout=_WRITER_SEED_TIMEOUT_SECONDS):
            raise TimeoutError(  # pragma: no cover (requires a stalled real deployment)
                "writer did not seed its documents within the timeout"
            )
        atlas_project_id = resolve_atlas_project_id()
        cached_result = _run_reader_phase(
            real_mongodb_uri, document_ids, collection_name, use_cache=True
        )
        uncached_result = _run_reader_phase(
            real_mongodb_uri, document_ids, collection_name, use_cache=False
        )
        bandwidth_evidence_overhead_seconds += (
            _log_bandwidth_evidence_excluding_its_duration(
                atlas_project_id, real_mongodb_uri.get_secret_value()
            )
        )
    finally:
        stop_event.set()
        writer.join(timeout=_WRITER_SHUTDOWN_TIMEOUT_SECONDS)
        if writer.is_alive():
            writer.terminate()  # pragma: no cover (requires a stalled real deployment)
            writer.join()  # pragma: no cover (requires a stalled real deployment)
        drop_benchmark_collection(real_mongodb_uri.get_secret_value(), collection_name)

    overall_duration = (
        time.perf_counter() - overall_start - bandwidth_evidence_overhead_seconds
    )

    assert overall_duration < _MAXIMUM_TOTAL_DURATION_SECONDS
    assert (
        cached_result.duration_seconds * _MINIMUM_CACHE_SPEEDUP_FACTOR
        <= uncached_result.duration_seconds
    )
    assert cached_result.duration_seconds <= _CACHED_DURATION_CEILING_SECONDS
    assert uncached_result.duration_seconds <= _UNCACHED_DURATION_CEILING_SECONDS
    assert uncached_result.find_command_count == _UNCACHED_FIND_COMMAND_COUNT
    assert cached_result.find_command_count <= _CACHED_FIND_COMMAND_COUNT_CEILING
    assert cached_result.max_observed_counter >= 0
    assert uncached_result.max_observed_counter >= 0
