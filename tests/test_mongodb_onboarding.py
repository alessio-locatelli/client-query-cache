from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pymongo import AsyncMongoClient, MongoClient
from testcontainers.core.container import DockerContainer

from benchmarks.mongodb_image import MONGODB_IMAGE
from client_query_cache import CacheManager, StreamHealthStatus
from client_query_cache._types import BsonDict, NonEmptyStr
from client_query_cache.asynchronous import CacheManager as AsyncCacheManager
from tests.conftest import MongoDbUri

if TYPE_CHECKING:
    from collections.abc import Iterator

_REPOSITORY = Path(__file__).resolve().parents[1]


@pytest.fixture
def readme_program() -> NonEmptyStr:
    return (
        (_REPOSITORY / "README.md")
        .read_text()
        .split("```python\n", 1)[1]
        .split("```", 1)[0]
    )


@pytest.fixture
def initializer_program() -> NonEmptyStr:
    return (
        (_REPOSITORY / "docs/user/getting-started/mongodb-ci.md")
        .read_text()
        .split("```python\n", 1)[1]
        .split("```", 1)[0]
    )


@pytest.fixture
def unavailable_uri() -> Iterator[MongoDbUri]:
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        yield MongoDbUri(
            f"mongodb://127.0.0.1:{reserved.getsockname()[1]}/"
            "?directConnection=true&serverSelectionTimeoutMS=100"
        )


@pytest.fixture(params=[True, False], ids=["replica-set", "standalone"])
def uninitialized_mongodb_uri(request: pytest.FixtureRequest) -> Iterator[MongoDbUri]:
    command = ["--bind_ip_all"]
    if request.param:
        command.extend(["--replSet", "rs0"])
    with (
        DockerContainer(MONGODB_IMAGE)
        .with_command(command)
        .with_exposed_ports(27017) as container
    ):
        yield MongoDbUri(
            f"mongodb://{container.get_container_host_ip()}:"
            f"{container.get_exposed_port(27017)}/?directConnection=true"
        )


def _run_program(
    program: NonEmptyStr, uri: MongoDbUri
) -> subprocess.CompletedProcess[str]:  # Captured output may be empty.
    return subprocess.run(  # noqa: S603 - Execute repository-authored documentation against disposable services.
        [sys.executable, "-c", program],
        env=os.environ | {"MONGODB_URI": uri, "MONGODB_MEMBER_HOST": "localhost:27017"},
        capture_output=True,
        text=True,
        check=False,
        timeout=70,
    )


@pytest.mark.unit
def test_initializer_fails_within_deadline_when_server_is_missing(
    initializer_program: NonEmptyStr, unavailable_uri: MongoDbUri
) -> None:
    completed = _run_program(
        initializer_program.replace("timeout(60)", "timeout(1)"), unavailable_uri
    )
    assert completed.returncode != 0
    assert "ServerSelectionTimeoutError" in completed.stderr


@pytest.mark.integration
def test_documented_initializer_handles_fresh_and_existing_services(
    initializer_program: NonEmptyStr,
    uninitialized_mongodb_uri: MongoDbUri,
    request: pytest.FixtureRequest,
) -> None:
    completed = _run_program(initializer_program, uninitialized_mongodb_uri)
    replica_set = request.node.callspec.params["uninitialized_mongodb_uri"]
    if not replica_set:
        assert completed.returncode != 0
        assert "NoReplicationEnabled" in completed.stderr
        return
    assert completed.returncode == 0, completed.stderr
    repeated = _run_program(initializer_program, uninitialized_mongodb_uri)
    assert repeated.returncode == 0, repeated.stderr
    with MongoClient[BsonDict](uninitialized_mongodb_uri) as client:
        assert client.admin.command("hello")["isWritablePrimary"] is True
        with client["ci_onboarding"].watch(max_await_time_ms=10) as stream:
            assert stream.alive
        client.admin.command("replSetStepDown", 30, force=True)
    unwritable = _run_program(
        initializer_program.replace("timeout(60)", "timeout(1)"),
        uninitialized_mongodb_uri,
    )
    assert unwritable.returncode != 0
    assert "operation would exceed time limit" in unwritable.stderr


@pytest.mark.integration
def test_readme_runs_against_ready_replica_set(
    readme_program: NonEmptyStr, mongodb_uri: MongoDbUri
) -> None:
    completed = _run_program(
        readme_program.replace("mongodb://localhost:27017", mongodb_uri), mongodb_uri
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.integration
@pytest.mark.parametrize(
    "uninitialized_mongodb_uri", [False], indirect=True, ids=["standalone"]
)
async def test_standalone_guidance_preserves_sync_and_async_uncached_reads(
    uninitialized_mongodb_uri: MongoDbUri,
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_name = "onboarding_standalone"
    with (
        MongoClient[BsonDict](uninitialized_mongodb_uri) as client,
        CacheManager(client) as manager,
    ):
        collection = client[database_name]["items"]
        collection.insert_one({"_id": "example"})
        assert manager.get_cached_collection(collection).find_one({"_id": "example"})
        assert (
            manager.stream_health_snapshot(database_name).status
            is StreamHealthStatus.STARTUP_FAILED
        )
    async with (
        AsyncMongoClient[BsonDict](uninitialized_mongodb_uri) as async_client,
        AsyncCacheManager(async_client) as async_manager,
    ):
        cached = async_manager[database_name]["items"]
        assert await cached.find_one({"_id": "example"})
        assert (
            async_manager.stream_health_snapshot(database_name).status
            is StreamHealthStatus.STARTUP_FAILED
        )
    assert caplog.text.count("caching requires a MongoDB replica set") == 2
    assert caplog.text.count("installation/#local-mongodb") == 2
