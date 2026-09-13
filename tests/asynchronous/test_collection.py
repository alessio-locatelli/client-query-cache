import asyncio
import uuid
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from bson import Binary
from bson.binary import UuidRepresentation
from bson.code import Code
from bson.codec_options import CodecOptions
from pymongo import AsyncMongoClient, ReadPreference
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.collation import Collation
from pymongo.cursor import CursorType
from pymongo.errors import OperationFailure
from pymongo.read_concern import ReadConcern

from mongo_client_cache._core.errors import UnsupportedCacheRequestError
from mongo_client_cache._core.manager import CacheCoreConfig
from mongo_client_cache.asynchronous.collection import CachedCollection
from mongo_client_cache.asynchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine

    from tests.conftest import CollectionName, DatabaseName, MongoDbUri

pytestmark = pytest.mark.integration


@pytest.fixture
async def independent_writer(
    mongodb_uri: MongoDbUri,
) -> AsyncIterator[AsyncMongoClient[dict[str, Any]]]:
    async with AsyncMongoClient[dict[str, Any]](mongodb_uri) as client:
        yield client


async def _wait_until(
    predicate: Callable[[], Coroutine[Any, Any, bool]],
    *,
    timeout_seconds: float = 15.0,
) -> None:
    async def _poll() -> None:
        while not await predicate():  # noqa: ASYNC110
            await asyncio.sleep(0.05)

    try:
        async with asyncio.timeout(timeout_seconds):
            await _poll()
    except TimeoutError:  # pragma: no cover (test timeout diagnostic)
        pytest.fail("condition was not met within the timeout")


async def _sorted_distinct(collection: CachedCollection[dict[str, Any]]) -> list[Any]:
    return sorted(await collection.distinct("v"))


@pytest.fixture
def client() -> AsyncMongoClient[dict[str, Any]]:
    return AsyncMongoClient("mongodb://localhost:27017", connect=False)


@pytest.fixture
async def tight_budget_cache_manager(
    raw_mongo_client: AsyncMongoClient[dict[str, Any]],
) -> AsyncIterator[CacheManager[dict[str, Any]]]:
    manager = CacheManager(
        raw_mongo_client,
        cache_config=CacheCoreConfig(shared_budget_bytes=200, max_entry_bytes=50),
    )
    yield manager
    await manager.close()


def test_collection_retains_access_to_the_caller_owned_raw_collection(
    client: AsyncMongoClient[dict[str, Any]],
) -> None:
    manager = CacheManager(client)
    raw_collection = client["example"]["items"]

    collection = CachedCollection(manager["example"], raw_collection)

    assert collection.raw is raw_collection
    assert collection.database.raw == manager["example"].raw
    assert collection.name == "items"


async def test_raw_collection_is_a_fully_functional_pymongo_escape_hatch(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., dict[str, Any]],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()

    await collection.raw.insert_one(document)

    assert await collection.raw.find_one({"_id": document["_id"]}) == document
    assert await collection.raw.count_documents({}) == 1


async def test_composed_facade_and_direct_client_access_can_mix_incrementally(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., dict[str, Any]],
) -> None:
    migrated_collection = cache_manager[cached_database_name][
        nonpersistent_collection_name
    ]
    unmigrated_collection = cache_manager.client[cached_database_name][
        persistent_collection_name
    ]
    migrated_document = make_fake_document()
    unmigrated_document = make_fake_document()

    await migrated_collection.raw.insert_one(migrated_document)
    await unmigrated_collection.insert_one(unmigrated_document)

    assert await migrated_collection.raw.find_one({"_id": migrated_document["_id"]})
    assert await unmigrated_collection.find_one({"_id": unmigrated_document["_id"]})


async def test_manager_never_takes_ownership_of_the_caller_client_lifecycle(
    mongodb_uri: MongoDbUri,
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., dict[str, Any]],
) -> None:
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(mongodb_uri)
    manager = CacheManager(client)
    collection = manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one(make_fake_document())
    del manager, collection

    assert (await client.admin.command("ping"))["ok"] == 1
    await client.close()


async def test_find_one_by_id_bypasses_cache_for_a_session_bound_read(
    cache_manager: CacheManager[dict[str, Any]],
    raw_mongo_client: AsyncMongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., dict[str, Any]],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()
    await collection.raw.insert_one(document)

    async with raw_mongo_client.start_session() as session:
        with patch.object(
            AsyncCollection,
            "find_one",
            autospec=True,
            side_effect=AsyncCollection.find_one,
        ) as spy:
            returned_document = await collection.find_one(
                {"_id": document["_id"]}, session=session
            )

    assert returned_document == document
    spy.assert_called_once_with(
        collection.raw, {"_id": document["_id"]}, None, session=session
    )


@pytest.mark.parametrize(
    "with_options_kwargs",
    [
        pytest.param(
            {"read_preference": ReadPreference.SECONDARY_PREFERRED},
            id="secondary-read-preference",
        ),
        pytest.param(
            {"read_concern": ReadConcern("local")}, id="non-majority-read-concern"
        ),
    ],
)
async def test_find_one_by_id_bypasses_cache_for_an_incompatible_read_profile(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., dict[str, Any]],
    with_options_kwargs: dict[str, Any],
) -> None:
    database = cache_manager[cached_database_name]
    raw_collection = database.raw[nonpersistent_collection_name].with_options(
        **with_options_kwargs
    )
    collection = CachedCollection(database, raw_collection)
    document = make_fake_document()
    await collection.raw.insert_one(document)

    with patch.object(
        AsyncCollection, "find_one", autospec=True, side_effect=AsyncCollection.find_one
    ) as spy:
        returned_document = await collection.find_one({"_id": document["_id"]})

    assert returned_document == document
    spy.assert_called_once_with(
        raw_collection, {"_id": document["_id"]}, None, session=None
    )


async def test_find_one_by_id_preserves_a_non_default_uuid_representation(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    database = cache_manager[cached_database_name]
    raw_collection: AsyncCollection[dict[str, Any]] = database.raw[
        nonpersistent_collection_name
    ].with_options(
        codec_options=CodecOptions(uuid_representation=UuidRepresentation.STANDARD)
    )
    collection = CachedCollection(database, raw_collection)
    identifier = uuid.uuid4()
    await collection.raw.insert_one({"_id": "doc-1", "token": identifier})

    first = await collection.find_one({"_id": "doc-1"})
    second = await collection.find_one({"_id": "doc-1"})

    assert first == {"_id": "doc-1", "token": identifier}
    assert second == first


async def test_find_one_by_a_uuid_id_invalidates_after_an_independent_write(
    cache_manager: CacheManager[dict[str, Any]],
    independent_writer: AsyncMongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    database = cache_manager[cached_database_name]
    raw_collection: AsyncCollection[dict[str, Any]] = database.raw[
        nonpersistent_collection_name
    ].with_options(
        codec_options=CodecOptions(uuid_representation=UuidRepresentation.STANDARD)
    )
    collection = CachedCollection(database, raw_collection)
    identifier = uuid.uuid4()
    await collection.raw.insert_one({"_id": identifier, "v": 1})
    assert await collection.find_one({"_id": identifier}) == {
        "_id": identifier,
        "v": 1,
    }

    binary_identifier = Binary.from_uuid(identifier, UuidRepresentation.STANDARD)
    await independent_writer[cached_database_name][
        nonpersistent_collection_name
    ].update_one({"_id": binary_identifier}, {"$set": {"v": 2}})

    async def _settled() -> bool:
        updated_document = await collection.find_one({"_id": identifier})
        return (updated_document or {}).get("v") == 2

    await _wait_until(_settled)


async def test_find_one_with_a_non_id_filter_bypasses_cache(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., dict[str, Any]],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()
    await collection.raw.insert_one(document)

    with patch.object(
        AsyncCollection, "find_one", autospec=True, side_effect=AsyncCollection.find_one
    ) as spy:
        await collection.find_one({"_id": document["_id"], "extra": "field"})
        await collection.find_one({"_id": document["_id"], "extra": "field"})

    assert spy.call_count == 2


async def test_find_one_with_extra_pymongo_options_bypasses_instead_of_raising(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., dict[str, Any]],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()
    await collection.raw.insert_one(document)

    with patch.object(
        AsyncCollection, "find_one", autospec=True, side_effect=AsyncCollection.find_one
    ) as spy:
        returned_document = await collection.find_one(
            {"_id": document["_id"]}, sort=[("_id", 1)]
        )

    assert returned_document == document
    spy.assert_called_once_with(
        collection.raw,
        {"_id": document["_id"]},
        None,
        session=None,
        sort=[("_id", 1)],
    )


async def test_find_one_by_id_projection_does_not_collide_with_full_document_read(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "doc-1", "a": 1, "b": 2})

    with patch.object(
        AsyncCollection, "find_one", autospec=True, side_effect=AsyncCollection.find_one
    ) as spy:
        full = await collection.find_one({"_id": "doc-1"})
        projected = await collection.find_one({"_id": "doc-1"}, {"a": 1})
        full_again = await collection.find_one({"_id": "doc-1"})
        projected_again = await collection.find_one({"_id": "doc-1"}, {"a": 1})

    assert full == {"_id": "doc-1", "a": 1, "b": 2}
    assert projected == {"_id": "doc-1", "a": 1}
    assert full_again == full
    assert projected_again == projected
    assert spy.call_count == 2


async def test_find_one_by_id_cache_hit_is_isolated_from_caller_mutation(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "doc-1", "tags": ["a", "b"]})

    first = await collection.find_one({"_id": "doc-1"})
    assert first is not None
    first["tags"].append("mutated")

    second = await collection.find_one({"_id": "doc-1"})

    assert second == {"_id": "doc-1", "tags": ["a", "b"]}


async def test_find_by_id_cache_hit_is_isolated_from_caller_mutation(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "doc-1", "tags": ["a", "b"]})

    first = await collection.find({})
    first[0]["tags"].append("mutated")

    second = await collection.find({})

    assert second == [{"_id": "doc-1", "tags": ["a", "b"]}]


async def test_find_one_by_id_negative_result_is_cached(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]

    with patch.object(
        AsyncCollection, "find_one", autospec=True, side_effect=AsyncCollection.find_one
    ) as spy:
        first = await collection.find_one({"_id": "missing"})
        second = await collection.find_one({"_id": "missing"})

    assert first is None
    assert second is None
    assert spy.call_count == 1


async def test_find_one_by_id_invalidates_after_an_independent_write(
    cache_manager: CacheManager[dict[str, Any]],
    independent_writer: AsyncMongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., dict[str, Any]],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()
    await collection.raw.insert_one(document)
    assert await collection.find_one({"_id": document["_id"]}) == document

    await independent_writer[cached_database_name][
        nonpersistent_collection_name
    ].update_one({"_id": document["_id"]}, {"$set": {"marker": "updated"}})

    async def _settled() -> bool:
        updated_document = await collection.find_one({"_id": document["_id"]})
        return (updated_document or {}).get("marker") == "updated"

    await _wait_until(_settled)


async def test_find_one_against_a_view_bypasses_cache(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
) -> None:
    database = cache_manager[cached_database_name]
    await database.raw[persistent_collection_name].insert_one({"_id": "doc-1", "v": 1})
    view_name = f"{persistent_collection_name}_view"
    await database.raw.create_collection(
        view_name, viewOn=persistent_collection_name, pipeline=[]
    )
    view_collection = database[view_name]

    assert await view_collection.find_one({"_id": "doc-1"}) == {"_id": "doc-1", "v": 1}

    with patch.object(
        AsyncCollection, "find_one", autospec=True, side_effect=AsyncCollection.find_one
    ) as spy:
        await view_collection.find_one({"_id": "doc-1"})
        await view_collection.find_one({"_id": "doc-1"})

    assert spy.call_count == 2


async def test_collection_recreated_as_a_view_loses_eligibility(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
) -> None:
    database = cache_manager[cached_database_name]
    ordinary_name = f"{persistent_collection_name}_source"
    wrapped_name = f"{persistent_collection_name}_target"
    await database.raw[ordinary_name].insert_one({"_id": "doc-1", "v": 1})
    await database.raw[wrapped_name].insert_one({"_id": "doc-1", "v": "original"})
    collection = database[wrapped_name]

    assert await collection.find_one({"_id": "doc-1"}) == {
        "_id": "doc-1",
        "v": "original",
    }

    await database.raw.drop_collection(wrapped_name)
    await database.raw.create_collection(
        wrapped_name, viewOn=ordinary_name, pipeline=[]
    )

    async def _settled() -> bool:
        return await collection.find_one({"_id": "doc-1"}) == {"_id": "doc-1", "v": 1}

    await _wait_until(_settled)

    with patch.object(
        AsyncCollection, "find_one", autospec=True, side_effect=AsyncCollection.find_one
    ) as spy:
        await collection.find_one({"_id": "doc-1"})
        await collection.find_one({"_id": "doc-1"})

    assert spy.call_count == 2


async def test_namespace_wrapped_while_absent_and_created_as_a_view_is_detected(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
) -> None:
    database = cache_manager[cached_database_name]
    source_name = f"{persistent_collection_name}_source"
    absent_name = f"{persistent_collection_name}_absent"
    await database.raw[source_name].insert_one({"_id": "doc-1", "v": 1})
    collection = database[absent_name]

    assert await collection.find_one({"_id": "doc-1"}) is None

    await database.raw.create_collection(absent_name, viewOn=source_name, pipeline=[])

    async def _settled() -> bool:
        return await collection.find_one({"_id": "doc-1"}) == {"_id": "doc-1", "v": 1}

    await _wait_until(_settled)

    with patch.object(
        AsyncCollection, "find_one", autospec=True, side_effect=AsyncCollection.find_one
    ) as spy:
        await collection.find_one({"_id": "doc-1"})
        await collection.find_one({"_id": "doc-1"})

    assert spy.call_count == 2


async def test_find_one_bypasses_cache_when_view_inspection_is_unauthorized(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., dict[str, Any]],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()
    await collection.raw.insert_one(document)

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise OperationFailure("not authorized", code=13)

    with (
        patch.object(AsyncDatabase, "list_collections", side_effect=_raise),
        patch.object(
            AsyncCollection,
            "find_one",
            autospec=True,
            side_effect=AsyncCollection.find_one,
        ) as spy,
    ):
        first = await collection.find_one({"_id": document["_id"]})
        second = await collection.find_one({"_id": document["_id"]})

    assert first == document
    assert second == document
    assert spy.call_count == 2


async def test_view_inspection_failure_is_not_memoized_as_a_permanent_view(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., dict[str, Any]],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()
    await collection.raw.insert_one(document)

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise OperationFailure("not authorized", code=13)

    with patch.object(AsyncDatabase, "list_collections", side_effect=_raise):
        await collection.find_one({"_id": document["_id"]})

    with patch.object(
        AsyncCollection,
        "find_one",
        autospec=True,
        side_effect=AsyncCollection.find_one,
    ) as spy:
        first = await collection.find_one({"_id": document["_id"]})
        second = await collection.find_one({"_id": document["_id"]})

    assert first == document
    assert second == document
    assert spy.call_count == 1


async def test_find_one_bypasses_forced_options_while_the_stream_is_unavailable(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_many([{"_id": "a", "v": 1}, {"_id": "b", "v": 2}])
    await collection.find_one({"_id": "a"})

    cache_manager.cache_core.set_database_available(
        cached_database_name, available=False
    )

    with patch.object(
        AsyncCollection, "find_one", autospec=True, side_effect=AsyncCollection.find_one
    ) as spy:
        returned_document = await collection.find_one({"_id": "b"})

    assert returned_document == {"_id": "b", "v": 2}
    spy.assert_called_once_with(collection.raw, {"_id": "b"}, None, session=None)


async def test_find_one_by_id_discards_admission_when_the_query_fails(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., dict[str, Any]],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()
    await collection.raw.insert_one(document)

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    with (
        patch.object(AsyncCollection, "find_one", autospec=True, side_effect=_raise),
        pytest.raises(RuntimeError, match="boom"),
    ):
        await collection.find_one({"_id": document["_id"]})

    assert await collection.find_one({"_id": document["_id"]}) == document


@pytest.mark.parametrize(
    ("patch_target", "invoke", "expected"),
    [
        pytest.param(
            "find_one",
            lambda collection: collection.find_one({"_id": "a"}),
            {"_id": "a", "v": 1},
            id="find_one",
        ),
        pytest.param(
            "find",
            lambda collection: collection.find({}, sort=[("_id", 1)]),
            [{"_id": "a", "v": 1}, {"_id": "b", "v": 2}],
            id="find",
        ),
        pytest.param(
            "aggregate",
            lambda collection: collection.aggregate([{"$sort": {"_id": 1}}]),
            [{"_id": "a", "v": 1}, {"_id": "b", "v": 2}],
            id="aggregate",
        ),
        pytest.param(
            "count_documents",
            lambda collection: collection.count_documents({}),
            2,
            id="count_documents",
        ),
        pytest.param(
            "estimated_document_count",
            lambda collection: collection.estimated_document_count(),
            2,
            id="estimated_document_count",
        ),
        pytest.param(
            "distinct",
            _sorted_distinct,
            [1, 2],
            id="distinct",
        ),
    ],
)
async def test_repeated_reads_are_served_from_cache(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    patch_target: str,
    invoke: Callable[[CachedCollection[dict[str, Any]]], Coroutine[Any, Any, object]],
    expected: object,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_many([{"_id": "a", "v": 1}, {"_id": "b", "v": 2}])

    with patch.object(
        AsyncCollection,
        patch_target,
        autospec=True,
        side_effect=getattr(AsyncCollection, patch_target),
    ) as spy:
        first = await invoke(collection)
        second = await invoke(collection)

    assert first == expected
    assert second == expected
    assert spy.call_count == 1


@pytest.mark.parametrize(
    ("invoke", "settled"),
    [
        pytest.param(
            lambda collection: collection.find({}),
            lambda value: len(value) == 2,
            id="find",
        ),
        pytest.param(
            lambda collection: collection.aggregate([{"$match": {}}]),
            lambda value: len(value) == 2,
            id="aggregate",
        ),
        pytest.param(
            lambda collection: collection.count_documents({}),
            lambda value: value == 2,
            id="count_documents",
        ),
        pytest.param(
            lambda collection: collection.estimated_document_count(),
            lambda value: value == 2,
            id="estimated_document_count",
        ),
        pytest.param(
            lambda collection: collection.distinct("v"),
            lambda value: sorted(value) == [1, 2],
            id="distinct",
        ),
    ],
)
async def test_namespace_guarded_reads_invalidate_after_an_independent_write(
    cache_manager: CacheManager[dict[str, Any]],
    independent_writer: AsyncMongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    invoke: Callable[[CachedCollection[dict[str, Any]]], Coroutine[Any, Any, object]],
    settled: Callable[[object], bool],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "a", "v": 1})
    await invoke(collection)

    await independent_writer[cached_database_name][
        nonpersistent_collection_name
    ].insert_one({"_id": "b", "v": 2})

    async def _settled() -> bool:
        return settled(await invoke(collection))

    await _wait_until(_settled)


async def test_find_shapes_do_not_collide(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_many(
        [{"_id": "a", "v": 1, "extra": "x"}, {"_id": "b", "v": 2, "extra": "y"}]
    )

    with patch.object(
        AsyncCollection, "find", autospec=True, side_effect=AsyncCollection.find
    ) as spy:
        full = await collection.find({})
        projected = await collection.find({}, {"v": 1})
        limited = await collection.find({}, limit=1)
        await collection.find({})
        await collection.find({}, {"v": 1})
        await collection.find({}, limit=1)

    assert full != projected
    assert len(limited) == 1
    assert spy.call_count == 3


async def test_find_with_an_embedded_document_filter_is_order_sensitive(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_many(
        [
            {"_id": "doc1", "x": {"a": 1, "b": 2}},
            {"_id": "doc2", "x": {"b": 2, "a": 1}},
        ]
    )

    first = await collection.find({"x": {"a": 1, "b": 2}})
    second = await collection.find({"x": {"b": 2, "a": 1}})

    assert first == [{"_id": "doc1", "x": {"a": 1, "b": 2}}]
    assert second == [{"_id": "doc2", "x": {"b": 2, "a": 1}}]


async def test_aggregate_with_a_multi_field_sort_is_order_sensitive(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_many(
        [
            {"_id": "a", "x": 1, "y": 2},
            {"_id": "b", "x": 1, "y": 1},
            {"_id": "c", "x": 2, "y": 1},
        ]
    )

    by_x_then_y = await collection.aggregate([{"$sort": {"x": 1, "y": 1}}])
    by_y_then_x = await collection.aggregate([{"$sort": {"y": 1, "x": 1}}])

    assert [doc["_id"] for doc in by_x_then_y] == ["b", "a", "c"]
    assert [doc["_id"] for doc in by_y_then_x] == ["b", "c", "a"]


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"cursor_type": CursorType.TAILABLE}, id="tailable"),
        pytest.param({"cursor_type": CursorType.TAILABLE_AWAIT}, id="tailable-await"),
        pytest.param({"cursor_type": CursorType.EXHAUST}, id="exhaust"),
        pytest.param({"allow_partial_results": True}, id="allow-partial-results"),
    ],
)
async def test_find_rejects_cursor_shapes_it_cannot_fully_materialize(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    kwargs: dict[str, Any],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]

    with pytest.raises(UnsupportedCacheRequestError):
        await collection.find({}, **kwargs)


async def test_aggregate_rejects_a_change_stream_pipeline(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]

    with pytest.raises(UnsupportedCacheRequestError):
        await collection.aggregate([{"$changeStream": {}}])


async def test_aggregate_with_a_now_variable_executes_without_raising_but_is_not_cached(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "a", "start": "2020-01-01T00:00:00Z"})
    pipeline: list[dict[str, Any]] = [{"$project": {"now": "$$NOW"}}]

    with patch.object(
        AsyncCollection,
        "aggregate",
        autospec=True,
        side_effect=AsyncCollection.aggregate,
    ) as spy:
        await collection.aggregate(pipeline)
        await collection.aggregate(pipeline)

    assert spy.call_count == 2


async def test_find_with_an_oversize_result_is_returned_but_never_cached(
    tight_budget_cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = tight_budget_cache_manager[cached_database_name][
        nonpersistent_collection_name
    ]
    await collection.raw.insert_many(
        [{"_id": f"doc-{i}", "padding": "x" * 100} for i in range(5)]
    )

    with patch.object(
        AsyncCollection, "find", autospec=True, side_effect=AsyncCollection.find
    ) as spy:
        first = await collection.find({})
        second = await collection.find({})

    assert first == second
    assert len(first) == 5
    assert spy.call_count == 2


async def test_find_with_a_plain_dict_collation_is_cached(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "a", "v": 1})

    with patch.object(
        AsyncCollection, "find", autospec=True, side_effect=AsyncCollection.find
    ) as spy:
        first = await collection.find({}, collation={"locale": "en"})
        second = await collection.find({}, collation={"locale": "en"})

    assert first == second == [{"_id": "a", "v": 1}]
    assert spy.call_count == 1


async def test_count_documents_with_skip_limit_hint_and_collation_object_is_cached(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_many([{"_id": "a", "v": 1}, {"_id": "b", "v": 2}])
    kwargs: dict[str, Any] = {
        "skip": 1,
        "limit": 1,
        "hint": "_id_",
        "collation": Collation(locale="en"),
    }

    with patch.object(
        AsyncCollection,
        "count_documents",
        autospec=True,
        side_effect=AsyncCollection.count_documents,
    ) as spy:
        first = await collection.count_documents({}, **kwargs)
        second = await collection.count_documents({}, **kwargs)

    assert first == second == 1
    assert spy.call_count == 1


async def test_estimated_document_count_bypasses_cache_for_extra_pymongo_options(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "a", "v": 1})

    with patch.object(
        AsyncCollection,
        "estimated_document_count",
        autospec=True,
        side_effect=AsyncCollection.estimated_document_count,
    ) as spy:
        await collection.estimated_document_count(comment="audit")
        await collection.estimated_document_count(comment="audit")

    assert spy.call_count == 2


@pytest.mark.parametrize(
    ("patch_target", "invoke"),
    [
        pytest.param(
            "find",
            lambda collection: collection.find({"$where": "this.v > 0"}),
            id="find-where",
        ),
        pytest.param(
            "find",
            lambda collection: collection.find({"$expr": {"$rand": {}}}),
            id="find-expr-rand",
        ),
        pytest.param(
            "find",
            lambda collection: collection.find(
                {
                    "$expr": {
                        "$function": {
                            "body": "function() { return true; }",
                            "args": [],
                            "lang": "js",
                        }
                    }
                }
            ),
            id="find-expr-function",
        ),
        pytest.param(
            "count_documents",
            lambda collection: collection.count_documents({"$expr": {"$rand": {}}}),
            id="count_documents-expr-rand",
        ),
        pytest.param(
            "distinct",
            lambda collection: collection.distinct("v", {"$expr": {"$rand": {}}}),
            id="distinct-expr-rand",
        ),
    ],
)
async def test_unsafe_filters_are_never_cached(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    patch_target: str,
    invoke: Callable[[CachedCollection[dict[str, Any]]], Coroutine[Any, Any, object]],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "a", "v": 1})

    with patch.object(
        AsyncCollection,
        patch_target,
        autospec=True,
        side_effect=getattr(AsyncCollection, patch_target),
    ) as spy:
        await invoke(collection)
        await invoke(collection)

    assert spy.call_count == 2


@pytest.mark.parametrize(
    ("patch_target", "insert_doc", "invoke", "expected"),
    [
        pytest.param(
            "find",
            {"_id": "a", "script": Code("function() { return true; }")},
            lambda collection: collection.find(
                {"script": Code("function() { return true; }")}
            ),
            [{"_id": "a", "script": Code("function() { return true; }")}],
            id="find-unhashable-filter-value",
        ),
        pytest.param(
            "find_one",
            {"_id": Code("function() { return true; }"), "v": 1},
            lambda collection: collection.find_one(
                {"_id": Code("function() { return true; }")}
            ),
            {"_id": Code("function() { return true; }"), "v": 1},
            id="find_one-unhashable-identity",
        ),
    ],
)
async def test_reads_with_an_unhashable_value_bypass_instead_of_raising(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    patch_target: str,
    insert_doc: dict[str, Any],
    invoke: Callable[[CachedCollection[dict[str, Any]]], Coroutine[Any, Any, object]],
    expected: object,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one(insert_doc)

    with patch.object(
        AsyncCollection,
        patch_target,
        autospec=True,
        side_effect=getattr(AsyncCollection, patch_target),
    ) as spy:
        first = await invoke(collection)
        second = await invoke(collection)

    assert first == expected
    assert second == expected
    assert spy.call_count == 2


@pytest.mark.parametrize(
    "pipeline",
    [
        pytest.param(
            [
                {
                    "$lookup": {
                        "from": "other",
                        "localField": "v",
                        "foreignField": "v",
                        "as": "j",
                    }
                }
            ],
            id="lookup",
        ),
        pytest.param([{"$sample": {"size": 1}}], id="sample"),
        pytest.param(
            [
                {
                    "$project": {
                        "r": {
                            "$function": {
                                "body": "function(x) {return x;}",
                                "args": ["$v"],
                                "lang": "js",
                            }
                        }
                    }
                }
            ],
            id="function",
        ),
        pytest.param([{"$collStats": {"count": {}}}], id="coll-stats"),
        pytest.param([{"$indexStats": {}}], id="index-stats"),
        pytest.param([{"$planCacheStats": {}}], id="plan-cache-stats"),
    ],
)
async def test_aggregate_with_an_unsafe_pipeline_is_never_cached(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    pipeline: list[dict[str, Any]],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "a", "v": 1})

    with patch.object(
        AsyncCollection,
        "aggregate",
        autospec=True,
        side_effect=AsyncCollection.aggregate,
    ) as spy:
        await collection.aggregate(pipeline)
        await collection.aggregate(pipeline)

    assert spy.call_count == 2


async def test_aggregate_with_an_out_stage_still_executes_its_write_but_is_not_cached(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    persistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "a", "v": 1})
    pipeline: list[dict[str, Any]] = [{"$out": persistent_collection_name}]

    with patch.object(
        AsyncCollection,
        "aggregate",
        autospec=True,
        side_effect=AsyncCollection.aggregate,
    ) as spy:
        await collection.aggregate(pipeline)
        await collection.aggregate(pipeline)

    assert spy.call_count == 2
    target = cache_manager[cached_database_name][persistent_collection_name]
    assert await target.raw.find_one({"_id": "a"}) == {"_id": "a", "v": 1}
