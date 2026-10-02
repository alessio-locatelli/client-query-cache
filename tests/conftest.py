import decimal
import logging
import uuid
from contextlib import ExitStack
from copy import copy
from datetime import datetime
from decimal import Decimal
from time import monotonic, sleep
from typing import TYPE_CHECKING, Any, NewType

import pytest
from bson import Decimal128
from docker.errors import DockerException
from pymongo import MongoClient
from pymongo.errors import AutoReconnect
from testcontainers.core.container import DockerContainer

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from faker import Faker

MongoDbUri = NewType("MongoDbUri", str)
DatabaseName = NewType("DatabaseName", str)
CollectionName = NewType("CollectionName", str)

logger = logging.getLogger(__name__)

_MONGODB_STARTUP_TIMEOUT_SECONDS = 30.0
_MONGODB_POLL_INTERVAL_SECONDS = 0.1

logging.getLogger("faker.factory").setLevel("INFO")
logging.getLogger("pymongo").setLevel("INFO")


def _wait_for_mongodb_ping(client: MongoClient[dict[str, Any]]) -> None:
    deadline = monotonic() + _MONGODB_STARTUP_TIMEOUT_SECONDS
    while monotonic() < deadline:
        try:
            client.admin.command("ping")
        except AutoReconnect:  # pragma: lax no cover (container startup timing varies)
            sleep(_MONGODB_POLL_INTERVAL_SECONDS)
        else:
            return
    pytest.fail(  # pragma: no cover (hard timeout; requires an unreachable container)
        f"MongoDB did not become reachable within "
        f"{_MONGODB_STARTUP_TIMEOUT_SECONDS:.0f} seconds after container start."
    )


@pytest.fixture(autouse=True)
def log_when_test_starts(request: pytest.FixtureRequest) -> None:
    cls_ = f"{request.cls}." if request.cls else ""
    logger.debug(f"Starting '{cls_}{request.node.name}'...")  # noqa: G004


@pytest.fixture
def cached_database_name() -> DatabaseName:
    return DatabaseName(f"test_{uuid.uuid4().hex}")


@pytest.fixture
def persistent_collection_name() -> CollectionName:
    return CollectionName("persistent_collection")


@pytest.fixture
def nonpersistent_collection_name() -> CollectionName:
    return CollectionName("nonpersistent_collection")


@pytest.fixture(scope="session")
def mongodb_uri() -> Iterator[MongoDbUri]:
    with ExitStack() as resources:
        try:
            # renovate: datasource=docker depName=mongo versioning=docker
            container = DockerContainer("mongo:8.0.4-noble")
            container.with_command(["--replSet", "rs0", "--bind_ip_all"])
            container.with_exposed_ports(27017)
            resources.enter_context(container)
        except DockerException as error:  # pragma: no cover (requires a broken runtime)
            message = (
                "A Docker-compatible container runtime is required for integration "
                "and end-to-end tests. Start Docker or a rootless Podman socket and "
                f"try again. Container startup failed: {error}"
            )
            raise pytest.fail.Exception(message, pytrace=False) from None

        host = container.get_container_host_ip()
        port = container.get_exposed_port(27017)
        uri = MongoDbUri(f"mongodb://{host}:{port}/?directConnection=true")

        with MongoClient[dict[str, Any]](uri, serverSelectionTimeoutMS=1_000) as client:
            _wait_for_mongodb_ping(client)

            client.admin.command(
                "replSetInitiate",
                {
                    "_id": "rs0",
                    "members": [{"_id": 0, "host": "localhost:27017"}],
                },
            )

            deadline = monotonic() + 30
            while monotonic() < deadline:
                try:
                    if client.admin.command("hello")["isWritablePrimary"]:
                        yield uri
                        return
                except AutoReconnect:  # pragma: lax no cover (election timing varies)
                    pass
                sleep(_MONGODB_POLL_INTERVAL_SECONDS)
            pytest.fail(  # pragma: no cover (hard timeout; requires a stuck container)
                "MongoDB did not elect a writable primary within 30 seconds."
            )


@pytest.fixture
def make_fake_document(faker: Faker) -> Callable[..., dict[str, Any]]:
    def _make_fake_document() -> dict[str, Any]:
        document = faker.pydict()
        document["_id"] = str(uuid.uuid4())

        mongo_compatible_document: dict[str, Any] = {}
        for k, v in document.items():
            if isinstance(v, datetime):
                mongo_compatible_document[k] = copy(v).replace(microsecond=0)
            elif isinstance(v, Decimal):
                try:
                    mongo_compatible_document[k] = Decimal128(v)
                except decimal.Inexact:
                    continue
            else:
                mongo_compatible_document[k] = v

        return mongo_compatible_document

    return _make_fake_document
