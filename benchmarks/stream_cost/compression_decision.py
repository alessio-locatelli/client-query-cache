from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from benchmarks.stream_cost.client import WireCompressor
from client_query_cache._types import JsonDict, NonNegativeFloat, NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

CPU_BUDGET_FRACTION = 0.05
LATENCY_TOLERANCE_FRACTION = 0.10
BYTE_SAVINGS_FRACTION = 0.10
NEAR_TIE_BYTES_FRACTION = 0.05

_STREAM_WATCHING = "stream_watching"
_IDLE_KIND = "idle"


@dataclass(frozen=True, slots=True)
class CompressionModeEvidence:
    mode: WireCompressor
    qualifies: bool
    idle_noisy: bool
    failures: tuple[str, ...]
    median_stream_total_bytes: NonNegativeFloat | None
    median_added_cpu_seconds: float | None


@dataclass(frozen=True, slots=True)
class CompressionDecision:
    recommended_mode: WireCompressor
    inconclusive: bool
    rationale: str
    evidence: tuple[CompressionModeEvidence, ...]


def _samples_index(
    report: Mapping[str, Any],
) -> dict[tuple[NonNegativeInt, str, str, str], JsonDict]:
    return {
        (
            sample["block_index"],
            sample["mode"],
            sample["window"],
            sample["path"],
        ): sample
        for sample in report["samples"]
    }


def _stream_minus_control_index(
    report: Mapping[str, Any],
) -> dict[tuple[NonNegativeInt, str, str], JsonDict]:
    return {
        (entry["block_index"], entry["mode"], entry["window"]): entry
        for entry in report["stream_minus_control"]
    }


def _active_window_names(report: Mapping[str, Any]) -> list[str]:
    return [
        window["name"] for window in report["windows"] if window["kind"] != _IDLE_KIND
    ]


def _idle_window_name(report: Mapping[str, Any]) -> str:
    (name,) = (
        window["name"] for window in report["windows"] if window["kind"] == _IDLE_KIND
    )
    return str(name)


def _observed_modes(report: Mapping[str, Any]) -> list[str]:
    modes = {sample["mode"] for sample in report["samples"]}
    modes.discard(WireCompressor.NONE.value)
    return sorted(modes)


def _total_bytes(sample: Mapping[str, Any]) -> NonNegativeFloat:
    direct = sample["direct_path_bytes"]
    return float(direct["sent"] + direct["received"])


def _check_cpu_budget(
    *, none_sample: Mapping[str, Any], mode_sample: Mapping[str, Any], label: str
) -> str | None:
    none_cpu = none_sample["container_cpu_seconds"]
    budget = CPU_BUDGET_FRACTION * none_cpu
    delta = mode_sample["container_cpu_seconds"] - none_cpu
    if delta > budget:
        return (
            f"{label}: stream-path CPU delta {delta:.6f}s exceeds the {budget:.6f}s "
            "budget"
        )
    return None


def _check_added_cpu_budget(
    *,
    none_sample: Mapping[str, Any],
    none_delta: Mapping[str, Any],
    mode_delta: Mapping[str, Any],
    label: str,
) -> str | None:
    budget = CPU_BUDGET_FRACTION * none_sample["container_cpu_seconds"]
    added_delta = (
        mode_delta["container_cpu_seconds_delta"]
        - none_delta["container_cpu_seconds_delta"]
    )
    if added_delta > budget:
        return (
            f"{label}: stream-minus-control CPU delta {added_delta:.6f}s exceeds "
            f"the {budget:.6f}s budget"
        )
    return None


def _check_invalidation_latency(
    *, none_sample: Mapping[str, Any], mode_sample: Mapping[str, Any], label: str
) -> str | None:
    none_p95 = none_sample["invalidation_latency"]["p95_seconds"]
    mode_p95 = mode_sample["invalidation_latency"]["p95_seconds"]
    budget = LATENCY_TOLERANCE_FRACTION * none_p95 if none_p95 > 0 else 0.0
    if (mode_p95 - none_p95) > budget:
        return (
            f"{label}: p95 invalidation latency {mode_p95:.6f}s exceeds "
            f"{none_p95 + budget:.6f}s"
        )
    return None


def _check_byte_savings(
    *, none_sample: Mapping[str, Any], mode_sample: Mapping[str, Any], label: str
) -> str | None:
    none_bytes = _total_bytes(none_sample)
    mode_bytes = _total_bytes(mode_sample)
    required_ceiling = (1 - BYTE_SAVINGS_FRACTION) * none_bytes
    if mode_bytes > required_ceiling:
        return (
            f"{label}: stream-path bytes {mode_bytes:.0f} do not fall at least "
            f"{BYTE_SAVINGS_FRACTION:.0%} below {none_bytes:.0f}"
        )
    return None


def _idle_is_noisy(idle_deltas: Sequence[float]) -> bool:
    return any(delta > 0 for delta in idle_deltas) and any(
        delta < 0 for delta in idle_deltas
    )


def _evaluate_mode(
    mode: WireCompressor,
    *,
    block_indices: Sequence[NonNegativeInt],
    active_windows: Sequence[str],
    idle_window: str,
    samples: Mapping[tuple[NonNegativeInt, str, str, str], Mapping[str, Any]],
    stream_minus_control: Mapping[tuple[NonNegativeInt, str, str], Mapping[str, Any]],
) -> CompressionModeEvidence:
    mode_value = mode.value
    none_value = WireCompressor.NONE.value
    failures: list[str] = []
    stream_bytes_points: list[NonNegativeFloat] = []
    added_cpu_points: list[float] = []

    for block_index in block_indices:
        for window in active_windows:
            label = f"mode {mode_value!r}, window {window!r}, block {block_index}"
            none_sample = samples[block_index, none_value, window, _STREAM_WATCHING]
            mode_sample = samples[block_index, mode_value, window, _STREAM_WATCHING]
            none_delta = stream_minus_control[block_index, none_value, window]
            mode_delta = stream_minus_control[block_index, mode_value, window]

            window_failures = (
                _check_cpu_budget(
                    none_sample=none_sample, mode_sample=mode_sample, label=label
                ),
                _check_added_cpu_budget(
                    none_sample=none_sample,
                    none_delta=none_delta,
                    mode_delta=mode_delta,
                    label=label,
                ),
                _check_invalidation_latency(
                    none_sample=none_sample, mode_sample=mode_sample, label=label
                ),
                _check_byte_savings(
                    none_sample=none_sample, mode_sample=mode_sample, label=label
                ),
            )
            failures.extend(
                failure for failure in window_failures if failure is not None
            )

            stream_bytes_points.append(_total_bytes(mode_sample))
            added_cpu_points.append(mode_delta["container_cpu_seconds_delta"])

    idle_deltas = [
        samples[block_index, mode_value, idle_window, _STREAM_WATCHING][
            "container_cpu_seconds"
        ]
        - samples[block_index, none_value, idle_window, _STREAM_WATCHING][
            "container_cpu_seconds"
        ]
        for block_index in block_indices
    ]
    idle_noisy = _idle_is_noisy(idle_deltas)
    if idle_noisy:
        failures.append(
            f"mode {mode_value!r}: idle-window CPU delta changes sign across blocks "
            "and cannot reliably distinguish it from no compression"
        )

    return CompressionModeEvidence(
        mode=mode,
        qualifies=not failures,
        idle_noisy=idle_noisy,
        failures=tuple(failures),
        median_stream_total_bytes=(
            statistics.median(stream_bytes_points) if stream_bytes_points else None
        ),
        median_added_cpu_seconds=(
            statistics.median(added_cpu_points) if added_cpu_points else None
        ),
    )


def _inconclusive_decision(
    evidence: tuple[CompressionModeEvidence, ...], rationale: str
) -> CompressionDecision:
    return CompressionDecision(
        recommended_mode=WireCompressor.NONE,
        inconclusive=True,
        rationale=rationale,
        evidence=evidence,
    )


def _select_among_qualifying(
    qualifying: Sequence[CompressionModeEvidence],
    evidence: tuple[CompressionModeEvidence, ...],
) -> CompressionDecision:
    ranked = sorted(qualifying, key=lambda item: item.median_stream_total_bytes or 0.0)
    best_bytes = ranked[0].median_stream_total_bytes
    assert best_bytes is not None
    near_ties = [
        item
        for item in ranked
        if item.median_stream_total_bytes is not None
        and item.median_stream_total_bytes <= best_bytes * (1 + NEAR_TIE_BYTES_FRACTION)
    ]
    near_ties.sort(key=lambda item: item.median_added_cpu_seconds or 0.0)
    min_cpu = near_ties[0].median_added_cpu_seconds
    cpu_ties = [item for item in near_ties if item.median_added_cpu_seconds == min_cpu]
    if len(cpu_ties) > 1:  # pragma: no cover - real CPU deltas never tie exactly
        return _inconclusive_decision(
            evidence,
            "multiple compressors tied on both stream-path bytes and added server "
            "CPU; no single mode can be recommended over no compression",
        )
    best = cpu_ties[0]
    return CompressionDecision(
        recommended_mode=best.mode,
        inconclusive=False,
        rationale=(
            f"{best.mode.value!r} met the pre-registered CPU, latency, and "
            "byte-savings thresholds in every paired block and active workload, its "
            "idle-window CPU "
            "delta did not change sign across blocks, and it had the lowest median "
            "stream-path bytes among qualifying compressors"
        ),
        evidence=evidence,
    )


def evaluate_compression_decision(report: Mapping[str, Any]) -> CompressionDecision:
    samples = _samples_index(report)
    stream_minus_control = _stream_minus_control_index(report)
    active_windows = _active_window_names(report)
    idle_window = _idle_window_name(report)
    block_indices = sorted({block["block_index"] for block in report["blocks"]})

    evidence = tuple(
        _evaluate_mode(
            WireCompressor(mode_value),
            block_indices=block_indices,
            active_windows=active_windows,
            idle_window=idle_window,
            samples=samples,
            stream_minus_control=stream_minus_control,
        )
        for mode_value in _observed_modes(report)
    )

    qualifying = [item for item in evidence if item.qualifies]
    if not qualifying:
        return _inconclusive_decision(
            evidence,
            "no compressor met the pre-registered CPU, latency, and byte-savings "
            "thresholds in every paired block and active workload, or its idle CPU "
            "comparison could not reliably distinguish it from no compression",
        )
    return _select_among_qualifying(qualifying, evidence)
