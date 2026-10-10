import re
import uuid
from operator import itemgetter
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from bson import Binary
from bson.binary import UuidRepresentation
from bson.code import Code
from bson.codec_options import CodecOptions
from bson.decimal128 import Decimal128
from bson.errors import InvalidDocument
from bson.int64 import Int64
from bson.raw_bson import RawBSONDocument
from pymongo import MongoClient, ReadPreference
from pymongo.collation import Collation
from pymongo.cursor import Cursor, CursorType
from pymongo.errors import ConnectionFailure, OperationFailure
from pymongo.read_concern import ReadConcern
from pymongo.synchronous.collection import Collection
from pymongo.synchronous.database import Database

from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import CacheCore, CacheCoreConfig
from client_query_cache._types import BsonDict, NonNegativeInt
from client_query_cache.synchronous.collection import CachedCollection
from client_query_cache.synchronous.manager import CacheManager
from client_query_cache.synchronous.streams import DatabaseStreamSupervisor
from tests.codec_helpers import DecodedPriceCase, decode_only_decimal_options
from tests.polling import wait_until as _wait_until
from tests.stream_helpers import wait_for_stream_barrier

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from faker import Faker

    from tests.conftest import CollectionName, DatabaseName, MongoDbUri

pytestmark = pytest.mark.integration


@pytest.fixture
def independent_writer(
    mongodb_uri: MongoDbUri,
) -> Iterator[MongoClient[BsonDict]]:
    with MongoClient[BsonDict](mongodb_uri) as client:
        yield client


@pytest.fixture
def client() -> MongoClient[BsonDict]:
    return MongoClient("mongodb://localhost:27017", connect=False)


@pytest.fixture
def decoded_price_case(
    mongodb_uri: MongoDbUri,
    independent_writer: MongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
) -> Iterator[DecodedPriceCase[CachedCollection[RawBSONDocument]]]:
    email = faker.email()
    price = faker.pydecimal(left_digits=3, right_digits=2, positive=True)
    document_id = Decimal128(str(faker.pydecimal(left_digits=3, right_digits=2)))
    options = decode_only_decimal_options()
    writer_collection = independent_writer[cached_database_name][
        nonpersistent_collection_name
    ]
    writer_collection.create_index("email", unique=True)
    writer_collection.insert_one(
        {"_id": document_id, "email": email, "price": Decimal128(str(price))}
    )
    with (
        MongoClient[RawBSONDocument](
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
def tight_budget_cache_manager(
    raw_mongo_client: MongoClient[BsonDict],
) -> Iterator[CacheManager[BsonDict]]:
    # Five padded fake documents exceed the 200-byte budget; each exceeds
    # the 50-byte entry limit, so neither individual nor combined reads cache.
    manager = CacheManager(
        raw_mongo_client,
        cache_config=CacheCoreConfig(shared_budget_bytes=200, max_entry_bytes=50),
    )
    yield manager
    manager.close()


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
    client: MongoClient[BsonDict],
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
    client: MongoClient[BsonDict], name: str
) -> None:
    collection = CacheManager(client).get_cached_collection(client["example"]["items"])

    with pytest.raises(AttributeError, match=repr(name)):
        getattr(collection, name)


def test_raw_collection_is_a_fully_functional_pymongo_escape_hatch(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., BsonDict],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()

    collection.raw.insert_one(document)
    index_name = collection.raw.create_index("email", unique=True)

    assert collection.raw.find_one({"_id": document["_id"]}) == document
    assert collection.raw.count_documents({}) == 1
    assert index_name in collection.raw.index_information()
    collection.raw.drop()
    assert nonpersistent_collection_name not in (
        cache_manager.client[cached_database_name].list_collection_names()
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


def test_created_raw_collection_is_readable_through_the_cached_view(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    raw_collection = cache_manager.client[cached_database_name].create_collection(
        nonpersistent_collection_name
    )

    collection = cache_manager.get_cached_collection(raw_collection)

    assert collection.raw is raw_collection
    assert list(collection.find({})) == []


def test_repeated_cached_views_share_entries_and_one_database_stream(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., BsonDict],
) -> None:
    raw_collection = cache_manager.client[cached_database_name][
        nonpersistent_collection_name
    ]
    document = make_fake_document()
    raw_collection.insert_one(document)

    with (
        patch.object(
            DatabaseStreamSupervisor,
            "start",
            autospec=True,
            side_effect=DatabaseStreamSupervisor.start,
        ) as start_spy,
        patch.object(
            Collection, "find_one", autospec=True, side_effect=Collection.find_one
        ) as find_one_spy,
    ):
        admitted = cache_manager.get_cached_collection(raw_collection).find_one(
            {"_id": document["_id"]}
        )
        hit = cache_manager.get_cached_collection(raw_collection).find_one(
            {"_id": document["_id"]}
        )

    assert admitted == hit == document
    assert find_one_spy.call_count == 1
    assert start_spy.call_count == 1


def test_composed_facade_and_direct_client_access_can_mix(
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

    cached_collection.raw.insert_one(cached_document)
    direct_collection.insert_one(direct_document)

    assert cached_collection.raw.find_one({"_id": cached_document["_id"]})
    assert direct_collection.find_one({"_id": direct_document["_id"]})


def test_manager_never_takes_ownership_of_the_caller_client_lifecycle(
    raw_mongo_client: MongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., BsonDict],
) -> None:
    client = raw_mongo_client
    manager = CacheManager(client)
    collection = manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one(make_fake_document())
    del manager, collection

    assert client.admin.command("ping")["ok"] == 1


@pytest.mark.parametrize(
    "query_kind", ["identity", "generic"], ids=["identity", "generic"]
)
def test_find_one_by_id_bypasses_cache_for_a_session_bound_read(
    query_kind: str,
    cache_manager: CacheManager[BsonDict],
    raw_mongo_client: MongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    make_fake_document: Callable[..., BsonDict],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()
    collection.raw.insert_one(document)

    query = {"_id": document["_id"]}
    if query_kind == "generic":
        query["$and"] = [{"_id": document["_id"]}]

    with (
        raw_mongo_client.start_session() as session,
        patch.object(
            Collection, "find_one", autospec=True, side_effect=Collection.find_one
        ) as spy,
    ):
        returned_document = collection.find_one(query, session=session)

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
def test_find_one_by_id_bypasses_cache_for_an_incompatible_read_profile(
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
    collection.raw.insert_one(document)

    query = {"_id": document["_id"]}
    if query_kind == "generic":
        query["$and"] = [{"_id": document["_id"]}]

    with patch.object(
        Collection, "find_one", autospec=True, side_effect=Collection.find_one
    ) as spy:
        returned_document = collection.find_one(query)

    assert returned_document == document
    spy.assert_called_once_with(
        raw_collection,
        query,
        None,
        sort=None,
        collation=None,
        session=None,
    )


def test_find_one_by_id_preserves_a_non_default_uuid_representation(
    make_uuid_collection: Callable[[NonNegativeInt], CachedCollection[BsonDict]],
) -> None:
    collection = make_uuid_collection(UuidRepresentation.STANDARD)
    identifier = uuid.uuid4()
    collection.raw.insert_one({"_id": "doc-1", "token": identifier})

    first = collection.find_one({"_id": "doc-1"})
    second = collection.find_one({"_id": "doc-1"})

    assert first == {"_id": "doc-1", "token": identifier}
    assert second == first


def test_find_one_by_a_uuid_id_invalidates_after_an_independent_write(
    independent_writer: MongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_uuid_collection: Callable[[NonNegativeInt], CachedCollection[BsonDict]],
) -> None:
    collection = make_uuid_collection(UuidRepresentation.STANDARD)
    identifier = uuid.uuid4()
    collection.raw.insert_one({"_id": identifier, "v": 1})
    assert collection.find_one({"_id": identifier}) == {"_id": identifier, "v": 1}

    binary_identifier = Binary.from_uuid(identifier, UuidRepresentation.STANDARD)
    independent_writer[cached_database_name][nonpersistent_collection_name].update_one(
        {"_id": binary_identifier}, {"$set": {"v": 2}}
    )

    _wait_until(
        lambda: (
            (document := collection.find_one({"_id": identifier})) is not None
            and document["v"] == 2
        )
    )


@pytest.mark.parametrize(
    "method", ["find", "find_one"], ids=["find", "generic-find-one"]
)
def test_reads_with_different_uuid_codecs_do_not_share_a_cache_entry(
    method: str,
    make_uuid_collection: Callable[[NonNegativeInt], CachedCollection[BsonDict]],
) -> None:
    standard_collection = make_uuid_collection(UuidRepresentation.STANDARD)
    legacy_collection = make_uuid_collection(UuidRepresentation.JAVA_LEGACY)
    identifier = uuid.uuid4()
    standard_collection.raw.insert_one({"_id": "doc-1", "u": identifier})

    first = (
        list(standard_collection.find({"u": identifier}))
        if method == "find"
        else standard_collection.find_one({"u": identifier})
    )
    second = (
        list(legacy_collection.find({"u": identifier}))
        if method == "find"
        else legacy_collection.find_one({"u": identifier})
    )

    assert first == (
        [{"_id": "doc-1", "u": identifier}]
        if method == "find"
        else {"_id": "doc-1", "u": identifier}
    )
    assert second == ([] if method == "find" else None)


def test_find_one_by_compound_ids_with_different_field_order_do_not_collide(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_many(
        [
            {"_id": {"a": 1, "b": 2}, "v": 1},
            {"_id": {"b": 2, "a": 1}, "v": 2},
        ]
    )

    first = collection.find_one({"_id": {"a": 1, "b": 2}})
    second = collection.find_one({"_id": {"b": 2, "a": 1}})

    assert first == {"_id": {"a": 1, "b": 2}, "v": 1}
    assert second == {"_id": {"b": 2, "a": 1}, "v": 2}


def test_find_one_by_a_compound_id_invalidates_after_an_independent_write(
    cache_manager: CacheManager[BsonDict],
    independent_writer: MongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    identity = {"a": 1, "b": 2}
    collection.raw.insert_one({"_id": identity, "v": 1})
    assert collection.find_one({"_id": identity}) == {"_id": identity, "v": 1}

    independent_writer[cached_database_name][nonpersistent_collection_name].update_one(
        {"_id": identity}, {"$set": {"v": 2}}
    )

    _wait_until(
        lambda: (
            (document := collection.find_one({"_id": identity})) is not None
            and document["v"] == 2
        )
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
def test_generic_find_one_caches_and_isolates_documents(
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
    collection.raw.insert_one(document)
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
    with patch.object(
        Collection, "find_one", autospec=True, side_effect=Collection.find_one
    ) as spy:
        first = collection.find_one(query)
        assert first == (document if matches else None)
        if first is not None:
            first["group"] = faker.uuid4()
        repeated_query = (
            None if query_kind == "empty" else {} if query_kind == "none" else query
        )
        second = collection.find_one(repeated_query)
    assert second == (document if matches else None)
    assert spy.call_count == 1


@pytest.mark.parametrize(
    "invoke",
    [
        pytest.param(
            lambda collection: list(collection.find({"$where": "true"})),
            id="find-unsafe-filter",
        ),
        pytest.param(
            lambda collection: collection.find_one({"$where": "true"}),
            id="find_one-unsafe-filter",
        ),
    ],
)
def test_facade_bypasses_are_recorded_in_cache_statistics(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    invoke: Callable[[CachedCollection[BsonDict]], object],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one({"_id": "a", "v": 1})

    before = cache_manager.cache_core.snapshot().bypasses
    invoke(collection)
    after = cache_manager.cache_core.snapshot().bypasses

    assert after == before + 1


def test_find_one_by_a_regex_id_uses_generic_caching(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one({"_id": "doc-1", "v": 1})

    with patch.object(
        Collection, "find_one", autospec=True, side_effect=Collection.find_one
    ) as spy:
        first = collection.find_one({"_id": re.compile(r"^doc-")})
        second = collection.find_one({"_id": re.compile(r"^doc-")})

    assert first == {"_id": "doc-1", "v": 1}
    assert second == {"_id": "doc-1", "v": 1}
    assert spy.call_count == 1


def test_find_one_with_extra_pymongo_options_bypasses_instead_of_raising(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., BsonDict],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()
    collection.raw.insert_one(document)

    with patch.object(
        Collection, "find_one", autospec=True, side_effect=Collection.find_one
    ) as spy:
        returned_document = collection.find_one({"_id": document["_id"]}, hint="_id_")

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


def test_find_one_by_id_projection_does_not_collide_with_full_document_read(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one({"_id": "doc-1", "a": 1, "b": 2})

    with patch.object(
        Collection, "find_one", autospec=True, side_effect=Collection.find_one
    ) as spy:
        full = collection.find_one({"_id": "doc-1"})
        projected = collection.find_one({"_id": "doc-1"}, {"a": 1})
        full_again = collection.find_one({"_id": "doc-1"})
        projected_again = collection.find_one({"_id": "doc-1"}, {"a": 1})

    assert full == {"_id": "doc-1", "a": 1, "b": 2}
    assert projected == {"_id": "doc-1", "a": 1}
    assert full_again == full
    assert projected_again == projected
    assert spy.call_count == 2


def test_unique_key_projection_with_decode_only_codec_strips_id(
    decoded_price_case: DecodedPriceCase[CachedCollection[RawBSONDocument]],
) -> None:
    document = decoded_price_case.collection.find_one(
        {"email": decoded_price_case.email}, {"_id": 0, "price": 1}
    )

    assert document == {"price": decoded_price_case.price}


@pytest.mark.parametrize(
    "read_document",
    [
        pytest.param(
            lambda collection: collection.find_one({"_id": "doc-1"}), id="find_one"
        ),
        pytest.param(lambda collection: next(iter(collection.find({}))), id="find"),
    ],
)
def test_cache_hit_is_isolated_from_caller_mutation(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    read_document: Callable[[CachedCollection[BsonDict]], BsonDict | None],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one({"_id": "doc-1", "tags": ["a", "b"]})

    first = read_document(collection)
    assert first is not None
    tags = first["tags"]
    assert isinstance(tags, list)
    tags.append("mutated")

    second = read_document(collection)

    assert second == {"_id": "doc-1", "tags": ["a", "b"]}


def test_find_one_by_id_invalidates_after_an_independent_write(
    cache_manager: CacheManager[BsonDict],
    independent_writer: MongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., BsonDict],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()
    collection.raw.insert_one(document)
    assert collection.find_one({"_id": document["_id"]}) == document

    independent_writer[cached_database_name][nonpersistent_collection_name].update_one(
        {"_id": document["_id"]}, {"$set": {"marker": "updated"}}
    )

    _wait_until(
        lambda: (
            (current := collection.find_one({"_id": document["_id"]})) is not None
            and "marker" in current
            and current["marker"] == "updated"
        )
    )


def test_find_one_against_a_view_bypasses_cache(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
) -> None:
    database = cache_manager[cached_database_name]
    database.raw[persistent_collection_name].insert_one({"_id": "doc-1", "v": 1})
    view_name = f"{persistent_collection_name}_view"
    database.raw.create_collection(
        view_name, viewOn=persistent_collection_name, pipeline=[]
    )
    view_collection = database[view_name]

    assert view_collection.find_one({"_id": "doc-1"}) == {"_id": "doc-1", "v": 1}

    with patch.object(
        Collection, "find_one", autospec=True, side_effect=Collection.find_one
    ) as spy:
        view_collection.find_one({"_id": "doc-1"})
        view_collection.find_one({"_id": "doc-1"})

    assert spy.call_count == 2


def test_collection_recreated_as_a_view_loses_eligibility(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
) -> None:
    database = cache_manager[cached_database_name]
    ordinary_name = f"{persistent_collection_name}_source"
    wrapped_name = f"{persistent_collection_name}_target"
    database.raw[ordinary_name].insert_one({"_id": "doc-1", "v": 1})
    database.raw[wrapped_name].insert_one({"_id": "doc-1", "v": "original"})
    collection = database[wrapped_name]

    assert collection.find_one({"_id": "doc-1"}) == {"_id": "doc-1", "v": "original"}

    database.raw.drop_collection(wrapped_name)
    database.raw.create_collection(wrapped_name, viewOn=ordinary_name, pipeline=[])

    _wait_until(
        lambda: collection.find_one({"_id": "doc-1"}) == {"_id": "doc-1", "v": 1}
    )

    with patch.object(
        Collection, "find_one", autospec=True, side_effect=Collection.find_one
    ) as spy:
        collection.find_one({"_id": "doc-1"})
        collection.find_one({"_id": "doc-1"})

    assert spy.call_count == 2


def test_namespace_wrapped_while_absent_and_created_as_a_view_is_detected(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
) -> None:
    database = cache_manager[cached_database_name]
    source_name = f"{persistent_collection_name}_source"
    absent_name = f"{persistent_collection_name}_absent"
    database.raw[source_name].insert_one({"_id": "doc-1", "v": 1})
    collection = database[absent_name]

    assert collection.find_one({"_id": "doc-1"}) is None

    database.raw.create_collection(absent_name, viewOn=source_name, pipeline=[])

    _wait_until(
        lambda: collection.find_one({"_id": "doc-1"}) == {"_id": "doc-1", "v": 1}
    )

    with patch.object(
        Collection, "find_one", autospec=True, side_effect=Collection.find_one
    ) as spy:
        collection.find_one({"_id": "doc-1"})
        collection.find_one({"_id": "doc-1"})

    assert spy.call_count == 2


@pytest.mark.parametrize(
    "probe_error",
    [
        pytest.param(OperationFailure("not authorized", code=13), id="unauthorized"),
        pytest.param(
            ConnectionFailure("no primary available"), id="connection_failure"
        ),
    ],
)
def test_find_one_bypasses_cache_when_view_inspection_fails(
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
    collection.raw.insert_one(document)

    with (
        caplog.at_level("WARNING", logger="client_query_cache.synchronous.collection"),
        patch.object(Database, "list_collections", side_effect=probe_error),
        patch.object(
            Collection, "find_one", autospec=True, side_effect=Collection.find_one
        ) as spy,
    ):
        first = collection.find_one({"_id": document["_id"]})
        second = collection.find_one({"_id": document["_id"]})

    assert first == document
    assert second == document
    assert spy.call_count == 2
    assert caplog.records
    assert all(record.levelname == "WARNING" for record in caplog.records)


@pytest.mark.parametrize(
    "probe_error",
    [
        pytest.param(OperationFailure("not authorized", code=13), id="unauthorized"),
        pytest.param(
            ConnectionFailure("no primary available"), id="connection_failure"
        ),
    ],
)
def test_view_inspection_failure_is_not_memoized_as_a_permanent_view(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., BsonDict],
    probe_error: Exception,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()
    collection.raw.insert_one(document)

    with patch.object(Database, "list_collections", side_effect=probe_error):
        collection.find_one({"_id": document["_id"]})

    with patch.object(
        Collection, "find_one", autospec=True, side_effect=Collection.find_one
    ) as spy:
        first = collection.find_one({"_id": document["_id"]})
        second = collection.find_one({"_id": document["_id"]})

    assert first == document
    assert second == document
    assert spy.call_count == 1


def test_find_one_bypasses_forced_options_while_the_stream_is_unavailable(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_many([{"_id": "a", "v": 1}, {"_id": "b", "v": 2}])
    collection.find_one({"_id": "a"})

    cache_manager.cache_core.set_database_available(
        cached_database_name, available=False
    )

    with patch.object(
        Collection, "find_one", autospec=True, side_effect=Collection.find_one
    ) as spy:
        returned_document = collection.find_one({"_id": "b"})

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
            lambda collection: list(collection.find({"v": 1})),
            [{"_id": "a", "v": 1, "email": "a@example.com"}],
            id="find",
        ),
        pytest.param(
            "aggregate",
            lambda collection: list(collection.aggregate([{"$match": {"v": 1}}])),
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
def test_reads_recheck_availability_before_forcing_read_options(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    patch_target: str,
    invoke: Callable[[CachedCollection[BsonDict]], object],
    expected: object,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.create_index("email", unique=True)
    collection.raw.insert_one({"_id": "a", "v": 1, "email": "a@example.com"})

    with (
        patch.object(CacheCore, "is_database_available", side_effect=[True, False]),
        patch.object(
            Cursor if patch_target == "find" else Collection,
            "_send_message"
            if patch_target == "find"
            else "_aggregate"
            if patch_target == "aggregate"
            else patch_target,
            autospec=True,
            side_effect=Cursor._send_message
            if patch_target == "find"
            else Collection._aggregate
            if patch_target == "aggregate"
            else getattr(Collection, patch_target),
        ) as spy,
    ):
        returned = invoke(collection)

    assert returned == expected
    assert (
        spy.call_args.args[0].collection
        if patch_target == "find"
        else spy.call_args.args[0]
    ) is collection.raw


def test_find_one_by_id_discards_admission_when_the_query_fails(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    make_fake_document: Callable[..., BsonDict],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = make_fake_document()
    collection.raw.insert_one(document)

    with (
        patch.object(
            Collection, "find_one", autospec=True, side_effect=RuntimeError("boom")
        ),
        pytest.raises(RuntimeError, match="boom"),
    ):
        collection.find_one({"_id": document["_id"]})

    assert collection.find_one({"_id": document["_id"]}) == document


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
            lambda collection: list(collection.find({}, sort=[("_id", 1)])),
            [{"_id": "a", "v": 1}, {"_id": "b", "v": 2}],
            id="find",
        ),
        pytest.param(
            "aggregate",
            lambda collection: list(collection.aggregate([{"$sort": {"_id": 1}}])),
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
            lambda collection: sorted(collection.distinct("v")),
            [1, 2],
            id="distinct",
        ),
    ],
)
def test_repeated_reads_are_served_from_cache(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    patch_target: str,
    invoke: Callable[[CachedCollection[BsonDict]], object],
    expected: object,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_many([{"_id": "a", "v": 1}, {"_id": "b", "v": 2}])

    with patch.object(
        Cursor if patch_target == "find" else Collection,
        "_send_message"
        if patch_target == "find"
        else "_aggregate"
        if patch_target == "aggregate"
        else patch_target,
        autospec=True,
        side_effect=Cursor._send_message
        if patch_target == "find"
        else Collection._aggregate
        if patch_target == "aggregate"
        else getattr(Collection, patch_target),
    ) as spy:
        first = invoke(collection)
        second = invoke(collection)

    assert first == expected
    assert second == expected
    assert spy.call_count == 1


@pytest.mark.parametrize(
    ("invoke", "settled"),
    [
        pytest.param(
            lambda collection: list(collection.find({})),
            lambda value: len(value) == 2,
            id="find",
        ),
        pytest.param(
            lambda collection: list(collection.aggregate([{"$match": {}}])),
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
def test_namespace_guarded_reads_invalidate_after_an_independent_write(
    cache_manager: CacheManager[BsonDict],
    independent_writer: MongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    invoke: Callable[[CachedCollection[BsonDict]], object],
    settled: Callable[[object], bool],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one({"_id": "a", "v": 1})
    invoke(collection)

    independent_writer[cached_database_name][nonpersistent_collection_name].insert_one(
        {"_id": "b", "v": 2}
    )

    _wait_until(lambda: settled(invoke(collection)))


def test_find_shapes_do_not_collide(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_many(
        [{"_id": "a", "v": 1, "extra": "x"}, {"_id": "b", "v": 2, "extra": "y"}]
    )

    with patch.object(
        Cursor, "_send_message", autospec=True, side_effect=Cursor._send_message
    ) as spy:
        full = list(collection.find({}))
        projected = list(collection.find({}, {"v": 1}))
        limited = list(collection.find({}, limit=1))
        list(collection.find({}))
        list(collection.find({}, {"v": 1}))
        list(collection.find({}, limit=1))

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
def test_find_filters_on_distinct_equivalent_looking_values_do_not_collide(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    first_value: object,
    second_value: object,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_many(
        [{"_id": "doc1", "x": first_value}, {"_id": "doc2", "x": second_value}]
    )

    first = list(collection.find({"x": first_value}))
    second = list(collection.find({"x": second_value}))

    assert first == [{"_id": "doc1", "x": first_value}]
    assert second == [{"_id": "doc2", "x": second_value}]


def test_find_one_bypasses_when_identity_normalization_yields_an_unhashable_value(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one({"_id": "a", "v": 1})

    with (
        patch(
            "client_query_cache.synchronous.collection.normalize_identity_for_cache_key",
            return_value={1, 2, 3},
        ),
        patch.object(
            Collection, "find_one", autospec=True, side_effect=Collection.find_one
        ) as spy,
    ):
        first = collection.find_one({"_id": "a"})
        second = collection.find_one({"_id": "a"})

    assert first == {"_id": "a", "v": 1}
    assert second == {"_id": "a", "v": 1}
    assert spy.call_count == 2


def test_find_one_with_a_nested_elem_match_projection_is_order_sensitive(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one(
        {
            "_id": "doc-1",
            "items": [
                {"sub": {"a": 1, "b": 2}, "tag": "first"},
                {"sub": {"b": 2, "a": 1}, "tag": "second"},
            ],
        }
    )

    first = collection.find_one(
        {"_id": "doc-1"}, {"items": {"$elemMatch": {"sub": {"a": 1, "b": 2}}}}
    )
    second = collection.find_one(
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


def test_aggregate_with_a_multi_field_sort_is_order_sensitive(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_many(
        [
            {"_id": "a", "x": 1, "y": 2},
            {"_id": "b", "x": 1, "y": 1},
            {"_id": "c", "x": 2, "y": 1},
        ]
    )

    by_x_then_y = list(collection.aggregate([{"$sort": {"x": 1, "y": 1}}]))
    by_y_then_x = list(collection.aggregate([{"$sort": {"y": 1, "x": 1}}]))

    assert [doc["_id"] for doc in by_x_then_y] == ["b", "a", "c"]
    assert [doc["_id"] for doc in by_y_then_x] == ["b", "c", "a"]


@pytest.mark.parametrize(
    ("other_literal", "other_type"),
    [
        pytest.param(1.0, "double", id="float"),
        pytest.param(Int64(1), "long", id="int64"),
    ],
)
def test_aggregate_with_equal_int_and_other_numeric_literals_do_not_collide(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    other_literal: object,
    other_type: str,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one({"_id": "a"})

    int_result = list(
        collection.aggregate([{"$project": {"t": {"$type": {"$literal": 1}}}}])
    )
    other_result = list(
        collection.aggregate(
            [{"$project": {"t": {"$type": {"$literal": other_literal}}}}]
        )
    )

    assert int_result == [{"_id": "a", "t": "int"}]
    assert other_result == [{"_id": "a", "t": other_type}]


def test_find_one_by_a_numeric_id_invalidates_regardless_of_int_or_float_spelling(
    cache_manager: CacheManager[BsonDict],
    independent_writer: MongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one({"_id": 1, "v": 1})
    assert collection.find_one({"_id": 1.0}) == {"_id": 1, "v": 1}

    independent_writer[cached_database_name][nonpersistent_collection_name].update_one(
        {"_id": 1}, {"$set": {"v": 2}}
    )

    _wait_until(
        lambda: (
            (document := collection.find_one({"_id": 1.0})) is not None
            and document["v"] == 2
        )
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({"cursor_type": CursorType.TAILABLE}, id="tailable"),
        pytest.param({"cursor_type": CursorType.TAILABLE_AWAIT}, id="tailable-await"),
        pytest.param({"cursor_type": CursorType.EXHAUST}, id="exhaust"),
        pytest.param({"allow_partial_results": True}, id="allow-partial-results"),
    ],
)
def test_find_preserves_native_cursor_shapes(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    kwargs: dict[str, Any],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]

    cursor = collection.find({}, **kwargs)
    assert isinstance(cursor, Cursor)
    cursor.close()
    assert cache_manager.snapshot().hits == 0


def test_aggregate_preserves_native_change_stream_cursor(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]

    cursor = collection.aggregate([{"$changeStream": {}}])
    cursor.close()
    assert cache_manager.snapshot().hits == 0
    assert cache_manager.snapshot().entry_count == 0


def test_aggregate_with_a_now_variable_executes_without_raising_but_is_not_cached(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one({"_id": "a", "start": "2020-01-01T00:00:00Z"})
    pipeline: list[BsonDict] = [{"$project": {"now": "$$NOW"}}]

    with patch.object(
        Collection, "_aggregate", autospec=True, side_effect=Collection._aggregate
    ) as spy:
        list(collection.aggregate(pipeline))
        list(collection.aggregate(pipeline))

    assert spy.call_count == 2


def test_find_with_an_oversize_result_is_returned_but_never_cached(
    tight_budget_cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = tight_budget_cache_manager[cached_database_name][
        nonpersistent_collection_name
    ]
    collection.raw.insert_many(
        [{"_id": f"doc-{i}", "padding": "x" * 100} for i in range(5)]
    )

    with patch.object(
        Cursor, "_send_message", autospec=True, side_effect=Cursor._send_message
    ) as spy:
        first = list(collection.find({}))
        second = list(collection.find({}))

    assert first == second
    assert len(first) == 5
    assert spy.call_count == 2


def test_find_with_a_plain_dict_collation_is_cached(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one({"_id": "a", "v": 1})

    with patch.object(
        Cursor, "_send_message", autospec=True, side_effect=Cursor._send_message
    ) as spy:
        first = list(collection.find({}, collation={"locale": "en"}))
        second = list(collection.find({}, collation={"locale": "en"}))

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
def test_count_documents_preserves_explicit_invalid_options(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    read_state: str,
    options: dict[str, Any],
    error_type: type[Exception],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one({"_id": "counted"})
    if read_state == "warm":
        assert collection.count_documents({}) == 1
        assert collection.count_documents({}) == 1
    elif read_state == "bypass":
        options = {**options, "comment": "count-option-bypass"}

    with pytest.raises(error_type) as native_error:
        collection.raw.count_documents({}, **options)
    with pytest.raises(error_type) as cached_error:
        collection.count_documents({}, **options)
    if isinstance(native_error.value, OperationFailure):
        assert isinstance(cached_error.value, OperationFailure)
        assert cached_error.value.code == native_error.value.code
    else:
        assert str(cached_error.value) == str(native_error.value)


@pytest.mark.parametrize("options", [{}, {"skip": 0}], ids=("omitted", "zero-skip"))
def test_count_documents_reuses_equivalent_skip_entries(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    options: dict[str, Any],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one({"_id": "counted"})
    other_options: dict[str, Any] = {} if options else {"skip": 0}
    with patch.object(
        Collection,
        "count_documents",
        autospec=True,
        side_effect=Collection.count_documents,
    ) as spy:
        assert collection.count_documents({}, **other_options) == 1
        assert collection.count_documents({}, **options) == 1
        assert collection.count_documents({}, **options) == 1
    assert spy.call_count == 1
    assert spy.call_args.kwargs == {"session": None, **other_options}


def test_count_documents_with_skip_limit_hint_and_collation_object_is_cached(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_many([{"_id": "a", "v": 1}, {"_id": "b", "v": 2}])
    kwargs: dict[str, Any] = {
        "skip": 1,
        "limit": 1,
        "hint": "_id_",
        "collation": Collation(locale="en"),
    }

    with patch.object(
        Collection,
        "count_documents",
        autospec=True,
        side_effect=Collection.count_documents,
    ) as spy:
        first = collection.count_documents({}, **kwargs)
        second = collection.count_documents({}, **kwargs)

    assert first == second == 1
    assert spy.call_count == 1


def test_estimated_document_count_bypasses_cache_for_extra_pymongo_options(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one({"_id": "a", "v": 1})

    with patch.object(
        Collection,
        "estimated_document_count",
        autospec=True,
        side_effect=Collection.estimated_document_count,
    ) as spy:
        collection.estimated_document_count(comment="audit")
        collection.estimated_document_count(comment="audit")

    assert spy.call_count == 2


@pytest.mark.parametrize(
    ("patch_target", "invoke"),
    [
        pytest.param(
            "find",
            lambda collection: list(collection.find({"$where": "this.v > 0"})),
            id="find-where",
        ),
        pytest.param(
            "find",
            lambda collection: list(collection.find({"$expr": {"$rand": {}}})),
            id="find-expr-rand",
        ),
        pytest.param(
            "find",
            lambda collection: list(
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
def test_unsafe_filters_are_never_cached(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    patch_target: str,
    invoke: Callable[[CachedCollection[BsonDict]], object],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one({"_id": "a", "v": 1})

    with patch.object(
        Cursor if patch_target == "find" else Collection,
        "_send_message"
        if patch_target == "find"
        else "_aggregate"
        if patch_target == "aggregate"
        else patch_target,
        autospec=True,
        side_effect=Cursor._send_message
        if patch_target == "find"
        else Collection._aggregate
        if patch_target == "aggregate"
        else getattr(Collection, patch_target),
    ) as spy:
        invoke(collection)
        invoke(collection)

    assert spy.call_count == 2


def test_find_with_a_meta_projection_is_never_cached(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.create_index([("text", "text")])
    collection.raw.insert_one({"_id": "a", "text": "hello world"})

    with patch.object(
        Cursor, "_send_message", autospec=True, side_effect=Cursor._send_message
    ) as spy:
        list(
            collection.find(
                {"$text": {"$search": "hello"}}, {"score": {"$meta": "textScore"}}
            )
        )
        list(
            collection.find(
                {"$text": {"$search": "hello"}}, {"score": {"$meta": "textScore"}}
            )
        )

    assert spy.call_count == 2


@pytest.mark.parametrize(
    ("patch_target", "invoke"),
    [
        pytest.param(
            "find_one",
            lambda collection: collection.find_one({"$text": {"$search": "hello"}}),
            id="find_one-text-search",
        ),
        pytest.param(
            "find",
            lambda collection: list(collection.find({"$text": {"$search": "hello"}})),
            id="find-text-search",
        ),
        pytest.param(
            "count_documents",
            lambda collection: collection.count_documents(
                {"$text": {"$search": "hello"}}
            ),
            id="count_documents-text-search",
        ),
        pytest.param(
            "distinct",
            lambda collection: collection.distinct(
                "text", {"$text": {"$search": "hello"}}
            ),
            id="distinct-text-search",
        ),
    ],
)
def test_text_search_filters_are_never_cached(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    patch_target: str,
    invoke: Callable[[CachedCollection[BsonDict]], object],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.create_index([("text", "text")])
    collection.raw.insert_one({"_id": "a", "text": "hello world"})

    with patch.object(
        Cursor if patch_target == "find" else Collection,
        "_send_message"
        if patch_target == "find"
        else "_aggregate"
        if patch_target == "aggregate"
        else patch_target,
        autospec=True,
        side_effect=Cursor._send_message
        if patch_target == "find"
        else Collection._aggregate
        if patch_target == "aggregate"
        else getattr(Collection, patch_target),
    ) as spy:
        invoke(collection)
        invoke(collection)

    assert spy.call_count == 2


@pytest.mark.parametrize(
    ("patch_target", "insert_doc", "invoke", "expected"),
    [
        pytest.param(
            "find",
            {"_id": "a", "script": Code("function() { return true; }")},
            lambda collection: list(
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
def test_reads_with_an_unhashable_value_bypass_instead_of_raising(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    patch_target: str,
    insert_doc: BsonDict,
    invoke: Callable[[CachedCollection[BsonDict]], object],
    expected: object,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.create_index("tag", unique=True)
    collection.raw.insert_one(insert_doc)

    with patch.object(
        Cursor if patch_target == "find" else Collection,
        "_send_message"
        if patch_target == "find"
        else "_aggregate"
        if patch_target == "aggregate"
        else patch_target,
        autospec=True,
        side_effect=Cursor._send_message
        if patch_target == "find"
        else Collection._aggregate
        if patch_target == "aggregate"
        else getattr(Collection, patch_target),
    ) as spy:
        first = invoke(collection)
        second = invoke(collection)

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
def test_aggregate_with_an_unsafe_pipeline_is_never_cached(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    pipeline: list[BsonDict],
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one({"_id": "a", "v": 1})

    with patch.object(
        Collection, "_aggregate", autospec=True, side_effect=Collection._aggregate
    ) as spy:
        list(collection.aggregate(pipeline))
        list(collection.aggregate(pipeline))

    assert spy.call_count == 2


def test_aggregate_with_an_out_stage_still_executes_its_write_but_is_not_cached(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    persistent_collection_name: CollectionName,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.insert_one({"_id": "a", "v": 1})
    pipeline: list[BsonDict] = [{"$out": persistent_collection_name}]

    with patch.object(
        Collection, "_aggregate", autospec=True, side_effect=Collection._aggregate
    ) as spy:
        list(collection.aggregate(pipeline))
        list(collection.aggregate(pipeline))

    assert spy.call_count == 2
    target = cache_manager[cached_database_name][persistent_collection_name]
    assert target.raw.find_one({"_id": "a"}) == {"_id": "a", "v": 1}


@pytest.mark.parametrize(
    "filter_query",
    [{"rank": {"$gte": 1}}, {"_id": "first"}, {"email": "first@example.com"}],
    ids=["generic", "identity", "unique"],
)
def test_find_one_sort_and_projection_shapes_do_not_collide(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    filter_query: BsonDict,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    collection.raw.create_index("email", unique=True)
    first_document = {"_id": "first", "rank": 1, "email": "first@example.com"}
    last_document = {"_id": "last", "rank": 2, "email": "last@example.com"}
    collection.raw.insert_many([first_document, last_document])
    with patch.object(
        Collection, "find_one", autospec=True, side_effect=Collection.find_one
    ) as spy:
        ascending = collection.find_one(filter_query, sort=[("rank", 1)])
        descending = collection.find_one(filter_query, sort=[("rank", -1)])
        projected = collection.find_one(
            filter_query, {"rank": 1, "_id": 0}, sort=[("rank", -1)]
        )
        assert collection.find_one(filter_query, sort=[("rank", 1)]) == ascending
        assert collection.find_one(filter_query, sort=[("rank", -1)]) == descending
        assert (
            collection.find_one(
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
def test_find_one_inherited_collation_uses_namespace_invalidation(
    cache_manager: CacheManager[BsonDict],
    independent_writer: MongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    scalar_identity: bool,
    faker: Faker,
) -> None:
    database = cache_manager[cached_database_name]
    database.raw.create_collection(
        nonpersistent_collection_name, collation={"locale": "en", "strength": 2}
    )
    collection = database[nonpersistent_collection_name]
    stored_identity = faker.lexify("????????").upper()
    query_identity = stored_identity.lower()
    document = {"_id": stored_identity, "rank": 1}
    collection.raw.insert_one(document)
    query = query_identity if scalar_identity else {"_id": query_identity}
    with patch.object(
        Collection, "find_one", autospec=True, side_effect=Collection.find_one
    ) as spy:
        assert collection.find_one(query) == document
        assert collection.find_one(query) == document
        assert collection.find_one(query, collation=Collation("simple")) is None
        assert collection.find_one(query, collation=Collation("simple")) is None
        assert (
            collection.find_one(stored_identity, collation={"locale": "simple"})
            == document
        )
        assert (
            collection.find_one(stored_identity, collation={"locale": "simple"})
            == document
        )
    assert spy.call_count == 3
    writer = independent_writer[cached_database_name][nonpersistent_collection_name]
    before = cache_manager.cache_core.capture_namespace_generation(
        NamespaceId(cached_database_name, nonpersistent_collection_name)
    ).generation
    writer.update_one({"_id": stored_identity}, {"$set": {"rank": 2}})
    _wait_until(
        lambda: (
            cache_manager.cache_core.capture_namespace_generation(
                NamespaceId(cached_database_name, nonpersistent_collection_name)
            ).generation
            > before
        )
    )
    assert collection.find_one(query) == {"_id": stored_identity, "rank": 2}


@pytest.mark.parametrize(
    "operation",
    ["matching-write", "nonmatching-write", "negative-insert", "drop-recreate"],
    ids=["matching-write", "nonmatching-write", "negative-insert", "drop-recreate"],
)
def test_generic_find_one_invalidates_for_namespace_changes(
    cache_manager: CacheManager[BsonDict],
    independent_writer: MongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    operation: str,
    faker: Faker,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = {"_id": faker.uuid4(), "group": faker.word(), "rank": 1}
    other = {"_id": faker.uuid4(), "group": faker.uuid4(), "rank": 2}
    collection.raw.insert_many([document, other])
    query = {
        "group": document["group"],
        "rank": 2 if operation == "negative-insert" else 1,
    }
    expected = None if operation == "negative-insert" else document
    assert collection.find_one(query) == expected
    assert collection.find_one(query) == expected
    writer = independent_writer[cached_database_name][nonpersistent_collection_name]
    if operation == "matching-write":
        writer.update_one({"_id": document["_id"]}, {"$set": {"rank": 2}})
        expected = None
    elif operation == "nonmatching-write":
        writer.update_one({"_id": other["_id"]}, {"$set": {"rank": 3}})
    elif operation == "negative-insert":
        expected = {"_id": faker.uuid4(), "group": document["group"], "rank": 2}
        writer.insert_one(expected)
    else:
        writer.drop()
        expected = {**document, "fresh": True}
        writer.insert_one(expected)
    wait_for_stream_barrier(
        cache_manager.cache_core, independent_writer[cached_database_name]
    )
    with patch.object(
        Collection, "find_one", autospec=True, side_effect=Collection.find_one
    ) as spy:
        assert collection.find_one(query) == expected
        assert collection.find_one(query) == expected
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
def test_find_one_invalid_options_preserve_driver_behavior_after_warming(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    options: dict[str, Any],
    faker: Faker,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = {"_id": faker.uuid4(), "rank": 1, "group": faker.word()}
    collection.raw.insert_one(document)
    query = {"_id": document["_id"]}
    assert collection.find_one(
        query, {"rank": 1}, sort=[("rank", 1)], collation={"locale": "simple"}
    )
    assert collection.find_one(query) == document
    assert collection.find_one(query, sort=[("rank", 1)]) == document
    assert collection.find_one(query, collation={"locale": "simple"}) == document
    try:
        direct = collection.raw.find_one(query, **options)
    except (TypeError, ValueError, OperationFailure) as error:
        with pytest.raises(type(error)):
            collection.find_one(query, **options)
    else:
        assert collection.find_one(query, **options) == direct


@pytest.mark.parametrize(
    "sort", [[("rank", 1)], [("priority", -1)]], ids=["rank", "priority"]
)
def test_find_one_sort_metadata_projections_execute_directly(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    sort: list[tuple[str, int]],
    faker: Faker,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = {"_id": faker.uuid4(), "rank": 1, "priority": 2}
    collection.raw.insert_one(document)
    projection = {"rank": 1, "sort_key": {"$meta": "sortKey"}}
    query = {"_id": document["_id"]}
    expected = collection.raw.find_one(query, projection, sort=sort)
    assert collection.find_one(query) == document
    with patch.object(
        Collection, "find_one", autospec=True, side_effect=Collection.find_one
    ) as spy:
        assert collection.find_one(query, projection, sort=sort) == expected
        assert collection.find_one(query, projection, sort=sort) == expected
    assert spy.call_count == 2


@pytest.fixture
def interrupted_generic_collection(
    cache_manager: CacheManager[BsonDict],
    independent_writer: MongoClient[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    faker: Faker,
) -> CachedCollection[BsonDict]:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = {"_id": faker.uuid4(), "rank": 1}
    collection.raw.insert_one(document)
    collection.count_documents({})
    namespace = NamespaceId(cached_database_name, nonpersistent_collection_name)
    original_find_one = Collection.find_one
    interrupted = False

    def read_then_interrupt(
        raw: Collection[BsonDict], *args: object, **kwargs: object
    ) -> BsonDict | None:
        nonlocal interrupted
        document = original_find_one(raw, *args, **kwargs)
        if not interrupted:
            assert document is not None
            interrupted = True
            if request.param == "write":
                before = cache_manager.cache_core.capture_namespace_generation(
                    namespace
                ).generation
                independent_writer[cached_database_name][
                    nonpersistent_collection_name
                ].update_one({"_id": document["_id"]}, {"$set": {"rank": 2}})
                _wait_until(
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

    monkeypatch.setattr(Collection, "find_one", read_then_interrupt)
    return collection


@pytest.mark.parametrize(
    "interrupted_generic_collection",
    ["write", "recovery"],
    indirect=True,
    ids=["write-during-read", "recovery-during-read"],
)
def test_generic_find_one_does_not_admit_a_read_spanning_invalidation(
    interrupted_generic_collection: CachedCollection[BsonDict],
) -> None:
    collection = interrupted_generic_collection
    query = {"rank": {"$gte": 1}}
    first = collection.find_one(query)
    assert first is not None
    assert first["rank"] == 1
    before = collection.database.manager.cache_core.snapshot()
    second = collection.find_one(query)
    assert collection.database.manager.cache_core.snapshot().misses > before.misses
    assert second == collection.raw.find_one(query)
    before = collection.database.manager.cache_core.snapshot()
    assert collection.find_one(query) == second
    assert collection.database.manager.cache_core.snapshot().hits == before.hits + 1


@pytest.mark.parametrize(
    "filter_query",
    [{1: "invalid"}, {"_id": {1: "invalid"}}, {"$and": []}],
    ids=["nonstring-key", "nonstring-embedded-id-key", "invalid-operator-argument"],
)
def test_find_one_malformed_filters_preserve_driver_errors(
    cache_manager: CacheManager[BsonDict],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    filter_query: dict[Any, Any],
    faker: Faker,
) -> None:
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = {"_id": faker.uuid4(), "rank": 1}
    collection.raw.insert_one(document)
    assert collection.find_one({}) == document
    with pytest.raises((InvalidDocument, OperationFailure)) as direct:
        collection.raw.find_one(filter_query)
    with pytest.raises(type(direct.value)):
        collection.find_one(filter_query)


@pytest.mark.parametrize(
    "query_kind",
    ["identity", "generic", "unique"],
    ids=["identity", "generic", "unique"],
)
def test_find_one_explicit_collation_changes_matching_without_alias_leaks(
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
    collection.raw.create_index("email", unique=True)
    collection.raw.insert_one(document)
    query_field = {"identity": "_id", "generic": "group", "unique": "email"}[query_kind]
    query = {query_field: stored_spelling.lower()}
    with patch.object(
        Collection, "find_one", autospec=True, side_effect=Collection.find_one
    ) as spy:
        assert collection.find_one(query) is None
        assert (
            collection.find_one(query, collation={"locale": "en", "strength": 2})
            == document
        )
        assert collection.find_one(query) is None
        assert (
            collection.find_one(query, collation=Collation("en", strength=2))
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
