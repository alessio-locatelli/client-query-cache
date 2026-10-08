from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from typing import TYPE_CHECKING, cast

import pytest

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.multiprocess_run import _CONFIG, Protocol, planned_cells
from benchmarks.stream_cost.shared_invalidation_decision import evaluate_baseline

if TYPE_CHECKING:
    from collections.abc import Callable

    from benchmarks.stream_cost.multiprocess_run import Payload

pytestmark = pytest.mark.unit
_CONTROL_CPU_SECONDS = 6.0


@pytest.fixture
def baseline_factory() -> Callable[[tuple[float, ...], tuple[float, ...]], Payload]:
    return _baseline_report


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
