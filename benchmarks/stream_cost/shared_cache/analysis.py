from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from benchmarks.stream_cost.bootstrap import ConfidenceInterval
from benchmarks.stream_cost.shared_cache.protocol import Registration

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from client_query_cache._types import NonNegativeInt, PositiveInt

type Payload = dict[str, object]
type Estimand = Literal["ratio", "delta", "absolute"]
type CellKey = tuple[str, str, str, int]

_CONFIG = Path("reports/shared-worker-cache/v3/config.json")


@dataclass(frozen=True, slots=True)
class Criterion:
    name: str
    workloads: tuple[str, ...]
    metric: str
    baseline: str
    estimand: Estimand
    threshold_key: str


CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        "group-memory", ("hot",), "steady_pss", "independent", "ratio", "pss_ratio"
    ),
    Criterion(
        "peak-memory", ("hot",), "peak_pss", "independent", "ratio", "peak_pss_ratio"
    ),
    Criterion(
        "resident-total",
        ("hot",),
        "resident_total",
        "independent",
        "ratio",
        "resident_total_ratio",
    ),
    Criterion("hit-p95", ("hot",), "hit_p95", "direct", "ratio", "hit_p95_ratio"),
    Criterion("hit-p99", ("hot",), "hit_p99", "direct", "ratio", "hit_p99_ratio"),
    Criterion(
        "request-p99",
        ("hot", "active"),
        "request_p99",
        "independent",
        "ratio",
        "request_p99_ratio",
    ),
    Criterion(
        "request-p99-delta",
        ("hot", "active"),
        "request_p99",
        "independent",
        "delta",
        "request_p99_delta_seconds",
    ),
    Criterion(
        "cpu", ("hot", "active"), "cpu_per_request", "independent", "ratio", "cpu_ratio"
    ),
    Criterion(
        "wire", ("hot", "active"), "wire_bytes", "independent", "ratio", "wire_ratio"
    ),
    Criterion(
        "miss-p95", ("cold",), "miss_p95", "direct", "delta", "miss_delta_seconds"
    ),
    Criterion(
        "miss-p99", ("cold",), "miss_p99", "direct", "delta", "miss_delta_seconds"
    ),
    Criterion(
        "lag-p95", ("active",), "lag_p95", "independent", "absolute", "lag_p95_seconds"
    ),
    Criterion(
        "lag-p95-delta",
        ("active",),
        "lag_p95",
        "independent",
        "delta",
        "lag_p95_delta_seconds",
    ),
)


def _number(record: Payload, *keys: str) -> float:
    value: object = record
    for key in keys:
        value = cast("Payload", value)[key]
    return cast("float", value)


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def _outcome_total(record: Payload, outcome: str) -> int:
    return sum(
        cast("int", cast("Payload", worker["outcomes"])[outcome])
        for worker in cast("list[Payload]", record["workers_measured"])
    )


def _lag_values(record: Payload) -> list[float]:
    if record["path"] == "shared":
        windows = cast(
            "list[list[float]]", cast("Payload", record["owner"])["lag_windows"]
        )
    else:
        windows = [
            window
            for worker in cast("list[Payload]", record["workers_measured"])
            for window in cast(
                "list[list[float]]", cast("Payload", worker["lag"])["lag_windows"]
            )
        ]
    offset = _number(record, "clock_offset_seconds")
    return [lag + offset for window in windows for lag in window]


def block_statistics(record: Payload) -> dict[str, float]:
    workers = cast("list[Payload]", record["workers_measured"])
    try:
        owner: Payload | None = cast("Payload", record["owner"])
    except KeyError:
        owner = None
    completed = _number(record, "completed")
    cpu = (
        sum(
            _number(worker, "cpu_seconds") + _number(worker, "drain_cpu_seconds")
            for worker in workers
        )
        + _number(record, "server_cpu_seconds")
        + _number(record, "server_drain_cpu_seconds")
    )
    wire = sum(
        _number(worker, "wire_sent") + _number(worker, "wire_received")
        for worker in workers
    )
    if owner is not None:
        cpu += _number(owner, "cpu_seconds") + _number(owner, "drain_cpu_seconds")
        wire += _number(owner, "wire_sent") + _number(owner, "wire_received")
    statistics = {
        "steady_pss": _number(record, "memory", "steady_group_pss_bytes"),
        "peak_pss": _number(record, "memory", "peak_group_pss_bytes"),
        "resident_total": _number(record, "memory", "steady_group_pss_bytes")
        + _number(record, "server_memory_bytes"),
        "cpu_per_request": cpu / completed,
        "wire_bytes": wire,
        "completion": completed / _number(record, "offered"),
        "failures": sum(
            _number(worker, "loop", "errors") + _number(worker, "loop", "overflow")
            for worker in workers
        ),
    }
    populations = ("sync", "async") if record["model"] == "mixed" else ("request",)
    for population in populations:
        suffix = "" if population == "request" else f"_{population}"
        statistics[f"request_p99{suffix}"] = _number(
            record, "populations", population, "p99_seconds"
        )
    cached = record["path"] != "direct"
    if record["workload"] == "hot" and (
        not cached or _outcome_total(record, "hits") == completed
    ):
        statistics["hit_p95"] = _number(record, "populations", "request", "p95_seconds")
        statistics["hit_p99"] = _number(record, "populations", "request", "p99_seconds")
    if record["workload"] == "cold" and (
        not cached or _outcome_total(record, "misses") == completed
    ):
        statistics["miss_p95"] = _number(
            record, "populations", "request", "p95_seconds"
        )
        statistics["miss_p99"] = _number(
            record, "populations", "request", "p99_seconds"
        )
    if record["workload"] == "active" and cached:
        statistics["lag_p95"] = _percentile(_lag_values(record), 0.95)
        statistics["lag_uncertainty"] = _number(record, "clock_uncertainty_seconds")
    return statistics


def cell_key(record: Payload) -> CellKey:
    return (
        str(record["workload"]),
        str(record["profile"]),
        str(record["model"]),
        cast("int", record["workers"]),
    )


def paired_blocks(
    records: Iterable[Payload],
) -> dict[CellKey, dict[str, dict[int, dict[str, float] | None]]]:
    cells: dict[CellKey, dict[str, dict[int, dict[str, float] | None]]] = {}
    for record in records:
        paths = cells.setdefault(cell_key(record), {})
        blocks = paths.setdefault(str(record["path"]), {})
        blocks[cast("int", record["block"])] = (
            block_statistics(record) if record["healthy"] else None
        )
    return cells


def estimate(
    estimand: Estimand, candidate: Sequence[float], baseline: Sequence[float]
) -> float:
    if estimand == "ratio":
        return (sum(candidate) / len(candidate)) / (sum(baseline) / len(baseline))
    if estimand == "absolute":
        return sum(candidate) / len(candidate)
    return sum(c - b for c, b in zip(candidate, baseline, strict=True)) / len(candidate)


def bootstrap(
    estimand: Estimand,
    candidate: Sequence[float],
    baseline: Sequence[float],
    *,
    draws: PositiveInt,
    seed: int,
    confidence: float,
) -> ConfidenceInterval:
    generator = random.Random(seed)
    count = len(candidate)
    resampled = []
    for _ in range(draws):
        indices = [generator.randrange(count) for _ in range(count)]
        resampled.append(
            estimate(
                estimand,
                [candidate[index] for index in indices],
                [baseline[index] for index in indices],
            )
        )
    resampled.sort()
    tail = (1 - confidence) / 2
    return ConfidenceInterval(
        lower=resampled[int(tail * (draws - 1))],
        upper=resampled[int((1 - tail) * (draws - 1))],
        point_estimate=estimate(estimand, candidate, baseline),
    )


@dataclass(frozen=True, slots=True)
class Comparison:
    criterion: str
    cell: CellKey
    metric: str
    blocks: NonNegativeInt
    point: float | None
    upper: float | None
    threshold: float
    outcome: Literal["pass", "fail", "missing", "unstable"]


def _pairs(
    cell: dict[str, dict[int, dict[str, float] | None]],
    metric: str,
    baseline: str,
    blocks: NonNegativeInt,
) -> tuple[list[float], list[float]] | None:
    try:
        shared, reference = cell["shared"], cell[baseline]
    except KeyError:
        return None
    candidate: list[float] = []
    control: list[float] = []
    for block in range(blocks):
        try:
            left, right = shared[block], reference[block]
        except KeyError:
            return None
        if left is None or right is None:
            return None
        try:
            candidate.append(left[metric])
            control.append(right[metric])
        except KeyError:
            return None
    return candidate, control


@dataclass(frozen=True, slots=True)
class InferenceSettings:
    blocks: NonNegativeInt
    inference: bool
    confidence: float
    draws: PositiveInt
    seeds: tuple[int, ...]
    leave_one_out_draws: PositiveInt
    gate: Payload

    @classmethod
    def load(
        cls, registration: Registration, blocks: NonNegativeInt, *, inference: bool
    ) -> InferenceSettings:
        settings = registration.section("inference")
        return cls(
            blocks=blocks,
            inference=inference,
            confidence=cast("float", settings["confidence"]),
            draws=cast("int", settings["draws"]),
            seeds=tuple(cast("list[int]", settings["seeds"])),
            leave_one_out_draws=cast("int", settings["leave_one_out_draws"]),
            gate=registration.section("gate"),
        )


def compare(
    cells: dict[CellKey, dict[str, dict[int, dict[str, float] | None]]],
    settings: InferenceSettings,
) -> list[Comparison]:
    comparisons: list[Comparison] = []
    for key, cell in sorted(cells.items()):
        for criterion in CRITERIA:
            if key[0] not in criterion.workloads:
                continue
            metrics = (
                [f"{criterion.metric}_sync", f"{criterion.metric}_async"]
                if key[2] == "mixed" and criterion.metric == "request_p99"
                else [criterion.metric]
            )
            comparisons.extend(
                _compare(criterion, key, cell, metric, settings) for metric in metrics
            )
    return comparisons


def _compare(
    criterion: Criterion,
    key: CellKey,
    cell: dict[str, dict[int, dict[str, float] | None]],
    metric: str,
    settings: InferenceSettings,
) -> Comparison:
    threshold = cast("float", settings.gate[criterion.threshold_key])
    pairs = _pairs(cell, metric, criterion.baseline, settings.blocks)
    if pairs is None:
        return Comparison(
            criterion.name,
            key,
            metric,
            settings.blocks,
            None,
            None,
            threshold,
            "missing",
        )
    candidate, control = pairs
    point = estimate(criterion.estimand, candidate, control)
    if not settings.inference:
        return Comparison(
            criterion.name,
            key,
            metric,
            settings.blocks,
            point,
            None,
            threshold,
            "pass" if point <= threshold else "fail",
        )
    uppers = [
        bootstrap(
            criterion.estimand,
            candidate,
            control,
            draws=settings.draws,
            seed=seed,
            confidence=settings.confidence,
        ).upper
        for seed in settings.seeds
    ]
    for left_out in range(len(candidate)):
        kept = [index for index in range(len(candidate)) if index != left_out]
        uppers.append(
            bootstrap(
                criterion.estimand,
                [candidate[index] for index in kept],
                [control[index] for index in kept],
                draws=settings.leave_one_out_draws,
                seed=settings.seeds[0],
                confidence=settings.confidence,
            ).upper
        )
    if criterion.metric == "lag_p95":
        expansion = max(
            statistics["lag_uncertainty"]
            for path in ("shared", criterion.baseline)
            for statistics in cell[path].values()
            if statistics is not None
        )
        uppers = [upper + expansion for upper in uppers]
    verdicts = {upper <= threshold for upper in uppers}
    outcome: Literal["pass", "fail", "unstable"] = (
        "unstable" if len(verdicts) > 1 else "pass" if verdicts == {True} else "fail"
    )
    return Comparison(
        criterion.name,
        key,
        metric,
        settings.blocks,
        point,
        uppers[0],
        threshold,
        outcome,
    )


def completion_failures(
    records: Iterable[Payload], registration: Registration
) -> list[Payload]:
    minimum = cast("float", registration.section("gate")["completion"])
    failures: list[Payload] = []
    for record in records:
        if not record["healthy"]:
            failures.append(
                {
                    "cell": cell_key(record),
                    "path": record["path"],
                    "reason": record["failure"],
                }
            )
            continue
        statistics = block_statistics(record)
        if statistics["completion"] < minimum or statistics["failures"]:
            failures.append(
                {
                    "cell": cell_key(record),
                    "path": record["path"],
                    "block": record["block"],
                    "reason": "fixed work did not complete",
                }
            )
    return failures


def decide(
    records: list[Payload],
    registration: Registration,
    *,
    phase: str,
    blocks: NonNegativeInt,
) -> Payload:
    inference = phase != "screening"
    required = [
        record for record in records if cast("int", record["workers"]) in {4, 8}
    ]
    comparisons = compare(
        paired_blocks(required),
        InferenceSettings.load(registration, blocks, inference=inference),
    )
    failures = completion_failures(records, registration)
    failed = [comparison for comparison in comparisons if comparison.outcome != "pass"]
    if inference:
        verdict = "promote" if not failed and not failures else "defer"
    else:
        verdict = "stop" if failed or failures else "continue"
    return {
        "phase": phase,
        "verdict": verdict,
        "completion_failures": failures,
        "comparisons": [asdict(comparison) for comparison in comparisons],
        "failed": [asdict(comparison) for comparison in failed],
    }


def descriptive(records: Iterable[Payload]) -> list[Payload]:
    rows: list[Payload] = []
    for key, paths in sorted(paired_blocks(records).items()):
        for path, blocks in sorted(paths.items()):
            healthy = [
                statistics for statistics in blocks.values() if statistics is not None
            ]
            if not healthy:
                rows.append({"cell": key, "path": path, "blocks": 0})
                continue
            metrics = sorted(
                {metric for statistics in healthy for metric in statistics}
            )
            rows.append(
                {
                    "cell": key,
                    "path": path,
                    "blocks": len(healthy),
                    **{
                        metric: _summary(
                            [
                                statistics[metric]
                                for statistics in healthy
                                if metric in statistics
                            ]
                        )
                        for metric in metrics
                    },
                }
            )
    return rows


def _summary(values: list[float]) -> Payload:
    return {"mean": sum(values) / len(values), "min": min(values), "max": max(values)}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate shared worker cache evidence."
    )
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--config", type=Path, default=_CONFIG)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--blocks", type=int, required=True)
    parser.add_argument("--describe", action="store_true")
    arguments = parser.parse_args(argv)
    registration = Registration.load(arguments.config)
    records = [
        record
        for path in arguments.reports
        for record in cast(
            "list[Payload]", json.loads(path.read_text(encoding="utf-8"))["cells"]
        )
    ]
    output: Payload = (
        {"descriptive": descriptive(records)}
        if arguments.describe
        else decide(
            records, registration, phase=arguments.phase, blocks=arguments.blocks
        )
    )
    print(json.dumps(output, indent=1, default=list))


if __name__ == "__main__":
    main()
