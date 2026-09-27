from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jsonschema

from benchmarks.stream_cost.errors import ReportValidationError
from benchmarks.stream_cost.measurement import latency_distribution

if TYPE_CHECKING:
    from collections.abc import Mapping

    from benchmarks.stream_cost.config import BenchmarkConfig
    from benchmarks.stream_cost.measurement import (
        ChangeStreamCostComparison,
        ControlledMeasurement,
    )
    from benchmarks.stream_cost.workload import WorkloadVariantOutcome

SCHEMA_VERSION = "1"

_SCHEMA_PATH = Path(__file__).with_name("schemas") / "report.v1.schema.json"
_SCHEMA: Mapping[str, Any] = json.loads(_SCHEMA_PATH.read_text())


def _direct_path_bytes_pair(
    measurement: ControlledMeasurement,
) -> dict[str, int] | None:
    sent = measurement.direct_path_bytes_sent
    received = measurement.direct_path_bytes_received
    if sent is None or received is None:
        return None
    return {"sent": sent, "received": received}


def _change_stream_cost_comparison_payload(
    comparison: ChangeStreamCostComparison,
) -> dict[str, object]:
    raw_bytes = _direct_path_bytes_pair(comparison.raw)
    cache_bytes = _direct_path_bytes_pair(comparison.cache)
    available = raw_bytes is not None and cache_bytes is not None
    return {
        "container_cpu_seconds": {
            "raw": comparison.raw.container_cpu_seconds,
            "cache": comparison.cache.container_cpu_seconds,
        },
        "direct_path_bytes": {
            "available": available,
            "raw": raw_bytes if available else None,
            "cache": cache_bytes if available else None,
        },
    }


def build_report(
    config: BenchmarkConfig,
    measurement: ControlledMeasurement,
    outcome: WorkloadVariantOutcome,
    logical_metrics: Mapping[str, object],
    *,
    change_stream_cost: ChangeStreamCostComparison | None = None,
) -> dict[str, object]:
    report: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "identity": {
            "revision": config.identity.revision,
            "library_version": config.identity.library_version,
            "python_version": config.identity.python_version,
            "pymongo_version": config.identity.pymongo_version,
        },
        "environment": {
            "mongodb_version": config.environment.mongodb_version,
            "topology": config.environment.topology,
            "member_count": config.environment.member_count,
            "resource_limits": dict(config.environment.resource_limits),
        },
        "workload": {
            "name": config.workload.name,
            "parameters": dict(config.workload.parameters),
        },
        "limitations": [
            {"label": limitation.label, "description": limitation.description}
            for limitation in config.limitations
        ],
        "measurement": {
            "wall_seconds": measurement.wall_seconds,
            "process_cpu_seconds": measurement.process_cpu_seconds,
            "container_cpu_seconds": measurement.container_cpu_seconds,
            "direct_path_bytes": (
                {
                    "sent": measurement.direct_path_bytes_sent,
                    "received": measurement.direct_path_bytes_received,
                    "scope": "dedicated direct benchmark path only",
                }
                if measurement.direct_path_bytes_sent is not None
                else None
            ),
            "warmup": {
                "admissions": outcome.warmup_delta.admissions,
                "hits": outcome.warmup_delta.hits,
            },
            "variants": [
                {
                    "name": "raw",
                    **latency_distribution(
                        outcome.reads.raw_latencies + outcome.write_latencies
                    ),
                },
                {
                    "name": "cache",
                    **latency_distribution(
                        outcome.reads.cache_latencies + outcome.write_latencies
                    ),
                },
            ],
            "logical_metrics": dict(logical_metrics),
        },
    }
    if change_stream_cost is not None:
        measurement_section = report["measurement"]
        assert isinstance(measurement_section, dict)
        measurement_section["change_stream_cost_comparison"] = (
            _change_stream_cost_comparison_payload(change_stream_cost)
        )
    return report


def validate_report(report: Mapping[str, object]) -> None:
    errors: list[str] = []
    try:
        json.dumps(report, allow_nan=False)
    except (TypeError, ValueError) as exc:
        errors.append(f"report is not JSON-serializable: {exc}")
    validator = jsonschema.Draft202012Validator(_SCHEMA)
    errors.extend(error.message for error in validator.iter_errors(report))
    if not errors:
        workload = report["workload"]
        measurement = report["measurement"]
        assert isinstance(workload, dict)
        assert isinstance(measurement, dict)
        parameters = workload["parameters"]
        assert isinstance(parameters, dict)
        expected_count = parameters["sample_reads"] + parameters["sample_writes"]
        for variant in measurement["variants"]:
            observed_count = variant["operation_count"]
            if observed_count != expected_count:
                errors.append(
                    f"{variant['name']} has {observed_count} latency samples; "
                    f"workload declares {expected_count} sampled operations"
                )
            distribution_count = sum(
                item["sample_count"] for item in variant["by_outcome"]
            )
            if distribution_count != observed_count:
                errors.append(
                    f"{variant['name']} outcome distributions contain "
                    f"{distribution_count} samples, expected {observed_count}"
                )
            operation_counts = {
                operation: sum(
                    item["sample_count"]
                    for item in variant["by_outcome"]
                    if item["operation"] == operation
                )
                for operation in ("read", "write")
            }
            for operation, parameter in (
                ("read", "sample_reads"),
                ("write", "sample_writes"),
            ):
                if operation_counts[operation] != parameters[parameter]:
                    errors.append(
                        f"{variant['name']} has {operation_counts[operation]} "
                        f"{operation} samples; workload declares "
                        f"{parameters[parameter]}"
                    )
    if errors:
        raise ReportValidationError(errors)
