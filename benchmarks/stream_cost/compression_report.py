from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jsonschema

from benchmarks.stream_cost.compression_matrix import WIRE_COMPRESSION_MODES, WirePath
from benchmarks.stream_cost.errors import ReportValidationError
from benchmarks.stream_cost.measurement import (
    latency_distribution,
    scalar_latency_distribution,
)
from benchmarks.stream_cost.workload import WorkloadKind
from client_query_cache._types import JsonDict, NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from benchmarks.stream_cost.client import WireCompressor
    from benchmarks.stream_cost.compression_matrix import CompressionWindowSpec
    from benchmarks.stream_cost.compression_matrix_runner import CompressionWindowResult
    from benchmarks.stream_cost.compressor_preflight import CompressorPreflightResult
    from benchmarks.stream_cost.config import (
        BenchmarkEnvironment,
        BenchmarkIdentity,
        Limitation,
    )
    from benchmarks.stream_cost.measurement import ControlledMeasurement

SCHEMA_VERSION = "1"

_SCHEMA_PATH = Path(__file__).with_name("schemas") / "compression_report.v1.schema.json"
_SCHEMA: Mapping[str, Any] = json.loads(_SCHEMA_PATH.read_text())
_DIRECT_PATH_BYTES_SCOPE = "dedicated direct benchmark path only"


@dataclass(frozen=True, slots=True)
class CompressionBlockPlan:
    block_index: NonNegativeInt
    mode_order: tuple[WireCompressor, ...]
    path_order: tuple[WirePath, WirePath]


def _window_payload(window: CompressionWindowSpec) -> JsonDict:
    is_idle = window.kind is WorkloadKind.IDLE
    return {
        "name": window.name,
        "kind": window.kind.value,
        "data_size": None if is_idle else window.data_size.name,
        "duration_seconds": window.duration_seconds,
        "sampling": {
            "reads": window.sampling.reads,
            "writes": window.sampling.writes,
        },
    }


def _sample_payload(window_result: CompressionWindowResult) -> JsonDict:
    window = window_result.window
    measurement = window_result.measurement
    is_idle = window.kind is WorkloadKind.IDLE
    direct_path_bytes = (
        {
            "sent": measurement.direct_path_bytes_sent,
            "received": measurement.direct_path_bytes_received,
            "scope": _DIRECT_PATH_BYTES_SCOPE,
        }
        if measurement.direct_path_bytes_sent is not None
        else None
    )
    return {
        "block_index": window_result.block_index,
        "mode": window_result.mode.value,
        "path": window_result.path.value,
        "window": window.name,
        "window_kind": window.kind.value,
        "data_size": None if is_idle else window.data_size.name,
        "wall_seconds": measurement.wall_seconds,
        "process_cpu_seconds": measurement.process_cpu_seconds,
        "container_cpu_seconds": measurement.container_cpu_seconds,
        "direct_path_bytes": direct_path_bytes,
        "expected_reads": window.sampling.reads,
        "expected_writes": window.sampling.writes,
        "reads_issued": window_result.reads_issued,
        "writes_issued": window_result.writes_issued,
        "read_latency": latency_distribution(window_result.read_latencies),
        "write_latency": latency_distribution(window_result.write_latencies),
        "invalidation_latency": scalar_latency_distribution(
            window_result.invalidation_latencies_seconds
        ),
    }


def _direct_path_bytes_delta(
    stream_measurement: ControlledMeasurement,
    control_measurement: ControlledMeasurement,
) -> dict[str, int] | None:
    if (
        stream_measurement.direct_path_bytes_sent is None
        or stream_measurement.direct_path_bytes_received is None
        or control_measurement.direct_path_bytes_sent is None
        or control_measurement.direct_path_bytes_received is None
    ):
        return None  # pragma: no cover - this benchmark always uses a direct-path proxy
    return {
        "sent": (
            stream_measurement.direct_path_bytes_sent
            - control_measurement.direct_path_bytes_sent
        ),
        "received": (
            stream_measurement.direct_path_bytes_received
            - control_measurement.direct_path_bytes_received
        ),
    }


def _stream_minus_control_payload(
    stream_result: CompressionWindowResult, control_result: CompressionWindowResult
) -> JsonDict:
    stream_measurement = stream_result.measurement
    control_measurement = control_result.measurement
    return {
        "block_index": stream_result.block_index,
        "mode": stream_result.mode.value,
        "window": stream_result.window.name,
        "container_cpu_seconds_delta": (
            stream_measurement.container_cpu_seconds
            - control_measurement.container_cpu_seconds
        ),
        "direct_path_bytes_delta": _direct_path_bytes_delta(
            stream_measurement, control_measurement
        ),
    }


def _negotiation_payload(
    block_index: NonNegativeInt,
    mode: WireCompressor,
    preflight_result: CompressorPreflightResult,
) -> JsonDict:
    return {
        "block_index": block_index,
        "mode": mode.value,
        "verified": True,
        "counter_deltas": dict(preflight_result.counter_deltas),
    }


def build_compression_report(
    *,
    identity: BenchmarkIdentity,
    environment: BenchmarkEnvironment,
    windows: Sequence[CompressionWindowSpec],
    blocks: Sequence[CompressionBlockPlan],
    negotiations: Mapping[
        tuple[NonNegativeInt, WireCompressor], CompressorPreflightResult
    ],
    window_results: Sequence[CompressionWindowResult],
    limitations: Sequence[Limitation],
) -> JsonDict:
    results_by_key = {
        (result.block_index, result.mode, result.window.name, result.path): result
        for result in window_results
    }
    stream_minus_control: list[JsonDict] = []
    for block in blocks:
        for mode in block.mode_order:
            for window in windows:
                stream_key = (
                    block.block_index,
                    mode,
                    window.name,
                    WirePath.STREAM_WATCHING,
                )
                control_key = (block.block_index, mode, window.name, WirePath.NO_STREAM)
                if (
                    stream_key in results_by_key and control_key in results_by_key
                ):  # pragma: no branch - every block runs both paths for every window
                    stream_minus_control.append(
                        _stream_minus_control_payload(
                            results_by_key[stream_key], results_by_key[control_key]
                        )
                    )

    return {
        "schema_version": SCHEMA_VERSION,
        "identity": {
            "revision": identity.revision,
            "library_version": identity.library_version,
            "python_version": identity.python_version,
            "pymongo_version": identity.pymongo_version,
        },
        "environment": {
            "mongodb_version": environment.mongodb_version,
            "topology": environment.topology,
            "member_count": environment.member_count,
            "resource_limits": dict(environment.resource_limits),
        },
        "compressors": [mode.value for mode in WIRE_COMPRESSION_MODES],
        "windows": [_window_payload(window) for window in windows],
        "block_count": len(blocks),
        "blocks": [
            {
                "block_index": block.block_index,
                "mode_order": [mode.value for mode in block.mode_order],
                "path_order": [path.value for path in block.path_order],
            }
            for block in blocks
        ],
        "negotiations": [
            _negotiation_payload(block_index, mode, result)
            for (block_index, mode), result in negotiations.items()
        ],
        "samples": [_sample_payload(result) for result in window_results],
        "stream_minus_control": stream_minus_control,
        "limitations": [
            {"label": limitation.label, "description": limitation.description}
            for limitation in limitations
        ],
    }


def _as_dicts(values: object) -> list[JsonDict]:
    assert isinstance(values, list)
    for value in values:
        assert isinstance(value, dict)
    return values


def _mode_order(block: JsonDict) -> list[object]:
    mode_order = block["mode_order"]
    assert isinstance(mode_order, list)
    return mode_order


def _validate_completeness(report: Mapping[str, object], errors: list[str]) -> None:
    blocks = _as_dicts(report["blocks"])
    windows = _as_dicts(report["windows"])
    window_names = [window["name"] for window in windows]

    sample_keys = Counter(
        (sample["block_index"], sample["mode"], sample["window"], sample["path"])
        for sample in _as_dicts(report["samples"])
    )
    for sample_key, count in sample_keys.items():
        if count > 1:
            errors.append(f"duplicate sample for {sample_key}")

    for block in blocks:
        for mode in _mode_order(block):
            for window_name in window_names:
                for path in ("no_stream", "stream_watching"):
                    sample_key = (block["block_index"], mode, window_name, path)
                    if sample_key not in sample_keys:
                        errors.append(f"missing sample for {sample_key}")

    negotiation_keys = {
        (negotiation["block_index"], negotiation["mode"])
        for negotiation in _as_dicts(report["negotiations"])
    }
    for block in blocks:
        for mode in _mode_order(block):
            negotiation_key = (block["block_index"], mode)
            if negotiation_key not in negotiation_keys:
                errors.append(f"missing verified negotiation for {negotiation_key}")

    stream_minus_control_keys = Counter(
        (entry["block_index"], entry["mode"], entry["window"])
        for entry in _as_dicts(report["stream_minus_control"])
    )
    for control_key, count in stream_minus_control_keys.items():
        if count > 1:
            errors.append(f"duplicate stream-minus-control entry for {control_key}")
    for block in blocks:
        for mode in _mode_order(block):
            for window_name in window_names:
                control_key = (block["block_index"], mode, window_name)
                if control_key not in stream_minus_control_keys:
                    errors.append(
                        f"missing stream-minus-control entry for {control_key}"
                    )


def _validate_samples(report: Mapping[str, object], errors: list[str]) -> None:
    windows_by_name = {
        window["name"]: window for window in _as_dicts(report["windows"])
    }
    for sample in _as_dicts(report["samples"]):
        try:
            window = windows_by_name[sample["window"]]
        except KeyError:
            errors.append(f"sample references undeclared window {sample['window']!r}")
            continue
        label = (
            sample["block_index"],
            sample["mode"],
            sample["window"],
            sample["path"],
        )
        if sample["reads_issued"] != sample["expected_reads"]:
            errors.append(
                f"{label} issued {sample['reads_issued']} reads, expected "
                f"{sample['expected_reads']}"
            )
        if sample["writes_issued"] != sample["expected_writes"]:
            errors.append(
                f"{label} issued {sample['writes_issued']} writes, expected "
                f"{sample['expected_writes']}"
            )

        is_idle = window["kind"] == WorkloadKind.IDLE.value
        for latency_field in ("read_latency", "write_latency"):
            distribution = sample[latency_field]
            assert isinstance(distribution, dict)
            if is_idle and not distribution["no_latency_samples"]:
                errors.append(
                    f"{label} {latency_field} must report no samples for idle"
                )

        invalidation = sample["invalidation_latency"]
        assert isinstance(invalidation, dict)
        expected_writes = sample["expected_writes"]
        assert isinstance(expected_writes, int)
        if sample["path"] == "stream_watching" and expected_writes > 0:
            if invalidation["sample_count"] != expected_writes:
                errors.append(
                    f"{label} invalidation_latency has "
                    f"{invalidation['sample_count']} samples, expected "
                    f"{expected_writes}"
                )
        elif not invalidation["no_latency_samples"]:
            errors.append(
                f"{label} invalidation_latency must report no samples for a "
                "no-stream path or a window without scheduled writes"
            )


def validate_compression_report(report: Mapping[str, object]) -> None:
    errors: list[str] = []
    serialization_error: Exception | None = None
    try:
        json.dumps(report, allow_nan=False)
    except TypeError as exc:
        serialization_error = exc
    except ValueError as exc:
        serialization_error = exc
    if serialization_error is not None:
        errors.append(f"report is not JSON-serializable: {serialization_error}")
    validator = jsonschema.Draft202012Validator(_SCHEMA)
    errors.extend(error.message for error in validator.iter_errors(report))
    if not errors:
        _validate_completeness(report, errors)
        _validate_samples(report, errors)
    if errors:
        raise ReportValidationError(errors)
