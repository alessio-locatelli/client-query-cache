"""Run one registered revision/block from its installed interpreter."""

from __future__ import annotations

import argparse
import hashlib
import json
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
from research.native_process_local_cache.contention import run_cell

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
_NODE_HASH = "595525f35b718ea67cd368334e97298943b07d1f36cdb91281833ebbed7e5bc8"  # pragma: allowlist secret  # noqa: E501 - Preserve the registered node-set digest as one literal.


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def public(
    replica: IsolatedReplicaSet,
    output: Path,
    block: NonNegativeInt,
    *,
    native: bool,
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
    paths: tuple[Literal["direct", "independent"], ...] = (
        ("independent", "direct") if block % 2 else ("direct", "independent")
    )
    try:
        with MongoClient[BsonDict](replica.uri) as client:
            for shape, model, workload in product(shapes, models, workloads):
                samples = shape.hot_samples if workload == "hot" else shape.cold_samples
                for path in paths:
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
                            native_local=native,
                            document_bytes=4096,
                            rotation=block * 8192,
                            profile_directory=None,
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


def command(arguments: list[str], output: Path) -> dict[str, object]:
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    with output.open("w", encoding="utf-8") as log:
        completed_process = subprocess.run(  # noqa: S603 - Run fixed acquisition modules with the installed interpreter.
            arguments, stdout=log, stderr=subprocess.STDOUT, check=False
        )
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    observation = {
        "command": arguments,
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
    parser.add_argument("--label", choices=("M", "R", "N"), required=True)
    parser.add_argument("--block", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--existing-nodes", type=Path, required=True)
    parser.add_argument(
        "--components",
        nargs="+",
        choices=("public", "memory", "contention", "tests"),
        default=("public", "memory", "contention", "tests"),
    )
    arguments = parser.parse_args()
    if arguments.block < 0:
        parser.error("block must not be negative")
    assert digest(arguments.existing_nodes) == _NODE_HASH
    arguments.output.mkdir(parents=True, exist_ok=False)
    imported = implementation(None)
    extension = Path(imported["extension"])
    assert extension.is_relative_to(sys.prefix)
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()  # noqa: S607 - Git is the repository tool on the configured executable path.
    (arguments.output / "provenance.json").write_text(
        json.dumps(
            {
                "label": arguments.label,
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
    native = arguments.label == "N"
    if "public" in arguments.components or "contention" in arguments.components:
        with IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="1g")) as replica:
            if "public" in arguments.components:
                public(
                    replica,
                    arguments.output / "public.json",
                    arguments.block,
                    native=native,
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
                        windows.append(run_cell(replica, threads, native=native))
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
                "--backend",
                "native" if native else "reference",
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
                "0",
                f"@{arguments.existing_nodes}",
                "--log-file",
                str(arguments.output / "pytest.log"),
                "--junitxml",
                str(arguments.output / "pytest.xml"),
                *(
                    [
                        "-p",
                        "research.native_process_local_cache.pytest_plugin",
                        "--native-managers-only",
                    ]
                    if native
                    else []
                ),
            ],
            arguments.output / "tests.log",
        )


if __name__ == "__main__":
    main()
