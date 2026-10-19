from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
from statistics import median
from typing import TYPE_CHECKING, Literal, cast

from benchmarks.stream_cost.bootstrap import ConfidenceInterval
from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)
from benchmarks.stream_cost.shared_cache.fault_timeline import (
    classify_requests,
    detect_recovery,
    stream_reopening_counts,
    timeline_generations,
    validate_request_counts,
)
from benchmarks.stream_cost.shared_cache.protocol import (
    BASELINES,
    FaultCell,
    RecoveryFaultCell,
    Registration,
    capacity_cells,
    comparison_cells,
    fault_applicability,
    fault_cells,
    fault_recovery_cells,
    is_worker_fault_registration,
    measurement_environment,
    phase_blocks,
    throughput,
    validation_failure,
)
from client_query_cache._types import (
    JsonDict,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence


type Estimand = Literal["ratio", "delta", "absolute"]
type CellKey = (
    tuple[str, str, str, PositiveInt]
    | tuple[str, str, str, PositiveInt, PositiveInt | str]
)
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


_REQUIRED_WORKERS: frozenset[int] = frozenset((4, 8))
_CAPACITY_CRITERIA: tuple[tuple[str, str, str], ...] = (
    ("capacity-independent", "independent", "capacity_independent_ratio"),
    ("capacity-direct", "direct", "capacity_direct_ratio"),
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
    if record["phase"] == "fault":
        return (*key, str(record["fault_case"]))
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


def capacity_statistics(record: JsonDict) -> dict[str, float]:
    return {"throughput": throughput(record)}


def compare_capacity(
    cells: dict[CellKey, dict[str, dict[int, dict[str, float] | None]]],
    settings: InferenceSettings,
) -> list[Comparison]:
    comparisons: list[Comparison] = []
    for candidate in settings.candidates:
        for key, cell in sorted(cells.items()):
            for name, baseline, threshold_key in _CAPACITY_CRITERIA:
                threshold = cast("float", settings.gate[threshold_key])
                pairs = _pairs(cell, candidate, "throughput", baseline, settings.blocks)
                point: float | None = None
                outcome: Literal["pass", "fail", "missing"] = "missing"
                if pairs is not None:
                    point = min(
                        measured / reference
                        for measured, reference in zip(*pairs, strict=True)
                    )
                    outcome = "pass" if point >= threshold else "fail"
                comparisons.append(
                    Comparison(
                        name,
                        candidate,
                        key,
                        "throughput",
                        settings.blocks,
                        point,
                        None,
                        threshold,
                        outcome,
                    )
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
        record
        for record in records
        if cast("int", record["workers"]) in _REQUIRED_WORKERS
    ]
    settings = InferenceSettings.load(registration, blocks, inference=inference)
    capacity = phase == "capacity"
    cells = paired_blocks(
        required, capacity_statistics if capacity else block_statistics
    )
    planned = (
        capacity_cells(registration)
        if capacity
        else comparison_cells(registration, phase)
    )
    for cell in planned:
        if cell.workers in _REQUIRED_WORKERS:
            cells.setdefault(cell_key(asdict(cell)), {})
    comparisons = (
        compare_capacity(cells, settings) if capacity else compare(cells, settings)
    )
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


def _fault_repetition(
    record: JsonDict | None,
    declaration: dict[str, bool],
    bound: PositiveFloat,
    block: NonNegativeInt,
) -> JsonDict:
    failures: list[str] = []
    durations: JsonDict = {}
    if record is None:
        failures.append("missing trial")
    else:
        if not record["healthy"] or not record["checks"]:
            failures.append(
                str(record["failure"])
                if "failure" in record
                else "safety checks failed or absent"
            )
        events = cast("JsonDict", record["events"])
        reported = cast("JsonDict", record["durations"])
        for name, applies in declaration.items():
            try:
                duration = reported[name]
            except KeyError:
                duration = None
            durations[name] = duration
            if not applies:
                if duration is not None:
                    failures.append(f"{name} must be inapplicable")
                continue
            origin = "injection" if name == "detection" else "recovery"
            if (
                name not in events
                or origin not in events
                or not isinstance(duration, (int, float))
                or not math.isfinite(duration)
                or duration < 0
            ):
                failures.append(f"missing or invalid {name}")
                continue
            if not math.isclose(
                duration,
                cast("float", events[name]) - cast("float", events[origin]),
                abs_tol=1e-9,
            ):
                failures.append(f"{name} does not match its event timestamps")
            if name == "readiness" and duration > bound:
                failures.append("readiness exceeds registered bound")
    return {
        "block": block,
        "durations": durations,
        "pass": not failures,
        "failures": failures,
    }


def _reconstruct_worker_fault(
    record: JsonDict, cell: RecoveryFaultCell, registration: Registration
) -> tuple[list[JsonDict], JsonDict]:
    request_record = cast("JsonDict", record["requests"])
    timelines = cast("list[JsonDict]", request_record["timeline"])
    requests: list[JsonDict] = []
    rate = cast("PositiveFloat", cell.rate)
    offered = round(rate * cell.window_seconds)
    for timeline in timelines:
        events = cast("list[JsonDict]", timeline["events"])
        ordinals = cast("list[NonNegativeInt]", timeline["scheduled_ordinals"])
        killed_at = cast("float | None", timeline["killed_at"])
        requests.extend(
            classify_requests(
                ordinals,
                events,
                rate=rate,
                killed_at=killed_at,
            )
        )
    counts = validate_request_counts(requests, offered)
    if counts != request_record["counts"]:
        raise BenchmarkSetupError("reported fault request counts differ from timeline")
    replacement_ready_offset = cast(
        "float | None",
        cast("JsonDict", record["worker_details"])["replacement_ready_offset"],
    )
    injection = cast(
        "float", cast("JsonDict", record["injection"])["actual_offset_seconds"]
    )
    criterion = registration.recovery_criterion()
    recovery = detect_recovery(
        requests,
        injection_offset=injection,
        deadline=injection + cell.recovery_deadline_seconds,
        window_end=cell.window_seconds,
        before_seconds=cast(
            "PositiveFloat",
            registration.section("fault_recovery")["before_interval_seconds"],
        ),
        replacement_ready_offset=replacement_ready_offset,
        bucket_seconds=criterion.bucket_seconds,
        minimum_completion_fraction=criterion.minimum_completion_fraction,
        request_p99_multiple=criterion.request_p99_multiple,
        backlog_grace_p99_multiple=criterion.backlog_grace_p99_multiple,
    )
    reported_recovery = cast("JsonDict", record["recovery"])
    if (
        recovery["recovered"] != reported_recovery["recovered"]
        or recovery["recovery_offset"] != reported_recovery["recovery_offset"]
    ):
        raise BenchmarkSetupError("reported fault recovery differs from its timeline")
    return requests, recovery


def _fault_snapshots(
    record: JsonDict,
    *,
    injection: NonNegativeFloat,
    fault_interval_end: NonNegativeFloat,
    window_end: NonNegativeFloat,
) -> JsonDict:
    worker_record = cast("JsonDict", record["worker_details"])
    timelines = cast("list[JsonDict]", cast("JsonDict", record["requests"])["timeline"])
    bypasses: Counter[str] = Counter()
    health_times: list[NonNegativeFloat] = []
    hit_times: list[NonNegativeFloat] = []
    stream_reopenings = stream_reopening_counts(
        timelines,
        injection_offset=injection,
        window_end=window_end,
    )
    replacement_misses: NonNegativeInt | None = None
    for timeline in timelines:
        snapshots = cast("list[JsonDict]", timeline["snapshots"])
        generations = timeline_generations(snapshots)
        ordered = sorted(
            snapshots, key=lambda snapshot: cast("float", snapshot["offset"])
        )
        if not ordered:
            raise BenchmarkSetupError("fault worker timeline has no snapshots")
        through_window = [
            sample
            for sample in ordered
            if injection <= cast("float", sample["offset"]) <= window_end
        ]
        for generation in generations:
            generation_before = [
                sample
                for sample in generation
                if cast("float", sample["offset"]) <= injection
            ]
            generation_fault = [
                sample
                for sample in generation
                if injection <= cast("float", sample["offset"]) <= fault_interval_end
            ]
            if generation_fault:
                initial_reasons = (
                    cast("dict[str, int]", generation_before[-1]["bypass_reasons"])
                    if generation_before
                    else {}
                )
                final_reasons = cast(
                    "dict[str, int]", generation_fault[-1]["bypass_reasons"]
                )
                for reason, count in final_reasons.items():
                    try:
                        previous = initial_reasons[reason]
                    except KeyError:
                        previous = 0
                    if count > previous:
                        bypasses[reason] += count - previous
            initial_hits = (
                cast("int", generation_before[-1]["hits"]) if generation_before else 0
            )
            generation_window = [
                sample
                for sample in generation
                if injection <= cast("float", sample["offset"]) <= window_end
            ]
            for sample in generation_window:
                if cast("int", sample["hits"]) > initial_hits:
                    hit_times.append(cast("float", sample["offset"]) - injection)
                    break
        observed_unhealthy = False
        killed_at = cast("float | None", timeline["killed_at"])
        for sample in through_window:
            offset = cast("float", sample["offset"])
            if killed_at is not None and offset >= killed_at:
                observed_unhealthy = True
            health = sample["health"]
            if health is not None and health != "healthy":
                observed_unhealthy = True
            elif health == "healthy" and observed_unhealthy:
                health_times.append(offset - injection)
                break
        ready_value = timeline["replacement_ready_offset"]
        if ready_value is None:
            continue
        ready_offset = cast("float", ready_value)
        replacement_generation = generations[-1]
        replacement_snapshots = [
            sample
            for sample in replacement_generation
            if cast("float", sample["offset"]) <= window_end
        ]
        ready_samples = [
            sample
            for sample in replacement_generation
            if cast("float", sample["offset"]) <= ready_offset
        ]
        replacement_ready = cast("JsonDict", worker_record["replacement_ready"])
        priming_misses = cast("int", replacement_ready["priming_misses"])
        replacement_misses = priming_misses
        if replacement_snapshots:
            ready_misses = (
                cast("int", ready_samples[-1]["misses"])
                if ready_samples
                else priming_misses
            )
            replacement_misses += max(
                0,
                cast("int", replacement_snapshots[-1]["misses"]) - ready_misses,
            )
    return {
        "bypasses_by_reason": dict(sorted(bypasses.items())),
        "time_to_stream_health_seconds": min(health_times) if health_times else None,
        "time_to_cache_hit_seconds": min(hit_times) if hit_times else None,
        "stream_reopenings": sum(stream_reopenings),
        "stream_reopenings_by_worker": stream_reopenings,
        "replacement_repriming_misses": replacement_misses,
    }


def _fault_range(values: list[float]) -> JsonDict | None:
    if not values:
        return None
    return {"median": median(values), "min": min(values), "max": max(values)}


def _fault_repetition_passed(repetition: JsonDict) -> bool:
    if repetition["healthy"] is not True:
        return False
    try:
        recovery = cast("JsonDict", repetition["recovery"])
        correctness = cast("JsonDict", repetition["correctness"])
    except KeyError:
        return False
    return recovery["recovered"] is True and correctness["passed"] is True


def analyze_worker_faults(
    records: list[JsonDict], registration: Registration
) -> JsonDict:
    expected = {
        (cell.fault_case, cell.path, cell.block): cell
        for cell in fault_recovery_cells(registration)
        if isinstance(cell, RecoveryFaultCell)
    }
    measured: dict[tuple[str, str, NonNegativeInt], JsonDict] = {}
    for record in records:
        key = (
            str(record["fault_case"]),
            str(record["path"]),
            cast("int", record["block"]),
        )
        if key in measured or key not in expected:
            message = f"duplicate or unregistered worker fault trial {key}"
            raise BenchmarkSetupError(message)
        cell = expected[key]
        mismatches = [
            field for field, value in asdict(cell).items() if record[field] != value
        ]
        if mismatches:
            message = (
                f"worker fault trial differs from registration {key}: {mismatches}"
            )
            raise BenchmarkSetupError(message)
        measured[key] = record

    cases: list[JsonDict] = []
    groups = dict.fromkeys((case, path) for case, path, _block in sorted(expected))
    for case, path in groups:
        case_cell = next(
            cell for key, cell in expected.items() if key[:2] == (case, path)
        )
        repetitions: list[JsonDict] = []
        for key in sorted(key for key in expected if key[:2] == (case, path)):
            cell = expected[key]
            try:
                measured_record: JsonDict | None = measured[key]
            except KeyError:
                measured_record = None
            if measured_record is None:
                repetitions.append(
                    {"block": key[2], "healthy": False, "failure": "missing trial"}
                )
                continue
            if not measured_record["healthy"]:
                repetitions.append(
                    {
                        "block": key[2],
                        "healthy": False,
                        "failure": measured_record["failure"],
                    }
                )
                continue
            requests, recovery = _reconstruct_worker_fault(
                measured_record, cell, registration
            )
            injection = cast(
                "float",
                cast("JsonDict", measured_record["injection"])["actual_offset_seconds"],
            )
            recovery_offset = cast("float | None", recovery["recovery_offset"])
            observation_end = (
                recovery_offset if recovery_offset is not None else cell.window_seconds
            )
            timeline_metrics = _fault_snapshots(
                measured_record,
                injection=injection,
                fault_interval_end=observation_end,
                window_end=cell.window_seconds,
            )
            request_data = cast("JsonDict", measured_record["requests"])
            counts = cast("JsonDict", request_data["counts"])
            correctness = cast("JsonDict", measured_record["correctness"])
            replacement_ready = cast(
                "float | None",
                cast("JsonDict", measured_record["worker_details"])[
                    "replacement_ready_offset"
                ],
            )
            replacement_ready_seconds = (
                None if replacement_ready is None else replacement_ready - injection
            )
            latencies = cast("JsonDict", request_data["latencies"])
            row: JsonDict = {
                "block": key[2],
                "healthy": True,
                "outcome": measured_record["outcome"],
                "injection_offset_seconds": injection,
                "recovery": recovery,
                "request_counts": counts,
                "failed_reads": counts["failed"],
                "latencies": latencies,
                **timeline_metrics,
                "replacement_ready_seconds": replacement_ready_seconds,
                "correctness": correctness,
                "write_failures": cast("JsonDict", measured_record["writes"])["failed"],
                "unknown_writes": cast("JsonDict", measured_record["writes"])[
                    "unknown"
                ],
                "command_failures": measured_record["command_failures"],
                "worker_cpu_seconds": measured_record["worker_cpu_seconds"],
                "server_cpu_seconds": measured_record["server_cpu_seconds"],
                "requests_classified": len(requests),
            }
            repetitions.append(row)
        recovery_measure_names: list[str] = []
        if path == "independent":
            recovery_measure_names.extend(
                ("time_to_stream_health_seconds", "time_to_cache_hit_seconds")
            )
        if case == "worker-restart":
            recovery_measure_names.append("replacement_ready_seconds")
        measures: dict[str, list[float]] = {name: [] for name in recovery_measure_names}
        for repetition in repetitions:
            if not repetition["healthy"]:
                continue
            recovery = cast("JsonDict", repetition["recovery"])
            if recovery["recovered"]:
                measures.setdefault("time_to_recovery_seconds", []).append(
                    cast("float", recovery["time_to_recovery_seconds"])
                )
            for name in (
                "failed_reads",
                "worker_cpu_seconds",
                "server_cpu_seconds",
                "stream_reopenings",
                "replacement_repriming_misses",
                "write_failures",
                "unknown_writes",
            ):
                value = cast("float", repetition[name])
                measures.setdefault(name, []).append(value)
            for name in recovery_measure_names:
                measure_value = repetition[name]
                if measure_value is not None:
                    measures[name].append(cast("float", measure_value))
            for interval, distribution in cast(
                "JsonDict", repetition["latencies"]
            ).items():
                if distribution is None:
                    continue
                for percentile_name, percentile_value in cast(
                    "JsonDict", distribution
                ).items():
                    measures.setdefault(
                        f"{interval}_{percentile_name}_seconds", []
                    ).append(cast("float", percentile_value))
        cases.append(
            {
                "case": case,
                "path": path,
                "topology": case_cell.topology,
                "repetitions": repetitions,
                "median_and_range": {
                    name: _fault_range(values)
                    for name, values in sorted(measures.items())
                },
                "pass": all(_fault_repetition_passed(row) for row in repetitions),
            }
        )
    return {
        "phase": "fault",
        "complete": len(measured) == len(expected),
        "pass": len(measured) == len(expected) and all(case["pass"] for case in cases),
        "cases": cases,
    }


def analyze_faults(records: list[JsonDict], registration: Registration) -> JsonDict:
    declarations = fault_applicability(registration)
    expected = {
        (cell.fault_case, cell.path, cell.block): asdict(cell)
        for cell in fault_cells(registration)
        if isinstance(cell, FaultCell)
    }
    measured: dict[tuple[str, str, NonNegativeInt], JsonDict] = {}
    for record in records:
        key = (
            str(record["fault_case"]),
            str(record["path"]),
            cast("int", record["block"]),
        )
        if key in measured or key not in expected:
            message = f"duplicate or unregistered fault trial {key}"
            raise BenchmarkSetupError(message)
        if any(record[field] != value for field, value in expected[key].items()):
            message = f"fault trial does not match its registered cell {key}"
            raise BenchmarkSetupError(message)
        measured[key] = record
    cases: list[JsonDict] = []
    for case, path in dict.fromkeys(
        (case, path) for case, path, _block in sorted(expected)
    ):
        repetitions: list[JsonDict] = []
        for _case, _path, block in sorted(
            key for key in expected if key[:2] == (case, path)
        ):
            key = (case, path, block)
            try:
                trial_record: JsonDict | None = measured[key]
            except KeyError:
                trial_record = None
            repetitions.append(
                _fault_repetition(
                    trial_record,
                    declarations[case],
                    registration.number("gate", "readiness_seconds"),
                    block,
                )
            )
        cases.append(
            {
                "case": case,
                "path": path,
                "applicability": declarations[case],
                "pass": all(row["pass"] for row in repetitions),
                "repetitions": repetitions,
            }
        )
    return {
        "phase": "fault",
        "pass": all(case["pass"] for case in cases),
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate shared worker cache evidence."
    )
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--config", type=Path, default=_CONFIG)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--blocks", type=int)
    parser.add_argument("--describe", action="store_true")
    arguments = parser.parse_args(argv)
    registration = Registration.load(arguments.config)
    if arguments.phase != "fault" and arguments.blocks is None:
        parser.error("--blocks is required outside the fault phase")
    records = load_records(arguments.reports, registration, arguments.phase)
    output: JsonDict = (
        analyze_worker_faults(records, registration)
        if arguments.phase == "fault" and is_worker_fault_registration(registration)
        else analyze_faults(records, registration)
        if arguments.phase == "fault"
        else {"descriptive": descriptive(records)}
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
