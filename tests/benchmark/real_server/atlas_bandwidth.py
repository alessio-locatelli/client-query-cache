from __future__ import annotations

import itertools
import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import dns.exception
import dns.resolver

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
_ATLAS_COLLECTION_BUDGET_SECONDS = 8.0


@dataclass(frozen=True, slots=True)
class BandwidthEvidence:
    host_id: str
    measurements: Mapping[str, tuple[float, ...]]


def requested_metric_types() -> tuple[str, ...]:
    return _METRIC_TYPES


def resolve_atlas_project_id() -> str | None:
    return os.environ.get(ATLAS_PROJECT_ID_ENV_VAR) or None


def _run_atlas(arguments: Sequence[str], *, timeout: float) -> str:
    atlas_path = shutil.which("atlas")
    if atlas_path is None:
        message = "the atlas CLI is not installed or not on PATH"
        raise RuntimeError(message)
    completed = subprocess.run(  # noqa: S603 - fixed argument lists built from trusted values
        [atlas_path, *arguments, "--output", "json"],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return completed.stdout


def _resolve_srv_members(mongodb_uri: str) -> frozenset[tuple[str, int]]:
    parsed = urlparse(mongodb_uri)
    if parsed.scheme != "mongodb+srv":
        message = (
            "Atlas bandwidth evidence requires a mongodb+srv:// connection "
            "string to resolve the deployment's cluster members"
        )
        raise RuntimeError(message)
    hostname = parsed.hostname
    if not hostname:
        message = (
            "could not determine a hostname from the real deployment's "
            "connection string to resolve its cluster members"
        )
        raise RuntimeError(message)
    answer = dns.resolver.resolve(f"_mongodb._tcp.{hostname}", "SRV")
    return frozenset(
        (str(record.target).rstrip(".").lower(), record.port) for record in answer
    )


def _process_matches_srv_members(
    process: Mapping[str, Any], members: frozenset[tuple[str, int]]
) -> bool:
    port = process.get("port")
    if not port:
        return False
    candidate_hostnames = (process.get("userAlias"), process.get("hostname"))
    return any(
        (str(hostname).lower(), int(port)) in members
        for hostname in candidate_hostnames
        if hostname
    )


def _primary_process_host_id(
    project_id: str, members: frozenset[tuple[str, int]], *, timeout: float
) -> str:
    payload = json.loads(
        _run_atlas(["processes", "list", "--projectId", project_id], timeout=timeout)
    )
    for process in payload.get("results", ()):
        if process.get(
            "typeName"
        ) == _PRIMARY_PROCESS_TYPE_NAME and _process_matches_srv_members(
            process, members
        ):
            return str(process["id"])
    message = (
        f"no {_PRIMARY_PROCESS_TYPE_NAME} process matching the configured "
        "deployment's SRV-resolved members was found in the configured Atlas project"
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


def _fetch_process_and_metrics(
    project_id: str, mongodb_uri: str, deadline: float
) -> tuple[str, Mapping[str, Any]] | None:
    members = _resolve_srv_members(mongodb_uri)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        logger.warning(
            "Atlas bandwidth evidence unavailable: collection budget "
            "exhausted before listing processes"
        )
        return None
    host_id = _primary_process_host_id(
        project_id, members, timeout=min(_ATLAS_TIMEOUT_SECONDS, remaining)
    )
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        logger.warning(
            "Atlas bandwidth evidence unavailable: collection budget "
            "exhausted before fetching metrics"
        )
        return None
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
            ],
            timeout=min(_ATLAS_TIMEOUT_SECONDS, remaining),
        )
    )
    return host_id, payload


def collect_bandwidth_evidence(
    project_id: str, mongodb_uri: str
) -> BandwidthEvidence | None:
    deadline = time.monotonic() + _ATLAS_COLLECTION_BUDGET_SECONDS
    try:
        process_and_metrics = _fetch_process_and_metrics(
            project_id, mongodb_uri, deadline
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
    except (OSError, RuntimeError, ValueError, dns.exception.DNSException) as error:
        logger.warning("Atlas bandwidth evidence unavailable: %s", error)
        return None
    if process_and_metrics is None:
        return None
    host_id, payload = process_and_metrics
    measurements = _measurements_by_type(payload)
    if not measurements:
        logger.warning("Atlas returned no bandwidth data points for host %r", host_id)
        return None
    return BandwidthEvidence(host_id=host_id, measurements=measurements)
