from __future__ import annotations

import datetime
from dataclasses import replace

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
from client_query_cache._types import JsonDict, NonNegativeInt

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


def _valid_report() -> JsonDict:
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


def _member(report: JsonDict, *path: str | NonNegativeInt) -> object:
    node: object = report
    for key in path:
        if isinstance(key, str):
            assert isinstance(node, dict)
            node = node[key]
        else:
            assert isinstance(node, list)
            node = node[key]
    return node


def _object(report: JsonDict, *path: str | NonNegativeInt) -> JsonDict:
    node = _member(report, *path)
    assert isinstance(node, dict)
    return node


def _array(report: JsonDict, *path: str | NonNegativeInt) -> list[object]:
    node = _member(report, *path)
    assert isinstance(node, list)
    return node


def _logical_metrics() -> JsonDict:
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
    ("path", "key"),
    [
        *(
            pytest.param((), key, id=key)
            for key in (
                "schema_version",
                "identity",
                "environment",
                "workload",
                "limitations",
                "measurement",
            )
        ),
        *(
            pytest.param(("identity",), key, id=f"identity_{key}")
            for key in (
                "revision",
                "library_version",
                "python_version",
                "pymongo_version",
            )
        ),
        *(
            pytest.param(("environment",), key, id=f"environment_{key}")
            for key in (
                "mongodb_version",
                "topology",
                "member_count",
                "resource_limits",
            )
        ),
        *(
            pytest.param(("workload",), key, id=f"workload_{key}")
            for key in ("name", "parameters")
        ),
        *(
            pytest.param(("limitations", 0), key, id=f"limitation_{key}")
            for key in ("label", "description")
        ),
        *(
            pytest.param(("measurement",), key, id=f"measurement_{key}")
            for key in ("wall_seconds", "process_cpu_seconds", "container_cpu_seconds")
        ),
    ],
)
def test_validate_report_rejects_a_missing_member(
    path: tuple[str | NonNegativeInt, ...], key: str
) -> None:
    report = _valid_report()
    del _object(report, *path)[key]

    with pytest.raises(ReportValidationError):
        validate_report(report)


@pytest.mark.parametrize(
    ("path", "key", "value"),
    [
        pytest.param((), "schema_version", "999", id="unsupported_schema_version"),
        pytest.param(
            ("environment", "resource_limits"),
            "cpu",
            [],
            id="non_string_resource_limit_value",
        ),
        pytest.param(
            ("workload", "parameters"),
            "nested",
            {"a": 1},
            id="non_scalar_workload_parameter_value",
        ),
        *(
            pytest.param(
                ("workload", "parameters"),
                "sample_reads",
                invalid_count,
                id=f"non_integer_sample_count_{invalid_count!r}",
            )
            for invalid_count in (None, "1", 1.5)
        ),
        pytest.param(
            ("measurement", "variants", 0),
            "by_outcome",
            [
                {
                    "operation": "read",
                    "outcome": "raw",
                    "sample_count": 1,
                    "p50_seconds": 0.1,
                    "p95_seconds": 0.1,
                    "p99_seconds": 0.1,
                }
            ],
            id="idle_latency_samples",
        ),
        pytest.param(
            ("measurement", "logical_metrics", "cache"),
            "wire_bytes",
            10,
            id="universal_wire_byte_label",
        ),
        pytest.param(
            ("measurement",),
            "direct_path_bytes",
            {"sent": 10, "received": 10, "scope": "all wire traffic"},
            id="proxy_bytes_without_direct_path_scope",
        ),
        pytest.param(
            ("measurement",),
            "change_stream_cost_comparison",
            {
                "container_cpu_seconds": {"raw": 0.1},
                "direct_path_bytes": {"available": False, "raw": None, "cache": None},
            },
            id="incomplete_change_stream_cost_comparison",
        ),
    ],
)
def test_validate_report_rejects_an_invalid_member(
    path: tuple[str | NonNegativeInt, ...], key: str, value: object
) -> None:
    report = _valid_report()
    _object(report, *path)[key] = value

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
    _object(report, "workload", "parameters")[key] = value

    with pytest.raises(ReportValidationError, match="JSON-serializable"):
        validate_report(report)


def test_validate_report_rejects_a_circular_reference() -> None:
    report = _valid_report()
    _object(report, "workload", "parameters")["self"] = report

    with pytest.raises(ReportValidationError, match="JSON-serializable"):
        validate_report(report)


@pytest.mark.parametrize("variant_index", [0, 1])
def test_validate_report_rejects_missing_operation_latency_samples(
    variant_index: NonNegativeInt,
) -> None:
    report = _valid_report()
    _object(report, "workload", "parameters")["sample_reads"] = 1
    _array(report, "measurement", "variants")[1 - variant_index] = {
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
    _object(report, "workload", "parameters")["sample_reads"] = 2
    for variant in _array(report, "measurement", "variants"):
        assert isinstance(variant, dict)
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


def test_build_report_omits_change_stream_cost_comparison_by_default() -> None:
    assert "change_stream_cost_comparison" not in _object(
        _valid_report(), "measurement"
    )


@pytest.mark.parametrize(
    ("raw_measurement", "cache_measurement", "expected_direct_path_bytes"),
    [
        pytest.param(
            ControlledMeasurement(1.0, 0.1, 0.2, None, None),
            ControlledMeasurement(1.0, 0.1, 0.3, None, None),
            {
                "available": False,
                "raw": None,
                "cache": None,
                "delta": None,
                "delta_percent": None,
            },
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
                "delta_percent": {"sent": 50.0, "received": 25.0},
            },
            id="with_a_proxy",
        ),
        pytest.param(
            ControlledMeasurement(1.0, 0.1, 0.0, 0, 0),
            ControlledMeasurement(1.0, 0.1, 0.05, 10, 20),
            {
                "available": True,
                "raw": {"sent": 0, "received": 0},
                "cache": {"sent": 10, "received": 20},
                "delta": {"sent": 10, "received": 20},
                "delta_percent": {"sent": None, "received": None},
            },
            id="zero_baseline",
        ),
    ],
)
def test_build_report_change_stream_cost_comparison_direct_path_bytes(
    raw_measurement: ControlledMeasurement,
    cache_measurement: ControlledMeasurement,
    expected_direct_path_bytes: JsonDict,
) -> None:
    variant = STANDARD_WORKLOAD_VARIANTS[0]
    outcome = WorkloadVariantOutcome(
        variant=variant,
        reads=PairedReadOutcome(variant=variant, raw_results=(), cache_results=()),
        writes_issued=0,
        warmup_delta=PrimingDelta(admissions=1, hits=1),
    )
    report = build_report(
        _valid_config(),
        ControlledMeasurement(1.0, 0.1, 0.2, None, None),
        outcome,
        _logical_metrics(),
        change_stream_cost=ChangeStreamCostComparison(
            raw=raw_measurement, cache=cache_measurement
        ),
    )

    validate_report(report)
    comparison = _object(report, "measurement")["change_stream_cost_comparison"]
    delta_seconds = (
        cache_measurement.container_cpu_seconds - raw_measurement.container_cpu_seconds
    )
    delta_percent = (
        delta_seconds / raw_measurement.container_cpu_seconds * 100
        if raw_measurement.container_cpu_seconds
        else None
    )
    assert comparison == {
        "container_cpu_seconds": {
            "raw": raw_measurement.container_cpu_seconds,
            "cache": cache_measurement.container_cpu_seconds,
            "delta_seconds": delta_seconds,
            "delta_percent": delta_percent,
        },
        "direct_path_bytes": expected_direct_path_bytes,
    }


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
    report = build_report(
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
    )

    validate_report(report)
    assert _object(report, "measurement", "variants", 1)["by_outcome"] == [
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
