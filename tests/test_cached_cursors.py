from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from copy import copy, deepcopy
from typing import TYPE_CHECKING

import pytest
from bson.codec_options import CodecOptions, TypeRegistry
from bson.decimal128 import Decimal128
from pymongo import AsyncMongoClient
from pymongo.asynchronous.command_cursor import AsyncCommandCursor
from pymongo.asynchronous.cursor import AsyncCursor
from pymongo.errors import ConnectionFailure, InvalidOperation
from pymongo.synchronous.command_cursor import CommandCursor
from pymongo.synchronous.cursor import Cursor

from client_query_cache.asynchronous.cursors import (
    CachedCommandCursor as AsyncCachedCommandCursor,
)
from client_query_cache.asynchronous.cursors import CachedCursor as AsyncCachedCursor
from client_query_cache.synchronous.cursors import CachedCommandCursor, CachedCursor
from tests.cursor_helpers import (
    advance,
    close_cursor,
    live_capture_ids,
    materialize,
    resolve_cursor,
    with_codec_options,
)

if TYPE_CHECKING:
    from pymongo.asynchronous.client_session import AsyncClientSession
    from pymongo.message import _GetMore, _Query
    from pymongo.synchronous.client_session import ClientSession

    from tests.cursor_fixtures import Binding, CursorFactory, Document, View

from tests.codec_helpers import Decimal128ToDecimalDecoder, fail_decimal_encoding
from tests.cursor_fixtures import DOCUMENT_COUNT

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "source_limit", [0, 10, 100], ids=["unlimited", "equal", "larger"]
)
@pytest.mark.parametrize("matching", [0, 3, 240], ids=["empty", "short", "full"])
async def test_covering_find_returns_an_isolated_prefix(
    cursors: Binding, source_limit: int, matching: int
) -> None:
    view = cursors["view"]
    query = {"_id": {"$lt": matching}}
    complete = cursors["documents"][:matching]
    expected = complete[:10]
    assert await materialize(view.find(query).sort("_id").limit(source_limit)) == (
        complete[:source_limit] if source_limit else complete
    )
    core = view.database.manager.cache_core
    before = core.snapshot()
    cursors["commands"].commands.clear()
    cursor = view.find(query).sort("_id").limit(10)
    prefix = await materialize(cursor)
    assert prefix == expected
    assert cursor.retrieved == len(expected)
    assert cursor.cursor_id == 0
    assert cursor.address is None
    assert cursor.session is None
    assert isinstance(cursor, CachedCursor | AsyncCachedCursor)
    assert cursor._capture is None
    if prefix:
        prefix[0]["nested"]["original"] = False
    assert await materialize(view.find(query).sort("_id").limit(10)) == expected
    assert await materialize(view.find(query).sort("_id").limit(source_limit)) == (
        complete[:source_limit] if source_limit else complete
    )
    after = core.snapshot()
    assert after.hits == before.hits + 3
    assert after.misses == before.misses
    assert (after.entry_count, after.used_bytes) == (
        before.entry_count,
        before.used_bytes,
    )
    assert cursors["commands"].commands == []


@pytest.mark.parametrize(
    ("source_limit", "request_limit"),
    [
        (10, 100),
        (100, 0),
        (-100, 10),
        (100, -10),
        (True, 10),
        (False, 10),
        (100, True),
        (100, False),
    ],
    ids=[
        "smaller",
        "unlimited-request",
        "negative-source",
        "negative-request",
        "true-source",
        "false-source",
        "true-request",
        "false-request",
    ],
)
async def test_incompatible_find_limits_execute_natively(
    cursors: Binding, source_limit: int, request_limit: int
) -> None:
    view = cursors["view"]
    expected = await materialize(view.raw.find({}).sort("_id").limit(request_limit))
    await materialize(view.find({}).sort("_id").limit(source_limit))
    before = view.database.manager.snapshot()
    cursors["commands"].commands.clear()
    assert await materialize(view.find({}).sort("_id").limit(request_limit)) == expected
    assert any("find" in command for command in cursors["commands"].commands)
    assert view.database.manager.snapshot().hits == before.hits


@pytest.mark.parametrize(
    "changed",
    [
        "filter",
        "projection",
        "sort",
        "skip",
        "collation",
        "codec",
        "namespace",
        "database",
        "batch",
        "hint",
        "comment",
    ],
    ids=[
        "filter",
        "projection",
        "sort",
        "skip",
        "collation",
        "codec",
        "collection",
        "database",
        "batch",
        "hint",
        "comment",
    ],
)
async def test_covering_find_preserves_query_boundaries(
    cursors: Binding, changed: str
) -> None:
    view = cursors["view"]
    await materialize(view.find({}).sort("_id").limit(100))
    core = view.database.manager.cache_core
    selected = view
    if changed == "codec":
        selected = with_codec_options(view, CodecOptions(tz_aware=True))
    elif changed == "namespace":
        selected = view.database["other"]
    elif changed == "database":
        selected = view.database.manager["admin"][view.raw.name]
    cursor = (
        selected.find(
            {"_id": {"$gt": 1}} if changed == "filter" else {},
            {"value": 1} if changed == "projection" else None,
        )
        .sort("_id", -1 if changed == "sort" else 1)
        .limit(10)
    )
    if changed == "skip":
        cursor.skip(1)
    elif changed == "collation":
        cursor.collation({"locale": "en"})
    elif changed == "batch":
        cursor.batch_size(0)
    elif changed == "hint":
        cursor.hint("_id_")
    elif changed == "comment":
        cursor.comment("covering-test")
    before = core.snapshot()
    cursors["commands"].commands.clear()
    await materialize(cursor)
    assert core.snapshot().hits == before.hits
    if changed != "namespace":
        assert any("find" in command for command in cursors["commands"].commands)


@pytest.fixture(params=("active", "ended"))
async def cursor_session(
    cursors: Binding, request: pytest.FixtureRequest
) -> AsyncIterator[ClientSession | AsyncClientSession]:
    client = cursors["view"].raw.database.client
    async with AsyncExitStack() as stack:
        session: ClientSession | AsyncClientSession
        if isinstance(client, AsyncMongoClient):
            session = await stack.enter_async_context(client.start_session())
        else:
            session = stack.enter_context(client.start_session())
        if request.param == "ended":
            ended = session.end_session()
            if isinstance(ended, Awaitable):
                await ended
        yield session


async def test_session_find_cannot_reuse_a_covering_source(
    cursors: Binding, cursor_session: ClientSession | AsyncClientSession
) -> None:
    view = cursors["view"]
    await materialize(view.find({}).sort("_id").limit(100))
    core = view.database.manager.cache_core
    before = core.snapshot()
    cursors["commands"].commands.clear()
    if cursor_session.has_ended:
        with pytest.raises(InvalidOperation) as native_error:
            await materialize(
                view.raw.find({}, sort=[("_id", 1)], limit=10, session=cursor_session)
            )
        with pytest.raises(InvalidOperation, match=re.escape(str(native_error.value))):
            await materialize(
                view.find({}, sort=[("_id", 1)], limit=10, session=cursor_session)
            )
    else:
        assert (
            await materialize(
                view.find({}, sort=[("_id", 1)], limit=10, session=cursor_session)
            )
            == cursors["documents"][:10]
        )
        assert any("find" in command for command in cursors["commands"].commands)
    after = core.snapshot()
    assert (after.hits, after.entry_count, after.used_bytes) == (
        before.hits,
        before.entry_count,
        before.used_bytes,
    )


@pytest.mark.parametrize(
    "transition",
    ["write", "clear", "create", "unavailable", "recover"],
    ids=["write", "clear", "create", "unavailable", "recover"],
)
async def test_started_prefix_finishes_but_new_execution_rechecks(
    cursors: Binding, transition: str
) -> None:
    view = cursors["view"]
    core = view.database.manager.cache_core
    namespace = view._namespace()
    await materialize(view.find({}).sort("_id").limit(100))
    hit = view.find({}).sort("_id").limit(10)
    assert await advance(hit) == cursors["documents"][0]
    if transition == "write":
        core.record_write(namespace, 0)
    elif transition == "clear":
        core.clear_namespace(namespace)
    elif transition == "create":
        core.create_namespace(namespace)
    else:
        core.set_database_available(namespace.database, available=False)
        if transition == "recover":
            core.clear_namespace(namespace)
            core.set_database_available(namespace.database, available=True)
    cursors["commands"].commands.clear()
    assert await materialize(hit) == cursors["documents"][1:10]
    assert cursors["commands"].commands == []
    assert (
        await materialize(view.find({}).sort("_id").limit(10))
        == cursors["documents"][:10]
    )
    assert any("find" in command for command in cursors["commands"].commands)


async def test_prefix_clone_rewind_and_indexing_use_final_shape(
    cursors: Binding,
) -> None:
    view = cursors["view"]
    await materialize(view.find({}).sort("_id").skip(2).limit(100))
    cursor = view.find({}).limit(1).skip(2).sort("_id").limit(10)
    cursors["commands"].commands.clear()
    assert await materialize(cursor) == cursors["documents"][2:12]
    assert await materialize(cursor.clone()) == cursors["documents"][2:12]
    rewound = cursor.rewind()
    if isinstance(rewound, Awaitable):
        await rewound
    assert await materialize(cursor) == cursors["documents"][2:12]
    assert cursors["commands"].commands == []
    if isinstance(cursor, Cursor):
        assert (
            await materialize(view.find({}).sort("_id")[2:12])
            == cursors["documents"][2:12]
        )
        assert cursors["commands"].commands == []
        assert view.find({}).sort("_id").limit(1)[2] == cursors["documents"][2]


@pytest.mark.parametrize("source_limit", [0, 100], ids=["unlimited", "larger"])
async def test_partial_source_publishes_no_compatible_prefix(
    cursors: Binding, source_limit: int
) -> None:
    view = cursors["view"]
    source = view.find({}).sort("_id").limit(source_limit)
    assert await materialize(source, 10) == cursors["documents"][:10]
    await close_cursor(source)
    core = view.database.manager.cache_core
    assert not core._namespace(view._namespace()).find_families
    cursors["commands"].commands.clear()
    assert (
        await materialize(view.find({}).sort("_id").limit(5))
        == cursors["documents"][:5]
    )
    assert any("find" in command for command in cursors["commands"].commands)


@pytest.mark.parametrize(
    "completion", ["exhaust", "close", "context"], ids=["exhaust", "close", "context"]
)
async def test_completed_cursor_releases_collector_object(
    cursors: Binding, cursor_factory: CursorFactory, completion: str
) -> None:
    cursor = await resolve_cursor(cursor_factory(cursors["view"]))
    assert await materialize(cursor, 1) == cursors["documents"][:1]
    assert isinstance(
        cursor,
        CachedCursor
        | AsyncCachedCursor
        | CachedCommandCursor
        | AsyncCachedCommandCursor,
    )
    capture_id = id(cursor._capture)
    assert capture_id in live_capture_ids()
    if completion == "exhaust":
        assert await materialize(cursor) == cursors["documents"][1:]
    elif completion == "close":
        await close_cursor(cursor)
    elif isinstance(cursor, AsyncCursor | AsyncCommandCursor):
        async with cursor:
            pass
    else:
        with cursor:
            pass
    assert cursor._capture is None
    assert capture_id not in live_capture_ids()
    assert not cursor.alive


async def test_lazy_find_and_native_validation(cursors: Binding) -> None:
    view = cursors["view"]
    before = view.database.manager.snapshot()
    cursor = view.find({}, None, 0, 0)
    assert isinstance(cursor, Cursor | AsyncCursor)
    assert cursor.collection is view.raw
    assert cursors["commands"].commands == []
    assert view.database.manager.snapshot() == before
    await close_cursor(cursor)
    assert cursors["commands"].commands == []
    with pytest.raises(TypeError):
        view.find({}, filter={})
    with pytest.raises(TypeError):
        view.find({}, skip="invalid")
    with pytest.raises(ValueError, match="batch_size must be >= 0"):
        view.find({}, batch_size=-1)


@pytest.mark.parametrize(
    ("arguments", "options", "error_type"),
    [
        (({},), {"filter": {}}, TypeError),
        (({},), {"skip": "invalid"}, TypeError),
        (({},), {"projection": 42}, TypeError),
        (({},), {"batch_size": -1}, ValueError),
    ],
    ids=["duplicate-filter", "skip", "projection", "batch-size"],
)
async def test_warm_find_keeps_native_constructor_errors(
    cursors: Binding,
    arguments: tuple[object, ...],
    options: dict[str, object],
    error_type: type[Exception],
) -> None:
    view = cursors["view"]
    assert await materialize(view.find({})) == cursors["documents"]
    before = view.database.manager.snapshot()
    cursors["commands"].commands.clear()
    with pytest.raises(error_type) as native_error:
        view.raw.find(*arguments, **options)
    with pytest.raises(error_type, match=re.escape(str(native_error.value))):
        view.find(*arguments, **options)
    assert view.database.manager.snapshot() == before
    assert cursors["commands"].commands == []


async def test_native_streaming_and_complete_admission(
    cursors: Binding, cursor_factory: CursorFactory
) -> None:
    view = cursors["view"]
    cursor = await resolve_cursor(cursor_factory(view))
    assert isinstance(cursor, Cursor | AsyncCursor | CommandCursor | AsyncCommandCursor)
    first = await advance(cursor)
    first["nested"]["original"] = False
    assert view.database.manager.snapshot().entry_count == 0
    assert not any("getMore" in command for command in cursors["commands"].commands)
    rest = await materialize(cursor)
    assert rest == cursors["documents"][1:]
    assert view.database.manager.snapshot().entry_count == 1
    cursors["commands"].commands.clear()
    hit = await resolve_cursor(cursor_factory(view))
    assert await materialize(hit) == cursors["documents"]
    assert cursors["commands"].commands == []
    assert hit.cursor_id == 0
    assert hit.address is None
    assert hit.session is None
    assert not hit.alive


async def test_partial_to_list_and_early_close(
    cursors: Binding, cursor_factory: CursorFactory
) -> None:
    view = cursors["view"]
    cursor = await resolve_cursor(cursor_factory(view))
    assert await materialize(cursor, 1) == cursors["documents"][:1]
    assert view.database.manager.snapshot().entry_count == 0
    await close_cursor(cursor)
    assert not bool(cursor.alive)
    assert await materialize(cursor) == []

    assert isinstance(
        cursor,
        CachedCursor
        | AsyncCachedCursor
        | CachedCommandCursor
        | AsyncCachedCommandCursor,
    )
    assert cursor._capture is None
    assert view.database.manager.snapshot().entry_count == 0
    assert await materialize(cursor_factory(view)) == cursors["documents"]
    assert view.database.manager.snapshot().entry_count == 1


async def test_single_final_batch_requires_caller_consumption(cursors: Binding) -> None:
    view = cursors["view"]
    cursor = view.find({}).sort("_id").limit(3)
    assert await materialize(cursor, 1) == cursors["documents"][:1]
    assert cursor.cursor_id == 0
    assert bool(cursor.alive)
    assert view.database.manager.snapshot().entry_count == 0
    assert await materialize(cursor, 2) == cursors["documents"][1:3]
    assert not bool(cursor.alive)
    assert view.database.manager.snapshot().entry_count == 1


async def test_empty_iteration_admits_a_complete_result(cursors: Binding) -> None:
    view = cursors["view"]
    cursor = view.find({"_id": "no-matching-document"})
    if isinstance(cursor, AsyncCursor):
        assert [document async for document in cursor] == []
    else:
        assert list(cursor) == []
    assert view.database.manager.snapshot().entry_count == 1
    cursors["commands"].commands.clear()
    assert await materialize(view.find({"_id": "no-matching-document"})) == []
    assert cursors["commands"].commands == []


@pytest.mark.parametrize(
    "consumption", ["next", "try_next", "to_list"], ids=["next", "try-next", "to-list"]
)
async def test_empty_command_consumption_and_warm_validation(
    cursors: Binding, consumption: str
) -> None:
    view = cursors["view"]
    pipeline = [{"$match": {"_id": "no-matching-document"}}]
    for warm in (False, True):
        cursors["commands"].commands.clear()
        cursor = await resolve_cursor(view.aggregate(pipeline))
        assert isinstance(cursor, CommandCursor | AsyncCommandCursor)
        if consumption == "next":
            if isinstance(cursor, AsyncCommandCursor):
                with pytest.raises(StopAsyncIteration):
                    await cursor.next()
            else:
                with pytest.raises(StopIteration):
                    cursor.next()
        elif consumption == "try_next":
            document = cursor.try_next()
            if isinstance(document, Awaitable):
                document = await document
            assert document is None
        else:
            assert await materialize(cursor) == []
        assert view.database.manager.snapshot().entry_count == 1
        assert bool(cursors["commands"].commands) is not warm
    for options in ({"collation": "invalid"}, {"batchSize": -1}):
        with pytest.raises(
            TypeError if "collation" in options else ValueError
        ) as native_error:
            await resolve_cursor(view.raw.aggregate(pipeline, **options))
        with pytest.raises(type(native_error.value), match=str(native_error.value)):
            await resolve_cursor(view.aggregate(pipeline, **options))


@pytest.mark.parametrize(
    "transition",
    ["invalidate", "unavailable", "restored", "close"],
    ids=["write", "unavailable", "restored", "manager-close"],
)
async def test_partial_miss_cannot_admit_after_transition(
    cursors: Binding, cursor_factory: CursorFactory, transition: str
) -> None:
    view = cursors["view"]
    cursor = await resolve_cursor(cursor_factory(view))
    assert await materialize(cursor, 1) == cursors["documents"][:1]
    core = view.database.manager.cache_core
    if transition == "invalidate":
        core.record_write(view._namespace(), 0)
    elif transition == "close":
        cleanup = view.database.manager.close()
        if isinstance(cleanup, Awaitable):
            await cleanup
    else:
        core.set_database_available(view.database.name, available=False)
        if transition == "restored":
            core.set_database_available(view.database.name, available=True)
    assert await materialize(cursor) == cursors["documents"][1:]
    assert core.snapshot().entry_count == 0


@pytest.fixture
def failed_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    for cursor_type in (Cursor, CommandCursor):
        original = cursor_type._send_message

        def fail_sync(
            cursor: Cursor[Document] | CommandCursor[Document],
            operation: _Query | _GetMore,
            send: Callable[..., None] = original,
        ) -> None:
            if operation.name == "getMore":
                raise ConnectionFailure("later cursor batch failed")
            send(cursor, operation)

        monkeypatch.setattr(cursor_type, "_send_message", fail_sync)
    for async_cursor_type in (AsyncCursor, AsyncCommandCursor):
        async_original = async_cursor_type._send_message

        async def fail_async(
            cursor: AsyncCursor[Document] | AsyncCommandCursor[Document],
            operation: _Query | _GetMore,
            send: Callable[..., Awaitable[None]] = async_original,
        ) -> None:
            if operation.name == "getMore":
                raise ConnectionFailure("later cursor batch failed")
            await send(cursor, operation)

        monkeypatch.setattr(async_cursor_type, "_send_message", fail_async)


@pytest.mark.usefixtures("failed_batch")
async def test_later_batch_failure_discards_candidate(
    cursors: Binding, cursor_factory: CursorFactory
) -> None:
    cursor = await resolve_cursor(cursor_factory(cursors["view"]))
    assert await materialize(cursor, 101) == cursors["documents"][:101]
    with pytest.raises(ConnectionFailure, match="later cursor batch failed"):
        await materialize(cursor)
    assert not bool(cursor.alive)
    assert cursors["view"].database.manager.snapshot().entry_count == 0
    assert (
        not cursors["view"]
        .database.manager.cache_core._namespace(cursors["view"]._namespace())
        .find_families
    )
    assert await materialize(cursor) == []
    assert isinstance(
        cursor,
        CachedCursor
        | AsyncCachedCursor
        | CachedCommandCursor
        | AsyncCachedCommandCursor,
    )
    assert cursor._capture is None


@pytest.mark.parametrize(
    "transition",
    ["invalidate", "unavailable", "restored", "close"],
    ids=["write", "unavailable", "restored", "manager-close"],
)
async def test_started_hit_retains_snapshot(
    cursors: Binding, cursor_factory: CursorFactory, transition: str
) -> None:
    view = cursors["view"]
    assert await materialize(cursor_factory(view)) == cursors["documents"]
    hit = await resolve_cursor(cursor_factory(view))
    assert await advance(hit) == cursors["documents"][0]
    assert hit.cursor_id == 0
    assert hit.address is None
    assert hit.session is None
    if isinstance(hit, Cursor | AsyncCursor):
        assert hit.retrieved == DOCUMENT_COUNT
    core = view.database.manager.cache_core
    if transition == "invalidate":
        core.record_write(view._namespace(), 0)
    elif transition == "close":
        cleanup = view.database.manager.close()
        if isinstance(cleanup, Awaitable):
            await cleanup
    else:
        core.set_database_available(view.database.name, available=False)
        if transition == "restored":
            core.set_database_available(view.database.name, available=True)
    cursors["commands"].commands.clear()
    assert await materialize(hit) == cursors["documents"][1:]
    await close_cursor(hit)
    assert cursors["commands"].commands == []


async def test_chaining_copy_rewind_and_native_operations(cursors: Binding) -> None:
    view = cursors["view"]
    cursor = view.find({}).sort("_id", -1).skip(2).limit(3)
    expected = list(reversed(cursors["documents"]))[2:5]
    assert await materialize(cursor) == expected
    assert await materialize(copy(cursor)) == expected
    assert await materialize(deepcopy(cursor)) == expected
    with pytest.raises(InvalidOperation):
        cursor.sort("_id")
    core = view.database.manager.cache_core
    core.record_write(view._namespace(), 0)
    rewound = cursor.rewind()
    if isinstance(rewound, Awaitable):
        assert await rewound is cursor
    else:
        assert rewound is cursor
    assert await materialize(cursor) == expected
    assert (
        await materialize(view.find({}).sort("_id").limit(3))
        == cursors["documents"][:3]
    )
    if isinstance(cursor, AsyncCursor):
        with pytest.raises(IndexError, match="does not support indexing"):
            cursor[0]
    else:
        assert view.find({}).sort("_id").limit(1)[2] == cursors["documents"][2]
        assert (
            await materialize(view.find({}).sort("_id")[1:3])
            == cursors["documents"][1:3]
        )


@pytest.mark.parametrize("setting", [0, 1, 5], ids=["default", "one", "five"])
async def test_command_batching_keeps_selected_execution(
    cursors: Binding, setting: int
) -> None:
    view = cursors["view"]
    pipeline = [{"$sort": {"_id": 1}}]
    for warm in (False, True):
        cursors["commands"].commands.clear()
        cursor = await resolve_cursor(view.aggregate(pipeline))
        assert isinstance(cursor, CommandCursor | AsyncCommandCursor)
        assert cursor.batch_size(setting) is cursor
        with pytest.raises(ValueError, match="batch_size must be >= 0"):
            cursor.batch_size(-1)
        with pytest.raises(TypeError):
            cursor.batch_size("invalid")  # type: ignore[arg-type]
        assert await materialize(cursor, 1) == cursors["documents"][:1]
        assert cursor.batch_size(setting) is cursor
        assert await materialize(cursor) == cursors["documents"][1:]
        assert view.database.manager.snapshot().entry_count == 1
        assert bool(cursors["commands"].commands) is not warm
    cursors["commands"].commands.clear()
    before = view.database.manager.snapshot().hits
    bypass = await resolve_cursor(view.aggregate(pipeline, batchSize=3))
    assert len(cursors["commands"].commands) == 1
    assert await materialize(bypass) == cursors["documents"]
    assert view.database.manager.snapshot().hits == before


@pytest.mark.parametrize(
    "option",
    [
        "batch",
        "hint",
        "comment",
        "timeout",
        "flags",
        "removed-flags",
        "explain",
        "distinct",
    ],
    ids=[
        "batch",
        "hint",
        "comment",
        "timeout",
        "flags",
        "removed-flags",
        "explain",
        "distinct",
    ],
)
async def test_unsupported_find_operations_execute_natively(
    cursors: Binding, option: str
) -> None:
    view = cursors["view"]
    assert await materialize(view.find({})) == cursors["documents"]
    before = view.database.manager.snapshot().hits
    cursor = view.find({})
    if option == "batch":
        cursor.batch_size(0)
    elif option == "hint":
        cursor.hint("_id_")
    elif option == "comment":
        cursor.comment("cursor-test")
    elif option == "timeout":
        cursor.max_time_ms(1000)
    elif option == "flags":
        changed = cursor.add_option(0)
        if isinstance(changed, Awaitable):
            await changed
    elif option == "removed-flags":
        assert cursor.remove_option(0) is cursor
    elif option == "explain":
        explanation = cursor.explain()
        if isinstance(explanation, Awaitable):
            explanation = await explanation
        assert "queryPlanner" in explanation
        await close_cursor(cursor)
    else:
        values = cursor.distinct("value")
        if isinstance(values, Awaitable):
            values = await values
        assert sorted(values) == list(range(DOCUMENT_COUNT))
        await close_cursor(cursor)
    if option not in {"explain", "distinct"}:
        assert await materialize(cursor) == cursors["documents"]
    assert view.database.manager.snapshot().hits == before


async def test_positional_aggregate_let_and_comment_execute_natively(
    cursors: Binding,
) -> None:
    view = cursors["view"]
    pipeline: list[Document] = [
        {"$match": {"$expr": {"$gt": ["$value", "$$minimum"]}}},
        {"$sort": {"_id": 1}},
    ]
    before = view.database.manager.snapshot()
    assert await materialize(
        view.aggregate(pipeline, None, {"minimum": 100}, "cursor-arguments")
    ) == await materialize(
        view.raw.aggregate(pipeline, None, {"minimum": 100}, "cursor-arguments")
    )
    after = view.database.manager.snapshot()
    assert after.hits == before.hits
    assert after.entry_count == before.entry_count


async def test_distinct_keeps_plain_dictionary_collation(cursors: Binding) -> None:
    view = cursors["view"]
    native = view.raw.distinct("value", collation={"locale": "simple"})
    cached = view.distinct("value", collation={"locale": "simple"})
    if isinstance(native, Awaitable):
        native = await native
    if isinstance(cached, Awaitable):
        cached = await cached
    assert sorted(cached) == sorted(native) == list(range(DOCUMENT_COUNT))


@pytest.fixture
async def failing_encoder_view(cursors: Binding) -> View:
    view = cursors["view"]
    inserted = view.raw.insert_one(
        {"_id": "decoded-price", "price": Decimal128("1.25")}
    )
    if isinstance(inserted, Awaitable):
        await inserted
    options: CodecOptions[Document] = CodecOptions(
        type_registry=TypeRegistry(
            [Decimal128ToDecimalDecoder()], fallback_encoder=fail_decimal_encoding
        )
    )
    return with_codec_options(view, options)


@pytest.mark.parametrize("method", ["find", "aggregate"], ids=["find", "aggregate"])
async def test_encoding_failure_keeps_native_cursor_delivery(
    failing_encoder_view: View, method: str
) -> None:
    view = failing_encoder_view
    query = {"_id": "decoded-price"}
    argument: Document | list[Document] = (
        query if method == "find" else [{"$match": query}]
    )
    before = view.database.manager.snapshot().entry_count
    native = await materialize(getattr(view.raw, method)(argument))
    assert len(native) == 1
    assert await materialize(getattr(view, method)(argument)) == native
    assert view.database.manager.snapshot().entry_count == before


@pytest.fixture
def paused_batch(monkeypatch: pytest.MonkeyPatch) -> asyncio.Event:
    entered = asyncio.Event()
    release = asyncio.Event()
    for cursor_type in (AsyncCursor, AsyncCommandCursor):
        original = cursor_type._send_message

        async def paused(
            cursor: AsyncCursor[Document] | AsyncCommandCursor[Document],
            operation: _Query | _GetMore,
            send: Callable[..., Awaitable[None]] = original,
        ) -> None:
            if operation.name == "getMore":
                entered.set()
                await release.wait()
            await send(cursor, operation)

        monkeypatch.setattr(cursor_type, "_send_message", paused)
    return entered


@pytest.mark.parametrize("cursors", ["async"], indirect=True)
async def test_cancelled_batch_await_discards_and_closes(
    cursors: Binding, cursor_factory: CursorFactory, paused_batch: asyncio.Event
) -> None:
    cursor = await resolve_cursor(cursor_factory(cursors["view"]))
    assert isinstance(cursor, AsyncCursor | AsyncCommandCursor)
    await materialize(cursor, 101)
    assert cursor.cursor_id
    pending = asyncio.create_task(cursor.to_list())
    await paused_batch.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not bool(cursor.alive)
    assert await cursor.to_list() == []
    assert cursors["view"].database.manager.snapshot().entry_count == 0
    assert (
        not cursors["view"]
        .database.manager.cache_core._namespace(cursors["view"]._namespace())
        .find_families
    )
    assert any("killCursors" in command for command in cursors["commands"].commands)
    assert isinstance(cursor, AsyncCachedCursor | AsyncCachedCommandCursor)
    assert cursor._capture is None
