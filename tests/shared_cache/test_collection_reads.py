from __future__ import annotations

import asyncio
import multiprocessing
import re
import time
from collections.abc import Awaitable
from contextlib import AsyncExitStack, asynccontextmanager
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

import pytest
from bson.codec_options import CodecOptions
from bson.errors import InvalidDocument
from bson.int64 import Int64
from bson.tz_util import FixedOffset
from pymongo import AsyncMongoClient, MongoClient
from pymongo.asynchronous.command_cursor import AsyncCommandCursor
from pymongo.asynchronous.cursor import AsyncCursor
from pymongo.collation import Collation
from pymongo.errors import ConnectionFailure, OperationFailure
from pymongo.monitoring import CommandListener

from benchmarks.stream_cost.multiprocess_run import reclaim_workers
from client_query_cache import (
    SharedCacheConfig,
    SharedCacheManager,
    SharedCacheServer,
)
from client_query_cache._core.codec import encode_document, encode_value
from client_query_cache._shared import wire
from client_query_cache._shared.adapters import (
    AsyncSharedCachedCollection,
    SharedCachedCollection,
)
from client_query_cache._types import BsonDict, NonNegativeInt
from client_query_cache.asynchronous import (
    SharedCacheManager as AsyncSharedCacheManager,
)
from tests.call_counting import count_current_thread_calls
from tests.cursor_helpers import advance, close_cursor, materialize, resolve_cursor
from tests.polling import wait_until_async

if TYPE_CHECKING:
    from collections.abc import (
        AsyncGenerator,
        AsyncIterator,
        Callable,
        Iterator,
        Mapping,
    )
    from multiprocessing.connection import Connection
    from multiprocessing.process import BaseProcess
    from typing import Any

    from pymongo.asynchronous.collection import AsyncCollection
    from pymongo.monitoring import (
        CommandFailedEvent,
        CommandStartedEvent,
        CommandSucceededEvent,
    )
    from pymongo.synchronous.collection import Collection

    from client_query_cache.shared import SharedCacheConnection
    from tests.conftest import MongoDbUri
    from tests.cursor_helpers import ReadCursor

pytestmark = pytest.mark.integration

type View = SharedCachedCollection[BsonDict] | AsyncSharedCachedCollection[BsonDict]
type Method = Literal[
    "find_one",
    "identity",
    "regex",
    "identity_predicate",
    "find",
    "aggregate",
    "count_documents",
    "estimated_document_count",
    "distinct",
    "empty_find",
    "empty_aggregate",
]
_METHODS: tuple[Method, ...] = (
    "find_one",
    "identity",
    "regex",
    "identity_predicate",
    "find",
    "aggregate",
    "count_documents",
    "estimated_document_count",
    "distinct",
    "empty_find",
    "empty_aggregate",
)
_READ_COMMANDS = frozenset({"find", "aggregate", "count", "distinct", "getMore"})


class ReadCommands(CommandListener):
    def __init__(self) -> None:
        self.count: NonNegativeInt = 0

    def started(self, event: CommandStartedEvent) -> None:
        if event.command_name in _READ_COMMANDS:
            self.count += 1

    def succeeded(self, event: CommandSucceededEvent) -> None:
        pass

    def failed(self, event: CommandFailedEvent) -> None:
        pass


@asynccontextmanager
async def _view(
    uri: str,
    connection: SharedCacheConnection,
    database: str,
    model: str,
    commands: ReadCommands,
) -> AsyncGenerator[View]:
    async with AsyncExitStack() as stack:
        view: View
        if model == "sync":
            client = stack.enter_context(
                MongoClient[BsonDict](uri, event_listeners=[commands])
            )
            manager = stack.enter_context(SharedCacheManager(client, connection))
            view = manager[database]["catalogue"]
        else:
            async_client = await stack.enter_async_context(
                AsyncMongoClient[BsonDict](uri, event_listeners=[commands])
            )
            async_manager = await stack.enter_async_context(
                AsyncSharedCacheManager(async_client, connection)
            )
            view = async_manager[database]["catalogue"]

        async def ready() -> bool:
            reason = view._cache_ineligibility_reason()
            if isinstance(reason, Awaitable):
                reason = await reason
            return reason is None

        await wait_until_async(ready)
        yield view


async def _read(view: View, method: Method) -> object:
    pending: object
    if method == "identity":
        pending = view.find_one({"_id": 0})
    elif method == "regex":
        pending = view.find_one({"payload": re.compile(r"^value-"), "revision": 0})
    elif method == "find_one":
        pending = view.find_one({"revision": 0}, {"payload": 1}, sort=[("_id", -1)])
    elif method == "identity_predicate":
        pending = view.find_one({"_id": 0, "revision": 0})
    elif method == "count_documents":
        pending = view.count_documents({"revision": 0}, skip=1, limit=8, hint="_id_")
    elif method == "estimated_document_count":
        pending = view.estimated_document_count()
    elif method == "distinct":
        pending = view.distinct("payload", {"revision": 0})
    elif method in {"find", "empty_find"}:
        return await materialize(
            view.find({"revision": 0 if method == "find" else -1}, {"payload": 1})
            .sort("_id", -1)
            .skip(1)
            .limit(8)
        )
    else:
        return await materialize(
            view.aggregate(
                [
                    {"$match": {"revision": 0 if method == "aggregate" else -1}},
                    {"$sort": {"_id": -1}},
                    {"$limit": 8},
                    {"$project": {"payload": 1}},
                ]
            )
        )
    return await pending if isinstance(pending, Awaitable) else pending


async def _worker_reads(
    pipe: Connection,
    uri: str,
    connection: SharedCacheConnection,
    database: str,
    model: str,
) -> None:
    commands = ReadCommands()
    async with _view(uri, connection, database, model, commands) as view:
        pipe.send("ready")
        operation = pipe.recv()
        before = commands.count
        snapshots = [
            await (_warm(view, method) if operation == "warm" else _read(view, method))
            for method in _METHODS
        ]
        # The request is ordered behind this worker's one-way admissions.
        observation = view._shared.endpoint.request({"op": "observe"})
        if isinstance(observation, Awaitable):
            observation = await observation
        assert observation is not None
        pipe.send((snapshots, commands.count - before, view._shared.snapshot()))


def _worker(
    pipe: Connection,
    uri: str,
    connection: SharedCacheConnection,
    database: str,
    model: str,
) -> None:
    with pipe:
        asyncio.run(_worker_reads(pipe, uri, connection, database, model))


@pytest.fixture
def server(
    mongodb_uri: MongoDbUri, seeded_database: str, request: pytest.FixtureRequest
) -> Iterator[SharedCacheServer]:
    with SharedCacheServer(
        mongodb_uri,
        (seeded_database,),
        config=SharedCacheConfig(
            budget_bytes=getattr(request, "param", 1024 * 1024),
            max_entry_bytes=min(65_536, getattr(request, "param", 1024 * 1024)),
            arena_bytes=2 * 1024 * 1024,
            slots=256,
            connections=16,
        ),
    ) as owner:
        yield owner


@pytest.fixture
def spawn_reader(
    server: SharedCacheServer, mongodb_uri: MongoDbUri, seeded_database: str
) -> Iterator[Callable[[str], Connection]]:
    workers: list[BaseProcess] = []
    pipes: list[Connection] = []

    def spawn(model: str) -> Connection:
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        worker = context.Process(
            target=_worker,
            args=(child, mongodb_uri, server.connection, seeded_database, model),
        )
        worker.start()
        child.close()
        workers.append(worker)
        pipes.append(parent)
        assert parent.poll(15)
        assert parent.recv() == "ready"
        return parent

    yield spawn
    reclaim_workers(tuple(workers), time.monotonic() + 10, graceful=True)
    for worker in workers:
        assert worker.exitcode == 0
    for pipe in pipes:
        pipe.close()


@pytest.mark.parametrize("writer_model", ["sync", "async"])
@pytest.mark.parametrize("reader_model", ["sync", "async"])
def test_first_reads_in_another_process_use_shared_results(
    spawn_reader: Callable[[str], Connection],
    writer_model: str,
    reader_model: str,
) -> None:
    writer = spawn_reader(writer_model)
    writer.send("warm")
    assert writer.poll(15)
    snapshots, reads, first = writer.recv()
    assert reads > 0
    assert first.hits >= len(_METHODS)
    assert first.misses >= len(_METHODS)
    reader = spawn_reader(reader_model)
    reader.send("read")
    assert reader.poll(15)
    second_snapshots, reads, second = reader.recv()
    assert second_snapshots == snapshots
    assert reads == 0
    assert second.hits == len(_METHODS)
    assert second.misses == second.bypasses == 0


@pytest.fixture(params=["sync", "async"])
async def view(
    request: pytest.FixtureRequest,
    server: SharedCacheServer,
    mongodb_uri: MongoDbUri,
    seeded_database: str,
) -> AsyncIterator[View]:
    async with _view(
        mongodb_uri, server.connection, seeded_database, request.param, ReadCommands()
    ) as attached:
        yield attached


async def _warm(view: View, method: Method) -> object:
    snapshot = await _read(view, method)

    async def hit() -> bool:
        before = view._shared.snapshot().hits
        assert await _read(view, method) == snapshot
        return view._shared.snapshot().hits > before

    await wait_until_async(hit)
    return snapshot


@pytest.mark.parametrize("method", _METHODS)
async def test_external_writes_invalidate_collection_results(
    view: View, method: Method, mongodb_uri: MongoDbUri
) -> None:
    before = await _warm(view, method)
    with MongoClient[BsonDict](mongodb_uri) as writer:
        raw = writer[view.raw.database.name][view.name]
        raw.update_many({}, {"$set": {"revision": -1}})
        raw.insert_one({"_id": 100, "payload": "new-member", "revision": 0})

    async def changed() -> bool:
        return await _read(view, method) != before

    await wait_until_async(changed)


async def _assert_index_refresh(view: View, *, create: bool) -> None:
    expected = await _warm(view, "find_one")
    misses_before = view._shared.snapshot().misses
    raw = view.raw
    pending = raw.create_index("revision") if create else raw.drop_index("revision_1")
    if isinstance(pending, Awaitable):
        await pending

    async def refreshed() -> bool:
        assert await _read(view, "find_one") == expected
        return view._shared.snapshot().misses > misses_before

    await wait_until_async(refreshed)
    assert await _warm(view, "find_one") == expected


async def test_index_changes_invalidate_generic_find_one(view: View) -> None:
    await _assert_index_refresh(view, create=True)
    await _assert_index_refresh(view, create=False)


@pytest.mark.parametrize("method", ["find", "aggregate"])
async def test_partial_cursor_is_not_admitted(view: View, method: str) -> None:
    cursor = await resolve_cursor(_plain_cursor(view, method))
    await advance(cursor)
    await close_cursor(cursor)
    before = view._shared.snapshot()
    complete = await materialize(_plain_cursor(view, method))
    assert len(complete) == 32
    assert view._shared.snapshot().misses == before.misses + 1


async def test_find_is_lazy_and_clone_rewind_keep_snapshots(view: View) -> None:
    before = view._shared.snapshot()
    cursor = view.find({"revision": 0}).sort("_id", 1).limit(8)
    assert view._shared.snapshot() == before
    documents = await materialize(cursor)
    assert await materialize(cursor.clone()) == documents
    rewind = cursor.rewind()
    if isinstance(rewind, Awaitable):
        await rewind
    assert await materialize(cursor) == documents


@pytest.mark.parametrize("method", ["find", "aggregate"])
@pytest.mark.parametrize("server", [1024], indirect=True)
async def test_cursor_hit_snapshot_survives_eviction_write_and_manager_close(
    view: View,
    method: Method,
    mongodb_uri: MongoDbUri,
) -> None:
    expected = await _warm(view, method)
    cursor = await resolve_cursor(
        view.find({"revision": 0}, {"payload": 1}).sort("_id", -1).skip(1).limit(8)
        if method == "find"
        else view.aggregate(
            [
                {"$match": {"revision": 0}},
                {"$sort": {"_id": -1}},
                {"$limit": 8},
                {"$project": {"payload": 1}},
            ]
        )
    )
    first = await advance(cursor)
    first["payload"] = "caller-mutated"
    for offset in range(1, 9):
        await materialize(view.find({"_id": {"$gte": offset}}).sort("_id", 1).limit(8))
    await wait_until_async(lambda: _has_evicted(view))
    with MongoClient[BsonDict](mongodb_uri) as writer:
        writer[view.raw.database.name][view.name].delete_many({})
    closed = view._shared.close()
    if isinstance(closed, Awaitable):
        await closed
    assert isinstance(expected, list)
    assert await materialize(cursor) == expected[1:]


async def _has_evicted(view: View) -> bool:
    observed = view._shared.endpoint.request({"op": "observe"})
    if isinstance(observed, Awaitable):
        observed = await observed
    assert observed is not None
    cache = observed["cache"]
    assert isinstance(cache, dict)
    evictions = cache["evictions"]
    assert isinstance(evictions, int)
    return evictions > 0


@pytest.mark.parametrize(
    ("stored_limit", "requested_limit"),
    [(8, 8), (8, 4), (0, 4), (0, 0), (Int64(8), Int64(4))],
    ids=("exact", "covering", "unlimited-covering", "unlimited-exact", "int64"),
)
async def test_native_find_captures_locally_and_reuses_results(
    view: View,
    stored_limit: NonNegativeInt,
    requested_limit: NonNegativeInt,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _warm(view, "empty_find")
    endpoint = view._shared.endpoint
    before = endpoint.counters.requests
    serializations = count_current_thread_calls(monkeypatch, wire, "encode_key")
    query = {"revision": {"$gte": 0}}
    complete = await materialize(view.find(query).sort("_id", 1).limit(stored_limit))
    assert endpoint.counters.requests == before
    assert serializations.count == 1
    pending = endpoint.request({"op": "observe"})
    if isinstance(pending, Awaitable):
        await pending
    before = endpoint.counters.requests
    expected = complete[:requested_limit] if requested_limit else complete

    async def hit() -> bool:
        hits = view._shared.snapshot().hits
        assert (
            await materialize(view.find(query).sort("_id", 1).limit(requested_limit))
            == expected
        )
        return view._shared.snapshot().hits > hits

    await wait_until_async(hit)
    if stored_limit == requested_limit:
        requests = endpoint.counters.requests
        assert (
            await materialize(view.find(query).sort("_id", 1).limit(requested_limit))
            == expected
        )
        assert endpoint.counters.requests == requests
    else:
        assert endpoint.counters.requests > before


async def test_negative_find_limits_reuse_only_exact_results(view: View) -> None:
    await _warm(view, "empty_find")
    query = {"revision": {"$gte": 0}}
    complete = await materialize(view.find(query).sort("_id", 1).limit(-8))
    assert len(complete) == 8

    async def hit() -> bool:
        hits = view._shared.snapshot().hits
        assert await materialize(view.find(query).sort("_id", 1).limit(-8)) == complete
        return view._shared.snapshot().hits > hits

    await wait_until_async(hit)
    requests = view._shared.endpoint.counters.requests
    assert await materialize(view.find(query).sort("_id", 1).limit(-8)) == complete
    assert view._shared.endpoint.counters.requests == requests


@pytest.mark.parametrize("limit", [8, -8], ids=["positive", "negative"])
async def test_unportable_integer_find_keys_preserve_native_errors(
    view: View, limit: int
) -> None:
    await _warm(view, "empty_find")
    query = {"_id": {"$in": [1 << 80]}}
    with pytest.raises(OverflowError) as native:
        await materialize(view.raw.find(query).limit(limit))
    before = view._shared.snapshot().bypasses
    with pytest.raises(OverflowError, match=re.escape(str(native.value))):
        await materialize(view.find(query).limit(limit))
    assert view._shared.snapshot().bypasses == before + 1


@pytest.mark.parametrize("server", [128], indirect=True)
async def test_local_find_envelope_can_exceed_the_document_snapshot_bound(
    view: View,
) -> None:
    await _warm(view, "empty_find")
    query = {"revision": 0}
    projection = {"_id": 1}
    expected = await materialize(
        view.raw.find(query, projection).sort("_id", 1).limit(8)
    )
    assert (
        sum(
            len(encode_document(document, view.raw.codec_options))
            for document in expected
        )
        <= 128
    )
    assert len(encode_value(expected)) > 128
    before = view._shared.snapshot()
    assert (
        await materialize(view.find(query, projection).sort("_id", 1).limit(8))
        == expected
    )
    assert view._shared.snapshot().misses == before.misses + 1
    assert view._shared.observation.bypasses["oversized"] == 1


@pytest.mark.parametrize("method", ["find", "aggregate", "find_one", "distinct"])
async def test_oversized_results_are_delivered_without_admission(
    oversized_view: View,
    method: str,
) -> None:
    expected = await _execute(oversized_view.raw, method, {})
    before = oversized_view._shared.snapshot()
    for _ in range(2):
        assert await _execute(oversized_view, method, {}) == expected
    assert oversized_view._shared.snapshot().misses == before.misses + 2
    assert oversized_view._shared.observation.bypasses["oversized"] == 2


@pytest.mark.parametrize("method", ["find", "aggregate"])
@pytest.mark.parametrize("transition", ["write", "restart"])
async def test_cursor_capture_crossing_write_or_restart_is_rejected(
    view: View,
    method: str,
    server: SharedCacheServer,
    mongodb_uri: MongoDbUri,
    transition: str,
) -> None:
    await _warm(view, "identity")
    cursor = await resolve_cursor(_plain_cursor(view, method))
    first = await advance(cursor)
    if transition == "restart":
        server.restart()
        await _warm(view, "identity")
    else:
        with MongoClient[BsonDict](mongodb_uri) as writer:
            writer[view.raw.database.name][view.name].update_many(
                {}, {"$set": {"revision": 1}}
            )

        async def refreshed() -> bool:
            pending = view.find_one({"_id": 0})
            current = await pending if isinstance(pending, Awaitable) else pending
            return current is not None and current["revision"] == 1

        await wait_until_async(refreshed)
    await materialize(cursor)
    before = view._shared.snapshot()
    complete = await materialize(_plain_cursor(view, method))
    assert len(complete) == 32
    assert view._shared.snapshot().misses == before.misses + 1
    assert first["revision"] == 0


async def _execute(
    view: View | Collection[BsonDict] | AsyncCollection[BsonDict],
    method: str,
    filter_query: BsonDict,
    **options: object,
) -> object:
    native_options: Mapping[str, Any] = options
    pending: object
    if method == "find":
        return await materialize(view.find(filter_query, **native_options))
    if method == "aggregate":
        return await materialize(
            view.aggregate([{"$match": filter_query}], **native_options)
        )
    if method == "find_one":
        pending = view.find_one(filter_query, **native_options)
    elif method == "count_documents":
        pending = view.count_documents(filter_query, **native_options)
    else:
        pending = view.distinct("payload", filter_query, **native_options)
    return await pending if isinstance(pending, Awaitable) else pending


@pytest.mark.parametrize(
    "method", ["find_one", "find", "aggregate", "count_documents", "distinct"]
)
async def test_user_roles_reads_retain_native_behavior(view: View, method: str) -> None:
    unsafe: BsonDict = {"$expr": {"$eq": ["$$USER_ROLES", []]}}
    before = view._shared.snapshot()
    expected = await _native_outcome(view.raw, method, unsafe)
    assert await _native_outcome(view, method, unsafe) == expected
    assert await _native_outcome(view, method, unsafe) == expected
    after = view._shared.snapshot()
    assert after.hits == before.hits
    assert after.misses == before.misses
    assert after.bypasses == before.bypasses + 2


@pytest.fixture
async def session(view: View) -> AsyncIterator[object]:
    async with AsyncExitStack() as stack:
        if isinstance(view._shared, AsyncSharedCacheManager):
            yield await stack.enter_async_context(view._shared.client.start_session())
        else:
            assert isinstance(view._shared, SharedCacheManager)
            yield stack.enter_context(view._shared.client.start_session())


@pytest.mark.parametrize(
    "method", ["find_one", "find", "aggregate", "count_documents", "distinct"]
)
async def test_session_reads_bypass_shared_results(
    view: View, method: str, session: object
) -> None:
    before = view._shared.snapshot()
    first = await _execute(view, method, {}, session=session)
    assert await _execute(view, method, {}, session=session) == first
    assert view._shared.snapshot().bypasses == before.bypasses + 2
    assert view._shared.snapshot().hits == before.hits
    assert view._shared.snapshot().misses == before.misses


@pytest.mark.parametrize(
    "method", ["find_one", "find", "aggregate", "count_documents", "distinct"]
)
@pytest.mark.parametrize(
    "collation", [{"locale": "simple"}, pytest.param(None, id="collation-object")]
)
async def test_simple_collation_and_option_keys_share_results(
    view: View, method: str, collation: object
) -> None:
    selected = Collation("simple") if collation is None else collation
    first = await _execute(view, method, {"revision": 0}, collation=selected)

    async def hit() -> bool:
        before = view._shared.snapshot().hits
        assert (
            await _execute(view, method, {"revision": 0}, collation=selected) == first
        )
        return view._shared.snapshot().hits > before

    await wait_until_async(hit)


@pytest.mark.parametrize(
    "method", ["find_one", "find", "aggregate", "count_documents", "distinct"]
)
async def test_non_simple_collation_uses_native_reads(view: View, method: str) -> None:
    before = view._shared.snapshot()
    first = await _execute(view, method, {"revision": 0}, collation={"locale": "en"})
    assert (
        await _execute(view, method, {"revision": 0}, collation={"locale": "en"})
        == first
    )
    assert view._shared.snapshot().bypasses == before.bypasses + 2
    assert view._shared.snapshot().misses == before.misses


@pytest.mark.usefixtures("unique_index")
async def test_tenant_predicates_and_unique_keys_keep_separate_entries(
    view: View,
) -> None:
    positive = await _execute(view, "find_one", {"_id": 0, "revision": 0})
    assert positive is not None
    assert await _execute(view, "find_one", {"_id": 0, "revision": -1}) is None
    assert await _execute(view, "find_one", {"payload": "value-0"}) == positive
    assert (
        await _execute(view, "find_one", {"payload": "value-0", "revision": -1}) is None
    )


@pytest.mark.parametrize("method", _METHODS)
async def test_owner_outage_bypasses_and_restart_rewarms_all_methods(
    view: View,
    method: Method,
    server: SharedCacheServer,
    request: pytest.FixtureRequest,
) -> None:
    expected = await _warm(view, method)
    request.getfixturevalue("unavailable_owner")
    assert await _read(view, method) == expected
    server.restart()
    assert await _warm(view, method) == expected


@pytest.fixture
def unavailable_owner(server: SharedCacheServer) -> None:
    process = server._process
    assert process is not None
    process.kill()
    process.join(5)


async def _native_outcome(
    view: View | Collection[BsonDict] | AsyncCollection[BsonDict],
    method: str,
    filter_query: BsonDict,
) -> object:
    try:
        return await _execute(view, method, filter_query)
    except OperationFailure as error:
        return ("native-error", error.code)


async def test_old_cursor_cannot_admit_into_a_reused_handle_after_restart(
    view: View,
    server: SharedCacheServer,
) -> None:
    old = view.find({"revision": 0}).sort("_id", 1).limit(4)
    await advance(old)
    server.restart()
    await _warm(view, "identity_predicate")
    fresh = view.find({"revision": 0}, {"payload": 1}).sort("_id", 1).limit(7)
    await advance(fresh)
    await materialize(old)
    await close_cursor(fresh)
    flushed = view._shared.endpoint.request({"op": "observe"})
    if isinstance(flushed, Awaitable):
        await flushed
    documents = await materialize(
        view.find({"revision": 0}, {"payload": 1}).sort("_id", 1).limit(7)
    )
    assert len(documents) == 7


@pytest.fixture(params=["find", "aggregate"])
async def batched_cursor(
    request: pytest.FixtureRequest,
    view: View,
) -> AsyncIterator[ReadCursor[BsonDict]]:
    pending = view.raw.insert_many(
        {"_id": identity, "payload": "later-batch", "revision": 0}
        for identity in range(100, 340)
    )
    if isinstance(pending, Awaitable):
        await pending
    cursor = await resolve_cursor(
        view.find({}) if request.param == "find" else view.aggregate([{"$match": {}}])
    )
    assert len(await materialize(cursor, 101)) == 101
    assert cursor.cursor_id
    yield cursor
    await close_cursor(cursor)


def _failed_batch(_operation: object) -> None:
    raise ConnectionFailure("injected getMore failure")


async def _failed_async_batch(_operation: object) -> None:
    await asyncio.sleep(0)
    raise ConnectionFailure("injected getMore failure")


@pytest.fixture
def failed_batch(
    monkeypatch: pytest.MonkeyPatch, batched_cursor: ReadCursor[BsonDict]
) -> None:
    monkeypatch.setattr(
        batched_cursor,
        "_send_message",
        _failed_async_batch
        if isinstance(batched_cursor, (AsyncCursor, AsyncCommandCursor))
        else _failed_batch,
    )


@pytest.mark.usefixtures("failed_batch")
async def test_later_batch_error_discards_shared_capture(
    view: View,
    batched_cursor: ReadCursor[BsonDict],
) -> None:
    with pytest.raises(ConnectionFailure, match="injected getMore"):
        await materialize(batched_cursor)
    observed = view._shared.endpoint.request({"op": "observe"})
    if isinstance(observed, Awaitable):
        observed = await observed
    assert observed is not None
    assert observed["captures"] == 0


@pytest.fixture
def paused_batch(
    monkeypatch: pytest.MonkeyPatch, batched_cursor: ReadCursor[BsonDict]
) -> asyncio.Event:
    entered = asyncio.Event()
    pending = asyncio.Event()

    async def pause(_operation: object) -> None:
        entered.set()
        await pending.wait()

    monkeypatch.setattr(batched_cursor, "_send_message", pause)
    return entered


@pytest.mark.parametrize("view", ["async"], indirect=True)
async def test_cancelled_getmore_discards_shared_capture(
    view: View,
    batched_cursor: ReadCursor[BsonDict],
    paused_batch: asyncio.Event,
) -> None:
    consuming = asyncio.create_task(materialize(batched_cursor))
    await paused_batch.wait()
    consuming.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consuming
    manager = view._shared
    assert isinstance(manager, AsyncSharedCacheManager)
    observed = await manager.endpoint.request({"op": "observe"})
    assert observed is not None
    assert observed["captures"] == 0


@pytest.mark.parametrize("method", ["count", "aggregate"])
async def test_failed_scalar_or_initial_command_releases_shared_capture(
    view: View, method: str
) -> None:
    with pytest.raises(OperationFailure):
        await _failed_read(view, method)
    observed = view._shared.endpoint.request({"op": "observe"})
    if isinstance(observed, Awaitable):
        observed = await observed
    assert observed is not None
    assert observed["captures"] == 0


async def _failed_read(view: View, method: str) -> None:
    if method == "count":
        if isinstance(view._shared, AsyncSharedCacheManager):
            assert isinstance(view, AsyncSharedCachedCollection)
            await view.count_documents({}, skip=-1)
        else:
            assert isinstance(view, SharedCachedCollection)
            view.count_documents({}, skip=-1)
    else:
        await materialize(view.aggregate([{"$project": {"payload": 1, "revision": 0}}]))


@pytest.fixture
def oversized_view(view: View, mongodb_uri: MongoDbUri) -> View:
    with MongoClient[BsonDict](mongodb_uri) as writer:
        raw = writer[view.raw.database.name][view.name]
        raw.update_many(
            {},
            [{"$set": {"payload": {"$concat": [{"$toString": "$_id"}, "x" * 70_000]}}}],
        )
    return view


def _plain_cursor(
    view: View, method: str
) -> ReadCursor[BsonDict] | Awaitable[AsyncCommandCursor[BsonDict]]:
    return view.find({}) if method == "find" else view.aggregate([{"$match": {}}])


@pytest.mark.parametrize("method", ["find", "aggregate"])
async def test_partial_oversized_cursor_releases_capture(
    oversized_view: View, method: str
) -> None:
    cursor = await resolve_cursor(_plain_cursor(oversized_view, method))
    await advance(cursor)
    await close_cursor(cursor)
    observed = oversized_view._shared.endpoint.request({"op": "observe"})
    if isinstance(observed, Awaitable):
        observed = await observed
    assert observed is not None
    assert observed["captures"] == 0


@pytest.fixture
def unique_index(view: View, mongodb_uri: MongoDbUri) -> None:
    with MongoClient[BsonDict](mongodb_uri) as writer:
        writer[view.raw.database.name][view.name].create_index("payload", unique=True)


class _NativeQueryText(str):  # noqa: FURB189 - Exercise native BSON string subclasses.
    __slots__ = ()

    def __hash__(self) -> int:
        raise AssertionError("bypassed queries must not construct cache keys")


@pytest.mark.parametrize(
    "method", ["find_one", "find", "aggregate", "count_documents", "distinct"]
)
async def test_session_bypass_does_not_prepare_query_keys(
    view: View, method: str, session: object
) -> None:
    first = await _execute(
        view, method, {"payload": _NativeQueryText("value-0")}, session=session
    )
    expected = await _execute(view.raw, method, {"payload": "value-0"}, session=session)
    assert first == expected


async def test_unportable_identity_reads_preserve_driver_error(view: View) -> None:
    before = view._shared.snapshot()
    query: BsonDict = {"_id": Decimal("1.25")}
    with pytest.raises(InvalidDocument):
        await _execute(view.raw, "find_one", query)
    with pytest.raises(InvalidDocument):
        await _execute(view, "find_one", query)
    assert view._shared.snapshot().bypasses == before.bypasses + 1


@pytest.fixture
async def unportable_view(view: View) -> View:  # noqa: RUF029 - Async manager checks the running loop.
    options: CodecOptions[BsonDict] = CodecOptions(
        tz_aware=True, tzinfo=FixedOffset(60, "UTC+1")
    )
    custom: View
    if isinstance(view, AsyncSharedCachedCollection):
        custom = view._shared.get_cached_collection(
            view.raw.with_options(codec_options=options)
        )
    else:
        custom = view._shared.get_cached_collection(
            view.raw.with_options(codec_options=options)
        )
    return custom


@pytest.mark.parametrize(
    "method", ["find_one", "aggregate", "count_documents", "distinct"]
)
async def test_unportable_namespace_codec_reads_use_native_results(
    unportable_view: View, method: str
) -> None:
    before = unportable_view._shared.snapshot()
    expected = await _execute(unportable_view.raw, method, {"revision": 0})
    assert await _execute(unportable_view, method, {"revision": 0}) == expected
    assert unportable_view._shared.snapshot().bypasses == before.bypasses + 1


async def test_find_one_native_sort_mapping_bypasses_shared_cache(view: View) -> None:
    before = view._shared.snapshot()
    expected = await _execute(view.raw, "find_one", {}, sort={"payload": 1})
    assert await _execute(view, "find_one", {}, sort={"payload": 1}) == expected
    assert view._shared.snapshot().bypasses == before.bypasses + 1


@pytest.mark.parametrize(
    "options", [{"let": {"revision": 0}}, {"comment": "shared-bypass"}]
)
async def test_aggregate_command_options_use_native_cursor(
    view: View, options: Mapping[str, Any]
) -> None:
    before = view._shared.snapshot()
    expected = await _execute(view.raw, "aggregate", {}, **options)
    assert await _execute(view, "aggregate", {}, **options) == expected
    assert view._shared.snapshot().bypasses == before.bypasses + 1
