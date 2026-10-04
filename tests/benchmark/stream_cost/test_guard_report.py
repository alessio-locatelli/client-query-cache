from __future__ import annotations

import json
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
    ids=["regression", "within-boundary"],
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
    payload = report_to_json(build_guard_report("base-sha", "head-sha", (report,)))
    cases = cast("list[dict[str, object]]", payload["cases"])
    assert cases[0]["base_seconds"] is None
    assert cases[0]["head_seconds"] is None


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


@pytest.mark.parametrize(
    ("base_seconds", "head_seconds", "expected_reason", "serialized_base_seconds"),
    [
        (
            (0.004,) * BLOCK_PAIRS,
            (0.02,) * BLOCK_PAIRS,
            "base block 1: 0.004",
            (0.004,) * BLOCK_PAIRS,
        ),
        (
            (0.02,) * BLOCK_PAIRS,
            (0.02,) * (BLOCK_PAIRS - 1) + (0.004,),
            "head block 15: 0.004",
            (0.02,) * BLOCK_PAIRS,
        ),
        (
            (float("nan"),) * BLOCK_PAIRS,
            (0.02,) * BLOCK_PAIRS,
            "base block 1: nan",
            (None,) * BLOCK_PAIRS,
        ),
    ],
    ids=["short-base", "short-head", "nonfinite"],
)
def test_rejected_completed_measurements_retain_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    base_seconds: tuple[float, ...],
    head_seconds: tuple[float, ...],
    expected_reason: str,
    serialized_base_seconds: tuple[float | None, ...],
) -> None:
    measurement = PairedCaseMeasurement(
        case="sync_hit",
        profile="small",
        base_seconds=base_seconds,
        head_seconds=head_seconds,
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

    assert report.passed is False
    assert case_report.decision is Decision.MEASUREMENT_ERROR
    assert expected_reason in case_report.reason
    assert case_report.base_seconds == base_seconds
    assert case_report.head_seconds == head_seconds
    serialized = json.dumps(report_to_json(report), allow_nan=False)
    decoded = json.loads(serialized)
    assert decoded["schema_version"] == 2
    assert decoded["cases"][0]["base_seconds"] == list(serialized_base_seconds)
    assert decoded["cases"][0]["head_seconds"] == list(head_seconds)
    assert case_report.median_ratio is None
    assert expected_reason in report_to_summary(report)
    assert "minimum 0.005 seconds" in case_report.reason
