"""Collect exploratory timing and ordered observations using the existing harness."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import threading
import time
from contextlib import ExitStack
from dataclasses import asdict, replace
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.shared_cache import window, worker, workload
from benchmarks.stream_cost.shared_cache.protocol import (
    Registration,
    capacity_cells,
    comparison_cells,
)
from benchmarks.stream_cost.shared_cache.run import environment
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache._types import (  # noqa: PLC2701 - Runtime constrained aliases are canonical for research too.
    JsonDict,
    NonNegativeFloat,
    PositiveInt,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from multiprocessing.connection import Connection

    from benchmarks.stream_cost.shared_cache.protocol import Cell
    from benchmarks.stream_cost.shared_cache.worker import WorkerSpec

CONFIG = Path("reports/shared-worker-cache/v8/config.json")


class TimedLatencies(list[NonNegativeFloat]):  # noqa: FURB189 - The harness and JSON encoder require a native list.
    __slots__ = ("_lock", "times")

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.times: list[NonNegativeFloat] = []

    def append(self, latency: NonNegativeFloat) -> None:
        with self._lock:
            self.times.append(time.monotonic())
            super().append(latency)


def traced_worker(connection: Connection, spec: WorkerSpec) -> None:
    original_sample = worker._sample  # noqa: SLF001 - Preserve the harness sample and add ordered trace metadata.
    original_loop = workload.LoopResult

    def loop_factory() -> workload.LoopResult:
        loop = original_loop()
        loop.latencies = TimedLatencies()
        return loop

    def sample(*args: object, **kwargs: object) -> JsonDict:
        measured = original_sample(*args, **kwargs)  # type: ignore[arg-type]
        loop = cast("workload.LoopResult", kwargs["loop"])
        assert isinstance(loop.latencies, TimedLatencies)
        measured["completion_times"] = loop.latencies.times
        measured["latencies"] = list(loop.latencies)
        return measured

    with (
        patch.object(workload, "LoopResult", loop_factory),
        patch.object(worker, "_sample", sample),
    ):
        worker.worker_main(connection, spec)


class Observations:
    __slots__ = ("boundaries", "latencies", "memory", "origin")

    def __init__(self) -> None:
        self.origin = time.monotonic()
        self.boundaries: list[JsonDict] = []
        self.latencies: list[JsonDict] = []
        self.memory: list[JsonDict] = []

    def mark(self, name: str, **fields: object) -> None:
        self.boundaries.append(
            {
                "name": name,
                "seconds": time.monotonic() - self.origin,
                **fields,
            }
        )

    def wrap(self, name: str, function: Callable[..., object]) -> Callable[..., object]:
        def timed(*args: object, **kwargs: object) -> object:
            self.mark(name + ":start")
            returned = function(*args, **kwargs)
            self.mark(name + ":end")
            return returned

        return timed

    def measure(
        self,
        replica: IsolatedReplicaSet,
        registration: Registration,
        cell: Cell,
        *,
        trace: bool = True,
    ) -> JsonDict:
        original_collect = window.ProcessGroup.collect
        original_pool = window._pooled  # noqa: SLF001 - Capture raw samples before the existing pool discards them.
        original_summary = window.GroupMemorySampler.summary
        original_wait = window._wait  # noqa: SLF001 - Record the harness's first scheduled measurement boundary.
        first_wait = True

        def collect(
            group: window.ProcessGroup, kind: str, deadline: NonNegativeFloat
        ) -> object:
            self.mark("collect-" + kind + ":start")
            samples = original_collect(group, kind, deadline)
            self.mark("collect-" + kind + ":end")
            return samples

        def pooled(samples: list[JsonDict], model: str | None) -> JsonDict:
            if model is None and trace:
                self.latencies = [
                    {
                        "index": sample["index"],
                        "model": sample["model"],
                        "latencies": sample["latencies"],
                        "completion_times": [
                            timestamp - self.origin
                            for timestamp in cast(
                                "list[NonNegativeFloat]", sample["completion_times"]
                            )
                        ],
                    }
                    for sample in samples
                ]
            return original_pool(samples, model)

        def memory_summary(sampler: window.GroupMemorySampler) -> JsonDict:
            self.memory = cast("list[JsonDict]", sampler.samples)
            return original_summary(sampler)

        def wait(deadline: NonNegativeFloat) -> None:
            nonlocal first_wait
            if first_wait:
                self.mark("measurement-scheduled", start=deadline + 0.05 - self.origin)
                first_wait = False
            original_wait(deadline)

        with ExitStack() as hooks:
            if trace:
                hooks.enter_context(patch.object(window, "worker_main", traced_worker))
            hooks.enter_context(
                patch.object(
                    window,
                    "seed_catalogue",
                    self.wrap("prepare", window.seed_catalogue),
                )
            )
            hooks.enter_context(patch.object(window.ProcessGroup, "collect", collect))
            hooks.enter_context(
                patch.object(
                    window.ProcessGroup,
                    "stop",
                    self.wrap("process-stop", window.ProcessGroup.stop),
                )
            )
            hooks.enter_context(
                patch.object(
                    window.ProcessGroup,
                    "__exit__",
                    self.wrap("process-context-exit", window.ProcessGroup.__exit__),
                )
            )
            hooks.enter_context(
                patch.object(
                    window,
                    "_verify_ready",
                    self.wrap("verify-ready", window._verify_ready),  # noqa: SLF001 - Time the harness residency check.
                )
            )
            hooks.enter_context(
                patch.object(
                    window,
                    "_drain_owner",
                    self.wrap("drain-owner", window._drain_owner),  # noqa: SLF001 - Time the harness invalidation drain.
                )
            )
            hooks.enter_context(patch.object(window, "_pooled", pooled))
            hooks.enter_context(patch.object(window, "_wait", wait))
            hooks.enter_context(
                patch.object(window.GroupMemorySampler, "summary", memory_summary)
            )
            try:
                record = window.run_window(replica, registration, cell)
            except BenchmarkSetupError as error:
                record = {**asdict(cell), "healthy": False, "failure": str(error)}
        self.mark("window:end")
        return {
            **record,
            "timing": self.boundaries,
            "traces": self.latencies,
            "memory_samples": self.memory,
            "wall_seconds": time.monotonic() - self.origin,
        }


def selected_cells(registration: Registration, mode: str) -> tuple[Cell, ...]:
    planned = comparison_cells(registration, "confirmation")
    blocks: PositiveInt = 1 if mode == "check" else 6
    seconds = 3 if mode == "check" else 30
    return tuple(
        replace(
            cell, window_seconds=seconds, warmup_seconds=1 if mode == "check" else 0
        )
        for cell in planned
        if cell.model == "async" and cell.workers == 8 and cell.block < blocks
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
        for cell in planned:
            if (
                cell.model not in group["models"]
                or cell.workers not in group["workers"]
                or cell.path not in group["paths"]
                or cell.block >= group["blocks"]
            ):
                continue
            if phase == "capacity" and cell.concurrency != 16:
                continue
            offset = cell.block % len(variants)
            ordered = variants[offset:] + variants[:offset]
            for variant in ordered:
                changed: dict[str, object] = {
                    "warmup_seconds": variant["warmup_seconds"]
                }
                trial_registration = registration
                if phase == "active" and "updates" in variant:
                    changed["window_seconds"] = variant["window_seconds"]
                    trial_registration = with_updates(
                        cast("PositiveInt", variant["updates"])
                    )
                selected.append(
                    (
                        cast("str", variant["label"]),
                        trial_registration,
                        replace(cell, **changed),
                    )
                )  # type: ignore[arg-type]
    return tuple(selected)


def planned_rows(cells: tuple[tuple[str, Registration, Cell], ...]) -> list[JsonDict]:
    return [
        {"condition": label, "configuration_sha256": trial.digest, **asdict(cell)}
        for label, trial, cell in cells
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mode", choices=("check", "discovery"))
    mode.add_argument("--design", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("output already exists")
    registration = Registration.load(CONFIG)
    if arguments.design is None:
        cells = tuple(
            (arguments.mode, registration, cell)
            for cell in selected_cells(registration, arguments.mode)
        )
        design: JsonDict = {"trace": True}
    else:
        design = json.loads(arguments.design.read_text(encoding="utf-8"))
        cells = design_cells(registration, design)
    report: JsonDict = {
        "label": "protocol investigation; excluded from candidate acceptance",
        "environment": environment(registration),
        "program_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "design": design,
        "planned": planned_rows(cells),
        "cells": [],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    topology = registration.section("topology")
    with IsolatedReplicaSet(ResourceLimits(**topology)) as replica:  # type: ignore[arg-type]
        report["container_startup_seconds"] = time.monotonic() - started
        for label, trial, cell in cells:
            observed = Observations().measure(
                replica, trial, cell, trace=bool(design["trace"])
            )
            observed["condition"] = label
            observed["configuration_sha256"] = trial.digest
            cast("list[JsonDict]", report["cells"]).append(observed)
            arguments.output.write_text(json.dumps(report) + "\n", encoding="utf-8")
        report["container_shutdown_started_seconds"] = time.monotonic() - started
    report["wall_seconds"] = time.monotonic() - started
    arguments.output.write_text(json.dumps(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
