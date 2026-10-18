from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import psutil
import pytest
from pymongo.errors import OperationFailure
from pymongo.synchronous.collection import Collection

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.shared_cache import diagnostics, run, window
from benchmarks.stream_cost.shared_cache.dataset import seed_catalogue
from benchmarks.stream_cost.shared_cache.protocol import (
    Registration,
    smoke_cells,
    validation_failure,
)
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache._types import BsonDict, JsonDict, PositiveInt

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from pymongo import MongoClient

    from benchmarks.stream_cost.shared_cache.protocol import Cell

pytestmark = pytest.mark.integration

_CONFIG = Path("reports/shared-worker-cache/v4/config.json")
_V5_CONFIG = Path("reports/shared-worker-cache/v5/config.json")
_CONCURRENT_CONFIG = Path("reports/concurrent-worker-workload/v1/config.json")
_ORIGINAL_WORKLOAD = window._workload
_ORIGINAL_SEED = seed_catalogue


@pytest.fixture(scope="module")
def replica() -> Iterator[IsolatedReplicaSet]:
    with IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="1g")) as replica_set:
        yield replica_set


def _smoke_config(source: Path, path: Path, **changes: object) -> Path:
    raw = json.loads(source.read_text(encoding="utf-8"))
    raw["status"] = "pending-calibration"
    raw["profiles"]["smoke"]["documents"] = 64
    raw["phases"]["smoke"].update(
        {"window_seconds": 1, "warmup_seconds": 0.5, "rate": 100, "identities": 40}
    )
    raw["drain_seconds"] = 2
    raw["schedule_tolerance_seconds"] = 1.0
    raw["startup_seconds"] = 60
    raw.update(changes)
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


@pytest.fixture
def config(tmp_path: Path) -> Path:
    return _smoke_config(_CONFIG, tmp_path / "config.json")


@pytest.fixture
def registration(config: Path) -> Registration:
    return Registration.load(config)


@pytest.fixture
def v5_config(tmp_path: Path) -> Path:
    return _smoke_config(_V5_CONFIG, tmp_path / "v5.json")


@pytest.fixture
def concurrent(tmp_path: Path) -> Registration:
    raw = json.loads(_CONCURRENT_CONFIG.read_text(encoding="utf-8"))
    raw["status"] = "frozen"
    raw["profiles"]["primary"]["documents"] = 64
    raw["hot_keys"] = 32
    raw.update(
        {
            "warmup_seconds": 0.5,
            "drain_seconds": 2,
            "schedule_tolerance_seconds": 1.0,
            "startup_seconds": 60,
        }
    )
    raw["frozen"] = {
        "rates": {"steady": 100},
        "window_seconds": {"active": 1},
        "calibration_summary": {},
    }
    path = tmp_path / "concurrent.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return Registration.load(path)


def _cell(registration: Registration, workload: str, path: str) -> Cell:
    return next(
        cell
        for cell in smoke_cells(registration)
        if cell.workload == workload and cell.path == path
    )


def _no_children() -> bool:
    return not [
        child
        for child in psutil.Process().children()
        if child.is_running()
        and child.status() != psutil.STATUS_ZOMBIE
        and any("spawn_main" in part for part in child.cmdline())
    ]


@pytest.mark.timeout(120)
@pytest.mark.parametrize(
    ("workload", "path"),
    [
        (workload, path)
        for workload in ("hot", "active", "cold")
        for path in ("direct", "independent", "shared", "shared-index")
    ],
)
def test_smoke_windows_identify_every_owner(
    replica: IsolatedReplicaSet,
    registration: Registration,
    v5_config: Path,
    workload: str,
    path: str,
) -> None:
    if path == "shared-index":
        registration = Registration.load(v5_config)
    cell = _cell(registration, workload, path)

    record = window.run_window(replica, registration, cell)

    workers = cast("list[JsonDict]", record["workers_measured"])
    assert record["healthy"] is True
    assert record["completed"] == record["offered"]
    assert len(workers) == cell.workers
    assert record["harness_includes"] == window.HARNESS_INCLUDES
    assert cast("int", record["server_memory_bytes"]) > 0
    memory = cast("JsonDict", record["memory"])
    assert cast("int", memory["samples"]) > 0
    streams = sum(
        cast("int", ready["streams"])
        for ready in cast("list[JsonDict]", record["ready"])
    )
    assert streams == (cell.workers if path == "independent" else 0)
    if path in {"shared", "shared-index"}:
        owner = cast("JsonDict", record["owner"])
        assert cast("float", owner["cpu_seconds"]) >= 0
        assert cast("float", memory["steady_owner_pss_bytes"]) > 0
        assert owner["health"] == "healthy"
        assert cast("dict[str, int]", owner["commands"])["stream:opened"] == 0
    else:
        assert "owner" not in record
    if workload == "hot" and path == "shared-index":
        assert [
            cast("JsonDict", worker["endpoint"])["requests"] for worker in workers
        ] == [0] * cell.workers
    if workload == "active" and path != "direct":
        lag_owner = owner if path != "independent" else workers[0]["lag"]
        assert cast("JsonDict", lag_owner)["invalidations"] == 200
    if workload == "cold" and path != "direct":
        assert validation_failure(record, registration) is None
    assert _no_children()


@pytest.mark.timeout(120)
def test_a_planned_steady_cell_shares_the_hot_set_across_workers(
    replica: IsolatedReplicaSet, concurrent: Registration
) -> None:
    cell = next(
        cell
        for cell in run.planned(concurrent, "steady", concurrent.paths)
        if cell.workers == 4 and cell.path == "independent"
    )

    record = window.run_window(replica, concurrent, cell)

    workers = cast("list[JsonDict]", record["workers_measured"])
    assert record["healthy"] is True
    assert record["completed"] == record["offered"] == 100
    assert [ready["entries"] for ready in cast("list[JsonDict]", record["ready"])] == [
        32
    ] * 4
    assert sum(cast("int", worker["streams"]) for worker in workers) == 4
    assert [cast("JsonDict", worker["lag"])["invalidations"] for worker in workers] == [
        5
    ] * 4
    assert _no_children()


def _delete_first_document(client: MongoClient[BsonDict], **kwargs: object) -> object:
    summary = _ORIGINAL_SEED(client, **kwargs)  # type: ignore[arg-type]
    database = cast("str", kwargs["database"])
    client[database][cast("str", kwargs["collection"])].delete_one({"_id": 0})
    return summary


def _more_invalidations(registration: Registration, cell: Cell) -> object:
    workload = _ORIGINAL_WORKLOAD(registration, cell)
    return replace(workload, expected_invalidations=workload.expected_invalidations + 1)


def _more_entries(registration: Registration, cell: Cell) -> object:
    workload = _ORIGINAL_WORKLOAD(registration, cell)
    return replace(workload, expected_entries=workload.expected_entries + 1)


def _failing_sampler(sampler: window.GroupMemorySampler) -> None:
    sampler.error = "PSS sampling failed: deliberate"


@dataclass(frozen=True, slots=True)
class _Failure:
    workload: str
    path: str
    target: str
    replacement: object
    message: str


@pytest.mark.timeout(120)
@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(
            _Failure(
                "hot",
                "independent",
                "seed_catalogue",
                _delete_first_document,
                "disappeared",
            ),
            id="worker-failure",
        ),
        pytest.param(
            _Failure(
                "hot", "shared", "seed_catalogue", _delete_first_document, "disappeared"
            ),
            id="shared-worker-failure",
        ),
        pytest.param(
            _Failure(
                "active",
                "independent",
                "_workload",
                _more_invalidations,
                "drain incomplete",
            ),
            id="independent-lag-capture",
        ),
        pytest.param(
            _Failure(
                "active", "shared", "_workload", _more_invalidations, "drain incomplete"
            ),
            id="shared-lag-capture",
        ),
        pytest.param(
            _Failure(
                "hot", "independent", "_workload", _more_entries, "not fully admitted"
            ),
            id="independent-working-set",
        ),
        pytest.param(
            _Failure("hot", "shared", "_workload", _more_entries, "not fully admitted"),
            id="shared-working-set",
        ),
    ],
)
def test_setup_and_collection_failures_are_rejected_and_reclaimed(
    replica: IsolatedReplicaSet,
    registration: Registration,
    monkeypatch: pytest.MonkeyPatch,
    failure: _Failure,
) -> None:
    monkeypatch.setattr(window, failure.target, failure.replacement)

    with pytest.raises(BenchmarkSetupError, match=failure.message):
        window.run_window(
            replica, registration, _cell(registration, failure.workload, failure.path)
        )

    assert _no_children()


@pytest.mark.timeout(120)
def test_an_undersized_shared_index_fails_the_window(
    replica: IsolatedReplicaSet, tmp_path: Path
) -> None:
    registration = Registration.load(
        _smoke_config(
            _V5_CONFIG,
            tmp_path / "undersized.json",
            shared_index={
                "slots": 16,
                "arena_bytes": 1024 * 1024,
                "namespaces": 1,
                "ring_tokens": 64,
            },
        )
    )

    with pytest.raises(BenchmarkSetupError, match="did not publish the working set"):
        window.run_window(
            replica, registration, _cell(registration, "hot", "shared-index")
        )

    assert _no_children()


@pytest.mark.timeout(120)
def test_missing_memory_metrics_fail_the_window(
    replica: IsolatedReplicaSet,
    registration: Registration,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(window.GroupMemorySampler, "_run", _failing_sampler)

    with pytest.raises(BenchmarkSetupError, match="PSS sampling failed"):
        window.run_window(replica, registration, _cell(registration, "hot", "direct"))


_ORIGINAL_WAIT = window._wait


def _late_wait(deadline: float) -> None:
    _ORIGINAL_WAIT(deadline + 1.5)


def _failing_update(*_args: object, **_kwargs: object) -> None:
    raise OperationFailure("deliberate write failure")


@dataclass(frozen=True, slots=True)
class _WriteFailure:
    target: object
    name: str
    replacement: object
    message: str


@pytest.mark.timeout(120)
@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(
            _WriteFailure(window, "_wait", _late_wait, "write schedule exceeded"),
            id="late-write",
        ),
        pytest.param(
            _WriteFailure(
                Collection,
                "update_one",
                _failing_update,
                "harness MongoDB write failed",
            ),
            id="write-error",
        ),
    ],
)
def test_harness_write_failures_reject_the_window(
    replica: IsolatedReplicaSet,
    registration: Registration,
    monkeypatch: pytest.MonkeyPatch,
    failure: _WriteFailure,
) -> None:
    monkeypatch.setattr(failure.target, failure.name, failure.replacement)

    with pytest.raises(BenchmarkSetupError, match=failure.message):
        window.run_window(
            replica, registration, _cell(registration, "active", "direct")
        )


@contextmanager
def _shared_replica(replica: IsolatedReplicaSet) -> Generator[IsolatedReplicaSet]:
    yield replica


@pytest.mark.timeout(300)
@pytest.mark.parametrize(
    ("source", "candidate"),
    [
        pytest.param(_CONFIG, "shared", id="v4"),
        pytest.param(_V5_CONFIG, "shared-index", id="v5"),
    ],
)
def test_smoke_command_records_every_cell(
    replica: IsolatedReplicaSet,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: Path,
    candidate: str,
) -> None:
    config = _smoke_config(source, tmp_path / "config.json")
    monkeypatch.setattr(
        run, "IsolatedReplicaSet", lambda _limits: _shared_replica(replica)
    )
    output = tmp_path / "smoke.json"

    run.main(["--smoke", "--config", str(config), "--output", str(output)])

    report = json.loads(output.read_text(encoding="utf-8"))
    cells = cast("list[JsonDict]", report["cells"])
    assert report["phase"] == "smoke"
    assert len(cells) == 9
    assert all(cell["healthy"] for cell in cells)
    assert {cell["path"] for cell in cells} == {"direct", "independent", candidate}
    for cell in cells:
        workers = cast("list[JsonDict]", cell["workers_measured"])
        assert [worker["streams"] for worker in workers] == [
            1 if cell["path"] == "independent" else 0
        ] * len(workers)
        if cell["path"] == candidate:
            owner = cast("JsonDict", cell["owner"])
            before = cast("JsonDict", owner["before"])
            assert (
                cast("dict[str, int]", before["upstream_commands"])["stream:opened"]
                == 1
            )
            assert cast("dict[str, int]", owner["commands"])["stream:opened"] == 0
            assert owner["health"] == "healthy"
    environment = cast("JsonDict", report["environment"])
    assert environment["configuration_sha256"] == Registration.load(config).digest
    native = cast("JsonDict", environment["native_extension"])
    assert cast("str", native["rustc"]).startswith("rustc version ")


def test_smoke_command_rejects_a_failed_window(
    config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object) -> JsonDict:
        raise BenchmarkSetupError("deliberate collection failure")

    monkeypatch.setattr(
        run,
        "IsolatedReplicaSet",
        lambda _limits: _shared_replica(cast("IsolatedReplicaSet", object())),
    )
    monkeypatch.setattr(run, "run_window", fail)

    with pytest.raises(BenchmarkSetupError, match="deliberate collection failure"):
        run.main(
            ["--smoke", "--config", str(config), "--output", str(tmp_path / "out.json")]
        )


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        pytest.param(["--smoke"], "--output is required", id="output"),
        pytest.param(
            ["--output", "{existing}"], "output already exists", id="existing"
        ),
        pytest.param(["--output", "{new}"], "choose --smoke", id="mode"),
        pytest.param(
            ["--output", "{new}", "--phase", "screening"],
            "frozen registration",
            id="unfrozen",
        ),
    ],
)
def test_command_line_rejects_unsafe_invocations(
    config: Path,
    tmp_path: Path,
    arguments: list[str],
    message: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    existing = tmp_path / "existing.json"
    existing.write_text("{}")
    substituted = [
        argument.format(existing=existing, new=tmp_path / "new.json")
        for argument in arguments
    ]

    with pytest.raises(SystemExit):
        run.main([*substituted, "--config", str(config)])

    assert message in capsys.readouterr().err


def test_phase_command_runs_the_planned_baseline_cells(
    config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = json.loads(config.read_text(encoding="utf-8"))
    raw["status"] = "frozen"
    raw["frozen"] = {
        "rates": {"primary": 100, "cold": 100, "sensitivity": 100},
        "window_seconds": {"hot": 30, "active": 60, "sensitivity": 30},
        "calibration_summary": {},
    }
    config.write_text(json.dumps(raw), encoding="utf-8")
    measured: list[Cell] = []

    def measure(_replica: object, _registration: Registration, cell: Cell) -> JsonDict:
        measured.append(cell)
        return {"healthy": True}

    monkeypatch.setattr(
        run,
        "IsolatedReplicaSet",
        lambda _limits: _shared_replica(cast("IsolatedReplicaSet", object())),
    )
    monkeypatch.setattr(run, "run_window", measure)

    run.main(
        [
            "--phase",
            "cold",
            "--baselines-only",
            "--config",
            str(config),
            "--output",
            str(tmp_path / "a.json"),
        ]
    )
    run.main(
        [
            "--phase",
            "capacity",
            "--baselines-only",
            "--only",
            "sync:8",
            "--config",
            str(config),
            "--output",
            str(tmp_path / "b.json"),
        ]
    )

    assert {cell.path for cell in measured} == {"direct", "independent"}
    assert {cell.phase for cell in measured} == {"cold", "capacity"}
    assert {
        (cell.model, cell.workers) for cell in measured if cell.phase == "capacity"
    } == {("sync", 8)}
    report = json.loads((tmp_path / "b.json").read_text(encoding="utf-8"))
    assert report["exploratory"] == "cells limited to sync:8"


def test_calibration_and_freeze_commands(
    config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        run,
        "IsolatedReplicaSet",
        lambda _limits: _shared_replica(cast("IsolatedReplicaSet", object())),
    )
    monkeypatch.setattr(
        run,
        "calibrate",
        lambda *_args: {"outcome": "inconclusive", "reason": "deliberate"},
    )
    output = tmp_path / "calibration.json"

    run.main(
        ["--calibrate-baselines", "--config", str(config), "--output", str(output)]
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["calibration"]["outcome"] == "inconclusive"
    with pytest.raises(BenchmarkSetupError, match="only validated"):
        run.main(["--freeze", str(output), "--config", str(config)])


@pytest.mark.timeout(120)
def test_exploratory_transport_diagnostics_are_labelled(tmp_path: Path) -> None:
    output = tmp_path / "diagnostics.json"

    diagnostics.main(["--entries", "8", "--repetitions", "1", "--output", str(output)])

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["label"].startswith("exploratory")
    assert {
        "proxy_coarse_operation",
        "socket_sync",
        "socket_async_event_loop",
        "socket_async_thread_executor",
    } <= report.keys()
    assert all(
        report[name]["calls"] == 8
        for name in ("proxy_coarse_operation", "socket_sync", "socket_async_event_loop")
    )


def _tiny_frozen(config: Path) -> None:
    raw = json.loads(config.read_text(encoding="utf-8"))
    raw["profiles"]["primary"]["documents"] = 64
    raw["warmup_seconds"] = 0.5
    raw["status"] = "frozen"
    raw["frozen"] = {
        "rates": {"primary": 100, "cold": 100, "sensitivity": 100},
        "window_seconds": {"hot": 1, "active": 1, "sensitivity": 1},
        "calibration_summary": {},
    }
    config.write_text(json.dumps(raw), encoding="utf-8")


@pytest.mark.timeout(180)
@pytest.mark.parametrize("workers", [1, 4], ids=["one-worker", "four-workers"])
def test_profiled_windows_summarize_owner_and_worker_hot_paths(
    config: Path, tmp_path: Path, workers: PositiveInt
) -> None:
    _tiny_frozen(config)
    output = tmp_path / "profile.json"

    diagnostics.main(
        [
            "--config",
            str(config),
            "--profile",
            "screening",
            str(workers),
            "async",
            "--output",
            str(output),
        ]
    )

    windows = json.loads(output.read_text(encoding="utf-8"))["windows"]
    shared = next(window for window in windows if window["path"] == "shared")
    direct = next(window for window in windows if window["path"] == "direct")
    for measured in windows:
        assert (
            sum(name.startswith("worker-") for name in measured["profiles"]) == workers
        )
    assert sum(name.startswith("owner-") for name in shared["profiles"]) == 1
    assert shared["owner_busy_seconds"] > 0
    assert direct["owner_busy_seconds"] is None


@pytest.mark.timeout(180)
@pytest.mark.parametrize(
    ("workload", "path", "changes"),
    [
        *(
            pytest.param(
                "hot",
                path,
                {"profile": "find16", "model": model},
                id=f"find16-{model}-{path}",
            )
            for model in ("sync", "async")
            for path in ("direct", "independent", "shared")
        ),
        pytest.param("cold", "direct", {"model": "sync"}, id="cold-sync"),
        *(
            pytest.param(
                "hot",
                "independent",
                {"model": model, "loop": "closed", "rate": None},
                id=f"closed-{model}",
            )
            for model in ("sync", "async")
        ),
    ],
)
def test_sensitivity_cold_and_closed_loop_windows_complete(
    replica: IsolatedReplicaSet,
    config: Path,
    workload: str,
    path: str,
    changes: dict[str, object],
) -> None:
    raw = json.loads(config.read_text(encoding="utf-8"))
    raw["profiles"]["find16"].update({"documents": 128, "categories": 4})
    config.write_text(json.dumps(raw), encoding="utf-8")
    registration = Registration.load(config)
    cell = replace(_cell(registration, workload, path), **changes)  # type: ignore[arg-type]

    record = window.run_window(replica, registration, cell)

    assert record["healthy"] is True
    assert cast("int", record["completed"]) > 0


@pytest.mark.timeout(180)
def test_observer_overhead_compares_matched_sampling_rates(
    config: Path, tmp_path: Path
) -> None:
    _tiny_frozen(config)
    output = tmp_path / "observer.json"

    diagnostics.main(
        ["--config", str(config), "--observer-overhead", "--output", str(output)]
    )

    rows = json.loads(output.read_text(encoding="utf-8"))["observer_overhead"]
    assert {(row["memory_sample_seconds"], row["path"]) for row in rows} == {
        (seconds, path) for seconds in (0.2, 5.0) for path in ("independent", "shared")
    }
