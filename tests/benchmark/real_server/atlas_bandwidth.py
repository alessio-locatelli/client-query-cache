from __future__ import annotations

import itertools
import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

logger = logging.getLogger(__name__)

ATLAS_PROJECT_ID_ENV_VAR = "REAL_MONGODB_ATLAS_PROJECT_ID"

_METRIC_TYPES = (
    "NETWORK_BYTES_IN",
    "NETWORK_BYTES_OUT",
    "NETWORK_NUM_REQUESTS",
    "OPCOUNTER_QUERY",
)
_GRANULARITY = "PT1M"
_PERIOD = "PT5M"
_PRIMARY_PROCESS_TYPE_NAME = "REPLICA_PRIMARY"
_ATLAS_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class BandwidthEvidence:
    host_id: str
    measurements: Mapping[str, tuple[float, ...]]


def requested_metric_types() -> tuple[str, ...]:
    return _METRIC_TYPES


def resolve_atlas_project_id() -> str | None:
    return os.environ.get(ATLAS_PROJECT_ID_ENV_VAR) or None


def _run_atlas(arguments: Sequence[str]) -> str:
    atlas_path = shutil.which("atlas")
    if atlas_path is None:
        message = "the atlas CLI is not installed or not on PATH"
        raise RuntimeError(message)
    completed = subprocess.run(  # noqa: S603 - fixed argument lists built from trusted values
        [atlas_path, *arguments, "--output", "json"],
        capture_output=True,
        text=True,
        timeout=_ATLAS_TIMEOUT_SECONDS,
        check=True,
    )
    return completed.stdout


def _primary_process_host_id(project_id: str) -> str:
    payload = json.loads(_run_atlas(["processes", "list", "--projectId", project_id]))
    for process in payload.get("results", ()):
        if process.get("typeName") == _PRIMARY_PROCESS_TYPE_NAME:
            return str(process["id"])
    message = (
        f"no {_PRIMARY_PROCESS_TYPE_NAME} process was found "
        "for the configured Atlas project"
    )
    raise RuntimeError(message)


def _measurements_by_type(payload: Mapping[str, Any]) -> dict[str, tuple[float, ...]]:
    measurements: dict[str, tuple[float, ...]] = {}
    for measurement in payload.get("measurements", ()):
        values = tuple(
            point["value"]
            for point in measurement.get("dataPoints", ())
            if point.get("value") is not None
        )
        if values:
            measurements[measurement["name"]] = values
    return measurements


def collect_bandwidth_evidence(project_id: str) -> BandwidthEvidence | None:
    try:
        host_id = _primary_process_host_id(project_id)
        type_arguments = itertools.chain.from_iterable(
            ("--type", metric_type) for metric_type in _METRIC_TYPES
        )
        payload = json.loads(
            _run_atlas(
                [
                    "metrics",
                    "processes",
                    host_id,
                    "--projectId",
                    project_id,
                    "--granularity",
                    _GRANULARITY,
                    "--period",
                    _PERIOD,
                    *type_arguments,
                ]
            )
        )
    except subprocess.CalledProcessError as error:
        logger.warning(
            "Atlas bandwidth evidence unavailable: atlas CLI exited with status %s",
            error.returncode,
        )
        return None
    except subprocess.TimeoutExpired:
        logger.warning("Atlas bandwidth evidence unavailable: atlas CLI timed out")
        return None
    except (OSError, RuntimeError, ValueError) as error:
        logger.warning("Atlas bandwidth evidence unavailable: %s", error)
        return None
    measurements = _measurements_by_type(payload)
    if not measurements:
        logger.warning("Atlas returned no bandwidth data points for host %r", host_id)
        return None
    return BandwidthEvidence(host_id=host_id, measurements=measurements)
