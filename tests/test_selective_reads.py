from __future__ import annotations

import asyncio
import gc
import weakref
from contextlib import AsyncExitStack
from functools import partial
from typing import TYPE_CHECKING, NotRequired, TypedDict

import pytest
from bson import BSON, ObjectId
from bson.decimal128 import Decimal128
from bson.int64 import Int64
from pymongo import AsyncMongoClient, MongoClient
from pymongo.asynchronous.cursor import AsyncCursor
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import ConnectionFailure, OperationFailure

from client_query_cache import CacheCore, CacheCoreConfig, SelectiveInvalidation
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.selective_invalidation import partition_scalar
from client_query_cache._core.stream_events import route_change_event
from client_query_cache._types import BsonDict, NonNegativeInt, PositiveInt
from client_query_cache.asynchronous import CacheManager as AsyncCacheManager
from client_query_cache.asynchronous import streams as asynchronous_streams
from client_query_cache.synchronous import CacheManager
from client_query_cache.synchronous import streams as synchronous_streams
from tests.cursor_fixtures import ReadCommands, View
from tests.cursor_helpers import materialize, resolved
from tests.polling import wait_until_async

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator
    from typing import Any

    from pymongo.asynchronous.change_stream import AsyncDatabaseChangeStream
    from pymongo.message import _GetMore, _Query
    from pymongo.synchronous.change_stream import DatabaseChangeStream

    from client_query_cache._core.contracts import LocalCacheCore, NamespaceCaptureView
    from client_query_cache._core.keys import NamespaceId
    from tests.conftest import CollectionName, DatabaseName, MongoDbUri
    from tests.stream_helpers import StreamBarrier

pytestmark = pytest.mark.integration
type ProjectedEvent = dict[str, Any]
type DatabaseStream = (
    DatabaseChangeStream[BsonDict] | AsyncDatabaseChangeStream[BsonDict]
)


class CollationOptions(TypedDict, total=False):
    collation: dict[str, str]


class SelectiveReads(TypedDict):
    view: View
    commands: ReadCommands
    policy: SelectiveInvalidation
    sibling: View


class Recovery(TypedDict):
    arm: Callable[[], None]
    pipelines: list[object]
    history_loss: bool


class PausedRead(TypedDict):
    entered: asyncio.Event
    tasks: list[asyncio.Task[list[BsonDict]]]


class DormantCapture(TypedDict):
    core: LocalCacheCore
    namespace: NamespaceId
    cursor: NotRequired[AsyncCursor[BsonDict]]
    reservations: tuple[NamespaceCaptureView, ...]


@pytest.fixture
def projected_events(
    stream_barrier: StreamBarrier,
    monkeypatch: pytest.MonkeyPatch,
) -> list[ProjectedEvent]:
    events: list[ProjectedEvent] = []

    def observe(
        route: Callable[..., bool],
        cache: CacheCore,
        database: str,
        event: ProjectedEvent,
        **options: object,
    ) -> bool:
        events.append(event)
        return route(cache, database, event, **options)

    routed = stream_barrier.observe(route_change_event)
    for module in (synchronous_streams, asynchronous_streams):
        monkeypatch.setattr(module, "route_change_event", partial(observe, routed))
    return events


@pytest.fixture
def dormant_async_cursor(
    mongodb_uri: MongoDbUri,
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> Iterator[DormantCapture]:
    resources = AsyncExitStack()

    async def setup() -> DormantCapture:
        client = await resources.enter_async_context(
            AsyncMongoClient[BsonDict](mongodb_uri)
        )
        resources.push_async_callback(client.drop_database, cached_database_name)
        manager = await resources.enter_async_context(
            AsyncCacheManager(
                client,
                invalidation={
                    (
                        cached_database_name,
                        nonpersistent_collection_name,
                    ): SelectiveInvalidation(insert_partition_field="author_id"),
                },
            )
        )
        view = manager[cached_database_name][nonpersistent_collection_name]
        await view.raw.insert_many(
            [{"_id": 1, "author_id": 42}, {"_id": 2, "author_id": 42}]
        )
        await view.find({"_id": "warm"}).to_list()
        namespace = view._namespace()
        reservations = tuple(
            manager.cache_core.capture_namespace_generation(
                namespace, partition=partition_scalar(index)
            )
            for index in range(100, 1123)
        )
        cursor = view.find({"author_id": 42})
        assert len(await cursor.to_list(length=1)) == 1
        return {
            "core": manager.cache_core,
            "namespace": namespace,
            "cursor": cursor,
            "reservations": reservations,
        }

    with asyncio.Runner() as runner:
        try:
            yield runner.run(setup())
        finally:
            runner.run(resources.aclose())


class FailingStream:
    __slots__ = ("stream",)

    def __init__(self, stream: DatabaseStream) -> None:
        self.stream = stream

    @property
    def resume_token(self) -> object:
        return self.stream.resume_token

    @staticmethod
    def next() -> BsonDict:
        raise ConnectionFailure("injected established-stream interruption")

    def close(self) -> object:
        return self.stream.close()


@pytest.fixture
async def unmeasured_view(selective_reads: SelectiveReads) -> AsyncIterator[View]:
    view = selective_reads["view"]
    await resolved(view.database.manager.close())
    policies = {(view.database.name, view.name): selective_reads["policy"]}
    client = view.raw.database.client
    if isinstance(client, AsyncMongoClient):
        async with AsyncCacheManager(client, invalidation=policies) as manager:
            yield manager[view.database.name][view.name]
    else:
        with CacheManager(client, invalidation=policies) as sync_manager:
            yield sync_manager[view.database.name][view.name]


@pytest.fixture
async def ordinary_database_view(
    selective_reads: SelectiveReads,
) -> AsyncIterator[View]:
    configured = selective_reads["view"]
    name = configured.database.name + "_ordinary"
    view = configured.database.manager[name][configured.name]
    await resolved(view.raw.insert_one({"_id": 1, "author_id": 42}))

    async def warm() -> bool:
        before = view.database.manager.snapshot().hits
        await resolved(view.count_documents({"author_id": 42}))
        return view.database.manager.snapshot().hits > before

    await wait_until_async(warm)
    yield view
    await resolved(view.raw.database.client.drop_database(name))


@pytest.fixture
async def uniquely_indexed_view(
    selective_reads: SelectiveReads,
    stream_barrier: StreamBarrier,
) -> View:
    view = selective_reads["view"]
    await resolved(
        view.raw.update_one({"_id": 1}, {"$set": {"email": "first@example.test"}})
    )
    await resolved(
        view.raw.update_one({"_id": 2}, {"$set": {"email": "second@example.test"}})
    )
    await resolved(view.raw.create_index("email", unique=True))
    await drain(view, stream_barrier)
    return view


@pytest.fixture
def reserved_capacity(selective_reads: SelectiveReads) -> Iterator[None]:
    view = selective_reads["view"]
    core = view.database.manager.cache_core
    reservations = [
        core.capture_namespace_generation(
            view._namespace(), partition=partition_scalar(index)
        )
        for index in range(100, 1123)
    ]
    yield
    for reservation in reservations:
        reservation.release()


@pytest.fixture
async def paused_cursor_start(
    selective_reads: SelectiveReads,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[PausedRead]:
    assert isinstance(selective_reads["view"].raw.database, AsyncDatabase)
    entered = asyncio.Event()
    release = asyncio.Event()
    tasks: list[asyncio.Task[list[BsonDict]]] = []

    async def blocked(
        _cursor: AsyncCursor[BsonDict], _operation: _Query | _GetMore
    ) -> None:
        entered.set()
        await release.wait()

    monkeypatch.setattr(AsyncCursor, "_send_message", blocked)
    yield {"entered": entered, "tasks": tasks}
    release.set()
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@pytest.fixture(
    params=[
        (api, insert, updates)
        for api in ("sync", "async")
        for insert in (False, True)
        for updates in (False, True)
    ]
)
async def selective_reads(
    request: pytest.FixtureRequest,
    mongodb_uri: MongoDbUri,
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> AsyncIterator[SelectiveReads]:
    api, insert, updates, *mixed = request.param
    policy = SelectiveInvalidation(
        insert_partition_field="author_id" if insert else None,
        update_dependencies_for_counts=updates,
    )
    policies: dict[tuple[str, str], SelectiveInvalidation] = {
        (cached_database_name, nonpersistent_collection_name): policy
    }
    if mixed:
        policies[cached_database_name, "inserts"] = SelectiveInvalidation(
            insert_partition_field="author_id"
        )
        policies[cached_database_name, "counts"] = SelectiveInvalidation(
            update_dependencies_for_counts=True
        )
    commands = ReadCommands(nonpersistent_collection_name)
    config = CacheCoreConfig(enable_telemetry=True)
    async with AsyncExitStack() as stack:
        if api == "sync":
            client = stack.enter_context(
                MongoClient[BsonDict](mongodb_uri, event_listeners=[commands])
            )
            manager = stack.enter_context(
                CacheManager(client, cache_config=config, invalidation=policies)
            )
            view: View = manager[cached_database_name][nonpersistent_collection_name]
        else:
            async_client = await stack.enter_async_context(
                AsyncMongoClient[BsonDict](mongodb_uri, event_listeners=[commands])
            )
            async_manager = await stack.enter_async_context(
                AsyncCacheManager(
                    async_client, cache_config=config, invalidation=policies
                )
            )
            view = async_manager[cached_database_name][nonpersistent_collection_name]
        await resolved(
            view.raw.insert_many(
                [
                    {
                        "_id": 1,
                        "author_id": 42,
                        "views": 0,
                        "membership": True,
                        "published": True,
                        "nested": {"0": False},
                        "tags": ["python", "rust"],
                        "ambiguous.name": False,
                    },
                    {"_id": 2, "author_id": 99, "views": 0, "membership": True},
                    {"_id": 3, "author_id": 42, "views": 0, "published": True},
                ]
            )
        )

        sibling = view.database.manager[cached_database_name]["ordinary"]
        await resolved(sibling.raw.insert_one({"_id": "ordinary"}))

        async def warm(target: View) -> bool:
            before = target.database.manager.snapshot().hits
            await materialize(target.find({"_id": "warm"}))
            return target.database.manager.snapshot().hits > before

        await wait_until_async(partial(warm, sibling))
        await wait_until_async(partial(warm, view))
        commands.commands.clear()
        yield {"view": view, "commands": commands, "policy": policy, "sibling": sibling}
        await resolved(view.raw.database.client.drop_database(cached_database_name))


async def drain(view: View, barrier: StreamBarrier) -> None:
    database = view.raw.database
    if isinstance(database, AsyncDatabase):
        await barrier.wait_async(database)
    else:
        barrier.wait(database)


@pytest.mark.parametrize(
    "selective_reads",
    [("sync", True, True, True), ("async", True, True, True)],
    indirect=True,
)
async def test_projection_is_collection_scoped_and_omits_update_values(
    selective_reads: SelectiveReads,
    stream_barrier: StreamBarrier,
    projected_events: list[ProjectedEvent],
) -> None:
    view = selective_reads["view"]
    for name in ("inserts", "counts", "ordinary"):
        raw = view.raw.database[name]
        await resolved(raw.insert_one({"_id": 10, "author_id": 99}))
        await resolved(raw.update_one({"_id": 10}, {"$set": {"body": "small"}}))
    await drain(view, stream_barrier)
    for name in ("inserts", "counts", "ordinary"):
        writes = [
            event
            for event in projected_events
            if event["ns"]["coll"] == name
            and event["operationType"] in {"insert", "update"}
            and event["documentKey"]["_id"] == 10
        ]
        assert len(writes) == 2
        inserted, updated = writes
        assert ("partition" in inserted) == (name == "inserts")
        assert "changes" not in inserted
        assert "partition" not in updated
        assert ("changes" in updated) == (name == "counts")
    sizes = []
    for value in ("small", "large" * 4000):
        await resolved(view.raw.update_one({"_id": 1}, {"$set": {"body": value}}))
        await drain(view, stream_barrier)
        event = next(
            event
            for event in reversed(projected_events)
            if event["ns"]["coll"] == view.name and event["operationType"] == "update"
        )
        assert event["changes"] == {"known": True, "names": ["body"]}
        assert "updateDescription" not in event
        assert "fullDocument" not in event
        sizes.append(len(BSON.encode(event)))
    assert sizes[0] == sizes[1]
    assert len(view.database.manager._coordinator._supervisors) == 1


@pytest.mark.parametrize(
    "selective_reads", [("sync", True, True), ("async", True, True)], indirect=True
)
async def test_expanded_ambiguous_path_disables_update_proof(
    selective_reads: SelectiveReads,
    stream_barrier: StreamBarrier,
    projected_events: list[ProjectedEvent],
) -> None:
    view = selective_reads["view"]
    query = {"author_id": 42}
    await resolved(view.count_documents(query))
    await resolved(
        view.raw.update_one(
            {"_id": 1},
            [
                {
                    "$replaceWith": {
                        "$setField": {
                            "field": "ambiguous.name",
                            "input": "$$ROOT",
                            "value": True,
                        }
                    }
                }
            ],
        )
    )
    await drain(view, stream_barrier)
    event = next(
        event
        for event in reversed(projected_events)
        if event["ns"]["coll"] == view.name and event["operationType"] == "update"
    )
    assert event["changes"] == {"known": False}
    before = view.database.manager.snapshot().hits
    assert await resolved(view.count_documents(query)) == await resolved(
        view.raw.count_documents(query)
    )
    assert view.database.manager.snapshot().hits == before


@pytest.fixture(params=[False, True], ids=["resumed", "history-loss"])
def interrupted_stream(
    selective_reads: SelectiveReads,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> Recovery:
    view = selective_reads["view"]
    supervisor = view.database.manager._coordinator._supervisors[view.database.name]
    pipelines: list[object] = [supervisor._pipeline]
    original_watch: Callable[..., object] = supervisor._database.watch
    history_loss = request.param

    def watch(*args: object, **kwargs: object) -> object:
        pipelines.append(args[0])
        if history_loss and len(pipelines) == 2:
            raise OperationFailure("injected resume history loss", code=286)
        return original_watch(*args, **kwargs)

    monkeypatch.setattr(supervisor._database, "watch", watch)

    def arm() -> None:
        stream = supervisor._stream
        assert stream is not None
        supervisor._stream = FailingStream(stream)  # type: ignore[assignment]

    return {"arm": arm, "pipelines": pipelines, "history_loss": history_loss}


async def test_independent_insert_and_update_proofs_compose(
    selective_reads: SelectiveReads,
    stream_barrier: StreamBarrier,
) -> None:
    view = selective_reads["view"]
    manager = view.database.manager
    query = {"author_id": 42}
    expected = await materialize(view.raw.find(query).sort("_id"))
    assert await materialize(view.find(query).sort("_id")) == expected
    assert await resolved(view.count_documents(query)) == len(expected)
    await resolved(view.raw.insert_one({"_id": 4, "author_id": 99, "views": 0}))
    await drain(view, stream_barrier)
    before = manager.snapshot().hits
    assert await materialize(view.find(query).sort("_id")) == expected
    assert await resolved(view.count_documents(query)) == len(expected)
    policy = selective_reads["policy"]
    assert manager.snapshot().hits - before == (
        2 if policy.insert_partition_field else 0
    )
    await resolved(view.raw.update_one({"_id": 2}, {"$inc": {"views": 1}}))
    await drain(view, stream_barrier)
    before = manager.snapshot().hits
    assert await materialize(view.find(query).sort("_id")) == expected
    assert await resolved(view.count_documents(query)) == len(expected)
    assert manager.snapshot().hits - before == int(
        policy.update_dependencies_for_counts
    )
    await resolved(view.raw.insert_one({"_id": 5, "author_id": 42}))
    await drain(view, stream_barrier)
    before = manager.snapshot().hits
    assert await resolved(view.count_documents(query)) == await resolved(
        view.raw.count_documents(query)
    )
    assert manager.snapshot().hits == before


@pytest.mark.parametrize("index_kind", ["sparse", "partial"])
async def test_hinted_counts_preserve_insert_proof_and_invalidate_every_update(
    selective_reads: SelectiveReads,
    stream_barrier: StreamBarrier,
    index_kind: str,
) -> None:
    view = selective_reads["view"]
    manager = view.database.manager
    if index_kind == "sparse":
        index = await resolved(view.raw.create_index("membership", sparse=True))
    else:
        index = await resolved(
            view.raw.create_index(
                "membership", partialFilterExpression={"membership": {"$exists": True}}
            )
        )
    await drain(view, stream_barrier)
    query = {"author_id": 42}
    expected = await resolved(view.raw.count_documents(query, hint=index))
    assert await resolved(view.count_documents(query, hint=index)) == expected
    before = manager.snapshot().hits
    assert await resolved(view.count_documents(query, hint=index)) == expected
    assert manager.snapshot().hits == before + 1
    await resolved(view.raw.insert_one({"_id": 4, "author_id": 99, "membership": True}))
    await drain(view, stream_barrier)
    before = manager.snapshot().hits
    assert await resolved(view.count_documents(query, hint=index)) == expected
    assert manager.snapshot().hits - before == int(
        selective_reads["policy"].insert_partition_field is not None
    )
    for changes in ({"$inc": {"views": 1}}, {"$set": {"membership": True}}):
        await resolved(view.raw.update_one({"_id": 3}, changes))
        await drain(view, stream_barrier)
        snapshot_before = manager.snapshot()
        assert await resolved(
            view.count_documents(query, hint=index)
        ) == await resolved(view.raw.count_documents(query, hint=index))
        after = manager.snapshot()
        assert after.hits == snapshot_before.hits
        assert after.bypasses == snapshot_before.bypasses


@pytest.mark.parametrize(
    "selective_reads", [("sync", True, True), ("async", True, True)], indirect=True
)
@pytest.mark.parametrize(
    ("queried", "inserted", "retained"),
    [
        pytest.param(42, Int64(99), True, id="distinct-integers"),
        pytest.param(Int64(42), 42, False, id="equal-integer-subtypes"),
        pytest.param(42, 42.0, False, id="equal-double"),
        pytest.param(42, Decimal128("42"), False, id="equal-decimal"),
        pytest.param(True, 1, True, id="boolean-number"),
        pytest.param("é" * 32, "a", True, id="utf8-query-boundary"),
        pytest.param("é" * 33, "a", False, id="utf8-query-overflow"),
        pytest.param("a", "é" * 33, False, id="utf8-event-overflow"),
        pytest.param(
            ObjectId("000000000000000000000001"),
            ObjectId("000000000000000000000002"),
            True,
            id="object-id",
        ),
        pytest.param(42, None, False, id="null-insert"),
        pytest.param(42, [99], False, id="array-insert"),
        pytest.param(42, {"value": 99}, False, id="object-insert"),
        pytest.param(None, 99, False, id="null-query"),
        pytest.param([42], 99, False, id="array-query"),
    ],
)
async def test_partition_bson_and_utf8_boundaries(
    selective_reads: SelectiveReads,
    stream_barrier: StreamBarrier,
    queried: object,
    inserted: object,
    retained: bool,
) -> None:
    view = selective_reads["view"]
    manager = view.database.manager
    query = {"author_id": queried}
    await materialize(view.find(query).sort("_id"))
    await resolved(view.count_documents(query))
    await resolved(view.raw.insert_one({"_id": 4, "author_id": inserted}))
    await drain(view, stream_barrier)
    before = manager.snapshot().hits
    assert await materialize(view.find(query).sort("_id")) == await materialize(
        view.raw.find(query).sort("_id")
    )
    assert await resolved(view.count_documents(query)) == await resolved(
        view.raw.count_documents(query)
    )
    assert manager.snapshot().hits - before == (2 if retained else 0)


@pytest.mark.parametrize(
    "selective_reads", [("sync", True, True), ("async", True, True)], indirect=True
)
@pytest.mark.parametrize(
    ("query", "changes", "retained"),
    [
        pytest.param({"author_id": 42}, {"$set": {"views": 1}}, True, id="irrelevant"),
        pytest.param(
            {"author_id": 42, **{f"q_{index}": None for index in range(31)}},
            {"$set": {"views": 1}},
            True,
            id="query-name-count-boundary",
        ),
        pytest.param(
            {"author_id": 42, **{f"q_{index}": None for index in range(32)}},
            {"$set": {"views": 1}},
            False,
            id="query-name-count-overflow",
        ),
        pytest.param(
            {"é" * 32: None},
            {"$set": {"views": 1}},
            True,
            id="query-name-bytes-boundary",
        ),
        pytest.param(
            {"é" * 33: None},
            {"$set": {"views": 1}},
            False,
            id="query-name-bytes-overflow",
        ),
        pytest.param(
            {"tags": "rust"},
            {"$pop": {"tags": 1}},
            False,
            id="truncated-array",
        ),
        pytest.param(
            {"author_id": 42},
            {"$unset": {"author_id": ""}},
            False,
            id="removed-dependency",
        ),
        pytest.param(
            {"profile.country": "UA"},
            {"$set": {"profile": {"country": "UA"}}},
            False,
            id="parent",
        ),
        pytest.param(
            {"profile": {"country": "UA"}},
            {"$set": {"profile.country": "UA"}},
            False,
            id="child",
        ),
        pytest.param(
            {"tags": "python"}, {"$set": {"tags": ["python"]}}, False, id="array-field"
        ),
        pytest.param(
            {"views": None}, {"$unset": {"views": ""}}, False, id="null-missing"
        ),
        pytest.param(
            {"missing": {"$exists": False}},
            {"$set": {"missing": True}},
            False,
            id="existence",
        ),
        pytest.param(
            {"author_id": 42},
            {"$set": {f"field_{index}": index for index in range(32)}},
            True,
            id="name-count-boundary",
        ),
        pytest.param(
            {"author_id": 42},
            {"$set": {f"field_{index}": index for index in range(33)}},
            False,
            id="name-count-overflow",
        ),
        pytest.param(
            {"author_id": 42},
            {"$set": {"é" * 32: True}},
            True,
            id="name-bytes-boundary",
        ),
        pytest.param(
            {"author_id": 42},
            {"$set": {"é" * 33: True}},
            False,
            id="name-bytes-overflow",
        ),
        pytest.param(
            {"author_id": 42}, {"$set": {"nested.0": True}}, False, id="numeric-path"
        ),
    ],
)
async def test_count_dependencies_follow_real_update_descriptions(
    selective_reads: SelectiveReads,
    stream_barrier: StreamBarrier,
    query: dict[str, object],
    changes: dict[str, object],
    retained: bool,
) -> None:
    view = selective_reads["view"]
    manager = view.database.manager
    await resolved(view.count_documents(query))
    await resolved(view.raw.update_one({"_id": 1}, changes))
    await drain(view, stream_barrier)
    before = manager.snapshot().hits
    assert await resolved(view.count_documents(query)) == await resolved(
        view.raw.count_documents(query)
    )
    assert manager.snapshot().hits - before == int(retained)


@pytest.mark.parametrize(
    "selective_reads", [("sync", True, True), ("async", True, True)], indirect=True
)
async def test_unsupported_dependencies_keep_insert_proof_without_bypass(
    selective_reads: SelectiveReads,
    stream_barrier: StreamBarrier,
) -> None:
    view = selective_reads["view"]
    manager = view.database.manager
    query = {"author_id": 42, "views": {"$not": {"$gt": 10}}}
    expected = await resolved(view.raw.count_documents(query))
    await resolved(view.count_documents(query))
    await resolved(view.raw.insert_one({"_id": 4, "author_id": 99}))
    await drain(view, stream_barrier)
    before = manager.snapshot()
    assert await resolved(view.count_documents(query)) == expected
    assert manager.snapshot().hits == before.hits + 1
    await resolved(view.raw.update_one({"_id": 2}, {"$inc": {"views": 1}}))
    await drain(view, stream_barrier)
    before = manager.snapshot()
    assert await resolved(view.count_documents(query)) == expected
    assert manager.snapshot().hits == before.hits
    assert manager.snapshot().bypasses == before.bypasses


@pytest.mark.parametrize(
    "selective_reads", [("sync", True, True), ("async", True, True)], indirect=True
)
@pytest.mark.parametrize("recreate", [False, True])
@pytest.mark.parametrize("disposal", ["gc", "close"])
@pytest.mark.usefixtures("reserved_capacity")
async def test_partial_cursor_release_reclaims_last_selective_slot(
    selective_reads: SelectiveReads,
    recreate: bool,
    disposal: str,
) -> None:
    view = selective_reads["view"]
    core = view.database.manager.cache_core
    namespace = view._namespace()
    before = core.snapshot().entry_count
    cursor = view.find({"author_id": 42}).sort("_id")
    assert len(await materialize(cursor, 1)) == 1
    assert core.snapshot().entry_count == before
    if recreate:
        core.drop_namespace(namespace)
        core.try_current_epoch(namespace)
    if disposal == "gc":
        reference = weakref.ref(cursor)
        del cursor
        gc.collect()
        assert reference() is None
    else:
        await resolved(cursor.close())
        assert not cursor.alive
    replacement = core.capture_namespace_generation(
        namespace, partition=partition_scalar(10000)
    )
    core.record_write(namespace, 1, partition=partition_scalar(10001))
    assert (
        core.admit_namespace(replacement, "capacity-probe", 1)
        is AdmissionOutcome.ADMITTED
    )


@pytest.mark.parametrize("selective_reads", [("async", True, True)], indirect=True)
@pytest.mark.usefixtures("reserved_capacity")
async def test_cancelled_selective_cursor_releases_its_reservation(
    selective_reads: SelectiveReads,
    paused_cursor_start: PausedRead,
) -> None:
    view = selective_reads["view"]
    core = view.database.manager.cache_core
    before = core.snapshot().entry_count  # pytriage: TR11 (before cancellation)
    cursor = view.find({"author_id": 42})
    assert isinstance(cursor, AsyncCursor)
    task = asyncio.create_task(cursor.to_list())
    paused_cursor_start["tasks"].append(task)
    await asyncio.wait_for(paused_cursor_start["entered"].wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not cursor.alive
    assert core.snapshot().entry_count == before
    replacement = core.capture_namespace_generation(
        view._namespace(), partition=partition_scalar(10000)
    )
    core.record_write(view._namespace(), 1, partition=partition_scalar(10001))
    assert (
        core.admit_namespace(replacement, "after-cancellation", 1)
        is AdmissionOutcome.ADMITTED
    )


@pytest.mark.parametrize(
    "selective_reads", [("sync", True, True), ("async", True, True)], indirect=True
)
async def test_covering_source_survives_unrelated_insert(
    selective_reads: SelectiveReads,
    stream_barrier: StreamBarrier,
) -> None:
    view = selective_reads["view"]
    query = {"author_id": 42}
    complete = await materialize(view.find(query).sort("_id"))
    await resolved(view.raw.insert_one({"_id": 4, "author_id": 99}))
    await drain(view, stream_barrier)
    selective_reads["commands"].commands.clear()
    assert await materialize(view.find(query).sort("_id").limit(1)) == complete[:1]
    assert not selective_reads["commands"].commands


@pytest.mark.parametrize(
    "selective_reads", [("sync", True, True), ("async", True, True)], indirect=True
)
@pytest.mark.parametrize("explicit_simple", [False, True])
async def test_effective_collection_collation_controls_partition_proof(
    selective_reads: SelectiveReads,
    stream_barrier: StreamBarrier,
    explicit_simple: bool,
) -> None:
    view = selective_reads["view"]
    await resolved(view.raw.drop())
    created: object = view.raw.database.create_collection(
        view.name, collation={"locale": "en", "strength": 2}
    )
    await resolved(created)
    await resolved(view.raw.insert_one({"_id": 1, "author_id": "a"}))
    await drain(view, stream_barrier)
    options: CollationOptions = (
        {"collation": {"locale": "simple"}} if explicit_simple else {}
    )
    query = {"author_id": "A"}
    await materialize(view.find(query, **options))
    await resolved(view.count_documents(query, **options))
    await resolved(view.raw.insert_one({"_id": 2, "author_id": "a"}))
    await drain(view, stream_barrier)
    before = view.database.manager.snapshot().hits
    assert await materialize(view.find(query, **options)) == await materialize(
        view.raw.find(query, **options)
    )
    assert await resolved(view.count_documents(query, **options)) == await resolved(
        view.raw.count_documents(query, **options)
    )
    assert view.database.manager.snapshot().hits - before == (
        2 if explicit_simple else 0
    )


@pytest.mark.parametrize(
    "selective_reads", [("sync", True, True), ("async", True, True)], indirect=True
)
@pytest.mark.parametrize(
    "transition", ["replace", "delete", "drop", "rename", "index", "drop-database"]
)
async def test_real_lifecycle_events_reject_selective_admission(
    selective_reads: SelectiveReads,
    stream_barrier: StreamBarrier,
    transition: str,
) -> None:
    view = selective_reads["view"]
    core = view.database.manager.cache_core
    namespace = view._namespace()
    query = {"author_id": 42}
    await resolved(view.count_documents(query))
    capture = core.capture_namespace_generation(  # pytriage: TR11 (before fence)
        namespace, partition=partition_scalar(42), dependencies=("author_id",)
    )
    if transition == "replace":
        await resolved(view.raw.replace_one({"_id": 2}, {"author_id": 99}))
    elif transition == "delete":
        await resolved(view.raw.delete_one({"_id": 2}))
    elif transition == "drop":
        await resolved(view.raw.drop())
    elif transition == "rename":
        await resolved(view.raw.rename("renamed_posts"))
    elif transition == "index":
        await resolved(view.raw.create_index("views"))
    else:
        await resolved(view.raw.database.client.drop_database(view.raw.database.name))
    await drain(view, stream_barrier)
    expected = (
        AdmissionOutcome.DECLINED_UNAVAILABLE
        if transition == "drop-database"
        else AdmissionOutcome.DECLINED_STALE
    )
    assert core.admit_namespace(capture, "late", 1) is expected
    before = view.database.manager.snapshot().hits
    assert await resolved(view.count_documents(query)) == await resolved(
        view.raw.count_documents(query)
    )
    assert view.database.manager.snapshot().hits == before


@pytest.mark.parametrize(
    "selective_reads", [("sync", True, True), ("async", True, True)], indirect=True
)
async def test_selective_guards_follow_established_stream_recovery(
    selective_reads: SelectiveReads,
    interrupted_stream: Recovery,
    stream_barrier: StreamBarrier,
) -> None:
    view = selective_reads["view"]
    manager = view.database.manager
    query = {"author_id": 42}
    await resolved(view.count_documents(query))
    capture = manager.cache_core.capture_namespace_generation(
        view._namespace(), partition=partition_scalar(42)
    )
    interrupted_stream["arm"]()
    await resolved(view.raw.insert_one({"_id": 4, "author_id": 99}))
    expected_watches = 3 if interrupted_stream["history_loss"] else 2
    await wait_until_async(
        lambda: (
            len(interrupted_stream["pipelines"]) == expected_watches
            and manager.cache_core.is_database_available(view.database.name)
        )
    )
    await drain(view, stream_barrier)
    assert all(
        pipeline is interrupted_stream["pipelines"][0]
        for pipeline in interrupted_stream["pipelines"]
    )
    assert (
        manager.cache_core.admit_namespace(capture, "late", 1)
        is AdmissionOutcome.DECLINED_UNAVAILABLE
    )
    before = manager.snapshot().hits
    assert await resolved(view.count_documents(query)) == await resolved(
        view.raw.count_documents(query)
    )
    assert manager.snapshot().hits - before == int(
        not interrupted_stream["history_loss"]
    )


@pytest.mark.parametrize(
    "selective_reads", [("sync", True, True), ("async", True, True)], indirect=True
)
async def test_public_feed_and_count_examples_work_without_telemetry(
    selective_reads: SelectiveReads,
    unmeasured_view: View,
    stream_barrier: StreamBarrier,
) -> None:
    posts = unmeasured_view
    query = {"author_id": 42, "published": True}
    expected = await materialize(posts.raw.find(query).sort("_id", -1).limit(20))
    assert await materialize(posts.find(query).sort("_id", -1).limit(20)) == expected
    assert await resolved(posts.count_documents(query)) == len(expected)
    await resolved(posts.raw.insert_one({"_id": 4, "author_id": 99, "views": 0}))
    await drain(posts, stream_barrier)
    selective_reads["commands"].commands.clear()
    assert await materialize(posts.find(query).sort("_id", -1).limit(20)) == expected
    assert await resolved(posts.count_documents(query)) == len(expected)
    assert not selective_reads["commands"].commands


async def test_ordinary_sibling_keeps_independent_namespace_guards(
    selective_reads: SelectiveReads,
    stream_barrier: StreamBarrier,
) -> None:
    sibling = selective_reads["sibling"]
    posts = selective_reads["view"]
    await resolved(sibling.count_documents({}))
    await resolved(posts.raw.insert_one({"_id": 4, "author_id": 99}))
    await drain(posts, stream_barrier)
    before = posts.database.manager.snapshot().hits
    assert await resolved(sibling.count_documents({})) == 1
    assert posts.database.manager.snapshot().hits == before + 1
    await resolved(sibling.raw.insert_one({"_id": "other"}))
    await drain(sibling, stream_barrier)
    before = posts.database.manager.snapshot().hits
    assert await resolved(sibling.count_documents({})) == 2
    assert posts.database.manager.snapshot().hits == before
    assert len(posts.database.manager._coordinator._supervisors) == 1


@pytest.mark.parametrize(
    "selective_reads", [("sync", True, True), ("async", True, True)], indirect=True
)
@pytest.mark.parametrize("write", ["insert", "update"])
@pytest.mark.parametrize(
    ("query", "insert_hit", "update_hit"),
    [
        pytest.param({"_id": 1}, True, False, id="written-identity"),
        pytest.param({"_id": 2}, True, True, id="other-identity"),
        pytest.param(
            {"email": "first@example.test"}, True, False, id="unique-positive"
        ),
        pytest.param(
            {"email": "absent@example.test"}, False, False, id="unique-negative"
        ),
        pytest.param({"published": True}, False, False, id="generic-query"),
    ],
)
async def test_selective_counts_do_not_weaken_other_read_guards(
    uniquely_indexed_view: View,
    stream_barrier: StreamBarrier,
    query: BsonDict,
    write: str,
    *,
    insert_hit: bool,
    update_hit: bool,
) -> None:
    view = uniquely_indexed_view
    await resolved(view.find_one(query))
    await resolved(view.count_documents({"author_id": 42}))
    if write == "insert":
        await resolved(
            view.raw.insert_one(
                {
                    "_id": 4,
                    "author_id": 99,
                    "email": "new@example.test",
                }
            )
        )
    else:
        await resolved(view.raw.update_one({"_id": 1}, {"$inc": {"views": 1}}))
    await drain(view, stream_barrier)
    before = view.database.manager.snapshot().hits
    assert await resolved(view.find_one(query)) == await resolved(
        view.raw.find_one(query)
    )
    assert view.database.manager.snapshot().hits - before == int(
        insert_hit if write == "insert" else update_hit
    )
    before = view.database.manager.snapshot().hits
    assert await resolved(view.count_documents({"author_id": 42})) == 2
    assert view.database.manager.snapshot().hits == before + 1


@pytest.mark.parametrize(
    "selective_reads", [("sync", True, True), ("async", True, True)], indirect=True
)
async def test_unconfigured_database_keeps_default_invalidation(
    selective_reads: SelectiveReads,
    ordinary_database_view: View,
    stream_barrier: StreamBarrier,
) -> None:
    view = ordinary_database_view
    assert view.database.manager is selective_reads["view"].database.manager
    await drain(view, stream_barrier)
    query = {"author_id": 42}
    assert await resolved(view.count_documents(query)) == 1
    before = view.database.manager.snapshot().hits
    assert await resolved(view.count_documents(query)) == 1
    assert view.database.manager.snapshot().hits == before + 1
    await resolved(view.raw.insert_one({"_id": 2, "author_id": 99}))
    await drain(view, stream_barrier)
    before = view.database.manager.snapshot().hits
    assert await resolved(view.count_documents(query)) == 1
    assert view.database.manager.snapshot().hits == before


@pytest.mark.parametrize(
    "selective_reads", [("sync", True, True), ("async", True, True)], indirect=True
)
@pytest.mark.usefixtures("reserved_capacity")
async def test_count_error_releases_selective_reservation(
    selective_reads: SelectiveReads,
) -> None:
    view = selective_reads["view"]
    with pytest.raises(TypeError, match="collation"):
        await resolved(view.count_documents({"author_id": 42}, collation=17))
    core = view.database.manager.cache_core
    capture = core.capture_namespace_generation(
        view._namespace(), partition=partition_scalar(10000)
    )
    core.record_write(view._namespace(), 1, partition=partition_scalar(10001))
    assert (
        core.admit_namespace(capture, "after-count-error", 1)
        is AdmissionOutcome.ADMITTED
    )


@pytest.mark.parametrize(
    "selective_reads", [("sync", True, True), ("async", True, True)], indirect=True
)
@pytest.mark.parametrize("matching", [False, True])
async def test_inflight_find_owns_its_partition_despite_caller_mutation(
    selective_reads: SelectiveReads,
    stream_barrier: StreamBarrier,
    matching: bool,
) -> None:
    view = selective_reads["view"]
    query = {"author_id": 42}
    expected = await materialize(view.raw.find(query).sort("_id"))
    before = view.database.manager.snapshot().entry_count
    cursor = view.find(query).sort("_id")
    assert await materialize(cursor, 1) == expected[:1]
    assert view.database.manager.snapshot().entry_count == before
    query["author_id"] = 99
    await resolved(view.raw.insert_one({"_id": 4, "author_id": 42 if matching else 99}))
    await drain(view, stream_barrier)
    assert await materialize(cursor) == expected[1:]
    original_query = {"author_id": 42}
    current = await materialize(view.raw.find(original_query).sort("_id"))
    before = view.database.manager.snapshot().hits
    assert await materialize(view.find(original_query).sort("_id")) == current
    assert view.database.manager.snapshot().hits - before == int(not matching)


@pytest.mark.parametrize(
    "selective_reads", [("sync", True, True), ("async", True, True)], indirect=True
)
@pytest.mark.parametrize(
    ("skip", "limit"), [(1, 1), (10, 2)], ids=["bounded-page", "empty-page"]
)
async def test_skipped_limited_and_empty_feeds_retain_insert_proofs(
    selective_reads: SelectiveReads,
    stream_barrier: StreamBarrier,
    skip: NonNegativeInt,
    limit: PositiveInt,
) -> None:
    view = selective_reads["view"]
    query = {"author_id": 42}
    expected = await materialize(
        view.raw.find(query).sort("_id", -1).skip(skip).limit(limit)
    )
    assert (
        await materialize(view.find(query).sort("_id", -1).skip(skip).limit(limit))
        == expected
    )
    await resolved(view.raw.insert_one({"_id": 4, "author_id": 99}))
    await drain(view, stream_barrier)
    selective_reads["commands"].commands.clear()
    assert (
        await materialize(view.find(query).sort("_id", -1).skip(skip).limit(limit))
        == expected
    )
    assert not selective_reads["commands"].commands


def test_async_cursor_gc_reclaims_capacity_without_a_running_event_loop(
    dormant_async_cursor: DormantCapture,
) -> None:
    with pytest.raises(RuntimeError, match="no running event loop"):
        asyncio.get_running_loop()
    reference = weakref.ref(dormant_async_cursor["cursor"])
    del dormant_async_cursor["cursor"]
    gc.collect()
    assert reference() is None
    core = dormant_async_cursor["core"]
    namespace = dormant_async_cursor["namespace"]
    replacement = core.capture_namespace_generation(
        namespace, partition=partition_scalar(10000)
    )
    core.record_write(namespace, 1, partition=partition_scalar(10001))
    assert (
        core.admit_namespace(replacement, "after-dormant-gc", 1)
        is AdmissionOutcome.ADMITTED
    )


@pytest.mark.parametrize(
    "selective_reads", [("sync", True, True), ("async", True, True)], indirect=True
)
async def test_selective_policy_preserves_unsupported_find_bypass_without_telemetry(
    selective_reads: SelectiveReads,
    unmeasured_view: View,
) -> None:
    query = {"author_id": 42}
    expected = await materialize(unmeasured_view.raw.find(query, hint="_id_"))
    commands = selective_reads["commands"].commands
    commands.clear()
    for _ in range(2):
        assert await materialize(unmeasured_view.find(query, hint="_id_")) == expected
    assert [command["find"] for command in commands] == [unmeasured_view.name] * 2
    assert all(command["hint"] == "_id_" for command in commands)
    assert not unmeasured_view.database.manager._coordinator._supervisors
