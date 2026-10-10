import re
import uuid
from operator import itemgetter
from typing import TYPE_CHECKING, Any
from unittest.mock import Mock, patch

import pytest
from bson import Binary
from bson.binary import UuidRepresentation
from bson.code import Code
from bson.codec_options import CodecOptions
from bson.decimal128 import Decimal128
from bson.errors import InvalidDocument
from bson.int64 import Int64
from bson.raw_bson import RawBSONDocument
from pymongo import AsyncMongoClient, ReadPreference
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.command_cursor import AsyncCommandCursor
from pymongo.asynchronous.cursor import AsyncCursor
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.collation import Collation
from pymongo.cursor import CursorType
from pymongo.errors import ConnectionFailure, OperationFailure
from pymongo.read_concern import ReadConcern

from client_query_cache import BypassReason
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCore, CacheCoreConfig
from client_query_cache._types import BsonDict, NonNegativeInt
from client_query_cache.asynchronous.collection import CachedCollection
from client_query_cache.asynchronous.manager import CacheManager
from client_query_cache.asynchronous.streams import DatabaseStreamSupervisor
from tests.codec_helpers import DecodedPriceCase, decode_only_decimal_options
from tests.cursor_helpers import materialize
from tests.polling import wait_until_async as _wait_until
from tests.polling import wait_until_value_async
from tests.stream_helpers import wait_for_stream_barrier_async

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
    from contextlib import AbstractContextManager

    from faker import Faker

    from tests.conftest import CollectionName, DatabaseName, MongoDbUri

pytestmark = pytest.mark.integration

_CAPPED_COLLECTION_BYTES = 4096
_TEXT_INDEX = [("text", "text")]
_GEO_INDEX = [("loc", "2dsphere")]
_ORIGIN: BsonDict = {"type": "Point", "coordinates": [0, 0]}
_VIEW_PROBE_ERRORS = [
    pytest.param(OperationFailure("not authorized", code=13), id="unauthorized"),
    pytest.param(ConnectionFailure("no primary available"), id="connection_failure"),
]


def _spy_on_driver(patch_target: str) -> AbstractContextManager[Mock]:
    if patch_target == "find":
        return patch.object(
            AsyncCursor,
            "_send_message",
            autospec=True,
            side_effect=AsyncCursor._send_message,
        )
    if patch_target == "aggregate":
        return patch.object(
            AsyncCollection,
            "_aggregate",
            autospec=True,
            side_effect=AsyncCollection._aggregate,
        )
    return patch.object(
        AsyncCollection,
        patch_target,
        autospec=True,
        side_effect=getattr(AsyncCollection, patch_target),
    )


def _fake_point(faker: Faker) -> BsonDict:
    return {
        "type": "Point",
        "coordinates": [float(faker.longitude()), float(faker.latitude())],
    }


@pytest.fixture
async def independent_writer(
    mongodb_uri: MongoDbUri,
) -> AsyncIterator[AsyncMongoClient[BsonDict]]:
    async with AsyncMongoClient[BsonDict](mongodb_uri) as client:
        yield client


async def _find_first(
    collection: CachedCollection[BsonDict],
) -> BsonDict | None:
    return (await materialize(collection.find({})))[0]


async def _sorted_distinct(collection: CachedCollection[BsonDict]) -> list[Any]:
    return sorted(await collection.distinct("v"))


@pytest.fixture
def client() -> AsyncMongoClient[BsonDict]:
    return AsyncMongoClient("mongodb://localhost:27017", connect=False)


@pytest.fixture
async def decoded_price_case(
    mongodb_uri: MongoDbUri,
    independent_writer: AsyncMongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
) -> AsyncIterator[DecodedPriceCase[CachedCollection[RawBSONDocument]]]:
    email = faker.email()
    price = faker.pydecimal(left_digits=3, right_digits=2, positive=True)
    document_id = Decimal128(str(faker.pydecimal(left_digits=3, right_digits=2)))
    options = decode_only_decimal_options()
    writer_collection = independent_writer[cached_database_name][
        nonpersistent_collection_name
    ]
    await writer_collection.create_index("email", unique=True)
    await writer_collection.insert_one(
        {"_id": document_id, "email": email, "price": Decimal128(str(price))}
    )
    async with (
        AsyncMongoClient[RawBSONDocument](
            mongodb_uri,
            document_class=RawBSONDocument,
            type_registry=options.type_registry,
        ) as client,
        CacheManager(client) as manager,
    ):
        collection = manager[cached_database_name][nonpersistent_collection_name]
        yield DecodedPriceCase(collection, email, price)


@pytest.fixture
def make_uuid_collection(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> Callable[[NonNegativeInt], CachedCollection[BsonDict]]:
    raw_collection = cache_manager.client[cached_database_name][
        nonpersistent_collection_name
    ]

    def _make_uuid_collection(
        uuid_representation: NonNegativeInt,
    ) -> CachedCollection[BsonDict]:
        return cache_manager.get_cached_collection(
            raw_collection.with_options(
                codec_options=CodecOptions(uuid_representation=uuid_representation)
            )
        )

    return _make_uuid_collection


@pytest.fixture
async def tight_budget_cache_manager(
    raw_mongo_client: AsyncMongoClient[BsonDict],
) -> AsyncIterator[CacheManager[BsonDict]]:
    # Five padded fake documents exceed the 200-byte budget; each exceeds
    # the 50-byte entry limit, so neither individual nor combined reads cache.
    manager = CacheManager(
        raw_mongo_client,
        cache_config=CacheCoreConfig(shared_budget_bytes=200, max_entry_bytes=50),
    )
    yield manager
    await manager.close()


@pytest.mark.parametrize(
    ("get_sub_collection", "expected_name"),
    [
        pytest.param(lambda collection: collection.chunks, "items.chunks", id="attr"),
        pytest.param(itemgetter("chunks"), "items.chunks", id="index"),
        pytest.param(
            itemgetter("insert_one"),
            "items.insert_one",
            id="index-colliding-with-a-pymongo-method",
        ),
    ],
)
def test_collection_sub_collection_access_returns_a_cached_facade(
    client: AsyncMongoClient[BsonDict],
    get_sub_collection: Callable[
        [CachedCollection[BsonDict]], CachedCollection[BsonDict]
    ],
    expected_name: str,
) -> None:
    collection = CacheManager(client).get_cached_collection(client["example"]["items"])

    sub_collection = get_sub_collection(collection)

    assert isinstance(sub_collection, CachedCollection)
    assert sub_collection.name == expected_name
    assert sub_collection.raw.full_name == f"example.{expected_name}"
    assert sub_collection.database is collection.database


@pytest.mark.parametrize(
    "name",
    ["insert_one", "create_index", "drop", "with_options", "codec_options", "_private"],
)
def test_collection_does_not_expose_undeclared_pymongo_attributes(
    client: AsyncMongoClient[BsonDict], name: str
) -> None:
    collection = CacheManager(client).get_cached_collection(client["example"]["items"])

    with pytest.raises(AttributeError, match=repr(name)):
        getattr(collection, name)


async def test_raw_collection_is_a_fully_functional_pymongo_escape_hatch(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., BsonDict],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()

    await collection.raw.insert_one(document)
    index_name = await collection.raw.create_index("email", unique=True)

    assert await collection.raw.find_one({"_id": document["_id"]}) == document
    assert await collection.raw.count_documents({}) == 1
    assert index_name in await collection.raw.index_information()
    await collection.raw.drop()
    assert nonpersistent_collection_name not in (
        await cache_manager.client[cached_database_name].list_collection_names()
    )


def test_optioned_raw_collection_keeps_its_options_through_the_cached_view(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    raw_collection = cache_manager.client[cached_database_name][
        nonpersistent_collection_name
    ].with_options(read_preference=ReadPreference.SECONDARY)

    collection = cache_manager.get_cached_collection(raw_collection)

    assert collection.raw is raw_collection
    assert collection.raw.read_preference == ReadPreference.SECONDARY


async def test_created_raw_collection_is_readable_through_the_cached_view(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    raw_collection = await cache_manager.client[cached_database_name].create_collection(
        nonpersistent_collection_name
    )

    collection = cache_manager.get_cached_collection(raw_collection)

    assert collection.raw is raw_collection
    assert await materialize(collection.find({})) == []


async def test_repeated_cached_views_share_entries_and_one_database_stream(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., BsonDict],
) -> None:
    raw_collection = cache_manager.client[cached_database_name][
        nonpersistent_collection_name
    ]
    document = make_fake_document()
    await raw_collection.insert_one(document)

    with (
        patch.object(
            DatabaseStreamSupervisor,
            "start",
            autospec=True,
            side_effect=DatabaseStreamSupervisor.start,
        ) as start_spy,
        _spy_on_driver("find_one") as find_one_spy,
    ):
        admitted = await cache_manager.get_cached_collection(raw_collection).find_one(
            {"_id": document["_id"]}
        )
        hit = await cache_manager.get_cached_collection(raw_collection).find_one(
            {"_id": document["_id"]}
        )

    assert admitted == hit == document
    assert find_one_spy.call_count == 1
    assert start_spy.call_count == 1


async def test_composed_facade_and_direct_client_access_can_mix(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., BsonDict],
) -> None:
    cached_collection = cache_manager[cached_database_name][
        nonpersistent_collection_name
    ]
    direct_collection = cache_manager.client[cached_database_name][
        persistent_collection_name
    ]
    cached_document = make_fake_document()
    direct_document = make_fake_document()

    await cached_collection.raw.insert_one(cached_document)
    await direct_collection.insert_one(direct_document)

    assert await cached_collection.raw.find_one({"_id": cached_document["_id"]})
    assert await direct_collection.find_one({"_id": direct_document["_id"]})


async def test_manager_never_takes_ownership_of_the_caller_client_lifecycle(
    raw_mongo_client: AsyncMongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., BsonDict],
) -> None:
    client = raw_mongo_client
    manager = CacheManager(client)
    collection = manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one(make_fake_document())
    del manager, collection

    assert (await client.admin.command("ping"))["ok"] == 1


@pytest.mark.parametrize(
    "query_kind", ["identity", "generic"], ids=["identity", "generic"]
)
async def test_find_one_by_id_bypasses_cache_for_a_session_bound_read(
    query_kind: str,
    cache_manager: CacheManager[BsonDict],
    raw_mongo_client: AsyncMongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    make_fake_document: Callable[..., BsonDict],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()
    await collection.raw.insert_one(document)

    query = {"_id": document["_id"]}
    if query_kind == "generic":
        query["$and"] = [{"_id": document["_id"]}]

    async with raw_mongo_client.start_session() as session:
        with _spy_on_driver("find_one") as spy:
            returned_document = await collection.find_one(query, session=session)

    assert returned_document == document
    spy.assert_called_once_with(
        collection.raw,
        query,
        None,
        sort=None,
        collation=None,
        session=session,
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
@pytest.mark.parametrize(
    "query_kind", ["identity", "generic"], ids=["identity", "generic"]
)
async def test_find_one_by_id_bypasses_cache_for_an_incompatible_read_profile(
    query_kind: str,
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    make_fake_document: Callable[..., BsonDict],
    with_options_kwargs: dict[str, Any],
) -> None:
    raw_collection = cache_manager.client[cached_database_name][
        nonpersistent_collection_name
    ].with_options(**with_options_kwargs)
    collection = cache_manager.get_cached_collection(raw_collection)
    document = make_fake_document()
    await collection.raw.insert_one(document)

    query = {"_id": document["_id"]}
    if query_kind == "generic":
        query["$and"] = [{"_id": document["_id"]}]

    with _spy_on_driver("find_one") as spy:
        returned_document = await collection.find_one(query)

    assert returned_document == document
    spy.assert_called_once_with(
        raw_collection,
        query,
        None,
        sort=None,
        collation=None,
        session=None,
    )


async def test_find_one_by_id_preserves_a_non_default_uuid_representation(
    make_uuid_collection: Callable[[NonNegativeInt], CachedCollection[BsonDict]],
) -> None:
    collection = make_uuid_collection(UuidRepresentation.STANDARD)
    identifier = uuid.uuid4()
    await collection.raw.insert_one({"_id": "doc-1", "token": identifier})

    first = await collection.find_one({"_id": "doc-1"})
    second = await collection.find_one({"_id": "doc-1"})

    assert first == {"_id": "doc-1", "token": identifier}
    assert second == first


async def test_find_one_by_a_uuid_id_invalidates_after_an_independent_write(
    independent_writer: AsyncMongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_uuid_collection: Callable[[NonNegativeInt], CachedCollection[BsonDict]],
) -> None:
    collection = make_uuid_collection(UuidRepresentation.STANDARD)
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

    await wait_until_value_async(
        lambda: collection.find_one({"_id": identifier}),
        lambda document: document is not None and document["v"] == 2,
    )


@pytest.mark.parametrize(
    "method", ["find", "find_one"], ids=["find", "generic-find-one"]
)
async def test_reads_with_different_uuid_codecs_do_not_share_a_cache_entry(
    method: str,
    make_uuid_collection: Callable[[NonNegativeInt], CachedCollection[BsonDict]],
) -> None:
    standard_collection = make_uuid_collection(UuidRepresentation.STANDARD)
    legacy_collection = make_uuid_collection(UuidRepresentation.JAVA_LEGACY)
    identifier = uuid.uuid4()
    await standard_collection.raw.insert_one({"_id": "doc-1", "u": identifier})

    first = (
        await standard_collection.find({"u": identifier}).to_list()
        if method == "find"
        else await standard_collection.find_one({"u": identifier})
    )
    second = (
        await legacy_collection.find({"u": identifier}).to_list()
        if method == "find"
        else await legacy_collection.find_one({"u": identifier})
    )

    assert first == (
        [{"_id": "doc-1", "u": identifier}]
        if method == "find"
        else {"_id": "doc-1", "u": identifier}
    )
    assert second == ([] if method == "find" else None)


async def test_find_one_by_compound_ids_with_different_field_order_do_not_collide(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_many(
        [
            {"_id": {"a": 1, "b": 2}, "v": 1},
            {"_id": {"b": 2, "a": 1}, "v": 2},
        ]
    )

    first = await collection.find_one({"_id": {"a": 1, "b": 2}})
    second = await collection.find_one({"_id": {"b": 2, "a": 1}})

    assert first == {"_id": {"a": 1, "b": 2}, "v": 1}
    assert second == {"_id": {"b": 2, "a": 1}, "v": 2}


@pytest.mark.parametrize(
    ("stored_id", "query_id"),
    [
        pytest.param({"a": 1, "b": 2}, {"a": 1, "b": 2}, id="compound"),
        pytest.param(1, 1.0, id="int-queried-as-float"),
    ],
)
async def test_find_one_by_a_compound_or_numeric_id_invalidates_after_a_write(
    cache_manager: CacheManager[BsonDict],
    independent_writer: AsyncMongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    stored_id: object,
    query_id: object,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": stored_id, "v": 1})
    assert await collection.find_one({"_id": query_id}) == {"_id": stored_id, "v": 1}

    await independent_writer[cached_database_name][
        nonpersistent_collection_name
    ].update_one({"_id": stored_id}, {"$set": {"v": 2}})

    await wait_until_value_async(
        lambda: collection.find_one({"_id": query_id}),
        lambda document: document is not None and document["v"] == 2,
    )


@pytest.mark.parametrize(
    ("query_kind", "matches"),
    [
        ("compound", True),
        ("compound", False),
        ("field", True),
        ("operator", True),
        ("empty", True),
        ("none", True),
    ],
    ids=["compound-match", "compound-negative", "field", "operator", "empty", "none"],
)
async def test_generic_find_one_caches_and_isolates_documents(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
    *,
    query_kind: str,
    matches: bool,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = {"_id": faker.uuid4(), "group": faker.word(), "rank": 1}
    await collection.raw.insert_one(document)
    queries = {
        "compound": {
            "_id": document["_id"],
            "group": document["group"] if matches else faker.uuid4(),
        },
        "field": {"group": document["group"]},
        "operator": {"rank": {"$gte": 1}},
        "empty": {},
        "none": None,
    }
    query = queries[query_kind]
    with _spy_on_driver("find_one") as spy:
        first = await collection.find_one(query)
        assert first == (document if matches else None)
        if first is not None:
            first["group"] = faker.uuid4()
        repeated_query = (
            None if query_kind == "empty" else {} if query_kind == "none" else query
        )
        second = await collection.find_one(repeated_query)
    assert second == (document if matches else None)
    assert spy.call_count == 1


@pytest.mark.parametrize(
    "invoke",
    [
        pytest.param(
            lambda collection: materialize(collection.find({"$where": "true"})),
            id="find-unsafe-filter",
        ),
        pytest.param(
            lambda collection: collection.find_one({"$where": "true"}),
            id="find_one-unsafe-filter",
        ),
    ],
)
async def test_facade_bypasses_are_recorded_in_cache_statistics(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    invoke: Callable[[CachedCollection[BsonDict]], Coroutine[Any, Any, object]],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "a", "v": 1})

    before = cache_manager.cache_core.snapshot().bypasses
    await invoke(collection)
    after = cache_manager.cache_core.snapshot().bypasses

    assert after == before + 1


async def test_find_one_by_a_regex_id_uses_generic_caching(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "doc-1", "v": 1})

    with _spy_on_driver("find_one") as spy:
        first = await collection.find_one({"_id": re.compile(r"^doc-")})
        second = await collection.find_one({"_id": re.compile(r"^doc-")})

    assert first == {"_id": "doc-1", "v": 1}
    assert second == {"_id": "doc-1", "v": 1}
    assert spy.call_count == 1


async def test_find_one_with_extra_pymongo_options_bypasses_instead_of_raising(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., BsonDict],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()
    await collection.raw.insert_one(document)

    with _spy_on_driver("find_one") as spy:
        returned_document = await collection.find_one(
            {"_id": document["_id"]}, hint="_id_"
        )

    assert returned_document == document
    spy.assert_called_once_with(
        collection.raw,
        {"_id": document["_id"]},
        None,
        session=None,
        hint="_id_",
        sort=None,
        collation=None,
    )


async def test_find_one_by_id_projection_does_not_collide_with_full_document_read(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "doc-1", "a": 1, "b": 2})

    with _spy_on_driver("find_one") as spy:
        full = await collection.find_one({"_id": "doc-1"})
        projected = await collection.find_one({"_id": "doc-1"}, {"a": 1})
        full_again = await collection.find_one({"_id": "doc-1"})
        projected_again = await collection.find_one({"_id": "doc-1"}, {"a": 1})

    assert full == {"_id": "doc-1", "a": 1, "b": 2}
    assert projected == {"_id": "doc-1", "a": 1}
    assert full_again == full
    assert projected_again == projected
    assert spy.call_count == 2


async def test_unique_key_projection_with_decode_only_codec_strips_id(
    decoded_price_case: DecodedPriceCase[CachedCollection[RawBSONDocument]],
) -> None:
    document = await decoded_price_case.collection.find_one(
        {"email": decoded_price_case.email}, {"_id": 0, "price": 1}
    )

    assert document == {"price": decoded_price_case.price}


@pytest.mark.parametrize(
    "read_document",
    [
        pytest.param(
            lambda collection: collection.find_one({"_id": "doc-1"}), id="find_one"
        ),
        pytest.param(_find_first, id="find"),
    ],
)
async def test_cache_hit_is_isolated_from_caller_mutation(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    read_document: Callable[[CachedCollection[BsonDict]], Awaitable[BsonDict | None]],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "doc-1", "tags": ["a", "b"]})

    first = await read_document(collection)
    assert first is not None
    tags = first["tags"]
    assert isinstance(tags, list)
    tags.append("mutated")

    second = await read_document(collection)

    assert second == {"_id": "doc-1", "tags": ["a", "b"]}


async def test_find_one_by_id_invalidates_after_an_independent_write(
    cache_manager: CacheManager[BsonDict],
    independent_writer: AsyncMongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., BsonDict],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()
    await collection.raw.insert_one(document)
    assert await collection.find_one({"_id": document["_id"]}) == document

    await independent_writer[cached_database_name][
        nonpersistent_collection_name
    ].update_one({"_id": document["_id"]}, {"$set": {"marker": "updated"}})

    await wait_until_value_async(
        lambda: collection.find_one({"_id": document["_id"]}),
        lambda current: (
            current is not None
            and "marker" in current
            and current["marker"] == "updated"
        ),
    )


async def test_find_one_against_a_view_bypasses_cache(
    cache_manager: CacheManager[BsonDict],
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

    with _spy_on_driver("find_one") as spy:
        await view_collection.find_one({"_id": "doc-1"})
        await view_collection.find_one({"_id": "doc-1"})

    assert spy.call_count == 2


async def test_collection_recreated_as_a_view_loses_eligibility(
    cache_manager: CacheManager[BsonDict],
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

    await wait_until_value_async(
        lambda: collection.find_one({"_id": "doc-1"}),
        lambda document: document == {"_id": "doc-1", "v": 1},
    )

    with _spy_on_driver("find_one") as spy:
        await collection.find_one({"_id": "doc-1"})
        await collection.find_one({"_id": "doc-1"})

    assert spy.call_count == 2


async def test_namespace_wrapped_while_absent_and_created_as_a_view_is_detected(
    cache_manager: CacheManager[BsonDict],
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

    await wait_until_value_async(
        lambda: collection.find_one({"_id": "doc-1"}),
        lambda document: document == {"_id": "doc-1", "v": 1},
    )

    with _spy_on_driver("find_one") as spy:
        await collection.find_one({"_id": "doc-1"})
        await collection.find_one({"_id": "doc-1"})

    assert spy.call_count == 2


@pytest.mark.parametrize("probe_error", _VIEW_PROBE_ERRORS)
async def test_find_one_bypasses_cache_when_view_inspection_fails(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., BsonDict],
    caplog: pytest.LogCaptureFixture,
    *,
    probe_error: Exception,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()
    await collection.raw.insert_one(document)

    with (
        caplog.at_level("WARNING", logger="client_query_cache.asynchronous.collection"),
        patch.object(AsyncDatabase, "list_collections", side_effect=probe_error),
        _spy_on_driver("find_one") as spy,
    ):
        first = await collection.find_one({"_id": document["_id"]})
        second = await collection.find_one({"_id": document["_id"]})

    assert first == document
    assert second == document
    assert spy.call_count == 2
    assert caplog.records
    assert all(record.levelname == "WARNING" for record in caplog.records)


@pytest.mark.parametrize("probe_error", _VIEW_PROBE_ERRORS)
async def test_view_inspection_failure_is_not_memoized_as_a_permanent_view(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., BsonDict],
    probe_error: Exception,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()
    await collection.raw.insert_one(document)

    with patch.object(AsyncDatabase, "list_collections", side_effect=probe_error):
        await collection.find_one({"_id": document["_id"]})

    with _spy_on_driver("find_one") as spy:
        first = await collection.find_one({"_id": document["_id"]})
        second = await collection.find_one({"_id": document["_id"]})

    assert first == document
    assert second == document
    assert spy.call_count == 1


async def test_find_one_bypasses_forced_options_while_the_stream_is_unavailable(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_many([{"_id": "a", "v": 1}, {"_id": "b", "v": 2}])
    await collection.find_one({"_id": "a"})

    cache_manager.cache_core.set_database_available(
        cached_database_name, available=False
    )

    with _spy_on_driver("find_one") as spy:
        returned_document = await collection.find_one({"_id": "b"})

    assert returned_document == {"_id": "b", "v": 2}
    spy.assert_called_once_with(
        collection.raw, {"_id": "b"}, None, sort=None, collation=None, session=None
    )


@pytest.mark.parametrize(
    ("patch_target", "invoke", "expected"),
    [
        pytest.param(
            "find_one",
            lambda collection: collection.find_one({"_id": "a"}),
            {"_id": "a", "v": 1, "email": "a@example.com"},
            id="find_one",
        ),
        pytest.param(
            "find_one",
            lambda collection: collection.find_one({"email": "a@example.com"}),
            {"_id": "a", "v": 1, "email": "a@example.com"},
            id="find_one_unresolved_unique_key",
        ),
        pytest.param(
            "find_one",
            lambda collection: collection.find_one(
                {"v": 1, "email": "a@example.com"},
                sort=[("v", 1)],
                collation={"locale": "simple"},
            ),
            {"_id": "a", "v": 1, "email": "a@example.com"},
            id="find_one_generic",
        ),
        pytest.param(
            "find",
            lambda collection: materialize(collection.find({"v": 1})),
            [{"_id": "a", "v": 1, "email": "a@example.com"}],
            id="find",
        ),
        pytest.param(
            "aggregate",
            lambda collection: materialize(
                collection.aggregate([{"$match": {"v": 1}}])
            ),
            [{"_id": "a", "v": 1, "email": "a@example.com"}],
            id="aggregate",
        ),
        pytest.param(
            "count_documents",
            lambda collection: collection.count_documents({"v": 1}),
            1,
            id="count_documents",
        ),
        pytest.param(
            "estimated_document_count",
            lambda collection: collection.estimated_document_count(),
            1,
            id="estimated_document_count",
        ),
        pytest.param(
            "distinct",
            lambda collection: collection.distinct("v"),
            [1],
            id="distinct",
        ),
    ],
)
async def test_reads_recheck_availability_before_forcing_read_options(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    patch_target: str,
    invoke: Callable[[CachedCollection[BsonDict]], Coroutine[Any, Any, object]],
    expected: object,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index("email", unique=True)
    await collection.raw.insert_one({"_id": "a", "v": 1, "email": "a@example.com"})

    with (
        patch.object(CacheCore, "is_database_available", side_effect=[True, False]),
        _spy_on_driver(patch_target) as spy,
    ):
        returned = await invoke(collection)

    assert returned == expected
    assert (
        spy.call_args.args[0].collection
        if patch_target == "find"
        else spy.call_args.args[0]
    ) is collection.raw


async def test_find_one_by_id_discards_admission_when_the_query_fails(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., BsonDict],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()
    await collection.raw.insert_one(document)

    with (
        patch.object(
            AsyncCollection, "find_one", autospec=True, side_effect=RuntimeError("boom")
        ),
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
            lambda collection: materialize(collection.find({}, sort=[("_id", 1)])),
            [{"_id": "a", "v": 1}, {"_id": "b", "v": 2}],
            id="find",
        ),
        pytest.param(
            "aggregate",
            lambda collection: materialize(
                collection.aggregate([{"$sort": {"_id": 1}}])
            ),
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
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    patch_target: str,
    invoke: Callable[[CachedCollection[BsonDict]], Coroutine[Any, Any, object]],
    expected: object,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_many([{"_id": "a", "v": 1}, {"_id": "b", "v": 2}])

    with _spy_on_driver(patch_target) as spy:
        first = await invoke(collection)
        second = await invoke(collection)

    assert first == expected
    assert second == expected
    assert spy.call_count == 1


@pytest.mark.parametrize(
    ("invoke", "settled"),
    [
        pytest.param(
            lambda collection: materialize(collection.find({})),
            lambda value: len(value) == 2,
            id="find",
        ),
        pytest.param(
            lambda collection: materialize(collection.aggregate([{"$match": {}}])),
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
    cache_manager: CacheManager[BsonDict],
    independent_writer: AsyncMongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    invoke: Callable[[CachedCollection[BsonDict]], Coroutine[Any, Any, object]],
    settled: Callable[[object], bool],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "a", "v": 1})
    await invoke(collection)

    await independent_writer[cached_database_name][
        nonpersistent_collection_name
    ].insert_one({"_id": "b", "v": 2})

    await wait_until_value_async(lambda: invoke(collection), settled)


async def test_find_shapes_do_not_collide(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_many(
        [{"_id": "a", "v": 1, "extra": "x"}, {"_id": "b", "v": 2, "extra": "y"}]
    )

    with _spy_on_driver("find") as spy:
        full = await materialize(collection.find({}))
        projected = await materialize(collection.find({}, {"v": 1}))
        limited = await materialize(collection.find({}, limit=1))
        await materialize(collection.find({}))
        await materialize(collection.find({}, {"v": 1}))
        await materialize(collection.find({}, limit=1))

    assert full != projected
    assert len(limited) == 1
    assert limited == full[:1]
    assert spy.call_count == 2


@pytest.mark.parametrize(
    ("first_value", "second_value"),
    [
        pytest.param({"a": 1, "b": 2}, {"b": 2, "a": 1}, id="embedded-field-order"),
        pytest.param({"a": 1}, [["a", 1]], id="mapping-vs-sequence"),
    ],
)
async def test_find_filters_on_distinct_equivalent_looking_values_do_not_collide(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    first_value: object,
    second_value: object,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_many(
        [{"_id": "doc1", "x": first_value}, {"_id": "doc2", "x": second_value}]
    )

    first = await materialize(collection.find({"x": first_value}))
    second = await materialize(collection.find({"x": second_value}))

    assert first == [{"_id": "doc1", "x": first_value}]
    assert second == [{"_id": "doc2", "x": second_value}]


async def test_find_one_bypasses_when_identity_normalization_yields_an_unhashable_value(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "a", "v": 1})

    with (
        patch(
            "client_query_cache.asynchronous.collection.normalize_identity_for_cache_key",
            return_value={1, 2, 3},
        ),
        _spy_on_driver("find_one") as spy,
    ):
        first = await collection.find_one({"_id": "a"})
        second = await collection.find_one({"_id": "a"})

    assert first == {"_id": "a", "v": 1}
    assert second == {"_id": "a", "v": 1}
    assert spy.call_count == 2


async def test_find_one_with_a_nested_elem_match_projection_is_order_sensitive(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one(
        {
            "_id": "doc-1",
            "items": [
                {"sub": {"a": 1, "b": 2}, "tag": "first"},
                {"sub": {"b": 2, "a": 1}, "tag": "second"},
            ],
        }
    )

    first = await collection.find_one(
        {"_id": "doc-1"}, {"items": {"$elemMatch": {"sub": {"a": 1, "b": 2}}}}
    )
    second = await collection.find_one(
        {"_id": "doc-1"}, {"items": {"$elemMatch": {"sub": {"b": 2, "a": 1}}}}
    )

    assert first == {
        "_id": "doc-1",
        "items": [{"sub": {"a": 1, "b": 2}, "tag": "first"}],
    }
    assert second == {
        "_id": "doc-1",
        "items": [{"sub": {"b": 2, "a": 1}, "tag": "second"}],
    }


async def test_aggregate_with_a_multi_field_sort_is_order_sensitive(
    cache_manager: CacheManager[BsonDict],
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

    by_x_then_y = await materialize(collection.aggregate([{"$sort": {"x": 1, "y": 1}}]))
    by_y_then_x = await materialize(collection.aggregate([{"$sort": {"y": 1, "x": 1}}]))

    assert [doc["_id"] for doc in by_x_then_y] == ["b", "a", "c"]
    assert [doc["_id"] for doc in by_y_then_x] == ["b", "c", "a"]


@pytest.mark.parametrize(
    ("other_literal", "other_type"),
    [
        pytest.param(1.0, "double", id="float"),
        pytest.param(Int64(1), "long", id="int64"),
    ],
)
async def test_aggregate_with_equal_int_and_other_numeric_literals_do_not_collide(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    other_literal: object,
    other_type: str,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "a"})

    int_result = await materialize(
        collection.aggregate([{"$project": {"t": {"$type": {"$literal": 1}}}}])
    )
    other_result = await materialize(
        collection.aggregate(
            [{"$project": {"t": {"$type": {"$literal": other_literal}}}}]
        )
    )

    assert int_result == [{"_id": "a", "t": "int"}]
    assert other_result == [{"_id": "a", "t": other_type}]


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"cursor_type": CursorType.TAILABLE}, id="tailable"),
        pytest.param({"cursor_type": CursorType.TAILABLE_AWAIT}, id="tailable-await"),
        pytest.param({"cursor_type": CursorType.EXHAUST}, id="exhaust"),
        pytest.param({"allow_partial_results": True}, id="allow-partial-results"),
    ],
)
async def test_find_executes_cursor_only_requests_natively(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
    kwargs: dict[str, Any],
) -> None:
    database = cache_manager[cached_database_name]
    await database.raw.create_collection(
        nonpersistent_collection_name, capped=True, size=_CAPPED_COLLECTION_BYTES
    )
    collection = database[nonpersistent_collection_name]
    document: BsonDict = {"_id": faker.uuid4(), "name": faker.word()}
    await collection.raw.insert_one(document)

    async with collection.find({}, **kwargs) as cursor:
        assert await anext(cursor) == document

    _assert_only_bypass(cache_manager, BypassReason.UNSUPPORTED_OPTIONS)


async def test_aggregate_executes_change_stream_pipeline_natively(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]

    async with await collection.aggregate([{"$changeStream": {}}]) as cursor:
        assert type(cursor) is AsyncCommandCursor

    _assert_only_bypass(cache_manager, BypassReason.UNSAFE_PIPELINE)


@pytest.mark.parametrize(
    "pipeline",
    [
        pytest.param(
            [{"$search": {"text": {"query": "coffee", "path": "text"}}}], id="search"
        ),
        pytest.param(
            [{"$searchMeta": {"text": {"query": "coffee", "path": "text"}}}],
            id="search-meta",
        ),
        pytest.param(
            [
                {
                    "$vectorSearch": {
                        "index": "embedding",
                        "path": "embedding",
                        "queryVector": [0.5, 0.5],
                        "numCandidates": 1,
                        "limit": 1,
                    }
                }
            ],
            id="vector-search",
        ),
        pytest.param([{"$listSearchIndexes": {}}], id="list-search-indexes"),
    ],
)
async def test_aggregate_executes_search_pipelines_natively(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
    pipeline: list[BsonDict],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": faker.uuid4(), "text": faker.sentence()})

    with pytest.raises(OperationFailure) as cached_error:
        await materialize(collection.aggregate(pipeline))
    with pytest.raises(OperationFailure) as native_error:
        await materialize(collection.raw.aggregate(pipeline))

    assert cached_error.value.code == native_error.value.code
    _assert_only_bypass(cache_manager, BypassReason.UNSAFE_PIPELINE)


def _assert_only_bypass(
    cache_manager: CacheManager[BsonDict], reason: BypassReason
) -> None:
    snapshot = cache_manager.snapshot()
    assert snapshot.hits == snapshot.misses == snapshot.entry_count == 0
    assert {
        record.reason: record.count for record in snapshot.bypass_reasons
    } == dict.fromkeys(BypassReason, 0) | {reason: 1}


async def test_find_with_an_oversize_result_is_returned_but_never_cached(
    tight_budget_cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = tight_budget_cache_manager[cached_database_name][
        nonpersistent_collection_name
    ]
    await collection.raw.insert_many(
        [{"_id": f"doc-{i}", "padding": "x" * 100} for i in range(5)]
    )

    with _spy_on_driver("find") as spy:
        first = await materialize(collection.find({}))
        second = await materialize(collection.find({}))

    assert first == second
    assert len(first) == 5
    assert spy.call_count == 2


async def test_find_with_a_plain_dict_collation_is_cached(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "a", "v": 1})

    with _spy_on_driver("find") as spy:
        first = await materialize(collection.find({}, collation={"locale": "en"}))
        second = await materialize(collection.find({}, collation={"locale": "en"}))

    assert first == second == [{"_id": "a", "v": 1}]
    assert spy.call_count == 1


@pytest.mark.parametrize("read_state", ["cold", "warm", "bypass"])
@pytest.mark.parametrize(
    ("options", "error_type"),
    [
        ({"limit": 0}, OperationFailure),
        ({"limit": None}, OperationFailure),
        ({"skip": None}, OperationFailure),
        ({"hint": None}, TypeError),
    ],
    ids=("zero-limit", "null-limit", "null-skip", "null-hint"),
)
async def test_count_documents_preserves_explicit_invalid_options(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    read_state: str,
    options: dict[str, Any],
    error_type: type[Exception],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "counted"})
    if read_state == "warm":
        assert await collection.count_documents({}) == 1
        assert await collection.count_documents({}) == 1
    elif read_state == "bypass":
        options = {**options, "comment": "count-option-bypass"}

    with pytest.raises(error_type) as native_error:
        await collection.raw.count_documents({}, **options)
    with pytest.raises(error_type) as cached_error:
        await collection.count_documents({}, **options)
    if isinstance(native_error.value, OperationFailure):
        assert isinstance(cached_error.value, OperationFailure)
        assert cached_error.value.code == native_error.value.code
    else:
        assert str(cached_error.value) == str(native_error.value)


@pytest.mark.parametrize("options", [{}, {"skip": 0}], ids=("omitted", "zero-skip"))
async def test_count_documents_reuses_equivalent_skip_entries(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    options: dict[str, Any],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "counted"})
    other_options: dict[str, Any] = {} if options else {"skip": 0}
    with _spy_on_driver("count_documents") as spy:
        assert await collection.count_documents({}, **other_options) == 1
        assert await collection.count_documents({}, **options) == 1
        assert await collection.count_documents({}, **options) == 1
    assert spy.call_count == 1
    assert spy.call_args.kwargs == {"session": None, **other_options}


async def test_count_documents_with_skip_limit_hint_and_collation_object_is_cached(
    cache_manager: CacheManager[BsonDict],
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

    with _spy_on_driver("count_documents") as spy:
        first = await collection.count_documents({}, **kwargs)
        second = await collection.count_documents({}, **kwargs)

    assert first == second == 1
    assert spy.call_count == 1


async def test_estimated_document_count_bypasses_cache_for_extra_pymongo_options(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "a", "v": 1})

    with _spy_on_driver("estimated_document_count") as spy:
        await collection.estimated_document_count(comment="audit")
        await collection.estimated_document_count(comment="audit")

    assert spy.call_count == 2


@pytest.mark.parametrize(
    ("patch_target", "invoke", "index_keys"),
    [
        pytest.param(
            "find",
            lambda collection: materialize(collection.find({"$where": "this.v > 0"})),
            None,
            id="find-where",
        ),
        pytest.param(
            "find",
            lambda collection: materialize(collection.find({"$expr": {"$rand": {}}})),
            None,
            id="find-expr-rand",
        ),
        pytest.param(
            "find",
            lambda collection: materialize(
                collection.find(
                    {
                        "$expr": {
                            "$function": {
                                "body": "function() { return true; }",
                                "args": [],
                                "lang": "js",
                            }
                        }
                    }
                )
            ),
            None,
            id="find-expr-function",
        ),
        pytest.param(
            "count_documents",
            lambda collection: collection.count_documents({"$expr": {"$rand": {}}}),
            None,
            id="count_documents-expr-rand",
        ),
        pytest.param(
            "distinct",
            lambda collection: collection.distinct("v", {"$expr": {"$rand": {}}}),
            None,
            id="distinct-expr-rand",
        ),
        pytest.param(
            "find_one",
            lambda collection: collection.find_one({"$text": {"$search": "hello"}}),
            _TEXT_INDEX,
            id="find_one-text-search",
        ),
        pytest.param(
            "find",
            lambda collection: materialize(
                collection.find({"$text": {"$search": "hello"}})
            ),
            _TEXT_INDEX,
            id="find-text-search",
        ),
        pytest.param(
            "count_documents",
            lambda collection: collection.count_documents(
                {"$text": {"$search": "hello"}}
            ),
            _TEXT_INDEX,
            id="count_documents-text-search",
        ),
        pytest.param(
            "distinct",
            lambda collection: collection.distinct(
                "text", {"$text": {"$search": "hello"}}
            ),
            _TEXT_INDEX,
            id="distinct-text-search",
        ),
        pytest.param(
            "find",
            lambda collection: materialize(
                collection.find({"$expr": {"$in": ["admin", "$$USER_ROLES.role"]}})
            ),
            None,
            id="find-expr-user-roles",
        ),
        pytest.param(
            "find_one",
            lambda collection: collection.find_one(
                {"loc": {"$near": {"$geometry": _ORIGIN}}}
            ),
            _GEO_INDEX,
            id="find_one-near",
        ),
        pytest.param(
            "find",
            lambda collection: materialize(
                collection.find({"loc": {"$near": {"$geometry": _ORIGIN}}})
            ),
            _GEO_INDEX,
            id="find-near",
        ),
        pytest.param(
            "distinct",
            lambda collection: collection.distinct(
                "v", {"loc": {"$near": {"$geometry": _ORIGIN}}}
            ),
            _GEO_INDEX,
            id="distinct-near",
        ),
        pytest.param(
            "find_one",
            lambda collection: collection.find_one(
                {"loc": {"$nearSphere": {"$geometry": _ORIGIN}}}
            ),
            _GEO_INDEX,
            id="find_one-near-sphere",
        ),
        pytest.param(
            "find",
            lambda collection: materialize(
                collection.find({"loc": {"$nearSphere": {"$geometry": _ORIGIN}}})
            ),
            _GEO_INDEX,
            id="find-near-sphere",
        ),
        pytest.param(
            "distinct",
            lambda collection: collection.distinct(
                "v", {"loc": {"$nearSphere": {"$geometry": _ORIGIN}}}
            ),
            _GEO_INDEX,
            id="distinct-near-sphere",
        ),
    ],
)
async def test_unsafe_filters_are_never_cached(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
    *,
    patch_target: str,
    invoke: Callable[[CachedCollection[BsonDict]], Coroutine[Any, Any, object]],
    index_keys: list[tuple[str, str]] | None,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    if index_keys is not None:
        await collection.raw.create_index(index_keys)
    await collection.raw.insert_one(
        {"_id": "a", "v": 1, "text": "hello world", "loc": _fake_point(faker)}
    )

    with _spy_on_driver(patch_target) as spy:
        await invoke(collection)
        await invoke(collection)

    assert spy.call_count == 2


@pytest.mark.parametrize(
    "projection",
    [
        pytest.param({"r": {"$rand": {}}}, id="rand"),
        pytest.param(
            {
                "r": {
                    "$function": {
                        "body": "function() { return 1; }",
                        "args": [],
                        "lang": "js",
                    }
                }
            },
            id="function",
        ),
        pytest.param({"now": "$$NOW"}, id="now-variable"),
        pytest.param({"time": "$$CLUSTER_TIME"}, id="cluster-time-variable"),
        pytest.param({"roles": "$$USER_ROLES"}, id="user-roles-variable"),
    ],
)
@pytest.mark.parametrize(
    ("patch_target", "invoke"),
    [
        pytest.param(
            "find_one",
            lambda collection, projection: collection.find_one(
                {"_id": "a"}, projection
            ),
            id="find_one",
        ),
        pytest.param(
            "find",
            lambda collection, projection: materialize(collection.find({}, projection)),
            id="find",
        ),
    ],
)
async def test_unsafe_projections_are_never_cached(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    patch_target: str,
    invoke: Callable[
        [CachedCollection[BsonDict], BsonDict], Coroutine[Any, Any, object]
    ],
    projection: BsonDict,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "a", "v": 1})

    with _spy_on_driver(patch_target) as spy:
        await invoke(collection, projection)
        await invoke(collection, projection)

    assert spy.call_count == 2


async def test_find_with_a_meta_projection_is_never_cached(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index([("text", "text")])
    await collection.raw.insert_one({"_id": "a", "text": "hello world"})

    with _spy_on_driver("find") as spy:
        await materialize(
            collection.find(
                {"$text": {"$search": "hello"}}, {"score": {"$meta": "textScore"}}
            )
        )
        await materialize(
            collection.find(
                {"$text": {"$search": "hello"}}, {"score": {"$meta": "textScore"}}
            )
        )

    assert spy.call_count == 2


@pytest.mark.parametrize(
    ("patch_target", "insert_doc", "invoke", "expected"),
    [
        pytest.param(
            "find",
            {"_id": "a", "script": Code("function() { return true; }")},
            lambda collection: materialize(
                collection.find({"script": Code("function() { return true; }")})
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
        pytest.param(
            "find_one",
            {"_id": "a", "items": [{"sub": 1}]},
            lambda collection: collection.find_one(
                {"_id": "a"},
                {"items": {"$elemMatch": {"sub": Code("function() { return true; }")}}},
            ),
            {"_id": "a"},
            id="find_one-unhashable-projection",
        ),
        pytest.param(
            "find_one",
            {"_id": "a", "tag": Code("function() { return true; }")},
            lambda collection: collection.find_one(
                {"tag": Code("function() { return true; }")}
            ),
            {"_id": "a", "tag": Code("function() { return true; }")},
            id="find_one-unhashable-unique-key-value",
        ),
    ],
)
async def test_reads_with_an_unhashable_value_bypass_instead_of_raising(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    patch_target: str,
    insert_doc: BsonDict,
    invoke: Callable[[CachedCollection[BsonDict]], Coroutine[Any, Any, object]],
    expected: object,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index("tag", unique=True)
    await collection.raw.insert_one(insert_doc)

    with _spy_on_driver(patch_target) as spy:
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
        pytest.param([{"$project": {"now": "$$NOW"}}], id="now-variable"),
        pytest.param(
            [{"$project": {"roles": "$$USER_ROLES"}}], id="user-roles-variable"
        ),
    ],
)
async def test_aggregate_with_an_unsafe_pipeline_is_never_cached(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    pipeline: list[BsonDict],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "a", "v": 1})

    with _spy_on_driver("aggregate") as spy:
        await materialize(collection.aggregate(pipeline))
        await materialize(collection.aggregate(pipeline))

    assert spy.call_count == 2


@pytest.mark.parametrize(
    ("index_keys", "pipeline"),
    [
        pytest.param(
            _GEO_INDEX,
            [{"$geoNear": {"near": _ORIGIN, "distanceField": "distance"}}],
            id="geo-near",
        ),
        pytest.param(
            _TEXT_INDEX,
            [{"$match": {"$text": {"$search": "hello"}}}],
            id="text-search",
        ),
    ],
)
async def test_aggregate_with_an_index_dependent_pipeline_is_never_cached(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
    *,
    index_keys: list[tuple[str, str]],
    pipeline: list[BsonDict],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index(index_keys)
    await collection.raw.insert_one(
        {
            "_id": faker.uuid4(),
            "loc": _fake_point(faker),
            "text": f"hello {faker.word()}",
        }
    )

    with _spy_on_driver("aggregate") as spy:
        await materialize(collection.aggregate(pipeline))
        await materialize(collection.aggregate(pipeline))

    assert spy.call_count == 2


async def test_aggregate_with_an_out_stage_still_executes_its_write_but_is_not_cached(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    persistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.insert_one({"_id": "a", "v": 1})
    pipeline: list[BsonDict] = [{"$out": persistent_collection_name}]

    with _spy_on_driver("aggregate") as spy:
        await materialize(collection.aggregate(pipeline))
        await materialize(collection.aggregate(pipeline))

    assert spy.call_count == 2
    target = cache_manager[cached_database_name][persistent_collection_name]
    assert await target.raw.find_one({"_id": "a"}) == {"_id": "a", "v": 1}


@pytest.mark.parametrize(
    "filter_query",
    [{"rank": {"$gte": 1}}, {"_id": "first"}, {"email": "first@example.com"}],
    ids=["generic", "identity", "unique"],
)
async def test_find_one_sort_and_projection_shapes_do_not_collide(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    filter_query: BsonDict,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index("email", unique=True)
    first_document = {"_id": "first", "rank": 1, "email": "first@example.com"}
    last_document = {"_id": "last", "rank": 2, "email": "last@example.com"}
    await collection.raw.insert_many([first_document, last_document])
    with _spy_on_driver("find_one") as spy:
        ascending = await collection.find_one(filter_query, sort=[("rank", 1)])
        descending = await collection.find_one(filter_query, sort=[("rank", -1)])
        projected = await collection.find_one(
            filter_query, {"rank": 1, "_id": 0}, sort=[("rank", -1)]
        )
        assert await collection.find_one(filter_query, sort=[("rank", 1)]) == ascending
        assert (
            await collection.find_one(filter_query, sort=[("rank", -1)]) == descending
        )
        assert (
            await collection.find_one(
                filter_query, {"rank": 1, "_id": 0}, sort=[("rank", -1)]
            )
            == projected
        )
    assert ascending == first_document
    expected_descending = last_document if "rank" in filter_query else first_document
    assert descending == expected_descending
    assert projected == {"rank": expected_descending["rank"]}
    assert spy.call_count == 3


@pytest.mark.parametrize("scalar_identity", [False, True], ids=["mapping", "scalar"])
async def test_find_one_inherited_collation_uses_namespace_invalidation(
    cache_manager: CacheManager[BsonDict],
    independent_writer: AsyncMongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    scalar_identity: bool,
    faker: Faker,
) -> None:
    database = cache_manager[cached_database_name]
    await database.raw.create_collection(
        nonpersistent_collection_name, collation={"locale": "en", "strength": 2}
    )
    collection = database[nonpersistent_collection_name]
    stored_identity = faker.lexify("????????").upper()
    query_identity = stored_identity.lower()
    document = {"_id": stored_identity, "rank": 1}
    await collection.raw.insert_one(document)
    query = query_identity if scalar_identity else {"_id": query_identity}
    with _spy_on_driver("find_one") as spy:
        assert await collection.find_one(query) == document
        assert await collection.find_one(query) == document
        assert await collection.find_one(query, collation=Collation("simple")) is None
        assert await collection.find_one(query, collation=Collation("simple")) is None
        assert (
            await collection.find_one(stored_identity, collation={"locale": "simple"})
            == document
        )
        assert (
            await collection.find_one(stored_identity, collation={"locale": "simple"})
            == document
        )
    assert spy.call_count == 3
    writer = independent_writer[cached_database_name][nonpersistent_collection_name]
    before = cache_manager.cache_core.capture_namespace_generation(
        NamespaceId(cached_database_name, nonpersistent_collection_name)
    ).generation
    await writer.update_one({"_id": stored_identity}, {"$set": {"rank": 2}})
    await _wait_until(
        lambda: (
            cache_manager.cache_core.capture_namespace_generation(
                NamespaceId(cached_database_name, nonpersistent_collection_name)
            ).generation
            > before
        )
    )
    assert await collection.find_one(query) == {"_id": stored_identity, "rank": 2}


@pytest.mark.parametrize(
    "operation",
    ["matching-write", "nonmatching-write", "negative-insert", "drop-recreate"],
    ids=["matching-write", "nonmatching-write", "negative-insert", "drop-recreate"],
)
async def test_generic_find_one_invalidates_for_namespace_changes(
    cache_manager: CacheManager[BsonDict],
    independent_writer: AsyncMongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    operation: str,
    faker: Faker,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = {"_id": faker.uuid4(), "group": faker.word(), "rank": 1}
    other = {"_id": faker.uuid4(), "group": faker.uuid4(), "rank": 2}
    await collection.raw.insert_many([document, other])
    query = {
        "group": document["group"],
        "rank": 2 if operation == "negative-insert" else 1,
    }
    expected = None if operation == "negative-insert" else document
    assert await collection.find_one(query) == expected
    assert await collection.find_one(query) == expected
    writer = independent_writer[cached_database_name][nonpersistent_collection_name]
    if operation == "matching-write":
        await writer.update_one({"_id": document["_id"]}, {"$set": {"rank": 2}})
        expected = None
    elif operation == "nonmatching-write":
        await writer.update_one({"_id": other["_id"]}, {"$set": {"rank": 3}})
    elif operation == "negative-insert":
        expected = {"_id": faker.uuid4(), "group": document["group"], "rank": 2}
        await writer.insert_one(expected)
    else:
        await writer.drop()
        expected = {**document, "fresh": True}
        await writer.insert_one(expected)
    await wait_for_stream_barrier_async(
        cache_manager.cache_core, independent_writer[cached_database_name]
    )
    with _spy_on_driver("find_one") as spy:
        assert await collection.find_one(query) == expected
        assert await collection.find_one(query) == expected
    assert spy.call_count == 1


@pytest.mark.parametrize(
    "options",
    [
        {"sort": [("rank", True)]},
        {"sort": "rank"},
        {"sort": [("rank", 0)]},
        {"sort": [("rank",)]},
        {"sort": [(1, 1)]},
        {"collation": {"locale": "simple", "strength": 2}},
        {"collation": {}},
        {"collation": 1},
        {"collation": {"locale": ""}},
        {"collation": {"locale": "en", "unsupported": True}},
        {"collation": {"locale": "en", "strength": 6}},
        {"collation": {"locale": "en", "caseFirst": "invalid"}},
        {"collation": {"locale": "en", "strength": "2"}},
        {"projection": [1]},
        {"projection": "rank"},
        {"projection": {"rank": 1, "group": 0}},
        {"unknown_option": True},
    ],
    ids=[
        "bool-sort",
        "string-sort",
        "zero-sort",
        "incomplete-sort-pair",
        "nonstring-sort-field",
        "simple-with-options",
        "missing-locale",
        "nonmapping-collation",
        "empty-locale",
        "unknown-collation-option",
        "out-of-range-strength",
        "invalid-case-first",
        "noninteger-strength",
        "nonstring-projection",
        "string-projection",
        "mixed-projection",
        "unknown-option",
    ],
)
async def test_find_one_invalid_options_preserve_driver_behavior_after_warming(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    options: dict[str, Any],
    faker: Faker,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = {"_id": faker.uuid4(), "rank": 1, "group": faker.word()}
    await collection.raw.insert_one(document)
    query = {"_id": document["_id"]}
    assert await collection.find_one(
        query, {"rank": 1}, sort=[("rank", 1)], collation={"locale": "simple"}
    )
    assert await collection.find_one(query) == document
    assert await collection.find_one(query, sort=[("rank", 1)]) == document
    assert await collection.find_one(query, collation={"locale": "simple"}) == document
    try:
        direct = await collection.raw.find_one(query, **options)
    except (TypeError, ValueError, OperationFailure) as error:
        with pytest.raises(type(error)):
            await collection.find_one(query, **options)
    else:
        assert await collection.find_one(query, **options) == direct


@pytest.mark.parametrize(
    "sort", [[("rank", 1)], [("priority", -1)]], ids=["rank", "priority"]
)
async def test_find_one_sort_metadata_projections_execute_directly(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    sort: list[tuple[str, int]],
    faker: Faker,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = {"_id": faker.uuid4(), "rank": 1, "priority": 2}
    await collection.raw.insert_one(document)
    projection = {"rank": 1, "sort_key": {"$meta": "sortKey"}}
    query = {"_id": document["_id"]}
    expected = await collection.raw.find_one(query, projection, sort=sort)
    assert await collection.find_one(query) == document
    with _spy_on_driver("find_one") as spy:
        assert await collection.find_one(query, projection, sort=sort) == expected
        assert await collection.find_one(query, projection, sort=sort) == expected
    assert spy.call_count == 2


@pytest.fixture
async def interrupted_generic_collection(
    cache_manager: CacheManager[BsonDict],
    independent_writer: AsyncMongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    faker: Faker,
) -> CachedCollection[BsonDict]:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = {"_id": faker.uuid4(), "rank": 1}
    await collection.raw.insert_one(document)
    await collection.count_documents({})
    namespace = NamespaceId(cached_database_name, nonpersistent_collection_name)
    original_find_one = AsyncCollection.find_one
    interrupted = False

    async def read_then_interrupt(
        raw: AsyncCollection[BsonDict], *args: object, **kwargs: object
    ) -> BsonDict | None:
        nonlocal interrupted
        document = await original_find_one(raw, *args, **kwargs)
        if not interrupted:
            assert document is not None
            interrupted = True
            if request.param == "write":
                before = cache_manager.cache_core.capture_namespace_generation(
                    namespace
                ).generation
                await independent_writer[cached_database_name][
                    nonpersistent_collection_name
                ].update_one({"_id": document["_id"]}, {"$set": {"rank": 2}})
                await _wait_until(
                    lambda: (
                        cache_manager.cache_core.capture_namespace_generation(
                            namespace
                        ).generation
                        > before
                    )
                )
            else:
                cache_manager.cache_core.set_database_available(
                    cached_database_name, available=False
                )
                cache_manager.cache_core.set_database_available(
                    cached_database_name, available=True
                )
        return document

    monkeypatch.setattr(AsyncCollection, "find_one", read_then_interrupt)
    return collection


@pytest.mark.parametrize(
    "interrupted_generic_collection",
    ["write", "recovery"],
    indirect=True,
    ids=["write-during-read", "recovery-during-read"],
)
async def test_generic_find_one_does_not_admit_a_read_spanning_invalidation(
    interrupted_generic_collection: CachedCollection[BsonDict],
) -> None:
    collection = interrupted_generic_collection
    query = {"rank": {"$gte": 1}}
    first = await collection.find_one(query)
    assert first is not None
    assert first["rank"] == 1
    before = collection.database.manager.cache_core.snapshot()
    second = await collection.find_one(query)
    assert collection.database.manager.cache_core.snapshot().misses > before.misses
    assert second == await collection.raw.find_one(query)
    before = collection.database.manager.cache_core.snapshot()
    assert await collection.find_one(query) == second
    assert collection.database.manager.cache_core.snapshot().hits == before.hits + 1


@pytest.mark.parametrize(
    "filter_query",
    [{1: "invalid"}, {"_id": {1: "invalid"}}, {"$and": []}],
    ids=["nonstring-key", "nonstring-embedded-id-key", "invalid-operator-argument"],
)
async def test_find_one_malformed_filters_preserve_driver_errors(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    filter_query: dict[Any, Any],
    faker: Faker,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = {"_id": faker.uuid4(), "rank": 1}
    await collection.raw.insert_one(document)
    assert await collection.find_one({}) == document
    with pytest.raises((InvalidDocument, OperationFailure)) as direct:
        await collection.raw.find_one(filter_query)
    with pytest.raises(type(direct.value)):
        await collection.find_one(filter_query)


@pytest.mark.parametrize(
    "query_kind",
    ["identity", "generic", "unique"],
    ids=["identity", "generic", "unique"],
)
async def test_find_one_explicit_collation_changes_matching_without_alias_leaks(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    query_kind: str,
    faker: Faker,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    stored_spelling = faker.lexify("????????").upper()
    document: BsonDict = {
        "_id": stored_spelling,
        "group": stored_spelling,
        "email": stored_spelling,
    }
    await collection.raw.create_index("email", unique=True)
    await collection.raw.insert_one(document)
    query_field = {"identity": "_id", "generic": "group", "unique": "email"}[query_kind]
    query = {query_field: stored_spelling.lower()}
    with _spy_on_driver("find_one") as spy:
        assert await collection.find_one(query) is None
        assert (
            await collection.find_one(query, collation={"locale": "en", "strength": 2})
            == document
        )
        assert await collection.find_one(query) is None
        assert (
            await collection.find_one(query, collation=Collation("en", strength=2))
            == document
        )
    assert spy.call_count == 2
    namespace = NamespaceId(cached_database_name, nonpersistent_collection_name)
    assert (
        cache_manager.cache_core.resolve_alias(
            namespace, ("email",), (stored_spelling.lower(),), None
        )
        is None
    )
