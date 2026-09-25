from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any

import pytest
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure

from mongo_client_cache._core.keys import NamespaceId
from mongo_client_cache._core.manager import CacheCore
from mongo_client_cache.synchronous import streams as streams_module
from mongo_client_cache.synchronous.streams import DatabaseStreamSupervisor

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

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
            lambda writer, database_name: writer[database_name]["items"].update_one(
                {"_id": "doc-1"}, {"$set": {"v": 2}}
            ),
            id="update",
        ),
        pytest.param(
            lambda writer, database_name: writer[database_name]["items"].delete_one(
                {"_id": "doc-1"}
            ),
            id="delete",
        ),
        pytest.param(
            lambda writer, database_name: writer[database_name].drop_collection(
                "items"
            ),
            id="drop",
        ),
    ],
)
def test_write_invalidates_the_cached_document(
    raw_mongo_client: MongoClient[dict[str, Any]],
    independent_writer: MongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    invalidate: Callable[[MongoClient[dict[str, Any]], DatabaseName], object],
) -> None:
    namespace = NamespaceId(cached_database_name, "items")
    independent_writer[cached_database_name]["items"].insert_one(
        {"_id": "doc-1", "v": 1}
    )
    cache = CacheCore()
    supervisor = make_supervisor(raw_mongo_client[cached_database_name], cache)
    supervisor.start()

    capture = cache.begin_identity_admission(namespace, "doc-1")
    cache.admit_identity(capture, "full", {"v": 1})
    assert cache.lookup_identity(namespace, "doc-1", "full").hit is True

    invalidate(independent_writer, cached_database_name)

    _wait_until(lambda: cache.lookup_identity(namespace, "doc-1", "full").hit is False)


def test_rename_clears_source_and_destination_namespaces(
    raw_mongo_client: MongoClient[dict[str, Any]],
    independent_writer: MongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
    source = NamespaceId(cached_database_name, "items_old")
    destination = NamespaceId(cached_database_name, "items_new")
    independent_writer[cached_database_name]["items_old"].insert_one({"_id": "doc-1"})
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
) -> None:
    namespace = NamespaceId(cached_database_name, "items")
    independent_writer[cached_database_name]["items"].insert_one(
        {"_id": "doc-1", "v": 1}
    )
    cache = CacheCore()
    supervisor = make_supervisor(raw_mongo_client[cached_database_name], cache)
    supervisor.start()

    capture = cache.begin_identity_admission(namespace, "doc-1")
    cache.admit_identity(capture, "full", {"v": 1})
    assert cache.lookup_identity(namespace, "doc-1", "full").hit is True

    independent_writer.drop_database(cached_database_name)

    _wait_until(lambda: cache.lookup_identity(namespace, "doc-1", "full").hit is False)
    _wait_until(lambda: supervisor.healthy)

    def _admit_and_check_doc2() -> bool:
        capture2 = cache.begin_identity_admission(namespace, "doc-2")
        cache.admit_identity(capture2, "full", {"v": 1})
        return cache.lookup_identity(namespace, "doc-2", "full").hit

    _wait_until(_admit_and_check_doc2)

    epoch_before_create = cache.current_epoch(namespace)
    independent_writer[cached_database_name].create_collection("items")

    _wait_until(lambda: cache.current_epoch(namespace) > epoch_before_create)
    _wait_until(lambda: supervisor.healthy)
    assert cache.lookup_identity(namespace, "doc-2", "full").hit is False

    _wait_until(_admit_and_check_doc2)

    independent_writer[cached_database_name]["items"].insert_one(
        {"_id": "doc-2", "v": 1}
    )

    _wait_until(lambda: cache.lookup_identity(namespace, "doc-2", "full").hit is False)

    capture4 = cache.begin_identity_admission(namespace, "doc-2")
    cache.admit_identity(capture4, "full", {"v": 1})
    assert cache.lookup_identity(namespace, "doc-2", "full").hit is True

    independent_writer[cached_database_name]["items"].update_one(
        {"_id": "doc-2"}, {"$set": {"v": 2}}
    )

    _wait_until(lambda: cache.lookup_identity(namespace, "doc-2", "full").hit is False)


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
) -> None:
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
        {"_id": "doc-2", "v": 1}
    )
    capture = cache.begin_identity_admission(namespace, "doc-2")
    cache.admit_identity(capture, "full", {"v": 1})
    assert cache.lookup_identity(namespace, "doc-2", "full").hit is True

    independent_writer[cached_database_name]["items"].update_one(
        {"_id": "doc-2"}, {"$set": {"v": 2}}
    )

    _wait_until(lambda: cache.lookup_identity(namespace, "doc-2", "full").hit is False)


def test_clears_the_cache_when_resume_history_is_lost(
    raw_mongo_client: MongoClient[dict[str, Any]],
    independent_writer: MongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
) -> None:
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
        {"_id": "doc-2", "v": 1}
    )
    capture = cache.begin_identity_admission(namespace, "doc-2")
    cache.admit_identity(capture, "full", {"v": 1})
    assert cache.lookup_identity(namespace, "doc-2", "full").hit is True

    independent_writer[cached_database_name]["items"].update_one(
        {"_id": "doc-2"}, {"$set": {"v": 2}}
    )

    _wait_until(lambda: cache.lookup_identity(namespace, "doc-2", "full").hit is False)


def test_a_cache_hit_concurrent_with_event_delivery_may_be_stale_but_not_after(
    raw_mongo_client: MongoClient[dict[str, Any]],
    independent_writer: MongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    make_supervisor: Callable[..., DatabaseStreamSupervisor],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = NamespaceId(cached_database_name, "items")
    independent_writer[cached_database_name]["items"].insert_one(
        {"_id": "doc-1", "v": 1}
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

    capture = cache.begin_identity_admission(namespace, "doc-1")
    cache.admit_identity(capture, "full", {"v": 1})
    assert cache.lookup_identity(namespace, "doc-1", "full").hit is True

    independent_writer[cached_database_name]["items"].update_one(
        {"_id": "doc-1"}, {"$set": {"v": 2}}
    )

    _wait_until(fetched_event.is_set)
    assert cache.lookup_identity(namespace, "doc-1", "full").hit is True

    release_event.set()

    _wait_until(lambda: cache.lookup_identity(namespace, "doc-1", "full").hit is False)
