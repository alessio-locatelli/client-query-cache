from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import psutil
import pytest
from pymongo.errors import OperationFailure

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.shared_cache import diagnostics, run, window
from benchmarks.stream_cost.shared_cache.dataset import seed_catalogue
from benchmarks.stream_cost.shared_cache.protocol import Registration, smoke_cells
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from pymongo import MongoClient

    from benchmarks.stream_cost.shared_cache.protocol import Cell, Payload

pytestmark = pytest.mark.integration

_CONFIG = Path("reports/shared-worker-cache/v4/config.json")
_ORIGINAL_WORKLOAD = window._workload
_ORIGINAL_SEED = seed_catalogue


@pytest.fixture(scope="module")
def replica() -> Iterator[IsolatedReplicaSet]:
    with IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="1g")) as replica_set:
        yield replica_set


@pytest.fixture
def config(tmp_path: Path) -> Path:
    raw = json.loads(_CONFIG.read_text(encoding="utf-8"))
    raw["status"] = "pending-calibration"
    raw["profiles"]["smoke"]["documents"] = 64
    raw["phases"]["smoke"].update(
        {"window_seconds": 1, "warmup_seconds": 0.5, "rate": 100}
    )
    raw["drain_seconds"] = 2
    raw["schedule_tolerance_seconds"] = 1.0
    raw["startup_seconds"] = 60
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


@pytest.fixture
def registration(config: Path) -> Registration:
    return Registration.load(config)


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
        for path in ("direct", "independent", "shared")
    ],
)
def test_smoke_windows_identify_every_owner(
    replica: IsolatedReplicaSet, registration: Registration, workload: str, path: str
) -> None:
    cell = _cell(registration, workload, path)

    record = window.run_window(replica, registration, cell)

    workers = cast("list[Payload]", record["workers_measured"])
    assert record["healthy"] is True
    assert record["completed"] == record["offered"]
    assert len(workers) == cell.workers
    assert record["harness_includes"] == window.HARNESS_INCLUDES
    assert cast("int", record["server_memory_bytes"]) > 0
    memory = cast("Payload", record["memory"])
    assert cast("int", memory["samples"]) > 0
    streams = sum(
        cast("int", ready["streams"])
        for ready in cast("list[Payload]", record["ready"])
    )
    assert streams == (cell.workers if path == "independent" else 0)
    if path == "shared":
        owner = cast("Payload", record["owner"])
        assert cast("float", owner["cpu_seconds"]) >= 0
        assert cast("float", memory["steady_owner_pss_bytes"]) > 0
        assert owner["health"] == "healthy"
    else:
        assert "owner" not in record
    if workload == "active" and path != "direct":
        lag_owner = owner if path == "shared" else workers[0]["lag"]
        assert cast("Payload", lag_owner)["invalidations"] == 200
    assert _no_children()


def _delete_first_document(
    client: MongoClient[dict[str, object]], **kwargs: object
) -> object:
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
def test_missing_memory_metrics_fail_the_window(
    replica: IsolatedReplicaSet,
    registration: Registration,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(window.GroupMemorySampler, "_run", _failing_sampler)

    with pytest.raises(BenchmarkSetupError, match="PSS sampling failed"):
        window.run_window(replica, registration, _cell(registration, "hot", "direct"))


@pytest.mark.timeout(120)
@pytest.mark.parametrize(
    ("failure", "message"),
    [
        pytest.param("late", "write schedule exceeded", id="late-write"),
        pytest.param("write", "harness MongoDB write failed", id="write-error"),
    ],
)
def test_harness_write_failures_reject_the_window(
    replica: IsolatedReplicaSet,
    registration: Registration,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    message: str,
) -> None:
    original_wait = window._wait
    if failure == "late":
        monkeypatch.setattr(
            window, "_wait", lambda deadline: original_wait(deadline + 1.5)
        )
    else:
        from pymongo.synchronous.collection import Collection  # noqa: PLC0415

        def fail(*_args: object, **_kwargs: object) -> None:
            raise OperationFailure("deliberate write failure")

        monkeypatch.setattr(Collection, "update_one", fail)

    with pytest.raises(BenchmarkSetupError, match=message):
        window.run_window(
            replica, registration, _cell(registration, "active", "direct")
        )


@contextmanager
def _shared_replica(replica: IsolatedReplicaSet) -> Generator[IsolatedReplicaSet]:
    yield replica


@pytest.mark.timeout(300)
def test_smoke_command_records_every_cell(
    replica: IsolatedReplicaSet,
    config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        run, "IsolatedReplicaSet", lambda _limits: _shared_replica(replica)
    )
    output = tmp_path / "smoke.json"

    run.main(["--smoke", "--config", str(config), "--output", str(output)])

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["phase"] == "smoke"
    assert len(report["cells"]) == 9
    assert all(cell["healthy"] for cell in report["cells"])
    assert (
        report["environment"]["configuration_sha256"]
        == Registration.load(config).digest
    )


def test_smoke_command_rejects_a_failed_window(
    config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object) -> Payload:
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

    def measure(_replica: object, _registration: Registration, cell: Cell) -> Payload:
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
            "--config",
            str(config),
            "--output",
            str(tmp_path / "b.json"),
        ]
    )

    assert {cell.path for cell in measured if cell.phase == "cold"} == {
        "direct",
        "independent",
    }
    assert {cell.phase for cell in measured} == {"cold", "capacity"}


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


@pytest.mark.timeout(180)
def test_profiled_windows_summarize_owner_and_worker_hot_paths(
    config: Path, tmp_path: Path
) -> None:
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
    output = tmp_path / "profile.json"

    diagnostics.main(
        [
            "--config",
            str(config),
            "--profile",
            "screening",
            "1",
            "async",
            "--output",
            str(output),
        ]
    )

    windows = json.loads(output.read_text(encoding="utf-8"))["windows"]
    shared = next(window for window in windows if window["path"] == "shared")
    direct = next(window for window in windows if window["path"] == "direct")
    assert {"owner", "worker-shared"} <= shared["profiles"].keys()
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
