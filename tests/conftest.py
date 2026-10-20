import decimal
import logging
import os
import tempfile
import uuid
from collections.abc import Generator  # noqa: TC003 (pluggy evaluates hook annotations)
from contextlib import ExitStack, contextmanager
from copy import copy
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from time import monotonic, sleep
from typing import TYPE_CHECKING, NewType

import pytest
from bson import Decimal128
from docker.errors import DockerException, ImageNotFound
from filelock import FileLock
from pymongo import MongoClient, timeout
from pymongo.errors import AutoReconnect
from testcontainers.core.container import DockerContainer
from testcontainers.core.docker_client import DockerClient

from benchmarks.mongodb_diagnostics import note_mongodb_startup_failure
from benchmarks.mongodb_image import MONGODB_IMAGE, compose_mongodb_image
from client_query_cache._types import BsonDict, NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from faker import Faker

MongoDbUri = NewType("MongoDbUri", str)
DatabaseName = NewType("DatabaseName", str)
CollectionName = NewType("CollectionName", str)

_MONGODB_SESSION = pytest.StashKey[pytest.CallInfo[MongoDbUri]]()
_MONGODB_RESOURCES = pytest.StashKey[ExitStack]()

logger = logging.getLogger(__name__)

_MONGODB_STARTUP_TIMEOUT_SECONDS = 30.0
_MONGODB_POLL_INTERVAL_SECONDS = 0.1
_MINIMUM_MONGODB_COMPOSE_FILE = (
    Path(__file__).with_name("mongodb-minimum") / "docker-compose.yaml"
)
_MONGODB_IMAGE_LOCK_FILE = (
    Path(tempfile.gettempdir()) / "client-query-cache-mongodb-image.lock"
)

logging.getLogger("faker.factory").setLevel("INFO")
logging.getLogger("pymongo").setLevel("INFO")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--minimum-mongodb",
        action="store_true",
        help="run MongoDB-backed tests against the minimum supported server",
    )


def _mongodb_image(config: pytest.Config) -> str:
    return (
        compose_mongodb_image(_MINIMUM_MONGODB_COMPOSE_FILE)
        if config.getoption("minimum_mongodb")
        else MONGODB_IMAGE
    )


def _pull_missing_image(image: str) -> None:
    images = DockerClient().client.images
    with FileLock(_MONGODB_IMAGE_LOCK_FILE):
        try:
            images.get(image)
        except ImageNotFound:  # pragma: lax no cover (depends on the image cache)
            images.pull(image)


def pytest_collection_finish(session: pytest.Session) -> None:
    needs_mongodb = not session.config.option.collectonly and any(
        isinstance(item, pytest.Function) and "mongodb_uri" in item.fixturenames
        for item in session.items
    )
    if needs_mongodb:  # pragma: no branch - coverage runs always run MongoDB tests
        try:
            _pull_missing_image(_mongodb_image(session.config))
        except DockerException:  # pragma: no cover (mongodb_uri reports it)
            pass


@pytest.hookimpl(wrapper=True)  # pragma: lax no cover (startup; CLI verified)
def pytest_xdist_auto_num_workers() -> Generator[None, NonNegativeInt, NonNegativeInt]:
    # Xdist's configured count can be zero to disable distribution.
    detected_workers = yield
    return min(detected_workers, 4)


@pytest.hookimpl(tryfirst=True)  # pragma: lax no cover (startup; CLI verified)
def pytest_configure(config: pytest.Config) -> None:
    if not hasattr(config, "workerinput"):
        return
    log_destination = config.getoption("log_file") or config.getini("log_file")
    if log_destination == os.devnull:
        return
    log_path = Path(log_destination)
    worker_id = config.workerinput["workerid"]
    config.option.log_file = str(
        log_path.with_name(f"{log_path.stem}-{worker_id}{log_path.suffix}")
    )


def _wait_for_mongodb_ping(client: MongoClient[BsonDict]) -> None:
    last_ping_error: AutoReconnect | None = None
    deadline = monotonic() + _MONGODB_STARTUP_TIMEOUT_SECONDS
    while monotonic() < deadline:
        try:
            client.admin.command("ping")
        except AutoReconnect as error:  # pragma: lax no cover (startup varies)
            last_ping_error = error
            sleep(_MONGODB_POLL_INTERVAL_SECONDS)
        else:
            return
    message = (  # pragma: no cover (requires an unreachable container)
        f"MongoDB did not become reachable within "
        f"{_MONGODB_STARTUP_TIMEOUT_SECONDS:.0f} seconds after container start."
    )
    raise pytest.fail.Exception(message) from last_ping_error  # pragma: no cover


def _prepare_mongodb(config: pytest.Config) -> pytest.CallInfo[MongoDbUri]:
    try:
        return config.stash[_MONGODB_SESSION]
    except KeyError:
        resources = ExitStack()
        config.stash[_MONGODB_RESOURCES] = resources
        config.add_cleanup(resources.close)
        startup = pytest.CallInfo.from_call(
            lambda: resources.enter_context(_mongodb_replica_set(config)),
            when="setup",
            reraise=(KeyboardInterrupt, pytest.exit.Exception),
        )
        config.stash[_MONGODB_SESSION] = startup
        return startup


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_protocol(item: pytest.Item) -> Generator[None, bool, bool]:
    # Prepare only a worker's assigned resource, before pytest-timeout starts
    # timing fixture setup, the test body, and teardown.
    if isinstance(item, pytest.Function) and "_mongodb_session" in item.fixturenames:
        _prepare_mongodb(item.config)
    return (yield)


@pytest.fixture(autouse=True)
def log_when_test_starts(request: pytest.FixtureRequest) -> None:
    cls_ = f"{request.cls}." if request.cls else ""
    logger.debug("Starting '%s%s'...", cls_, request.node.name)


@pytest.fixture
def cached_database_name() -> DatabaseName:
    # Session databases outlive tests; Faker reseeds per test and can repeat names.
    return DatabaseName(f"test_{uuid.uuid4().hex}")


@pytest.fixture
def persistent_collection_name() -> CollectionName:
    return CollectionName("persistent_collection")


@pytest.fixture
def nonpersistent_collection_name() -> CollectionName:
    return CollectionName("nonpersistent_collection")


@pytest.fixture(scope="session")
def mongodb_uri(_mongodb_session: MongoDbUri) -> MongoDbUri:
    return _mongodb_session


@pytest.fixture(scope="session")
def _mongodb_session(request: pytest.FixtureRequest) -> Iterator[MongoDbUri]:
    startup = _prepare_mongodb(request.config)
    with request.config.stash[_MONGODB_RESOURCES]:
        if startup.excinfo is not None:  # pragma: lax no cover (CLI failure verified)
            raise startup.excinfo.value
        yield startup.result


@contextmanager
def _mongodb_replica_set(config: pytest.Config) -> Generator[MongoDbUri]:
    with ExitStack() as resources:
        try:
            container = DockerContainer(_mongodb_image(config))
            # MongoDB: https://www.mongodb.com/docs/manual/reference/program/mongod/
            # --replSet: The default is no replica set. We override it because the
            # disposable runtime must support change streams.
            container.with_command(["--replSet", "rs0"])
            container.with_exposed_ports(27017)
            resources.enter_context(container)
            resources.push(
                lambda _type, error, _tb: note_mongodb_startup_failure(container, error)
            )
        except DockerException as error:  # pragma: no cover (requires a broken runtime)
            message = (
                "A Docker-compatible container runtime is required for integration "
                "and end-to-end tests. Start Docker or a rootless Podman socket and "
                f"try again. Container startup failed: {error}"
            )
            raise pytest.fail.Exception(message, pytrace=False) from None

        host = container.get_container_host_ip()
        port = container.get_exposed_port(27017)
        # PyMongo 4.18:
        # https://pymongo.readthedocs.io/en/4.18.1/api/pymongo/mongo_client.html
        # directConnection: The default is false. We override it because discovery would
        # follow the internally advertised localhost address instead of the mapped port.
        uri = MongoDbUri(f"mongodb://{host}:{port}/?directConnection=true")

        # serverSelectionTimeoutMS: The default is 30000 ms. We override it because
        # bounded startup polling needs short connection attempts.
        # PyMongo timeout(): The default is no operation deadline. Bound the two
        # readiness phases together, including command I/O, outside test timing.
        with (
            MongoClient[BsonDict](uri, serverSelectionTimeoutMS=1_000) as client,
            timeout(2 * _MONGODB_STARTUP_TIMEOUT_SECONDS),
        ):
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
                        break
                except AutoReconnect:  # pragma: lax no cover (election timing varies)
                    pass
                sleep(_MONGODB_POLL_INTERVAL_SECONDS)
            else:
                pytest.fail(  # pragma: no cover (requires a stuck container)
                    "MongoDB did not elect a writable primary within 30 seconds."
                )
        yield uri


@pytest.fixture
def make_fake_document(faker: Faker) -> Callable[..., BsonDict]:
    def _make_fake_document() -> BsonDict:
        document = faker.pydict()
        # Benchmark collections outlive tests, so IDs must survive Faker reseeding.
        document["_id"] = str(uuid.uuid4())

        mongo_compatible_document: BsonDict = {}
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


pytest_plugins = ("tests.cursor_fixtures",)
