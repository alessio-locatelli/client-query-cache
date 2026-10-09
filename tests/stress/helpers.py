from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Literal, TypedDict, cast

import pytest
from pymongo import AsyncMongoClient, MongoClient
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.collection import Collection
from pymongo.errors import ConnectionFailure, OperationFailure
from pymongo.synchronous.database import Database

from client_query_cache._core.stream_events import route_change_event
from client_query_cache._types import NonNegativeInt
from client_query_cache.asynchronous import streams as async_streams
from client_query_cache.asynchronous.manager import CacheManager as AsyncManager
from client_query_cache.synchronous import streams as sync_streams
from client_query_cache.synchronous.manager import CacheManager as SyncManager
from tests.conftest import DatabaseName

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence

    from faker import Faker
    from pymongo.asynchronous.change_stream import AsyncDatabaseChangeStream
    from pymongo.change_stream import DatabaseChangeStream

    from client_query_cache._core.manager import CacheCore
    from tests.conftest import MongoDbUri

Mode = Literal["sync", "async"]
ReadShape = Literal["identity", "namespace"]
WriteKind = Literal["insert", "update", "replace", "delete"]
CollectionName = Literal["hot", "cold"]
Target = tuple[CollectionName, str]


class Document(TypedDict):
    _id: str
    slot: str
    version: NonNegativeInt  # Zero denotes the unwritten revision.
    payload: str


async def wait_until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(10):
        while not predicate():  # noqa: ASYNC110 (public health has no awaitable notification)
            await asyncio.sleep(0.001)


class StressRun:
    __slots__ = (
        "background_reads",
        "cold_ids",
        "database",
        "deleted",
        "disconnect",
        "faker",
        "hot_ids",
        "issued",
        "lock",
        "manager",
        "mode",
        "origin_reads",
        "patches",
        "processed",
        "recovering",
        "release_read",
        "release_recovery",
        "revision",
        "writer",
    )

    def __init__(
        self,
        manager: SyncManager[Document] | AsyncManager[Document],
        writer: AsyncMongoClient[Document],
        database: DatabaseName,
        mode: Mode,
        *,
        faker: Faker,
        patches: pytest.MonkeyPatch,
    ) -> None:
        self.manager = manager
        self.writer = writer
        self.database = database
        self.mode = mode
        self.faker = faker
        self.patches = patches
        self.hot_ids = tuple(faker.uuid4() for _ in range(2))
        self.cold_ids = tuple(faker.uuid4() for _ in range(8))
        self.issued: dict[Target, NonNegativeInt] = {}  # Zero means unwritten.
        self.processed: dict[Target, NonNegativeInt] = {}  # Zero means unwritten.
        self.deleted: dict[Target, NonNegativeInt] = {}  # Zero means unwritten.
        self.origin_reads: dict[tuple[Target, ReadShape], int] = {}
        self.revision = 0
        self.background_reads = [0] * 4
        self.lock = threading.Lock()
        self.disconnect = threading.Event()
        self.recovering = asyncio.Event()
        self.release_read = threading.Event()
        self.release_recovery = threading.Event()
        module = sync_streams if mode == "sync" else async_streams
        patches.setattr(module, "route_change_event", self.route)
        self.observe_origin_reads()
        self.prepare_recovery()

    def route(
        self, core: CacheCore, database: str, event: Mapping[str, object]
    ) -> bool:
        with self.lock:
            reopen = route_change_event(core, database, event)
            assert database == self.database
            assert event["operationType"] in {
                "insert",
                "update",
                "replace",
                "delete",
            }
            namespace = cast("Mapping[str, CollectionName]", event["ns"])
            document_key = cast("Mapping[str, str]", event["documentKey"])
            target = (namespace["coll"], document_key["_id"])
            self.processed[target] = self.issued[target]
            return reopen

    async def read(self, target: Target, shape: ReadShape) -> Document | None:
        collection_name, document_id = target
        query = {"_id" if shape == "identity" else "slot": document_id}
        if isinstance(self.manager, SyncManager):
            return await asyncio.to_thread(
                self.manager[self.database][collection_name].find_one, query
            )
        return await self.manager[self.database][collection_name].find_one(query)

    async def checked_read(self, target: Target, shape: ReadShape) -> Document | None:
        with self.lock:
            try:
                minimum = self.processed[target]
            except KeyError:
                minimum = 0
        document = await self.read(target, shape)
        if document is not None:
            assert document["_id"] == target[1]
            assert document["version"] >= minimum
        else:
            with self.lock:
                try:
                    deletion = self.deleted[target]
                except KeyError:
                    deletion = 0
            assert minimum == 0 or deletion >= minimum
        return document

    async def write(self, target: Target, kind: WriteKind) -> Document | None:
        with self.lock:
            self.revision += 1
            revision = self.revision
            self.issued[target] = revision
            if kind == "delete":
                self.deleted[target] = revision
        collection = self.writer[self.database][target[0]]
        document = Document(
            _id=target[1],
            slot=target[1],
            version=revision,
            payload=self.faker.pystr(),
        )
        if kind == "insert":
            await collection.insert_one(document)
        elif kind == "update":
            await collection.update_one(
                {"_id": target[1]}, {"$set": {"version": revision}}
            )
            stored = await collection.find_one({"_id": target[1]})
            assert stored is not None
            document = stored
        elif kind == "replace":
            await collection.replace_one({"_id": target[1]}, document)
        else:
            await collection.delete_one({"_id": target[1]})
            return None
        return document

    def applied(self, target: Target) -> bool:
        with self.lock:
            try:
                return self.processed[target] == self.issued[target]
            except KeyError:
                return False

    async def checkpoint(self, target: Target, expected: Document | None) -> None:
        await wait_until(lambda: self.applied(target))
        previous_origin_reads: tuple[int, ...] = ()
        for _ in range(2):
            documents = await asyncio.gather(
                *(
                    self.checked_read(target, shape)
                    for shape in ("identity", "namespace", "identity", "namespace")
                )
            )
            assert documents == [expected] * 4
            with self.lock:
                origin_reads = tuple(
                    self.origin_reads[target, shape]
                    for shape in ("identity", "namespace")
                )
            if previous_origin_reads:
                assert origin_reads == previous_origin_reads
            previous_origin_reads = origin_reads

    @asynccontextmanager
    async def traffic(
        self, targets: Sequence[Target]
    ) -> AsyncGenerator[tuple[asyncio.Task[None], ...]]:
        stop = asyncio.Event()
        started = tuple(asyncio.Event() for _ in range(4))
        async with asyncio.TaskGroup() as workers:
            readers = tuple(
                workers.create_task(self.reader(targets, index, stop, started[index]))
                for index in range(4)
            )
            try:
                await asyncio.gather(
                    *(reader_started.wait() for reader_started in started)
                )
                yield readers
            finally:
                stop.set()

    async def reader(
        self,
        targets: Sequence[Target],
        offset: int,
        stop: asyncio.Event,
        started: asyncio.Event,
    ) -> None:
        index = offset
        while not stop.is_set():
            await self.checked_read(
                targets[index % len(targets)],
                "identity" if index % 2 == 0 else "namespace",
            )
            self.background_reads[offset] += 1
            started.set()
            index += 1
            await asyncio.sleep(0)

    def pause_read(self, target: Target) -> asyncio.Event:
        started = asyncio.Event()
        loop = asyncio.get_running_loop()
        sync_read = Collection.find_one
        async_read = AsyncCollection.find_one
        claimed = False
        claim_lock = threading.Lock()

        def claim(database: str, collection: str, query: object) -> bool:
            nonlocal claimed
            with claim_lock:
                if (
                    not claimed
                    and database == self.database
                    and collection == target[0]
                    and query in ({"_id": target[1]}, {"slot": target[1]})
                ):
                    claimed = True
                    return True
                return False

        def paused_sync(
            collection: Collection[Document],
            query: object,
            *args: object,
            **kwargs: object,
        ) -> Document | None:
            document = sync_read(collection, query, *args, **kwargs)
            if claim(collection.database.name, collection.name, query):
                loop.call_soon_threadsafe(started.set)
                assert self.release_read.wait(timeout=10)
            return document

        async def paused_async(
            collection: AsyncCollection[Document],
            query: object,
            *args: object,
            **kwargs: object,
        ) -> Document | None:
            document = await async_read(collection, query, *args, **kwargs)
            if claim(collection.database.name, collection.name, query):
                started.set()
                assert await asyncio.to_thread(self.release_read.wait, 10)
            return document

        if self.mode == "sync":
            self.patches.setattr(Collection, "find_one", paused_sync)
        else:
            self.patches.setattr(AsyncCollection, "find_one", paused_async)
        return started

    def observe_origin_reads(self) -> None:
        sync_read = Collection.find_one
        async_read = AsyncCollection.find_one

        def record(collection_name: CollectionName, query: object) -> None:
            filters = cast("Mapping[str, str]", query)
            shape: ReadShape = "identity" if "_id" in filters else "namespace"
            identity = filters["_id" if shape == "identity" else "slot"]
            key = ((collection_name, identity), shape)
            with self.lock:
                try:
                    self.origin_reads[key] += 1
                except KeyError:
                    self.origin_reads[key] = 1

        def observed_sync(
            collection: Collection[Document],
            query: object,
            *args: object,
            **kwargs: object,
        ) -> Document | None:
            record(cast("CollectionName", collection.name), query)
            return sync_read(collection, query, *args, **kwargs)

        async def observed_async(
            collection: AsyncCollection[Document],
            query: object,
            *args: object,
            **kwargs: object,
        ) -> Document | None:
            record(cast("CollectionName", collection.name), query)
            return await async_read(collection, query, *args, **kwargs)

        if self.mode == "sync":
            self.patches.setattr(Collection, "find_one", observed_sync)
        else:
            self.patches.setattr(AsyncCollection, "find_one", observed_async)

    def raise_if_disconnected(self) -> None:
        if self.disconnect.is_set():
            raise ConnectionFailure("injected stream disconnection")

    def prepare_recovery(self) -> None:
        loop = asyncio.get_running_loop()
        watch_calls = 0

        def reopening() -> bool:
            nonlocal watch_calls
            if not self.disconnect.is_set():
                return False
            watch_calls += 1
            if watch_calls == 1:
                raise OperationFailure("injected lost resume history", code=286)
            loop.call_soon_threadsafe(self.recovering.set)
            return True

        if self.mode == "sync":
            original_watch = cast(
                "Callable[..., DatabaseChangeStream[Document]]", Database.watch
            )

            def watched_sync(
                database: Database[Document],
                *args: object,
                **kwargs: object,
            ) -> DatabaseChangeStream[Document]:
                if reopening():
                    assert self.release_recovery.wait(timeout=10)
                    self.disconnect.clear()
                stream = original_watch(database, *args, **kwargs)
                original_next = stream.next

                def interrupted_next() -> Document:
                    event = original_next()  # pytriage: TR5
                    self.raise_if_disconnected()
                    return event

                self.patches.setattr(stream, "next", interrupted_next)
                return stream

            self.patches.setattr(Database, "watch", watched_sync)
        else:
            original_async_watch = cast(
                "Callable[..., Awaitable[AsyncDatabaseChangeStream[Document]]]",
                AsyncDatabase.watch,
            )

            async def watched_async(
                database: AsyncDatabase[Document],
                *args: object,
                **kwargs: object,
            ) -> AsyncDatabaseChangeStream[Document]:
                if reopening():
                    assert await asyncio.to_thread(self.release_recovery.wait, 10)
                    self.disconnect.clear()
                stream = await original_async_watch(database, *args, **kwargs)
                original_next = stream.next

                async def interrupted_next() -> Document:
                    event = await original_next()
                    self.raise_if_disconnected()
                    return event

                self.patches.setattr(stream, "next", interrupted_next)
                return stream

            self.patches.setattr(AsyncDatabase, "watch", watched_async)

    def lose_history(self) -> asyncio.Event:
        self.disconnect.set()
        return self.recovering


@asynccontextmanager
async def stress_run(
    uri: MongoDbUri, mode: Mode, faker: Faker
) -> AsyncGenerator[StressRun]:
    async with AsyncMongoClient[Document](uri, socketTimeoutMS=5000) as writer:
        database = DatabaseName(f"stress_{faker.uuid4().replace('-', '')}")
        for collection in ("hot", "cold"):
            await writer[database].create_collection(collection)
        with pytest.MonkeyPatch.context() as patches:
            if mode == "sync":
                client: MongoClient[Document] | AsyncMongoClient[Document]
                client = MongoClient[Document](uri, socketTimeoutMS=5000)
                manager: SyncManager[Document] | AsyncManager[Document] = SyncManager(
                    client
                )
            else:
                client = AsyncMongoClient[Document](uri, socketTimeoutMS=5000)
                manager = AsyncManager(client)
            run = StressRun(
                manager, writer, database, mode, faker=faker, patches=patches
            )
            try:
                await run.read(("hot", run.hot_ids[0]), "namespace")
                yield run
            finally:
                run.release_read.set()
                run.release_recovery.set()
                if isinstance(manager, SyncManager):
                    await asyncio.to_thread(manager.close)
                    assert isinstance(client, MongoClient)
                    client.close()
                else:
                    await manager.close()
                    assert isinstance(client, AsyncMongoClient)
                    await client.close()
                await writer.drop_database(database)
