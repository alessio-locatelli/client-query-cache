from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, cast

import psutil

from benchmarks.mongodb_image import MONGODB_IMAGE
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.shared_cache.protocol import (
    BASELINES,
    Registration,
    capacity_cells,
    comparison_cells,
    families,
    family_cells,
    family_probe_cells,
    probe_cells,
    required_samples,
    smoke_cells,
    validation_cells,
    validation_failure,
    window_for,
    window_kind,
)
from benchmarks.stream_cost.shared_cache.window import run_window
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache._types import JsonDict, PositiveFloat

if TYPE_CHECKING:
    from collections.abc import Iterable

    from benchmarks.stream_cost.shared_cache.protocol import Cell, PathKind

_CONFIG = Path("reports/shared-worker-cache/v4/config.json")
_CEILING_FAMILY = "primary"


def environment(registration: Registration) -> JsonDict:
    git = shutil.which("git")
    if git is None:
        raise BenchmarkSetupError("git is required to record the benchmark revision")
    revision = subprocess.check_output([git, "rev-parse", "HEAD"], text=True).strip()  # noqa: S603
    dirty = bool(
        subprocess.check_output(  # noqa: S603
            [git, "status", "--porcelain", "--", "benchmarks", "src", "reports"],
            text=True,
        ).strip()
    )
    memory = psutil.virtual_memory()
    return {
        "revision": revision,
        "dirty_tree": dirty,
        "configuration_sha256": registration.digest,
        "python": sys.version.split()[0],
        "pymongo": version("pymongo"),
        "psutil": version("psutil"),
        "testcontainers": version("testcontainers"),
        "platform": platform.platform(),
        "processor": processor_name(Path("/proc/cpuinfo").read_text(encoding="utf-8")),
        "logical_cpus": os.cpu_count(),
        "available_memory_bytes": memory.available,
        "total_memory_bytes": memory.total,
        "mongodb_image": MONGODB_IMAGE,
        "topology": registration.section("topology"),
        "start_method": registration.raw["start_method"],
        "client_options": registration.section("client_options"),
        "transport": "unix-domain socket, length-prefixed BSON frames",
    }


def processor_name(cpuinfo: str) -> str:
    for line in cpuinfo.splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor()


class Recorder:
    __slots__ = ("_resumed", "output", "report")

    def __init__(
        self,
        output: Path,
        phase: str,
        registration: Registration,
        resumed: list[JsonDict],
    ) -> None:
        self.output = output
        self._resumed = resumed
        self.report: JsonDict = {
            "phase": phase,
            "environment": environment(registration),
            "cells": [],
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        self.flush()

    def flush(self) -> None:
        self.output.write_text(
            json.dumps(self.report, indent=1) + "\n", encoding="utf-8"
        )

    def run(
        self,
        replica: IsolatedReplicaSet,
        registration: Registration,
        cells: Iterable[Cell],
    ) -> list[JsonDict]:
        records: list[JsonDict] = []
        planned = tuple(cells)
        for ordinal, cell in enumerate(planned, 1):
            print(
                f"{ordinal}/{len(planned)} {cell.phase} b{cell.block} "
                f"{cell.workload} {cell.profile} {cell.model} "
                f"{cell.workers}x{cell.concurrency} {cell.path}",
                flush=True,
            )
            record = self._measure(replica, registration, cell)
            records.append(record)
            cast("list[JsonDict]", self.report["cells"]).append(record)
            self.flush()
        return records

    def _measure(
        self, replica: IsolatedReplicaSet, registration: Registration, cell: Cell
    ) -> JsonDict:
        if self._resumed and all(
            self._resumed[0][key] == value for key, value in asdict(cell).items()
        ):
            return self._resumed.pop(0)
        try:
            return run_window(replica, registration, cell)
        except BenchmarkSetupError as error:
            return {**asdict(cell), "healthy": False, "failure": str(error)}


def resumed_cells(
    path: Path, phase: str, registration: Registration, exploratory: str | None
) -> list[JsonDict]:
    report = json.loads(path.read_text(encoding="utf-8"))
    current = environment(registration)
    previous = cast("JsonDict", report["environment"])
    try:
        limit = report["exploratory"]
    except KeyError:
        limit = None
    if (
        report["phase"] != phase
        or limit != exploratory
        or any(
            previous[key] != current[key]
            for key in ("revision", "dirty_tree", "configuration_sha256")
        )
    ):
        message = (
            "resumed report has another phase, cell limit, revision or registration"
        )
        raise BenchmarkSetupError(message)
    return cast("list[JsonDict]", report["cells"])


def reused_probes(path: Path) -> list[JsonDict]:
    report = json.loads(path.read_text(encoding="utf-8"))
    probes = [
        record
        for record in cast("list[JsonDict]", report["cells"])
        if record["phase"] == "probe" and record["healthy"]
    ]
    if report["phase"] != "calibration" or not probes:
        message = "reused probes need a calibration report with healthy probes"
        raise BenchmarkSetupError(message)
    return probes


def throughput(record: JsonDict) -> float:
    workers = cast("list[JsonDict]", record["workers_measured"])
    elapsed = max(
        cast("float", cast("JsonDict", worker["loop"])["elapsed"]) for worker in workers
    )
    return cast("int", record["completed"]) / elapsed


def select_rate(
    registration: Registration,
    family: str,
    probes: list[JsonDict],
    ceiling: float | None,
) -> int:
    rates = [throughput(record) for record in probes]
    cap = registration.number("calibration", "caps", family)
    if ceiling is not None:
        cap = min(cap, ceiling)
    return math.floor(
        min(min(rates) * registration.number("calibration", "selected_fraction"), cap)
    )


def family_durations(
    registration: Registration, family: str, rate: PositiveFloat
) -> dict[str, PositiveFloat]:
    models: dict[str, set[str]] = {}
    for kind, model, _workers in family_cells(registration, family):
        models.setdefault(window_kind(kind), set()).add(model)
    return {
        kind: registration.number("calibration", "cold_probe_identities") / rate
        if kind == "cold"
        else window_for(registration, kind, rate, 2 if "mixed" in kind_models else 1)
        for kind, kind_models in models.items()
    }


def calibrate(
    replica: IsolatedReplicaSet, registration: Registration, recorder: Recorder
) -> JsonDict:
    probes = recorder.run(replica, registration, probe_cells(registration))
    failed = [record for record in probes if not record["healthy"]]
    if failed:
        return {"outcome": "inconclusive", "reason": "probe window failed"}
    selections: JsonDict = {}
    rates: dict[str, int] = {}
    durations: dict[str, PositiveFloat] = {}
    ordered = sorted(
        families(registration), key=lambda family: family.name != _CEILING_FAMILY
    )
    for family in ordered:
        members = {
            (cell.workload, cell.profile, cell.model, cell.workers)
            for cell in family_probe_cells(registration, family)
        }
        family_probes = [
            record
            for record in probes
            if (
                record["workload"],
                record["profile"],
                record["model"],
                record["workers"],
            )
            in members
        ]
        try:
            ceiling: int | None = rates[_CEILING_FAMILY]
        except KeyError:
            ceiling = None
        rate = select_rate(registration, family.name, family_probes, ceiling)
        attempts: list[JsonDict] = []
        for _attempt in range(int(registration.number("calibration", "rate_attempts"))):
            proposed = family_durations(registration, family.name, rate)
            cap = registration.number("calibration", "window_cap_seconds")
            if any(seconds > cap for seconds in proposed.values()):
                attempts.append(
                    {"rate": rate, "durations": proposed, "failure": "window cap"}
                )
                break
            cells = validation_cells(registration, family.name, rate, proposed)
            records = recorder.run(replica, registration, cells)
            if any(not record["healthy"] for record in records):
                selections[family.name] = {"attempts": attempts}
                return {
                    "outcome": "inconclusive",
                    "reason": f"{family.name} validation window failed setup",
                    "selections": selections,
                }
            failures = [
                {"cell": asdict(cell), "failure": failure}
                for cell, record in zip(cells, records, strict=True)
                if (failure := validation_failure(record, registration)) is not None
            ]
            attempts.append({"rate": rate, "durations": proposed, "failures": failures})
            if not failures:
                rates[family.name] = rate
                durations.update(proposed)
                break
            rate //= 2
        selections[family.name] = {
            "probe_throughputs": [throughput(record) for record in family_probes],
            "attempts": attempts,
        }
        if family.name not in rates:
            return {
                "outcome": "inconclusive",
                "reason": f"no sustainable {family.name} rate",
                "selections": selections,
            }
    validated: JsonDict = {
        "outcome": "validated",
        "rates": rates,
        "window_seconds": {
            kind: seconds for kind, seconds in durations.items() if kind != "cold"
        },
    }
    try:
        validated["cold_seconds"] = durations["cold"]
    except KeyError:
        pass
    return {
        **validated,
        "required_samples": required_samples(registration),
        "selections": selections,
    }


def freeze(registration_path: Path, calibration_path: Path) -> None:
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    validated = cast("JsonDict", calibration["calibration"])
    if validated["outcome"] != "validated":
        message = "only validated baseline calibration can be frozen"
        raise BenchmarkSetupError(message)
    text = registration_path.read_text(encoding="utf-8")
    summary: JsonDict = {}
    try:
        summary["cold_seconds"] = validated["cold_seconds"]
    except KeyError:
        pass
    frozen = {
        "rates": validated["rates"],
        "window_seconds": validated["window_seconds"],
        "calibration_summary": summary,
    }
    start = text.index('  "frozen": {')
    end = text.index('\n  "nominal_seconds"', start)
    block = json.dumps(frozen, indent=2).replace("\n", "\n  ")
    text = text[:start] + f'  "frozen": {block},' + text[end:]
    registration_path.write_text(
        text.replace('"status": "pending-calibration"', '"status": "frozen"', 1),
        encoding="utf-8",
    )


def planned(
    registration: Registration, phase: str, paths: tuple[PathKind, ...]
) -> tuple[Cell, ...]:
    if phase == "capacity":
        return capacity_cells(registration, paths)
    return comparison_cells(registration, phase, paths)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Measure a registered multi-worker cache benchmark."
    )
    parser.add_argument("--config", type=Path, default=_CONFIG)
    parser.add_argument("--output", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--smoke", action="store_true", help="Shortened instrumentation check."
    )
    mode.add_argument("--calibrate-baselines", action="store_true")
    mode.add_argument(
        "--freeze", type=Path, help="Freeze a validated calibration report."
    )
    mode.add_argument("--phase", help="A comparison phase listed in the registration.")
    parser.add_argument("--baselines-only", action="store_true")
    parser.add_argument(
        "--only",
        metavar="MODEL:WORKERS",
        help="Exploratory rerun of one model and worker count; not decision evidence.",
    )
    reuse = parser.add_mutually_exclusive_group()
    reuse.add_argument(
        "--resume", type=Path, help="Reuse completed windows from an earlier report."
    )
    reuse.add_argument(
        "--reuse-probes",
        type=Path,
        help="Reuse healthy closed-loop probes registered as unaffected.",
    )
    arguments = parser.parse_args(argv)
    if arguments.freeze is not None:
        freeze(arguments.config, arguments.freeze)
        return
    if arguments.output is None:
        parser.error("--output is required")
    if arguments.output.exists():
        parser.error("output already exists; choose a new path to preserve evidence")
    registration = Registration.load(arguments.config)
    phase = (
        "smoke"
        if arguments.smoke
        else "calibration"
        if arguments.calibrate_baselines
        else arguments.phase
    )
    if phase is None:
        parser.error("choose --smoke, --calibrate-baselines, --freeze or --phase")
    cells: tuple[Cell, ...] = ()
    exploratory: str | None = None
    if phase not in {"smoke", "calibration"}:
        if not registration.frozen:
            parser.error("candidate phases require a frozen registration")
        cells = planned(
            registration,
            phase,
            BASELINES if arguments.baselines_only else registration.paths,
        )
        if arguments.only is not None:
            model, workers = arguments.only.split(":")
            exploratory = f"cells limited to {arguments.only}"
            cells = tuple(
                cell
                for cell in cells
                if cell.model == model and cell.workers == int(workers)
            )
    recorder = Recorder(
        arguments.output,
        phase,
        registration,
        resumed_cells(arguments.resume, phase, registration, exploratory)
        if arguments.resume is not None
        else reused_probes(arguments.reuse_probes)
        if arguments.reuse_probes is not None
        else [],
    )
    if exploratory is not None:
        recorder.report["exploratory"] = exploratory
    limits = ResourceLimits(**registration.section("topology"))  # type: ignore[arg-type]
    with IsolatedReplicaSet(limits) as replica:
        if phase == "smoke":
            records = recorder.run(replica, registration, smoke_cells(registration))
            failures = [record for record in records if not record["healthy"]]
            if failures:
                raise BenchmarkSetupError(str(failures[0]["failure"]))
            return
        if phase == "calibration":
            recorder.report["calibration"] = calibrate(replica, registration, recorder)
            recorder.flush()
            return
        recorder.run(replica, registration, cells)


if __name__ == "__main__":
    main()
