from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from pymongo import AsyncMongoClient
from pymongo.errors import ConnectionFailure, OperationFailure

from mongo_client_cache._core.keys import NamespaceId
from mongo_client_cache._core.manager import CacheCore
from mongo_client_cache.asynchronous.streams import DatabaseStreamSupervisor

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from pymongo.asynchronous.database import AsyncDatabase

    from tests.conftest import DatabaseName, MongoDbUri

pytestmark = pytest.mark.integration


@pytest.fixture
async def independent_writer(
    mongodb_uri: MongoDbUri,
) -> AsyncIterator[AsyncMongoClient[dict[str, Any]]]:
    async with AsyncMongoClient[dict[str, Any]](mongodb_uri) as client:
        yield client


@pytest.fixture
async def make_supervisor() -> AsyncIterator[Callable[..., DatabaseStreamSupervisor]]:
    supervisors: list[DatabaseStreamSupervisor] = []

    def _make(
        database: AsyncDatabase[Any],
        cache: CacheCore,
        **kwargs: Any,  # noqa: ANN401
    ) -> DatabaseStreamSupervisor:
        supervisor = DatabaseStreamSupervisor(database, cache, **kwargs)
        supervisors.append(supervisor)
        return supervisor

    yield _make
    for supervisor in supervisors:
        await supervisor.stop()


async def _wait_until(
    predicate: Callable[[], bool], *, timeout_seconds: float = 15.0
) -> None:
    async def _poll() -> None:
        while not predicate():  # noqa: ASYNC110 (generic predicate, no single Event)
            await asyncio.sleep(0.05)

    try:
        async with asyncio.timeout(timeout_seconds):
            await _poll()
    except TimeoutError:  # pragma: no cover (test timeout diagnostic)
        pytest.fail("condition was not met within the timeout")


async def test_update_invalidates_the_cached_document(
    raw_mongo_client: AsyncMongoClient[dict[str, Any]],
    independent_writer: AsyncMongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    namespace = NamespaceId(cached_database_name, "items")
    await independent_writer[cached_database_name]["items"].insert_one(
        {"_id": "doc-1", "v": 1}
    )
    cache = CacheCore()
    supervisor = make_supervisor(raw_mongo_client[cached_database_name], cache)
    await supervisor.start()

    capture = cache.begin_identity_admission(namespace, "doc-1")
    cache.admit_identity(capture, "full", {"v": 1})
    assert cache.lookup_identity(namespace, "doc-1", "full").hit is True

    await independent_writer[cached_database_name]["items"].update_one(
        {"_id": "doc-1"}, {"$set": {"v": 2}}
    )

    await _wait_until(
        lambda: cache.lookup_identity(namespace, "doc-1", "full").hit is False
    )


async def test_delete_invalidates_the_cached_document(
    raw_mongo_client: AsyncMongoClient[dict[str, Any]],
    independent_writer: AsyncMongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    namespace = NamespaceId(cached_database_name, "items")
    await independent_writer[cached_database_name]["items"].insert_one(
        {"_id": "doc-1", "v": 1}
    )
    cache = CacheCore()
    supervisor = make_supervisor(raw_mongo_client[cached_database_name], cache)
    await supervisor.start()

    capture = cache.begin_identity_admission(namespace, "doc-1")
    cache.admit_identity(capture, "full", {"v": 1})
    assert cache.lookup_identity(namespace, "doc-1", "full").hit is True

    await independent_writer[cached_database_name]["items"].delete_one({"_id": "doc-1"})

    await _wait_until(
        lambda: cache.lookup_identity(namespace, "doc-1", "full").hit is False
    )


async def test_drop_clears_the_namespace(
    raw_mongo_client: AsyncMongoClient[dict[str, Any]],
    independent_writer: AsyncMongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    namespace = NamespaceId(cached_database_name, "items")
    await independent_writer[cached_database_name]["items"].insert_one(
        {"_id": "doc-1", "v": 1}
    )
    cache = CacheCore()
    supervisor = make_supervisor(raw_mongo_client[cached_database_name], cache)
    await supervisor.start()

    capture = cache.begin_identity_admission(namespace, "doc-1")
    cache.admit_identity(capture, "full", {"v": 1})
    assert cache.lookup_identity(namespace, "doc-1", "full").hit is True

    await independent_writer[cached_database_name].drop_collection("items")

    await _wait_until(
        lambda: cache.lookup_identity(namespace, "doc-1", "full").hit is False
    )


async def test_rename_clears_source_and_destination_namespaces(
    raw_mongo_client: AsyncMongoClient[dict[str, Any]],
    independent_writer: AsyncMongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    source = NamespaceId(cached_database_name, "items_old")
    destination = NamespaceId(cached_database_name, "items_new")
    await independent_writer[cached_database_name]["items_old"].insert_one(
        {"_id": "doc-1"}
    )
    cache = CacheCore()
    supervisor = make_supervisor(raw_mongo_client[cached_database_name], cache)
    await supervisor.start()

    source_capture = cache.capture_namespace_generation(source)
    cache.admit_namespace(source_capture, "query", [1])
    destination_capture = cache.capture_namespace_generation(destination)
    cache.admit_namespace(destination_capture, "query", [1])
    assert cache.lookup_namespace(source, "query").hit is True
    assert cache.lookup_namespace(destination, "query").hit is True

    await independent_writer[cached_database_name]["items_old"].rename("items_new")

    await _wait_until(lambda: cache.lookup_namespace(source, "query").hit is False)
    await _wait_until(lambda: cache.lookup_namespace(destination, "query").hit is False)


async def test_drop_database_clears_the_cache_and_the_stream_recovers(
    raw_mongo_client: AsyncMongoClient[dict[str, Any]],
    independent_writer: AsyncMongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    namespace = NamespaceId(cached_database_name, "items")
    await independent_writer[cached_database_name]["items"].insert_one(
        {"_id": "doc-1", "v": 1}
    )
    cache = CacheCore()
    supervisor = make_supervisor(raw_mongo_client[cached_database_name], cache)
    await supervisor.start()

    capture = cache.begin_identity_admission(namespace, "doc-1")
    cache.admit_identity(capture, "full", {"v": 1})
    assert cache.lookup_identity(namespace, "doc-1", "full").hit is True

    await independent_writer.drop_database(cached_database_name)

    await _wait_until(
        lambda: cache.lookup_identity(namespace, "doc-1", "full").hit is False
    )
    await _wait_until(lambda: supervisor.healthy)

    await independent_writer[cached_database_name]["items"].insert_one(
        {"_id": "doc-2", "v": 1}
    )

    def _admit_and_check_doc2() -> bool:
        capture2 = cache.begin_identity_admission(namespace, "doc-2")
        cache.admit_identity(capture2, "full", {"v": 1})
        return cache.lookup_identity(namespace, "doc-2", "full").hit

    await _wait_until(_admit_and_check_doc2)

    await independent_writer[cached_database_name]["items"].update_one(
        {"_id": "doc-2"}, {"$set": {"v": 2}}
    )

    await _wait_until(
        lambda: cache.lookup_identity(namespace, "doc-2", "full").hit is False
    )


class _NextFailsOnceStream:
    __slots__ = ("_error", "_real_stream")

    def __init__(self, real_stream: object, error: Exception) -> None:
        self._real_stream = real_stream
        self._error = error

    async def next(self) -> dict[str, object]:
        raise self._error

    async def close(self) -> None:
        await self._real_stream.close()  # type: ignore[attr-defined]


async def test_recovers_from_a_resumable_disconnection(
    raw_mongo_client: AsyncMongoClient[dict[str, Any]],
    independent_writer: AsyncMongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    namespace = NamespaceId(cached_database_name, "items")
    database = raw_mongo_client[cached_database_name]
    original_watch: Any = database.watch
    call_count = 0

    async def patched_watch(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        nonlocal call_count
        call_count += 1
        real_stream = await original_watch(*args, **kwargs)
        if call_count == 1:
            return _NextFailsOnceStream(
                real_stream, ConnectionFailure("simulated transient disconnect")
            )
        return real_stream

    database.watch = patched_watch  # type: ignore[method-assign]

    cache = CacheCore()
    supervisor = make_supervisor(database, cache)
    watch_calls_after_reconnect = 2
    await supervisor.start()

    await _wait_until(
        lambda: call_count == watch_calls_after_reconnect and supervisor.healthy
    )

    await independent_writer[cached_database_name]["items"].insert_one(
        {"_id": "doc-2", "v": 1}
    )
    capture = cache.begin_identity_admission(namespace, "doc-2")
    cache.admit_identity(capture, "full", {"v": 1})
    assert cache.lookup_identity(namespace, "doc-2", "full").hit is True

    await independent_writer[cached_database_name]["items"].update_one(
        {"_id": "doc-2"}, {"$set": {"v": 2}}
    )

    await _wait_until(
        lambda: cache.lookup_identity(namespace, "doc-2", "full").hit is False
    )


async def test_clears_the_cache_when_resume_history_is_lost(
    raw_mongo_client: AsyncMongoClient[dict[str, Any]],
    independent_writer: AsyncMongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    namespace = NamespaceId(cached_database_name, "items")
    database = raw_mongo_client[cached_database_name]
    original_watch: Any = database.watch
    call_count = 0
    unresumable_watch_call = 2
    watch_calls_after_recovery = 3

    async def patched_watch(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            real_stream = await original_watch(*args, **kwargs)
            return _NextFailsOnceStream(
                real_stream, ConnectionFailure("simulated transient disconnect")
            )
        if call_count == unresumable_watch_call:
            message = "resume point is not in the oplog anymore"
            raise OperationFailure(message, code=286)
        return await original_watch(*args, **kwargs)

    database.watch = patched_watch  # type: ignore[method-assign]

    cache = CacheCore()
    supervisor = make_supervisor(database, cache)
    await supervisor.start()

    await _wait_until(
        lambda: call_count == watch_calls_after_recovery and supervisor.healthy
    )

    await independent_writer[cached_database_name]["items"].insert_one(
        {"_id": "doc-2", "v": 1}
    )
    capture = cache.begin_identity_admission(namespace, "doc-2")
    cache.admit_identity(capture, "full", {"v": 1})
    assert cache.lookup_identity(namespace, "doc-2", "full").hit is True

    await independent_writer[cached_database_name]["items"].update_one(
        {"_id": "doc-2"}, {"$set": {"v": 2}}
    )

    await _wait_until(
        lambda: cache.lookup_identity(namespace, "doc-2", "full").hit is False
    )


class _PausingStream:
    __slots__ = ("_fetched_event", "_real_stream", "_release_event")

    def __init__(
        self,
        real_stream: object,
        fetched_event: asyncio.Event,
        release_event: asyncio.Event,
    ) -> None:
        self._real_stream = real_stream
        self._fetched_event = fetched_event
        self._release_event = release_event

    async def next(self) -> dict[str, object]:
        event: dict[str, object] = await self._real_stream.next()  # type: ignore[attr-defined]
        self._fetched_event.set()
        await self._release_event.wait()
        return event

    @property
    def resume_token(self) -> object:
        return self._real_stream.resume_token  # type: ignore[attr-defined]

    async def close(self) -> None:
        await self._real_stream.close()  # type: ignore[attr-defined]


async def test_a_cache_hit_concurrent_with_event_delivery_may_be_stale_but_not_after(
    raw_mongo_client: AsyncMongoClient[dict[str, Any]],
    independent_writer: AsyncMongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    namespace = NamespaceId(cached_database_name, "items")
    await independent_writer[cached_database_name]["items"].insert_one(
        {"_id": "doc-1", "v": 1}
    )
    database = raw_mongo_client[cached_database_name]
    original_watch: Any = database.watch
    fetched_event = asyncio.Event()
    release_event = asyncio.Event()

    async def patched_watch(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        real_stream = await original_watch(*args, **kwargs)
        return _PausingStream(real_stream, fetched_event, release_event)

    database.watch = patched_watch  # type: ignore[method-assign]

    cache = CacheCore()
    supervisor = make_supervisor(database, cache)

    await supervisor.start()

    capture = cache.begin_identity_admission(namespace, "doc-1")
    cache.admit_identity(capture, "full", {"v": 1})
    assert cache.lookup_identity(namespace, "doc-1", "full").hit is True

    await independent_writer[cached_database_name]["items"].update_one(
        {"_id": "doc-1"}, {"$set": {"v": 2}}
    )

    await _wait_until(fetched_event.is_set)
    assert cache.lookup_identity(namespace, "doc-1", "full").hit is True

    release_event.set()

    await _wait_until(
        lambda: cache.lookup_identity(namespace, "doc-1", "full").hit is False
    )
