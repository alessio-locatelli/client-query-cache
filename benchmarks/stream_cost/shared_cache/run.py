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
from email.parser import Parser
from hashlib import sha256
from importlib.metadata import distribution, version
from pathlib import Path
from typing import TYPE_CHECKING, cast

import psutil
from pymongo.errors import PyMongoError

from benchmarks.mongodb_image import MONGODB_IMAGE
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.proxy import PROXY_TCP_NODELAY
from benchmarks.stream_cost.shared_cache.fault_recovery import (
    run_recovery_fault_window,
)
from benchmarks.stream_cost.shared_cache.fault_timeline import (
    classify_requests,
    detect_recovery,
    validate_request_counts,
)
from benchmarks.stream_cost.shared_cache.protocol import (
    BASELINES,
    CalibrationFamily,
    Cell,
    RecoveryFaultCell,
    Registration,
    capacity_cells,
    comparison_cells,
    families,
    family_cells,
    family_probe_cells,
    fault_cells,
    fault_recovery_cells,
    is_worker_fault_registration,
    measurement_environment,
    required_samples,
    smoke_cells,
    throughput,
    validation_cells,
    validation_failure,
    window_for,
    window_kind,
)
from benchmarks.stream_cost.shared_cache.window import run_window
from benchmarks.stream_cost.topology import (
    IsolatedReplicaSet,
    ReplicaSetTopology,
    ResourceLimits,
)
from client_query_cache import _shared_index
from client_query_cache._types import (
    JsonDict,
    NonEmptyStr,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from benchmarks.stream_cost.shared_cache.protocol import PathKind

_CONFIG = Path("reports/shared-worker-cache/v4/config.json")
_CEILING_FAMILY = "primary"
_NATIVE_DISTRIBUTION = "client-query-cache"
_CARGO_LOCK = Path("native/shared-index/Cargo.lock")
_RUSTC_MARKER = b"rustc version "


def environment(
    registration: Registration, *, extra_source_paths: tuple[NonEmptyStr, ...] = ()
) -> JsonDict:
    git = shutil.which("git")
    if git is None:
        raise BenchmarkSetupError("git is required to record the benchmark revision")
    revision = subprocess.check_output([git, "rev-parse", "HEAD"], text=True).strip()  # noqa: S603 - Use the resolved git executable with fixed arguments and no shell.
    dirty = bool(
        subprocess.check_output(  # noqa: S603 - Use the resolved git executable with fixed arguments and no shell.
            [
                git,
                "status",
                "--porcelain",
                "--",
                "benchmarks",
                "native",
                "src",
                "reports",
                *extra_source_paths,
            ],
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
        "proxy_tcp_nodelay": PROXY_TCP_NODELAY,
        "proxy_io": "native duplex relay",
        "native_extension": native_extension(),
    }


def native_extension() -> JsonDict:
    installed = distribution(_NATIVE_DISTRIBUTION)
    binary = Path(_shared_index.__file__).read_bytes()
    start = binary.index(_RUSTC_MARKER)
    wheel = Parser().parsestr(cast("str", installed.read_text("WHEEL")))
    return {
        "version": version(_NATIVE_DISTRIBUTION),
        "binary_sha256": sha256(binary).hexdigest(),
        "rustc": binary[start : binary.index(b"\0", start)].decode(),
        "generator": wheel["Generator"],
        "tag": wheel["Tag"],
        "cargo_lock_sha256": sha256(_CARGO_LOCK.read_bytes()).hexdigest(),
    }


def processor_name(cpuinfo: str) -> str:
    for line in cpuinfo.splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor()


class Recorder:
    __slots__ = ("_resumed", "output", "report", "timeline_validation")

    def __init__(
        self,
        output: Path,
        phase: str,
        registration: Registration,
        resumed: list[JsonDict],
        *,
        timeline_validation: bool = False,
    ) -> None:
        self.output = output
        self._resumed = resumed
        self.timeline_validation = timeline_validation
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
        replica: IsolatedReplicaSet | ReplicaSetTopology,
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
        self,
        replica: IsolatedReplicaSet | ReplicaSetTopology,
        registration: Registration,
        cell: Cell,
    ) -> JsonDict:
        if self._resumed and all(
            self._resumed[0][key] == value for key, value in asdict(cell).items()
        ):
            return self._resumed.pop(0)
        try:
            if isinstance(cell, RecoveryFaultCell):
                return run_recovery_fault_window(replica, registration, cell)
            timeline_enabled = self.timeline_validation and cell.phase == "validation"
            if timeline_enabled:
                return run_window(
                    replica,
                    registration,
                    cell,
                    timeline_enabled=True,
                    timeline_cadence_seconds=(
                        registration.number(
                            "fault_recovery", "timeline_cadence_seconds"
                        )
                        if is_worker_fault_registration(registration)
                        else 0.25
                    ),
                )
            return run_window(replica, registration, cell)
        except BenchmarkSetupError as error:
            return {**asdict(cell), "healthy": False, "failure": str(error)}
        except PyMongoError as error:
            return {
                **asdict(cell),
                "healthy": False,
                "failure": f"MongoDB fault trial setup failed: {error}",
            }
        except TimeoutError as error:
            return {
                **asdict(cell),
                "healthy": False,
                "failure": f"fault trial timed out: {error}",
            }

    def run_recovery_faults(
        self, registration: Registration, cells: tuple[RecoveryFaultCell, ...]
    ) -> list[JsonDict]:
        limits = ResourceLimits(**registration.section("topology"))  # type: ignore[arg-type]
        records: list[JsonDict | None] = [None] * len(cells)
        for topology in ("single-member", "three-member"):
            indexes = [
                index for index, cell in enumerate(cells) if cell.topology == topology
            ]
            if not indexes:
                continue
            manager = (
                IsolatedReplicaSet(limits)
                if topology == "single-member"
                else ReplicaSetTopology()
            )
            try:
                self._run_recovery_topology(
                    manager, indexes, registration, cells, records
                )
            except BenchmarkSetupError as error:
                for index in indexes:
                    if records[index] is None:
                        records[index] = {
                            **asdict(cells[index]),
                            "healthy": False,
                            "failure": str(error),
                        }
                self.report["cells"] = [
                    record for record in records if record is not None
                ]
                self.flush()
        return [cast("JsonDict", record) for record in records]

    def _run_recovery_topology(
        self,
        manager: IsolatedReplicaSet | ReplicaSetTopology,
        indexes: list[int],
        registration: Registration,
        cells: tuple[RecoveryFaultCell, ...],
        records: list[JsonDict | None],
    ) -> None:
        with manager as replica:
            for index in indexes:
                cell = cells[index]
                print(
                    f"{index + 1}/{len(cells)} {cell.phase} "
                    f"b{cell.block} {cell.fault_case} {cell.path} "
                    f"{cell.topology}",
                    flush=True,
                )
                records[index] = self._measure(replica, registration, cell)
                self.report["cells"] = [
                    record for record in records if record is not None
                ]
                self.flush()


def resumed_cells(
    path: Path, phase: str, registration: Registration, exploratory: str | None
) -> list[JsonDict]:
    report = json.loads(path.read_text(encoding="utf-8"))
    try:
        limit = report["exploratory"]
    except KeyError:
        limit = None
    if (
        report["phase"] != phase
        or limit != exploratory
        or measurement_environment(cast("JsonDict", report["environment"]))
        != measurement_environment(environment(registration))
    ):
        message = "resumed report has another phase, cell limit or environment"
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


def _run_calibration_cells(
    replica: IsolatedReplicaSet | None,
    registration: Registration,
    recorder: Recorder,
    family: CalibrationFamily,
    cells: tuple[Cell, ...],
) -> list[JsonDict]:
    if family.topology == "single-member" and replica is not None:
        return recorder.run(replica, registration, cells)
    if family.topology == "three-member":
        with ReplicaSetTopology() as three_member:
            return recorder.run(three_member, registration, cells)
    limits = ResourceLimits(**registration.section("topology"))  # type: ignore[arg-type]
    with IsolatedReplicaSet(limits) as single_member:
        return recorder.run(single_member, registration, cells)


def _null_fault_check(records: list[JsonDict], registration: Registration) -> JsonDict:
    checks: list[JsonDict] = []
    for record in records:
        cell = record
        try:
            timelines = cast("list[JsonDict]", record["fault_timeline"])
        except KeyError:
            raise BenchmarkSetupError(
                "calibration validation record lacks the opted-in fault timeline"
            ) from None
        rate = cast("PositiveFloat", record["rate"])
        window_end = cast("PositiveFloat", record["window_seconds"])
        offered = round(rate * window_end)
        requests: list[JsonDict] = []
        for timeline in timelines:
            index = cast("int", timeline["index"])
            events = cast("list[JsonDict]", timeline["events"])
            workers = cast("PositiveInt", record["workers"])
            ordinals = tuple(range(index, offered, workers))
            requests.extend(
                classify_requests(
                    ordinals,
                    events,
                    rate=rate,
                    killed_at=None,
                )
            )
        validate_request_counts(requests, offered)
        injection = min(5.0, window_end / 2)
        criterion = registration.recovery_criterion()
        recovery = detect_recovery(
            requests,
            injection_offset=injection,
            deadline=injection + criterion.bucket_seconds,
            window_end=window_end,
            before_seconds=injection,
            bucket_seconds=criterion.bucket_seconds,
            minimum_completion_fraction=criterion.minimum_completion_fraction,
            request_p99_multiple=criterion.request_p99_multiple,
            backlog_grace_p99_multiple=criterion.backlog_grace_p99_multiple,
        )
        first_bucket = (
            math.ceil(injection / criterion.bucket_seconds) * criterion.bucket_seconds
        )
        passed = (
            recovery["recovered"] is True
            and recovery["recovery_offset"] == first_bucket
        )
        checks.append(
            {
                "phase": cell["phase"],
                "block": cell["block"],
                "path": cell["path"],
                "topology": _topology(cell),
                "injection_offset_seconds": injection,
                "pass": passed,
                "recovery": recovery,
            }
        )
    return {
        "outcome": "passed" if all(check["pass"] for check in checks) else "failed",
        "checks": checks,
    }


def _topology(cell: JsonDict) -> str:
    try:
        return cast("str", cell["topology"])
    except KeyError:
        return "single-member"


def _validated_calibration_result(
    registration: Registration,
    rates: dict[str, PositiveInt],
    durations: dict[str, PositiveFloat],
    selections: JsonDict,
    validation_records: list[JsonDict],
) -> JsonDict:
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
    calibration: JsonDict = {
        **validated,
        "required_samples": required_samples(registration),
        "selections": selections,
    }
    if validation_records and any(
        "fault_timeline" in record for record in validation_records
    ):
        calibration["null_fault_check"] = _null_fault_check(
            validation_records, registration
        )
        if cast("JsonDict", calibration["null_fault_check"])["outcome"] != "passed":
            calibration["outcome"] = "inconclusive"
            calibration["reason"] = (
                "fault-free calibration validation failed the recovery detector"
            )
    return calibration


def calibrate(
    replica: IsolatedReplicaSet | None,
    registration: Registration,
    recorder: Recorder,
) -> JsonDict:
    ordered = sorted(
        families(registration), key=lambda family: family.name != _CEILING_FAMILY
    )
    probes: list[JsonDict] = []
    for family in ordered:
        probes.extend(
            _run_calibration_cells(
                replica,
                registration,
                recorder,
                family,
                family_probe_cells(registration, family),
            )
        )
    failed = [record for record in probes if not record["healthy"]]
    if failed:
        return {"outcome": "inconclusive", "reason": "probe window failed"}
    selections: JsonDict = {}
    rates: dict[str, PositiveInt] = {}
    durations: dict[str, PositiveFloat] = {}
    validation_records: list[JsonDict] = []
    for family in ordered:
        members = {
            (cell.workload, cell.profile, cell.model, cell.workers, family.topology)
            for cell in family_probe_cells(registration, family)
        }
        family_probes = [
            record for record in probes if _probe_member(record) in members
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
            records = _run_calibration_cells(
                replica, registration, recorder, family, cells
            )
            validation_records.extend(records)
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
    return _validated_calibration_result(
        registration, rates, durations, selections, validation_records
    )


def _probe_member(record: JsonDict) -> tuple[str, str, str, PositiveInt, str]:
    try:
        topology = cast("str", record["topology"])
    except KeyError:
        topology = "single-member"
    return (
        cast("str", record["workload"]),
        cast("str", record["profile"]),
        cast("str", record["model"]),
        cast("PositiveInt", record["workers"]),
        topology,
    )


def _observer_calibration(
    registration: Registration, report_path: Path
) -> tuple[PositiveFloat, PositiveFloat]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    environment = cast("JsonDict", report["environment"])
    if environment["configuration_sha256"] != registration.digest:
        raise BenchmarkSetupError(
            "observer calibration report has another registration digest"
        )
    calibration = cast("JsonDict", report["calibration"])
    if calibration["outcome"] != "validated":
        raise BenchmarkSetupError("observer overhead needs validated calibration")
    matching_families = [
        family.name
        for family in families(registration)
        if family.topology == "single-member"
        and family.probe_workload in {None, "hot"}
        and any(
            model == "async"
            and workers == 4
            and (family.probe_workload == "hot" or window_kind(kind) == "hot")
            for kind, model, workers in family.cells
        )
    ]
    if len(matching_families) != 1:
        raise BenchmarkSetupError(
            "observer calibration needs one hot four-worker asyncio family"
        )
    rates = cast("JsonDict", calibration["rates"])
    rate = cast("PositiveFloat", rates[matching_families[0]])
    durations = cast("JsonDict", calibration["window_seconds"])
    family = next(
        item for item in families(registration) if item.name == matching_families[0]
    )
    duration_kind = window_kind(family.cells[0][0])
    window_seconds = cast("PositiveFloat", durations[duration_kind])
    return rate, window_seconds


def _observer_metrics(record: JsonDict) -> JsonDict:
    population = cast("JsonDict", record["populations"])
    workers = cast("list[JsonDict]", record["workers_measured"])
    completed = sum(
        cast("int", cast("JsonDict", worker["loop"])["completed"]) for worker in workers
    )
    if completed == 0:
        raise BenchmarkSetupError("observer window completed no requests")
    request = cast("JsonDict", population["request"])
    cpu_seconds = sum(cast("float", worker["cpu_seconds"]) for worker in workers)
    return {
        "request_p99_seconds": request["p99_seconds"],
        "worker_cpu_seconds_per_request": cpu_seconds / completed,
        "completed": completed,
    }


def _observer_attempt(
    replica: IsolatedReplicaSet,
    registration: Registration,
    rate: PositiveFloat,
    window_seconds: PositiveFloat,
    cadence: PositiveFloat,
) -> JsonDict:
    cells: list[JsonDict] = []
    timeline_records: list[JsonDict] = []
    paired: dict[tuple[str, NonNegativeInt], dict[bool, JsonDict]] = {}
    for repetition in range(3):
        for path_index, path in enumerate(("direct", "independent")):
            order = (
                (True, False) if (repetition + path_index) % 2 == 0 else (False, True)
            )
            for instrumented in order:
                cell = Cell(
                    phase="fault-observer-overhead",
                    block=repetition,
                    workload="hot",
                    profile="primary",
                    model="async",
                    workers=4,
                    path=cast("PathKind", path),
                    loop="open",
                    concurrency=cast("int", registration.raw["concurrency_per_worker"]),
                    window_seconds=window_seconds,
                    warmup_seconds=0,
                    rate=rate,
                )
                record = run_window(
                    replica,
                    registration,
                    cell,
                    timeline_enabled=instrumented,
                    timeline_cadence_seconds=cadence,
                )
                metrics = _observer_metrics(record)
                if instrumented:
                    timeline_records.append(record)
                cells.append(
                    {
                        **asdict(cell),
                        "instrumented": instrumented,
                        **metrics,
                    }
                )
                key = (path, repetition)
                try:
                    paired[key][instrumented] = metrics
                except KeyError:
                    paired[key] = {instrumented: metrics}

    comparisons: list[JsonDict] = []
    for (path, repetition), measurements in paired.items():
        baseline_metrics = measurements[False]
        instrumented_metrics = measurements[True]
        baseline_p99 = cast("float", baseline_metrics["request_p99_seconds"])
        instrumented_p99 = cast("float", instrumented_metrics["request_p99_seconds"])
        baseline_cpu = cast("float", baseline_metrics["worker_cpu_seconds_per_request"])
        instrumented_cpu = cast(
            "float", instrumented_metrics["worker_cpu_seconds_per_request"]
        )
        p99_delta = instrumented_p99 - baseline_p99
        cpu_delta = instrumented_cpu - baseline_cpu
        p99_limit = max(0.1 * baseline_p99, 0.0002)
        p99_passed = abs(p99_delta) <= p99_limit
        cpu_passed = abs(cpu_delta) <= 0.1 * baseline_cpu
        comparisons.append(
            {
                "path": path,
                "repetition": repetition,
                "request_p99_baseline_seconds": baseline_p99,
                "request_p99_instrumented_seconds": instrumented_p99,
                "request_p99_delta_seconds": p99_delta,
                "request_p99_tolerance_seconds": p99_limit,
                "worker_cpu_baseline_seconds_per_request": baseline_cpu,
                "worker_cpu_instrumented_seconds_per_request": instrumented_cpu,
                "worker_cpu_delta_seconds_per_request": cpu_delta,
                "request_p99_passed": p99_passed,
                "worker_cpu_passed": cpu_passed,
                "passed": p99_passed and cpu_passed,
            }
        )
    null_fault_check = _null_fault_check(timeline_records, registration)
    return {
        "cadence_seconds": cadence,
        "passed": all(cast("bool", comparison["passed"]) for comparison in comparisons)
        and null_fault_check["outcome"] == "passed",
        "null_fault_check": null_fault_check,
        "comparisons": comparisons,
        "cells": cells,
    }


def fault_observer_overhead(
    replica: IsolatedReplicaSet,
    registration: Registration,
    calibration_path: Path,
) -> JsonDict:
    rate, window_seconds = _observer_calibration(registration, calibration_path)
    attempts = [
        _observer_attempt(
            replica,
            registration,
            rate,
            window_seconds,
            0.25,
        )
    ]
    if not cast("bool", attempts[0]["passed"]):
        attempts.append(
            _observer_attempt(
                replica,
                registration,
                rate,
                window_seconds,
                1.0,
            )
        )
    outcome = "passed" if attempts[-1]["passed"] else "inconclusive"
    return {
        "outcome": outcome,
        "rate": rate,
        "window_seconds": window_seconds,
        "selected_cadence_seconds": attempts[-1]["cadence_seconds"],
        "attempts": attempts,
    }


def freeze(
    registration_path: Path,
    calibration_path: Path,
    fault_observer_path: Path | None = None,
) -> None:
    calibration = cast(
        "JsonDict", json.loads(calibration_path.read_text(encoding="utf-8"))
    )
    validated = cast("JsonDict", calibration["calibration"])
    if validated["outcome"] != "validated":
        message = "only validated baseline calibration can be frozen"
        raise BenchmarkSetupError(message)
    registration = Registration.load(registration_path)
    selected_timeline_cadence: PositiveFloat | None = None
    if is_worker_fault_registration(registration):
        environment = cast("JsonDict", calibration["environment"])
        if environment["configuration_sha256"] != registration.digest:
            raise BenchmarkSetupError(
                "calibration report has another registration digest"
            )
        try:
            null_fault = cast("JsonDict", validated["null_fault_check"])
        except KeyError:
            raise BenchmarkSetupError(
                "worker fault calibration lacks the null-fault check"
            ) from None
        if null_fault["outcome"] != "passed":
            raise BenchmarkSetupError("null-fault check must pass before freezing")
        if fault_observer_path is None:
            raise BenchmarkSetupError(
                "worker fault registration needs an observer-overhead report"
            )
        observer_report = cast(
            "JsonDict", json.loads(fault_observer_path.read_text(encoding="utf-8"))
        )
        observer_environment = cast("JsonDict", observer_report["environment"])
        if observer_environment["configuration_sha256"] != registration.digest:
            raise BenchmarkSetupError(
                "observer overhead report has another registration digest"
            )
        overhead = cast("JsonDict", observer_report["fault_observer_overhead"])
        if overhead["outcome"] != "passed":
            raise BenchmarkSetupError(
                "observer overhead must pass before freezing worker fault evidence"
            )
        selected_timeline_cadence = cast(
            "PositiveFloat", overhead["selected_cadence_seconds"]
        )
        if selected_timeline_cadence not in {0.25, 1.0}:
            raise BenchmarkSetupError(
                "observer overhead selected an unregistered timeline cadence"
            )
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
    if selected_timeline_cadence is not None:
        summary["fault_observer_cadence_seconds"] = selected_timeline_cadence
        registration_data = cast("JsonDict", json.loads(text))
        registration_data["status"] = "frozen"
        fault_recovery = cast("JsonDict", registration_data["fault_recovery"])
        fault_recovery["timeline_cadence_seconds"] = selected_timeline_cadence
        registration_data["frozen"] = frozen
        registration_path.write_text(
            json.dumps(registration_data, indent=2) + "\n", encoding="utf-8"
        )
        return
    start = text.index('  "frozen": {')
    end = text.index('\n  "nominal_seconds"', start)
    block = json.dumps(frozen, indent=2).replace("\n", "\n  ")
    text = text[:start] + f'  "frozen": {block},' + text[end:]
    registration_path.write_text(
        text.replace('"status": "pending-calibration"', '"status": "frozen"', 1),
        encoding="utf-8",
    )


def planned(
    registration: Registration,
    phase: str,
    paths: tuple[PathKind, ...],
    *,
    smoke: bool = False,
) -> tuple[Cell, ...]:
    if phase == "fault":
        if is_worker_fault_registration(registration):
            return fault_recovery_cells(registration, paths, smoke=smoke)
        return fault_cells(registration, paths)
    if phase == "capacity":
        return capacity_cells(registration, paths)
    return comparison_cells(registration, phase, paths)


def _fault_smoke_failure(records: list[JsonDict]) -> str | None:
    for index, record in enumerate(records, start=1):
        if record["healthy"] is not True:
            try:
                failure = record["failure"]
            except KeyError:
                failure = "cell was marked unhealthy"
            return f"cell {index}: {failure}"
        injection = cast("JsonDict", record["injection"])
        if injection["injected"] is not True:
            return f"cell {index}: fault was not injected"
        requests = cast("JsonDict", record["requests"])
        counts = cast("dict[str, int]", requests["counts"])
        if sum(counts.values()) != requests["offered"]:
            return f"cell {index}: request counts do not match the offered schedule"
        recovery = cast("JsonDict", record["recovery"])
        if recovery["recovered"] is not True or record["outcome"] != "recovered":
            return f"cell {index}: recovery criterion was not met"
        correctness = cast("JsonDict", record["correctness"])
        probed = correctness["probed"]
        if (
            correctness["available"] is not True
            or correctness["passed"] is not True
            or not isinstance(probed, int)
            or isinstance(probed, bool)
            or probed <= 0
        ):
            return f"cell {index}: post-recovery correctness check did not pass"
    return None


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
    parser.add_argument(
        "--fault-observer-report",
        type=Path,
        help="Observer-overhead report required to freeze worker fault registrations.",
    )
    mode.add_argument(
        "--fault-observer-overhead",
        action="store_true",
        help="Measure the fault timeline observer overhead.",
    )
    parser.add_argument(
        "--phase", help="A comparison phase listed in the registration."
    )
    parser.add_argument("--baselines-only", action="store_true")
    parser.add_argument(
        "--calibration-report",
        type=Path,
        help="Validated calibration report used by --fault-observer-overhead.",
    )
    parser.add_argument(
        "--fault-calibration-timeline",
        action="store_true",
        help="Opt calibration validation windows into fault timeline instrumentation.",
    )
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
        freeze(
            arguments.config,
            arguments.freeze,
            arguments.fault_observer_report,
        )
        return
    if arguments.fault_observer_report is not None:
        parser.error("--fault-observer-report requires --freeze")
    if arguments.output is None:
        parser.error("--output is required")
    if arguments.output.exists():
        parser.error("output already exists; choose a new path to preserve evidence")
    registration = Registration.load(arguments.config)
    if arguments.phase is not None and (
        arguments.calibrate_baselines or arguments.fault_observer_overhead
    ):
        parser.error("--phase cannot be combined with calibration modes")
    if arguments.smoke and arguments.phase is not None:
        if not (
            arguments.phase == "fault"
            and is_worker_fault_registration(registration)
            and not arguments.calibrate_baselines
            and not arguments.fault_observer_overhead
        ):
            parser.error(
                "--smoke may be combined only with this registration's fault phase"
            )
        phase = "fault-smoke"
    elif arguments.smoke:
        phase = "smoke"
    elif arguments.calibrate_baselines:
        phase = "calibration"
    elif arguments.fault_observer_overhead:
        phase = "fault-observer-overhead"
    else:
        phase = arguments.phase
    if phase is None:
        parser.error("choose --smoke, --calibrate-baselines, --freeze or --phase")
    if arguments.fault_calibration_timeline and phase != "calibration":
        parser.error("--fault-calibration-timeline requires --calibrate-baselines")
    if arguments.fault_observer_overhead and arguments.calibration_report is None:
        parser.error("--fault-observer-overhead requires --calibration-report")
    if (
        arguments.calibration_report is not None
        and not arguments.fault_observer_overhead
    ):
        parser.error("--calibration-report requires --fault-observer-overhead")
    cells: tuple[Cell, ...] = ()
    exploratory: str | None = None
    if phase not in {"smoke", "fault-smoke", "calibration", "fault-observer-overhead"}:
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
    elif phase == "fault-smoke":
        cells = fault_recovery_cells(registration, smoke=True)
    recorder = Recorder(
        arguments.output,
        phase,
        registration,
        resumed_cells(arguments.resume, phase, registration, exploratory)
        if arguments.resume is not None
        else reused_probes(arguments.reuse_probes)
        if arguments.reuse_probes is not None
        else [],
        timeline_validation=arguments.fault_calibration_timeline,
    )
    if exploratory is not None:
        recorder.report["exploratory"] = exploratory
    if phase == "fault-smoke":
        recorder.report["smoke"] = True
        recorder.report["evidence"] = False
        recorder.report["cells"] = []
        recorder.flush()
    if phase in {"fault", "fault-smoke"} and is_worker_fault_registration(registration):
        records = recorder.run_recovery_faults(
            registration, cast("tuple[RecoveryFaultCell, ...]", cells)
        )
        if phase == "fault-smoke":
            if len(records) != len(cells):
                raise BenchmarkSetupError(
                    "fault smoke did not record every applicable cell"
                )
            failure = _fault_smoke_failure(records)
            if failure is not None:
                message = f"fault smoke failed: {failure}"
                raise BenchmarkSetupError(message)
        return
    if phase == "calibration":
        calibration = calibrate(None, registration, recorder)
        recorder.report["calibration"] = calibration
        recorder.flush()
        if calibration["outcome"] != "validated":
            reason = cast("str", calibration["reason"])
            message = f"calibration was not validated: {reason}"
            raise BenchmarkSetupError(message)
        return
    limits = ResourceLimits(**registration.section("topology"))  # type: ignore[arg-type]
    with IsolatedReplicaSet(limits) as replica:
        if phase == "smoke":
            records = recorder.run(replica, registration, smoke_cells(registration))
            failures = [record for record in records if not record["healthy"]]
            if failures:
                raise BenchmarkSetupError(str(failures[0]["failure"]))
            return
        if phase == "fault-observer-overhead":
            assert arguments.calibration_report is not None
            overhead = fault_observer_overhead(
                replica, registration, arguments.calibration_report
            )
            recorder.report["fault_observer_overhead"] = overhead
            recorder.flush()
            if overhead["outcome"] == "inconclusive":
                raise BenchmarkSetupError(
                    "fault timeline observer overhead remained above the "
                    "registered limits"
                )
            return
        recorder.run(replica, registration, cells)


if __name__ == "__main__":
    main()
