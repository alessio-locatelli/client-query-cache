from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.guard_decision import (
    BLOCK_PAIRS,
    MATERIAL_SLOWDOWN,
    Decision,
    evaluate_case,
)
from benchmarks.stream_cost.guard_runner import measure_paired_case

if TYPE_CHECKING:
    from benchmarks.stream_cost.guard_runner import RevisionEnvironment

SCHEMA_VERSION = 2
_MAX_REASON_LENGTH = 2000
_FAILING_DECISIONS = (Decision.REGRESSION, Decision.MEASUREMENT_ERROR)


@dataclass(frozen=True, slots=True)
class CaseReport:
    case: str
    profile: str
    decision: Decision
    reason: str
    base_seconds: tuple[float, ...] | None
    head_seconds: tuple[float, ...] | None
    base_median_seconds: float | None
    head_median_seconds: float | None
    median_ratio: float | None
    lower_ratio: float | None
    upper_ratio: float | None


def measurement_error_report(case: str, profile: str, reason: str) -> CaseReport:
    return CaseReport(
        case=case,
        profile=profile,
        decision=Decision.MEASUREMENT_ERROR,
        reason=reason[:_MAX_REASON_LENGTH],
        base_seconds=None,
        head_seconds=None,
        base_median_seconds=None,
        head_median_seconds=None,
        median_ratio=None,
        lower_ratio=None,
        upper_ratio=None,
    )


def measure_and_evaluate_case(
    base_environment: RevisionEnvironment,
    head_environment: RevisionEnvironment,
    uri: str,
    case: str,
    profile: str,
    *,
    block_pairs: int = BLOCK_PAIRS,
) -> CaseReport:
    try:
        measurement = measure_paired_case(
            base_environment,
            head_environment,
            uri,
            case,
            profile,
            block_pairs=block_pairs,
        )
    except BenchmarkSetupError as error:
        return measurement_error_report(case, profile, str(error))
    except ValueError as error:
        return measurement_error_report(case, profile, str(error))
    try:
        decision = evaluate_case(measurement.base_seconds, measurement.head_seconds)
    except ValueError as error:
        return replace(
            measurement_error_report(case, profile, str(error)),
            base_seconds=measurement.base_seconds,
            head_seconds=measurement.head_seconds,
        )
    return CaseReport(
        case=case,
        profile=profile,
        decision=decision.decision,
        reason=decision.reason,
        base_seconds=measurement.base_seconds,
        head_seconds=measurement.head_seconds,
        base_median_seconds=decision.base_median_seconds,
        head_median_seconds=decision.head_median_seconds,
        median_ratio=decision.median_ratio,
        lower_ratio=decision.lower_ratio,
        upper_ratio=decision.upper_ratio,
    )


@dataclass(frozen=True, slots=True)
class GuardReport:
    schema_version: int
    base_revision: str
    head_revision: str
    material_slowdown_boundary: float
    block_pairs: int
    cases: tuple[CaseReport, ...]
    base_python_version: str | None
    head_python_version: str | None

    @property
    def passed(self) -> bool:
        return all(case.decision not in _FAILING_DECISIONS for case in self.cases)


def build_guard_report(
    base_revision: str,
    head_revision: str,
    cases: tuple[CaseReport, ...],
    *,
    base_python_version: str | None = None,
    head_python_version: str | None = None,
) -> GuardReport:
    return GuardReport(
        schema_version=SCHEMA_VERSION,
        base_revision=base_revision,
        head_revision=head_revision,
        material_slowdown_boundary=MATERIAL_SLOWDOWN,
        block_pairs=BLOCK_PAIRS,
        cases=cases,
        base_python_version=base_python_version,
        head_python_version=head_python_version,
    )


def _json_seconds(
    seconds: tuple[float, ...] | None,
) -> tuple[float | None, ...] | None:
    if seconds is None:
        return None
    return tuple(value if math.isfinite(value) else None for value in seconds)


def report_to_json(report: GuardReport) -> dict[str, object]:
    return {
        "schema_version": report.schema_version,
        "base_revision": report.base_revision,
        "head_revision": report.head_revision,
        "base_python_version": report.base_python_version,
        "head_python_version": report.head_python_version,
        "material_slowdown_boundary": report.material_slowdown_boundary,
        "block_pairs": report.block_pairs,
        "passed": report.passed,
        "cases": [
            {
                "case": case.case,
                "profile": case.profile,
                "decision": case.decision,
                "reason": case.reason,
                "base_seconds": _json_seconds(case.base_seconds),
                "head_seconds": _json_seconds(case.head_seconds),
                "base_median_seconds": case.base_median_seconds,
                "head_median_seconds": case.head_median_seconds,
                "median_ratio": case.median_ratio,
                "lower_ratio": case.lower_ratio,
                "upper_ratio": case.upper_ratio,
            }
            for case in report.cases
        ],
    }


def report_to_summary(report: GuardReport) -> str:
    lines = [
        "| case | profile | decision | base (s) | head (s) | ratio | reason |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in report.cases:
        base_display = (
            "n/a"
            if case.base_median_seconds is None
            else f"{case.base_median_seconds:.4f}"
        )
        head_display = (
            "n/a"
            if case.head_median_seconds is None
            else f"{case.head_median_seconds:.4f}"
        )
        ratio_display = (
            "n/a" if case.median_ratio is None else f"{case.median_ratio:.2f}"
        )
        lines.append(
            f"| {case.case} | {case.profile} | {case.decision} | {base_display} | "
            f"{head_display} | {ratio_display} | {case.reason} |"
        )
    status = "PASSED" if report.passed else "FAILED"
    lines.extend(
        (
            "",
            (
                f"Guard {status}: base {report.base_revision} vs head "
                f"{report.head_revision}, {report.material_slowdown_boundary:.0%} "
                f"boundary, {report.block_pairs} paired blocks; Python "
                f"{report.base_python_version} vs {report.head_python_version}."
            ),
        )
    )
    return "\n".join(lines)
