import asyncio
import re
from collections.abc import AsyncIterator, Awaitable
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    AsyncExitStack,
)
from typing import TYPE_CHECKING, Any, Literal, TypedDict

import pytest
from pymongo import AsyncMongoClient, MongoClient
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.errors import InvalidOperation, OperationFailure
from pymongo.synchronous.client_session import ClientSession

from client_query_cache.asynchronous import CachedCollection as AsyncCachedCollection
from client_query_cache.asynchronous import CacheManager as AsyncCacheManager
from client_query_cache.synchronous import CachedCollection, CacheManager
from tests.polling import wait_until_async

if TYPE_CHECKING:
    from tests.conftest import CollectionName, DatabaseName, MongoDbUri

pytestmark = pytest.mark.integration
DOCUMENT_ID = "committed-record"
COMMITTED_VALUE = 1
TRANSACTION_VALUE = 2
INVALID_PROJECTION = 42
INITIAL_DOCUMENT_COUNT = 1
Document = dict[str, Any]  # Can be empty for native projections.
Client = MongoClient[Document] | AsyncMongoClient[Document]
View = CachedCollection[Document] | AsyncCachedCollection[Document]


class Binding(TypedDict):
    client: Client
    view: View


async def execute[T](operation: T | Awaitable[T]) -> T:
    if isinstance(operation, Awaitable):
        return await operation
    return operation


async def enter[T](
    stack: AsyncExitStack,
    context: AbstractContextManager[T] | AbstractAsyncContextManager[T],
) -> T:
    if isinstance(context, AbstractAsyncContextManager):
        return await stack.enter_async_context(context)
    return stack.enter_context(context)


async def session_context(
    stack: AsyncExitStack,
    client: Client,
) -> ClientSession | AsyncClientSession:
    if isinstance(client, MongoClient):
        return stack.enter_context(client.start_session())
    return await stack.enter_async_context(client.start_session())


@pytest.fixture(params=("sync", "async"))
def api(request: pytest.FixtureRequest) -> Literal["sync", "async"]:
    return "sync" if request.param == "sync" else "async"


@pytest.fixture
async def binding(
    api: Literal["sync", "async"],
    mongodb_uri: MongoDbUri,
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> AsyncIterator[Binding]:
    async with AsyncExitStack() as stack:
        if api == "sync":
            sync_client = stack.enter_context(MongoClient[Document](mongodb_uri))
            sync_manager = stack.enter_context(CacheManager(sync_client))
            handles: Binding = {
                "client": sync_client,
                "view": sync_manager[cached_database_name][
                    nonpersistent_collection_name
                ],
            }
        else:
            async_client = await stack.enter_async_context(
                AsyncMongoClient[Document](mongodb_uri)
            )
            async_manager = await stack.enter_async_context(
                AsyncCacheManager(async_client)
            )
            handles = {
                "client": async_client,
                "view": async_manager[cached_database_name][
                    nonpersistent_collection_name
                ],
            }
        await execute(
            handles["view"].raw.insert_one({"_id": DOCUMENT_ID, "v": COMMITTED_VALUE})
        )
        yield handles
        await execute(handles["client"].drop_database(cached_database_name))


async def cache_hit(view: View) -> bool:
    before = view.database.manager.snapshot().hits
    assert await execute(view.find_one(DOCUMENT_ID)) == {
        "_id": DOCUMENT_ID,
        "v": COMMITTED_VALUE,
    }
    return view.database.manager.snapshot().hits > before


@pytest.fixture
async def warm_binding(binding: Binding) -> Binding:
    await wait_until_async(lambda: cache_hit(binding["view"]))
    return binding


async def estimated_count_cache_hit(view: View) -> bool:
    before = view.database.manager.snapshot().hits
    assert await execute(view.estimated_document_count()) == INITIAL_DOCUMENT_COUNT
    return view.database.manager.snapshot().hits > before


@pytest.fixture
async def bound_estimated_count(binding: Binding) -> AsyncIterator[Binding]:
    await wait_until_async(lambda: estimated_count_cache_hit(binding["view"]))
    async with AsyncExitStack() as stack:
        session = await session_context(stack, binding["client"])
        await enter(stack, session.bind(end_session=False))
        await enter(stack, await execute(session.start_transaction()))
        yield binding
        await execute(session.abort_transaction())


async def test_bound_estimated_count_preserves_native_error(
    bound_estimated_count: Binding,
) -> None:
    view = bound_estimated_count["view"]
    before = view.database.manager.snapshot()
    with pytest.raises(OperationFailure) as native_error:
        await execute(view.raw.estimated_document_count())
    assert native_error.value.details is not None
    with pytest.raises(
        OperationFailure, match=re.escape(native_error.value.details["errmsg"])
    ) as cached_error:
        await execute(view.estimated_document_count())
    assert cached_error.value.code == native_error.value.code
    after = view.database.manager.snapshot()
    assert (after.hits, after.misses, after.entry_count, after.used_bytes) == (
        before.hits,
        before.misses,
        before.entry_count,
        before.used_bytes,
    )
    assert after.bypasses == before.bypasses + 1


@pytest.fixture
async def transaction(warm_binding: Binding) -> AsyncIterator[Binding]:
    async with AsyncExitStack() as stack:
        session = await session_context(stack, warm_binding["client"])
        await enter(stack, session.bind(end_session=False))
        await enter(stack, await execute(session.start_transaction()))
        await execute(
            warm_binding["view"].raw.update_one(
                {"_id": DOCUMENT_ID}, {"$set": {"v": TRANSACTION_VALUE}}
            )
        )
        await execute(
            warm_binding["view"].raw.insert_one(
                {"_id": "new-record", "v": TRANSACTION_VALUE}
            )
        )
        yield warm_binding
        await execute(session.abort_transaction())


@pytest.mark.parametrize(
    "explicit_none", [False, True], ids=("omitted", "explicit-none")
)
async def test_bound_transaction_bypasses_a_warm_entry(
    transaction: Binding,
    explicit_none: bool,
) -> None:
    view = transaction["view"]
    before = view.database.manager.snapshot()
    options = {"session": None} if explicit_none else {}  # Can be empty.
    assert (
        await execute(view.find_one(DOCUMENT_ID, **options))
        == await execute(view.raw.find_one(DOCUMENT_ID, **options))
        == {"_id": DOCUMENT_ID, "v": TRANSACTION_VALUE}
    )
    after = view.database.manager.snapshot()
    assert (after.hits, after.misses, after.entry_count, after.used_bytes) == (
        before.hits,
        before.misses,
        before.entry_count,
        before.used_bytes,
    )
    assert after.bypasses == before.bypasses + 1


async def test_cold_bound_result_is_not_admitted(transaction: Binding) -> None:
    view = transaction["view"]
    before = view.database.manager.snapshot()
    assert await execute(view.find_one("new-record")) == {
        "_id": "new-record",
        "v": TRANSACTION_VALUE,
    }
    after = view.database.manager.snapshot()
    assert after.entry_count == before.entry_count
    assert after.misses == before.misses
    assert after.bypasses == before.bypasses + 1


@pytest.fixture
async def foreign_context(
    warm_binding: Binding, mongodb_uri: MongoDbUri
) -> AsyncIterator[Binding]:
    async with AsyncExitStack() as stack:
        client: Client
        if isinstance(warm_binding["client"], MongoClient):
            client = stack.enter_context(MongoClient[Document](mongodb_uri))
        else:
            client = await stack.enter_async_context(
                AsyncMongoClient[Document](mongodb_uri)
            )
        session = await session_context(stack, client)
        await enter(stack, session.bind(end_session=False))
        yield warm_binding


@pytest.mark.parametrize(
    "projection",
    [None, INVALID_PROJECTION],
    ids=("foreign-session", "argument-error-first"),
)
async def test_foreign_context_preserves_native_error_precedence(
    foreign_context: Binding,
    projection: Literal[42] | None,
) -> None:
    view = foreign_context["view"]
    before = view.database.manager.snapshot().hits
    method = "find_one"
    error_type = InvalidOperation if projection is None else TypeError
    with pytest.raises(error_type) as native_error:
        await execute(getattr(view.raw, method)(DOCUMENT_ID, projection=projection))
    with pytest.raises(error_type, match=re.escape(str(native_error.value))):
        await execute(getattr(view, method)(DOCUMENT_ID, projection=projection))
    assert view.database.manager.snapshot().hits == before


async def test_explicit_session_takes_precedence(foreign_context: Binding) -> None:
    view = foreign_context["view"]
    before = view.database.manager.snapshot().hits
    async with AsyncExitStack() as stack:
        session = await session_context(stack, foreign_context["client"])
        if isinstance(view, CachedCollection):
            assert isinstance(session, ClientSession)
            assert view.find_one(DOCUMENT_ID, session=session) == view.raw.find_one(
                DOCUMENT_ID, session=session
            )
        else:
            assert isinstance(session, AsyncClientSession)
            assert await view.find_one(
                DOCUMENT_ID, session=session
            ) == await view.raw.find_one(DOCUMENT_ID, session=session)
    assert view.database.manager.snapshot().hits == before


async def test_bind_exit_restores_hits(warm_binding: Binding) -> None:
    view = warm_binding["view"]
    before = view.database.manager.snapshot().hits
    async with AsyncExitStack() as stack:
        session = await session_context(stack, warm_binding["client"])
        await enter(stack, session.bind(end_session=False))
        assert await execute(view.find_one(DOCUMENT_ID)) == await execute(
            view.raw.find_one(DOCUMENT_ID)
        )
    assert view.database.manager.snapshot().hits == before
    assert await cache_hit(view)


class PendingRead(TypedDict):
    binding: Binding
    release: asyncio.Event
    task: asyncio.Task[object]


async def delayed_read(view: View, release: asyncio.Event) -> object:
    await release.wait()
    return await execute(view.find_one(DOCUMENT_ID))


@pytest.fixture
async def pending_read(warm_binding: Binding) -> AsyncIterator[PendingRead]:
    release = asyncio.Event()
    task = asyncio.create_task(delayed_read(warm_binding["view"], release))
    yield {"binding": warm_binding, "release": release, "task": task}
    release.set()
    await task


@pytest.mark.parametrize("api", ["async"], indirect=True)
async def test_bound_context_does_not_leak_into_existing_task(
    pending_read: PendingRead,
) -> None:
    handles = pending_read["binding"]
    view = handles["view"]
    before = view.database.manager.snapshot()
    async with AsyncExitStack() as stack:
        session = await session_context(stack, handles["client"])
        await enter(stack, session.bind(end_session=False))
        pending_read["release"].set()
        assert await pending_read["task"] == await execute(
            view.raw.find_one(DOCUMENT_ID)
        )
        assert await execute(view.find_one(DOCUMENT_ID)) == await execute(
            view.raw.find_one(DOCUMENT_ID)
        )
    after = view.database.manager.snapshot()
    assert after.hits == before.hits + 1
    assert after.bypasses == before.bypasses + 1
