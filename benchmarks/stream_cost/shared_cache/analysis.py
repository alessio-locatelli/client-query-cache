from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from benchmarks.stream_cost.bootstrap import ConfidenceInterval
from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)
from benchmarks.stream_cost.shared_cache.protocol import (
    BASELINES,
    Registration,
    measurement_environment,
    phase_blocks,
    validation_failure,
)
from client_query_cache._types import JsonDict, NonNegativeInt, PositiveInt

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence


type Estimand = Literal["ratio", "delta", "absolute"]
type CellKey = tuple[str, str, str, int] | tuple[str, str, str, int, int]
type Statistics = Callable[[JsonDict], dict[str, float]]

_CONFIG = Path("reports/shared-worker-cache/v4/config.json")


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


def _number(record: JsonDict, *keys: str) -> float:
    value: object = record
    for key in keys:
        value = cast("JsonDict", value)[key]
    return cast("float", value)


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def _outcome_total(record: JsonDict, outcome: str) -> int:
    return sum(
        cast("int", cast("JsonDict", worker["outcomes"])[outcome])
        for worker in cast("list[JsonDict]", record["workers_measured"])
    )


def _lag_values(record: JsonDict) -> list[float]:
    if record["path"] not in BASELINES:
        windows = cast(
            "list[list[float]]", cast("JsonDict", record["owner"])["lag_windows"]
        )
    else:
        windows = [
            window
            for worker in cast("list[JsonDict]", record["workers_measured"])
            for window in cast(
                "list[list[float]]", cast("JsonDict", worker["lag"])["lag_windows"]
            )
        ]
    offset = _number(record, "clock_offset_seconds")
    return [lag + offset for window in windows for lag in window]


def block_statistics(record: JsonDict) -> dict[str, float]:
    statistics = _shared_statistics(record)
    if record["workload"] == "active" and record["path"] != "direct":
        statistics["lag_p95"] = _percentile(_lag_values(record), 0.95)
        statistics["lag_uncertainty"] = _number(record, "clock_uncertainty_seconds")
    return statistics


def _shared_statistics(record: JsonDict) -> dict[str, float]:
    workers = cast("list[JsonDict]", record["workers_measured"])
    try:
        owner: JsonDict | None = cast("JsonDict", record["owner"])
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
    return statistics


def window_statistics(record: JsonDict, lag_floor: NonNegativeInt) -> dict[str, float]:
    workers = cast("list[JsonDict]", record["workers_measured"])
    completed = _number(record, "completed")
    reasons: Counter[str] = Counter()
    for worker in workers:
        reasons.update(
            cast(
                "dict[str, int]",
                cast("JsonDict", worker["outcomes"])["bypass_reasons"],
            )
        )
    statistics = {
        **_shared_statistics(record),
        "throughput": _number(record, "completed_in_window")
        / _number(record, "window_seconds"),
        "request_p50": _number(record, "populations", "request", "p50_seconds"),
        "request_p95": _number(record, "populations", "request", "p95_seconds"),
        "request_p99": _number(record, "populations", "request", "p99_seconds"),
        "server_cpu_seconds": _number(record, "server_cpu_seconds")
        + _number(record, "server_drain_cpu_seconds"),
        "worker_cpu_per_request": sum(
            _number(worker, "cpu_seconds") + _number(worker, "drain_cpu_seconds")
            for worker in workers
        )
        / completed,
        "harness_cpu_seconds": _number(record, "harness_cpu_seconds"),
        "hits": _outcome_total(record, "hits"),
        "misses": _outcome_total(record, "misses"),
        "streams": sum(_number(worker, "streams") for worker in workers),
        "clock_offset_seconds": _number(record, "clock_offset_seconds"),
        "clock_uncertainty_seconds": _number(record, "clock_uncertainty_seconds"),
        **{f"bypass_{reason}": count for reason, count in sorted(reasons.items())},
    }
    if record["workload"] == "active" and record["path"] != "direct":
        lags = _lag_values(record)
        statistics["lag_events"] = len(lags)
        if len(lags) >= lag_floor:
            statistics["lag_p50"] = _percentile(lags, 0.5)
            statistics["lag_p95"] = _percentile(lags, 0.95)
    return statistics


def cell_key(record: JsonDict) -> CellKey:
    key = (
        str(record["workload"]),
        str(record["profile"]),
        str(record["model"]),
        cast("int", record["workers"]),
    )
    if record["phase"] == "capacity":
        return (*key, cast("int", record["concurrency"]))
    return key


def reject_duplicates(records: Iterable[JsonDict]) -> None:
    seen: set[tuple[CellKey, str, int]] = set()
    for record in records:
        window = (cell_key(record), str(record["path"]), cast("int", record["block"]))
        if window in seen:
            message = f"duplicate window {window}"
            raise BenchmarkSetupError(message)
        seen.add(window)


def paired_blocks(
    records: Iterable[JsonDict], statistics: Statistics = block_statistics
) -> dict[CellKey, dict[str, dict[int, dict[str, float] | None]]]:
    grouped = list(records)
    reject_duplicates(grouped)
    cells: dict[CellKey, dict[str, dict[int, dict[str, float] | None]]] = {}
    for record in grouped:
        paths = cells.setdefault(cell_key(record), {})
        blocks = paths.setdefault(str(record["path"]), {})
        blocks[cast("int", record["block"])] = (
            statistics(record) if record["healthy"] else None
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
    candidate: str
    cell: CellKey
    metric: str
    blocks: NonNegativeInt
    point: float | None
    upper: float | None
    threshold: float
    outcome: Literal["pass", "fail", "missing", "unstable"]


def _pairs(
    cell: dict[str, dict[int, dict[str, float] | None]],
    path: str,
    metric: str,
    baseline: str,
    blocks: NonNegativeInt,
) -> tuple[list[float], list[float]] | None:
    try:
        measured, reference = cell[path], cell[baseline]
    except KeyError:
        return None
    candidate: list[float] = []
    control: list[float] = []
    for block in range(blocks):
        try:
            left, right = measured[block], reference[block]
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
    candidates: tuple[str, ...]
    blocks: NonNegativeInt
    inference: bool
    confidence: float
    draws: PositiveInt
    seeds: tuple[int, ...]
    leave_one_out_draws: PositiveInt
    gate: JsonDict

    @classmethod
    def load(
        cls, registration: Registration, blocks: NonNegativeInt, *, inference: bool
    ) -> InferenceSettings:
        settings = registration.section("inference")
        candidates = registration.candidates
        return cls(
            candidates=candidates,
            blocks=blocks,
            inference=inference,
            confidence=cast(
                "float",
                settings[
                    "confidence" if len(candidates) == 1 else "two_candidate_confidence"
                ],
            ),
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
    for candidate in settings.candidates:
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
                    _compare(criterion, key, cell, metric, settings, path=candidate)
                    for metric in metrics
                )
    return comparisons


def _compare(
    criterion: Criterion,
    key: CellKey,
    cell: dict[str, dict[int, dict[str, float] | None]],
    metric: str,
    settings: InferenceSettings,
    *,
    path: str,
) -> Comparison:
    threshold = cast("float", settings.gate[criterion.threshold_key])
    pairs = _pairs(cell, path, metric, criterion.baseline, settings.blocks)
    if pairs is None:
        return Comparison(
            criterion.name,
            path,
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
            path,
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
            for measured in (path, criterion.baseline)
            for statistics in cell[measured].values()
            if statistics is not None
        )
        uppers = [upper + expansion for upper in uppers]
    verdicts = {upper <= threshold for upper in uppers}
    outcome: Literal["pass", "fail", "unstable"] = (
        "unstable" if len(verdicts) > 1 else "pass" if verdicts == {True} else "fail"
    )
    return Comparison(
        criterion.name,
        path,
        key,
        metric,
        settings.blocks,
        point,
        uppers[0],
        threshold,
        outcome,
    )


def completion_failures(
    records: Iterable[JsonDict], registration: Registration
) -> list[JsonDict]:
    minimum = cast("float", registration.section("gate")["completion"])
    failures: list[JsonDict] = []
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
    records: list[JsonDict],
    registration: Registration,
    *,
    phase: str,
    blocks: NonNegativeInt,
) -> JsonDict:
    inference = phase != "screening"
    required = [
        record for record in records if cast("int", record["workers"]) in {4, 8}
    ]
    settings = InferenceSettings.load(registration, blocks, inference=inference)
    comparisons = compare(paired_blocks(required), settings)
    failures = completion_failures(records, registration)
    failed = [comparison for comparison in comparisons if comparison.outcome != "pass"]
    verdicts: dict[str, str] = {}
    for candidate in settings.candidates:
        blocked = any(item.candidate == candidate for item in failed) or any(
            failure["path"] in {candidate, *BASELINES} for failure in failures
        )
        if inference:
            verdicts[candidate] = "defer" if blocked else "promote"
        else:
            verdicts[candidate] = "stop" if blocked else "continue"
    return {
        "phase": phase,
        "verdicts": verdicts,
        "completion_failures": failures,
        "comparisons": [asdict(comparison) for comparison in comparisons],
        "failed": [asdict(comparison) for comparison in failed],
    }


def descriptive(
    records: Iterable[JsonDict], statistics: Statistics = block_statistics
) -> list[JsonDict]:
    rows: list[JsonDict] = []
    for key, paths in sorted(paired_blocks(records, statistics).items()):
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


def _summary(values: list[float]) -> JsonDict:
    return {"mean": sum(values) / len(values), "min": min(values), "max": max(values)}


def exclusion_reason(record: JsonDict, registration: Registration) -> str | None:
    if not record["healthy"]:
        return str(record["failure"])
    per_worker = 1 if record["path"] == "independent" else 0
    workers = cast("list[JsonDict]", record["workers_measured"])
    if any(cast("int", worker["streams"]) != per_worker for worker in workers):
        return "observed stream openings differ from the registered count"
    if record["path"] not in BASELINES:
        owner = cast("JsonDict", record["owner"])
        commands = cast("dict[str, int]", owner["commands"])
        if owner["health"] != "healthy" or commands["stream:opened"]:
            return "the shared owner's stream was unhealthy or reopened"
    return validation_failure(record, registration)


def _paired_values(
    cell: dict[str, dict[int, dict[str, float] | None]],
    candidate: str,
    baseline: str,
    measure: str,
    blocks: NonNegativeInt,
) -> tuple[list[float], list[float]]:
    left: list[float] = []
    right: list[float] = []
    for block in range(blocks):
        try:
            values = (
                cast("dict[str, float]", cell[candidate][block])[measure],
                cast("dict[str, float]", cell[baseline][block])[measure],
            )
        except KeyError:
            continue
        left.append(values[0])
        right.append(values[1])
    return left, right


def describe_phase(
    records: list[JsonDict],
    registration: Registration,
    *,
    phase: str,
    blocks: NonNegativeInt,
) -> JsonDict:
    settings = registration.section("analysis")
    inference = registration.section("inference")
    registered = phase_blocks(registration, phase)
    if blocks != registered:
        message = f"the {phase} phase registers {registered} blocks, not {blocks}"
        raise BenchmarkConfigurationError(message)
    reject_duplicates(records)
    excluded: list[JsonDict] = []
    usable: list[JsonDict] = []
    for record in records:
        reason = exclusion_reason(record, registration)
        if reason is None:
            usable.append(record)
            continue
        excluded.append(
            {
                "cell": cell_key(record),
                "path": record["path"],
                "block": record["block"],
                "reason": reason,
            }
        )
    lag_floor = cast("int", inference["lag_event_floor"])
    statistics = partial(window_statistics, lag_floor=lag_floor)
    cells = paired_blocks(usable, statistics)
    unclaimed = [
        {
            "cell": key,
            "path": path,
            "block": block,
            "lag_events": values["lag_events"],
            "reason": f"fewer than {lag_floor} captured invalidations",
        }
        for key, paths in sorted(cells.items())
        for path, windows in sorted(paths.items())
        for block, values in sorted(windows.items())
        if values is not None and "lag_events" in values and "lag_p50" not in values
    ]
    comparisons: list[JsonDict] = []
    for key, cell in sorted(cells.items()):
        for candidate, baseline in cast("list[list[str]]", settings["pairs"]):
            for measure in cast("list[str]", settings["measures"]):
                left, right = _paired_values(cell, candidate, baseline, measure, blocks)
                comparison: JsonDict = {
                    "cell": key,
                    "candidate": candidate,
                    "baseline": baseline,
                    "measure": measure,
                    "pairs": len(left),
                }
                if left:
                    comparison.update(
                        {
                            estimand: asdict(
                                bootstrap(
                                    estimand,
                                    left,
                                    right,
                                    draws=cast("int", inference["draws"]),
                                    seed=cast("list[int]", inference["seeds"])[0],
                                    confidence=cast("float", inference["confidence"]),
                                )
                            )
                            for estimand in ("ratio", "delta")
                        }
                    )
                comparisons.append(comparison)
    return {
        "phase": phase,
        "blocks": blocks,
        "excluded": excluded,
        "lag_unclaimed": unclaimed,
        "paths": descriptive(usable, statistics),
        "comparisons": comparisons,
    }


def load_records(
    reports: Sequence[Path], registration: Registration, phase: str
) -> list[JsonDict]:
    environments: set[str] = set()
    records: list[JsonDict] = []
    for path in reports:
        report = cast("JsonDict", json.loads(path.read_text(encoding="utf-8")))
        environment = cast("JsonDict", report["environment"])
        if environment["configuration_sha256"] != registration.digest:
            message = f"{path} was measured under another registration"
            raise BenchmarkSetupError(message)
        if report["phase"] != phase:
            message = f"{path} holds the {report['phase']} phase, not {phase}"
            raise BenchmarkSetupError(message)
        if "exploratory" in report:
            message = f"{path} is exploratory: {report['exploratory']}"
            raise BenchmarkSetupError(message)
        if environment["dirty_tree"]:
            message = f"{path} was measured on a tree with uncommitted changes"
            raise BenchmarkSetupError(message)
        environments.add(
            json.dumps(measurement_environment(environment), sort_keys=True)
        )
        records.extend(cast("list[JsonDict]", report["cells"]))
    if len(environments) > 1:
        message = "reports were measured at different revisions or environments"
        raise BenchmarkSetupError(message)
    if any(record["phase"] != phase for record in records):
        message = f"a report holds windows outside the {phase} phase"
        raise BenchmarkSetupError(message)
    reject_duplicates(records)
    return records


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
    records = load_records(arguments.reports, registration, arguments.phase)
    output: JsonDict = (
        {"descriptive": descriptive(records)}
        if arguments.describe
        else decide(
            records, registration, phase=arguments.phase, blocks=arguments.blocks
        )
        if "gate" in registration.raw
        else describe_phase(
            records, registration, phase=arguments.phase, blocks=arguments.blocks
        )
    )
    print(json.dumps(output, indent=1, default=list))


if __name__ == "__main__":
    main()
