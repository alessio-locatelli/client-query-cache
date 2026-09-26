from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from bson.decimal128 import Decimal128
from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import ConnectionFailure, OperationFailure

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import codec_fingerprint
from client_query_cache._core.keys import (
    IdentityCacheKey,
    NamespaceId,
    canonical_alias_key,
)
from client_query_cache._core.manager import CacheCore, CacheCoreConfig
from client_query_cache._core.order_sensitive_keys import (
    order_sensitive_discriminator_key,
)
from client_query_cache.asynchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine, Iterator

    from faker import Faker

    from client_query_cache.asynchronous.collection import CachedCollection
    from tests.conftest import CollectionName, DatabaseName, MongoDbUri

pytestmark = pytest.mark.integration


def _available_once_then_unavailable() -> Iterator[bool]:
    yield True
    while True:
        yield False


@pytest.fixture
async def independent_writer(
    mongodb_uri: MongoDbUri,
) -> AsyncIterator[AsyncMongoClient[dict[str, Any]]]:
    async with AsyncMongoClient[dict[str, Any]](mongodb_uri) as client:
        yield client


@pytest.fixture
async def tight_budget_cache_manager(
    raw_mongo_client: AsyncMongoClient[dict[str, Any]],
) -> AsyncIterator[CacheManager[dict[str, Any]]]:
    manager = CacheManager(
        raw_mongo_client,
        cache_config=CacheCoreConfig(shared_budget_bytes=800, max_entry_bytes=200),
    )
    yield manager
    await manager.close()


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


@pytest.mark.parametrize(
    "seed_document",
    [
        pytest.param(
            True,
            id="match",
        ),
        pytest.param(False, id="negative-result"),
    ],
)
async def test_unique_key_read_is_cached_after_the_first_lookup(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    seed_document: bool,
    faker: Faker,
) -> None:
    email = faker.email()
    document = {"_id": faker.uuid4(), "email": email, "name": faker.first_name()}
    expected = document if seed_document else None
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index("email", unique=True)
    if seed_document:
        await collection.raw.insert_one(document)

    with patch.object(
        AsyncCollection, "find_one", autospec=True, side_effect=AsyncCollection.find_one
    ) as spy:
        first = await collection.find_one({"email": email})
        second = await collection.find_one({"email": email})

    assert first == expected
    assert second == expected
    assert spy.call_count == 1


@pytest.mark.parametrize(
    "create_excluded_index",
    [
        pytest.param(
            lambda raw: raw.create_index(
                "email",
                unique=True,
                partialFilterExpression={"email": {"$exists": True}},
            ),
            id="partial",
        ),
        pytest.param(
            lambda raw: raw.create_index("email", unique=True, sparse=True),
            id="sparse",
        ),
    ],
)
async def test_partial_or_sparse_unique_indexes_are_not_used_as_a_unique_key(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    create_excluded_index: Callable[
        [AsyncCollection[dict[str, Any]]], Coroutine[Any, Any, object]
    ],
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    email = faker.email()
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await create_excluded_index(collection.raw)
    document = {"_id": document_id, "email": email, "name": faker.first_name()}
    await collection.raw.insert_one(document)

    with patch.object(
        AsyncCollection, "find_one", autospec=True, side_effect=AsyncCollection.find_one
    ) as spy:
        first = await collection.find_one({"email": email})
        second = await collection.find_one({"email": email})

    assert first == document
    assert second == document
    assert spy.call_count == 2


async def test_a_read_collation_not_matching_the_index_is_not_used(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    email = faker.email()
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index(
        "email", unique=True, collation={"locale": "en", "strength": 2}
    )
    document = {"_id": document_id, "email": email, "name": faker.first_name()}
    await collection.raw.insert_one(document)

    with patch.object(
        AsyncCollection, "find_one", autospec=True, side_effect=AsyncCollection.find_one
    ) as spy:
        first = await collection.find_one({"email": email})
        second = await collection.find_one({"email": email})

    assert first == document
    assert second == document
    assert spy.call_count == 2


async def test_a_unique_index_inheriting_the_collections_default_collation_is_used(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    persistent_collection_name: CollectionName,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    email = faker.email()
    database = cache_manager[cached_database_name]
    await database.raw.create_collection(
        persistent_collection_name, collation={"locale": "en", "strength": 2}
    )
    collection = database[persistent_collection_name]
    await collection.raw.create_index("email", unique=True)
    document = {"_id": document_id, "email": email, "name": faker.first_name()}
    await collection.raw.insert_one(document)

    with patch.object(
        AsyncCollection, "find_one", autospec=True, side_effect=AsyncCollection.find_one
    ) as spy:
        first = await collection.find_one({"email": email})
        second = await collection.find_one({"email": email})

    assert first == document
    assert second == document
    assert spy.call_count == 1


async def test_discovery_is_shared_across_handles_from_the_same_manager(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    other_document_id = faker.uuid4()
    email = faker.unique.email()
    other_email = faker.unique.email()
    first_handle = cache_manager[cached_database_name][nonpersistent_collection_name]
    await first_handle.raw.create_index("email", unique=True)
    await first_handle.raw.insert_many(
        [
            {"_id": document_id, "email": email},
            {"_id": other_document_id, "email": other_email},
        ]
    )
    second_handle = cache_manager[cached_database_name][nonpersistent_collection_name]

    with patch.object(
        AsyncCollection,
        "list_indexes",
        autospec=True,
        side_effect=AsyncCollection.list_indexes,
    ) as spy:
        await first_handle.find_one({"email": email})
        await second_handle.find_one({"email": other_email})

    assert spy.call_count == 1


async def test_an_index_created_on_a_live_collection_is_detected_and_used(
    cache_manager: CacheManager[dict[str, Any]],
    independent_writer: AsyncMongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    email = faker.email()
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    document = {"_id": document_id, "email": email, "name": faker.first_name()}
    await collection.raw.insert_one(document)

    with patch.object(
        AsyncCollection, "find_one", autospec=True, side_effect=AsyncCollection.find_one
    ) as spy:
        await collection.find_one({"email": email})
        await collection.find_one({"email": email})
    assert spy.call_count == 2

    await independent_writer[cached_database_name][
        nonpersistent_collection_name
    ].create_index("email", unique=True)

    async def _round_trips_for_two_reads() -> int:
        with patch.object(
            AsyncCollection,
            "find_one",
            autospec=True,
            side_effect=AsyncCollection.find_one,
        ) as spy:
            await collection.find_one({"email": email})
            await collection.find_one({"email": email})
        return spy.call_count

    async def _is_settling() -> bool:
        return (await _round_trips_for_two_reads()) <= 1

    await _wait_until(_is_settling)
    assert await _round_trips_for_two_reads() == 0

    await independent_writer[cached_database_name][
        nonpersistent_collection_name
    ].drop_index("email_1")

    async def _is_uncached_again() -> bool:
        return (await _round_trips_for_two_reads()) == 2

    await _wait_until(_is_uncached_again)


async def test_an_inclusion_projection_excluding_id_resolves_without_leaking_id(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    email = faker.email()
    name = faker.first_name()
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index("email", unique=True)
    await collection.raw.insert_one({"_id": document_id, "email": email, "name": name})

    with patch.object(
        AsyncCollection, "find_one", autospec=True, side_effect=AsyncCollection.find_one
    ) as spy:
        first = await collection.find_one({"email": email}, {"_id": 0, "name": 1})
        second = await collection.find_one({"email": email}, {"_id": 0, "name": 1})

    assert first == {"name": name}
    assert second == {"name": name}
    assert spy.call_count == 1


async def test_an_exclusion_projection_excluding_id_avoids_an_invalid_projection(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    email = faker.email()
    name = faker.first_name()
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index("email", unique=True)
    await collection.raw.insert_one(
        {"_id": document_id, "email": email, "secret": "s", "name": name}
    )

    with patch.object(
        AsyncCollection, "find_one", autospec=True, side_effect=AsyncCollection.find_one
    ) as spy:
        first = await collection.find_one({"email": email}, {"_id": 0, "secret": 0})
        second = await collection.find_one({"email": email}, {"_id": 0, "secret": 0})

    expected = {"email": email, "name": name}
    assert first == expected
    assert second == expected
    assert spy.call_count == 1


async def test_an_independent_write_invalidates_a_resolved_unique_key_read(
    cache_manager: CacheManager[dict[str, Any]],
    independent_writer: AsyncMongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    email = faker.email()
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index("email", unique=True)
    await collection.raw.insert_one({"_id": document_id, "email": email, "v": 1})
    first = await collection.find_one({"email": email})
    assert (first or {}).get("v") == 1

    await independent_writer[cached_database_name][
        nonpersistent_collection_name
    ].update_one({"_id": document_id}, {"$set": {"v": 2}})

    async def _updated() -> bool:
        current = await collection.find_one({"email": email})
        return (current or {}).get("v") == 2

    await _wait_until(_updated)


async def test_an_independent_write_invalidates_an_unresolved_negative_unique_key_read(
    cache_manager: CacheManager[dict[str, Any]],
    independent_writer: AsyncMongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    email = faker.email()
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index("email", unique=True)
    assert await collection.find_one({"email": email}) is None

    await independent_writer[cached_database_name][
        nonpersistent_collection_name
    ].insert_one({"_id": document_id, "email": email, "v": 1})

    async def _appeared() -> bool:
        return (await collection.find_one({"email": email})) is not None

    await _wait_until(_appeared)


async def test_a_key_field_change_is_not_masked_by_a_stale_resolved_identity(
    cache_manager: CacheManager[dict[str, Any]],
    independent_writer: AsyncMongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    email = faker.unique.email()
    other_email = faker.unique.email()
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index("email", unique=True)
    await collection.raw.insert_one({"_id": document_id, "email": email, "v": 1})
    assert await collection.find_one({"email": email}) == {
        "_id": document_id,
        "email": email,
        "v": 1,
    }

    await independent_writer[cached_database_name][
        nonpersistent_collection_name
    ].update_one({"_id": document_id}, {"$set": {"email": other_email}})

    async def _old_email_no_longer_matches() -> bool:
        return (await collection.find_one({"email": email})) is None

    await _wait_until(_old_email_no_longer_matches)
    assert await collection.find_one({"email": other_email}) == {
        "_id": document_id,
        "email": other_email,
        "v": 1,
    }


async def test_a_drop_and_recreate_reusing_the_same_id_does_not_leak_the_old_document(
    cache_manager: CacheManager[dict[str, Any]],
    independent_writer: AsyncMongoClient[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    email = faker.email()
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index("email", unique=True)
    await collection.raw.insert_one({"_id": document_id, "email": email, "v": "old"})
    first = await collection.find_one({"email": email})
    assert (first or {}).get("v") == "old"

    await independent_writer[cached_database_name].drop_collection(
        nonpersistent_collection_name
    )
    await independent_writer[cached_database_name][
        nonpersistent_collection_name
    ].insert_one({"_id": document_id, "email": email, "v": "new"})

    async def _recreated_document_visible() -> bool:
        current = await collection.find_one({"email": email})
        return (current or {}).get("v") == "new"

    await _wait_until(_recreated_document_visible)


async def _evict_identity_entry_via_filler_pressure(
    cache_manager: CacheManager[dict[str, Any]],
    collection: CachedCollection[dict[str, Any]],
    namespace: NamespaceId,
    identity_key: IdentityCacheKey,
) -> None:
    cache = cache_manager.cache_core
    lru = cache._lru
    filler_count = 60
    await collection.raw.insert_many(
        [
            {"_id": f"filler-{index}", "email": f"filler-{index}@example.com"}
            for index in range(filler_count)
        ]
    )

    async def _namespace_generation_has_settled() -> bool:
        first = cache.capture_namespace_generation(namespace).generation
        await asyncio.sleep(0.2)
        return first == cache.capture_namespace_generation(namespace).generation

    await _wait_until(_namespace_generation_has_settled, timeout_seconds=20.0)

    for index in range(filler_count):
        if lru.peek(identity_key) is None:
            return
        await collection.find_one({"email": f"filler-{index}@example.com"})
    pytest.fail(  # pragma: no cover (test timeout diagnostic)
        "target entry was never evicted under budget pressure"
    )


async def test_a_still_accurate_resolved_alias_refreshes_with_a_single_round_trip(
    tight_budget_cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    email = faker.email()
    collection = tight_budget_cache_manager[cached_database_name][
        nonpersistent_collection_name
    ]
    await collection.raw.create_index("email", unique=True)
    target = {"_id": document_id, "email": email, "v": 1}
    await collection.raw.insert_one(target)
    assert await collection.find_one({"email": email}) == target
    await collection.find_one({"email": email}, {"v": 1})

    namespace = NamespaceId(cached_database_name, nonpersistent_collection_name)
    read_shape = order_sensitive_discriminator_key(
        ("find_one", None, codec_fingerprint(collection.raw.codec_options))
    )
    resolved_identity = tight_budget_cache_manager.cache_core.resolve_alias(
        namespace, ("email",), (email,), None
    )
    assert resolved_identity is not None
    identity_key = IdentityCacheKey(
        namespace, resolved_identity, canonicalize(read_shape)
    )

    await _evict_identity_entry_via_filler_pressure(
        tight_budget_cache_manager, collection, namespace, identity_key
    )
    assert (
        tight_budget_cache_manager.cache_core.resolve_alias(
            namespace, ("email",), (email,), None
        )
        is not None
    )

    with patch.object(
        AsyncCollection, "find_one", autospec=True, side_effect=AsyncCollection.find_one
    ) as spy:
        refreshed_document = await collection.find_one({"email": email})

    assert refreshed_document == target
    assert spy.call_count == 1


async def test_a_resolved_alias_with_no_remaining_match_discards_the_alias(
    tight_budget_cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    email = faker.email()
    collection = tight_budget_cache_manager[cached_database_name][
        nonpersistent_collection_name
    ]
    await collection.raw.create_index("email", unique=True)
    target = {"_id": document_id, "email": email, "v": 1}
    await collection.raw.insert_one(target)
    assert await collection.find_one({"email": email}) == target
    await collection.find_one({"email": email}, {"v": 1})

    namespace = NamespaceId(cached_database_name, nonpersistent_collection_name)
    read_shape = order_sensitive_discriminator_key(
        ("find_one", None, codec_fingerprint(collection.raw.codec_options))
    )
    resolved_identity = tight_budget_cache_manager.cache_core.resolve_alias(
        namespace, ("email",), (email,), None
    )
    assert resolved_identity is not None
    identity_key = IdentityCacheKey(
        namespace, resolved_identity, canonicalize(read_shape)
    )

    await _evict_identity_entry_via_filler_pressure(
        tight_budget_cache_manager, collection, namespace, identity_key
    )
    assert (
        tight_budget_cache_manager.cache_core.resolve_alias(
            namespace, ("email",), (email,), None
        )
        is not None
    )

    with patch.object(AsyncCollection, "find_one", autospec=True, return_value=None):
        reverified_document = await collection.find_one({"email": email})

    assert reverified_document is None
    assert (
        tight_budget_cache_manager.cache_core.resolve_alias(
            namespace, ("email",), (email,), None
        )
        is None
    )


async def test_a_revalidated_positive_match_overwrites_a_stale_namespace_entry(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    email = faker.email()
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index("email", unique=True)
    original = {"_id": document_id, "email": email, "v": 1}
    await collection.raw.insert_one(original)
    assert await collection.find_one({"email": email}) == original

    namespace = NamespaceId(cached_database_name, nonpersistent_collection_name)
    alias = canonical_alias_key(("email",), (email,), None)
    read_shape = order_sensitive_discriminator_key(
        ("find_one", None, codec_fingerprint(collection.raw.codec_options))
    )
    cache = cache_manager.cache_core
    identity = cache.resolve_alias(namespace, ("email",), (email,), None)
    assert identity is not None
    identity_key = IdentityCacheKey(namespace, identity, canonicalize(read_shape))
    identity_entry = cache._lru.peek(identity_key)
    assert identity_entry is not None
    assert cache._lru.remove_exact(identity_key, identity_entry)

    updated = {"_id": document_id, "email": email, "v": 2}
    with patch.object(AsyncCollection, "find_one", autospec=True, return_value=updated):
        refreshed = await collection.find_one({"email": email})

    assert refreshed == updated
    namespace_lookup = cache.lookup_namespace(namespace, (alias, read_shape))
    assert namespace_lookup.hit
    assert namespace_lookup.value == updated


async def test_an_uncanonicalizable_revalidated_identity_discards_the_stale_alias(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    email = faker.email()
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index("email", unique=True)
    original = {"_id": document_id, "email": email, "v": 1}
    await collection.raw.insert_one(original)
    assert await collection.find_one({"email": email}) == original

    namespace = NamespaceId(cached_database_name, nonpersistent_collection_name)
    alias = canonical_alias_key(("email",), (email,), None)
    read_shape = order_sensitive_discriminator_key(
        ("find_one", None, codec_fingerprint(collection.raw.codec_options))
    )
    cache = cache_manager.cache_core
    identity = cache.resolve_alias(namespace, ("email",), (email,), None)
    assert identity is not None
    identity_key = IdentityCacheKey(namespace, identity, canonicalize(read_shape))
    identity_entry = cache._lru.peek(identity_key)
    assert identity_entry is not None
    assert cache._lru.remove_exact(identity_key, identity_entry)

    replaced = {
        "_id": Decimal128("2.0"),
        "email": email,
        "v": 2,
    }
    with patch.object(
        AsyncCollection, "find_one", autospec=True, return_value=replaced
    ):
        revalidated = await collection.find_one({"email": email})

    assert revalidated == replaced
    assert cache.resolve_alias(namespace, ("email",), (email,), None) is None
    assert cache.lookup_namespace(namespace, (alias, read_shape)).hit is False


async def test_a_resolved_unique_key_read_rechecks_availability_before_forcing_options(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    email = faker.email()
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index("email", unique=True)
    document = {"_id": document_id, "email": email, "v": 1}
    await collection.raw.insert_one(document)
    await collection.find_one({"email": email})

    with (
        patch.object(
            CacheCore,
            "is_database_available",
            side_effect=_available_once_then_unavailable(),
        ),
        patch.object(
            AsyncCollection,
            "find_one",
            autospec=True,
            side_effect=AsyncCollection.find_one,
        ) as spy,
    ):
        returned_document = await collection.find_one({"email": email}, {"v": 1})

    assert returned_document == {"_id": document_id, "v": 1}
    assert spy.call_args.args[0] is collection.raw


@pytest.mark.parametrize(
    ("seed_document", "cache_identity"),
    [
        pytest.param(
            True,
            {1, 2, 3},
            id="unhashable-identity",
        ),
        pytest.param(False, None, id="null-identity"),
    ],
)
async def test_unique_key_match_skips_admission_for_an_uncacheable_identity(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    *,
    seed_document: bool,
    cache_identity: object,
    faker: Faker,
) -> None:
    email = faker.email()
    document = {"_id": faker.uuid4() if seed_document else None, "email": email, "v": 1}
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index("email", unique=True)
    await collection.raw.insert_one(document)

    with (
        patch(
            "client_query_cache.asynchronous.collection.normalize_identity_for_cache_key",
            return_value=cache_identity,
        ),
        patch.object(
            AsyncCollection,
            "find_one",
            autospec=True,
            side_effect=AsyncCollection.find_one,
        ) as spy,
    ):
        first = await collection.find_one({"email": email})
        second = await collection.find_one({"email": email})

    assert first == document
    assert second == document
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
async def test_unique_key_read_bypasses_cache_when_index_inspection_fails(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    caplog: pytest.LogCaptureFixture,
    *,
    probe_error: Exception,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    email = faker.email()
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index("email", unique=True)
    document = {"_id": document_id, "email": email, "name": faker.first_name()}
    await collection.raw.insert_one(document)

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise probe_error

    with (
        caplog.at_level("WARNING", logger="client_query_cache.asynchronous.collection"),
        patch.object(AsyncCollection, "list_indexes", side_effect=_raise),
        patch.object(
            AsyncCollection,
            "find_one",
            autospec=True,
            side_effect=AsyncCollection.find_one,
        ) as spy,
    ):
        first = await collection.find_one({"email": email})
        second = await collection.find_one({"email": email})

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
async def test_index_inspection_failure_is_not_memoized_as_a_permanent_absence(
    cache_manager: CacheManager[dict[str, Any]],
    cached_database_name: DatabaseName,
    nonpersistent_collection_name: CollectionName,
    probe_error: Exception,
    faker: Faker,
) -> None:
    document_id = faker.uuid4()
    email = faker.email()
    collection = cache_manager[cached_database_name][nonpersistent_collection_name]
    await collection.raw.create_index("email", unique=True)
    document = {"_id": document_id, "email": email, "name": faker.first_name()}
    await collection.raw.insert_one(document)

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise probe_error

    with patch.object(AsyncCollection, "list_indexes", side_effect=_raise):
        await collection.find_one({"email": email})

    with patch.object(
        AsyncCollection, "find_one", autospec=True, side_effect=AsyncCollection.find_one
    ) as spy:
        first = await collection.find_one({"email": email})
        second = await collection.find_one({"email": email})

    assert first == document
    assert second == document
    assert spy.call_count == 1
