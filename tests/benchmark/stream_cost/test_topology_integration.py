from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from pymongo import MongoClient

from benchmarks.stream_cost import topology
from benchmarks.stream_cost.topology import IsolatedReplicaSet, ResourceLimits

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration


@pytest.fixture(params=["benchmark", "compose"])
def replica_set(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[IsolatedReplicaSet]:
    if request.param == "compose":
        compose = Path(__file__).resolve().parents[3] / "docker-compose.yaml"
        image = str(yaml.safe_load(compose.read_text())["services"]["mongo"]["image"])
        monkeypatch.setattr(topology, "MONGODB_IMAGE", image)
    limits = ResourceLimits(cpus=1.0, memory="512m")
    with IsolatedReplicaSet(limits) as replica_set:
        yield replica_set


@pytest.fixture
def mongo_client(
    replica_set: IsolatedReplicaSet,
) -> Iterator[MongoClient[dict[str, Any]]]:
    with MongoClient[dict[str, Any]](
        replica_set.uri, serverSelectionTimeoutMS=2_000
    ) as client:
        yield client


def test_isolated_replica_set_starts_and_reports_cpu_usage(
    replica_set: IsolatedReplicaSet, mongo_client: MongoClient[dict[str, Any]]
) -> None:
    hello = mongo_client.admin.command("hello")
    assert hello["isWritablePrimary"] is True
    for _ in range(1_000):
        mongo_client.get_database("warmup").get_collection("cpu").insert_one({})

    usage_seconds = replica_set.container_cpu_usage_seconds()
    assert usage_seconds > 0
