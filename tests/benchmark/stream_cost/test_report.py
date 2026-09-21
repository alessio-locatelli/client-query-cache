from __future__ import annotations

import copy
import datetime
from typing import Any

import pytest

from benchmarks.stream_cost.config import (
    BenchmarkConfig,
    BenchmarkEnvironment,
    BenchmarkIdentity,
    Limitation,
    WorkloadParameters,
)
from benchmarks.stream_cost.errors import ReportValidationError
from benchmarks.stream_cost.report import build_report, validate_report

pytestmark = pytest.mark.unit


def _valid_config() -> BenchmarkConfig:
    return BenchmarkConfig(
        identity=BenchmarkIdentity(
            revision="abc123",
            library_version="0.1.0",
            python_version="3.14.6",
            pymongo_version="4.18.0",
        ),
        environment=BenchmarkEnvironment(
            mongodb_version="8.0.4",
            topology="replica-set",
            member_count=1,
            resource_limits={"cpu": "1"},
        ),
        workload=WorkloadParameters(name="idle", parameters={"duration_seconds": 30}),
        limitations=(Limitation("clock-skew", "raw lag includes server-host skew"),),
    )


def _valid_report() -> dict[str, Any]:
    return build_report(_valid_config())


def test_build_report_produces_a_report_that_validates() -> None:
    validate_report(_valid_report())


@pytest.mark.parametrize(
    "top_level_key",
    ["schema_version", "identity", "environment", "workload", "limitations"],
)
def test_validate_report_rejects_a_missing_top_level_section(
    top_level_key: str,
) -> None:
    report = _valid_report()
    del report[top_level_key]

    with pytest.raises(ReportValidationError):
        validate_report(report)


def test_validate_report_rejects_an_unsupported_schema_version() -> None:
    report = _valid_report()
    report["schema_version"] = "999"

    with pytest.raises(ReportValidationError):
        validate_report(report)


@pytest.mark.parametrize(
    "missing_field",
    ["revision", "library_version", "python_version", "pymongo_version"],
)
def test_validate_report_rejects_incomplete_identity(missing_field: str) -> None:
    report = _valid_report()
    del report["identity"][missing_field]

    with pytest.raises(ReportValidationError):
        validate_report(report)


@pytest.mark.parametrize(
    "missing_field", ["mongodb_version", "topology", "member_count", "resource_limits"]
)
def test_validate_report_rejects_incomplete_environment(missing_field: str) -> None:
    report = _valid_report()
    del report["environment"][missing_field]

    with pytest.raises(ReportValidationError):
        validate_report(report)


def test_validate_report_rejects_a_non_string_resource_limit_value() -> None:
    report = _valid_report()
    report["environment"]["resource_limits"]["cpu"] = []

    with pytest.raises(ReportValidationError):
        validate_report(report)


def test_validate_report_rejects_a_non_scalar_workload_parameter_value() -> None:
    report = _valid_report()
    report["workload"]["parameters"]["nested"] = {"a": 1}

    with pytest.raises(ReportValidationError):
        validate_report(report)


@pytest.mark.parametrize("missing_field", ["name", "parameters"])
def test_validate_report_rejects_incomplete_workload(missing_field: str) -> None:
    report = _valid_report()
    del report["workload"][missing_field]

    with pytest.raises(ReportValidationError):
        validate_report(report)


@pytest.mark.parametrize("missing_field", ["label", "description"])
def test_validate_report_rejects_incomplete_limitations(missing_field: str) -> None:
    report = _valid_report()
    report["limitations"] = [copy.deepcopy(report["limitations"][0])]
    del report["limitations"][0][missing_field]

    with pytest.raises(ReportValidationError):
        validate_report(report)


def test_validate_report_accepts_an_empty_limitations_list() -> None:
    report = _valid_report()
    report["limitations"] = []

    validate_report(report)


def test_report_validation_error_collects_every_violation_message() -> None:
    report = _valid_report()
    del report["identity"]
    del report["workload"]

    with pytest.raises(ReportValidationError) as excinfo:
        validate_report(report)

    assert len(excinfo.value.errors) >= 2


def test_validate_report_rejects_a_non_json_serializable_value() -> None:
    report = _valid_report()
    report["workload"]["parameters"]["issued_at"] = datetime.datetime.now(datetime.UTC)

    with pytest.raises(ReportValidationError, match="JSON-serializable"):
        validate_report(report)


def test_validate_report_rejects_a_non_finite_float() -> None:
    report = _valid_report()
    report["workload"]["parameters"]["ratio"] = float("nan")

    with pytest.raises(ReportValidationError, match="JSON-serializable"):
        validate_report(report)


def test_validate_report_rejects_a_circular_reference() -> None:
    report = _valid_report()
    report["workload"]["parameters"]["self"] = report

    with pytest.raises(ReportValidationError, match="JSON-serializable"):
        validate_report(report)
