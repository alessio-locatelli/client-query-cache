from __future__ import annotations

from typing import Any

import pytest
from pymongo import MongoClient

from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits

pytestmark = pytest.mark.integration


def test_isolated_replica_set_starts_and_reports_cpu_usage() -> None:
    limits = ResourceLimits(cpus=1.0, memory="512m")
    with IsolatedReplicaSet(limits) as replica_set:
        with MongoClient[dict[str, Any]](
            replica_set.uri, serverSelectionTimeoutMS=2_000
        ) as client:
            hello = client.admin.command("hello")
            assert hello["isWritablePrimary"] is True
            for _ in range(1_000):
                client.get_database("warmup").get_collection("cpu").insert_one({})

        usage_seconds = replica_set.container_cpu_usage_seconds()
        assert usage_seconds > 0
