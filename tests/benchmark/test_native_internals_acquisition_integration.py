from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Literal

import psutil
import pytest
from pymongo import MongoClient

from benchmarks.public_shared_cache import (
    _run_window,
    _seed,
)
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache._types import BsonDict, PositiveInt

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.integration

_WORKERS: PositiveInt = 2
_KEYS: PositiveInt = 4
_READS: PositiveInt = 4
_DEFAULT_COLLECTOR_WORKERS: PositiveInt = 4
_SPAWNED_OWNERS: PositiveInt = 1
_COLLECTOR_PROCESSES = _DEFAULT_COLLECTOR_WORKERS + _SPAWNED_OWNERS
_INTERRUPT_EXIT = 128 + signal.SIGTERM


@pytest.fixture(scope="module")
def replica_set() -> Iterator[IsolatedReplicaSet]:
    with IsolatedReplicaSet(ResourceLimits(cpus=1.0, memory="512m")) as replica_set:
        yield replica_set


def _window(
    replica_set: IsolatedReplicaSet,
    method: str,
    model: Literal["sync", "async"],
    workload: Literal["hot", "cold"],
    path: Literal["independent", "shared"],
) -> dict[str, object]:
    with MongoClient[BsonDict](replica_set.uri) as client:
        _seed(
            client,
            argparse.Namespace(
                method=method,
                hot_keys=_KEYS,
                samples=_READS,
                result_documents=1,
                document_bytes=16,
            ),
            workload,
            workers=_WORKERS,
        )
    return _run_window(
        replica_set,
        model,
        workload,
        path,
        _READS,
        method=method,
        hot_keys=_KEYS,
        diagnostics=path == "shared",
        validate=True,
        document_bytes=16,
        workers=_WORKERS,
        profile_directory=None,
        require_installed=False,
    )


@pytest.mark.timeout(120)
@pytest.mark.parametrize("model", ["sync", "async"])
@pytest.mark.parametrize("workload", ["hot", "cold"])
def test_the_preparation_variant_window_measures_the_full_predicate(
    replica_set: IsolatedReplicaSet,
    model: Literal["sync", "async"],
    workload: Literal["hot", "cold"],
) -> None:
    window = _window(replica_set, "find_one_in", model, workload, "independent")
    observations = window["worker_observations"]
    assert isinstance(observations, list)
    for observation in observations:
        assert observation["predicates"]["unmatched"] == 0
        assert observation["predicates"]["matched"] > 0
        assert observation["follow_up"] == (
            {"hits": _READS, "misses": 0, "bypasses": 0, "origin_reads": 0}
            if workload == "cold"
            else {}
        )


@pytest.mark.timeout(120)
@pytest.mark.parametrize("model", ["sync", "async"])
def test_queued_identity_admissions_drain_before_follow_up_hits(
    replica_set: IsolatedReplicaSet, model: Literal["sync", "async"]
) -> None:
    window = _window(replica_set, "identity", model, "cold", "shared")
    drain = window["admission_drain"]
    assert isinstance(drain, dict)
    assert drain["processed"] == drain["admitted"] == _WORKERS * _READS
    assert drain["worker_submitted"] == drain["worker_queued"] == _WORKERS * _READS
    assert drain["entries"] == _KEYS + _WORKERS * _READS
    observations = window["worker_observations"]
    assert isinstance(observations, list)
    for observation in observations:
        assert observation["follow_up"]["hits"] == _READS


@pytest.mark.timeout(180)
def test_an_interrupted_collector_leaves_no_disposable_processes(
    tmp_path: Path,
) -> None:
    output = tmp_path / "interrupted.json"
    with subprocess.Popen(  # noqa: S603 - Run the fixed collector module with this interpreter.
        (
            sys.executable,
            "-m",
            "benchmarks.public_shared_cache",
            "--method",
            "identity",
            "--hot-keys",
            str(_KEYS),
            "--samples",
            "100000000",
            "--repetitions",
            "1",
            "--models",
            "sync",
            "--paths",
            "shared",
            "--workloads",
            "hot",
            "--output",
            str(output),
        ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ) as collector:
        supervisor = psutil.Process(collector.pid)
        deadline = time.monotonic() + 120
        while len(supervisor.children(recursive=True)) < _COLLECTOR_PROCESSES:
            assert collector.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.1)
        spawned = supervisor.children(recursive=True)
        collector.send_signal(signal.SIGTERM)
        assert collector.wait(timeout=60) == _INTERRUPT_EXIT
    _gone, alive = psutil.wait_procs(spawned, timeout=10)
    assert alive == []
    record = json.loads(output.read_text(encoding="utf-8"))
    assert record["invalid_reason"] == f"SystemExit: {_INTERRUPT_EXIT}"
