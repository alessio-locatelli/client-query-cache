from __future__ import annotations

from asyncio import sleep
from time import monotonic
from typing import TYPE_CHECKING, Literal
from unittest.mock import patch

import pytest
from pymongo import AsyncMongoClient
from pymongo.errors import OperationFailure

from mongo_client_cache._core.keys import NamespaceId

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from faker import Faker

    from mongo_client_cache.asynchronous.collection import CachedCollection
    from mongo_client_cache.asynchronous.manager import CacheManager
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
    cache_manager: CacheManager[dict[str, object]],
    cached_database_name: DatabaseName,
    faker: Faker,
    request: pytest.FixtureRequest,
) -> AsyncIterator[CachedCollection[dict[str, object]]]:
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
) -> AsyncIterator[AsyncMongoClient[dict[str, object]]]:
    async with AsyncMongoClient[dict[str, object]](mongodb_uri) as client:
        yield client


async def create_collection(
    collection: CachedCollection[dict[str, object]], kind: CollectionKind
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
def measurement(faker: Faker) -> dict[str, object]:
    return {
        "_id": faker.pystr(),
        "timestamp": faker.date_time().replace(microsecond=0),
        "value": faker.pyint(),
    }


async def read(
    collection: CachedCollection[dict[str, object]],
    method: ReadMethod,
    identity: object,
) -> object:
    match method:
        case "find_one":
            return await collection.find_one({"_id": identity})
        case "find":
            return await collection.find({})
        case "aggregate":
            return await collection.aggregate([{"$match": {}}])
        case "count_documents":
            return await collection.count_documents({})
        case "estimated_document_count":
            return await collection.estimated_document_count()
        case _:
            return await collection.distinct("value")


@pytest.mark.parametrize("method", READ_METHODS, ids=READ_METHODS)
async def test_timeseries_reads_bypass_with_healthy_stream(
    collection: CachedCollection[dict[str, object]],
    measurement: dict[str, object],
    method: ReadMethod,
    independent_writer: AsyncMongoClient[dict[str, object]],
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


@pytest.mark.parametrize(
    "with_options", [False, True], ids=["type-bypass", "options-bypass"]
)
@pytest.mark.parametrize("method", READ_METHODS, ids=READ_METHODS)
async def test_timeseries_delegation_preserves_options_and_errors(
    collection: CachedCollection[dict[str, object]],
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
            type(collection.raw), method, autospec=True, side_effect=expected_error
        ) as operation,
        pytest.raises(OperationFailure) as raised,
    ):
        await getattr(collection, method)(*arguments, **options)
    assert raised.value is expected_error
    assert operation.call_args.kwargs.get("comment") == options.get("comment")


@pytest.mark.parametrize(
    "collection",
    ["collection", "timeseries", "absent"],
    indirect=True,
    ids=["ordinary", "timeseries", "absent"],
)
async def test_collection_metadata_probe_counts(
    collection: CachedCollection[dict[str, object]],
    measurement: dict[str, object],
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
    collection: CachedCollection[dict[str, object]],
    measurement: dict[str, object],
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
