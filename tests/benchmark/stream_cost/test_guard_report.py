from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from benchmarks.stream_cost import guard_report
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.guard_decision import BLOCK_PAIRS, Decision
from benchmarks.stream_cost.guard_report import (
    build_guard_report,
    measure_and_evaluate_case,
    report_to_json,
    report_to_summary,
)
from benchmarks.stream_cost.guard_runner import (
    PairedCaseMeasurement,
    RevisionEnvironment,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _environment(tmp_path: Path, revision: str) -> RevisionEnvironment:
    return RevisionEnvironment(
        revision=revision,
        repo_root=tmp_path / revision,
        python_executable=tmp_path / revision / "python",
        python_version="3.14.6",
        workload_digest="digest",
    )


@pytest.mark.parametrize(
    ("head_seconds", "expected_decision"),
    [
        ((0.04,) * BLOCK_PAIRS, Decision.REGRESSION),
        ((0.021,) * BLOCK_PAIRS, Decision.WITHIN_BOUNDARY),
    ],
)
def test_measure_and_evaluate_case_reports_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    head_seconds: tuple[float, ...],
    expected_decision: Decision,
) -> None:
    measurement = PairedCaseMeasurement(
        case="sync_hit",
        profile="small",
        base_seconds=(0.025,) * BLOCK_PAIRS,
        head_seconds=head_seconds,
    )
    monkeypatch.setattr(
        guard_report, "measure_paired_case", lambda *_args, **_kwargs: measurement
    )

    report = measure_and_evaluate_case(
        _environment(tmp_path, "base"),
        _environment(tmp_path, "head"),
        "mongodb://unused",
        "sync_hit",
        "small",
    )

    assert report.decision is expected_decision
    assert report.base_seconds == measurement.base_seconds
    assert report.head_seconds == measurement.head_seconds
    assert report.reason


@pytest.mark.parametrize(
    "error_type",
    [BenchmarkSetupError, ValueError],
    ids=["setup-failure", "invalid-data"],
)
def test_measure_and_evaluate_case_reports_measurement_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_type: type[Exception]
) -> None:
    def fail(*_args: object, **_kwargs: object) -> PairedCaseMeasurement:
        raise error_type("base and head environments do not match")

    monkeypatch.setattr(guard_report, "measure_paired_case", fail)

    report = measure_and_evaluate_case(
        _environment(tmp_path, "base"),
        _environment(tmp_path, "head"),
        "mongodb://unused",
        "sync_hit",
        "small",
    )

    assert report.decision is Decision.MEASUREMENT_ERROR
    assert report.base_seconds is None
    assert report.head_seconds is None
    assert "do not match" in report.reason


def test_measurement_error_reason_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    overly_long_reason = "x" * 10_000

    def fail(*_args: object, **_kwargs: object) -> PairedCaseMeasurement:
        raise BenchmarkSetupError(overly_long_reason)

    monkeypatch.setattr(guard_report, "measure_paired_case", fail)

    report = measure_and_evaluate_case(
        _environment(tmp_path, "base"),
        _environment(tmp_path, "head"),
        "mongodb://unused",
        "sync_hit",
        "small",
    )

    assert len(report.reason) <= guard_report._MAX_REASON_LENGTH


def test_report_to_json_and_summary_omit_documents_and_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    measurement = PairedCaseMeasurement(
        case="sync_hit",
        profile="small",
        base_seconds=(0.025,) * BLOCK_PAIRS,
        head_seconds=(0.021,) * BLOCK_PAIRS,
    )
    monkeypatch.setattr(
        guard_report, "measure_paired_case", lambda *_args, **_kwargs: measurement
    )
    case_report = measure_and_evaluate_case(
        _environment(tmp_path, "base"),
        _environment(tmp_path, "head"),
        "mongodb://unused",
        "sync_hit",
        "small",
    )
    report = build_guard_report("base-sha", "head-sha", (case_report,))

    payload = report_to_json(report)
    summary = report_to_summary(report)

    assert payload["base_revision"] == "base-sha"
    assert payload["passed"] is True
    assert "mongodb://unused" not in str(payload)
    assert "mongodb://unused" not in summary
    cases = cast("list[dict[str, object]]", payload["cases"])
    assert set(cases[0]) == {
        "case",
        "profile",
        "decision",
        "reason",
        "base_seconds",
        "head_seconds",
        "base_median_seconds",
        "head_median_seconds",
        "median_ratio",
        "lower_ratio",
        "upper_ratio",
    }
