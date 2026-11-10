"""Compare release environments with alternating warm batches in persistent workers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING

import pymongo

from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache import _shared_index
from client_query_cache._types import BsonDict, NonNegativeInt, PositiveInt
from research.invalidation_scope.benchmark import HOT_AUTHORS, TOPOLOGY
from research.invalidation_scope.end_to_end import SEED, seed, warm_calls

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import IO


def worker(uri: str) -> None:
    with warm_calls(uri, "bench") as (manager, listener, calls):
        print(
            json.dumps(
                {
                    "python": platform.python_version(),
                    "pymongo": pymongo.version,
                    "binary_sha256": hashlib.sha256(
                        Path(_shared_index.__file__).read_bytes()
                    ).hexdigest(),
                }
            ),
            flush=True,
        )
        for line in sys.stdin:
            request = json.loads(line)
            kind, reads = request["kind"], request["reads"]
            before = manager.snapshot().hits  # pytriage: TR11 (before measured reads)
            listener.active = kind
            commands = listener.counts[kind]
            cpu_started = time.thread_time_ns()
            wall_started = time.perf_counter_ns()
            for index in range(reads):
                calls[kind, index % HOT_AUTHORS]()
            wall = time.perf_counter_ns() - wall_started
            cpu = time.thread_time_ns() - cpu_started
            listener.active = None
            assert manager.snapshot().hits - before == reads
            assert listener.counts[kind] == commands
            print(
                json.dumps(
                    {"cpu_ns_per_hit": cpu / reads, "wall_ns_per_hit": wall / reads}
                ),
                flush=True,
            )


def sample_workers(
    workers: dict[str, tuple[IO[str], IO[str]]],
    selected_kinds: Sequence[str],
    batches: PositiveInt,
    reads: PositiveInt,
    block: NonNegativeInt,
) -> list[BsonDict]:
    samples: list[BsonDict] = []
    for batch in range(batches):
        kinds = selected_kinds if batch % 2 == 0 else reversed(selected_kinds)
        for kind in kinds:
            order = ("base", "head") if (batch + block) % 2 == 0 else ("head", "base")
            for label in order:
                writer, reader = workers[label]
                writer.write(json.dumps({"kind": kind, "reads": reads}) + "\n")
                writer.flush()
                samples.append(
                    {
                        "block": block,
                        "batch": batch,
                        "kind": kind,
                        "label": label,
                        **json.loads(reader.readline()),
                    }
                )
    return samples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-python", type=Path)
    parser.add_argument("--head-python", type=Path)
    parser.add_argument("--worker-uri")
    parser.add_argument("--reps", type=int, default=4)
    parser.add_argument("--batches", type=int, default=100)
    parser.add_argument("--reads", type=int, default=1000)
    parser.add_argument(
        "--kinds",
        nargs="+",
        choices=("feed", "prefix", "count", "own", "by_id"),
        default=("feed", "prefix", "own"),
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.worker_uri is not None:
        worker(args.worker_uri)
        return
    if args.base_python is None or args.head_python is None or args.out is None:
        parser.error("base/head interpreters and output are required")
    if min(args.reps, args.batches, args.reads) < 1:
        parser.error("reps, batches, and reads must be positive")
    cpu = min(os.sched_getaffinity(0))
    os.sched_setaffinity(0, {cpu})
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = str(SEED)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    samples: list[BsonDict] = []
    environments: list[BsonDict] = []
    with (
        args.out.open("x") as output,
        IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="4g")) as replica,
        replica.build_client(TOPOLOGY) as client,
    ):
        seed(client.bench, 2000)
        for block in range(args.reps):
            with ExitStack() as stack:
                workers = {}
                revisions = (
                    ("base", args.base_python),
                    ("head", args.head_python),
                )
                for label, interpreter in (
                    revisions if block % 2 == 0 else reversed(revisions)
                ):
                    process = stack.enter_context(
                        subprocess.Popen(  # noqa: S603 - Explicit local release interpreter; no shell.
                            [
                                # Keep the venv path when Python is a symlink.
                                str(interpreter.absolute()),
                                "-m",
                                "research.invalidation_scope.paired",
                                "--worker-uri",
                                replica.uri,
                            ],
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            text=True,
                            env=environment,
                        )
                    )
                    assert process.stdin is not None
                    assert process.stdout is not None
                    workers[label] = (process.stdin, process.stdout)
                    environments.append(
                        {
                            "block": block,
                            "label": label,
                            **json.loads(process.stdout.readline()),
                        }
                    )
                assert environments[-1]["python"] == environments[-2]["python"]
                assert environments[-1]["pymongo"] == environments[-2]["pymongo"]
                samples.extend(
                    sample_workers(workers, args.kinds, args.batches, args.reads, block)
                )
        json.dump(
            {
                "client_cpu": cpu,
                "python_hash_seed": SEED,
                "reads_per_batch": args.reads,
                "environments": environments,
                "samples": samples,
            },
            output,
            indent=2,
        )
        output.write("\n")


if __name__ == "__main__":
    main()
