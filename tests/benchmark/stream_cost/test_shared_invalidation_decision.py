from __future__ import annotations

import json
import math
import runpy
from dataclasses import asdict
from hashlib import sha256
from itertools import product
from typing import TYPE_CHECKING, cast

import pytest

from benchmarks.stream_cost import shared_invalidation_decision
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.multiprocess_run import _CONFIG, Protocol, planned_cells
from benchmarks.stream_cost.shared_invalidation_decision import (
    describe_native_lag,
    evaluate_baseline,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from benchmarks.stream_cost.multiprocess_run import Payload

pytestmark = pytest.mark.unit
_CONTROL_CPU_SECONDS = 6.0
_CAPTURE_P95_INDEX = 114  # Existing estimator: floor(0.95 * 120), zero-based.


def test_cli_prints_gate_and_lag_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    baseline_factory: Callable[[tuple[float, ...], tuple[float, ...]], Payload],
    native_report: Payload,
) -> None:
    report = baseline_factory((0.01,) * 6, (0.01,) * 6)
    native = cast("list[Payload]", native_report["cells"])[0]
    for sample in cast("list[Payload]", report["cells"]):
        if sample["path"] == "native" and sample["workload"] == "active":
            sample.update(
                {
                    key: native[key]
                    for key in (
                        "workers_measured",
                        "clock_offset_seconds",
                        "clock_uncertainty_seconds",
                    )
                }
            )
    output = tmp_path / "baseline.json"
    output.write_text(json.dumps(report))
    monkeypatch.setattr("sys.argv", ["shared_invalidation_decision", str(output)])
    runpy.run_path(str(shared_invalidation_decision.__file__), run_name="__main__")
    decision = json.loads(capsys.readouterr().out)
    assert decision["outcome"] == "below-threshold"
    assert len(decision["native_lag_context"]) == 24


@pytest.fixture
def baseline_factory() -> Callable[[tuple[float, ...], tuple[float, ...]], Payload]:
    return _baseline_report


@pytest.fixture
def native_report() -> Payload:
    return {
        "cells": [
            {
                "path": "native",
                "workload": "active",
                "healthy": True,
                "model": "sync",
                "block": 0,
                "workers": 1,
                "clock_offset_seconds": 0.01,
                "clock_uncertainty_seconds": 0.003,
                "workers_measured": [
                    {
                        "invalidations": 200,
                        "lag_windows": tuple(
                            tuple(rank * 0.0001 for rank in range(start, start + 20))
                            for start in range(0, 120, 20)
                        ),
                    }
                ],
            }
        ]
    }


@pytest.mark.parametrize(
    "clock_offset", [-0.02, 0.0, 0.01], ids=["negative-lag", "aligned", "server-ahead"]
)
def test_native_lag_matches_exact_capture_percentiles_and_clock_margin(
    native_report: Payload, clock_offset: float
) -> None:
    cast("list[Payload]", native_report["cells"])[0]["clock_offset_seconds"] = (
        clock_offset
    )
    interval = describe_native_lag(native_report)[0]
    percentiles = sorted(
        sorted(
            rank * 0.0001
            for window in indices
            for rank in range(window * 20, window * 20 + 20)
        )[_CAPTURE_P95_INDEX]
        for indices in product(range(6), repeat=6)
    )
    assert interval["p95_seconds"] == pytest.approx(0.0114 + clock_offset)
    assert interval["lower_seconds"] == pytest.approx(
        percentiles[math.ceil(0.025 * len(percentiles)) - 1] + clock_offset - 0.003
    )
    assert interval["upper_seconds"] == pytest.approx(
        percentiles[math.ceil(0.975 * len(percentiles)) - 1] + clock_offset + 0.003
    )


@pytest.mark.parametrize(
    "fault", ["failed", "capture"], ids=["failed-native-cell", "incomplete-capture"]
)
def test_native_lag_cannot_describe_failed_or_incomplete_cells(
    native_report: Payload, fault: str
) -> None:
    sample = cast("list[Payload]", native_report["cells"])[0]
    if fault == "failed":
        sample["healthy"] = False
        assert describe_native_lag(native_report) == ()
    else:
        worker = cast("list[Payload]", sample["workers_measured"])[0]
        worker["lag_windows"] = ((0.01,) * 20,) * 5
        with pytest.raises(BenchmarkSetupError, match="capture"):
            describe_native_lag(native_report)


def _baseline_report(idle: tuple[float, ...], active: tuple[float, ...]) -> Payload:
    cells: list[Payload] = []  # Populated with the registered cells.
    for cell in planned_cells():
        cpu_seconds = _CONTROL_CPU_SECONDS
        if cell.path == "stream-only" and cell.workers == 8:
            cpu_seconds += (active if cell.workload == "active" else idle)[
                cell.block
            ] * 60
        elif cell.path == "native-control":
            cpu_seconds = 1000.0
        cells.append(
            {
                **asdict(cell),
                "healthy": True,
                "server_cpu_seconds": cpu_seconds,
                "server_drain_cpu_seconds": 0.0,
                "application_seconds": 60,
            }
        )
    return {
        "phase": "baseline",
        "configuration_sha256": sha256(_CONFIG.read_bytes()).hexdigest(),
        "protocol": asdict(Protocol.load()),
        "cells": cells,
    }


@pytest.mark.parametrize(
    ("rates", "expected"),
    [
        ((0.01,) * 6, "below-threshold"),
        ((0.10,) * 6, "proceed"),
        ((0.01, 0.02, 0.03, 0.07, 0.08, 0.09), "inconclusive"),
        ((-0.03,) * 6, "below-threshold"),
    ],
    ids=["complete-below", "complete-opportunity", "overlapping", "signed-negative"],
)
def test_gate_preserves_signed_complete_outcomes(
    baseline_factory: Callable[[tuple[float, ...], tuple[float, ...]], Payload],
    rates: tuple[float, ...],
    expected: str,
) -> None:
    decision = evaluate_baseline(baseline_factory(rates, rates))
    assert decision["outcome"] == expected
    assert len(decision["comparisons"]) == 4
    assert all(comparison["complete"] for comparison in decision["comparisons"])
    assert decision["alpha"] == pytest.approx(0.05 / 4)
    assert decision["threshold"] == pytest.approx(0.05)


def test_active_opportunity_can_pass_with_idle_below_threshold(
    baseline_factory: Callable[[tuple[float, ...], tuple[float, ...]], Payload],
) -> None:
    decision = evaluate_baseline(baseline_factory((0.01,) * 6, (0.1,) * 6))
    assert decision["outcome"] == "proceed"
    assert all(
        comparison["outcome"]
        == ("opportunity" if comparison["workload"] == "active" else "below-threshold")
        for comparison in decision["comparisons"]
    )
    assert all(
        value == pytest.approx(0.09) for value in decision["active_minus_idle"].values()
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "failed",
        "duplicate",
        "metric-missing",
        "metric-negative",
        "metric-nan",
        "duration",
    ],
    ids=[
        "missing-cell",
        "failed-cell",
        "duplicate-cell",
        "missing-cpu",
        "negative-cpu",
        "nan-cpu",
        "wrong-duration",
    ],
)
def test_gate_retains_incomplete_alternatives(
    baseline_factory: Callable[[tuple[float, ...], tuple[float, ...]], Payload],
    fault: str,
) -> None:
    report = baseline_factory((0.01,) * 6, (0.01,) * 6)
    cells = cast("list[Payload]", report["cells"])
    sample = next(
        cell
        for cell in cells
        if cell["block"] == 0
        and cell["model"] == "async"
        and cell["workload"] == "idle"
        and cell["workers"] == 8
        and cell["path"] == "stream-only"
    )
    if fault == "missing":
        cells.remove(sample)
    elif fault == "failed":
        sample["healthy"] = False
    elif fault == "duplicate":
        cells.append(sample.copy())
    elif fault == "metric-missing":
        del sample["server_cpu_seconds"]
    elif fault == "metric-negative":
        sample["server_cpu_seconds"] = -1
    elif fault == "metric-nan":
        sample["server_cpu_seconds"] = float("nan")
    else:
        sample["application_seconds"] = 59
    decision = evaluate_baseline(report)
    assert decision["outcome"] == "inconclusive"
    assert len(decision["comparisons"]) == 4
    assert sum(comparison["complete"] for comparison in decision["comparisons"]) == 3
    incomplete = next(
        comparison
        for comparison in decision["comparisons"]
        if not comparison["complete"]
    )
    assert incomplete["failure"] is not None
    assert incomplete["lower"] is incomplete["upper"] is None


def test_gate_includes_active_drain_and_ignores_native_refetch_savings(
    baseline_factory: Callable[[tuple[float, ...], tuple[float, ...]], Payload],
) -> None:
    report = baseline_factory((0.0,) * 6, (0.0,) * 6)
    for cell in cast("list[Payload]", report["cells"]):
        if cell["workers"] == 8 and cell["path"] == "stream-only":
            cell["server_drain_cpu_seconds"] = 6.0
    decision = evaluate_baseline(report)
    assert decision["outcome"] == "proceed"
    assert all(
        comparison["estimate"]
        == pytest.approx(0.1 if comparison["workload"] == "active" else 0.0)
        for comparison in decision["comparisons"]
    )


@pytest.mark.parametrize(
    "fault",
    ["smoke", "hash", "protocol"],
    ids=["smoke-phase", "changed-registration", "shortened-schedule"],
)
def test_gate_rejects_unregistered_reports(
    baseline_factory: Callable[[tuple[float, ...], tuple[float, ...]], Payload],
    fault: str,
) -> None:
    report = baseline_factory((0.01,) * 6, (0.01,) * 6)
    if fault == "smoke":
        report["phase"] = "smoke"
    elif fault == "hash":
        report["configuration_sha256"] = "different protocol"
    else:
        cast("Payload", report["protocol"])["window_seconds"] = 1
    with pytest.raises(BenchmarkSetupError, match="registered baseline protocol"):
        evaluate_baseline(report)
