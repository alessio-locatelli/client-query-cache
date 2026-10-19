from __future__ import annotations

import copy
import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from benchmarks.stream_cost.errors import BenchmarkConfigurationError
from benchmarks.stream_cost.shared_cache import run
from benchmarks.stream_cost.shared_cache.protocol import (
    CalibrationTopologyCell,
    Cell,
    Registration,
    _calibration_topology_cell,
    fault_recovery_cells,
)
from benchmarks.stream_cost.shared_cache.run import planned
from benchmarks.stream_cost.shared_cache.window import _spec, _workload

if TYPE_CHECKING:
    from benchmarks.stream_cost.shared_cache.protocol import RecoveryFaultCell

pytestmark = pytest.mark.unit

_CONFIG = Path("reports/shared-worker-cache/v4/config.json")


def _connection_loss_only(registration: Registration) -> dict[str, object]:
    settings = cast("dict[str, object]", registration.raw["fault_recovery"])
    settings["cases"] = ["connection-loss"]
    error_classes = cast("dict[str, object]", settings["error_classes"])
    settings["error_classes"] = {"connection-loss": error_classes["connection-loss"]}
    return settings


def _registration(*, frozen: bool) -> Registration:
    raw = copy.deepcopy(Registration.load(_CONFIG).raw)
    calibration = raw["calibration"]
    assert isinstance(calibration, dict)
    raw["status"] = "frozen" if frozen else "pending-calibration"
    calibration_families = calibration["families"]
    assert isinstance(calibration_families, dict)
    calibration_families["stepdown"] = {
        "probe_workload": "hot",
        "topology": "three-member",
        "cells": [["active", "async", 4]],
    }
    frozen_configuration = raw["frozen"]
    assert isinstance(frozen_configuration, dict)
    frozen_rates = frozen_configuration["rates"]
    assert isinstance(frozen_rates, dict)
    frozen_rates["stepdown"] = 1500
    raw["fault_recovery"] = {
        "cases": [
            "connection-loss",
            "stepdown",
            "history-loss",
            "worker-restart",
        ],
        "rate_families": {
            "single-member": "primary",
            "three-member": "stepdown",
        },
        "repetitions": 5,
        "before_seconds": 20,
        "after_seconds": 120,
        "recovery_deadline_seconds": 110,
        "before_interval_seconds": 10,
        "timeline_cadence_seconds": 0.25,
        "error_classes": {
            "connection-loss": [
                "AutoReconnect",
                "ConnectionFailure",
                "NetworkTimeout",
                "CursorNotFound",
            ],
            "stepdown": [
                "AutoReconnect",
                "ConnectionFailure",
                "NetworkTimeout",
                "NotWritablePrimary",
                "InterruptedDueToReplStateChange",
                "PrimarySteppedDown",
            ],
            "history-loss": [
                "AutoReconnect",
                "ConnectionFailure",
                "NetworkTimeout",
                "CursorNotFound",
                "ChangeStreamHistoryLost",
            ],
            "worker-restart": [
                "AutoReconnect",
                "ConnectionFailure",
                "NetworkTimeout",
                "CursorNotFound",
            ],
        },
        "smoke": {
            "rate": 100,
            "before_seconds": 10,
            "after_seconds": 30,
            "recovery_deadline_seconds": 20,
        },
        "recovery_criterion": {
            "bucket_seconds": 1,
            "minimum_completion_fraction": 0.99,
            "request_p99_multiple": 2,
            "backlog_grace_p99_multiple": 2,
        },
    }
    return Registration(raw, "fault-recovery-test")


def test_freeze_applies_the_observer_selected_timeline_cadence(
    tmp_path: Path,
) -> None:
    pending = _registration(frozen=False)
    config = tmp_path / "config.json"
    config.write_text(json.dumps(pending.raw), encoding="utf-8")
    pending = Registration.load(config)
    calibration = tmp_path / "calibration.json"
    calibration.write_text(
        json.dumps(
            {
                "environment": {"configuration_sha256": pending.digest},
                "calibration": {
                    "outcome": "validated",
                    "rates": {"primary": 100, "stepdown": 80},
                    "window_seconds": {"hot": 6},
                    "null_fault_check": {"outcome": "passed"},
                },
            }
        ),
        encoding="utf-8",
    )
    observer = tmp_path / "observer.json"
    observer.write_text(
        json.dumps(
            {
                "environment": {"configuration_sha256": pending.digest},
                "fault_observer_overhead": {
                    "outcome": "passed",
                    "selected_cadence_seconds": 1.0,
                },
            }
        ),
        encoding="utf-8",
    )

    run.freeze(config, calibration, observer)

    frozen = Registration.load(config)
    summary = frozen.section("frozen")["calibration_summary"]
    assert isinstance(summary, dict)
    cadence = frozen.section("fault_recovery")["timeline_cadence_seconds"]
    assert frozen.frozen
    assert cadence == pytest.approx(1.0)
    selected_cadence = summary["fault_observer_cadence_seconds"]
    assert isinstance(selected_cadence, (int, float))
    assert selected_cadence == pytest.approx(1.0)


def test_smoke_cells_cover_every_applicable_worker_fault_path() -> None:
    registration = _registration(frozen=False)

    cells = fault_recovery_cells(registration, smoke=True)
    direct_history = [
        cell
        for cell in cells
        if cell.fault_case == "history-loss" and cell.path == "direct"
    ]
    stepdown = [cell for cell in cells if cell.fault_case == "stepdown"]

    assert len(cells) == 7
    assert direct_history == []
    assert {cell.path for cell in stepdown} == {"direct", "independent"}
    assert all(cell.topology == "three-member" for cell in stepdown)
    assert all(cell.smoke for cell in cells)
    assert all(cell.window_seconds == 40 for cell in cells)
    assert all(cell.injection_offset_seconds == 10 for cell in cells)


def test_registration_supports_legacy_fault_recovery_without_registration_number() -> (
    None
):
    registration = _registration(frozen=False)
    del registration.raw["registration"]
    settings = cast("dict[str, object]", registration.raw["fault_recovery"])
    del settings["recovery_criterion"]

    validated = Registration(registration.raw, registration.digest)

    assert validated.raw["fault_recovery"] is settings


@pytest.mark.parametrize(
    ("invalid_field", "message"),
    [
        pytest.param("settings", "settings are invalid", id="settings-type"),
        pytest.param("registration", "registration number is invalid", id="number"),
        pytest.param(
            "criterion", "recovery criterion is invalid", id="criterion-shape"
        ),
    ],
)
def test_registration_rejects_invalid_fault_recovery_criteria(
    invalid_field: str, message: str
) -> None:
    registration = _registration(frozen=False)
    settings = cast("dict[str, object]", registration.raw["fault_recovery"])
    if invalid_field == "settings":
        registration.raw["fault_recovery"] = None
    elif invalid_field == "registration":
        registration.raw["registration"] = True
    else:
        settings["recovery_criterion"] = {"bucket_seconds": 1}

    with pytest.raises(BenchmarkConfigurationError, match=message):
        Registration(registration.raw, registration.digest)


def test_timed_fault_cells_require_freeze_and_use_registered_rate() -> None:
    pending = _registration(frozen=False)
    with pytest.raises(BenchmarkConfigurationError, match="frozen registration"):
        fault_recovery_cells(pending)

    frozen = _registration(frozen=True)
    cells = planned(frozen, "fault", ("direct", "independent"))

    assert len(cells) == 35
    assert all(not cast("RecoveryFaultCell", cell).smoke for cell in cells)
    assert {
        cell.rate
        for cell in cells
        if cast("RecoveryFaultCell", cell).topology == "single-member"
    } == {frozen.rate("primary")}
    assert {
        cell.rate
        for cell in cells
        if cast("RecoveryFaultCell", cell).topology == "three-member"
    } == {frozen.rate("stepdown")}


def test_planner_builds_controlled_direct_and_independent_workers() -> None:
    registration = _registration(frozen=True)
    cells = planned(registration, "fault", ("direct", "independent"))
    workload = _workload(
        registration,
        next(cell for cell in cells if cell.path == "direct"),
    )

    specs = {
        path: _spec(
            registration,
            next(cell for cell in cells if cell.path == path),
            workload,
            "mongodb://127.0.0.1:27017/?directConnection=true",
            index=0,
            attachment=None,
        )
        for path in ("direct", "independent")
    }

    assert specs["direct"].controls_enabled
    assert specs["independent"].controls_enabled
    assert specs["direct"].cell.path == "direct"
    assert specs["independent"].cell.path == "independent"
    assert specs["direct"].attachment is None
    assert specs["independent"].attachment is None
    assert all(spec.timeline_enabled for spec in specs.values())
    assert all(spec.topology == "single-member" for spec in specs.values())


def test_fault_smoke_cli_accepts_pending_registration_and_marks_non_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registration = _registration(frozen=False)
    config = tmp_path / "config.json"
    config.write_text(json.dumps(registration.raw), encoding="utf-8")
    output = tmp_path / "smoke.json"

    def record_smoke(
        recorder: run.Recorder,
        _registration: Registration,
        cells: tuple[RecoveryFaultCell, ...],
    ) -> list[dict[str, object]]:
        records = [
            {
                **asdict(cell),
                "healthy": True,
                "outcome": "recovered",
                "injection": {"injected": True},
                "requests": {
                    "offered": 10,
                    "counts": {
                        "completed": 10,
                        "failed": 0,
                        "interrupted": 0,
                        "undelivered": 0,
                    },
                },
                "recovery": {"recovered": True},
                "correctness": {"available": True, "passed": True, "probed": 1},
            }
            for cell in cells
        ]
        recorder.report["cells"] = records
        recorder.flush()
        return records

    monkeypatch.setattr(run.Recorder, "run_recovery_faults", record_smoke)
    run.main(
        [
            "--smoke",
            "--phase",
            "fault",
            "--config",
            str(config),
            "--output",
            str(output),
        ]
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["phase"] == "fault-smoke"
    assert report["smoke"] is True
    assert report["evidence"] is False
    assert len(report["cells"]) == 7
    assert all(cell["smoke"] is True for cell in report["cells"])


@pytest.mark.parametrize(
    "cases",
    [
        pytest.param(None, id="not-a-list"),
        pytest.param([], id="empty"),
        pytest.param(["connection-loss", "connection-loss"], id="duplicate"),
        pytest.param(["unknown"], id="unsupported"),
        pytest.param([1], id="non-string"),
    ],
)
def test_fault_recovery_cells_reject_invalid_case_lists(cases: object) -> None:
    registration = _registration(frozen=False)
    settings = cast("dict[str, object]", registration.raw["fault_recovery"])
    settings["cases"] = cases

    with pytest.raises(BenchmarkConfigurationError, match="cases"):
        fault_recovery_cells(registration, smoke=True)


@pytest.mark.parametrize(
    ("section", "key", "value", "message"),
    [
        pytest.param("smoke", "before_seconds", 0, "timings", id="no-before"),
        pytest.param("smoke", "after_seconds", 2, "timings", id="deadline-too-late"),
        pytest.param(
            "fault_recovery",
            "before_interval_seconds",
            0,
            "before interval",
            id="interval",
        ),
        pytest.param(
            "fault_recovery", "error_classes", {}, "error classes", id="error-classes"
        ),
        pytest.param(
            "fault_recovery", "timeline_cadence_seconds", 0, "cadence", id="cadence"
        ),
    ],
)
def test_fault_recovery_cells_reject_invalid_settings(
    section: str, key: str, value: object, message: str
) -> None:
    registration = _registration(frozen=False)
    settings = cast("dict[str, object]", registration.raw["fault_recovery"])
    target = (
        settings
        if section == "fault_recovery"
        else cast("dict[str, object]", settings[section])
    )
    target[key] = value

    with pytest.raises(BenchmarkConfigurationError, match=message):
        fault_recovery_cells(registration, smoke=True)


def test_fault_recovery_cells_support_legacy_single_rate_family() -> None:
    registration = _registration(frozen=True)
    settings = _connection_loss_only(registration)
    del settings["rate_families"]
    settings["rate_family"] = "primary"

    cells = fault_recovery_cells(registration)

    assert cells
    assert all(cell.rate == registration.rate("primary") for cell in cells)


@pytest.mark.parametrize(
    ("rate_families", "message"),
    [
        pytest.param(
            {"single-member": "missing"}, "missing calibration family", id="missing"
        ),
        pytest.param(
            {"single-member": "stepdown"}, "topology differs", id="wrong-topology"
        ),
    ],
)
def test_fault_recovery_cells_validate_calibration_families(
    rate_families: dict[str, str], message: str
) -> None:
    registration = _registration(frozen=True)
    settings = _connection_loss_only(registration)
    settings["rate_families"] = rate_families

    with pytest.raises(BenchmarkConfigurationError, match=message):
        fault_recovery_cells(registration)


def test_fault_recovery_cells_allow_an_empty_path_selection() -> None:
    registration = _registration(frozen=False)

    assert fault_recovery_cells(registration, (), smoke=True) == ()


def test_calibration_topology_cell_preserves_single_member_and_wraps_stepdown() -> None:
    cell = Cell(
        phase="calibration",
        block=0,
        workload="active",
        profile="primary",
        model="async",
        workers=4,
        path="direct",
        loop="open",
        concurrency=4,
        window_seconds=1.0,
        warmup_seconds=0,
        rate=10.0,
    )

    assert _calibration_topology_cell(cell, "single-member") is cell
    topology_cell = _calibration_topology_cell(cell, "three-member")
    assert isinstance(topology_cell, CalibrationTopologyCell)
    assert topology_cell.topology == "three-member"


def test_fault_evidence_cli_still_requires_a_frozen_registration(
    tmp_path: Path,
) -> None:
    registration = _registration(frozen=False)
    config = tmp_path / "config.json"
    config.write_text(json.dumps(registration.raw), encoding="utf-8")

    with pytest.raises(SystemExit, match="2"):
        run.main(
            [
                "--phase",
                "fault",
                "--config",
                str(config),
                "--output",
                str(tmp_path / "fault.json"),
            ]
        )
