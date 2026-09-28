from __future__ import annotations

import hashlib
import json
import math
from dataclasses import fields
from pathlib import Path
from typing import TYPE_CHECKING, cast

from benchmarks.stream_cost.await_model import (
    AwaitConfiguration,
    AwaitWindow,
    planned_windows,
)
from benchmarks.stream_cost.errors import BenchmarkConfigurationError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

# Content hash of the reviewed pre-run configuration.
CONFIGURATION_SHA256 = (
    # pragma: allowlist nextline secret
    "d4797f8d8d10c71f4b41d83dfcc51486c1923e47b1f0704133fd6854861a9fc9"
)
CONFIGURATION_PATH = Path("reports/stream-cost/await-v1/config.v1.json")

_SCALARS = ("elapsed_seconds", "server_cpu_seconds", "client_cpu_seconds")
_COUNTS = (
    "block",
    "candidate_ms",
    "bytes_sent",
    "bytes_received",
    "getmore_started",
    "getmore_completed",
    "getmore_inflight_at_start",
    "command_failures",
    "manager_iteration_calls",
    "invalidations",
)
_ARRAYS = (
    "issue_offsets_seconds",
    "lag_seconds",
    "shutdown_seconds",
    "shutdown_start_offsets_seconds",
    "requested_max_time_ms",
)


def configuration_hash(content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()
    if digest != CONFIGURATION_SHA256:
        raise BenchmarkConfigurationError(
            "await-time configuration differs from the reviewed frozen configuration"
        )
    return digest


def _require(*, condition: bool, message: str) -> None:
    if not condition:
        raise BenchmarkConfigurationError(message)


def _finite_nonnegative(value: object) -> bool:
    return (
        type(value) in {int, float}
        and math.isfinite(cast("float", value))
        and cast("float", value) >= 0
    )


def _window(raw: object) -> AwaitWindow:
    _require(condition=isinstance(raw, dict), message="window must be an object")
    mapping = cast("dict[str, object]", raw).copy()
    _require(
        condition=set(mapping) == {field.name for field in fields(AwaitWindow)},
        message="window has missing or unknown measurements",
    )
    shutdown = mapping["workload"] == "shutdown"
    for tag, choices in (
        ("model", {"sync", "async"}),
        ("workload", {"idle", "paced", "burst", "shutdown"}),
    ):
        value = mapping[tag]
        _require(
            condition=isinstance(value, str) and value in choices,
            message=f"invalid {tag}",
        )
    for name in _SCALARS:
        if shutdown and name != "elapsed_seconds":
            _require(
                condition=mapping[name] is None,
                message="shutdown does not measure workload CPU",
            )
            continue
        _require(
            condition=_finite_nonnegative(mapping[name]),
            message=f"{name} must be finite and nonnegative",
        )
    for name in _COUNTS:
        if shutdown and name in {"bytes_sent", "bytes_received"}:
            _require(
                condition=mapping[name] is None,
                message="shutdown does not measure workload bytes",
            )
            continue
        _require(
            condition=type(mapping[name]) is int and cast("int", mapping[name]) >= 0,
            message=f"{name} must be a nonnegative integer",
        )
    for name in _ARRAYS:
        values = mapping[name]
        _require(
            condition=isinstance(values, (list, tuple)),
            message=f"{name} must contain measurements",
        )
        values = cast("list[object] | tuple[object, ...]", values)
        _require(
            condition=all(_finite_nonnegative(value) for value in values),
            message=f"{name} contains missing or invalid measurements",
        )
        if name == "requested_max_time_ms":
            _require(
                condition=all(type(value) is int and value > 0 for value in values),
                message="requested maxTimeMS must contain positive integers",
            )
        mapping[name] = tuple(values)
    inflight = mapping["shutdown_inflight"]
    _require(
        condition=isinstance(inflight, (list, tuple))
        and all(type(value) is bool for value in inflight),
        message="invalid shutdown in-flight observations",
    )
    mapping["shutdown_inflight"] = tuple(
        cast("list[bool] | tuple[bool, ...]", inflight)
    )
    _require(
        condition=type(mapping["healthy"]) is bool and mapping["failure"] is None,
        message="successful windows require explicit health and no failure",
    )
    return cast("Callable[..., AwaitWindow]", AwaitWindow)(**mapping)


def validate_await_report(
    report: Mapping[str, object], configuration: AwaitConfiguration, digest: str
) -> tuple[AwaitWindow, ...]:
    frozen_bytes = CONFIGURATION_PATH.read_bytes()
    _require(
        condition=configuration == json.loads(frozen_bytes)
        and configuration_hash(frozen_bytes) == digest,
        message="decision configuration differs from the frozen configuration",
    )
    _require(
        condition=set(report)
        == {
            "schema_version",
            "configuration_sha256",
            "revision",
            "environment",
            "topology",
            "command_count_source",
            "scope",
            "client_options",
            "samples",
            "failures",
        },
        message="report has missing or unknown fields",
    )
    _require(
        condition=report["client_options"] == configuration["client_options"],
        message="mismatched client timeout options",
    )
    _require(
        condition=report["command_count_source"] == "pymongo_command_listener",
        message="getMore counts require command-level observation",
    )
    _require(
        condition=report["scope"] == "tested_single_member_replica_set_only",
        message="unsupported topology scope",
    )
    _require(
        condition=digest == CONFIGURATION_SHA256
        and report["configuration_sha256"] == digest,
        message="configuration hash mismatch",
    )
    _require(
        condition=report["schema_version"] == 1, message="unsupported report schema"
    )
    _require(
        condition=report["topology"] == configuration["topology"],
        message="mismatched topology or unsupported topology scope",
    )
    _require(
        condition=isinstance(report["revision"], str) and bool(report["revision"]),
        message="repository revision is required",
    )
    environment = report["environment"]
    _require(
        condition=isinstance(environment, dict)
        and all(
            isinstance(environment.get(key), str) and bool(environment[key])
            for key in (
                "python",
                "pymongo",
                "client_query_cache",
                "mongodb",
                "platform",
            )
        ),
        message="runtime, driver, library, server, and platform versions are required",
    )
    raw_samples = report["samples"]
    _require(condition=isinstance(raw_samples, list), message="samples must be a list")
    samples = tuple(_window(raw) for raw in cast("list[object]", raw_samples))
    observed = {
        (sample.block, sample.candidate_ms, sample.model, sample.workload)
        for sample in samples
    }
    expected = set(planned_windows(configuration))
    _require(
        condition=len(observed) == len(samples), message="duplicate measurement windows"
    )
    raw_failures = report["failures"]
    _require(
        condition=isinstance(raw_failures, list), message="failures must be a list"
    )
    failure_keys = set()
    for raw_failure in cast("list[object]", raw_failures):
        _require(
            condition=isinstance(raw_failure, dict), message="failure must be an object"
        )
        failure = cast("dict[str, object]", raw_failure)
        _require(
            condition=set(failure)
            == {"block", "candidate_ms", "model", "workload", "error_type", "reason"},
            message="incomplete failure evidence",
        )
        _require(
            condition=type(failure["block"]) is int
            and type(failure["candidate_ms"]) is int
            and all(
                isinstance(failure[key], str) and bool(failure[key])
                for key in ("model", "workload", "error_type", "reason")
            ),
            message="invalid failure evidence",
        )
        key = (
            failure["block"],
            failure["candidate_ms"],
            failure["model"],
            failure["workload"],
        )
        _require(
            condition=key in expected
            and key not in failure_keys
            and key not in observed,
            message="unexpected or duplicate failed window",
        )
        failure_keys.add(key)
    _require(
        condition=observed | failure_keys == expected,
        message="missing or unexpected candidate measurement windows",
    )
    expected_order = planned_windows(configuration)
    _require(
        condition=[
            (sample.block, sample.candidate_ms, sample.model, sample.workload)
            for sample in samples
        ]
        == [key for key in expected_order if key not in failure_keys],
        message="run order differs from registered order",
    )
    for sample in samples:
        _require(
            condition=sample.healthy,
            message="candidate experienced a stream-health failure",
        )
        _require(
            condition=sample.elapsed_seconds > 0,
            message="window has no elapsed-time measurement",
        )
        _require(
            condition=bool(sample.requested_max_time_ms)
            and all(
                value == sample.candidate_ms for value in sample.requested_max_time_ms
            ),
            message="getMore requested maxTimeMS mismatch",
        )
        _require(
            condition=sample.getmore_started + sample.getmore_inflight_at_start
            == len(sample.requested_max_time_ms),
            message="actual getMore counts do not match observed commands",
        )
        _require(
            condition=0
            <= sample.getmore_completed
            <= sample.getmore_started + sample.getmore_inflight_at_start,
            message="completed getMore observations exceed observed commands",
        )
        _require(
            condition=sample.command_failures <= sample.getmore_completed,
            message="command failures exceed completed command observations",
        )
        if sample.workload == "shutdown":
            _require(
                condition=sample.getmore_inflight_at_start
                == len(sample.shutdown_seconds),
                message="shutdown in-flight command count differs from trial count",
            )
            _require(
                condition=len(sample.shutdown_seconds)
                == len(configuration["shutdown_trial_offsets_seconds"]),
                message="shutdown trials are missing",
            )
            _require(
                condition=len(sample.shutdown_inflight) == len(sample.shutdown_seconds)
                and all(sample.shutdown_inflight),
                message="shutdown was not observed in flight",
            )
            _require(
                condition=len(sample.shutdown_start_offsets_seconds)
                == len(sample.shutdown_seconds)
                and all(
                    0
                    <= actual - planned
                    <= configuration["shutdown_schedule_tolerance_seconds"]
                    for actual, planned in zip(
                        sample.shutdown_start_offsets_seconds,
                        configuration["shutdown_trial_offsets_seconds"],
                        strict=True,
                    )
                ),
                message="shutdown schedule differs from registered schedule",
            )
            continue
        _require(
            condition=sample.getmore_completed > 0,
            message="completed getMore observations are missing",
        )
        _require(
            condition=sample.getmore_inflight_at_start <= 1,
            message="window contains more than one active stream",
        )
        _require(
            condition=sample.command_failures == 0,
            message="unexpected getMore failure during workload sampling",
        )
        _require(
            condition=sample.bytes_sent is not None
            and sample.bytes_received is not None
            and sample.bytes_sent > 0
            and sample.bytes_received > 0,
            message="direct-path byte observations are missing",
        )
        _require(
            condition=not sample.shutdown_seconds
            and not sample.shutdown_start_offsets_seconds
            and not sample.shutdown_inflight,
            message="shutdown trials mixed into workload measurements",
        )
        if sample.workload == "idle":
            _require(
                condition=sample.getmore_inflight_at_start == 0,
                message="idle sampling did not start at a command boundary",
            )
            _require(
                condition=sample.elapsed_seconds
                >= configuration["idle_minimum_seconds"],
                message="idle window is too short",
            )
            _require(
                condition=sample.getmore_completed
                >= configuration["idle_minimum_completed_commands"],
                message="idle window lacks complete waits",
            )
            _require(
                condition=not sample.issue_offsets_seconds
                and not sample.lag_seconds
                and sample.invalidations == 0,
                message="idle window includes writes or latency samples",
            )
        else:
            schedule = configuration["write_offsets_seconds"][sample.workload]
            _require(
                condition=len(sample.issue_offsets_seconds)
                == len(schedule)
                == len(sample.lag_seconds)
                == sample.invalidations,
                message="unequal event schedule or event counts",
            )
            _require(
                condition=all(
                    0
                    <= actual - planned
                    <= configuration["write_schedule_tolerance_seconds"][
                        sample.workload
                    ]
                    for actual, planned in zip(
                        sample.issue_offsets_seconds, schedule, strict=True
                    )
                ),
                message="write schedule differs from registered schedule",
            )
            _require(
                condition=sample.elapsed_seconds
                >= configuration["active_window_seconds"],
                message="active window is too short",
            )
    return samples
