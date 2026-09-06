import logging
import uuid
from collections.abc import Callable, Iterable, Iterator
from time import monotonic, sleep
from typing import Any, TypedDict, cast

import pytest
from faker import Faker
from pymongo.cursor_shared import _Sort
from pymongo.synchronous.collection import Collection

from mongo_client_cache._types import JsonDict
from mongo_client_cache.synchronous.collection import CachedCollection
from mongo_client_cache.synchronous.mongo_client import CachedMongoClient

fake = Faker()
logger = logging.getLogger(__name__)
pytestmark = pytest.mark.integration


@pytest.fixture
def document_count(faker: Faker) -> int:
    return faker.pyint(min_value=1, max_value=42)


@pytest.fixture(autouse=True)
def fill_collection(
    cached_collection: CachedCollection,
    make_fake_document: Callable[..., dict[str, Any]],
    document_count: int,
) -> Iterator[None]:
    logger.debug(
        "[SETUP] Filling %s with %s documents.", cached_collection.name, document_count
    )
    cached_collection.insert_many(make_fake_document() for _ in range(document_count))
    logger.debug(
        "[SETUP] Filled %s with %s documents.", cached_collection.name, document_count
    )
    yield
    logger.debug("[TEARDOWN] Deleteding all documents in %s", cached_collection.name)
    cached_collection.delete_many({})
    logger.debug("[TEARDOWN] Deleteded all documents in %s", cached_collection.name)


@pytest.fixture
def cached_collection(
    cached_mongo_client: CachedMongoClient,
    cached_database_name: str,
    nonpersistent_collection_name: str,
) -> CachedCollection:
    return cast(
        "CachedCollection",
        cached_mongo_client[cached_database_name][nonpersistent_collection_name],
    )


class FindOneCommandKwargs(TypedDict):
    filter: dict[str, Any] | None
    projection: dict[str, Any] | Iterable[str] | None


@pytest.mark.parametrize(
    ("kwargs", "should_find_document"),
    [
        ({"filter": None}, True),
        ({"filter": {"_id": str(uuid.uuid4())}}, False),
    ],
    ids=["existing", "missing"],
)
def test_find_one(
    cached_collection: CachedCollection,
    faker: Faker,
    kwargs: FindOneCommandKwargs,
    should_find_document: bool,
) -> None:
    for _ in range(faker.pyint(min_value=1, max_value=5)):
        found_document = cached_collection.find_one(**kwargs)
        if should_find_document:
            assert found_document is not None
        else:
            assert found_document is None


class FindCommandKwargs(TypedDict):
    filter: dict[str, Any] | None
    projection: dict[str, Any] | Iterable[str] | None
    limit: int
    skip: int
    sort: _Sort | None


@pytest.mark.parametrize(
    ("kwargs", "expected_count"),
    [
        ({"filter": None}, lambda all_documents: all_documents),
    ],
)
def test_find(
    cached_collection: CachedCollection,
    document_count: int,
    faker: Faker,
    kwargs: FindCommandKwargs,
    expected_count: Callable[[int], int],
) -> None:
    for _ in range(faker.pyint(min_value=1, max_value=5)):
        assert len(list(cached_collection.find(**kwargs))) == expected_count(
            document_count
        )

    for _ in range(faker.pyint(min_value=1, max_value=5)):
        assert len(cached_collection.find(**kwargs).to_list()) == expected_count(
            document_count
        )

    for _ in range(faker.pyint(min_value=1, max_value=5)):
        cursor = cached_collection.find(**kwargs)
        assert isinstance(cursor.next(), dict)
        cursor.close()


class CountDocumentsKwargs(TypedDict):
    limit: int
    skip: int


@pytest.mark.parametrize(
    ("document_filter", "kwargs", "expected_count"),
    [
        ({}, {}, None),
        ({fake.pystr(): fake.pystr()}, {}, 0),
        ({}, {"limit": 1, "skip": 1}, 1),
    ],
)
def test_count_documents(  # noqa: PLR0913, PLR0917
    cached_collection: CachedCollection,
    make_fake_document: Callable[..., dict[str, Any]],
    document_count: int,
    faker: Faker,
    document_filter: JsonDict,
    kwargs: CountDocumentsKwargs,
    expected_count: int | None,
) -> None:
    if "skip" in kwargs and document_count == 1:
        kwargs["skip"] = 0

    if expected_count is None:
        expected_count = document_count
    for _ in range(faker.pyint(min_value=1, max_value=5)):
        assert (
            cached_collection.count_documents(document_filter, **kwargs)
            == expected_count
        )

    cached_collection.insert_one(doc := make_fake_document())
    for _ in range(faker.pyint(min_value=1, max_value=5)):
        assert cached_collection.count_documents({}) == document_count + 1

    cached_collection.delete_one({"_id": doc["_id"]})
    for _ in range(faker.pyint(min_value=1, max_value=5)):
        assert (
            cached_collection.count_documents(document_filter, **kwargs)
            == expected_count
        )


def test_estimated_document_count(
    cached_collection: CachedCollection,
    make_fake_document: Callable[..., dict[str, Any]],
    document_count: int,
    faker: Faker,
) -> None:
    for _ in range(faker.pyint(min_value=1, max_value=5)):
        assert cached_collection.estimated_document_count() == document_count

    cached_collection.insert_one(doc := make_fake_document())
    for _ in range(faker.pyint(min_value=1, max_value=5)):
        assert cached_collection.estimated_document_count() == document_count + 1

    cached_collection.delete_one({"_id": doc["_id"]})
    for _ in range(faker.pyint(min_value=1, max_value=5)):
        assert cached_collection.estimated_document_count() == document_count


def test_independent_raw_write_updates_cached_count(
    cached_collection: CachedCollection,
    raw_collection: Collection,
    make_fake_document: Callable[..., dict[str, Any]],
    document_count: int,
) -> None:
    assert cached_collection.count_documents({}) == document_count
    raw_collection.insert_one(make_fake_document())

    deadline = monotonic() + 5
    while monotonic() < deadline:
        if cached_collection.count_documents({}) == document_count + 1:
            return
        sleep(0.01)

    pytest.fail("The cache did not observe an independent raw write within 5 seconds.")
