from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace
from typing import TYPE_CHECKING, Self, cast
from unittest.mock import Mock

import pytest
from bson.timestamp import Timestamp
from pymongo.errors import AutoReconnect, PyMongoError

from benchmarks.stream_cost.calibration import CalibrationPoint, ClockSample
from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)
from benchmarks.stream_cost.shared_cache import fault_recovery as recovery
from benchmarks.stream_cost.shared_cache.fault_recovery import (
    _check_clock,
    _control_stream_start,
    _failure_delta,
    _FaultInjection,
    _injection_state,
    _join_write_scheduler,
    _latest_snapshot,
    _operation_time,
    _probe_acknowledged_writes,
    _probe_keys,
    _registered_error,
    _reject_pre_fault_failures,
    _remaining_ordinals,
    _require_stepdown_changed,
    _scheduled_write_records,
    _validate_initial_workers,
    _validate_request_counts_without_kill,
    _validate_trial_counts,
    _wait_for_post_writes,
    _wait_for_primary_change,
    _write_one,
    _WriteSchedule,
    invalidation_bounds,
    post_recovery_correctness,
    run_recovery_fault_window,
    validate_fault_errors,
)
from benchmarks.stream_cost.shared_cache.protocol import (
    RecoveryFaultCell,
    Registration,
    fault_recovery_cells,
)
from benchmarks.stream_cost.topology import (
    IsolatedReplicaSet,
    ReplicaSetTopology,
    ResourceLimits,
)
from client_query_cache._types import BsonDict, JsonDict, NonNegativeFloat

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from concurrent.futures import ThreadPoolExecutor

    from pymongo import MongoClient
    from pymongo.synchronous.collection import Collection

    from benchmarks.stream_cost.shared_cache.window import ProcessGroup, _Workload

pytestmark = pytest.mark.unit

_FAULT_REGISTRATION = Path("reports/worker-fault-recovery/v1/config.json")
_CURRENT_FAULT_REGISTRATION = Path("reports/worker-fault-recovery/v8/config.json")


def _fault_cell(case: str) -> tuple[Registration, RecoveryFaultCell]:
    registration = Registration.load(_FAULT_REGISTRATION)
    cell = next(
        cell
        for cell in fault_recovery_cells(registration, smoke=True)
        if cell.fault_case == case
    )
    return registration, cell


def test_v8_registration_pins_the_recovery_criterion() -> None:
    registration = Registration.load(_CURRENT_FAULT_REGISTRATION)
    criterion = registration.recovery_criterion()

    assert criterion.bucket_seconds == 1
    assert criterion.minimum_completion_fraction == pytest.approx(0.99)
    assert criterion.request_p99_multiple == 2
    assert criterion.backlog_grace_p99_multiple == 2


def test_v8_registration_requires_recovery_criterion() -> None:
    registration = Registration.load(_FAULT_REGISTRATION)
    raw = dict(registration.raw)
    raw["registration"] = 2

    with pytest.raises(
        BenchmarkConfigurationError,
        match="registration lacks its recovery criterion",
    ):
        Registration(raw, registration.digest)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("bucket_seconds", 0, id="zero-bucket"),
        pytest.param("minimum_completion_fraction", 0, id="zero-completion"),
        pytest.param("minimum_completion_fraction", 1.1, id="completion-over-one"),
        pytest.param("request_p99_multiple", 0, id="zero-p99-multiple"),
        pytest.param("backlog_grace_p99_multiple", -1, id="negative-backlog-grace"),
        pytest.param("request_p99_multiple", "invalid", id="non-numeric-p99"),
    ],
)
def test_v8_registration_rejects_invalid_recovery_criterion_values(
    field: str, value: object
) -> None:
    registration = Registration.load(_CURRENT_FAULT_REGISTRATION)
    raw = dict(registration.raw)
    settings = dict(cast("JsonDict", raw["fault_recovery"]))
    criterion = dict(cast("JsonDict", settings["recovery_criterion"]))
    criterion[field] = value
    settings["recovery_criterion"] = criterion
    raw["fault_recovery"] = settings

    with pytest.raises(
        BenchmarkConfigurationError, match="recovery criterion is invalid"
    ):
        Registration(raw, registration.digest)


def test_invalidation_bounds_use_strict_operation_time_and_include_unknowns() -> None:
    writes: list[JsonDict] = [
        {"state": "acknowledged", "operation_time": (9, 8)},
        {"state": "acknowledged", "operation_time": (10, 1)},
        {"state": "acknowledged", "operation_time": (10, 2)},
        {"state": "unknown", "operation_time": None},
        {"state": "failed", "operation_time": None},
    ]

    bounds = invalidation_bounds(writes, (10, 1))

    assert bounds == {"lower": 1, "upper": 3, "ambiguous": 1, "unknown": 1}


def test_operation_time_rejects_a_malformed_timestamp() -> None:
    with pytest.raises(BenchmarkSetupError, match="invalid operationTime"):
        _operation_time((1,))


def test_operation_time_preserves_valid_timestamp() -> None:
    assert _operation_time((7, 13)) == (7, 13)


def test_probe_keys_exclude_write_targets_and_require_sixteen_keys() -> None:
    writes = ((0.0, 0), (1.0, 1))

    assert _probe_keys(tuple(range(20)), writes) == tuple(range(2, 18))
    with pytest.raises(BenchmarkSetupError, match="fewer than 16 probe keys"):
        _probe_keys(tuple(range(16)), writes)


def test_remaining_ordinals_reject_cells_without_an_offered_rate() -> None:
    cell = cast(
        "RecoveryFaultCell",
        SimpleNamespace(rate=None, window_seconds=1.0, workers=4),
    )

    with pytest.raises(BenchmarkSetupError, match="no registered offered rate"):
        _remaining_ordinals(cell, 0.0)


def test_pre_fault_command_failures_are_rejected() -> None:
    with pytest.raises(BenchmarkSetupError, match="before fault injection"):
        _reject_pre_fault_failures(
            [{"command_failures": {}}],
            [{"command_failures": {"getMore:AutoReconnect": 1}}],
        )


def test_failure_deltas_ignore_unchanged_and_decreased_counters() -> None:
    initial: JsonDict = {"command_failures": {"getMore:AutoReconnect": 2}}

    assert _failure_delta(initial, initial) == {}
    assert (
        _failure_delta(initial, {"command_failures": {"getMore:AutoReconnect": 1}})
        == {}
    )


def test_registered_server_error_codes_must_match_the_allowed_class() -> None:
    assert _registered_error("find:Error:13", frozenset({"AutoReconnect"})) is False


@pytest.mark.parametrize(
    ("classes", "expected"),
    [
        pytest.param(frozenset({"NotWritablePrimary"}), True, id="registered"),
        pytest.param(frozenset({"AutoReconnect"}), False, id="different-class"),
    ],
)
def test_registered_server_error_code_maps_to_allowed_class(
    classes: frozenset[str], expected: bool
) -> None:
    assert _registered_error("getMore:Error:10107", classes) is expected


def test_stepdown_registration_accepts_pymongo_not_primary_error() -> None:
    registration, _cell = _fault_cell("stepdown")
    configured = cast(
        "dict[str, object]", registration.section("fault_recovery")["error_classes"]
    )
    stepdown_classes = frozenset(cast("list[str]", configured["stepdown"]))

    validate_fault_errors(
        [
            {
                "state": "failed",
                "completed_offset": 3.0,
                "error": "NotPrimaryError",
            }
        ],
        {},
        classes=stepdown_classes,
        injection_offset=2.0,
    )


@pytest.mark.parametrize(
    ("ready", "snapshots", "message"),
    [
        pytest.param(
            [{"streams": 0}],
            [{"stream_operation_times": [(1, 1)]}],
            "stream ownership",
            id="ownership",
        ),
        pytest.param(
            [{"streams": 1}],
            [{"stream_operation_times": []}],
            "stream did not open",
            id="operation-time",
        ),
    ],
)
def test_initial_worker_stream_state_is_checked(
    ready: list[JsonDict], snapshots: list[JsonDict], message: str
) -> None:
    with pytest.raises(BenchmarkSetupError, match=message):
        _validate_initial_workers(ready, snapshots, path="independent")


@pytest.mark.parametrize(
    ("during_cleanup", "message"),
    [
        pytest.param(True, "during cleanup", id="cleanup"),
        pytest.param(False, "did not finish", id="window-end"),
    ],
)
def test_write_scheduler_timeout_is_reported(
    during_cleanup: bool, message: str
) -> None:
    scheduler = Mock()
    scheduler.is_alive.return_value = True

    with pytest.raises(BenchmarkSetupError, match=message):
        _join_write_scheduler(scheduler, 0.0, during_cleanup=during_cleanup)


def test_write_schedule_errors_are_rejected() -> None:
    schedule = cast("_WriteSchedule", SimpleNamespace(errors=["write failed"]))

    with pytest.raises(BenchmarkSetupError, match="write failed"):
        _scheduled_write_records(schedule)


def test_missing_fault_injection_state_is_rejected() -> None:
    injector = cast("_FaultInjection", SimpleNamespace(offset=None, snapshots=None))

    with pytest.raises(BenchmarkSetupError, match="fault injection did not run"):
        _injection_state(injector)


def test_worker_and_trial_request_counts_must_match() -> None:
    with pytest.raises(BenchmarkSetupError, match="request counts differ"):
        _validate_trial_counts(
            [],
            0,
            {"completed": 1, "failed": 0, "interrupted": 0, "undelivered": 0},
        )


@pytest.mark.parametrize(
    "state",
    ["interrupted", "undelivered"],
)
def test_unresolved_request_counts_without_a_kill_are_rejected(state: str) -> None:
    counts: JsonDict = {
        "completed": 0,
        "failed": 0,
        "interrupted": 0,
        "undelivered": 0,
    }
    counts[state] = 1

    with pytest.raises(BenchmarkSetupError, match="unresolved requests without a kill"):
        _validate_request_counts_without_kill(counts)


def test_completed_and_failed_requests_are_valid_without_a_kill() -> None:
    _validate_request_counts_without_kill(
        {"completed": 1, "failed": 1, "interrupted": 0, "undelivered": 0}
    )


def test_stepdown_must_change_primary_identity() -> None:
    with pytest.raises(BenchmarkSetupError, match="identity did not change"):
        _require_stepdown_changed("stepdown", "primary-a", "primary-a")


def test_no_acknowledged_post_recovery_writes_skip_worker_probes() -> None:
    assert _probe_acknowledged_writes(cast("ProcessGroup", object()), ()) == []


@pytest.mark.parametrize("failure", ["garbled", "getMore:Error:not-a-code"])
def test_unparsable_command_failures_are_rejected(failure: str) -> None:
    with pytest.raises(BenchmarkSetupError, match="unregistered wire command failure"):
        validate_fault_errors(
            (),
            {failure: 1},
            classes=frozenset({"AutoReconnect"}),
            injection_offset=1.0,
        )


def test_write_schedule_stops_before_a_future_write() -> None:
    scheduler = _WriteSchedule(
        cast("MongoClient[BsonDict]", object()),
        cast("Collection[BsonDict]", object()),
        ((0.0, 1),),
        time.monotonic() + 10.0,
        0.01,
        [],
        Lock(),
        [],
        Event(),
    )
    scheduler.stop.set()

    scheduler.run()

    assert scheduler.futures == []
    assert scheduler.errors == []


def test_write_schedule_records_late_issuance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recovery, "_write_one", lambda *_args: {})
    scheduler = _WriteSchedule(
        cast("MongoClient[BsonDict]", object()),
        cast("Collection[BsonDict]", object()),
        ((0.0, 1),),
        time.monotonic() - 1.0,
        0.001,
        [],
        Lock(),
        [],
        Event(),
    )

    scheduler.run()

    assert scheduler.errors == ["write schedule exceeded tolerance"]
    assert len(scheduler.futures) == 1


@pytest.mark.parametrize(
    ("failure", "state"),
    [
        pytest.param(AutoReconnect("connection lost"), "unknown", id="unknown"),
        pytest.param(PyMongoError("write rejected"), "failed", id="failed"),
    ],
)
def test_write_outcomes_distinguish_unknown_and_failed_pymongo_errors(
    failure: PyMongoError,
    state: str,
) -> None:
    class _FakeClient:
        __slots__ = ()

        @staticmethod
        def start_session() -> _FakeSession:
            return _FakeSession(None)

    class _FakeCollection:
        __slots__ = ()

        @staticmethod
        def update_one(*_args: object, **_kwargs: object) -> None:
            raise failure

    outcome = _write_one(
        cast("MongoClient[BsonDict]", _FakeClient()),
        cast("Collection[BsonDict]", _FakeCollection()),
        1,
    )

    assert outcome["state"] == state
    assert outcome["error"] == type(failure).__name__


class _FakeSession:
    __slots__ = ("operation_time",)

    def __init__(self, operation_time: Timestamp | None) -> None:
        self.operation_time = operation_time

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        return None


class _FakeClient:
    __slots__ = ("session",)

    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    def start_session(self) -> _FakeSession:
        return self.session


class _FakeCollection:
    __slots__ = ()

    @staticmethod
    def update_one(*_args: object, **_kwargs: object) -> None:
        return None


def test_write_outcomes_require_and_record_operation_time() -> None:
    fake_client = _FakeClient(_FakeSession(None))
    client = cast("MongoClient[BsonDict]", fake_client)
    collection = cast("Collection[BsonDict]", _FakeCollection())

    missing = _write_one(client, collection, 1)
    fake_client.session.operation_time = Timestamp(12, 3)
    acknowledged = _write_one(client, collection, 1)

    assert missing["state"] == "failed"
    assert missing["error"] == "MissingOperationTime"
    assert acknowledged["state"] == "acknowledged"
    assert acknowledged["operation_time"] == (12, 3)


def test_latest_snapshot_and_stream_lifetime_require_snapshot_data() -> None:
    with pytest.raises(BenchmarkSetupError, match="no worker snapshots"):
        _latest_snapshot([])
    with pytest.raises(BenchmarkSetupError, match="no stream lifetime"):
        _control_stream_start({"stream_operation_times": []})


def test_wait_for_primary_change_retries_and_returns_the_new_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identities: list[str | PyMongoError] = [
        AutoReconnect("election in progress"),
        "primary-a",
        "primary-b",
    ]

    class Replica:
        @staticmethod
        def primary_identity() -> str:
            identity = identities.pop(0)
            if isinstance(identity, PyMongoError):
                raise identity
            return identity

    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert (
        _wait_for_primary_change(
            cast("ReplicaSetTopology", Replica()),
            "primary-a",
            time.monotonic() + 1.0,
        )
        == "primary-b"
    )


def test_wait_for_primary_change_reports_an_expired_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(time, "monotonic", lambda: 5.0)

    with pytest.raises(BenchmarkSetupError, match="did not elect a different primary"):
        _wait_for_primary_change(cast("ReplicaSetTopology", object()), "primary-a", 5.0)


def test_post_write_wait_returns_final_snapshot_when_deadline_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot: JsonDict = {"invalidations": 1}

    class Group:
        # Static to satisfy the worker-group API without fake instance state.
        @staticmethod
        def control_workers(_operation: str) -> list[JsonDict]:
            return [snapshot]

    monkeypatch.setattr(time, "monotonic", lambda: 5.0)

    assert _wait_for_post_writes(
        cast("ProcessGroup", Group()),
        baseline=[{"invalidations": 0}],
        expected=(2,),
        deadline=5.0,
    ) == [snapshot]


def test_post_write_wait_retries_until_invalidations_arrive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots: Iterator[list[JsonDict]] = iter(
        [[{"invalidations": 0}], [{"invalidations": 1}]]
    )

    class Group:
        # Static to satisfy the worker-group API without fake instance state.
        @staticmethod
        def control_workers(_operation: str) -> list[JsonDict]:
            return next(snapshots)

    monkeypatch.setattr(time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    assert _wait_for_post_writes(
        cast("ProcessGroup", Group()),
        baseline=[{"invalidations": 0}],
        expected=(1,),
        deadline=1.0,
    ) == [{"invalidations": 1}]


@pytest.mark.parametrize(
    ("case", "replica_factory", "primary_before", "message"),
    [
        pytest.param(
            "stepdown",
            lambda: IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="1g")),
            None,
            "no multi-member topology",
            id="stepdown-topology",
        ),
        pytest.param(
            "stepdown",
            ReplicaSetTopology,
            None,
            "no initial primary",
            id="stepdown-primary",
        ),
        pytest.param(
            "unsupported",
            lambda: IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="1g")),
            None,
            "unknown worker fault case",
            id="unknown-case",
        ),
    ],
)
def test_fault_injection_rejects_invalid_stepdown_and_case_state(
    case: str,
    replica_factory: Callable[[], IsolatedReplicaSet | ReplicaSetTopology],
    primary_before: str | None,
    message: str,
) -> None:
    registration, original_cell = _fault_cell("connection-loss")
    cell = replace(original_cell, fault_case=case)
    now = time.monotonic()

    class Group:
        # Static to satisfy the worker-group API without fake instance state.
        @staticmethod
        def control_workers(_operation: str) -> list[JsonDict]:
            return [{"command_failures": {}}]

    injection = _FaultInjection(
        group=cast("ProcessGroup", Group()),
        replica=replica_factory(),
        registration=registration,
        cell=cell,
        workload=cast("_Workload", object()),
        initial=[{"command_failures": {}}],
        primary_before=primary_before,
        start=now,
        window_start=now - cell.injection_offset_seconds,
        window_end=now + cell.window_seconds,
        executor=cast("ThreadPoolExecutor", object()),
    )

    with pytest.raises(BenchmarkSetupError, match=message):
        injection.inject()


def test_fault_injection_rejects_primary_change_before_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registration, cell = _fault_cell("stepdown")
    now = time.monotonic()

    class Group:
        # Static to satisfy the worker-group API without fake instance state.
        @staticmethod
        def control_workers(_operation: str) -> list[JsonDict]:
            return [{"command_failures": {}}]

    monkeypatch.setattr(ReplicaSetTopology, "primary_identity", lambda _self: "new")
    injection = _FaultInjection(
        group=cast("ProcessGroup", Group()),
        replica=ReplicaSetTopology(),
        registration=registration,
        cell=cell,
        workload=cast("_Workload", object()),
        initial=[{"command_failures": {}}],
        primary_before="old",
        start=now,
        window_start=now - cell.injection_offset_seconds,
        window_end=now + cell.window_seconds,
        executor=cast("ThreadPoolExecutor", object()),
    )

    with pytest.raises(BenchmarkSetupError, match="primary changed before"):
        injection.inject()


@pytest.mark.parametrize(
    ("fault_case", "actions"),
    [
        pytest.param("connection-loss", ("sever",), id="connection-loss"),
        pytest.param("history-loss", ("lose-history", "sever"), id="history-loss"),
    ],
)
def test_worker_fault_offset_is_recorded_after_control_actions(
    fault_case: str, actions: tuple[str, ...]
) -> None:
    registration, cell = _fault_cell(fault_case)
    now = time.monotonic()
    action_times: list[NonNegativeFloat] = []

    class Group:
        # Static to satisfy the worker-group API without fake instance state.
        @staticmethod
        def control_workers(operation: str) -> list[JsonDict]:
            if operation in actions:
                time.sleep(0.05)
                action_time = time.monotonic()
                action_times.append(action_time)
                time.sleep(0.05)
                return [{"command_failures": {}, "action_monotonic": action_time}]
            return [{"command_failures": {}}]

    injection = _FaultInjection(
        group=cast("ProcessGroup", Group()),
        replica=cast("ReplicaSetTopology", object()),
        registration=registration,
        cell=cell,
        workload=cast("_Workload", object()),
        initial=[{"command_failures": {}}],
        primary_before=None,
        start=now,
        window_start=now - cell.injection_offset_seconds,
        window_end=now + cell.window_seconds,
        executor=cast("ThreadPoolExecutor", object()),
    )

    injection.inject()

    assert injection.offset is not None
    assert action_times
    assert injection.offset == pytest.approx(action_times[0] - injection.window_start)


def test_stepdown_offset_is_recorded_after_server_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registration, cell = _fault_cell("stepdown")
    now = time.monotonic()
    action_times: list[NonNegativeFloat] = []

    def delayed_stepdown(_replica: ReplicaSetTopology) -> NonNegativeFloat:
        time.sleep(0.05)
        action_time = time.monotonic()
        action_times.append(action_time)
        time.sleep(0.05)
        return action_time

    monkeypatch.setattr(ReplicaSetTopology, "step_down_primary", delayed_stepdown)
    monkeypatch.setattr(
        ReplicaSetTopology, "primary_identity", lambda _replica: "primary-a"
    )
    monkeypatch.setattr(
        recovery, "_wait_for_primary_change", lambda *_args: "primary-b"
    )

    class Group:
        # Static to satisfy the worker-group API without fake instance state.
        @staticmethod
        def control_workers(_operation: str) -> list[JsonDict]:
            return [{"command_failures": {}}]

    injection = _FaultInjection(
        group=cast("ProcessGroup", Group()),
        replica=ReplicaSetTopology(),
        registration=registration,
        cell=cell,
        workload=cast("_Workload", object()),
        initial=[{"command_failures": {}}],
        primary_before="primary-a",
        start=now,
        window_start=now - cell.injection_offset_seconds,
        window_end=now + cell.window_seconds,
        executor=cast("ThreadPoolExecutor", object()),
    )

    injection.inject()

    assert injection.offset is not None
    assert action_times
    assert injection.offset == pytest.approx(action_times[0] - injection.window_start)


def test_fault_injection_rejects_a_late_injection() -> None:
    registration, cell = _fault_cell("connection-loss")
    now = time.monotonic()
    injection = _FaultInjection(
        group=cast("ProcessGroup", object()),
        replica=cast("IsolatedReplicaSet", object()),
        registration=registration,
        cell=cell,
        workload=cast("_Workload", object()),
        initial=[],
        primary_before=None,
        start=now,
        window_start=now,
        window_end=now + cell.window_seconds,
        executor=cast("ThreadPoolExecutor", object()),
    )

    with pytest.raises(BenchmarkSetupError, match="missed its registered offset"):
        injection._record_injection(now + cell.injection_offset_seconds + 1.0)


@pytest.mark.parametrize(
    ("request_error", "completed", "classes", "command_failures", "raises"),
    [
        pytest.param(
            "AutoReconnect",
            5.0,
            frozenset({"AutoReconnect"}),
            {},
            False,
            id="registered-read-error-is-evidence",
        ),
        pytest.param(
            "AuthenticationFailure",
            5.0,
            frozenset({"AutoReconnect"}),
            {},
            True,
            id="unregistered-read-error-fails-setup",
        ),
        pytest.param(
            "AutoReconnect",
            1.0,
            frozenset({"AutoReconnect"}),
            {},
            True,
            id="read-error-before-injection-fails-setup",
        ),
        pytest.param(
            "",
            5.0,
            frozenset({"ChangeStreamHistoryLost"}),
            {"getMore:ChangeStreamHistoryLost:286": 1},
            False,
            id="registered-stream-code-is-evidence",
        ),
        pytest.param(
            "",
            5.0,
            frozenset({"ResumableChangeStreamError"}),
            {"getMore:None:None:ResumableChangeStreamError": 1},
            False,
            id="registered-resume-label-is-evidence",
        ),
        pytest.param(
            "",
            5.0,
            frozenset({"CursorKilled"}),
            {"getMore:None:237": 1},
            False,
            id="registered-stream-code-without-name-is-evidence",
        ),
        pytest.param(
            "",
            5.0,
            frozenset({"AutoReconnect"}),
            {"find:AuthenticationFailure:13": 1},
            True,
            id="unregistered-command-error-fails-setup",
        ),
    ],
)
def test_fault_error_policy(
    request_error: str,
    completed: NonNegativeFloat,
    classes: frozenset[str],
    command_failures: dict[str, int],
    raises: bool,
) -> None:
    requests = (
        [
            {
                "state": "failed",
                "completed_offset": completed,
                "error": request_error,
            }
        ]
        if request_error
        else []
    )

    if raises:
        with pytest.raises(BenchmarkSetupError):
            validate_fault_errors(
                requests,
                command_failures,
                classes=classes,
                injection_offset=2.0,
            )
    else:
        validate_fault_errors(
            requests,
            command_failures,
            classes=classes,
            injection_offset=2.0,
        )


def test_stale_post_recovery_probe_is_reported_as_correctness_failure() -> None:
    correctness = post_recovery_correctness(
        [{"probe_ok": False, "stale_key": 42, "probed": 1}],
        expected_writes=1,
        acknowledged_writes=1,
        invalidation_drain_passed=True,
    )

    assert correctness["available"] is True
    assert correctness["passed"] is False
    assert correctness["workers"] == [{"probe_ok": False, "stale_key": 42, "probed": 1}]


def test_acknowledged_subset_can_verify_post_recovery_correctness() -> None:
    correctness = post_recovery_correctness(
        [
            {"probe_ok": True, "probed": 15},
            {"probe_ok": True, "probed": 15},
        ],
        expected_writes=16,
        acknowledged_writes=15,
        invalidation_drain_passed=True,
    )

    assert correctness["available"] is True
    assert correctness["passed"] is True
    assert correctness["expected_writes"] == 16
    assert correctness["acknowledged_writes"] == 15


def test_no_acknowledged_post_recovery_writes_are_inconclusive() -> None:
    correctness = post_recovery_correctness(
        [],
        expected_writes=16,
        acknowledged_writes=0,
        invalidation_drain_passed=True,
    )

    assert correctness["available"] is False
    assert correctness["passed"] is None
    assert correctness["probed"] == 0


def _calibration_point(
    *,
    election: str,
    wall_t0: NonNegativeFloat,
    wall_t1: NonNegativeFloat,
    mono_t0: NonNegativeFloat,
    mono_t1: NonNegativeFloat,
    offset: float = 0.0,
) -> CalibrationPoint:
    sample = ClockSample(
        wall_t0=wall_t0,
        wall_t1=wall_t1,
        monotonic_t0=mono_t0,
        monotonic_t1=mono_t1,
        server_time_seconds=(wall_t0 + wall_t1) / 2 + offset,
        election_id=election,
    )
    return CalibrationPoint(sample, (sample,))


def test_clock_policy_rejects_steps_and_elections_outside_stepdown() -> None:
    stepped = _calibration_point(
        election="one", wall_t0=0.0, wall_t1=2.0, mono_t0=0.0, mono_t1=1.0
    )
    with pytest.raises(BenchmarkSetupError, match="clock stepped"):
        _check_clock((stepped,), case="connection-loss", tolerance=0.01)

    first = _calibration_point(
        election="one", wall_t0=0.0, wall_t1=0.001, mono_t0=0.0, mono_t1=0.001
    )
    second = _calibration_point(
        election="two", wall_t0=1.0, wall_t1=1.001, mono_t0=1.0, mono_t1=1.001
    )
    with pytest.raises(BenchmarkSetupError, match="election occurred"):
        _check_clock((first, second), case="connection-loss", tolerance=0.01)


def test_clock_policy_accounts_for_selected_sample_uncertainty() -> None:
    first = _calibration_point(
        election="one",
        wall_t0=0.0,
        wall_t1=0.02,
        mono_t0=0.0,
        mono_t1=0.02,
    )
    second = _calibration_point(
        election="one",
        wall_t0=2.0,
        wall_t1=2.02,
        mono_t0=2.0,
        mono_t1=2.02,
        offset=0.02,
    )

    _check_clock((first, second), case="connection-loss", tolerance=0.005)


def test_clock_policy_rejects_missing_samples_drift_and_multiple_elections() -> None:
    with pytest.raises(BenchmarkSetupError, match="no clock calibration samples"):
        _check_clock((), case="connection-loss", tolerance=0.01)

    first = _calibration_point(
        election="one",
        wall_t0=0.0,
        wall_t1=0.001,
        mono_t0=0.0,
        mono_t1=0.001,
    )
    drifted = _calibration_point(
        election="one",
        wall_t0=1.0,
        wall_t1=1.001,
        mono_t0=1.0,
        mono_t1=1.001,
        offset=0.1,
    )
    with pytest.raises(BenchmarkSetupError, match="drift exceeded"):
        _check_clock((first, drifted), case="stepdown", tolerance=0.01)

    elections = tuple(
        _calibration_point(
            election=f"election-{index}",
            wall_t0=float(index),
            wall_t1=float(index) + 0.001,
            mono_t0=float(index),
            mono_t1=float(index) + 0.001,
        )
        for index in range(3)
    )
    with pytest.raises(BenchmarkSetupError, match="multiple elections"):
        _check_clock(elections, case="stepdown", tolerance=0.01)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        pytest.param("topology", "topology does not match", id="topology"),
        pytest.param("path", "baseline paths only", id="path"),
        pytest.param("rate", "no registered offered rate", id="rate"),
    ],
)
def test_fault_window_rejects_incompatible_cell_setup(
    case: str,
    message: str,
) -> None:
    registration, original_cell = _fault_cell("connection-loss")
    match case:
        case "topology":
            cell = replace(original_cell, topology="three-member")
        case "path":
            cell = replace(original_cell, path="shared-index")
        case _:
            cell = replace(original_cell, rate=None)

    with pytest.raises(BenchmarkSetupError, match=message):
        run_recovery_fault_window(
            cast("IsolatedReplicaSet", object()), registration, cell
        )
