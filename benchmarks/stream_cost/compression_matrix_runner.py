from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from benchmarks.stream_cost.compression_matrix import CompressionWindowSpec, WirePath
from benchmarks.stream_cost.compressor_preflight import verify_compressor_negotiation
from benchmarks.stream_cost.consolidated_stream import (
    generate_relevant_write_schedule,
    replay_write_schedule,
)
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.generators import generate_seeded_documents
from benchmarks.stream_cost.measurement import (
    ControlledMeasurement,
    OperationLatency,
    measure_controlled,
)
from benchmarks.stream_cost.workload import (
    SeededDataset,
    WorkloadKind,
    insert_dataset,
    sample_operation_ids,
    verify_primed,
    wait_for_invalidations_to_settle,
)
from client_query_cache._types import NonNegativeFloat, NonNegativeInt
from client_query_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pymongo import MongoClient
    from pymongo.synchronous.collection import Collection

    from benchmarks.stream_cost.client import WireCompressor
    from benchmarks.stream_cost.compressor_preflight import CompressorPreflightResult
    from benchmarks.stream_cost.proxy import DirectPathByteProxy
    from benchmarks.stream_cost.topology import IsolatedReplicaSet
    from client_query_cache._core.snapshots import CacheSnapshot
    from client_query_cache._core.stream_cost import InvalidationApplyReading
    from client_query_cache.synchronous.collection import CachedCollection

_COLLECTION_NAME = "measured"
_SCHEDULE_TOLERANCE_SECONDS = 2.0
_WRITE_SCHEDULE_SEED_OFFSET = 1_000
_WRITE_ID_SEED_OFFSET = 2_000


@dataclass(frozen=True, slots=True)
class CompressionWindowResult:
    window: CompressionWindowSpec
    mode: WireCompressor
    path: WirePath
    block_index: NonNegativeInt
    measurement: ControlledMeasurement
    read_latencies: tuple[OperationLatency, ...]
    write_latencies: tuple[OperationLatency, ...]
    invalidation_latencies_seconds: tuple[NonNegativeFloat, ...]
    reads_issued: NonNegativeInt
    writes_issued: NonNegativeInt


def _seed_window_dataset(window: CompressionWindowSpec) -> SeededDataset:
    documents = generate_seeded_documents(
        window.data_size, count=window.document_count, seed=window.seed
    )
    return SeededDataset(documents=tuple(documents))


def _write_schedule(window: CompressionWindowSpec) -> tuple[NonNegativeFloat, ...]:
    if window.sampling.writes == 0:
        return ()
    return generate_relevant_write_schedule(
        window.sampling.writes,
        total_duration_seconds=window.duration_seconds,
        seed=window.seed + _WRITE_SCHEDULE_SEED_OFFSET,
    )


def _issue_reads(
    find_one: Callable[[dict[str, object]], object],
    ids: Sequence[object],
    *,
    latencies: list[OperationLatency],
    outcome: str,
) -> None:
    for document_id in ids:
        started = time.monotonic()
        find_one({"_id": document_id})
        latencies.append(OperationLatency("read", outcome, time.monotonic() - started))


def _require_cache_hit(
    document_id: object, before: CacheSnapshot, after: CacheSnapshot
) -> None:
    if after.hits <= before.hits:
        message = (
            f"cache read for {document_id!r} was not a hit despite priming; "
            "the shared cache budget may be too small for this window's dataset"
        )
        raise BenchmarkSetupError(message)


def _issue_cache_reads(
    cache_collection: CachedCollection[dict[str, Any]],
    manager: CacheManager[dict[str, Any]],
    ids: Sequence[object],
    *,
    latencies: list[OperationLatency],
) -> None:
    for document_id in ids:
        before = manager.cache_core.snapshot()
        started = time.monotonic()
        cache_collection.find_one({"_id": document_id})
        seconds = time.monotonic() - started
        after = manager.cache_core.snapshot()
        _require_cache_hit(document_id, before, after)
        latencies.append(OperationLatency("read", "hit", seconds))


def _issue_scheduled_writes(
    collection: Collection[dict[str, Any]],
    dataset: SeededDataset,
    window: CompressionWindowSpec,
    *,
    latencies: list[OperationLatency],
) -> tuple[tuple[NonNegativeFloat, ...], NonNegativeFloat]:
    schedule = _write_schedule(window)
    if not schedule:
        return (), time.monotonic()
    ids = sample_operation_ids(
        dataset, len(schedule), seed=window.seed + _WRITE_ID_SEED_OFFSET
    )
    ids_iterator = iter(ids)

    def _issue_write() -> None:
        document_id = next(ids_iterator)
        started = time.monotonic()
        collection.update_one({"_id": document_id}, {"$inc": {"touched": 1}})
        latencies.append(
            OperationLatency("write", "shared_write", time.monotonic() - started)
        )

    start_monotonic = time.monotonic()
    actual_offsets = replay_write_schedule(
        _issue_write,
        schedule,
        start_monotonic=start_monotonic,
        tolerance_seconds=_SCHEDULE_TOLERANCE_SECONDS,
    )
    return actual_offsets, start_monotonic


def _invalidation_latencies(
    actual_offsets: tuple[NonNegativeFloat, ...],
    start_monotonic: NonNegativeFloat,
    apply_readings: Sequence[InvalidationApplyReading],
) -> tuple[NonNegativeFloat, ...]:
    if not actual_offsets:
        return ()
    if len(apply_readings) < len(actual_offsets):
        message = (
            f"{len(apply_readings)} invalidation-apply readings were captured but "
            f"{len(actual_offsets)} writes were scheduled"
        )
        raise BenchmarkSetupError(message)
    matched_readings = apply_readings[-len(actual_offsets) :]
    return tuple(
        reading.monotonic_seconds - (start_monotonic + offset)
        for offset, reading in zip(actual_offsets, matched_readings, strict=True)
    )


def _run_no_stream_window(
    window: CompressionWindowSpec,
    dataset: SeededDataset,
    *,
    collection: Collection[dict[str, Any]],
    replica_set: IsolatedReplicaSet,
    proxy: DirectPathByteProxy | None,
) -> tuple[ControlledMeasurement, list[OperationLatency], list[OperationLatency]]:
    read_ids = sample_operation_ids(dataset, window.sampling.reads, seed=window.seed)
    read_latencies: list[OperationLatency] = []
    write_latencies: list[OperationLatency] = []

    def _operation() -> None:
        _issue_reads(
            collection.find_one, read_ids, latencies=read_latencies, outcome="raw"
        )
        _issue_scheduled_writes(collection, dataset, window, latencies=write_latencies)
        if window.kind is WorkloadKind.IDLE:
            time.sleep(window.duration_seconds)

    _, measurement = measure_controlled(
        _operation, replica_set=replica_set, proxy=proxy
    )
    return measurement, read_latencies, write_latencies


def _prime_cache_reads(
    cache_collection: CachedCollection[dict[str, Any]],
    *,
    dataset: SeededDataset,
    read_ids: Sequence[object],
    warmup_reads: NonNegativeInt,
) -> None:
    if read_ids:
        distinct_ids = list(dict.fromkeys(read_ids))
        for document_id in distinct_ids:
            cache_collection.find_one({"_id": document_id})
        cache_collection.find_one({"_id": distinct_ids[0]})
        return
    warmup_id = dataset.ids[0]
    for _ in range(warmup_reads):
        cache_collection.find_one({"_id": warmup_id})


def _run_stream_watching_window(
    window: CompressionWindowSpec,
    dataset: SeededDataset,
    *,
    client: MongoClient[dict[str, Any]],
    database_name: str,
    replica_set: IsolatedReplicaSet,
    proxy: DirectPathByteProxy | None,
) -> tuple[
    ControlledMeasurement,
    list[OperationLatency],
    list[OperationLatency],
    tuple[NonNegativeFloat, ...],
]:
    with CacheManager(client) as manager:
        cache_collection = manager[database_name][_COLLECTION_NAME]
        raw_collection = manager[database_name].raw[_COLLECTION_NAME]

        read_ids = sample_operation_ids(
            dataset, window.sampling.reads, seed=window.seed
        )

        before = manager.cache_core.snapshot()
        _prime_cache_reads(
            cache_collection,
            dataset=dataset,
            read_ids=read_ids,
            warmup_reads=window.warmup.reads,
        )
        after = manager.cache_core.snapshot()
        verify_primed(before, after, variant_name=window.name)

        active = manager.cache_core.active_stream_cost_databases()
        if active != [database_name]:
            message = (
                f"expected exactly one stream serving database {database_name!r}, "
                f"found active streams for {active}"
            )
            raise BenchmarkSetupError(message)

        read_latencies: list[OperationLatency] = []
        write_latencies: list[OperationLatency] = []
        invalidation_latencies: tuple[NonNegativeFloat, ...] = ()

        def _operation() -> None:
            nonlocal invalidation_latencies
            _issue_cache_reads(
                cache_collection, manager, read_ids, latencies=read_latencies
            )
            actual_offsets, start_monotonic = _issue_scheduled_writes(
                raw_collection, dataset, window, latencies=write_latencies
            )
            if window.kind is WorkloadKind.IDLE:
                time.sleep(window.duration_seconds)
            elif actual_offsets:  # pragma: no branch - writes always scheduled
                wait_for_invalidations_to_settle(
                    manager,
                    database_name,
                    len(actual_offsets),
                    context=window.name,
                )
                readings = manager.cache_core.stream_cost_snapshot(
                    database_name
                ).invalidation_apply_readings
                invalidation_latencies = _invalidation_latencies(
                    actual_offsets, start_monotonic, readings
                )

        _, measurement = measure_controlled(
            _operation, replica_set=replica_set, proxy=proxy
        )

        active = manager.cache_core.active_stream_cost_databases()
        if active != [database_name]:  # pragma: no cover - stream never fails here
            message = (
                f"stream serving database {database_name!r} was no longer healthy "
                f"after sampling; active streams: {active}"
            )
            raise BenchmarkSetupError(message)

    return measurement, read_latencies, write_latencies, invalidation_latencies


def run_compression_window(
    window: CompressionWindowSpec,
    *,
    mode: WireCompressor,
    path: WirePath,
    block_index: NonNegativeInt,
    client: MongoClient[dict[str, Any]],
    replica_set: IsolatedReplicaSet,
    proxy: DirectPathByteProxy | None,
    database_name: str,
) -> CompressionWindowResult:
    database = client[database_name]
    database.drop_collection(_COLLECTION_NAME)
    dataset = _seed_window_dataset(window)
    insert_dataset(database[_COLLECTION_NAME], dataset)

    if path is WirePath.NO_STREAM:
        measurement, read_latencies, write_latencies = _run_no_stream_window(
            window,
            dataset,
            collection=database[_COLLECTION_NAME],
            replica_set=replica_set,
            proxy=proxy,
        )
        invalidation_latencies: tuple[NonNegativeFloat, ...] = ()
    else:
        measurement, read_latencies, write_latencies, invalidation_latencies = (
            _run_stream_watching_window(
                window,
                dataset,
                client=client,
                database_name=database_name,
                replica_set=replica_set,
                proxy=proxy,
            )
        )

    return CompressionWindowResult(
        window=window,
        mode=mode,
        path=path,
        block_index=block_index,
        measurement=measurement,
        read_latencies=tuple(read_latencies),
        write_latencies=tuple(write_latencies),
        invalidation_latencies_seconds=invalidation_latencies,
        reads_issued=len(read_latencies),
        writes_issued=len(write_latencies),
    )


def run_compression_mode_block(
    windows: Sequence[CompressionWindowSpec],
    *,
    mode: WireCompressor,
    path_order: tuple[WirePath, WirePath],
    block_index: NonNegativeInt,
    client: MongoClient[dict[str, Any]],
    admin_client: MongoClient[dict[str, Any]],
    replica_set: IsolatedReplicaSet,
    proxy: DirectPathByteProxy | None,
    database_prefix: str,
) -> tuple[CompressorPreflightResult, tuple[CompressionWindowResult, ...]]:
    preflight_database = f"{database_prefix}_preflight"
    negotiation = verify_compressor_negotiation(
        client, admin_client, compressor=mode, database_name=preflight_database
    )
    compression_window_results: list[CompressionWindowResult] = []
    for window in windows:
        for path in path_order:
            database_name = f"{database_prefix}_{window.name}_{path.value}"
            compression_window_results.append(
                run_compression_window(
                    window,
                    mode=mode,
                    path=path,
                    block_index=block_index,
                    client=client,
                    replica_set=replica_set,
                    proxy=proxy,
                    database_name=database_name,
                )
            )
    return negotiation, tuple(compression_window_results)
