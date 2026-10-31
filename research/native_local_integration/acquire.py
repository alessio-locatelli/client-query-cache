"""Run one registered revision/block from its installed interpreter."""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from importlib.metadata import version
from itertools import product
from pathlib import Path
from typing import TYPE_CHECKING

from pymongo import MongoClient

from benchmarks.implementation import implementation
from benchmarks.public_shared_cache import (
    _run_window,  # noqa: PLC2701 - Extend the existing public collector with the registered block order.
    _seed,  # noqa: PLC2701 - Keep identical workload construction in CLI and acquisition.
)
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache._types import BsonDict, NonNegativeInt, PositiveInt  # noqa: PLC2701 - Use the library constraint aliases for acquisition counts.
from research.native_local_integration.contention import run_cell
from research.native_local_integration.registration import (
    REGISTRATIONS,
    build,
    digest,
    verify_installation,
)

if TYPE_CHECKING:
    from typing import Literal


@dataclass(frozen=True, slots=True)
class Shape:
    method: str
    hot_keys: PositiveInt
    documents: PositiveInt
    hot_samples: PositiveInt
    cold_samples: PositiveInt


SHAPES = (
    Shape("identity", 1024, 1, 16384, 1024),
    Shape("find_one", 1024, 1, 16384, 1024),
    Shape("find", 128, 16, 2048, 256),
    Shape("small-entries", 64000, 1, 16384, 8192),
    Shape("large-keys", 64000, 1, 16384, 8192),
)


@dataclass(frozen=True, slots=True)
class Cell:
    role: Literal["target", "control"]
    method: str
    workload: Literal["hot", "cold"]
    path: Literal["independent", "shared"]
    hot_keys: PositiveInt
    documents: PositiveInt
    document_bytes: PositiveInt
    samples: PositiveInt
    budget_bytes: PositiveInt | None = None
    max_entry_bytes: PositiveInt | None = None


CANDIDATES: dict[str, tuple[Cell, ...]] = {
    "capture": (
        Cell(
            "target",
            "find",
            "cold",
            "independent",
            1,
            4000,
            1024,
            32,
            256 * 1024 * 1024,
            8 * 1024 * 1024,
        ),
        Cell("control", "find", "hot", "independent", 128, 16, 128, 2048),
    ),
    "preparation": (
        Cell("target", "find_one_in", "hot", "independent", 1024, 1, 4096, 4096),
        Cell("control", "identity", "hot", "independent", 1024, 1, 4096, 4096),
        Cell("control", "identity", "hot", "shared", 1024, 1, 4096, 4096),
    ),
    "owner": (
        Cell("target", "identity", "cold", "shared", 1024, 1, 4096, 1024),
        Cell("control", "identity", "hot", "shared", 1024, 1, 4096, 16384),
    ),
    "dispatch": (
        Cell("target", "find", "hot", "independent", 128, 16, 128, 2048),
        Cell("target", "find", "hot", "shared", 128, 16, 128, 2048),
        Cell("target", "find_one", "hot", "independent", 1024, 1, 4096, 4096),
        Cell("control", "identity", "hot", "independent", 1024, 1, 4096, 4096),
    ),
}
_PROFILE_READS = 256


def resolved(window: dict[str, object], *, profiled: bool = False) -> dict[str, object]:
    if window["unresolved_cpu"] and not profiled:
        message = f"CPU below 100 clock quanta: {window['unresolved_cpu']}"
        raise AssertionError(message)
    return window


def candidate(
    replica: IsolatedReplicaSet,
    output: Path,
    block: NonNegativeInt,
    cells: tuple[Cell, ...],
    profile: Path | None,
) -> None:
    windows = []
    invalid = None
    active: dict[str, object] = {}
    models: tuple[Literal["sync", "async"], ...] = (
        ("async", "sync") if block % 2 else ("sync", "async")
    )
    ordered = cells[::-1] if block % 2 else cells
    try:
        with MongoClient[BsonDict](replica.uri) as client:
            for cell, model in product(ordered, models):
                for samples, profile_directory in (
                    (cell.samples, None),
                    *(
                        ()
                        if profile is None or cell.role != "target"
                        else ((min(cell.samples, _PROFILE_READS), profile / model),)
                    ),
                ):
                    active = {"cell": asdict(cell), "model": model, "samples": samples}
                    _seed(
                        client,
                        argparse.Namespace(
                            method=cell.method,
                            hot_keys=cell.hot_keys,
                            samples=samples,
                            result_documents=cell.documents,
                            document_bytes=cell.document_bytes,
                        ),
                        cell.workload,
                    )
                    windows.append(
                        {
                            **active,
                            "profiled": profile_directory is not None,
                            **resolved(
                                _run_window(
                                    replica,
                                    model,
                                    cell.workload,
                                    cell.path,
                                    samples,
                                    method=cell.method,
                                    hot_keys=cell.hot_keys,
                                    result_documents=cell.documents,
                                    diagnostics=cell.path == "shared",
                                    validate=True,
                                    document_bytes=cell.document_bytes,
                                    rotation=block * 8192,
                                    budget_bytes=cell.budget_bytes,
                                    max_entry_bytes=cell.max_entry_bytes,
                                    profile_directory=profile_directory,
                                ),
                                profiled=profile_directory is not None,
                            ),
                        }
                    )
    except Exception as error:
        invalid = {"cell": active, "reason": f"{type(error).__name__}: {error}"}
        raise
    finally:
        output.write_text(
            json.dumps({"windows": windows, "invalid": invalid}, indent=2) + "\n",
            encoding="utf-8",
        )


def public(
    replica: IsolatedReplicaSet,
    output: Path,
    block: NonNegativeInt,
    *,
    uncertainty: bool = False,
) -> None:
    windows = []
    invalid = None
    active: dict[str, object] = {}
    rotation = block % len(SHAPES)
    shapes = SHAPES[rotation:] + SHAPES[:rotation]
    models: tuple[Literal["sync", "async"], ...] = (
        ("async", "sync") if block % 2 else ("sync", "async")
    )
    workloads: tuple[Literal["hot", "cold"], ...] = (
        ("cold", "hot") if block % 2 else ("hot", "cold")
    )
    paths: tuple[Literal["direct", "independent", "shared"], ...] = (
        ("independent", "direct") if block % 2 else ("direct", "independent")
    )
    cells = (
        (shape, model, workload)
        for shape, model, workload in product(shapes, models, workloads)
        if not uncertainty
        or shape.method == "find"
        or (shape.method, model, workload) == ("small-entries", "async", "hot")
    )
    try:
        with MongoClient[BsonDict](replica.uri) as client:
            for shape, model, workload in cells:
                samples = shape.hot_samples if workload == "hot" else shape.cold_samples
                for path in (
                    *paths,
                    *(
                        ("shared",)
                        if workload == "hot"
                        and shape.method in {"identity", "find_one", "find"}
                        else ()
                    ),
                ):
                    active = {
                        "shape": asdict(shape),
                        "model": model,
                        "workload": workload,
                        "path": path,
                    }
                    _seed(
                        client,
                        argparse.Namespace(
                            method=shape.method,
                            hot_keys=shape.hot_keys,
                            samples=samples,
                            result_documents=shape.documents,
                            document_bytes=4096,
                        ),
                        workload,
                    )
                    windows.append(
                        resolved(
                            _run_window(
                                replica,
                                model,
                                workload,
                                path,
                                samples,
                                method=shape.method,
                                hot_keys=shape.hot_keys,
                                result_documents=shape.documents,
                                validate=True,
                                document_bytes=4096,
                                rotation=block * 8192,
                                profile_directory=None,
                            )
                        )
                    )
    except Exception as error:
        invalid = {"cell": active, "reason": f"{type(error).__name__}: {error}"}
        raise
    finally:
        output.write_text(
            json.dumps({"windows": windows, "invalid": invalid}, indent=2) + "\n",
            encoding="utf-8",
        )


def command(
    arguments: list[str], output: Path, *, checkout: Path | None = None
) -> dict[str, object]:
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    with output.open("w", encoding="utf-8") as log:
        completed_process = subprocess.run(  # noqa: S603 - Run fixed acquisition modules with the installed interpreter.
            arguments,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
            cwd=checkout,
            env=None
            if checkout is None
            else os.environ | {"PYTHONPATH": str(checkout / "src")},
        )
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    observation = {
        "command": arguments,
        "checkout": str(Path.cwd() if checkout is None else checkout),
        "source_overlay": None if checkout is None else str(checkout / "src"),
        "returncode": completed_process.returncode,
        "wall_seconds": time.monotonic() - started,
        "children_cpu_seconds": after.ru_utime
        + after.ru_stime
        - before.ru_utime
        - before.ru_stime,
    }
    output.with_suffix(".command.json").write_text(
        json.dumps(observation, indent=2) + "\n"
    )
    completed_process.check_returncode()
    return observation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registration", choices=tuple(REGISTRATIONS), required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--block", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--existing-nodes", type=Path, required=True)
    parser.add_argument("--test-checkout", type=Path, default=Path.cwd())
    parser.add_argument("--uncertainty", action="store_true")
    parser.add_argument(
        "--components",
        nargs="+",
        choices=("public", "memory", "contention", "tests", "candidate"),
        default=("public", "memory", "contention", "tests"),
    )
    parser.add_argument("--candidate", choices=tuple(CANDIDATES))
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Add one bounded profiled window per candidate target and model.",
    )
    arguments = parser.parse_args()
    arguments.output = arguments.output.resolve()
    arguments.existing_nodes = arguments.existing_nodes.resolve()
    arguments.wheel = arguments.wheel.resolve()
    arguments.test_checkout = arguments.test_checkout.resolve()
    if arguments.block < 0:
        parser.error("block must not be negative")
    if arguments.uncertainty and arguments.components != ["public"]:
        parser.error("the registered uncertainty cohort contains public cells only")
    if ("candidate" in arguments.components) != (arguments.candidate is not None):
        parser.error("--candidate selects the cells of the candidate component")
    try:
        expected = build(arguments.registration, arguments.label)
    except ValueError as error:
        parser.error(str(error))
    registration = REGISTRATIONS[arguments.registration]
    if digest(arguments.existing_nodes) != registration.node_hash:
        parser.error(f"{arguments.existing_nodes} is not the registered node selection")
    imported = implementation(None)
    extension = Path(imported["extension"])
    if not extension.is_relative_to(sys.prefix):
        parser.error(f"{extension} is not installed in {sys.prefix}")
    verify_installation(expected, arguments.wheel, Path(imported["library"]).parent)
    arguments.output.mkdir(parents=True, exist_ok=False)
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()  # noqa: S607 - Git is the repository tool on the configured executable path.
    (arguments.output / "provenance.json").write_text(
        json.dumps(
            {
                "registration": arguments.registration,
                "label": arguments.label,
                "candidate": arguments.candidate,
                "expected_core": expected.core,
                "block": arguments.block,
                "harness_source": source,
                "wheel": str(arguments.wheel),
                "wheel_sha256": digest(arguments.wheel),
                "extension_sha256": digest(extension),
                "implementation": imported,
                "lock_sha256": digest(Path("uv.lock")),
                "python": sys.version,
                "pymongo": version("pymongo"),
                "platform": platform.platform(),
                "process_clock": vars(time.get_clock_info("process_time")),
                "limits": {
                    name: list(resource.getrlimit(getattr(resource, name)))
                    for name in ("RLIMIT_AS", "RLIMIT_CPU", "RLIMIT_NOFILE")
                },
            },
            indent=2,
        )
        + "\n"
    )
    startup = []
    for model in ("sync", "async"):
        before = time.monotonic()
        output = subprocess.check_output(  # noqa: S603 - Execute a fixed module with this installed interpreter.
            [sys.executable, "-m", "research.native_local_integration.startup", model],
            text=True,
        )
        startup.append(
            {
                "model": model,
                "child_wall_seconds": time.monotonic() - before,
                "checkpoints": json.loads(output),
            }
        )
    (arguments.output / "startup.json").write_text(json.dumps(startup, indent=2) + "\n")
    if "candidate" in arguments.components:
        with IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="1g")) as replica:
            candidate(
                replica,
                arguments.output / "candidate.json",
                arguments.block,
                CANDIDATES[arguments.candidate],
                arguments.output / "profiles" if arguments.profile else None,
            )
    if "public" in arguments.components or "contention" in arguments.components:
        with IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="1g")) as replica:
            if "public" in arguments.components:
                public(
                    replica,
                    arguments.output / "public.json",
                    arguments.block,
                    uncertainty=arguments.uncertainty,
                )
            if "contention" in arguments.components:
                windows = []
                with MongoClient[BsonDict](replica.uri) as client:
                    for threads in (1, 4):
                        _seed(
                            client,
                            argparse.Namespace(
                                method="identity",
                                hot_keys=1024,
                                samples=1,
                                result_documents=1,
                                document_bytes=4096,
                            ),
                            "hot",
                        )
                        windows.append(run_cell(replica, threads, expected=expected))
                        (arguments.output / "contention.json").write_text(
                            json.dumps({"windows": windows}, indent=2) + "\n"
                        )
    if "memory" in arguments.components:
        command(
            [
                sys.executable,
                "-m",
                "research.process_memory.measure",
                "run",
                "--runs",
                "1",
                "--seed",
                str(197 + arguments.block),
                "--scenarios",
                "documents",
                "small-entries",
                "large-keys",
                "cycles",
                "--output",
                str(arguments.output / "memory.json"),
            ],
            arguments.output / "memory.log",
        )
    if "tests" in arguments.components:
        command(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-n",
                "auto",
                f"@{arguments.existing_nodes}",
                "--deselect=tests/core/test_unique_key_admission.py::test_a_rolled_back_identity_admission_does_not_leave_the_alias_orphaned[namespace-clear]",
                "--log-file",
                str(arguments.output / "pytest.log"),
                "--junitxml",
                str(arguments.output / "pytest.xml"),
            ],
            arguments.output / "tests.log",
            checkout=arguments.test_checkout,
        )


if __name__ == "__main__":
    main()
