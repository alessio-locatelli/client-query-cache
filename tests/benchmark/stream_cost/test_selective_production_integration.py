from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from client_query_cache._types import NonNegativeFloat, NonNegativeInt
from research.invalidation_scope.benchmark import TOPOLOGY
from research.invalidation_scope.end_to_end import run_cell, seed

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pymongo.synchronous.database import Database

    from client_query_cache._types import BsonDict
    from research.invalidation_scope.end_to_end import Mix, Policy, Scenario

pytestmark = pytest.mark.integration


@pytest.fixture
def production_workload() -> Iterator[
    tuple[IsolatedReplicaSet, Database[BsonDict], str]
]:
    with (
        IsolatedReplicaSet(ResourceLimits(cpus=2.0, memory="4g")) as replica,
        replica.build_client(TOPOLOGY) as client,
    ):
        yield replica, client.bench, seed(client.bench, 2000)


@pytest.mark.parametrize(
    ("policy", "mix", "rate", "seconds", "scenario", "writes", "reads"),
    [
        ("both", "mixed", 0, 0, "cached", 12, 128),
        ("insert", "update", 8, 1, "cached", 8, 8),
        ("counts", "insert", 8, 1, "cached", 8, 8),
        ("both", "insert", 8, 1, "uncached", 8, 8),
    ],
)
def test_production_runner_reconciles_public_cache_and_native_commands(
    production_workload: tuple[IsolatedReplicaSet, Database[BsonDict], str],
    policy: Policy,
    mix: Mix,
    rate: NonNegativeInt,
    seconds: NonNegativeFloat,
    *,
    scenario: Scenario,
    writes: NonNegativeInt,
    reads: NonNegativeInt,
) -> None:
    replica, database, body = production_workload
    cell = run_cell(
        replica,
        database,
        body,
        path="production",
        policy=policy,
        mix=mix,
        scenario=scenario,
        rep=0,
        reads=128,
        reads_per_write=10,
        control_rate=rate,
        seconds=seconds,
    )
    assert cell["path"] == "production"
    assert cell["policy"] == policy
    assert cell["stream_wire"] is None
    assert cell["writes"] == cell["applied_events"] == writes
    logical_bytes = cell["logical_bytes"]
    assert isinstance(logical_bytes, int)
    assert logical_bytes > 0
    assert isinstance(cell["cache_delta"], dict)
    assert isinstance(cell["driver_reads"], dict)
    assert cell["cache_delta"]["bypasses"] == 0
    assert sum(cell["driver_reads"].values()) == cell["cache_delta"]["misses"]
    assert cell["cache_delta"]["hits"] + cell["cache_delta"]["misses"] == reads
