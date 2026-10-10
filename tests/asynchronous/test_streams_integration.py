from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import pytest
from bson.codec_options import DatetimeConversion
from pymongo import AsyncMongoClient
from pymongo.errors import ConnectionFailure, OperationFailure

from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCore, CacheCoreConfig
from client_query_cache._types import (
    BsonDict,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)
from client_query_cache.asynchronous.streams import DatabaseStreamSupervisor
from tests.stream_helpers import (
    SINGLE_EVENT_LAG_WINDOW,
    assert_lag_matches_write_interval,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from faker import Faker
    from pymongo.asynchronous.database import AsyncDatabase

    from tests.conftest import CollectionName, DatabaseName, MongoDbUri

pytestmark = pytest.mark.integration


@pytest.fixture
async def independent_writer(
    mongodb_uri: MongoDbUri,
) -> AsyncIterator[AsyncMongoClient[BsonDict]]:
    async with AsyncMongoClient[BsonDict](mongodb_uri) as client:
        yield client


@pytest.fixture(
    params=[
        pytest.param({"tz_aware": True}, id="tz_aware"),
        pytest.param(
            {"datetime_conversion": DatetimeConversion.DATETIME_MS}, id="datetime_ms"
        ),
    ]
)
async def wall_time_client(
    mongodb_uri: MongoDbUri, request: pytest.FixtureRequest
) -> AsyncIterator[AsyncMongoClient[BsonDict]]:
    async with AsyncMongoClient[BsonDict](mongodb_uri, **request.param) as client:
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
    predicate: Callable[[], bool], *, timeout_seconds: PositiveFloat = 15.0
) -> None:
    async def _poll() -> None:
        while not predicate():  # noqa: ASYNC110 (generic predicate, no single Event)
            await asyncio.sleep(0.05)

    try:
        async with asyncio.timeout(timeout_seconds):
            await _poll()
    except TimeoutError:  # pragma: no cover (test timeout diagnostic)
        pytest.fail("condition was not met within the timeout")


@pytest.mark.parametrize(
    "invalidate",
    [
        pytest.param(
            lambda writer, database_name, document_id, after_value: writer[
                database_name
            ]["items"].update_one({"_id": document_id}, {"$set": {"v": after_value}}),
            id="update",
        ),
        pytest.param(
            lambda writer, database_name, document_id, _after_value: writer[
                database_name
            ]["items"].delete_one({"_id": document_id}),
            id="delete",
        ),
        pytest.param(
            lambda writer, database_name, _document_id, _after_value: writer[
                database_name
            ].drop_collection("items"),
            id="drop",
        ),
    ],
)
async def test_write_invalidates_the_cached_document(
    raw_mongo_client: AsyncMongoClient[BsonDict],
    independent_writer: AsyncMongoClient[BsonDict],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    invalidate: Callable[
        [AsyncMongoClient[BsonDict], DatabaseName, str, NonNegativeInt],
        Awaitable[object],
    ],
    *,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    before_value = faker.random_int()
    after_value = before_value + 1
    namespace = NamespaceId(cached_database_name, "items")
    await independent_writer[cached_database_name]["items"].insert_one(
        {"_id": document_id, "v": before_value}
    )
    cache = CacheCore()
    supervisor = make_supervisor(raw_mongo_client[cached_database_name], cache)
    await supervisor.start()

    capture = cache.begin_identity_admission(namespace, document_id)
    cache.admit_identity(capture, "full", {"v": before_value})
    assert cache.lookup_identity(namespace, document_id, "full").hit is True

    await invalidate(independent_writer, cached_database_name, document_id, after_value)

    await _wait_until(
        lambda: cache.lookup_identity(namespace, document_id, "full").hit is False
    )


async def test_configured_wall_time_stream_records_invalidation_lag(
    wall_time_client: AsyncMongoClient[BsonDict],
    independent_writer: AsyncMongoClient[BsonDict],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    *,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    before_value = faker.random_int()
    namespace = NamespaceId(cached_database_name, persistent_collection_name)
    writer_collection = independent_writer[cached_database_name][
        persistent_collection_name
    ]
    await writer_collection.insert_one({"_id": document_id, "v": before_value})
    cache = CacheCore(
        CacheCoreConfig(lag_capture_window_config=SINGLE_EVENT_LAG_WINDOW)
    )
    supervisor = make_supervisor(wall_time_client[cached_database_name], cache)
    await supervisor.start()

    capture = cache.begin_identity_admission(namespace, document_id)
    cache.admit_identity(capture, "full", {"v": before_value})
    assert cache.lookup_identity(namespace, document_id, "full").hit

    write_started = time.time()
    await writer_collection.update_one(
        {"_id": document_id}, {"$set": {"v": before_value + 1}}
    )
    write_finished = time.time()

    await _wait_until(
        lambda: cache.stream_cost_snapshot(cached_database_name).invalidations >= 1
    )
    assert cache.lookup_identity(namespace, document_id, "full").hit is False
    snapshot = cache.stream_cost_snapshot(cached_database_name)
    assert_lag_matches_write_interval(snapshot, write_started, write_finished)


async def test_rename_clears_source_and_destination_namespaces(
    raw_mongo_client: AsyncMongoClient[BsonDict],
    independent_writer: AsyncMongoClient[BsonDict],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    source = NamespaceId(cached_database_name, "items_old")
    destination = NamespaceId(cached_database_name, "items_new")
    await independent_writer[cached_database_name]["items_old"].insert_one(
        {"_id": document_id}
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
    raw_mongo_client: AsyncMongoClient[BsonDict],
    independent_writer: AsyncMongoClient[BsonDict],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    other_document_id = faker.uuid4()
    before_value = faker.random_int()
    namespace = NamespaceId(cached_database_name, "items")
    await independent_writer[cached_database_name]["items"].insert_one(
        {"_id": document_id, "v": before_value}
    )
    cache = CacheCore()
    supervisor = make_supervisor(raw_mongo_client[cached_database_name], cache)
    await supervisor.start()

    capture = cache.begin_identity_admission(namespace, document_id)
    cache.admit_identity(capture, "full", {"v": before_value})
    assert cache.lookup_identity(namespace, document_id, "full").hit is True

    await independent_writer.drop_database(cached_database_name)

    await _wait_until(
        lambda: cache.lookup_identity(namespace, document_id, "full").hit is False
    )
    await _wait_until(lambda: supervisor.healthy)

    await independent_writer[cached_database_name]["items"].insert_one(
        {"_id": other_document_id, "v": before_value}
    )

    def _admit_and_check_doc2() -> bool:
        capture2 = cache.begin_identity_admission(namespace, other_document_id)
        cache.admit_identity(capture2, "full", {"v": before_value})
        return cache.lookup_identity(namespace, other_document_id, "full").hit

    await _wait_until(_admit_and_check_doc2)

    after_value = before_value + 1
    await independent_writer[cached_database_name]["items"].update_one(
        {"_id": other_document_id}, {"$set": {"v": after_value}}
    )

    await _wait_until(
        lambda: cache.lookup_identity(namespace, other_document_id, "full").hit is False
    )


class _NextFailsOnceStream:
    __slots__ = ("_error", "_real_stream")

    def __init__(self, real_stream: object, error: Exception) -> None:
        self._real_stream = real_stream
        self._error = error

    async def next(self) -> BsonDict:
        raise self._error

    async def close(self) -> None:
        await self._real_stream.close()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("lost_history_watch_call", "watch_calls_after_recovery"),
    [
        pytest.param(None, 2, id="resumable-disconnection"),
        pytest.param(2, 3, id="lost-resume-history"),
    ],
)
async def test_recovers_from_a_stream_failure(
    raw_mongo_client: AsyncMongoClient[BsonDict],
    independent_writer: AsyncMongoClient[BsonDict],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    *,
    lost_history_watch_call: PositiveInt | None,
    watch_calls_after_recovery: PositiveInt,
    faker: Faker,
) -> None:
    other_document_id = faker.uuid4()
    before_value = faker.random_int()
    namespace = NamespaceId(cached_database_name, "items")
    database = raw_mongo_client[cached_database_name]
    original_watch: Any = database.watch
    call_count = 0

    async def patched_watch(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        nonlocal call_count
        call_count += 1
        if call_count == lost_history_watch_call:
            message = "resume point is not in the oplog anymore"
            raise OperationFailure(message, code=286)
        real_stream = await original_watch(*args, **kwargs)
        if call_count == 1:
            return _NextFailsOnceStream(
                real_stream, ConnectionFailure("simulated transient disconnect")
            )
        return real_stream

    database.watch = patched_watch  # type: ignore[method-assign]

    cache = CacheCore()
    supervisor = make_supervisor(database, cache)
    await supervisor.start()

    await _wait_until(
        lambda: call_count == watch_calls_after_recovery and supervisor.healthy
    )

    await independent_writer[cached_database_name]["items"].insert_one(
        {"_id": other_document_id, "v": before_value}
    )
    capture = cache.begin_identity_admission(namespace, other_document_id)
    cache.admit_identity(capture, "full", {"v": before_value})
    assert cache.lookup_identity(namespace, other_document_id, "full").hit is True

    after_value = before_value + 1
    await independent_writer[cached_database_name]["items"].update_one(
        {"_id": other_document_id}, {"$set": {"v": after_value}}
    )

    await _wait_until(
        lambda: cache.lookup_identity(namespace, other_document_id, "full").hit is False
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

    async def next(self) -> BsonDict:
        event: BsonDict = await self._real_stream.next()  # type: ignore[attr-defined]
        self._fetched_event.set()
        await self._release_event.wait()
        return event

    @property
    def resume_token(self) -> object:
        return self._real_stream.resume_token  # type: ignore[attr-defined]

    async def close(self) -> None:
        await self._real_stream.close()  # type: ignore[attr-defined]


async def test_a_cache_hit_concurrent_with_event_delivery_may_be_stale_but_not_after(
    raw_mongo_client: AsyncMongoClient[BsonDict],
    independent_writer: AsyncMongoClient[BsonDict],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    before_value = faker.random_int()
    namespace = NamespaceId(cached_database_name, "items")
    await independent_writer[cached_database_name]["items"].insert_one(
        {"_id": document_id, "v": before_value}
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

    capture = cache.begin_identity_admission(namespace, document_id)
    cache.admit_identity(capture, "full", {"v": before_value})
    assert cache.lookup_identity(namespace, document_id, "full").hit is True

    after_value = before_value + 1
    await independent_writer[cached_database_name]["items"].update_one(
        {"_id": document_id}, {"$set": {"v": after_value}}
    )

    await _wait_until(fetched_event.is_set)
    assert cache.lookup_identity(namespace, document_id, "full").hit is True

    release_event.set()

    await _wait_until(
        lambda: cache.lookup_identity(namespace, document_id, "full").hit is False
    )
