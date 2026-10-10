from __future__ import annotations

from asyncio import sleep
from time import monotonic
from typing import TYPE_CHECKING, Literal
from unittest.mock import patch

import pytest
from pymongo import AsyncMongoClient
from pymongo.asynchronous.cursor import AsyncCursor
from pymongo.errors import OperationFailure

from client_query_cache import BypassReason
from client_query_cache._core.keys import NamespaceId
from client_query_cache._types import BsonDict

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from faker import Faker

    from client_query_cache.asynchronous.collection import CachedCollection
    from client_query_cache.asynchronous.manager import CacheManager
    from tests.conftest import DatabaseName, MongoDbUri

pytestmark = pytest.mark.integration

ReadMethod = Literal[
    "find_one",
    "find",
    "aggregate",
    "count_documents",
    "estimated_document_count",
    "distinct",
]
READ_METHODS = (
    "find_one",
    "find",
    "aggregate",
    "count_documents",
    "estimated_document_count",
    "distinct",
)
CollectionKind = Literal["collection", "timeseries", "absent"]


@pytest.fixture
async def collection(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    faker: Faker,
    request: pytest.FixtureRequest,
) -> AsyncIterator[CachedCollection[BsonDict]]:
    database = cache_manager[cached_database_name]
    name = faker.pystr()
    kind: CollectionKind = request.param if hasattr(request, "param") else "timeseries"
    if kind != "absent":
        await create_collection(database[name], kind)
    yield database[name]
    await database.raw.client.drop_database(database.name)


@pytest.fixture
async def independent_writer(
    mongodb_uri: MongoDbUri,
) -> AsyncIterator[AsyncMongoClient[BsonDict]]:
    async with AsyncMongoClient[BsonDict](mongodb_uri) as client:
        yield client


async def create_collection(
    collection: CachedCollection[BsonDict], kind: CollectionKind
) -> None:
    if kind == "timeseries":
        await collection.database.raw.create_collection(
            collection.name, timeseries={"timeField": "timestamp"}
        )
    else:
        await collection.database.raw.create_collection(collection.name)


async def wait_until(predicate: Callable[[], bool]) -> None:
    deadline = monotonic() + 10
    while not predicate():
        assert monotonic() < deadline, "Timed out waiting for change-stream delivery"
        await sleep(0.01)


@pytest.fixture
def measurement(faker: Faker) -> BsonDict:
    return {
        "_id": faker.pystr(),
        "timestamp": faker.date_time().replace(microsecond=0),
        "value": faker.pyint(),
    }


async def read(
    collection: CachedCollection[BsonDict],
    method: ReadMethod,
    identity: object,
) -> object:
    match method:
        case "find_one":
            return await collection.find_one({"_id": identity})
        case "find":
            return await collection.find({}).to_list()
        case "aggregate":
            return await (await collection.aggregate([{"$match": {}}])).to_list()
        case "count_documents":
            return await collection.count_documents({})
        case "estimated_document_count":
            return await collection.estimated_document_count()
        case _:
            return await collection.distinct("value")


@pytest.mark.parametrize("method", READ_METHODS, ids=READ_METHODS)
async def test_timeseries_reads_bypass_with_healthy_stream(
    collection: CachedCollection[BsonDict],
    measurement: BsonDict,
    method: ReadMethod,
    independent_writer: AsyncMongoClient[BsonDict],
) -> None:
    cache = collection.database.manager.cache_core
    before = cache.snapshot()
    first = await read(collection, method, measurement["_id"])
    assert cache.is_database_available(collection.database.name)
    assert await read(collection, method, measurement["_id"]) == first
    await independent_writer[collection.database.name][collection.name].insert_one(
        measurement
    )
    after_write = await read(collection, method, measurement["_id"])
    assert after_write != first
    assert await read(collection, method, measurement["_id"]) == after_write
    after = cache.snapshot()
    assert after.hits == before.hits
    assert after.entry_count == before.entry_count
    assert after.bypasses - before.bypasses == 4
    assert (
        next(
            record.count
            for record in after.bypass_reasons
            if record.reason is BypassReason.TIME_SERIES_COLLECTION
        )
        == 4
    )


@pytest.mark.parametrize(
    "with_options", [False, True], ids=["type-bypass", "options-bypass"]
)
@pytest.mark.parametrize("method", READ_METHODS, ids=READ_METHODS)
async def test_timeseries_delegation_preserves_options_and_errors(
    collection: CachedCollection[BsonDict],
    method: ReadMethod,
    faker: Faker,
    with_options: bool,
) -> None:
    arguments = {
        "find_one": ({},),
        "find": ({},),
        "aggregate": ([],),
        "count_documents": ({},),
        "estimated_document_count": (),
        "distinct": ("value",),
    }[method]
    options = {"comment": faker.sentence()} if with_options else {}
    expected_error = OperationFailure(faker.sentence())
    with (
        patch.object(
            AsyncCursor if method == "find" else type(collection.raw),
            "_send_message" if method == "find" else method,
            autospec=True,
            side_effect=expected_error,
        ) as operation,
        pytest.raises(OperationFailure) as raised,
    ):
        await (
            getattr(collection, method)(*arguments, **options).to_list()
            if method == "find"
            else getattr(collection, method)(*arguments, **options)
        )
    assert raised.value is expected_error
    try:
        actual_comment = (
            operation.call_args.args[0]._comment
            if method == "find"
            else operation.call_args.kwargs["comment"]
        )
    except KeyError:
        actual_comment = None
    try:
        expected_comment = options["comment"]
    except KeyError:
        expected_comment = None
    assert actual_comment == expected_comment


@pytest.mark.parametrize(
    "collection",
    ["collection", "timeseries", "absent"],
    indirect=True,
    ids=["ordinary", "timeseries", "absent"],
)
async def test_collection_metadata_probe_counts(
    collection: CachedCollection[BsonDict],
    measurement: BsonDict,
    request: pytest.FixtureRequest,
) -> None:
    database_type = type(collection.database.raw)
    with patch.object(
        database_type,
        "list_collections",
        autospec=True,
        side_effect=database_type.list_collections,
    ) as probe:
        for _ in range(3):
            await collection.find_one({"_id": measurement["_id"]})
    kind = request.node.callspec.params["collection"]
    assert probe.call_count == (3 if kind == "absent" else 1)
    snapshot = collection.database.manager.cache_core.snapshot()
    assert snapshot.hits == (2 if kind == "collection" else 0)
    expected_reason = {
        "collection": None,
        "timeseries": BypassReason.TIME_SERIES_COLLECTION,
        "absent": BypassReason.MISSING_COLLECTION,
    }[kind]
    assert snapshot.bypasses == (0 if kind == "collection" else 3)
    assert {
        record.reason: record.count
        for record in snapshot.bypass_reasons
        if record.count
    } == ({} if expected_reason is None else {expected_reason: 3})


@pytest.mark.parametrize(
    "collection",
    ["absent", "collection"],
    indirect=True,
    ids=["initially-absent", "after-drop"],
)
@pytest.mark.parametrize(
    "replacement", ["timeseries", "collection"], ids=["to-timeseries", "to-ordinary"]
)
async def test_collection_type_is_rechecked_after_absence(
    collection: CachedCollection[BsonDict],
    measurement: BsonDict,
    replacement: CollectionKind,
    request: pytest.FixtureRequest,
) -> None:
    cache = collection.database.manager.cache_core
    namespace = NamespaceId(collection.database.name, collection.name)
    if request.node.callspec.params["collection"] == "collection":
        await collection.raw.insert_one(measurement)
        assert await collection.find_one({"_id": measurement["_id"]}) == measurement
        epoch = cache.current_epoch(namespace)
        await collection.database.raw.drop_collection(collection.name)
        await wait_until(lambda: cache.current_epoch(namespace) > epoch)
    assert await collection.find_one({"_id": measurement["_id"]}) is None
    assert await collection.find_one({"_id": measurement["_id"]}) is None
    assert cache.snapshot().entry_count == 0
    assert (
        next(
            record.count
            for record in cache.snapshot().bypass_reasons
            if record.reason is BypassReason.MISSING_COLLECTION
        )
        == 2
    )
    generation_before_create = cache.capture_namespace_generation(namespace).generation
    await create_collection(collection, replacement)
    await collection.raw.insert_one(measurement)
    if replacement == "collection":
        # Wait for both the create and insert events before priming a cache hit.
        expected_generation = generation_before_create + 2
        await wait_until(
            lambda: (
                cache.capture_namespace_generation(namespace).generation
                >= expected_generation
            )
        )
    assert await collection.find_one({"_id": measurement["_id"]}) == measurement
    before = cache.snapshot()
    assert await collection.find_one({"_id": measurement["_id"]}) == measurement
    after = cache.snapshot()
    assert after.hits - before.hits == (1 if replacement == "collection" else 0)
    assert after.entry_count == (1 if replacement == "collection" else 0)
