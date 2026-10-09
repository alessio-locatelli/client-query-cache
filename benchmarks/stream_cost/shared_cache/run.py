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

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.shared_cache.protocol import (
    BASELINES,
    Registration,
    capacity_cells,
    cell_kind,
    comparison_cells,
    family_cells,
    probe_cells,
    required_samples,
    smoke_cells,
    validation_cells,
    window_for,
)
from benchmarks.stream_cost.shared_cache.window import run_window
from benchmarks.stream_cost.topology import (
    MONGODB_IMAGE,
    IsolatedReplicaSet,
    ResourceLimits,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from benchmarks.stream_cost.shared_cache.protocol import Cell, Family, PathKind
    from client_query_cache._types import PositiveFloat

type Payload = dict[str, object]

_CONFIG = Path("reports/shared-worker-cache/v4/config.json")
_PHASES = ("screening", "confirmation", "capacity", "active", "cold", "sensitivity")
_CAPS: dict[Family, str] = {
    "primary": "primary",
    "cold": "cold",
    "sensitivity": "sensitivity",
}


def environment(registration: Registration) -> Payload:
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
        resumed: list[Payload],
    ) -> None:
        self.output = output
        self._resumed = resumed
        self.report: Payload = {
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
    ) -> list[Payload]:
        records: list[Payload] = []
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
            cast("list[Payload]", self.report["cells"]).append(record)
            self.flush()
        return records

    def _measure(
        self, replica: IsolatedReplicaSet, registration: Registration, cell: Cell
    ) -> Payload:
        if self._resumed and all(
            self._resumed[0][key] == value for key, value in asdict(cell).items()
        ):
            return self._resumed.pop(0)
        try:
            return run_window(replica, registration, cell)
        except BenchmarkSetupError as error:
            return {**asdict(cell), "healthy": False, "failure": str(error)}


def resumed_cells(path: Path, phase: str, registration: Registration) -> list[Payload]:
    report = json.loads(path.read_text(encoding="utf-8"))
    current = environment(registration)
    previous = cast("Payload", report["environment"])
    if report["phase"] != phase or any(
        previous[key] != current[key]
        for key in ("revision", "dirty_tree", "configuration_sha256")
    ):
        message = "resumed report has another phase, revision or registration"
        raise BenchmarkSetupError(message)
    return cast("list[Payload]", report["cells"])


def reused_probes(path: Path) -> list[Payload]:
    report = json.loads(path.read_text(encoding="utf-8"))
    probes = [
        record
        for record in cast("list[Payload]", report["cells"])
        if record["phase"] == "probe" and record["healthy"]
    ]
    if report["phase"] != "calibration" or not probes:
        message = "reused probes need a calibration report with healthy probes"
        raise BenchmarkSetupError(message)
    return probes


def throughput(record: Payload) -> float:
    workers = cast("list[Payload]", record["workers_measured"])
    elapsed = max(
        cast("float", cast("Payload", worker["loop"])["elapsed"]) for worker in workers
    )
    return cast("int", record["completed"]) / elapsed


def validation_failure(record: Payload, registration: Registration) -> str | None:
    offered = cast("int", record["offered"])
    in_window = cast("int", record["completed_in_window"])
    if in_window < registration.number("calibration", "minimum_completion") * offered:
        return "completed less than the registered fraction inside the window"
    workers = cast("list[Payload]", record["workers_measured"])
    loops = [cast("Payload", worker["loop"]) for worker in workers]
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
        return None
    floor = cast("int", registration.number("calibration", "sample_floor"))
    populations = cast("Payload", record["populations"])
    names = ("sync", "async") if record["model"] == "mixed" else ("request",)
    if any(
        cast("int", cast("Payload", populations[name])["sample_count"]) < floor
        for name in names
    ):
        return "percentile population below the registered sample floor"
    return None


def select_rate(
    registration: Registration,
    family: Family,
    probes: list[Payload],
    ceiling: float | None,
) -> int:
    rates = [throughput(record) for record in probes]
    cap = registration.number("calibration", "caps", _CAPS[family])
    if ceiling is not None:
        cap = min(cap, ceiling)
    return math.floor(
        min(min(rates) * registration.number("calibration", "selected_fraction"), cap)
    )


def family_durations(
    registration: Registration, family: Family, rate: PositiveFloat
) -> dict[str, PositiveFloat]:
    if family == "primary":
        return {
            "hot": window_for(registration, "hot", rate, "sync"),
            "active": window_for(registration, "active", rate, "mixed"),
        }
    if family == "sensitivity":
        return {"sensitivity": window_for(registration, "sensitivity", rate, "sync")}
    identities = registration.number("calibration", "cold_probe_identities")
    return {"cold": identities / rate}


def calibrate(
    replica: IsolatedReplicaSet, registration: Registration, recorder: Recorder
) -> Payload:
    probes = recorder.run(replica, registration, probe_cells(registration))
    failed = [record for record in probes if not record["healthy"]]
    if failed:
        return {"outcome": "inconclusive", "reason": "probe window failed"}
    selections: Payload = {}
    rates: dict[str, int] = {}
    durations: dict[str, PositiveFloat] = {}
    for family in ("primary", "cold", "sensitivity"):
        members = {
            (kind, model, workers)
            for kind, model, workers in family_cells(registration, family)
        }
        family_probes = [
            record
            for record in probes
            if (
                cell_kind(str(record["workload"]), str(record["profile"])),
                record["model"],
                record["workers"],
            )
            in members
        ]
        rate = select_rate(
            registration,
            family,
            family_probes,
            rates["primary"] if family != "primary" else None,
        )
        attempts: list[Payload] = []
        for _attempt in range(int(registration.number("calibration", "rate_attempts"))):
            proposed = family_durations(registration, family, rate)
            cap = registration.number("calibration", "window_cap_seconds")
            if any(seconds > cap for seconds in proposed.values()):
                attempts.append(
                    {"rate": rate, "durations": proposed, "failure": "window cap"}
                )
                break
            cells = validation_cells(
                registration, family, rate, {**_placeholders(proposed), **proposed}
            )
            records = recorder.run(replica, registration, cells)
            if any(not record["healthy"] for record in records):
                selections[family] = {"attempts": attempts}
                return {
                    "outcome": "inconclusive",
                    "reason": f"{family} validation window failed setup",
                    "selections": selections,
                }
            failures = [
                {"cell": asdict(cell), "failure": failure}
                for cell, record in zip(cells, records, strict=True)
                if (failure := validation_failure(record, registration)) is not None
            ]
            attempts.append({"rate": rate, "durations": proposed, "failures": failures})
            if not failures:
                rates[family] = rate
                durations.update(proposed)
                break
            rate //= 2
        selections[family] = {
            "probe_throughputs": [throughput(record) for record in family_probes],
            "attempts": attempts,
        }
        if family not in rates:
            return {
                "outcome": "inconclusive",
                "reason": f"no sustainable {family} rate",
                "selections": selections,
            }
    return {
        "outcome": "validated",
        "rates": rates,
        "window_seconds": {
            "hot": durations["hot"],
            "active": durations["active"],
            "sensitivity": durations["sensitivity"],
        },
        "cold_seconds": durations["cold"],
        "required_samples": required_samples(registration),
        "selections": selections,
    }


def _placeholders(proposed: dict[str, PositiveFloat]) -> dict[str, PositiveFloat]:
    return {
        kind: 1.0 for kind in ("hot", "active", "sensitivity") if kind not in proposed
    }


def freeze(registration_path: Path, calibration_path: Path) -> None:
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    validated = cast("Payload", calibration["calibration"])
    if validated["outcome"] != "validated":
        message = "only validated baseline calibration can be frozen"
        raise BenchmarkSetupError(message)
    configuration = json.loads(registration_path.read_text(encoding="utf-8"))
    configuration["status"] = "frozen"
    configuration["frozen"] = {
        "rates": validated["rates"],
        "window_seconds": validated["window_seconds"],
        "calibration_summary": {
            "revision": cast("Payload", calibration["environment"])["revision"],
            "draft_sha256": cast("Payload", calibration["environment"])[
                "configuration_sha256"
            ],
            "cold_seconds": validated["cold_seconds"],
        },
    }
    registration_path.write_text(
        json.dumps(configuration, indent=2) + "\n", encoding="utf-8"
    )


def planned(
    registration: Registration, phase: str, paths: tuple[PathKind, ...]
) -> tuple[Cell, ...]:
    if phase == "capacity":
        return capacity_cells(registration)
    return comparison_cells(registration, phase, paths)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Measure shared worker cache feasibility."
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
    mode.add_argument("--phase", choices=_PHASES)
    parser.add_argument("--baselines-only", action="store_true")
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
    if phase not in {"smoke", "calibration"} and not registration.frozen:
        parser.error("candidate phases require a frozen registration")
    recorder = Recorder(
        arguments.output,
        phase,
        registration,
        resumed_cells(arguments.resume, phase, registration)
        if arguments.resume is not None
        else reused_probes(arguments.reuse_probes)
        if arguments.reuse_probes is not None
        else [],
    )
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
        paths = BASELINES if arguments.baselines_only else None
        recorder.run(
            replica,
            registration,
            planned(registration, phase, paths or ("direct", "independent", "shared")),
        )


if __name__ == "__main__":
    main()
