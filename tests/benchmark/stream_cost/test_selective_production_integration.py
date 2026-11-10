from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits
from research.invalidation_scope.benchmark import TOPOLOGY
from research.invalidation_scope.end_to_end import run_cell, seed

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pymongo.synchronous.database import Database

    from client_query_cache._types import BsonDict

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


def test_production_runner_reconciles_public_cache_and_native_commands(
    production_workload: tuple[IsolatedReplicaSet, Database[BsonDict], str],
) -> None:
    replica, database, body = production_workload
    cell = run_cell(
        replica,
        database,
        body,
        path="production",
        policy="both",
        mix="mixed",
        scenario="cached",
        rep=0,
        reads=128,
        reads_per_write=10,
    )
    assert cell["path"] == "production"
    assert cell["policy"] == "both"
    assert cell["stream_wire"] is None
    assert cell["writes"] == cell["applied_events"] == 12
    assert isinstance(cell["cache_delta"], dict)
    assert isinstance(cell["driver_reads"], dict)
    assert cell["cache_delta"]["bypasses"] == 0
    assert sum(cell["driver_reads"].values()) == cell["cache_delta"]["misses"]
    assert cell["cache_delta"]["hits"] + cell["cache_delta"]["misses"] == 128
