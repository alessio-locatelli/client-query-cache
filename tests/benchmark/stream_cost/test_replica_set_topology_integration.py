from __future__ import annotations

from time import monotonic, sleep

import pytest
from docker.errors import NotFound
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.topology import ReplicaSetTopology
from client_query_cache._types import BsonDict, NonEmptyStr

pytestmark = pytest.mark.integration

_ELECTION_DEADLINE_SECONDS = 25.0
_ELECTION_POLL_SECONDS = 0.1
_EXPECTED_CPU_NANOCPUS = 1_000_000_000
_EXPECTED_MEMORY_BYTES = 1_073_741_824


@pytest.mark.timeout(120)
def test_replica_set_topology_limits_and_stepdown_elect_a_new_primary() -> None:
    topology = ReplicaSetTopology()
    with topology:
        containers = topology.member_containers
        assert len(containers) == 3
        assert len(set(topology.member_ports)) == 3

        for container in containers:
            host_config = container.get_wrapped_container().attrs["HostConfig"]
            assert host_config["NetworkMode"] == "host"
            assert host_config["NanoCpus"] == _EXPECTED_CPU_NANOCPUS
            assert host_config["Memory"] == _EXPECTED_MEMORY_BYTES

        with MongoClient[BsonDict](
            topology.uri,
            serverSelectionTimeoutMS=1_000,
            connectTimeoutMS=1_000,
        ) as client:
            assert "directConnection" not in topology.uri
            collection = client["benchmark_fault_recovery"]["failover"]
            collection.insert_one({"_id": "before-stepdown"})
            previous_primary = topology.primary_identity()

            topology.step_down_primary()
            elected_primary = _await_new_primary(topology, previous_primary)

            assert elected_primary != previous_primary
            collection.insert_one({"_id": "after-stepdown"})
            assert collection.find_one({"_id": "after-stepdown"}) is not None

    for container in containers:
        with pytest.raises(NotFound):
            container.get_wrapped_container().reload()
    with pytest.raises(BenchmarkSetupError, match="has not been started"):
        _ = topology.member_containers


def _await_new_primary(
    topology: ReplicaSetTopology, previous_primary: NonEmptyStr
) -> NonEmptyStr:
    deadline = monotonic() + _ELECTION_DEADLINE_SECONDS
    while (
        monotonic() < deadline
    ):  # pragma: lax no cover (election timing varies across container runs)
        try:
            primary_identity = topology.primary_identity()
        except (
            PyMongoError
        ):  # pragma: lax no cover (transient election errors are timing dependent)
            sleep(_ELECTION_POLL_SECONDS)
        else:
            if primary_identity != previous_primary:
                return primary_identity
            sleep(
                _ELECTION_POLL_SECONDS
            )  # pragma: lax no cover (election timing varies across container runs)
    raise AssertionError(
        "MongoDB did not elect a different writable primary after stepdown"
    )  # pragma: lax no cover (transient election timeout)
