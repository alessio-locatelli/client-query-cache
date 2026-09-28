from __future__ import annotations

import copy
import datetime
from dataclasses import replace
from typing import Any, cast

import pytest

from benchmarks.stream_cost.config import (
    BenchmarkConfig,
    BenchmarkEnvironment,
    BenchmarkIdentity,
    Limitation,
    WorkloadParameters,
)
from benchmarks.stream_cost.errors import ReportValidationError
from benchmarks.stream_cost.measurement import (
    ChangeStreamCostComparison,
    ControlledMeasurement,
    OperationLatency,
)
from benchmarks.stream_cost.report import build_report, validate_report
from benchmarks.stream_cost.workload import (
    STANDARD_WORKLOAD_VARIANTS,
    PairedReadOutcome,
    PrimingDelta,
    WorkloadVariantOutcome,
)

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
        workload=WorkloadParameters(
            name="idle-small", parameters={"sample_reads": 0, "sample_writes": 0}
        ),
        limitations=(Limitation("clock-skew", "raw lag includes server-host skew"),),
    )


def _valid_report() -> dict[str, Any]:
    variant = STANDARD_WORKLOAD_VARIANTS[0]
    outcome = WorkloadVariantOutcome(
        variant=variant,
        reads=PairedReadOutcome(variant=variant, raw_results=(), cache_results=()),
        writes_issued=0,
        warmup_delta=PrimingDelta(admissions=1, hits=1),
    )
    return build_report(
        _valid_config(),
        ControlledMeasurement(1.0, 0.1, 0.2, None, None),
        outcome,
        _logical_metrics(),
    )


def _logical_metrics() -> dict[str, object]:
    return {
        "cache": {
            "hits": 1,
            "misses": 1,
            "evictions": 0,
            "bypasses": 0,
            "oversized_bypasses": 0,
            "used_bytes": 100,
            "shared_budget_bytes": 1000,
            "entry_count": 1,
        },
        "streams": [],
    }


def test_build_report_produces_a_report_that_validates() -> None:
    validate_report(_valid_report())


@pytest.mark.parametrize(
    "top_level_key",
    [
        "schema_version",
        "identity",
        "environment",
        "workload",
        "limitations",
        "measurement",
    ],
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
    ("section", "missing_field"),
    [
        pytest.param("identity", "revision", id="identity_revision"),
        pytest.param("identity", "library_version", id="identity_library_version"),
        pytest.param("identity", "python_version", id="identity_python_version"),
        pytest.param("identity", "pymongo_version", id="identity_pymongo_version"),
        pytest.param(
            "environment", "mongodb_version", id="environment_mongodb_version"
        ),
        pytest.param("environment", "topology", id="environment_topology"),
        pytest.param("environment", "member_count", id="environment_member_count"),
        pytest.param(
            "environment", "resource_limits", id="environment_resource_limits"
        ),
        pytest.param("workload", "name", id="workload_name"),
        pytest.param("workload", "parameters", id="workload_parameters"),
    ],
)
def test_validate_report_rejects_an_incomplete_section(
    section: str, missing_field: str
) -> None:
    report = _valid_report()
    del report[section][missing_field]

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


@pytest.mark.parametrize(
    ("key", "value"),
    [
        pytest.param(
            "issued_at", datetime.datetime.now(datetime.UTC), id="non_serializable"
        ),
        pytest.param("ratio", float("nan"), id="non_finite_float"),
    ],
)
def test_validate_report_rejects_a_non_json_serializable_value(
    key: str, value: object
) -> None:
    report = _valid_report()
    report["workload"]["parameters"][key] = value

    with pytest.raises(ReportValidationError, match="JSON-serializable"):
        validate_report(report)


def test_validate_report_rejects_a_circular_reference() -> None:
    report = _valid_report()
    report["workload"]["parameters"]["self"] = report

    with pytest.raises(ReportValidationError, match="JSON-serializable"):
        validate_report(report)


@pytest.mark.parametrize(
    "field", ["wall_seconds", "process_cpu_seconds", "container_cpu_seconds"]
)
def test_validate_report_requires_each_controlled_measurement(field: str) -> None:
    report = _valid_report()
    del report["measurement"][field]

    with pytest.raises(ReportValidationError):
        validate_report(report)


def test_validate_report_rejects_idle_latency_samples() -> None:
    report = _valid_report()
    report["measurement"]["variants"][0]["by_outcome"] = [
        {
            "operation": "read",
            "outcome": "raw",
            "sample_count": 1,
            "p50_seconds": 0.1,
            "p95_seconds": 0.1,
            "p99_seconds": 0.1,
        }
    ]

    with pytest.raises(ReportValidationError):
        validate_report(report)


@pytest.mark.parametrize("variant_index", [0, 1])
def test_validate_report_rejects_missing_operation_latency_samples(
    variant_index: int,
) -> None:
    report = _valid_report()
    report["workload"]["parameters"]["sample_reads"] = 1
    report["measurement"]["variants"][1 - variant_index] = {
        "name": "cache" if variant_index == 0 else "raw",
        "operation_count": 1,
        "no_latency_samples": False,
        "by_outcome": [
            {
                "operation": "read",
                "outcome": "hit" if variant_index == 0 else "raw",
                "sample_count": 1,
                "p50_seconds": 0.1,
                "p95_seconds": 0.1,
                "p99_seconds": 0.1,
            }
        ],
    }

    with pytest.raises(ReportValidationError, match="latency samples"):
        validate_report(report)


def test_validate_report_rejects_distribution_count_mismatch() -> None:
    report = _valid_report()
    report["workload"]["parameters"]["sample_reads"] = 2
    for variant in report["measurement"]["variants"]:
        variant["operation_count"] = 2
        variant["no_latency_samples"] = False
        variant["by_outcome"] = [
            {
                "operation": "read",
                "outcome": "raw" if variant["name"] == "raw" else "hit",
                "sample_count": 1,
                "p50_seconds": 0.1,
                "p95_seconds": 0.1,
                "p99_seconds": 0.1,
            }
        ]

    with pytest.raises(ReportValidationError, match="outcome distributions"):
        validate_report(report)


@pytest.mark.parametrize("invalid_count", [None, "1", 1.5])
def test_validate_report_rejects_non_integer_sample_count(
    invalid_count: object,
) -> None:
    report = _valid_report()
    report["workload"]["parameters"]["sample_reads"] = invalid_count

    with pytest.raises(ReportValidationError):
        validate_report(report)


def test_validate_report_rejects_universal_wire_byte_label() -> None:
    report = _valid_report()
    report["measurement"]["logical_metrics"]["cache"]["wire_bytes"] = 10

    with pytest.raises(ReportValidationError):
        validate_report(report)


def test_validate_report_rejects_proxy_bytes_without_direct_path_scope() -> None:
    report = _valid_report()
    report["measurement"]["direct_path_bytes"] = {
        "sent": 10,
        "received": 10,
        "scope": "all wire traffic",
    }

    with pytest.raises(ReportValidationError):
        validate_report(report)


def test_build_report_omits_change_stream_cost_comparison_by_default() -> None:
    assert "change_stream_cost_comparison" not in _valid_report()["measurement"]


@pytest.mark.parametrize(
    ("raw_measurement", "cache_measurement", "expected_direct_path_bytes"),
    [
        pytest.param(
            ControlledMeasurement(1.0, 0.1, 0.2, None, None),
            ControlledMeasurement(1.0, 0.1, 0.3, None, None),
            {"available": False, "raw": None, "cache": None, "delta": None},
            id="without_a_proxy",
        ),
        pytest.param(
            ControlledMeasurement(1.0, 0.1, 0.2, 100, 200),
            ControlledMeasurement(1.0, 0.1, 0.3, 150, 250),
            {
                "available": True,
                "raw": {"sent": 100, "received": 200},
                "cache": {"sent": 150, "received": 250},
                "delta": {"sent": 50, "received": 50},
            },
            id="with_a_proxy",
        ),
    ],
)
def test_build_report_change_stream_cost_comparison_direct_path_bytes(
    raw_measurement: ControlledMeasurement,
    cache_measurement: ControlledMeasurement,
    expected_direct_path_bytes: dict[str, object],
) -> None:
    variant = STANDARD_WORKLOAD_VARIANTS[0]
    outcome = WorkloadVariantOutcome(
        variant=variant,
        reads=PairedReadOutcome(variant=variant, raw_results=(), cache_results=()),
        writes_issued=0,
        warmup_delta=PrimingDelta(admissions=1, hits=1),
    )
    report = cast(
        "dict[str, Any]",
        build_report(
            _valid_config(),
            ControlledMeasurement(1.0, 0.1, 0.2, None, None),
            outcome,
            _logical_metrics(),
            change_stream_cost=ChangeStreamCostComparison(
                raw=raw_measurement, cache=cache_measurement
            ),
        ),
    )

    validate_report(report)
    comparison = report["measurement"]["change_stream_cost_comparison"]
    assert comparison == {
        "container_cpu_seconds": {
            "raw": raw_measurement.container_cpu_seconds,
            "cache": cache_measurement.container_cpu_seconds,
            "delta_seconds": (
                cache_measurement.container_cpu_seconds
                - raw_measurement.container_cpu_seconds
            ),
        },
        "direct_path_bytes": expected_direct_path_bytes,
    }


def test_validate_report_rejects_an_incomplete_change_stream_cost_comparison() -> None:
    report = _valid_report()
    report["measurement"]["change_stream_cost_comparison"] = {
        "container_cpu_seconds": {"raw": 0.1},
        "direct_path_bytes": {"available": False, "raw": None, "cache": None},
    }

    with pytest.raises(ReportValidationError):
        validate_report(report)


def test_build_report_preserves_cache_outcome_distributions() -> None:
    variant = STANDARD_WORKLOAD_VARIANTS[3]
    outcome = WorkloadVariantOutcome(
        variant=variant,
        reads=PairedReadOutcome(
            variant=variant,
            raw_results=({}, {}),
            cache_results=({}, {}),
            raw_latencies=(
                OperationLatency("read", "raw", 0.2),
                OperationLatency("read", "raw", 0.4),
            ),
            cache_latencies=(
                OperationLatency("read", "miss", 0.3),
                OperationLatency("read", "hit", 0.1),
            ),
        ),
        writes_issued=0,
        warmup_delta=PrimingDelta(admissions=1, hits=1),
    )
    report = cast(
        "dict[str, Any]",
        build_report(
            replace(
                _valid_config(),
                workload=WorkloadParameters(
                    name=variant.name,
                    parameters={"sample_reads": 2, "sample_writes": 0},
                ),
            ),
            ControlledMeasurement(1.0, 0.1, 0.2, None, None),
            outcome,
            _logical_metrics(),
        ),
    )

    validate_report(report)
    assert report["measurement"]["variants"][1]["by_outcome"] == [
        {
            "operation": "read",
            "outcome": "hit",
            "sample_count": 1,
            "p50_seconds": 0.1,
            "p95_seconds": 0.1,
            "p99_seconds": 0.1,
        },
        {
            "operation": "read",
            "outcome": "miss",
            "sample_count": 1,
            "p50_seconds": 0.3,
            "p95_seconds": 0.3,
            "p99_seconds": 0.3,
        },
    ]
