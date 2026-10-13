from __future__ import annotations

import copy
import json
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.shared_cache import faults, run
from benchmarks.stream_cost.shared_cache.protocol import (
    FAULT_CASES,
    FaultCell,
    Registration,
    fault_applicability,
    fault_cells,
)
from benchmarks.stream_cost.shared_cache.window import run_window
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def replica() -> Iterator[IsolatedReplicaSet]:
    with IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="2g")) as topology:
        yield topology


@pytest.fixture(scope="module")
def registration() -> Registration:
    return Registration.load(Path("reports/shared-worker-cache/v6/config.json"))


@pytest.mark.parametrize("case", FAULT_CASES, ids=FAULT_CASES)
def test_registered_fault(
    replica: IsolatedReplicaSet, registration: Registration, case: str
) -> None:
    cell = next(
        cell
        for cell in fault_cells(registration)
        if isinstance(cell, FaultCell) and cell.fault_case == case
    )
    record = run_window(replica, registration, cell)
    assert record["healthy"], record["failure"]
    durations = record["durations"]
    assert isinstance(durations, dict)
    for name, applies in fault_applicability(registration)[case].items():
        assert (durations[name] is not None) is applies


@contextmanager
def _shared_replica(replica: IsolatedReplicaSet) -> Generator[IsolatedReplicaSet]:
    yield replica


def test_failed_pause_is_recorded_and_owner_is_resumed(
    replica: IsolatedReplicaSet,
    registration: Registration,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_detection(_trial: faults.FaultTrial) -> None:
        raise BenchmarkSetupError("injected detection timeout")

    raw = copy.deepcopy(registration.raw)
    raw["fault_cases"] = ["coordinator-pause"]
    raw["fault_timings"] = {
        "coordinator-pause": fault_applicability(registration)["coordinator-pause"]
    }
    phases = raw["phases"]
    assert isinstance(phases, dict)
    phases["fault"]["repetitions"] = 1
    config = tmp_path / "config.json"
    config.write_text(json.dumps(raw))
    output = tmp_path / "fault.json"
    monkeypatch.setattr(faults.FaultTrial, "detect", fail_detection)
    monkeypatch.setattr(
        run, "IsolatedReplicaSet", lambda _limits: _shared_replica(replica)
    )
    run.main(["--phase", "fault", "--config", str(config), "--output", str(output)])
    report = json.loads(output.read_text())
    record = report["cells"][0]
    assert record["healthy"] is False
    assert record["failure"] == "BenchmarkSetupError: injected detection timeout"
    assert record["events"]["injection"] > 0


def test_failed_priming_preserves_its_original_failure(
    replica: IsolatedReplicaSet,
    registration: Registration,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_priming(_trial: faults.FaultTrial) -> bool:
        raise BenchmarkSetupError("injected priming timeout")

    monkeypatch.setattr(faults.FaultTrial, "rewarmed", fail_priming)
    record = run_window(replica, registration, fault_cells(registration)[0])
    assert record["failure"] == "BenchmarkSetupError: injected priming timeout"
    durations = record["durations"]
    assert isinstance(durations, dict)
    assert all(value is None for value in durations.values())
