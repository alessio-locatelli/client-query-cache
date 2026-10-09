from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, TypedDict

from annotated_types import Len

from client_query_cache._types import (
    ExclusiveProbability,
    MaxAwaitTimeMs,
    NonEmpty,
    NonEmptyStr,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)

type ExecutionModel = Literal["sync", "async"]
type AwaitWorkload = Literal["idle", "paced", "burst", "shutdown"]


type AwaitMetric = Literal[
    "lag_p95_seconds",
    "shutdown_p95_seconds",
    "server_cpu_seconds",
    "client_cpu_seconds",
    "server_cpu_rate",
    "client_cpu_rate",
    "byte_rate",
]


class Comparison(TypedDict):
    candidate: MaxAwaitTimeMs
    reference: MaxAwaitTimeMs | None  # None denotes an absolute gate.
    model: ExecutionModel
    workload: AwaitWorkload
    metric: AwaitMetric
    limit: PositiveFloat  # Registered limit.


class UncertaintyConfig(TypedDict):
    confidence_level: ExclusiveProbability
    method: NonEmptyStr
    resample_count: PositiveInt  # Ordered block resamples.
    resampling: NonEmptyStr  # Procedure description.
    statistic: NonEmptyStr  # Procedure description.
    one_sided_p_value: NonEmptyStr  # Procedure description.
    upper_bound: NonEmptyStr  # Procedure description.
    multiplicity: NonEmptyStr  # Procedure description.
    resolution: NonEmpty[dict[str, PositiveFloat]]  # Keyed by metric.
    unresolved_denominator: NonEmptyStr  # Resolution procedure description.


class AwaitConfiguration(TypedDict):
    schema_version: Literal[1]
    candidates_ms: NonEmpty[list[MaxAwaitTimeMs]]
    models: NonEmpty[list[ExecutionModel]]
    block_orders: Annotated[list[NonEmpty[list[MaxAwaitTimeMs]]], Len(6, 6)]
    model_orders: Annotated[list[NonEmpty[list[ExecutionModel]]], Len(6, 6)]
    warmup_seconds: PositiveFloat
    idle_minimum_seconds: PositiveFloat
    idle_minimum_completed_commands: PositiveInt
    active_window_seconds: PositiveFloat
    write_offsets_seconds: dict[str, NonEmpty[list[NonNegativeFloat]]]
    write_schedule_tolerance_seconds: dict[str, PositiveFloat]  # Per workload.
    event_settle_timeout_seconds: PositiveFloat
    shutdown_schedule_tolerance_seconds: PositiveFloat  # Permitted scheduling error.
    shutdown_window_timeout_seconds: PositiveFloat  # Deadline for all shutdown trials.
    shutdown_trial_offsets_seconds: NonEmpty[list[PositiveFloat]]
    topology: NonEmpty[dict[str, object]]
    client_options: NonEmpty[dict[str, object]]
    uncertainty: UncertaintyConfig
    comparisons: NonEmpty[list[Comparison]]  # Complete comparison family.
    selection: NonEmptyStr  # Registered selection procedure.


@dataclass(frozen=True, slots=True)
class AwaitWindow:
    block: NonNegativeInt  # Zero-based.
    candidate_ms: MaxAwaitTimeMs
    model: ExecutionModel
    workload: AwaitWorkload
    elapsed_seconds: PositiveFloat
    server_cpu_seconds: NonNegativeFloat | None  # Not measured during shutdown.
    client_cpu_seconds: NonNegativeFloat | None  # Not measured during shutdown.
    bytes_sent: NonNegativeInt | None  # Not measured during shutdown.
    bytes_received: NonNegativeInt | None  # Not measured during shutdown.
    getmore_started: NonNegativeInt
    getmore_completed: NonNegativeInt
    requested_max_time_ms: tuple[NonNegativeInt | None, ...]  # None means absent.
    command_failures: NonNegativeInt
    manager_iteration_calls: NonNegativeInt
    issue_offsets_seconds: tuple[NonNegativeFloat, ...]
    lag_seconds: tuple[NonNegativeFloat, ...]
    shutdown_seconds: tuple[NonNegativeFloat, ...]
    invalidations: NonNegativeInt
    healthy: bool
    failure: NonEmptyStr | None  # Error category, or None for a completed window.
    shutdown_start_offsets_seconds: tuple[NonNegativeFloat, ...] = ()
    shutdown_inflight: tuple[bool, ...] = ()
    getmore_inflight_at_start: NonNegativeInt = 0


type WindowIdentity = tuple[
    NonNegativeInt, MaxAwaitTimeMs, ExecutionModel, AwaitWorkload
]


def planned_windows(configuration: AwaitConfiguration) -> tuple[WindowIdentity, ...]:
    workloads: tuple[AwaitWorkload, ...] = ("idle", "paced", "burst", "shutdown")
    return tuple(
        (block, candidate, model, workload)
        for block, candidates in enumerate(configuration["block_orders"])
        for candidate in candidates
        for model in configuration["model_orders"][block]
        for workload in workloads
    )
