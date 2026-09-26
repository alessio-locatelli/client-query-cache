from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any

import pytest
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure

from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCore
from client_query_cache.synchronous import streams as streams_module
from client_query_cache.synchronous.streams import DatabaseStreamSupervisor

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from faker import Faker
    from pymongo.synchronous.database import Database

    from tests.conftest import DatabaseName, MongoDbUri

pytestmark = pytest.mark.integration


@pytest.fixture
def independent_writer(
    mongodb_uri: MongoDbUri,
) -> Iterator[MongoClient[dict[str, Any]]]:
    with MongoClient[dict[str, Any]](mongodb_uri) as client:
        yield client


@pytest.fixture
def make_supervisor() -> Iterator[Callable[..., DatabaseStreamSupervisor]]:
    supervisors: list[DatabaseStreamSupervisor] = []

    def _make(
        database: Database[Any],
        cache: CacheCore,
        **kwargs: Any,  # noqa: ANN401
    ) -> DatabaseStreamSupervisor:
        supervisor = DatabaseStreamSupervisor(database, cache, **kwargs)
        supervisors.append(supervisor)
        return supervisor

    yield _make
    for supervisor in supervisors:
        supervisor.stop()


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    pytest.fail(  # pragma: no cover (test timeout diagnostic)
        "condition was not met within the timeout"
    )


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
def test_write_invalidates_the_cached_document(
    raw_mongo_client: MongoClient[dict[str, Any]],
    independent_writer: MongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    invalidate: Callable[[MongoClient[dict[str, Any]], DatabaseName, str, int], object],
    *,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    before_value = faker.random_int()
    after_value = before_value + 1
    namespace = NamespaceId(cached_database_name, "items")
    independent_writer[cached_database_name]["items"].insert_one(
        {"_id": document_id, "v": before_value}
    )
    cache = CacheCore()
    supervisor = make_supervisor(raw_mongo_client[cached_database_name], cache)
    supervisor.start()

    capture = cache.begin_identity_admission(namespace, document_id)
    cache.admit_identity(capture, "full", {"v": before_value})
    assert cache.lookup_identity(namespace, document_id, "full").hit is True

    invalidate(independent_writer, cached_database_name, document_id, after_value)

    _wait_until(
        lambda: cache.lookup_identity(namespace, document_id, "full").hit is False
    )


def test_rename_clears_source_and_destination_namespaces(
    raw_mongo_client: MongoClient[dict[str, Any]],
    independent_writer: MongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    source = NamespaceId(cached_database_name, "items_old")
    destination = NamespaceId(cached_database_name, "items_new")
    independent_writer[cached_database_name]["items_old"].insert_one(
        {"_id": document_id}
    )
    cache = CacheCore()
    supervisor = make_supervisor(raw_mongo_client[cached_database_name], cache)
    supervisor.start()

    source_capture = cache.capture_namespace_generation(source)
    cache.admit_namespace(source_capture, "query", [1])
    destination_capture = cache.capture_namespace_generation(destination)
    cache.admit_namespace(destination_capture, "query", [1])
    assert cache.lookup_namespace(source, "query").hit is True
    assert cache.lookup_namespace(destination, "query").hit is True

    independent_writer[cached_database_name]["items_old"].rename("items_new")

    _wait_until(lambda: cache.lookup_namespace(source, "query").hit is False)
    _wait_until(lambda: cache.lookup_namespace(destination, "query").hit is False)


def test_drop_database_clears_the_cache_and_the_stream_recovers(
    raw_mongo_client: MongoClient[dict[str, Any]],
    independent_writer: MongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    other_document_id = faker.uuid4()
    before_value = faker.random_int()
    after_value = before_value + 1
    namespace = NamespaceId(cached_database_name, "items")
    independent_writer[cached_database_name]["items"].insert_one(
        {"_id": document_id, "v": before_value}
    )
    cache = CacheCore()
    supervisor = make_supervisor(raw_mongo_client[cached_database_name], cache)
    supervisor.start()

    capture = cache.begin_identity_admission(namespace, document_id)
    cache.admit_identity(capture, "full", {"v": before_value})
    assert cache.lookup_identity(namespace, document_id, "full").hit is True

    independent_writer.drop_database(cached_database_name)

    _wait_until(
        lambda: cache.lookup_identity(namespace, document_id, "full").hit is False
    )
    _wait_until(lambda: supervisor.healthy)

    def _admit_and_check_doc2() -> bool:
        capture2 = cache.begin_identity_admission(namespace, other_document_id)
        cache.admit_identity(capture2, "full", {"v": before_value})
        return cache.lookup_identity(namespace, other_document_id, "full").hit

    _wait_until(_admit_and_check_doc2)

    epoch_before_create = cache.current_epoch(namespace)
    independent_writer[cached_database_name].create_collection("items")

    _wait_until(lambda: cache.current_epoch(namespace) > epoch_before_create)
    _wait_until(lambda: supervisor.healthy)
    assert cache.lookup_identity(namespace, other_document_id, "full").hit is False

    _wait_until(_admit_and_check_doc2)

    independent_writer[cached_database_name]["items"].insert_one(
        {"_id": other_document_id, "v": before_value}
    )

    _wait_until(
        lambda: cache.lookup_identity(namespace, other_document_id, "full").hit is False
    )

    capture4 = cache.begin_identity_admission(namespace, other_document_id)
    cache.admit_identity(capture4, "full", {"v": before_value})
    assert cache.lookup_identity(namespace, other_document_id, "full").hit is True

    independent_writer[cached_database_name]["items"].update_one(
        {"_id": other_document_id}, {"$set": {"v": after_value}}
    )

    _wait_until(
        lambda: cache.lookup_identity(namespace, other_document_id, "full").hit is False
    )


class _NextFailsOnceStream:
    __slots__ = ("_error", "_real_stream")

    def __init__(self, real_stream: object, error: Exception) -> None:
        self._real_stream = real_stream
        self._error = error

    def next(self) -> dict[str, object]:
        raise self._error

    def close(self) -> None:
        self._real_stream.close()  # type: ignore[attr-defined]


def test_recovers_from_a_resumable_disconnection(
    raw_mongo_client: MongoClient[dict[str, Any]],
    independent_writer: MongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    faker: Faker,
) -> None:
    other_document_id = faker.uuid4()
    before_value = faker.random_int()
    after_value = before_value + 1
    namespace = NamespaceId(cached_database_name, "items")
    database = raw_mongo_client[cached_database_name]
    original_watch: Any = database.watch
    call_count = 0

    def patched_watch(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        nonlocal call_count
        call_count += 1
        real_stream = original_watch(*args, **kwargs)
        if call_count == 1:
            return _NextFailsOnceStream(
                real_stream, ConnectionFailure("simulated transient disconnect")
            )
        return real_stream

    database.watch = patched_watch  # type: ignore[method-assign]

    cache = CacheCore()
    supervisor = make_supervisor(database, cache)
    watch_calls_after_reconnect = 2
    supervisor.start()

    _wait_until(
        lambda: call_count == watch_calls_after_reconnect and supervisor.healthy
    )

    independent_writer[cached_database_name]["items"].insert_one(
        {"_id": other_document_id, "v": before_value}
    )
    capture = cache.begin_identity_admission(namespace, other_document_id)
    cache.admit_identity(capture, "full", {"v": before_value})
    assert cache.lookup_identity(namespace, other_document_id, "full").hit is True

    independent_writer[cached_database_name]["items"].update_one(
        {"_id": other_document_id}, {"$set": {"v": after_value}}
    )

    _wait_until(
        lambda: cache.lookup_identity(namespace, other_document_id, "full").hit is False
    )


def test_clears_the_cache_when_resume_history_is_lost(
    raw_mongo_client: MongoClient[dict[str, Any]],
    independent_writer: MongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    faker: Faker,
) -> None:
    other_document_id = faker.uuid4()
    before_value = faker.random_int()
    after_value = before_value + 1
    namespace = NamespaceId(cached_database_name, "items")
    database = raw_mongo_client[cached_database_name]
    original_watch: Any = database.watch
    call_count = 0
    unresumable_watch_call = 2
    watch_calls_after_recovery = 3

    def patched_watch(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            real_stream = original_watch(*args, **kwargs)
            return _NextFailsOnceStream(
                real_stream, ConnectionFailure("simulated transient disconnect")
            )
        if call_count == unresumable_watch_call:
            message = "resume point is not in the oplog anymore"
            raise OperationFailure(message, code=286)
        return original_watch(*args, **kwargs)

    database.watch = patched_watch  # type: ignore[method-assign]

    cache = CacheCore()
    supervisor = make_supervisor(database, cache)
    supervisor.start()

    _wait_until(lambda: call_count == watch_calls_after_recovery and supervisor.healthy)

    independent_writer[cached_database_name]["items"].insert_one(
        {"_id": other_document_id, "v": before_value}
    )
    capture = cache.begin_identity_admission(namespace, other_document_id)
    cache.admit_identity(capture, "full", {"v": before_value})
    assert cache.lookup_identity(namespace, other_document_id, "full").hit is True

    independent_writer[cached_database_name]["items"].update_one(
        {"_id": other_document_id}, {"$set": {"v": after_value}}
    )

    _wait_until(
        lambda: cache.lookup_identity(namespace, other_document_id, "full").hit is False
    )


def test_a_cache_hit_concurrent_with_event_delivery_may_be_stale_but_not_after(
    raw_mongo_client: MongoClient[dict[str, Any]],
    independent_writer: MongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    monkeypatch: pytest.MonkeyPatch,
    *,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    before_value = faker.random_int()
    after_value = before_value + 1
    namespace = NamespaceId(cached_database_name, "items")
    independent_writer[cached_database_name]["items"].insert_one(
        {"_id": document_id, "v": before_value}
    )
    cache = CacheCore()
    supervisor = make_supervisor(raw_mongo_client[cached_database_name], cache)

    original_route_change_event: Any = streams_module.route_change_event  # type: ignore[attr-defined]
    fetched_event = threading.Event()
    release_event = threading.Event()

    def blocking_route_change_event(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        fetched_event.set()
        release_event.wait(timeout=15)
        return original_route_change_event(*args, **kwargs)

    monkeypatch.setattr(
        streams_module, "route_change_event", blocking_route_change_event
    )

    supervisor.start()

    capture = cache.begin_identity_admission(namespace, document_id)
    cache.admit_identity(capture, "full", {"v": before_value})
    assert cache.lookup_identity(namespace, document_id, "full").hit is True

    independent_writer[cached_database_name]["items"].update_one(
        {"_id": document_id}, {"$set": {"v": after_value}}
    )

    _wait_until(fetched_event.is_set)
    assert cache.lookup_identity(namespace, document_id, "full").hit is True

    release_event.set()

    _wait_until(
        lambda: cache.lookup_identity(namespace, document_id, "full").hit is False
    )
