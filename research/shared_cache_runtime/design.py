"""Build research schedules without importing the experiment execution driver."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, replace
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, cast

from benchmarks.stream_cost.shared_cache.protocol import (
    Registration,
    capacity_cells,
    comparison_cells,
)
from client_query_cache._types import (
    JsonDict,
    NonNegativeFloat,
    PositiveFloat,
    PositiveInt,
)

if TYPE_CHECKING:
    from benchmarks.stream_cost.shared_cache.protocol import Cell, Model, PathKind

CONFIG = Path("reports/shared-worker-cache/v8/config.json")
PROGRAM = Path("research/shared_cache_runtime/experiment.py")
RESEARCH_PATHS = (
    "research/shared_cache_runtime",
    "scripts/analyze_shared_cache_runtime.py",
)


def design_cells(
    registration: Registration, design: JsonDict
) -> tuple[tuple[str, Registration, Cell], ...]:
    @cache
    def with_updates(updates: PositiveInt) -> Registration:
        raw = copy.deepcopy(registration.raw)
        cast("JsonDict", raw["active"])["updates"] = updates
        encoded = json.dumps(raw, sort_keys=True).encode()
        return Registration(raw, hashlib.sha256(encoded).hexdigest())

    selected: list[tuple[str, Registration, Cell]] = []
    for group in cast("list[JsonDict]", design["groups"]):
        phase = cast("str", group["phase"])
        planned = (
            capacity_cells(registration)
            if phase == "capacity"
            else comparison_cells(registration, phase)
        )
        variants = cast("list[JsonDict]", group["variants"])
        models = cast("list[Model]", group["models"])
        workers = cast("list[PositiveInt]", group["workers"])
        paths = cast("list[PathKind]", group["paths"])
        blocks = cast("PositiveInt", group["blocks"])
        for cell in planned:
            if (
                cell.model not in models
                or cell.workers not in workers
                or cell.path not in paths
                or cell.block >= blocks
            ):
                continue
            if phase == "capacity" and cell.concurrency != 16:
                continue
            offset = cell.block % len(variants)
            ordered = variants[offset:] + variants[:offset]
            for variant in ordered:
                duration = cell.window_seconds
                trial_registration = registration
                if phase == "active" and "updates" in variant:
                    duration = cast("PositiveFloat", variant["window_seconds"])
                    trial_registration = with_updates(
                        cast("PositiveInt", variant["updates"])
                    )
                selected.append(
                    (
                        cast("str", variant["label"]),
                        trial_registration,
                        replace(
                            cell,
                            warmup_seconds=cast(
                                "NonNegativeFloat", variant["warmup_seconds"]
                            ),
                            window_seconds=duration,
                        ),
                    )
                )
    return tuple(selected)


def planned_rows(cells: tuple[tuple[str, Registration, Cell], ...]) -> list[JsonDict]:
    return [
        {"condition": label, "configuration_sha256": trial.digest, **asdict(cell)}
        for label, trial, cell in cells
    ]
