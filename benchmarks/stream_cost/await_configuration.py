from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from benchmarks.stream_cost.errors import BenchmarkConfigurationError
from client_query_cache._types import (
    JsonDict,
    MaxAwaitTimeMs,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
)

if TYPE_CHECKING:
    from benchmarks.stream_cost.await_model import (
        AwaitConfiguration,
        AwaitMetric,
        AwaitWorkload,
        Comparison,
        ExecutionModel,
    )


def _expand_comparisons(plan: object) -> list[Comparison]:
    groups = cast("dict[str, JsonDict]", plan)
    comparisons: list[Comparison] = []
    baseline = groups["baseline"]
    for candidate in cast("list[MaxAwaitTimeMs]", baseline["candidates_ms"]):
        for model in cast("list[str]", baseline["models"]):
            for case in cast("list[list[object]]", baseline["comparisons"]):
                workload, metric, limit = case[:3]
                reference = (
                    cast("MaxAwaitTimeMs | None", case[3]) if len(case) == 4 else 1000
                )
                comparisons.append(
                    {
                        "candidate": candidate,
                        "reference": reference,
                        "model": cast("ExecutionModel", model),
                        "workload": cast("AwaitWorkload", workload),
                        "metric": cast("AwaitMetric", metric),
                        "limit": cast("PositiveFloat", limit),
                    }
                )
    pairwise = groups["pairwise_idle"]
    references_by_candidate = cast(
        "dict[str, list[MaxAwaitTimeMs]]", pairwise["references_by_candidate_ms"]
    )
    for candidate in cast("list[MaxAwaitTimeMs]", pairwise["candidates_ms"]):
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
                            "limit": cast("PositiveFloat", limit),
                        }
                    )
    return comparisons


def _expand_schedule(pattern: object) -> list[NonNegativeFloat]:
    schedule = cast("JsonDict", pattern)
    start = cast("NonNegativeFloat", schedule["start_seconds"])
    interval = cast("PositiveFloat", schedule["interval_seconds"])
    count = cast("NonNegativeInt", schedule["count"])
    return [round(start + interval * index, 3) for index in range(count)]


def expand_await_configuration(raw: object) -> AwaitConfiguration:
    """Expand the compact frozen definition or return its original representation.

    Returns:
        The full await-time configuration used by benchmark and decision code.
    """
    configuration = cast("JsonDict", raw)
    if "comparison_plan" not in configuration:
        return cast("AwaitConfiguration", configuration)

    expanded = configuration.copy()
    schedules = cast("JsonDict", expanded.pop("write_schedule_patterns"))
    burst = cast("JsonDict", schedules["burst"])
    interval = cast("PositiveFloat", burst["interval_seconds"])
    expanded["write_offsets_seconds"] = {
        "paced": _expand_schedule(schedules["paced"]),
        "burst": [
            round(base + interval * index, 3)
            for base in cast("list[NonNegativeFloat]", burst["starts_seconds"])
            for index in range(cast("NonNegativeInt", burst["count_per_burst"]))
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
