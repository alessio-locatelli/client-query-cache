from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pymongo import ReadPreference

from benchmarks.stream_cost.calibration import (
    CalibrationSeries,
    sample_clock_offset,
)
from benchmarks.stream_cost.consolidated_stream import (
    PairVariant,
    UnrelatedWriteWorkload,
    replay_write_schedule,
    reset_run_state,
    verify_relevant_write_counts_match,
    verify_single_consolidated_stream,
    verify_unrelated_write_minimum,
)
from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pymongo import MongoClient

    from benchmarks.stream_cost.calibration import TopologyChangeListener
    from benchmarks.stream_cost.consolidated_stream import (
        ConsolidatedStreamPairConfig,
    )
    from mongo_client_cache.synchronous.manager import CacheManager

_CALIBRATION_ROUNDS = 5
_MINIMUM_RELEVANT_COLLECTIONS = 2


def _send_hello(client: MongoClient[dict[str, Any]]) -> Mapping[str, object]:
    return client.admin.command("hello", read_preference=ReadPreference.PRIMARY)


@dataclass(frozen=True, slots=True)
class RunResult:
    variant: PairVariant
    relevant_write_count: int
    unrelated_write_count_during_window: int
    raw_lag_windows: tuple[tuple[float, ...], ...]


def _activate_consolidated_stream(
    manager: CacheManager[dict[str, Any]],
    *,
    database: str,
    relevant_collection_names: Sequence[str],
) -> None:
    for name in relevant_collection_names:
        manager[database][name].find({})
    verify_single_consolidated_stream(manager, database=database)


def _run_single(
    client: MongoClient[dict[str, Any]],
    previous_manager: CacheManager[dict[str, Any]] | None,
    *,
    database: str,
    relevant_collection_names: Sequence[str],
    unrelated_collection_name: str,
    config: ConsolidatedStreamPairConfig,
    schedule: Sequence[float],
    variant: PairVariant,
) -> tuple[CacheManager[dict[str, Any]], RunResult]:
    manager = reset_run_state(client, previous_manager, database=database)
    _activate_consolidated_stream(
        manager, database=database, relevant_collection_names=relevant_collection_names
    )
    time.sleep(config.warmup_duration_seconds)

    unrelated_writer: UnrelatedWriteWorkload | None = None
    window_start_count = 0
    if variant is PairVariant.LOADED:
        unrelated_writer = UnrelatedWriteWorkload(
            manager[database].raw[unrelated_collection_name],
            interval_seconds=config.unrelated_write_interval_seconds,
        )
        unrelated_writer.start()
        window_start_count = unrelated_writer.count

    relevant_collection = manager[database].raw[relevant_collection_names[0]]

    def _issue_relevant_write() -> None:
        relevant_collection.update_one(
            {"_id": "relevant"}, {"$inc": {"touched": 1}}, upsert=True
        )

    start_monotonic = time.monotonic()
    replay_write_schedule(
        _issue_relevant_write,
        schedule,
        start_monotonic=start_monotonic,
        tolerance_seconds=config.relevant_write_schedule_tolerance_seconds,
    )

    unrelated_count_during_window = 0
    if unrelated_writer is not None:
        unrelated_count_during_window = unrelated_writer.stop() - window_start_count
        verify_unrelated_write_minimum(
            unrelated_count_during_window,
            minimum_count=config.unrelated_write_minimum_count,
        )

    snapshot = manager.cache_core.stream_cost_snapshot(database)
    run_result = RunResult(
        variant=variant,
        relevant_write_count=len(schedule),
        unrelated_write_count_during_window=unrelated_count_during_window,
        raw_lag_windows=snapshot.invalidation_lag_windows,
    )
    return manager, run_result


@dataclass(frozen=True, slots=True)
class PairResult:
    control: RunResult
    loaded: RunResult
    calibration: CalibrationSeries


def run_consolidated_stream_pair(
    client: MongoClient[dict[str, Any]],
    listener: TopologyChangeListener,
    *,
    database: str,
    relevant_collection_names: Sequence[str],
    unrelated_collection_name: str,
    config: ConsolidatedStreamPairConfig,
    schedule: Sequence[float],
    order: tuple[PairVariant, PairVariant],
) -> PairResult:
    if len(relevant_collection_names) < _MINIMUM_RELEVANT_COLLECTIONS:
        message = (
            f"relevant_collection_names must name at least "
            f"{_MINIMUM_RELEVANT_COLLECTIONS} collections to characterize a "
            "consolidated stream"
        )
        raise BenchmarkConfigurationError(message)

    calibration_points = [
        sample_clock_offset(lambda: _send_hello(client), rounds=_CALIBRATION_ROUNDS)
    ]
    manager: CacheManager[dict[str, Any]] | None = None
    run_results_by_variant: dict[PairVariant, RunResult] = {}
    try:
        for variant in order:
            manager, run_result = _run_single(
                client,
                manager,
                database=database,
                relevant_collection_names=relevant_collection_names,
                unrelated_collection_name=unrelated_collection_name,
                config=config,
                schedule=schedule,
                variant=variant,
            )
            run_results_by_variant[variant] = run_result
            calibration_points.append(
                sample_clock_offset(
                    lambda: _send_hello(client), rounds=_CALIBRATION_ROUNDS
                )
            )
    finally:
        # order always has two entries, so a successful loop always assigns
        # manager; it can only still be None here while an exception from
        # the first run is propagating, which skips past this function
        # entirely rather than falling through to the checks below.
        if manager is not None:  # pragma: no branch
            manager.close()

    series = CalibrationSeries(points=tuple(calibration_points))
    if listener.primary_changed or series.has_election_change:
        message = (
            "the replica set's primary changed during the calibration-to-pair "
            "interval; the shared clock offset no longer corresponds to the "
            "stream's event source for both runs"
        )
        raise BenchmarkSetupError(message)
    if series.exceeds_drift_tolerance(config.clock_drift_tolerance_seconds):
        message = (
            "clock drift between calibration samples exceeded the pre-registered "
            "tolerance"
        )
        raise BenchmarkSetupError(message)
    if series.has_host_clock_step(
        tolerance_seconds=config.clock_drift_tolerance_seconds
    ):
        message = (
            "the benchmark host's wall clock was stepped during the "
            "calibration-to-pair interval"
        )
        raise BenchmarkSetupError(message)

    verify_relevant_write_counts_match(
        run_results_by_variant[PairVariant.CONTROL].relevant_write_count,
        run_results_by_variant[PairVariant.LOADED].relevant_write_count,
        tolerance=config.relevant_write_count_tolerance,
    )

    return PairResult(
        control=run_results_by_variant[PairVariant.CONTROL],
        loaded=run_results_by_variant[PairVariant.LOADED],
        calibration=series,
    )
