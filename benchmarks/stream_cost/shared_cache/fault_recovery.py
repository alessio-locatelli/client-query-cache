from __future__ import annotations

import multiprocessing
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, TypedDict, cast

from pymongo import MongoClient
from pymongo.errors import (
    AutoReconnect,
    ConnectionFailure,
    NetworkTimeout,
    PyMongoError,
)

from benchmarks.stream_cost.calibration import (
    CalibrationPoint,
    PairedReading,
    PeriodicCalibrationSampler,
    host_clock_stepped,
)
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.measurement import scalar_latency_distribution
from benchmarks.stream_cost.multiprocess_run import WireCommands
from benchmarks.stream_cost.shared_cache.dataset import seed_catalogue
from benchmarks.stream_cost.shared_cache.fault_timeline import (
    classify_requests,
    detect_recovery,
    merge_chunks,
    stream_reopening_counts,
    validate_request_counts,
)
from benchmarks.stream_cost.shared_cache.window import (
    ProcessGroup,
    _client_options,
    _count,
    _spec,
    _workload,
)
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ReplicaSetTopology
from client_query_cache._types import (
    BsonDict,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from multiprocessing.context import SpawnContext

    from pymongo.synchronous.collection import Collection

    from benchmarks.stream_cost.shared_cache.protocol import (
        RecoveryFaultCell,
        Registration,
    )
    from benchmarks.stream_cost.shared_cache.window import _Workload
    from benchmarks.stream_cost.shared_cache.worker import WorkerSpec

type Payload = dict[str, object]


class _InjectionState(TypedDict):
    offset: NonNegativeFloat
    snapshots: list[Payload]


type OperationTime = tuple[NonNegativeInt, NonNegativeInt]
type FaultTopology = IsolatedReplicaSet | ReplicaSetTopology

_SERVER_ERROR_CODES: dict[NonNegativeInt, str] = {
    6: "AutoReconnect",
    7: "AutoReconnect",
    43: "CursorNotFound",
    89: "NetworkTimeout",
    237: "CursorKilled",
    91: "AutoReconnect",
    10107: "NotWritablePrimary",
    11600: "AutoReconnect",
    11602: "InterruptedDueToReplStateChange",
    189: "PrimarySteppedDown",
    286: "ChangeStreamHistoryLost",
}


def invalidation_bounds(
    writes: Iterable[Payload], stream_start: OperationTime
) -> Payload:
    lower = 0
    ambiguous = 0
    unknown = 0
    for write in writes:
        state = cast("str", write["state"])
        if state == "unknown":
            unknown += 1
        elif state == "acknowledged":
            operation_time = cast("OperationTime", write["operation_time"])
            if operation_time > stream_start:
                lower += 1
            elif operation_time == stream_start:
                ambiguous += 1
    return {
        "lower": lower,
        "upper": lower + ambiguous + unknown,
        "ambiguous": ambiguous,
        "unknown": unknown,
    }


def _operation_time(value: object) -> OperationTime:
    timestamp = cast("tuple[int, int]", value)
    if len(timestamp) != 2:
        raise BenchmarkSetupError("change stream opening has an invalid operationTime")
    return timestamp


def _failure_counts(snapshot: Payload) -> dict[str, NonNegativeInt]:
    return cast("dict[str, NonNegativeInt]", snapshot["command_failures"])


def _failure_delta(before: Payload, after: Payload) -> dict[str, NonNegativeInt]:
    initial = _failure_counts(before)
    deltas: dict[str, NonNegativeInt] = {}
    for label, count in _failure_counts(after).items():
        try:
            previous = initial[label]
        except KeyError:
            previous = 0
        delta = count - previous
        if delta > 0:
            deltas[label] = delta
    return deltas


def _validate_initial_workers(
    ready: list[Payload], snapshots: list[Payload], *, path: str
) -> None:
    expected_streams = 1 if path == "independent" else 0
    if any(_count(worker, "streams") != expected_streams for worker in ready):
        raise BenchmarkSetupError("initial worker stream ownership is incorrect")
    if path == "independent" and any(
        not cast("list[object]", worker["stream_operation_times"])
        for worker in snapshots
    ):
        raise BenchmarkSetupError("independent worker stream did not open")


def _join_write_scheduler(
    write_scheduler: threading.Thread,
    timeout: NonNegativeFloat,
    *,
    during_cleanup: bool,
) -> None:
    write_scheduler.join(timeout)
    if write_scheduler.is_alive():
        message = (
            "fault write scheduler did not stop during cleanup"
            if during_cleanup
            else "registered write schedule did not finish"
        )
        raise BenchmarkSetupError(message)


def _scheduled_write_records(
    schedule: _WriteSchedule,
) -> list[Payload]:
    if schedule.errors:
        raise BenchmarkSetupError(schedule.errors[0])
    return [future.result() for future in schedule.futures]


def _injection_state(injector: _FaultInjection) -> _InjectionState:
    if injector.offset is None or injector.snapshots is None:
        raise BenchmarkSetupError("fault injection did not run")
    return {"offset": injector.offset, "snapshots": injector.snapshots}


def _validate_trial_counts(
    requests: list[Payload], offered: NonNegativeInt, reported_counts: Payload
) -> None:
    if validate_request_counts(requests, offered) != reported_counts:
        raise BenchmarkSetupError("per-worker and trial request counts differ")


def _validate_request_counts_without_kill(counts: Payload) -> None:
    if cast("int", counts["interrupted"]) or cast("int", counts["undelivered"]):
        raise BenchmarkSetupError(
            "fault timeline has unresolved requests without a kill"
        )


def _require_stepdown_changed(
    fault_case: str, primary_before: str | None, primary_after: str | None
) -> None:
    if fault_case == "stepdown" and primary_after == primary_before:
        raise BenchmarkSetupError("stepdown primary identity did not change")


def _probe_acknowledged_writes(
    group: ProcessGroup, acknowledged_keys: tuple[NonNegativeInt, ...]
) -> list[Payload]:
    if not acknowledged_keys:
        return []
    revisions = dict.fromkeys(acknowledged_keys, 1)
    return group.control_workers("probe", keys=acknowledged_keys, revisions=revisions)


def _reject_pre_fault_failures(initial: list[Payload], at_fault: list[Payload]) -> None:
    for before, current in zip(initial, at_fault, strict=True):
        if _failure_delta(before, current):
            raise BenchmarkSetupError("wire command failed before fault injection")


def _registered_error(error: str, classes: frozenset[str]) -> bool:
    if any(name in error for name in classes):
        return True
    parts = error.split(":")
    if len(parts) < 3:
        return False
    for part in parts[2:]:
        try:
            code = int(part)
        except ValueError:
            continue
        try:
            error_class = _SERVER_ERROR_CODES[code]
        except KeyError:
            continue
        if error_class in classes:
            return True
    return False


def validate_fault_errors(
    requests: Iterable[Payload],
    failures: dict[str, NonNegativeInt],
    *,
    classes: frozenset[str],
    injection_offset: NonNegativeFloat,
) -> None:
    for request in requests:
        if request["state"] != "failed":
            continue
        if cast("float", request["completed_offset"]) < injection_offset:
            raise BenchmarkSetupError("read failed before fault injection")
        error = cast("str", request["error"])
        if error not in classes:
            message = f"unregistered read error class: {error}"
            raise BenchmarkSetupError(message)
    for failure, count in failures.items():
        if count and not _registered_error(failure, classes):
            message = f"unregistered wire command failure after injection: {failure}"
            raise BenchmarkSetupError(message)


def post_recovery_correctness(
    probes: list[Payload],
    *,
    expected_writes: NonNegativeInt,
    acknowledged_writes: NonNegativeInt,
    invalidation_drain_passed: bool,
) -> Payload:
    available = acknowledged_writes > 0
    probe_passed = bool(probes) and all(
        probe["probe_ok"] is True and probe["probed"] == acknowledged_writes
        for probe in probes
    )
    return {
        "available": available,
        "passed": (invalidation_drain_passed and probe_passed if available else None),
        "expected_writes": expected_writes,
        "probed": sum(cast("int", probe["probed"]) for probe in probes),
        "acknowledged_writes": acknowledged_writes,
        "invalidation_drain_passed": invalidation_drain_passed,
        "workers": probes,
    }


def _write_one(
    client: MongoClient[BsonDict], collection: Collection[BsonDict], target: int
) -> Payload:
    started = time.monotonic()
    with client.start_session() as session:
        try:
            collection.update_one(
                {"_id": target}, {"$inc": {"revision": 1}}, session=session
            )
        except PyMongoError as error:
            unknown = isinstance(
                error, (AutoReconnect, ConnectionFailure, NetworkTimeout)
            ) or error.has_error_label("RetryableWriteError")
            return {
                "state": "unknown" if unknown else "failed",
                "error": type(error).__name__,
                "seconds": time.monotonic() - started,
            }
        operation_time = session.operation_time
        if operation_time is None:
            return {
                "state": "failed",
                "error": "MissingOperationTime",
                "seconds": time.monotonic() - started,
            }
        return {
            "state": "acknowledged",
            "operation_time": (operation_time.time, operation_time.inc),
            "seconds": time.monotonic() - started,
        }


@dataclass(slots=True)
class _WriteSchedule:
    client: MongoClient[BsonDict]
    collection: Collection[BsonDict]
    writes: tuple[tuple[NonNegativeFloat, NonNegativeInt], ...]
    window_start: NonNegativeFloat
    tolerance: PositiveFloat
    futures: list[Future[Payload]]
    lock: threading.Lock
    errors: list[str]
    stop: threading.Event

    def run(self) -> None:
        with ThreadPoolExecutor(max_workers=4) as executor:
            for offset, target in self.writes:
                due = self.window_start + offset
                while (remaining := due - time.monotonic()) > 0:
                    if self.stop.wait(min(remaining, 0.01)):
                        return
                issued = time.monotonic()
                if issued - due > self.tolerance and not self.errors:
                    self.errors.append("write schedule exceeded tolerance")
                future = executor.submit(
                    _write_one, self.client, self.collection, target
                )
                with self.lock:
                    self.futures.append(future)


def _probe_keys(
    workload_keys: tuple[NonNegativeInt, ...],
    writes: tuple[tuple[NonNegativeFloat, NonNegativeInt], ...],
) -> tuple[NonNegativeInt, ...]:
    written = frozenset(target for _offset, target in writes)
    selected = tuple(key for key in workload_keys if key not in written)[:16]
    if len(selected) != 16:
        raise BenchmarkSetupError("hot working set has fewer than 16 probe keys")
    return selected


def _remaining_ordinals(
    cell: RecoveryFaultCell, killed_at: NonNegativeFloat
) -> tuple[NonNegativeInt, ...]:
    if cell.rate is None:
        raise BenchmarkSetupError("fault cell has no registered offered rate")
    offered = round(cell.rate * cell.window_seconds)
    return tuple(
        ordinal
        for ordinal in range(0, offered, cell.workers)
        if ordinal / cell.rate >= killed_at
    )


def _timeline_cadence(registration: Registration) -> PositiveFloat:
    return cast(
        "PositiveFloat",
        registration.section("fault_recovery")["timeline_cadence_seconds"],
    )


@dataclass(slots=True)
class _FaultInjection:
    group: ProcessGroup
    replica: FaultTopology
    registration: Registration
    cell: RecoveryFaultCell
    workload: _Workload
    initial: list[Payload]
    primary_before: str | None
    start: NonNegativeFloat
    window_start: NonNegativeFloat
    window_end: NonNegativeFloat
    executor: ThreadPoolExecutor
    offset: NonNegativeFloat | None = None
    snapshots: list[Payload] | None = None
    killed_at: NonNegativeFloat | None = None
    replacement_future: Future[Payload] | None = None
    primary_after: str | None = None

    def inject(self) -> None:
        self.snapshots = self.group.control_workers("snapshot")
        _reject_pre_fault_failures(self.initial, self.snapshots)
        if (
            self.primary_before is not None
            and _primary(self.replica) != self.primary_before
        ):
            raise BenchmarkSetupError("primary changed before fault injection")
        match self.cell.fault_case:
            case "connection-loss":
                responses = self.group.control_workers("sever")
                self._record_injection(
                    min(
                        cast("NonNegativeFloat", response["action_monotonic"])
                        for response in responses
                    )
                )
            case "history-loss":
                responses = self.group.control_workers("lose-history")
                self._record_injection(
                    min(
                        cast("NonNegativeFloat", response["action_monotonic"])
                        for response in responses
                    )
                )
                self.group.control_workers("sever")
            case "stepdown":
                if not isinstance(self.replica, ReplicaSetTopology):
                    raise BenchmarkSetupError(
                        "stepdown cell has no multi-member topology"
                    )
                if self.primary_before is None:
                    raise BenchmarkSetupError("stepdown has no initial primary")
                self._record_injection(self.replica.step_down_primary())
                self.primary_after = _wait_for_primary_change(
                    self.replica,
                    self.primary_before,
                    time.monotonic() + self.registration.number("startup_seconds"),
                )
            case "worker-restart":
                self._replace_worker()
            case _:
                raise BenchmarkSetupError("unknown worker fault case")

    def _record_injection(self, actual: NonNegativeFloat) -> None:
        lateness = actual - (self.window_start + self.cell.injection_offset_seconds)
        if lateness > self.registration.number("schedule_tolerance_seconds"):
            raise BenchmarkSetupError("fault injection missed its registered offset")
        self.offset = actual - self.window_start

    def _replace_worker(self) -> None:
        def mark_kill(killed_at: NonNegativeFloat) -> None:
            self._record_injection(killed_at)
            self.killed_at = killed_at - self.window_start

        def replacement_spec(killed_at: NonNegativeFloat) -> WorkerSpec:
            killed_offset = killed_at - self.window_start
            return _spec(
                self.registration,
                self.cell,
                self.workload,
                self.replica.uri,
                index=0,
                attachment=None,
                timeline_enabled=True,
                timeline_cadence_seconds=_timeline_cadence(self.registration),
                scheduled_ordinals=_remaining_ordinals(self.cell, killed_offset),
            )

        self.group.kill_and_replace(
            0,
            spec_factory=replacement_spec,
            before_kill=mark_kill,
        )
        self.replacement_future = self.executor.submit(self._replacement_ready)

    def _replacement_ready(self) -> Payload:
        ready_message = self.group.collect_worker(
            0,
            "ready",
            self.window_end + self.registration.number("startup_seconds"),
            drain_timelines=False,
        )
        self.group.connections[0].send(self.start)
        return {
            "ready": ready_message,
            "offset": time.monotonic() - self.window_start,
        }


def _server_cpu(replica: FaultTopology) -> NonNegativeFloat:
    if isinstance(replica, ReplicaSetTopology):
        return sum(replica.container_cpu_usage_seconds(index) for index in range(3))
    return replica.container_cpu_usage_seconds()


def _server_memory(replica: FaultTopology) -> NonNegativeInt:
    if isinstance(replica, ReplicaSetTopology):
        return sum(replica.container_memory_usage_bytes(index) for index in range(3))
    return replica.container_memory_usage_bytes()


def _primary(replica: FaultTopology) -> str | None:
    return (
        replica.primary_identity() if isinstance(replica, ReplicaSetTopology) else None
    )


def _wait_for_primary_change(
    replica: ReplicaSetTopology,
    previous: str,
    deadline: NonNegativeFloat,
) -> str:
    while time.monotonic() < deadline:
        try:
            current = replica.primary_identity()
        except PyMongoError:
            time.sleep(0.05)
            continue
        if current != previous:
            return current
        time.sleep(0.05)
    raise BenchmarkSetupError("stepdown did not elect a different primary")


def _check_clock(
    points: tuple[CalibrationPoint, ...],
    *,
    case: str,
    tolerance: PositiveFloat,
) -> None:
    samples = [sample for point in points for sample in point.rounds]
    if not samples:
        raise BenchmarkSetupError("fault window collected no clock calibration samples")
    first = samples[0]
    for sample in samples:
        if host_clock_stepped(
            PairedReading(sample.wall_t0, sample.monotonic_t0),
            PairedReading(sample.wall_t1, sample.monotonic_t1),
            tolerance_seconds=tolerance,
        ) or host_clock_stepped(
            PairedReading(first.wall_t0, first.monotonic_t0),
            PairedReading(sample.wall_t0, sample.monotonic_t0),
            tolerance_seconds=tolerance,
        ):
            raise BenchmarkSetupError("host clock stepped during fault window")
    offsets: dict[object, CalibrationPoint] = {}
    for point in points:
        sample = point.selected
        election = sample.election_id
        try:
            initial = offsets[election]
        except KeyError:
            offsets[election] = point
        else:
            initial_sample = initial.selected
            allowed_difference = (
                tolerance
                + initial_sample.uncertainty_seconds
                + sample.uncertainty_seconds
            )
            if abs(sample.offset_seconds - initial_sample.offset_seconds) > (
                allowed_difference
            ):
                raise BenchmarkSetupError("server clock drift exceeded tolerance")
    if case != "stepdown" and len(offsets) > 1:
        raise BenchmarkSetupError("an election occurred outside the stepdown case")
    if case == "stepdown" and len(offsets) > 2:
        raise BenchmarkSetupError("multiple elections occurred during stepdown trial")


def _latest_snapshot(snapshots: list[Payload]) -> Payload:
    if not snapshots:
        raise BenchmarkSetupError("fault window collected no worker snapshots")
    return snapshots[-1]


def _latency_intervals(
    requests: list[Payload],
    injection: NonNegativeFloat,
    recovery_offset: NonNegativeFloat | None,
    window_end: NonNegativeFloat,
) -> Payload:
    intervals: dict[str, list[float]] = {
        name: [] for name in ("before", "during", "after")
    }
    for request in requests:
        if request["state"] != "completed":
            continue
        scheduled = cast("float", request["scheduled_offset"])
        latency = cast("float", request["completed_offset"]) - scheduled
        if injection - 10.0 <= scheduled < injection:
            intervals["before"].append(latency)
        elif scheduled >= injection and (
            recovery_offset is None or scheduled < recovery_offset
        ):
            intervals["during"].append(latency)
        elif recovery_offset is not None and recovery_offset <= scheduled < min(
            window_end, recovery_offset + 10.0
        ):
            intervals["after"].append(latency)
    return {
        name: scalar_latency_distribution(values) if values else None
        for name, values in intervals.items()
    }


def _control_invalidation(snapshot: Payload) -> NonNegativeInt:
    return cast("int", snapshot["invalidations"])


def _control_stream_start(snapshot: Payload) -> OperationTime:
    starts = cast("list[OperationTime]", snapshot["stream_operation_times"])
    if not starts:
        raise BenchmarkSetupError("cached worker has no stream lifetime operationTime")
    return _operation_time(starts[-1])


def _wait_for_post_writes(
    group: ProcessGroup,
    *,
    baseline: list[Payload],
    expected: tuple[NonNegativeInt, ...],
    deadline: NonNegativeFloat,
) -> list[Payload]:
    while True:
        current = group.control_workers("snapshot")
        if all(
            _control_invalidation(snapshot) - _control_invalidation(before) >= count
            for before, snapshot, count in zip(baseline, current, expected, strict=True)
        ):
            return current
        if time.monotonic() >= deadline:
            return current
        time.sleep(0.05)


def run_recovery_fault_window(
    replica: FaultTopology,
    registration: Registration,
    cell: RecoveryFaultCell,
) -> Payload:
    if (cell.topology == "three-member") != isinstance(replica, ReplicaSetTopology):
        raise BenchmarkSetupError("fault cell topology does not match its replica set")
    if cell.path not in {"direct", "independent"}:
        raise BenchmarkSetupError("worker fault trials support baseline paths only")
    if cell.rate is None:
        raise BenchmarkSetupError("fault cell has no registered offered rate")
    database = cast("str", registration.raw["database"])
    collection_name = cast("str", registration.raw["collection"])
    client_options = _client_options(
        replica, dict(registration.section("client_options"))
    )
    listener = WireCommands((collection_name,))
    with (
        MongoClient[BsonDict](
            replica.uri,
            event_listeners=[listener],
            **client_options,  # type: ignore[arg-type]
        ) as writer,
        ExitStack() as cleanup,
    ):
        dataset = seed_catalogue(
            writer,
            database=database,
            collection=collection_name,
            seed=cast("int", registration.raw["seed"]),
            profile=registration.profile(cell.profile),  # type: ignore[arg-type]
            categories=registration.categories,
        )
        workload = _workload(registration, cell)
        options = dict(registration.section("client_options"))
        options["serverSelectionTimeoutMS"] = max(
            30000,
            cast("int", options["serverSelectionTimeoutMS"]),
        )
        options = _client_options(replica, options)
        observer = MongoClient[BsonDict](replica.uri, **options)  # type: ignore[arg-type]
        cleanup.callback(observer.close)
        sampler = PeriodicCalibrationSampler(
            lambda: observer.admin.command("hello"),
            cadence_seconds=registration.number("calibration_seconds"),
            rounds=3,
            ignore_non_primary=cell.fault_case == "stepdown",
        )
        sampler.start()
        sampler_stopped = False

        def stop_sampler() -> tuple[CalibrationPoint, ...]:
            nonlocal sampler_stopped
            if not sampler_stopped:
                sampler_stopped = True
                return sampler.stop()
            return ()

        cleanup.callback(stop_sampler)
        context: SpawnContext = multiprocessing.get_context("spawn")
        start_timeout = time.monotonic() + registration.number("startup_seconds")
        with (
            ThreadPoolExecutor(max_workers=1) as replacement_executor,
            ProcessGroup(context, registration.number("shutdown_seconds")) as group,
        ):
            specs = [
                _spec(
                    registration,
                    cell,
                    workload,
                    replica.uri,
                    index=index,
                    attachment=None,
                    timeline_enabled=True,
                    timeline_cadence_seconds=_timeline_cadence(registration),
                )
                for index in range(cell.workers)
            ]
            for spec in specs:
                group.start_worker(spec)
            ready = group.collect("ready", start_timeout)
            initial = group.control_workers("snapshot")
            _validate_initial_workers(ready, initial, path=cell.path)
            start = time.monotonic() + 1.0
            for connection in group.connections:
                connection.send(start)
            window_start = start + cell.warmup_seconds
            window_end = window_start + cell.window_seconds
            schedule = _WriteSchedule(
                writer,
                writer[database][collection_name],
                workload.writes,
                window_start,
                registration.number("schedule_tolerance_seconds"),
                [],
                threading.Lock(),
                [],
                threading.Event(),
            )
            write_scheduler = threading.Thread(target=schedule.run, daemon=True)
            write_scheduler.start()

            def stop_write_scheduler() -> None:
                schedule.stop.set()
                _join_write_scheduler(
                    write_scheduler,
                    registration.number("drain_seconds") + 10.0,
                    during_cleanup=True,
                )

            cleanup.callback(stop_write_scheduler)
            server_before = {
                "cpu_seconds": _server_cpu(replica),
                "memory_bytes": _server_memory(replica),
            }
            primary_before = _primary(replica)
            injector = _FaultInjection(
                group=group,
                replica=replica,
                registration=registration,
                cell=cell,
                workload=workload,
                initial=initial,
                primary_before=primary_before,
                start=start,
                window_start=window_start,
                window_end=window_end,
                executor=replacement_executor,
            )
            while time.monotonic() < window_end:
                group.drain_timeline_chunks()
                if (
                    injector.offset is None
                    and time.monotonic() >= window_start + cell.injection_offset_seconds
                ):
                    injector.inject()
                time.sleep(min(0.01, max(0.0, window_end - time.monotonic())))
            injection = _injection_state(injector)
            killed_at = injector.killed_at
            replacement_future = injector.replacement_future
            _join_write_scheduler(
                write_scheduler,
                max(
                    0.0,
                    window_end
                    + registration.number("drain_seconds")
                    - time.monotonic(),
                ),
                during_cleanup=False,
            )
            if replacement_future is not None:
                replacement_message = replacement_future.result(
                    timeout=registration.number("startup_seconds")
                )
                replacement_ready_record = cast("Payload", replacement_message["ready"])
                replacement_ready_offset = cast("float", replacement_message["offset"])
            else:
                replacement_ready_record = None
                replacement_ready_offset = None
            drain_deadline = window_end + registration.number("drain_seconds") + 5.0
            samples = group.collect("sample", drain_deadline)
            final_states = group.control_workers("snapshot")
            timelines: list[Payload] = []
            requests: list[Payload] = []
            counts: Payload = {
                "completed": 0,
                "failed": 0,
                "interrupted": 0,
                "undelivered": 0,
            }
            for index in range(cell.workers):
                chunks = group.received_timeline(index)
                events, snapshots = merge_chunks(chunks)
                ordinals = tuple(
                    range(index, round(cell.rate * cell.window_seconds), cell.workers)
                )
                worker_requests = classify_requests(
                    ordinals,
                    events,
                    rate=cell.rate,
                    killed_at=killed_at if index == 0 else None,
                )
                worker_counts = validate_request_counts(worker_requests, len(ordinals))
                if index != 0 or killed_at is None:
                    _validate_request_counts_without_kill(worker_counts)
                for worker_state, count in worker_counts.items():
                    counts[worker_state] = cast("int", counts[worker_state]) + cast(
                        "int", count
                    )
                timelines.append(
                    {
                        "index": index,
                        "events": events,
                        "snapshots": snapshots,
                        "scheduled_ordinals": ordinals,
                        "killed_at": killed_at if index == 0 else None,
                        "replacement_ready_offset": replacement_ready_offset
                        if index == 0
                        else None,
                    }
                )
                requests.extend(worker_requests)
            offered = round(cell.rate * cell.window_seconds)
            _validate_trial_counts(requests, offered, counts)
            injection_offset = injection["offset"]
            stream_reopenings = stream_reopening_counts(
                timelines,
                injection_offset=injection_offset,
                window_end=cell.window_seconds,
            )
            classes_config = cast(
                "dict[str, object]",
                registration.section("fault_recovery")["error_classes"],
            )
            allowed = frozenset(cast("list[str]", classes_config[cell.fault_case]))
            failures_after: dict[str, NonNegativeInt] = {}
            injection_snapshots = injection["snapshots"]
            for before, after in zip(injection_snapshots, final_states, strict=True):
                for failure, count in _failure_delta(before, after).items():
                    try:
                        failures_after[failure] += count
                    except KeyError:
                        failures_after[failure] = count
            validate_fault_errors(
                requests,
                failures_after,
                classes=allowed,
                injection_offset=injection_offset,
            )
            points = stop_sampler()
            _check_clock(
                points,
                case=cell.fault_case,
                tolerance=registration.number("clock_tolerance_seconds"),
            )
            criterion = registration.recovery_criterion()
            recovery = detect_recovery(
                requests,
                injection_offset=injection_offset,
                deadline=injection_offset + cell.recovery_deadline_seconds,
                window_end=cell.window_seconds,
                before_seconds=cast(
                    "PositiveFloat",
                    registration.section("fault_recovery")["before_interval_seconds"],
                ),
                replacement_ready_offset=replacement_ready_offset,
                bucket_seconds=criterion.bucket_seconds,
                minimum_completion_fraction=criterion.minimum_completion_fraction,
                request_p99_multiple=criterion.request_p99_multiple,
                backlog_grace_p99_multiple=criterion.backlog_grace_p99_multiple,
            )
            primary_after = _primary(replica)
            _require_stepdown_changed(cell.fault_case, primary_before, primary_after)
            correctness: Payload = {
                "available": False,
                "passed": None,
                "probed": 0,
            }
            post_probe_writes: list[Payload] = []
            if recovery["recovered"]:
                probe_keys = _probe_keys(workload.keys, workload.writes)
                before_probe = (
                    group.control_workers("snapshot")
                    if cell.path == "independent"
                    else []
                )
                post_probe_writes.extend(
                    _write_one(writer, writer[database][collection_name], key)
                    for key in probe_keys
                )
                acknowledged_keys = tuple(
                    key
                    for key, write in zip(probe_keys, post_probe_writes, strict=True)
                    if write["state"] == "acknowledged"
                )
                if acknowledged_keys and cell.path == "independent":
                    acknowledged_writes = [
                        write
                        for write in post_probe_writes
                        if write["state"] == "acknowledged"
                    ]
                    expected_probe_writes = tuple(
                        cast(
                            "NonNegativeInt",
                            invalidation_bounds(
                                acknowledged_writes,
                                _control_stream_start(snapshot),
                            )["lower"],
                        )
                        for snapshot in before_probe
                    )
                    drained = _wait_for_post_writes(
                        group,
                        baseline=before_probe,
                        expected=expected_probe_writes,
                        deadline=time.monotonic()
                        + registration.number("drain_seconds"),
                    )
                    drain_passed = all(
                        _control_invalidation(after) - _control_invalidation(before)
                        >= expected
                        for before, after, expected in zip(
                            before_probe,
                            drained,
                            expected_probe_writes,
                            strict=True,
                        )
                    )
                    final_states = drained
                else:
                    drained = group.control_workers("snapshot")
                    drain_passed = True
                probes = _probe_acknowledged_writes(group, acknowledged_keys)
                correctness = post_recovery_correctness(
                    probes,
                    expected_writes=len(probe_keys),
                    acknowledged_writes=len(acknowledged_keys),
                    invalidation_drain_passed=drain_passed,
                )
            write_records = _scheduled_write_records(schedule)
            write_records.extend(post_probe_writes)
            stream_bounds: list[Payload] = []
            if cell.path == "independent":
                for snapshot_state in final_states:
                    start_operation_time = _control_stream_start(snapshot_state)
                    stream_bounds.append(
                        invalidation_bounds(write_records, start_operation_time)
                    )
            latest_snapshots = [
                _latest_snapshot(cast("list[Payload]", timeline["snapshots"]))
                for timeline in timelines
            ]
            for connection in group.connections:
                connection.send("continue")
            recovery_offset = (
                cast("float", recovery["recovery_offset"])
                if recovery["recovered"]
                else None
            )
            record: Payload = {
                **asdict(cell),
                "phase": cell.phase,
                "block": cell.block,
                "fault_case": cell.fault_case,
                "topology": cell.topology,
                "path": cell.path,
                "smoke": cell.smoke,
                "healthy": True,
                "outcome": "correctness-failure"
                if correctness["passed"] is False
                else "not-recovered"
                if not recovery["recovered"]
                else "recovered",
                "dataset": dataset,
                "primary_before": primary_before,
                "primary_after": primary_after,
                "injection": {
                    "registered_offset_seconds": cell.injection_offset_seconds,
                    "actual_offset_seconds": injection["offset"],
                    "case": cell.fault_case,
                    "injected": True,
                },
                "recovery": recovery,
                "requests": {
                    "offered": offered,
                    "counts": counts,
                    "timeline": timelines,
                    "latencies": _latency_intervals(
                        requests,
                        injection["offset"],
                        recovery_offset,
                        cell.window_seconds,
                    ),
                },
                "worker_details": {
                    "ready": ready,
                    "samples": samples,
                    "final_snapshots": final_states,
                    "timeline_latest": latest_snapshots,
                    "replacement_ready": replacement_ready_record,
                    "replacement_ready_offset": replacement_ready_offset,
                },
                "writes": {
                    "scheduled": len(workload.writes),
                    "outcomes": write_records,
                    "failed": sum(
                        write["state"] == "failed" for write in write_records
                    ),
                    "unknown": sum(
                        write["state"] == "unknown" for write in write_records
                    ),
                    "invalidation_bounds": stream_bounds,
                },
                "command_failures": failures_after,
                "fault_errors": sorted(allowed),
                "correctness": correctness,
                "server_cpu_seconds": _server_cpu(replica)
                - server_before["cpu_seconds"],
                "server_memory_bytes": server_before["memory_bytes"],
                "clock_samples": len(points),
                "clock_offset_seconds": points[0].selected.offset_seconds,
                "clock_uncertainty_seconds": max(
                    point.selected.uncertainty_seconds for point in points
                ),
                "worker_cpu_seconds": sum(
                    cast("float", sample["cpu_seconds"]) for sample in samples
                ),
                "stream_health": [snapshot["health"] for snapshot in latest_snapshots],
                "cache_hits": [snapshot["hits"] for snapshot in latest_snapshots],
                "stream_reopenings": sum(stream_reopenings),
                "stream_reopenings_by_worker": stream_reopenings,
                "cache_bypass_reasons": [
                    snapshot["bypass_reasons"] for snapshot in latest_snapshots
                ],
            }
            return record
