from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

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
    candidate: int  # Positive await time in milliseconds.
    reference: int | None  # Positive await time; None denotes an absolute gate.
    model: ExecutionModel
    workload: AwaitWorkload
    metric: AwaitMetric
    limit: float  # Positive registered limit.


class UncertaintyConfig(TypedDict):
    confidence_level: float  # Probability in (0, 1).
    method: str  # Nonempty method identifier.
    resample_count: int  # Positive number of ordered block resamples.
    resampling: str  # Nonempty procedure description.
    statistic: str  # Nonempty procedure description.
    one_sided_p_value: str  # Nonempty procedure description.
    upper_bound: str  # Nonempty procedure description.
    multiplicity: str  # Nonempty procedure description.
    resolution: dict[str, float]  # Nonempty metric-to-positive-resolution mapping.
    unresolved_denominator: str  # Nonempty resolution procedure description.


class AwaitConfiguration(TypedDict):
    schema_version: Literal[1]
    candidates_ms: list[int]  # Nonempty positive await times.
    models: list[ExecutionModel]  # Nonempty execution model list.
    block_orders: list[list[int]]  # Six nonempty candidate permutations.
    model_orders: list[list[ExecutionModel]]  # Six nonempty model permutations.
    warmup_seconds: float  # Positive duration.
    idle_minimum_seconds: float  # Positive duration.
    idle_minimum_completed_commands: int  # Positive command count.
    active_window_seconds: float  # Positive duration.
    write_offsets_seconds: dict[
        str, list[float]  # Nonempty schedules; offsets may be zero.
    ]
    write_schedule_tolerance_seconds: dict[
        str, float  # Positive per-workload tolerances.
    ]
    event_settle_timeout_seconds: float  # Positive timeout.
    shutdown_schedule_tolerance_seconds: float  # Positive permitted scheduling error.
    shutdown_window_timeout_seconds: float  # Positive deadline for all shutdown trials.
    shutdown_trial_offsets_seconds: list[float]  # Nonempty positive offsets.
    topology: dict[str, object]  # Nonempty topology descriptor.
    client_options: dict[str, object]  # Nonempty client option mapping.
    uncertainty: UncertaintyConfig
    comparisons: list[Comparison]  # Nonempty complete comparison family.
    selection: str  # Nonempty registered selection procedure.


@dataclass(frozen=True, slots=True)
class AwaitWindow:
    block: int  # Zero-based block index.
    candidate_ms: int  # Positive await time.
    model: ExecutionModel
    workload: AwaitWorkload
    elapsed_seconds: float  # Positive measured elapsed time.
    server_cpu_seconds: float | None  # Delta can be zero; not measured during shutdown.
    client_cpu_seconds: float | None  # Delta can be zero; not measured during shutdown.
    bytes_sent: int | None  # Delta can be zero; not measured during shutdown.
    bytes_received: int | None  # Delta can be zero; not measured during shutdown.
    getmore_started: int  # Command count can be zero on failure.
    getmore_completed: int  # Command count can be zero on failure.
    requested_max_time_ms: tuple[
        int | None, ...  # Empty on failure; None means absent.
    ]
    command_failures: int  # Failure count can be zero.
    manager_iteration_calls: int  # Iteration-call count can be zero.
    issue_offsets_seconds: tuple[float, ...]  # Empty for idle windows.
    lag_seconds: tuple[float, ...]  # Empty for idle windows.
    shutdown_seconds: tuple[float, ...]  # Empty outside shutdown trials.
    invalidations: int  # Event count can be zero.
    healthy: bool
    failure: str | None  # Nonempty error category, or None for a completed window.
    shutdown_start_offsets_seconds: tuple[float, ...] = ()  # Empty outside shutdown.
    shutdown_inflight: tuple[bool, ...] = ()  # Empty outside shutdown.
    getmore_inflight_at_start: int = (
        0  # Zero for windows starting at a command boundary.
    )


type WindowIdentity = tuple[int, int, ExecutionModel, AwaitWorkload]


def planned_windows(configuration: AwaitConfiguration) -> tuple[WindowIdentity, ...]:
    workloads: tuple[AwaitWorkload, ...] = ("idle", "paced", "burst", "shutdown")
    return tuple(
        (block, candidate, model, workload)
        for block, candidates in enumerate(configuration["block_orders"])
        for candidate in candidates
        for model in configuration["model_orders"][block]
        for workload in workloads
    )
