"""Compare a warm cache hit with native execution under a live server failure."""

# ruff: noqa: INP001 - Standalone research script outside the distributed package.

import json
from contextlib import contextmanager
from time import monotonic, sleep
from typing import TYPE_CHECKING
from uuid import uuid4

import pymongo
import pytest
from pymongo import MongoClient
from pymongo.errors import AutoReconnect, OperationFailure
from pymongo.monitoring import CommandListener
from pymongo.read_concern import ReadConcern
from testcontainers.core.container import DockerContainer

from client_query_cache import CachedCollection, CacheManager
from tests.conftest import _wait_for_mongodb_ping  # noqa: PLC2701 - Reuse the repository fixture readiness check.

if TYPE_CHECKING:
    from collections.abc import Generator

    from pymongo.monitoring import (
        CommandFailedEvent,
        CommandStartedEvent,
        CommandSucceededEvent,
    )

Document = dict[str, object]  # Can be empty for native projections.
APP_NAME = "collection_adapter_live_error"
ERROR_CODE = 2  # BadValue is not retried by the driver.


class ReadCommands(CommandListener):
    def __init__(self, database: str) -> None:  # Database name is nonempty.
        self.database = database
        self.count = 0  # Can be zero before a count command executes.

    def started(self, event: CommandStartedEvent) -> None:
        if event.database_name == self.database and event.command_name == "aggregate":
            pipeline = event.command["pipeline"]
            if pipeline and "$match" in pipeline[0]:
                self.count += 1

    def succeeded(self, event: CommandSucceededEvent) -> None:
        pass

    def failed(self, event: CommandFailedEvent) -> None:
        pass


@contextmanager
def fixture() -> Generator[MongoClient[Document]]:
    container = DockerContainer("mongo:8.0.4-noble").with_exposed_ports(27017)
    container.with_command(
        ["--replSet", "rs0", "--bind_ip_all", "--setParameter", "enableTestCommands=1"]
    )
    with container:
        uri = f"mongodb://{container.get_container_host_ip()}:{container.get_exposed_port(27017)}/?directConnection=true"
        with MongoClient[Document](uri, serverSelectionTimeoutMS=1000) as control:
            _wait_for_mongodb_ping(control)
            control.admin.command(
                "replSetInitiate",
                {"_id": "rs0", "members": [{"_id": 0, "host": "localhost:27017"}]},
            )
            deadline = monotonic() + 30
            while monotonic() < deadline:
                try:
                    if control.admin.command("hello")["isWritablePrimary"]:
                        break
                except AutoReconnect:
                    pass
                sleep(0.05)
            else:
                raise RuntimeError("Disposable replica set did not elect a primary")
            yield control


def warm(view: CachedCollection[Document], manager: CacheManager[Document]) -> None:
    deadline = monotonic() + 15
    while monotonic() < deadline:
        hits = manager.snapshot().hits
        assert view.count_documents({}) == 1
        if manager.snapshot().hits > hits:
            return
        sleep(0.05)
    raise RuntimeError("Disposable cache did not become warm")


@contextmanager
def failure(control: MongoClient[Document]) -> Generator[None]:
    control.admin.command(
        "configureFailPoint",
        "failCommand",
        mode="alwaysOn",
        data={
            "failCommands": ["aggregate"],
            "appName": APP_NAME,
            "errorCode": ERROR_CODE,
        },
    )
    try:
        yield
    finally:
        control.admin.command("configureFailPoint", "failCommand", mode="off")


def run(control: MongoClient[Document]) -> None:
    database = "adapter_error_" + uuid4().hex
    commands = ReadCommands(database)
    address = control.address
    assert address is not None
    with MongoClient[Document](
        address[0],
        address[1],
        directConnection=True,
        appName=APP_NAME,
        event_listeners=[commands],
    ) as client:
        raw = client[database]["records"].with_options(
            read_concern=ReadConcern("majority")
        )
        raw.insert_one({"_id": "one-record"})
        with CacheManager(client) as manager:
            view = manager.cached(raw)
            warm(view, manager)
            with failure(control):
                before = commands.count
                with pytest.raises(OperationFailure) as native_error:
                    raw.count_documents({})
                assert native_error.value.code == ERROR_CODE
                assert commands.count == before + 1
                hits = manager.snapshot().hits  # pytriage: TR5
                before = commands.count
                assert view.count_documents({}) == 1
                assert manager.snapshot().hits == hits + 1
                assert commands.count == before
                print(
                    json.dumps(
                        {
                            "pymongo": pymongo.version,
                            "server": control.server_info()["version"],
                            "native_error": ERROR_CODE,
                            "native_commands": 1,
                            "warm_value": 1,
                            "warm_commands": 0,
                            "library_hits": 1,
                        }
                    )
                )
        client.drop_database(database)


if __name__ == "__main__":
    with fixture() as control:
        run(control)
