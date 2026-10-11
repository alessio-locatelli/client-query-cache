from __future__ import annotations

import json
import math
from dataclasses import dataclass
from hashlib import sha256
from itertools import permutations, starmap
from typing import TYPE_CHECKING, Literal, cast

from benchmarks.stream_cost.errors import BenchmarkConfigurationError
from benchmarks.stream_cost.shared_cache.coordinator import TransportLimits
from client_query_cache._types import (
    JsonDict,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


type PathKind = Literal["direct", "independent", "shared"]
type Model = Literal["sync", "async", "mixed"]
type Workload = Literal["hot", "active", "cold"]
type Loop = Literal["open", "closed"]
type KeyAssignment = Literal["partitioned", "shared"]
type CellSpec = tuple[str, Model, PositiveInt]

BASELINES: tuple[PathKind, ...] = ("direct", "independent")
_V4_PATHS: tuple[PathKind, ...] = ("direct", "independent", "shared")
_V4_MODELS: tuple[Model, ...] = ("sync", "async")
_MODELS: frozenset[str] = frozenset(("sync", "async", "mixed"))
_KEY_ASSIGNMENTS: frozenset[str] = frozenset(("partitioned", "shared"))
_FAMILY_WORKLOADS: dict[str, Workload] = {
    "hot": "hot",
    "active": "active",
    "cold": "cold",
    "large": "hot",
    "find16": "hot",
}


def _positive(value: object) -> bool:
    return type(value) is int and value > 0


@dataclass(frozen=True, slots=True)
class Registration:
    raw: JsonDict
    digest: str

    def __post_init__(self) -> None:
        self._validate_workload()
        self._validate_plan()
        self._validate_cold_routing()

    def _validate_cold_routing(self) -> None:
        if self.key_assignment != "shared" or "shared" not in self.paths:
            return
        phases = cast("dict[str, JsonDict]", self.section("phases"))
        kinds = {kind for family in families(self) for kind, _, _ in family.cells}
        kinds.update(
            kind
            for phase, settings in phases.items()
            if "cells" in settings or phase in _V4_PHASE_CELLS
            for kind, _, _ in phase_cells(self, phase)
        )
        if "cold" in kinds:
            message = (
                "shared key assignment lets workers repeat cold keys, "
                "so the shared path cannot measure all-miss cold windows"
            )
            raise BenchmarkConfigurationError(message)

    def _validate_plan(self) -> None:
        declared = families(self)
        if not declared:
            message = "calibration lists no families"
            raise BenchmarkConfigurationError(message)
        if "reads_per_write" in self.section("active") and any(
            (family.probe_workload or _FAMILY_WORKLOADS[kind]) == "active"
            for family in declared
            for kind, _, _ in family.cells
        ):
            message = "reads_per_write needs read-only probes for active families"
            raise BenchmarkConfigurationError(message)
        calibration = self.section("calibration")
        for name in ("probe_windows", "validation_repetitions", "rate_attempts"):
            if not _positive(calibration[name]):
                message = f"calibration {name} must be a positive integer"
                raise BenchmarkConfigurationError(message)
        if "gate" not in self.raw:
            try:
                floor = self.section("inference")["lag_event_floor"]
            except KeyError:
                floor = None
            if not _positive(floor):
                message = "descriptive analysis needs a positive lag_event_floor"
                raise BenchmarkConfigurationError(message)
        phases = cast("dict[str, JsonDict]", self.section("phases"))
        for phase, settings in phases.items():
            if "blocks" in settings and not _positive(settings["blocks"]):
                message = f"{phase} phase blocks must be a positive integer"
                raise BenchmarkConfigurationError(message)

    def _validate_workload(self) -> None:
        active = self.section("active")
        if "updates" in active and "reads_per_write" in active:
            message = "active windows set both updates and reads_per_write"
            raise BenchmarkConfigurationError(message)
        if "write_keys" in active and active["write_keys"] != "hot":
            message = "active write_keys supports only the hot set"
            raise BenchmarkConfigurationError(message)
        if "reads_per_write" in active and not _positive(active["reads_per_write"]):
            message = "active reads_per_write must be a positive integer"
            raise BenchmarkConfigurationError(message)
        if self.hot_keys is not None and not _positive(self.hot_keys):
            message = "hot_keys must be a positive integer"
            raise BenchmarkConfigurationError(message)
        if self.hot_keys is not None and "write_keys" not in active:
            message = "hot_keys needs active write_keys so writes target the hot set"
            raise BenchmarkConfigurationError(message)
        if self.key_assignment not in _KEY_ASSIGNMENTS:
            message = "key_assignment must be partitioned or shared"
            raise BenchmarkConfigurationError(message)
        paths = self.paths
        if not paths or not set(paths) <= set(_V4_PATHS):
            message = "paths must list direct, independent or shared"
            raise BenchmarkConfigurationError(message)
        if len(set(paths)) != len(paths):
            message = "paths must not repeat a path"
            raise BenchmarkConfigurationError(message)

    @classmethod
    def load(cls, path: Path) -> Registration:
        content = path.read_bytes()
        return cls(json.loads(content), sha256(content).hexdigest())

    def section(self, name: str) -> JsonDict:
        return cast("JsonDict", self.raw[name])

    def number(self, *keys: str) -> float:
        value: object = self.raw
        for key in keys:
            value = cast("JsonDict", value)[key]
        assert isinstance(value, (int, float))
        return value

    @property
    def frozen(self) -> bool:
        return self.raw["status"] == "frozen"

    @property
    def paths(self) -> tuple[PathKind, ...]:
        try:
            paths = self.raw["paths"]
        except KeyError:
            return _V4_PATHS
        return tuple(cast("list[PathKind]", paths))

    @property
    def categories(self) -> PositiveInt:
        try:
            return cast("int", self.raw["categories"])
        except KeyError:
            return cast("int", self.profile("find16")["categories"])

    @property
    def hot_keys(self) -> PositiveInt | None:
        try:
            return cast("int", self.raw["hot_keys"])
        except KeyError:
            return None

    @property
    def key_assignment(self) -> KeyAssignment:
        try:
            return cast("KeyAssignment", self.raw["key_assignment"])
        except KeyError:
            return "partitioned"

    def profile(self, name: str) -> JsonDict:
        return cast("JsonDict", self.section("profiles")[name])

    def limits(self) -> TransportLimits:
        return TransportLimits(**cast("dict[str, float]", self.section("transport")))  # type: ignore[arg-type]

    def rate(self, family: str) -> PositiveFloat:
        rates = cast("JsonDict", self.section("frozen")["rates"])
        value = rates[family]
        if value is None:
            message = f"registration has no frozen {family} rate"
            raise BenchmarkConfigurationError(message)
        assert isinstance(value, (int, float))
        return value

    def window(self, kind: str) -> PositiveFloat:
        windows = cast("JsonDict", self.section("frozen")["window_seconds"])
        value = windows[kind]
        if value is None:
            message = f"registration has no frozen {kind} window"
            raise BenchmarkConfigurationError(message)
        assert isinstance(value, (int, float))
        return value


@dataclass(frozen=True, slots=True)
class CalibrationFamily:
    name: str
    cells: tuple[CellSpec, ...]
    probe_workload: Workload | None


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


def _cell_specs(entries: object, owner: str) -> tuple[CellSpec, ...]:
    if not isinstance(entries, list) or not entries:
        message = f"{owner} lists no cells"
        raise BenchmarkConfigurationError(message)
    specs: list[CellSpec] = []
    for entry in cast("list[object]", entries):
        match entry:
            case [str(kind), str(model), int(workers)] if (
                kind in _FAMILY_WORKLOADS
                and model in _MODELS
                and not isinstance(workers, bool)
                and workers > 0
            ):
                specs.append((kind, cast("Model", model), workers))
            case _:
                message = f"{owner} has a malformed cell {entry!r}"
                raise BenchmarkConfigurationError(message)
    if len(set(specs)) != len(specs):
        message = f"{owner} repeats a cell"
        raise BenchmarkConfigurationError(message)
    return tuple(specs)


def _v4_counts(kind: str) -> Callable[[JsonDict], tuple[CellSpec, ...]]:
    def cells(settings: JsonDict) -> tuple[CellSpec, ...]:
        counts = cast("list[int]", settings["worker_counts"])
        return tuple(
            (kind, model, workers) for workers in counts for model in _V4_MODELS
        )

    return cells


def _v4_active(settings: JsonDict) -> tuple[CellSpec, ...]:
    mixed = cast("list[int]", settings["mixed"])
    return (*_v4_counts("active")(settings), ("active", "mixed", sum(mixed)))


def _v4_sensitivity(settings: JsonDict) -> tuple[CellSpec, ...]:
    workers = cast("int", settings["workers"])
    profiles = cast("list[str]", settings["profiles"])
    return tuple(
        (profile, model, workers) for profile in profiles for model in _V4_MODELS
    )


def _v4_smoke(_settings: JsonDict) -> tuple[CellSpec, ...]:
    return (("hot", "sync", 2), ("active", "mixed", 2), ("cold", "async", 2))


_V4_PHASE_CELLS: dict[str, Callable[[JsonDict], tuple[CellSpec, ...]]] = {
    "smoke": _v4_smoke,
    "screening": _v4_counts("hot"),
    "confirmation": _v4_counts("hot"),
    "capacity": _v4_counts("hot"),
    "active": _v4_active,
    "cold": _v4_counts("cold"),
    "sensitivity": _v4_sensitivity,
}


def _phase_settings(registration: Registration, phase: str) -> JsonDict:
    try:
        return cast("JsonDict", registration.section("phases")[phase])
    except KeyError:
        message = f"registration has no {phase} phase"
        raise BenchmarkConfigurationError(message) from None


def phase_blocks(registration: Registration, phase: str) -> PositiveInt:
    try:
        return cast("int", _phase_settings(registration, phase)["blocks"])
    except KeyError:
        message = f"{phase} phase has no blocks"
        raise BenchmarkConfigurationError(message) from None


def phase_cells(registration: Registration, phase: str) -> tuple[CellSpec, ...]:
    settings = _phase_settings(registration, phase)
    try:
        entries = settings["cells"]
    except KeyError:
        try:
            derive = _V4_PHASE_CELLS[phase]
        except KeyError:
            message = f"{phase} phase lists no cells"
            raise BenchmarkConfigurationError(message) from None
        return derive(settings)
    return _cell_specs(entries, f"{phase} phase")


def families(registration: Registration) -> tuple[CalibrationFamily, ...]:
    declared = cast("JsonDict", registration.section("calibration")["families"])
    return tuple(starmap(_family, declared.items()))


def _family(name: str, value: object) -> CalibrationFamily:
    owner = f"{name} family"
    match value:
        case list():
            return CalibrationFamily(name, _cell_specs(value, owner), None)
        case {"cells": entries, "probe_workload": "hot" | "active" | "cold" as probe}:
            return CalibrationFamily(name, _cell_specs(entries, owner), probe)
    message = f"{owner} is malformed"  # pytriage: TR5 (EM102 needs a variable)
    raise BenchmarkConfigurationError(message)


def family_cells(registration: Registration, family: str) -> tuple[CellSpec, ...]:
    return next(item.cells for item in families(registration) if item.name == family)


def rate_family(registration: Registration, kind: str) -> str:
    for family in families(registration):
        if any(cell[0] == kind for cell in family.cells):
            return family.name
    message = f"no calibration family covers {kind} cells"
    raise BenchmarkConfigurationError(message)


def window_kind(kind: str) -> str:
    return "sensitivity" if kind in {"large", "find16"} else kind


def _profile_for(kind: str) -> str:
    return kind if kind in {"large", "find16"} else "primary"


def required_samples(registration: Registration) -> PositiveInt:
    floor = registration.number("calibration", "sample_floor")
    completion = registration.number("calibration", "minimum_completion")
    return math.ceil(floor / completion)


def measurement_environment(environment: JsonDict) -> JsonDict:
    return {
        key: value
        for key, value in environment.items()
        if key != "available_memory_bytes"
    }


def validation_failure(record: JsonDict, registration: Registration) -> str | None:
    offered = cast("int", record["offered"])
    in_window = cast("int", record["completed_in_window"])
    if in_window < registration.number("calibration", "minimum_completion") * offered:
        return "completed less than the registered fraction inside the window"
    workers = cast("list[JsonDict]", record["workers_measured"])
    loops = [cast("JsonDict", worker["loop"]) for worker in workers]
    if any(
        cast("int", loop["errors"]) or cast("int", loop["overflow"]) for loop in loops
    ):
        return "errors or request-queue overflow"
    backlog = 2 * cast("int", registration.raw["concurrency_per_worker"])
    if any(cast("int", loop["outstanding_at_end"]) > backlog for loop in loops):
        return "growing backlog at the end of the application window"
    if record["workload"] == "cold":
        if record["completed"] != record["identities"]:
            return "cold window did not complete every identity"
        outcomes = [cast("dict[str, int]", worker["outcomes"]) for worker in workers]
        if record["path"] != "direct" and (
            sum(outcome["misses"] for outcome in outcomes) != record["completed"]
            or any(outcome["hits"] or outcome["bypasses"] for outcome in outcomes)
        ):
            return "cold window recorded hits or bypasses instead of misses"
        return None
    floor = cast("int", registration.number("calibration", "sample_floor"))
    populations = cast("JsonDict", record["populations"])
    names = ("sync", "async") if record["model"] == "mixed" else ("request",)
    if any(
        cast("int", cast("JsonDict", populations[name])["sample_count"]) < floor
        for name in names
    ):
        return "percentile population below the registered sample floor"
    return None


def write_count(registration: Registration, cell: Cell) -> NonNegativeInt:
    active = registration.section("active")
    try:
        reads_per_write = cast("int", active["reads_per_write"])
    except KeyError:
        return cast("int", active["updates"])
    if cell.rate is None:
        message = "reads_per_write needs an open-loop rate"
        raise BenchmarkConfigurationError(message)
    return math.floor(cell.rate * cell.window_seconds / reads_per_write)


def window_for(
    registration: Registration,
    kind: str,
    rate: PositiveFloat,
    populations: PositiveInt,
) -> PositiveFloat:
    nominal = registration.number("nominal_seconds", kind)
    needed = required_samples(registration) * populations / rate
    return max(nominal, math.ceil(needed))


def family_probe_cells(
    registration: Registration, family: CalibrationFamily
) -> tuple[Cell, ...]:
    calibration = registration.section("calibration")
    windows = cast("int", calibration["probe_windows"])
    seconds = registration.number("calibration", "probe_seconds")
    warmup = registration.number("warmup_seconds")
    concurrency = cast("int", registration.raw["concurrency_per_worker"])
    return tuple(
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
        for kind, model, workers in family.cells
        for workload in (family.probe_workload or _FAMILY_WORKLOADS[kind],)
        for window in range(windows)
        for path in _ordered(BASELINES, window)
    )


def probe_cells(registration: Registration) -> tuple[Cell, ...]:
    return tuple(
        cell
        for family in families(registration)
        for cell in family_probe_cells(registration, family)
    )


def validation_cells(
    registration: Registration,
    family: str,
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
        identities / rate if identities is not None else durations[window_kind(kind)]
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
    kinds = dict.fromkeys(
        window_kind(kind)
        for family in families(registration)
        for kind, _model, _workers in family.cells
        if _FAMILY_WORKLOADS[kind] != "cold"
    )
    return {kind: registration.window(kind) for kind in kinds}


def comparison_cells(
    registration: Registration,
    phase: str,
    paths: tuple[PathKind, ...] | None = None,
) -> tuple[Cell, ...]:
    blocks = phase_blocks(registration, phase)
    matrix = phase_cells(registration, phase)
    durations = frozen_durations(registration)
    rates = {
        kind: registration.rate(rate_family(registration, kind))
        for kind in dict.fromkeys(kind for kind, _model, _workers in matrix)
    }
    return tuple(
        fixed_cell(
            registration,
            phase=phase,
            block=block,
            kind=kind,
            model=model,
            workers=workers,
            path=path,
            rate=rates[kind],
            durations=durations,
        )
        for block in range(blocks)
        for kind, model, workers in matrix
        for path in path_order(block, paths or registration.paths)
    )


def capacity_cells(
    registration: Registration, paths: tuple[PathKind, ...] | None = None
) -> tuple[Cell, ...]:
    settings = _phase_settings(registration, "capacity")
    return tuple(
        Cell(
            phase="capacity",
            block=window,
            workload=_FAMILY_WORKLOADS[kind],
            profile=_profile_for(kind),
            model=model,
            workers=workers,
            path=path,
            loop="closed",
            concurrency=concurrency,
            window_seconds=registration.number("phases", "capacity", "window_seconds"),
            warmup_seconds=registration.number("warmup_seconds"),
        )
        for window in range(cast("int", settings["windows"]))
        for kind, model, workers in phase_cells(registration, "capacity")
        for concurrency in cast("list[int]", settings["concurrency"])
        for path in path_order(window, paths or registration.paths)
    )


def smoke_cells(registration: Registration) -> tuple[Cell, ...]:
    settings = _phase_settings(registration, "smoke")
    return tuple(
        Cell(
            phase="smoke",
            block=0,
            workload=_FAMILY_WORKLOADS[kind],
            profile="smoke",
            model=model,
            workers=workers,
            path=path,
            loop="open",
            concurrency=cast("int", registration.raw["concurrency_per_worker"]),
            window_seconds=cast("float", settings["window_seconds"]),
            warmup_seconds=0
            if kind == "cold"
            else cast("float", settings["warmup_seconds"]),
            rate=cast("float", settings["rate"]),
            identities=cast("int", settings["identities"]) if kind == "cold" else None,
        )
        for kind, model, workers in phase_cells(registration, "smoke")
        for path in registration.paths
    )
