from __future__ import annotations

import json
import math
from dataclasses import dataclass
from hashlib import sha256
from itertools import permutations
from typing import TYPE_CHECKING, Literal, cast

from benchmarks.stream_cost.errors import BenchmarkConfigurationError
from benchmarks.stream_cost.shared_cache.coordinator import TransportLimits

if TYPE_CHECKING:
    from pathlib import Path

    from client_query_cache._types import (
        NonNegativeFloat,
        NonNegativeInt,
        PositiveFloat,
        PositiveInt,
    )

type Payload = dict[str, object]
type PathKind = Literal["direct", "independent", "shared"]
type Model = Literal["sync", "async", "mixed"]
type Workload = Literal["hot", "active", "cold"]
type Loop = Literal["open", "closed"]
type Family = Literal["primary", "cold", "sensitivity"]

PATHS: tuple[PathKind, ...] = ("direct", "independent", "shared")
BASELINES: tuple[PathKind, ...] = ("direct", "independent")
_FAMILY_WORKLOADS: dict[str, Workload] = {
    "hot": "hot",
    "active": "active",
    "cold": "cold",
    "large": "hot",
    "find16": "hot",
}


@dataclass(frozen=True, slots=True)
class Registration:
    raw: Payload
    digest: str

    @classmethod
    def load(cls, path: Path) -> Registration:
        content = path.read_bytes()
        return cls(json.loads(content), sha256(content).hexdigest())

    def section(self, name: str) -> Payload:
        return cast("Payload", self.raw[name])

    def number(self, *keys: str) -> float:
        value: object = self.raw
        for key in keys:
            value = cast("Payload", value)[key]
        assert isinstance(value, (int, float))
        return value

    @property
    def frozen(self) -> bool:
        return self.raw["status"] == "frozen"

    def profile(self, name: str) -> Payload:
        return cast("Payload", self.section("profiles")[name])

    def limits(self) -> TransportLimits:
        return TransportLimits(**cast("dict[str, float]", self.section("transport")))  # type: ignore[arg-type]

    def rate(self, family: Family) -> PositiveFloat:
        rates = cast("Payload", self.section("frozen")["rates"])
        value = rates[family]
        if value is None:
            message = f"registration has no frozen {family} rate"
            raise BenchmarkConfigurationError(message)
        assert isinstance(value, (int, float))
        return value

    def window(self, kind: str) -> PositiveFloat:
        windows = cast("Payload", self.section("frozen")["window_seconds"])
        value = windows[kind]
        if value is None:
            message = f"registration has no frozen {kind} window"
            raise BenchmarkConfigurationError(message)
        assert isinstance(value, (int, float))
        return value


@dataclass(frozen=True, slots=True)
class Cell:
    phase: str
    block: NonNegativeInt
    workload: Workload
    profile: str
    model: Model
    workers: PositiveInt
    path: PathKind
    loop: Loop
    concurrency: PositiveInt
    window_seconds: PositiveFloat
    warmup_seconds: NonNegativeFloat
    rate: PositiveFloat | None = None
    identities: PositiveInt | None = None

    @property
    def key(self) -> tuple[str, str, Model, PositiveInt, PositiveInt]:
        return (self.workload, self.profile, self.model, self.workers, self.concurrency)

    def sync_workers(self) -> NonNegativeInt:
        if self.model == "mixed":
            return self.workers // 2
        return self.workers if self.model == "sync" else 0


def path_order(
    block: NonNegativeInt, paths: tuple[PathKind, ...]
) -> tuple[PathKind, ...]:
    orders = tuple(permutations(paths))
    return orders[block % len(orders)]


def _ordered[T](items: tuple[T, ...], block: NonNegativeInt) -> tuple[T, ...]:
    return items[::-1] if block % 2 else items


def family_cells(
    registration: Registration, family: Family
) -> tuple[tuple[str, Model, PositiveInt], ...]:
    entries = cast(
        "list[list[object]]", registration.section("calibration")["families"]
    )
    families = cast("dict[str, list[list[object]]]", entries)
    return tuple(
        (str(kind), cast("Model", model), cast("int", workers))
        for kind, model, workers in families[family]
    )


def cell_kind(workload: str, profile: str) -> str:
    return profile if profile in {"large", "find16"} else workload


def _profile_for(kind: str) -> str:
    return kind if kind in {"large", "find16"} else "primary"


def required_samples(registration: Registration) -> PositiveInt:
    floor = registration.number("calibration", "sample_floor")
    completion = registration.number("calibration", "minimum_completion")
    return math.ceil(floor / completion)


def window_for(
    registration: Registration, kind: str, rate: PositiveFloat, model: Model
) -> PositiveFloat:
    nominal = registration.number("nominal_seconds", kind)
    populations = 2 if model == "mixed" else 1
    needed = required_samples(registration) * populations / rate
    return max(nominal, math.ceil(needed))


def probe_cells(registration: Registration) -> tuple[Cell, ...]:
    calibration = registration.section("calibration")
    windows = cast("int", calibration["probe_windows"])
    seconds = registration.number("calibration", "probe_seconds")
    warmup = registration.number("warmup_seconds")
    concurrency = cast("int", registration.raw["concurrency_per_worker"])
    cells: list[Cell] = []
    for family in ("primary", "cold", "sensitivity"):
        for kind, model, workers in family_cells(registration, family):
            for window in range(windows):
                for path in _ordered(BASELINES, window):
                    workload = _FAMILY_WORKLOADS[kind]
                    cells.append(
                        Cell(
                            phase="probe",
                            block=window,
                            workload=workload,
                            profile=_profile_for(kind),
                            model=model,
                            workers=workers,
                            path=path,
                            loop="closed",
                            concurrency=concurrency,
                            window_seconds=seconds,
                            warmup_seconds=0 if workload == "cold" else warmup,
                            identities=cast("int", calibration["cold_probe_identities"])
                            if workload == "cold"
                            else None,
                        )
                    )
    return tuple(cells)


def validation_cells(
    registration: Registration,
    family: Family,
    rate: PositiveFloat,
    durations: dict[str, PositiveFloat],
) -> tuple[Cell, ...]:
    repetitions = cast(
        "int", registration.section("calibration")["validation_repetitions"]
    )
    return tuple(
        fixed_cell(
            registration,
            phase="validation",
            block=repetition,
            kind=kind,
            model=model,
            workers=workers,
            path=path,
            rate=rate,
            durations=durations,
        )
        for repetition in range(repetitions)
        for kind, model, workers in family_cells(registration, family)
        for path in _ordered(BASELINES, repetition)
    )


def fixed_cell(
    registration: Registration,
    *,
    phase: str,
    block: NonNegativeInt,
    kind: str,
    model: Model,
    workers: PositiveInt,
    path: PathKind,
    rate: PositiveFloat,
    durations: dict[str, PositiveFloat],
) -> Cell:
    workload = _FAMILY_WORKLOADS[kind]
    identities = (
        cast("int", registration.section("calibration")["cold_probe_identities"])
        if workload == "cold"
        else None
    )
    duration = (
        identities / rate
        if identities is not None
        else durations["sensitivity" if kind in {"large", "find16"} else kind]
    )
    return Cell(
        phase=phase,
        block=block,
        workload=workload,
        profile=_profile_for(kind),
        model=model,
        workers=workers,
        path=path,
        loop="open",
        concurrency=cast("int", registration.raw["concurrency_per_worker"]),
        window_seconds=duration,
        warmup_seconds=0
        if workload == "cold"
        else registration.number("warmup_seconds"),
        rate=rate,
        identities=identities,
    )


def frozen_durations(registration: Registration) -> dict[str, PositiveFloat]:
    return {
        kind: registration.window(kind) for kind in ("hot", "active", "sensitivity")
    }


def comparison_cells(
    registration: Registration, phase: str, paths: tuple[PathKind, ...] = PATHS
) -> tuple[Cell, ...]:
    phases = registration.section("phases")
    settings = cast("Payload", phases[phase])
    durations = frozen_durations(registration)
    cells: list[Cell] = []
    blocks = cast("int", settings["blocks"])
    for block in range(blocks):
        for kind, model, workers in _phase_matrix(phase, settings):
            for path in path_order(block, paths):
                family: Family = (
                    "cold"
                    if kind == "cold"
                    else "sensitivity"
                    if kind in {"large", "find16"}
                    else "primary"
                )
                cells.append(
                    fixed_cell(
                        registration,
                        phase=phase,
                        block=block,
                        kind=kind,
                        model=model,
                        workers=workers,
                        path=path,
                        rate=registration.rate(family),
                        durations=durations,
                    )
                )
    return tuple(cells)


def _phase_matrix(
    phase: str, settings: Payload
) -> tuple[tuple[str, Model, PositiveInt], ...]:
    models: tuple[Model, ...] = ("sync", "async")
    if phase in {"screening", "confirmation", "cold"}:
        kind = "cold" if phase == "cold" else "hot"
        counts = cast("list[int]", settings["worker_counts"])
        return tuple((kind, model, workers) for workers in counts for model in models)
    if phase == "active":
        counts = cast("list[int]", settings["worker_counts"])
        mixed = cast("list[int]", settings["mixed"])
        return (
            *(("active", model, workers) for workers in counts for model in models),
            ("active", "mixed", sum(mixed)),
        )
    workers = cast("int", settings["workers"])
    profiles = cast("list[str]", settings["profiles"])
    return tuple((profile, model, workers) for profile in profiles for model in models)


def capacity_cells(registration: Registration) -> tuple[Cell, ...]:
    settings = cast("Payload", registration.section("phases")["capacity"])
    models: tuple[Model, ...] = ("sync", "async")
    return tuple(
        Cell(
            phase="capacity",
            block=window,
            workload="hot",
            profile="primary",
            model=model,
            workers=workers,
            path=path,
            loop="closed",
            concurrency=concurrency,
            window_seconds=registration.number("phases", "capacity", "window_seconds"),
            warmup_seconds=registration.number("warmup_seconds"),
        )
        for window in range(cast("int", settings["windows"]))
        for workers in cast("list[int]", settings["worker_counts"])
        for model in models
        for concurrency in cast("list[int]", settings["concurrency"])
        for path in path_order(window, PATHS)
    )


def smoke_cells(registration: Registration) -> tuple[Cell, ...]:
    settings = cast("Payload", registration.section("phases")["smoke"])
    combinations: tuple[tuple[Workload, Model], ...] = (
        ("hot", "sync"),
        ("active", "mixed"),
        ("cold", "async"),
    )
    return tuple(
        Cell(
            phase="smoke",
            block=0,
            workload=workload,
            profile="smoke",
            model=model,
            workers=2,
            path=path,
            loop="open",
            concurrency=cast("int", registration.raw["concurrency_per_worker"]),
            window_seconds=cast("float", settings["window_seconds"]),
            warmup_seconds=0
            if workload == "cold"
            else cast("float", settings["warmup_seconds"]),
            rate=cast("float", settings["rate"]),
            identities=cast("int", settings["identities"])
            if workload == "cold"
            else None,
        )
        for workload, model in combinations
        for path in PATHS
    )
