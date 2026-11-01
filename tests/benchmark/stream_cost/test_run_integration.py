from __future__ import annotations

import json
import runpy
import sys
from typing import TYPE_CHECKING

import pytest

from benchmarks.stream_cost.report import validate_report
from benchmarks.stream_cost.run import run_standard_matrix
from benchmarks.stream_cost.topology import ResourceLimits
from benchmarks.stream_cost.workload import STANDARD_WORKLOAD_VARIANTS

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


@pytest.mark.timeout(180)
@pytest.mark.parametrize(
    ("direct_path_proxy", "workloads"),
    [(False, ()), (True, ()), (False, ("read_heavy-small",))],
    ids=["direct", "proxy", "selected"],
)
def test_controlled_matrix_emits_valid_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    direct_path_proxy: bool,
    workloads: tuple[str, ...],
) -> None:
    if direct_path_proxy:
        run_standard_matrix(
            tmp_path,
            limits=ResourceLimits(cpus=1.0, memory="1g"),
            direct_path_proxy=True,
        )
    else:
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "benchmarks.stream_cost.run",
                "--output-dir",
                str(tmp_path),
                *(argument for name in workloads for argument in ("--workload", name)),
            ],
        )
        runpy.run_path("benchmarks/stream_cost/run.py", run_name="__main__")

    reports = [
        json.loads(report_path.read_text())
        for report_path in tmp_path.glob("*.report.v1.json")
    ]
    assert sorted(report["workload"]["name"] for report in reports) == sorted(
        workloads or (variant.name for variant in STANDARD_WORKLOAD_VARIANTS)
    )
    for report in reports:
        validate_report(report)
        measurement = report["measurement"]
        assert measurement["container_cpu_seconds"] >= 0
        assert measurement["warmup"]["admissions"] > 0
        assert measurement["warmup"]["hits"] > 0
        if direct_path_proxy:
            assert measurement["direct_path_bytes"]["scope"] == (
                "dedicated direct benchmark path only"
            )
        else:
            assert measurement["direct_path_bytes"] is None

        if report["workload"]["name"].startswith("idle-"):
            assert all(
                variant["operation_count"] == 0 and variant["no_latency_samples"]
                for variant in measurement["variants"]
            )
        else:
            assert all(
                variant["operation_count"] > 0 and not variant["no_latency_samples"]
                for variant in measurement["variants"]
            )
