from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jsonschema

from benchmarks.stream_cost.errors import ReportValidationError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from benchmarks.stream_cost.config import BenchmarkConfig

SCHEMA_VERSION = "1"

_SCHEMA_PATH = Path(__file__).with_name("schemas") / "report.v1.schema.json"
_SCHEMA: Mapping[str, Any] = json.loads(_SCHEMA_PATH.read_text())


def build_report(config: BenchmarkConfig) -> dict[str, object]:
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
    }
    return report


def validate_report(report: Mapping[str, object]) -> None:
    errors: list[str] = []
    try:
        json.dumps(report, allow_nan=False)
    except (TypeError, ValueError) as exc:
        errors.append(f"report is not JSON-serializable: {exc}")
    validator = jsonschema.Draft202012Validator(_SCHEMA)
    errors.extend(error.message for error in validator.iter_errors(report))
    if errors:
        raise ReportValidationError(errors)
