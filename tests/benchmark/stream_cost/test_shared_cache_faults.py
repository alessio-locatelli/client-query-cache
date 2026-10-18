from __future__ import annotations

import copy
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, Mock

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
from benchmarks.stream_cost.shared_cache.safety import (
    local_read,
    verify_published_payloads,
)
from client_query_cache._core.keys import NamespaceId
from client_query_cache._shared.coordinator import UpstreamProgress
from client_query_cache._shared.wire import ProtocolError
from client_query_cache._types import (
    JsonDict,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)

if TYPE_CHECKING:
    from benchmarks.stream_cost.shared_cache.protocol import PathKind
    from client_query_cache._shared.coordinator import Message
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
        evidence=Mock(first_hit=None, last_hit=None, unsafe_hit=False),
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
    trial.workers("detect")
    assert trial.workers("detect") == [{"kind": "probe", "monotonic": 2.0}]
    assert trial.probes == {"detect": [{"kind": "probe", "monotonic": 2.0}]}


@pytest.fixture
def healthy_owner() -> Message:
    return {
        "available": True,
        "progress_fresh": True,
        "incarnation": "current",
        "monotonic": 2.0,
        "available_since": 0.5,
        "fresh_since": 0.5,
    }


@pytest.fixture
def cached_hit() -> Message:
    return {
        "eligible": True,
        "hit": True,
        "hit_at": 1.0,
        "last_hit_at": 1.0,
        "unsafe_hit": False,
        "incarnation": "current",
    }


@pytest.mark.parametrize(
    "condition",
    ["unavailable", "stale", "transition", "incarnation", "ineligible", "unsafe-read"],
    ids=[
        "unavailable",
        "stale",
        "sampled-transition",
        "old-incarnation",
        "ineligible-worker",
        "unsafe-read",
    ],
)
def test_premature_hit_is_retained_and_fails_recovery(
    trial: faults.FaultTrial,
    healthy_owner: Message,
    cached_hit: Message,
    condition: str,
) -> None:
    trial.events["recovery"] = 0.0
    before = {**healthy_owner, "monotonic": 0.0}
    if condition == "unavailable":
        healthy_owner["available"] = False
    elif condition == "stale":
        healthy_owner["progress_fresh"] = False
    elif condition == "transition":
        before["available"] = False
        healthy_owner["available_since"] = 1.5
    elif condition == "incarnation":
        cached_hit["incarnation"] = "obsolete"
    elif condition == "ineligible":
        cached_hit["eligible"] = False
        cached_hit["unsafe_hit"] = True
    else:
        cached_hit["unsafe_hit"] = True
    eligible_peer = {**cached_hit, "eligible": True, "hit": False}
    with pytest.raises(LookupError, match="lacks safe"):
        trial._record_readiness(before, [cached_hit, eligible_peer], healthy_owner)
    assert trial.events == {"recovery": 0.0, "first_hit": 1.0}


def test_first_hit_is_independent_of_readiness(
    trial: faults.FaultTrial,
    monkeypatch: pytest.MonkeyPatch,
    healthy_owner: Message,
    cached_hit: Message,
) -> None:
    monkeypatch.setattr(
        "benchmarks.stream_cost.shared_cache.faults.time",
        Mock(monotonic=Mock(side_effect=[2.0, 5.0])),
    )
    trial.events["recovery"] = 0.0
    before = {**healthy_owner, "monotonic": 0.0}
    assert trial._record_readiness(before, [cached_hit], healthy_owner)
    assert trial.events == {"recovery": 0.0, "readiness": 2.0, "first_hit": 1.0}
    cached_hit["hit_at"] = 3.0
    cached_hit["last_hit_at"] = 3.0
    before["monotonic"] = 2.0
    healthy_owner["monotonic"] = 4.0
    assert trial._record_readiness(before, [cached_hit], healthy_owner)
    assert trial.events == {"recovery": 0.0, "readiness": 2.0, "first_hit": 1.0}


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


@pytest.fixture
def traffic() -> fault_worker.LocalTraffic:
    return fault_worker.LocalTraffic()


def test_local_traffic_prepares_lookup_inputs_once(
    traffic: fault_worker.LocalTraffic,
) -> None:
    namespace = NamespaceId("catalogue", "documents")
    manager = MagicMock()
    manager._slots.find.return_value = (0, 1, "owner")
    manager._metadata.find.return_value = Mock(checked_epoch=2)
    manager.keys.encode.return_value = b"shape"
    manager.local.reader.lookup.return_value = b"payload"
    spec = Mock(
        database=namespace.database,
        collection=namespace.collection,
        keys=tuple(range(64)),
    )
    for _ in range(10):
        for key in spec.keys:
            assert (
                local_read(manager, spec.database, spec.collection, key) == b"payload"
            )
    assert manager.__getitem__.call_count == 640
    assert manager.keys.encode.call_count == 640
    manager.reset_mock()
    traffic.prepare(manager, spec)
    for _ in range(10):
        traffic.step()
    assert manager.__getitem__.call_count == 1
    manager.keys.encode.assert_called_once()
    assert manager.local.reader.lookup.call_count == 640
    assert traffic.hits == 640
    assert traffic.sweeps == 10


@pytest.fixture
def read_evidence() -> fault_worker.ReadEvidence:
    return fault_worker.ReadEvidence()


def test_per_read_evidence_retains_unsafe_hits(
    read_evidence: fault_worker.ReadEvidence, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "benchmarks.stream_cost.shared_cache.fault_worker.time",
        Mock(monotonic=Mock(side_effect=[1.0, 2.0])),
    )
    read_evidence.observe(0, 0, eligible=False)
    assert read_evidence.first_hit is None
    read_evidence.observe(0, 1, eligible=False)
    read_evidence.observe(1, 2, eligible=True)
    assert read_evidence.first_hit == pytest.approx(1.0)
    assert read_evidence.unsafe_hit


@pytest.mark.parametrize(
    "window", ["available_since", "fresh_since"], ids=["availability", "progress"]
)
def test_sampled_transition_uses_the_actual_ready_window(
    trial: faults.FaultTrial,
    healthy_owner: Message,
    cached_hit: Message,
    window: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trial.events["recovery"] = 0.0
    before = {
        **healthy_owner,
        "available": False,
        "progress_fresh": False,
        "monotonic": 0.0,
    }
    monkeypatch.setattr(
        "benchmarks.stream_cost.shared_cache.faults.time",
        Mock(monotonic=Mock(return_value=2.0)),
    )
    assert trial._record_readiness(before, [cached_hit], healthy_owner)
    healthy_owner[window] = 1.5
    with pytest.raises(LookupError, match="lacks safe"):
        trial._record_readiness(before, [cached_hit], healthy_owner)
    assert trial.events["first_hit"] == pytest.approx(1.0)


def test_owner_evidence_uses_snapshot_time_not_receipt_time(
    trial: faults.FaultTrial,
    healthy_owner: Message,
    cached_hit: Message,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trial.events["recovery"] = 0.0
    database = str(trial.registration.raw["database"])
    observation = {
        "databases": {database: healthy_owner},
        "incarnation": "current",
        "observed_monotonic": 0.5,
    }
    monkeypatch.setattr(faults.FaultTrial, "observe", Mock(return_value=observation))
    monkeypatch.setattr(
        "benchmarks.stream_cost.shared_cache.faults.time",
        Mock(monotonic=Mock(return_value=2.0)),
    )
    after = trial._owner_state()
    assert after["monotonic"] == pytest.approx(0.5)
    before = {**healthy_owner, "monotonic": 0.0}
    with pytest.raises(LookupError, match="lacks safe"):
        trial._record_readiness(before, [cached_hit], after)


@pytest.fixture
def progress() -> UpstreamProgress:
    return UpstreamProgress(expiry_seconds=1.0)


def test_progress_window_resets_only_after_expiry(
    progress: UpstreamProgress, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = "progress-window"
    event = Mock(command_name="getMore", database_name=database)
    monkeypatch.setattr(
        "client_query_cache._shared.coordinator.time",
        Mock(monotonic=Mock(side_effect=[1.0, 1.5, 3.0])),
    )
    assert progress.fresh_since(database) is None
    progress.succeeded(event)
    assert progress.fresh_since(database) == pytest.approx(1.0)
    progress.succeeded(event)
    assert progress.fresh_since(database) == pytest.approx(1.0)
    progress.succeeded(event)
    assert progress.fresh_since(database) == pytest.approx(3.0)


def test_safe_hit_precedes_a_later_readiness_observation(
    trial: faults.FaultTrial,
    healthy_owner: Message,
    cached_hit: Message,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trial.events["recovery"] = 0.0
    before = {**healthy_owner, "monotonic": 0.0}
    cached_hit["eligible"] = False
    assert not trial._record_readiness(before, [cached_hit], healthy_owner)
    assert trial.events == {"recovery": 0.0, "first_hit": 1.0}
    cached_hit.update(eligible=True, hit=False)
    monkeypatch.setattr(
        "benchmarks.stream_cost.shared_cache.faults.time",
        Mock(monotonic=Mock(return_value=2.0)),
    )
    assert trial._record_readiness(before, [cached_hit], healthy_owner)
    assert trial.events == {"recovery": 0.0, "first_hit": 1.0, "readiness": 2.0}
