from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Any, TypedDict

import pytest
from pymongo import AsyncMongoClient, MongoClient
from pymongo.asynchronous.command_cursor import AsyncCommandCursor
from pymongo.monitoring import CommandListener

from client_query_cache._core.manager import CacheCoreConfig
from client_query_cache.asynchronous import CachedCollection as AsyncCachedCollection
from client_query_cache.asynchronous import CacheManager as AsyncCacheManager
from client_query_cache.synchronous import CachedCollection, CacheManager
from tests.cursor_helpers import (
    ReadCursor,
    materialize,
)
from tests.polling import wait_until_async

if TYPE_CHECKING:
    from pymongo.monitoring import (
        CommandFailedEvent,
        CommandStartedEvent,
        CommandSucceededEvent,
    )

    from tests.conftest import CollectionName, DatabaseName, MongoDbUri

pytestmark = pytest.mark.integration
type Document = dict[str, Any]  # Empty projections are valid.
type View = CachedCollection[Document] | AsyncCachedCollection[Document]
type CursorFactory = Callable[
    [View], ReadCursor[Document] | Awaitable[AsyncCommandCursor[Document]]
]
DOCUMENT_COUNT = 240  # Exceeds MongoDB's default initial find batch.


class ReadCommands(CommandListener):
    def __init__(self, collection: str) -> None:
        self.collection = collection
        self.commands: list[
            Mapping[str, Any]
        ] = []  # No query runs during find construction.

    def started(self, event: CommandStartedEvent) -> None:
        command = event.command
        if event.command_name in {"find", "aggregate", "getMore", "killCursors"} and (
            command[event.command_name] == self.collection
            or ("collection" in command and command["collection"] == self.collection)
        ):
            self.commands.append(dict(command))

    def succeeded(self, event: CommandSucceededEvent) -> None:
        pass

    def failed(self, event: CommandFailedEvent) -> None:
        pass


class Binding(TypedDict):
    view: View
    commands: ReadCommands
    documents: list[Document]


@pytest.fixture(params=("sync", "async"))
async def cursors(
    request: pytest.FixtureRequest,
    mongodb_uri: MongoDbUri,
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> AsyncIterator[Binding]:
    commands = ReadCommands(nonpersistent_collection_name)
    api, count, payload_bytes, entry_limit = (
        request.param
        if isinstance(request.param, tuple)
        else (request.param, DOCUMENT_COUNT, 0, 1024 * 1024)
    )
    config = CacheCoreConfig(max_entry_bytes=entry_limit)
    async with AsyncExitStack() as stack:
        if api == "sync":
            client = stack.enter_context(
                MongoClient[Document](mongodb_uri, event_listeners=[commands])
            )
            manager = stack.enter_context(CacheManager(client, cache_config=config))
            view: View = manager[cached_database_name][nonpersistent_collection_name]
        else:
            async_client = await stack.enter_async_context(
                AsyncMongoClient[Document](mongodb_uri, event_listeners=[commands])
            )
            async_manager = await stack.enter_async_context(
                AsyncCacheManager(async_client, cache_config=config)
            )
            view = async_manager[cached_database_name][nonpersistent_collection_name]
        documents = [
            {
                "_id": n,
                "value": n,
                "nested": {"original": True},
                "payload": "x" * payload_bytes,
            }
            for n in range(count)
        ]
        inserted = view.raw.insert_many(documents)
        if isinstance(inserted, Awaitable):
            await inserted

        async def warm() -> bool:
            before = view.database.manager.snapshot().hits
            assert await materialize(view.find({"_id": "warmup"})) == []
            return view.database.manager.snapshot().hits > before

        await wait_until_async(warm)
        view.database.manager.cache_core.clear_namespace(view._namespace())
        commands.commands.clear()
        yield {"view": view, "commands": commands, "documents": documents}
        dropped = view.raw.database.client.drop_database(cached_database_name)
        if isinstance(dropped, Awaitable):
            await dropped


@pytest.fixture(params=("find", "aggregate"))
def cursor_factory(request: pytest.FixtureRequest) -> CursorFactory:
    if request.param == "find":
        return lambda view: view.find({}).sort("_id")
    return lambda view: view.aggregate([{"$sort": {"_id": 1}}])
