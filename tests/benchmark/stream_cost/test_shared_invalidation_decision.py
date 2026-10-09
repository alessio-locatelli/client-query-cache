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


def test_native_lag_omits_failed_cells(native_report: Payload) -> None:
    cast("list[Payload]", native_report["cells"])[0]["healthy"] = False
    assert describe_native_lag(native_report) == ()


def test_native_lag_rejects_incomplete_capture(native_report: Payload) -> None:
    sample = cast("list[Payload]", native_report["cells"])[0]
    worker = cast("list[Payload]", sample["workers_measured"])[0]
    worker["lag_windows"] = ((0.01,) * 20,) * 5
    with pytest.raises(BenchmarkSetupError, match="capture"):
        describe_native_lag(native_report)


def _baseline_report(idle: tuple[float, ...], active: tuple[float, ...]) -> Payload:
    cells: list[Payload] = []
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
    "inject_fault",
    [
        pytest.param(lambda cells, sample: cells.remove(sample), id="missing-cell"),
        pytest.param(
            lambda _cells, sample: sample.update(healthy=False), id="failed-cell"
        ),
        pytest.param(
            lambda cells, sample: cells.append(sample.copy()), id="duplicate-cell"
        ),
        pytest.param(
            lambda _cells, sample: sample.pop("server_cpu_seconds"), id="missing-cpu"
        ),
        pytest.param(
            lambda _cells, sample: sample.update(server_cpu_seconds=-1),
            id="negative-cpu",
        ),
        pytest.param(
            lambda _cells, sample: sample.update(server_cpu_seconds=float("nan")),
            id="nan-cpu",
        ),
        pytest.param(
            lambda _cells, sample: sample.update(application_seconds=59),
            id="wrong-duration",
        ),
    ],
)
def test_gate_retains_incomplete_alternatives(
    baseline_factory: Callable[[tuple[float, ...], tuple[float, ...]], Payload],
    inject_fault: Callable[[list[Payload], Payload], object],
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
    inject_fault(cells, sample)
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
    "unregister",
    [
        pytest.param(lambda report: report.update(phase="smoke"), id="smoke-phase"),
        pytest.param(
            lambda report: report.update(configuration_sha256="different protocol"),
            id="changed-registration",
        ),
        pytest.param(
            lambda report: cast("Payload", report["protocol"]).update(window_seconds=1),
            id="shortened-schedule",
        ),
    ],
)
def test_gate_rejects_unregistered_reports(
    baseline_factory: Callable[[tuple[float, ...], tuple[float, ...]], Payload],
    unregister: Callable[[Payload], object],
) -> None:
    report = baseline_factory((0.01,) * 6, (0.01,) * 6)
    unregister(report)
    with pytest.raises(BenchmarkSetupError, match="registered baseline protocol"):
        evaluate_baseline(report)
