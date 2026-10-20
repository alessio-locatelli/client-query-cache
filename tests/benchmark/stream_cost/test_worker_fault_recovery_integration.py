from __future__ import annotations

import time
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from pymongo import MongoClient

from benchmarks.stream_cost.topology import (
    IsolatedReplicaSet,
    ReplicaSetTopology,
    ResourceLimits,
)
from client_query_cache._types import BsonDict, NonNegativeInt
from tests.benchmark.stream_cost.worker_fault_harness import (
    Payload,
    WorkerConfig,
    WorkerPath,
    WorkerProcesses,
    WorkerRequestError,
    wait_for,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

pytestmark = pytest.mark.integration

_IDENTITY: NonNegativeInt = 0
_POLL_SECONDS = 0.05
_RECOVERY_TIMEOUT_SECONDS = 30.0
_LIMITS = ResourceLimits(cpus=1.0, memory="1g")


@pytest.fixture(scope="module")
def replica_set() -> Iterator[IsolatedReplicaSet]:
    with IsolatedReplicaSet(_LIMITS) as topology:
        yield topology


@pytest.mark.timeout(180)
@pytest.mark.parametrize("path", ["direct", "independent"])
def test_tcp_connection_loss_recovers_real_workers(
    replica_set: IsolatedReplicaSet, path: WorkerPath
) -> None:
    database, collection = _new_collection(replica_set.uri)
    configs = _configs(replica_set.uri, database, collection, (path, path), proxy=True)
    _insert(replica_set.uri, database, collection, revision=0)

    with WorkerProcesses(configs) as workers:
        before = [workers.request(index, "snapshot") for index in range(2)]
        if path == "direct":
            assert all(_number(state, "streams") == 0 for state in before)
        for index in range(2):
            severed = workers.request(index, "sever")
            assert _number(severed, "severed_sockets") > 0
        _update(replica_set.uri, database, collection, revision=1)

        for index, initial in enumerate(before):
            recovered = _await_read(
                workers,
                index,
                revision=1,
                predicate=_path_recovered(
                    path,
                    initial,
                    require_stream_reopen=path == "independent",
                ),
            )
            if path == "direct":
                assert _number(recovered, "streams") == 0


@pytest.mark.timeout(180)
def test_lost_stream_history_clears_cache_and_reads_latest_document(
    replica_set: IsolatedReplicaSet,
) -> None:
    database, collection = _new_collection(replica_set.uri)
    configs = _configs(
        replica_set.uri,
        database,
        collection,
        ("independent", "independent"),
        proxy=True,
    )
    _insert(replica_set.uri, database, collection, revision=0)

    with WorkerProcesses(configs) as workers:
        before = [workers.request(index, "snapshot") for index in range(2)]
        assert all(state["entries"] == 1 for state in before)

        _update(replica_set.uri, database, collection, revision=1)
        primed: list[Payload] = []
        for index, initial in enumerate(before):
            recovered = _await_read(
                workers,
                index,
                revision=1,
                predicate=_path_recovered("independent", initial),
            )
            assert _number(recovered, "entries") == 1
            primed.append(recovered)

        for index in range(2):
            injected = workers.request(index, "lose-history")
            assert _number(injected, "history_fault_code") == 286

        recovered_after_history_loss: list[Payload] = []
        for index, previous in enumerate(primed):
            wait_for(
                workers,
                index,
                _history_cleared(previous),
            )
            latest = workers.request(index, "read")
            assert latest["revision"] == 1
            assert _number(latest, "misses") > _number(previous, "misses")
            recovered_after_history_loss.append(latest)

        _update(replica_set.uri, database, collection, revision=2)
        for index, previous in enumerate(recovered_after_history_loss):
            latest = _await_read(
                workers,
                index,
                revision=2,
                predicate=_path_recovered("independent", previous),
            )
            assert _number(latest, "invalidations") > _number(previous, "invalidations")


@pytest.mark.timeout(180)
@pytest.mark.parametrize("path", ["direct", "independent"])
def test_killed_worker_replacement_reads_from_mongodb(
    replica_set: IsolatedReplicaSet, path: WorkerPath
) -> None:
    database, collection = _new_collection(replica_set.uri)
    configs = _configs(replica_set.uri, database, collection, (path, path), proxy=True)
    _insert(replica_set.uri, database, collection, revision=0)

    with WorkerProcesses(configs) as workers:
        before = [workers.request(index, "snapshot") for index in range(2)]
        if path == "direct":
            assert _number(before[0], "streams") == 0
        _update(replica_set.uri, database, collection, revision=1)
        _await_read(
            workers,
            1,
            revision=1,
            predicate=lambda state: (
                path == "direct"
                or _number(state, "invalidations") > _number(before[1], "invalidations")
            ),
        )

        replacement = workers.restart(0)

        assert _number(replacement, "pid") != _number(before[0], "pid")
        assert _number(replacement, "entries") == int(path == "independent")
        if path == "direct":
            assert _number(replacement, "streams") == 0
        assert workers.request(0, "read")["revision"] == 1
        assert workers.request(1, "read")["revision"] == 1


@pytest.mark.timeout(300)
def test_primary_stepdown_recovers_direct_and_independent_workers() -> None:
    with ReplicaSetTopology() as topology:
        database, collection = _new_collection(topology.uri)
        paths: tuple[WorkerPath, ...] = (
            "direct",
            "direct",
            "independent",
            "independent",
        )
        configs = _configs(topology.uri, database, collection, paths, proxy=False)
        _insert(topology.uri, database, collection, revision=0)

        with WorkerProcesses(configs) as workers:
            before = [workers.request(index, "read") for index in range(len(paths))]
            previous_primary = topology.await_writable_primary()
            assert topology.step_down_primary() == previous_primary
            elected_primary = topology.await_writable_primary()
            assert elected_primary != previous_primary
            _update(topology.uri, database, collection, revision=1)

            for index, path in enumerate(paths):
                recovered = _await_read(
                    workers,
                    index,
                    revision=1,
                    predicate=_path_recovered(path, before[index]),
                )
                if path == "direct":
                    assert _number(recovered, "streams") == 0


def _new_collection(uri: str) -> tuple[str, str]:
    database = f"worker_fault_{uuid4().hex}"
    collection = "documents"
    with MongoClient[BsonDict](uri) as client:
        client[database].create_collection(collection)
    return database, collection


def _insert(
    uri: str, database: str, collection: str, *, revision: NonNegativeInt
) -> None:
    with MongoClient[BsonDict](uri) as client:
        client[database][collection].insert_one(
            {"_id": _IDENTITY, "revision": revision}
        )


def _update(
    uri: str, database: str, collection: str, *, revision: NonNegativeInt
) -> None:
    with MongoClient[BsonDict](uri) as client:
        update_result = client[database][collection].update_one(
            {"_id": _IDENTITY}, {"$set": {"revision": revision}}
        )
    assert update_result.matched_count == 1


def _configs(
    uri: str,
    database: str,
    collection: str,
    paths: tuple[WorkerPath, ...],
    *,
    proxy: bool,
) -> tuple[WorkerConfig, ...]:
    return tuple(
        WorkerConfig(
            uri=uri,
            database=database,
            collection=collection,
            identity=_IDENTITY,
            path=path,
            proxy_enabled=proxy,
        )
        for path in paths
    )


def _await_read(
    workers: WorkerProcesses,
    index: NonNegativeInt,
    *,
    revision: NonNegativeInt,
    predicate: Callable[[Payload], bool],
) -> Payload:
    deadline = time.monotonic() + _RECOVERY_TIMEOUT_SECONDS
    last: Payload = {}
    while time.monotonic() < deadline:
        try:
            last = workers.request(index, "read")
        except (
            WorkerRequestError
        ):  # pragma: lax no cover (transient fault timing varies).
            time.sleep(_POLL_SECONDS)
            continue
        if last["revision"] == revision and predicate(last):
            return last
        time.sleep(
            _POLL_SECONDS
        )  # pragma: lax no cover (the first read may already show recovery).
    message = (  # pragma: no cover (the recovery deadline fails the test).
        f"worker {index} did not read revision {revision}: {last}"
    )
    raise AssertionError(
        message
    )  # pragma: no cover (recovery is required by the test).


def _stream_recovered(state: Payload, previous: Payload) -> bool:
    return state["health"] == "healthy" and _number(state, "invalidations") > _number(
        previous, "invalidations"
    )


def _path_recovered(
    path: WorkerPath,
    previous: Payload,
    *,
    require_stream_reopen: bool = False,
) -> Callable[[Payload], bool]:
    def predicate(state: Payload) -> bool:
        return path == "direct" or (
            _stream_recovered(state, previous)
            and (
                not require_stream_reopen
                or _number(state, "streams") > _number(previous, "streams")
            )
        )

    return predicate


def _history_cleared(previous: Payload) -> Callable[[Payload], bool]:
    def predicate(state: Payload) -> bool:
        return (
            _number(state, "entries") == 0
            and _number(state, "streams") > _number(previous, "streams")
            and state["health"] == "healthy"
        )

    return predicate


def _number(state: Payload, key: str) -> NonNegativeInt:
    value = state[key]
    assert isinstance(value, int)
    return value
