from __future__ import annotations

import json
import runpy
import sys
from typing import TYPE_CHECKING

import pytest

from benchmarks.stream_cost.report import validate_report
from benchmarks.stream_cost.run import run_standard_matrix
from benchmarks.stream_cost.topology import ResourceLimits

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("direct_path_proxy", [False, True])
def test_controlled_matrix_emits_valid_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, direct_path_proxy: bool
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
            ["benchmarks.stream_cost.run", "--output-dir", str(tmp_path)],
        )
        runpy.run_path("benchmarks/stream_cost/run.py", run_name="__main__")

    report_paths = tuple(sorted(tmp_path.glob("*.report.v1.json")))
    assert len(report_paths) == 12
    for report_path in report_paths:
        report = json.loads(report_path.read_text())
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
