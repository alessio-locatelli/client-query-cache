from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pymongo import ReadPreference

from benchmarks.stream_cost.bootstrap import minimum_sample_count
from benchmarks.stream_cost.calibration import (
    CalibrationSeries,
    PeriodicCalibrationSampler,
)
from benchmarks.stream_cost.consolidated_stream import (
    PairVariant,
    UnrelatedWriteWorkload,
    counterbalanced_pair_order,
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
    from collections.abc import Callable, Mapping, Sequence

    from pymongo import MongoClient
    from pymongo.synchronous.collection import Collection

    from benchmarks.stream_cost.calibration import TopologyChangeListener
    from benchmarks.stream_cost.consolidated_stream import (
        ConsolidatedStreamPairConfig,
    )
    from mongo_client_cache._core.manager import CacheCoreConfig
    from mongo_client_cache.synchronous.manager import CacheManager

_CALIBRATION_ROUNDS = 5
_MINIMUM_RELEVANT_COLLECTIONS = 2
_STREAM_REGISTRATION_TIMEOUT_SECONDS = 15.0
_STREAM_REGISTRATION_POLL_INTERVAL_SECONDS = 0.05
_INVALIDATION_SETTLE_TIMEOUT_SECONDS = 15.0
_INVALIDATION_SETTLE_POLL_INTERVAL_SECONDS = 0.05
_RELEVANT_WRITE_DOCUMENT_ID = "relevant"


def _send_hello(client: MongoClient[dict[str, Any]]) -> Mapping[str, object]:
    return client.admin.command("hello", read_preference=ReadPreference.PRIMARY)


def _await_condition(
    predicate: Callable[[], bool],
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
    timeout_message: str,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(poll_interval_seconds)
    raise BenchmarkSetupError(timeout_message)


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
    # Seed the write-target document before the collection is ever read or
    # activated, so the scheduled relevant writes below are always plain
    # updates. Otherwise the very first scheduled write implicitly creates
    # the collection, and the server emits a "create" event in addition to
    # the write's own event — one extra invalidation beyond len(schedule)
    # that the settle-wait below does not account for.
    manager[database].raw[relevant_collection_names[0]].insert_one(
        {"_id": _RELEVANT_WRITE_DOCUMENT_ID, "touched": 0}
    )
    for name in relevant_collection_names:
        manager[database][name].find({})
    _await_condition(
        lambda: manager.cache_core.active_stream_cost_databases() == [database],
        timeout_seconds=_STREAM_REGISTRATION_TIMEOUT_SECONDS,
        poll_interval_seconds=_STREAM_REGISTRATION_POLL_INTERVAL_SECONDS,
        timeout_message=(
            f"the consolidated stream for database {database!r} did not "
            f"register within {_STREAM_REGISTRATION_TIMEOUT_SECONDS:.0f} seconds"
        ),
    )
    verify_single_consolidated_stream(manager, database=database)


def _warm_up_server(
    collection: Collection[dict[str, Any]], *, duration_seconds: float
) -> None:
    # A plain sleep does not touch the server at all: WiredTiger/OS page
    # cache warmth (the reason this phase exists, per this workload's
    # reset-does-not-clear-server-state design) only changes in response to
    # real traffic against the collection, so this issues read round trips
    # against the seeded relevant document for the configured duration.
    deadline = time.monotonic() + duration_seconds
    while time.monotonic() < deadline:
        collection.find_one({"_id": _RELEVANT_WRITE_DOCUMENT_ID})


def _execute_run(
    manager: CacheManager[dict[str, Any]],
    *,
    database: str,
    relevant_collection_names: Sequence[str],
    unrelated_collection_name: str,
    config: ConsolidatedStreamPairConfig,
    schedule: Sequence[float],
    variant: PairVariant,
) -> RunResult:
    _activate_consolidated_stream(
        manager, database=database, relevant_collection_names=relevant_collection_names
    )
    _warm_up_server(
        manager[database].raw[relevant_collection_names[0]],
        duration_seconds=config.warmup_duration_seconds,
    )

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
            {"_id": _RELEVANT_WRITE_DOCUMENT_ID}, {"$inc": {"touched": 1}}
        )

    unrelated_count_during_window = 0
    try:
        start_monotonic = time.monotonic()
        replay_write_schedule(
            _issue_relevant_write,
            schedule,
            start_monotonic=start_monotonic,
            tolerance_seconds=config.relevant_write_schedule_tolerance_seconds,
        )
        # The unrelated writer must still be running while these
        # invalidations are being applied, or the lag samples they produce
        # were never actually subjected to concurrent unrelated load.
        _await_condition(
            lambda: (
                manager.cache_core.stream_cost_snapshot(database).invalidations
                >= len(schedule)
            ),
            timeout_seconds=_INVALIDATION_SETTLE_TIMEOUT_SECONDS,
            poll_interval_seconds=_INVALIDATION_SETTLE_POLL_INTERVAL_SECONDS,
            timeout_message=(
                "not all scheduled relevant-write invalidations were applied "
                f"within {_INVALIDATION_SETTLE_TIMEOUT_SECONDS:.0f} seconds"
            ),
        )
        if unrelated_writer is not None:
            unrelated_count_during_window = unrelated_writer.stop() - window_start_count
            unrelated_writer = None
            verify_unrelated_write_minimum(
                unrelated_count_during_window,
                minimum_count=config.unrelated_write_minimum_count,
            )
    finally:
        if unrelated_writer is not None:
            unrelated_writer.stop()

    snapshot = manager.cache_core.stream_cost_snapshot(database)
    total_lag_samples = sum(len(window) for window in snapshot.invalidation_lag_windows)
    required_lag_samples = minimum_sample_count(config.acceptable_lag_percentile)
    if total_lag_samples < required_lag_samples:
        message = (
            f"only {total_lag_samples} invalidation-lag samples were captured for "
            f"this run, below the {required_lag_samples} required for the "
            f"{config.acceptable_lag_percentile:.2%} percentile to be defined"
        )
        raise BenchmarkSetupError(message)
    return RunResult(
        variant=variant,
        relevant_write_count=len(schedule),
        unrelated_write_count_during_window=unrelated_count_during_window,
        raw_lag_windows=snapshot.invalidation_lag_windows,
    )


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
    cache_config: CacheCoreConfig | None,
) -> tuple[CacheManager[dict[str, Any]], RunResult]:
    manager = reset_run_state(
        client, previous_manager, database=database, cache_config=cache_config
    )
    try:
        run_result = _execute_run(
            manager,
            database=database,
            relevant_collection_names=relevant_collection_names,
            unrelated_collection_name=unrelated_collection_name,
            config=config,
            schedule=schedule,
            variant=variant,
        )
    except BaseException:
        manager.close()
        raise
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
    cache_config: CacheCoreConfig | None = None,
) -> PairResult:
    if len(relevant_collection_names) < _MINIMUM_RELEVANT_COLLECTIONS:
        message = (
            f"relevant_collection_names must name at least "
            f"{_MINIMUM_RELEVANT_COLLECTIONS} collections to characterize a "
            "consolidated stream"
        )
        raise BenchmarkConfigurationError(message)
    if len(set(relevant_collection_names)) != len(relevant_collection_names):
        message = "relevant_collection_names must not contain duplicate names"
        raise BenchmarkConfigurationError(message)
    if unrelated_collection_name in relevant_collection_names:
        message = (
            "unrelated_collection_name must not be one of relevant_collection_names; "
            "writes to a relevant collection cannot stand in for unrelated traffic"
        )
        raise BenchmarkConfigurationError(message)
    if len(schedule) != config.relevant_write_count:
        message = (
            f"schedule has {len(schedule)} writes but config.relevant_write_count "
            f"is {config.relevant_write_count}; the replayed schedule must match "
            "the pre-registered relevant write count"
        )
        raise BenchmarkConfigurationError(message)

    listener.reset()
    sampler = PeriodicCalibrationSampler(
        lambda: _send_hello(client),
        cadence_seconds=config.calibration_cadence_seconds,
        rounds=_CALIBRATION_ROUNDS,
    )
    sampler.start()
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
                cache_config=cache_config,
            )
            run_results_by_variant[variant] = run_result
            sampler.sample_now()
    finally:
        try:
            calibration_points = sampler.stop()
        finally:
            # order always has two entries, so a successful loop always
            # assigns manager; it can only still be None here while an
            # exception from the first run is propagating, which skips past
            # this function entirely rather than falling through below.
            if manager is not None:  # pragma: no branch
                manager.close()

    series = CalibrationSeries(points=calibration_points)
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


def run_consolidated_stream_pairs(
    client: MongoClient[dict[str, Any]],
    listener: TopologyChangeListener,
    *,
    database: str,
    relevant_collection_names: Sequence[str],
    unrelated_collection_name: str,
    config: ConsolidatedStreamPairConfig,
    schedule: Sequence[float],
    cache_config: CacheCoreConfig | None = None,
) -> tuple[PairResult, ...]:
    orders = counterbalanced_pair_order(config.pair_count)
    return tuple(
        run_consolidated_stream_pair(
            client,
            listener,
            database=database,
            relevant_collection_names=relevant_collection_names,
            unrelated_collection_name=unrelated_collection_name,
            config=config,
            schedule=schedule,
            order=order,
            cache_config=cache_config,
        )
        for order in orders
    )
