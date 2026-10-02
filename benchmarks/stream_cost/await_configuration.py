from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from benchmarks.stream_cost.errors import BenchmarkConfigurationError

if TYPE_CHECKING:
    from benchmarks.stream_cost.await_model import (
        AwaitConfiguration,
        AwaitMetric,
        AwaitWorkload,
        Comparison,
        ExecutionModel,
    )


def _expand_comparisons(plan: object) -> list[Comparison]:
    groups = cast("dict[str, dict[str, object]]", plan)
    comparisons: list[Comparison] = []
    baseline = groups["baseline"]
    for candidate in cast("list[int]", baseline["candidates_ms"]):
        for model in cast("list[str]", baseline["models"]):
            for case in cast("list[list[object]]", baseline["comparisons"]):
                workload, metric, limit = case[:3]
                reference = cast("int | None", case[3]) if len(case) == 4 else 1000
                comparisons.append(
                    {
                        "candidate": candidate,
                        "reference": reference,
                        "model": cast("ExecutionModel", model),
                        "workload": cast("AwaitWorkload", workload),
                        "metric": cast("AwaitMetric", metric),
                        "limit": cast("float", limit),
                    }
                )
    pairwise = groups["pairwise_idle"]
    references_by_candidate = cast(
        "dict[str, list[int]]", pairwise["references_by_candidate_ms"]
    )
    for candidate in cast("list[int]", pairwise["candidates_ms"]):
        for reference in references_by_candidate[str(candidate)]:
            for model in cast("list[str]", pairwise["models"]):
                for metric, limit in cast("list[list[object]]", pairwise["metrics"]):
                    comparisons.append(
                        {
                            "candidate": candidate,
                            "reference": reference,
                            "model": cast("ExecutionModel", model),
                            "workload": "idle",
                            "metric": cast("AwaitMetric", metric),
                            "limit": cast("float", limit),
                        }
                    )
    return comparisons


def _expand_schedule(pattern: object) -> list[float]:
    schedule = cast("dict[str, object]", pattern)
    start = cast("float", schedule["start_seconds"])
    interval = cast("float", schedule["interval_seconds"])
    count = cast("int", schedule["count"])
    return [round(start + interval * index, 3) for index in range(count)]


def expand_await_configuration(raw: object) -> AwaitConfiguration:
    """Expand the compact frozen definition or return its original representation.

    Returns:
        The full await-time configuration used by benchmark and decision code.
    """
    configuration = cast("dict[str, object]", raw)
    if "comparison_plan" not in configuration:
        return cast("AwaitConfiguration", configuration)

    expanded = configuration.copy()
    schedules = cast("dict[str, object]", expanded.pop("write_schedule_patterns"))
    burst = cast("dict[str, object]", schedules["burst"])
    interval = cast("float", burst["interval_seconds"])
    expanded["write_offsets_seconds"] = {
        "paced": _expand_schedule(schedules["paced"]),
        "burst": [
            round(base + interval * index, 3)
            for base in cast("list[float]", burst["starts_seconds"])
            for index in range(cast("int", burst["count_per_burst"]))
        ],
    }
    expanded["comparisons"] = _expand_comparisons(expanded.pop("comparison_plan"))
    return cast("AwaitConfiguration", expanded)


def load_await_configuration(content: bytes) -> AwaitConfiguration:
    message = "invalid await-time configuration"
    try:
        return expand_await_configuration(json.loads(content))
    except KeyError as error:
        raise BenchmarkConfigurationError(message) from error
    except TypeError as error:
        raise BenchmarkConfigurationError(message) from error
    except ValueError as error:
        raise BenchmarkConfigurationError(message) from error
