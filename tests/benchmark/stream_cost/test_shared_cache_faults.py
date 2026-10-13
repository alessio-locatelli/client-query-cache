from __future__ import annotations

import copy
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from pymongo.errors import PyMongoError

from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)
from benchmarks.stream_cost.shared_cache import analysis, fault_worker, faults
from benchmarks.stream_cost.shared_cache.analysis import analyze_faults
from benchmarks.stream_cost.shared_cache.fault_worker import verify_document
from benchmarks.stream_cost.shared_cache.protocol import (
    FAULT_CASES,
    FaultCell,
    Registration,
    fault_applicability,
    fault_cells,
)
from benchmarks.stream_cost.shared_cache.safety import verify_published_payloads
from benchmarks.stream_cost.shared_cache.wire import ProtocolError
from client_query_cache._types import (
    JsonDict,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)

if TYPE_CHECKING:
    from benchmarks.stream_cost.shared_cache.coordinator import Message
    from benchmarks.stream_cost.shared_cache.protocol import PathKind
    from client_query_cache._types import BsonDict

pytestmark = pytest.mark.unit
_CONFIG = Path("reports/shared-worker-cache/v6/config.json")


@pytest.fixture
def registration() -> Registration:
    return Registration.load(_CONFIG)


@pytest.fixture
def records(registration: Registration) -> list[JsonDict]:
    rows: list[JsonDict] = []
    for cell in fault_cells(registration):
        assert isinstance(cell, FaultCell)
        applicability = fault_applicability(registration)[cell.fault_case]
        events = {"injection": 10.0, "recovery": 20.0}
        durations = {}
        for name, applies in applicability.items():
            durations[name] = 1.0 if applies else None
            if applies:
                events[name] = (10.0 if name == "detection" else 20.0) + 1.0
        rows.append(
            {
                **asdict(cell),
                "healthy": True,
                "checks": ["verified"],
                "events": events,
                "durations": durations,
            }
        )
    return rows


def test_fault_plan(registration: Registration) -> None:
    cells = fault_cells(registration)
    assert len(cells) == len(FAULT_CASES) * 5
    assert {
        (cell.block, cell.fault_case) for cell in cells if isinstance(cell, FaultCell)
    } == {(block, case) for block in range(5) for case in FAULT_CASES}
    assert all(cell.sync_workers() == 2 and cell.workers == 4 for cell in cells)


@pytest.mark.parametrize("version", [4, 5], ids=["v4", "v5"])
def test_frozen_fault_lists_require_metadata(version: PositiveInt) -> None:
    registration = Registration.load(
        Path(f"reports/shared-worker-cache/v{version}/config.json")
    )
    with pytest.raises(BenchmarkConfigurationError, match="applicability"):
        fault_cells(registration)


@pytest.mark.parametrize(
    "mutation",
    ["missing", "partial", "non-bool"],
    ids=["missing-case", "missing-timing", "invalid-flag"],
)
def test_fault_declarations(registration: Registration, mutation: str) -> None:
    raw = copy.deepcopy(registration.raw)
    declarations = raw["fault_timings"]
    assert isinstance(declarations, dict)
    if mutation == "missing":
        del declarations[FAULT_CASES[0]]
    elif mutation == "partial":
        del declarations[FAULT_CASES[0]]["detection"]
    else:
        declarations[FAULT_CASES[0]]["detection"] = 1
    with pytest.raises(BenchmarkConfigurationError, match="declare"):
        fault_cells(Registration(raw, registration.digest))


@pytest.mark.parametrize(
    ("seconds", "passed"),
    [(5.0, True), (5.000001, False)],
    ids=["at-bound", "above-bound"],
)
def test_readiness_gate(
    registration: Registration,
    records: list[JsonDict],
    seconds: PositiveFloat,
    passed: bool,
) -> None:
    durations = records[0]["durations"]
    events = records[0]["events"]
    assert isinstance(durations, dict)
    assert isinstance(events, dict)
    durations["readiness"] = seconds
    events["readiness"] = 20 + seconds
    assert analyze_faults(records, registration)["pass"] is passed


@pytest.mark.parametrize(
    "mutation",
    [
        "unsafe",
        "missing-trial",
        "missing-event",
        "missing-duration",
        "wrong-origin",
        "inapplicable-zero",
    ],
    ids=[
        "unsafe",
        "missing-trial",
        "missing-event",
        "missing-duration",
        "wrong-origin",
        "inapplicable-zero",
    ],
)
def test_fault_analysis_fails_incomplete_or_unsafe_evidence(
    registration: Registration, records: list[JsonDict], mutation: str
) -> None:
    durations = records[0]["durations"]
    events = records[0]["events"]
    assert isinstance(durations, dict)
    assert isinstance(events, dict)
    if mutation == "unsafe":
        records[0]["healthy"] = False
    elif mutation == "missing-trial":
        records.pop()
    elif mutation == "missing-event":
        del events["readiness"]
    elif mutation == "missing-duration":
        del durations["readiness"]
    elif mutation == "wrong-origin":
        durations["readiness"] = 11.0
    else:
        inapplicable = records[8]["durations"]
        assert isinstance(inapplicable, dict)
        inapplicable["readiness"] = 0
    assert analyze_faults(records, registration)["pass"] is False


def test_duplicate_fault_trials(
    registration: Registration, records: list[JsonDict]
) -> None:
    records.append(records[0])
    with pytest.raises(BenchmarkSetupError, match="duplicate"):
        analyze_faults(records, registration)


@pytest.mark.parametrize("document", [None, {"revision": 0}], ids=["missing", "stale"])
def test_revision_oracle(document: BsonDict | None) -> None:
    with pytest.raises(LookupError, match="missing or stale"):
        verify_document(document, 1)


def test_publication_oracle() -> None:
    with pytest.raises(LookupError, match="torn or unpublished"):
        verify_published_payloads({0: {b"torn"}}, {0: {b"published"}})


@pytest.mark.parametrize(
    "error_type",
    [
        BenchmarkSetupError,
        LookupError,
        AssertionError,
        EOFError,
        OSError,
        PyMongoError,
        ProtocolError,
    ],
    ids=[
        "deadline",
        "safety",
        "assertion",
        "worker-exit",
        "transport",
        "database",
        "protocol",
    ],
)
def test_trial_failure_is_retained(
    registration: Registration,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    def fail(*_args: object) -> None:
        raise error_type("injected failure")

    monkeypatch.setattr(faults, "_execute_fault_window", fail)
    cell = fault_cells(registration)[0]
    record = faults.run_fault_window(None, registration, cell)  # type: ignore[arg-type]
    assert record["healthy"] is False
    assert record["failure"] == f"{error_type.__name__}: injected failure"


@pytest.fixture
def trial(registration: Registration) -> faults.FaultTrial:
    cell = fault_cells(registration)[0]
    assert isinstance(cell, FaultCell)
    return faults.FaultTrial(Mock(), registration, cell, "mongodb://localhost", Mock())


def test_observation_deadline(trial: faults.FaultTrial) -> None:
    trial.deadline = 0
    with pytest.raises(BenchmarkSetupError, match="deadline expired"):
        trial.wait(lambda: False)


@pytest.mark.parametrize(
    ("resident", "hit"), [(1, False), (0, True)], ids=["other-local-key", "rpc-hit"]
)
def test_detection_rejects_any_cached_selection(
    trial: faults.FaultTrial,
    monkeypatch: pytest.MonkeyPatch,
    resident: NonNegativeInt,
    hit: bool,
) -> None:
    unsafe = {
        "resident_keys": resident,
        "hit": hit,
        "local_hit": False,
        "bypass": True,
        "monotonic": 1.0,
    }
    safe = {**unsafe, "resident_keys": 0, "hit": False, "monotonic": 2.0}
    workers = Mock(side_effect=[[safe, unsafe], [safe, safe]])
    monkeypatch.setattr(faults.FaultTrial, "workers", workers)
    trial.detect()
    assert trial.events["detection"] == pytest.approx(2.0)
    assert workers.call_count == 2
    workers.assert_called_with("detect")


@pytest.mark.parametrize(
    ("operation", "expected"),
    [("detect", (0, 1)), ("prime", (0, 1)), ("probe", (0,))],
    ids=["detection", "rewarming", "readiness"],
)
def test_probe_key_scope(operation: str, expected: tuple[NonNegativeInt, ...]) -> None:
    assert fault_worker.probe_keys(Mock(keys=(0, 1)), {"op": operation}) == expected


def test_readiness_snapshot_skips_residency_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_snapshot = Mock(side_effect=AssertionError("unexpected residency scan"))
    monkeypatch.setattr(fault_worker, "local_snapshot", local_snapshot)
    manager = Mock()
    manager.observation.hits = 0
    manager.observation.bypasses = {}
    observation = fault_worker.snapshot(
        manager,
        Mock(),
        eligible=True,
        hits_before=0,
        bypasses_before=0,
        reads=1,
        exhaustive=False,
    )
    assert observation["resident_keys"] is None
    local_snapshot.assert_not_called()


def test_polling_retains_only_the_latest_round(trial: faults.FaultTrial) -> None:
    connection = Mock()
    connection.recv.side_effect = [
        {"kind": "probe", "monotonic": 1.0},
        {"kind": "probe", "monotonic": 2.0},
    ]
    trial.group.connections = [connection]
    trial.workers()
    assert trial.workers() == [{"kind": "probe", "monotonic": 2.0}]
    assert trial.probes == {"probe": [{"kind": "probe", "monotonic": 2.0}]}


def test_readiness_waits_for_both_owner_and_worker_observations(
    trial: faults.FaultTrial, monkeypatch: pytest.MonkeyPatch
) -> None:
    first: Message = {"eligible": True, "hit": True, "monotonic": 1.0}
    unavailable: Message = {"available": False, "progress_fresh": False}
    available: Message = {"available": True, "progress_fresh": True}
    monkeypatch.setattr(
        "benchmarks.stream_cost.shared_cache.faults.time.monotonic",
        Mock(return_value=2.0),
    )

    assert not trial._record_readiness(unavailable, [first])
    assert trial.events == {}
    assert trial._record_readiness(available, [first])
    assert trial.events == {"readiness": 2.0, "first_hit": 2.0}


@pytest.mark.parametrize(
    "reply", [None, {"r": "hit"}], ids=["detached", "unexpected-hit"]
)
def test_capture_safety_failure(trial: faults.FaultTrial, reply: object) -> None:
    connection = Mock()
    connection.recv.return_value = reply
    trial.group.connections = [connection]
    with pytest.raises(LookupError, match="obtain its capture"):
        trial.capture()


def test_capture_timeout(trial: faults.FaultTrial) -> None:
    connection = Mock()
    connection.poll.return_value = False
    trial.group.connections = [connection]
    with pytest.raises(LookupError, match="capture timed out"):
        trial.capture()


def test_dead_worker_cleanup(trial: faults.FaultTrial) -> None:
    connection = Mock()
    connection.send.side_effect = BrokenPipeError
    trial.group.connections = [connection]
    faults._close_fault_workers(trial.group)


@pytest.mark.parametrize(
    ("setting", "value"),
    [("workers", 3), ("repetitions", 0)],
    ids=["worker-count", "repetitions"],
)
def test_fault_group_configuration(
    registration: Registration, setting: str, value: NonNegativeInt
) -> None:
    raw = copy.deepcopy(registration.raw)
    phases = raw["phases"]
    assert isinstance(phases, dict)
    phases["fault"][setting] = value
    with pytest.raises(BenchmarkConfigurationError):
        fault_cells(Registration(raw, registration.digest))


def test_fault_phase_rejects_baselines(registration: Registration) -> None:
    with pytest.raises(BenchmarkConfigurationError, match="shared cache path"):
        fault_cells(registration, ("direct", "independent"))


def test_fault_phase_rejects_unknown_case(registration: Registration) -> None:
    raw = copy.deepcopy(registration.raw)
    raw["fault_cases"] = ["unknown"]
    with pytest.raises(BenchmarkConfigurationError, match="supported cases"):
        fault_cells(Registration(raw, registration.digest))


def test_fault_analysis_rejects_another_worker_group(
    registration: Registration, records: list[JsonDict]
) -> None:
    records[0]["workers"] = 1
    with pytest.raises(BenchmarkSetupError, match="registered cell"):
        analyze_faults(records, registration)


def test_fault_analysis_cli(
    records: list[JsonDict],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(analysis, "load_records", lambda *_args: records)
    analysis.main(["fault.json", "--config", str(_CONFIG), "--phase", "fault"])
    output = json.loads(capsys.readouterr().out)
    assert output["pass"] is True


def test_other_analysis_phases_require_blocks() -> None:
    with pytest.raises(SystemExit, match="2"):
        analysis.main(["fault.json", "--config", str(_CONFIG), "--phase", "screening"])


def test_fault_cases_have_distinct_loader_keys(records: list[JsonDict]) -> None:
    analysis.reject_duplicates(records)


@pytest.mark.parametrize(
    (
        "path",
        "cache_delta",
        "publication_delta",
        "resident_delta",
        "all_hits",
        "complete",
    ),
    [
        ("shared", 0, 0, 0, True, True),
        ("shared", 0, 0, 0, False, False),
        ("shared-index", -1, 0, 0, True, False),
        ("shared-index", 0, -1, 0, True, False),
        ("shared-index", 0, 0, -1, True, False),
        ("shared-index", 0, 0, 0, True, True),
    ],
    ids=[
        "rpc-resident",
        "rpc-still-missing",
        "incomplete-hot-set",
        "not-published",
        "not-worker-visible",
        "published-hot-set",
    ],
)
def test_rewarming_requires_the_complete_servable_hot_set(
    trial: faults.FaultTrial,
    monkeypatch: pytest.MonkeyPatch,
    *,
    path: PathKind,
    cache_delta: int,
    publication_delta: int,
    resident_delta: int,
    all_hits: bool,
    complete: bool,
) -> None:
    keys = trial.registration.hot_keys
    assert keys is not None
    trial.cell = replace(trial.cell, path=path)
    monkeypatch.setattr(
        faults.FaultTrial,
        "workers",
        lambda *_args: [{"resident_keys": keys + resident_delta, "all_hits": all_hits}],
    )
    monkeypatch.setattr(
        faults.FaultTrial,
        "observe",
        lambda _trial: {
            "cache": {"entry_count": keys + cache_delta},
            "shared_index": {"published": keys + publication_delta},
        },
    )
    assert trial.rewarmed() is complete
    assert ("rewarming" in trial.events) is complete
