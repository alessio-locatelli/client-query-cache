from __future__ import annotations

from functools import partial, partialmethod
from typing import TYPE_CHECKING, TypedDict
from unittest.mock import patch

import pytest
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.synchronous.collection import Collection

from client_query_cache._core.codec import codec_fingerprint, encode_value
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.find_one_reads import find_one_read_shape
from client_query_cache._core.keys import canonical_alias_key
from client_query_cache._types import BsonDict, NonEmptyStr, NonNegativeInt
from tests.cursor_helpers import materialize, resolved
from tests.polling import wait_until_async

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator
    from unittest.mock import Mock

    from faker import Faker

    from client_query_cache._core.contracts import LocalCacheCore, NamespaceCaptureView
    from client_query_cache._core.keys import AliasKey
    from tests.cursor_fixtures import Binding, View

pytestmark = pytest.mark.integration


class UniqueRead(TypedDict):
    view: View
    target: BsonDict
    shape: object


@pytest.fixture
async def evicted_unique(cursors: Binding, faker: Faker) -> AsyncIterator[UniqueRead]:
    view = cursors["view"]
    target: BsonDict = {"_id": faker.uuid4(), "email": faker.email(), "v": 1}
    await resolved(view.raw.create_index("email", unique=True))
    await resolved(view.raw.insert_one(target))
    core = view.database.manager.cache_core
    namespace = view._namespace()
    query = {"email": target["email"]}
    expected = {"email": target["email"], "v": 1}

    async def warm() -> bool:
        assert await resolved(view.find_one(query, {"_id": 0})) == expected
        return (
            core.resolve_alias(namespace, ("email",), (target["email"],), None)
            is not None
        )

    await wait_until_async(warm)
    shape = find_one_read_shape(
        {"_id": 0}, None, None, codec_fingerprint(view.raw.codec_options)
    )
    capture = core.begin_identity_admission(namespace, target["_id"])
    try:
        budget = core.snapshot().budget_bytes
        filler = b"x" * (budget - len(encode_value(b"")))
        assert (
            core.admit_namespace(
                core.capture_namespace_generation(namespace), "filler", filler
            )
            is AdmissionOutcome.ADMITTED
        )
        assert not core.lookup_identity(namespace, target["_id"], shape).hit
        assert (
            core.resolve_alias(namespace, ("email",), (target["email"],), None)
            == target["_id"]
        )
        yield {"view": view, "target": target, "shape": shape}
    finally:
        capture.release()


@pytest.fixture
def rebound_origin(evicted_unique: UniqueRead) -> Iterator[Mock]:
    raw = evicted_unique["view"].raw
    driver = Collection if isinstance(raw, Collection) else AsyncCollection
    replacement = {**evicted_unique["target"], "_id": "B" * 16384, "v": 2}
    with patch.object(
        driver, "find_one", autospec=True, return_value=replacement
    ) as origin:
        yield origin


def replace_before_cleanup(
    core: LocalCacheCore,
    capture: NamespaceCaptureView,
    alias: AliasKey,
    expected: object,
    *,
    replacement: NonEmptyStr,
    original: Callable[..., None],
) -> None:
    assert (
        core.admit_identity(
            core.begin_identity_admission(capture.namespace, replacement),
            "other-shape",
            {"v": 3},
            alias=alias,
        )
        is AdmissionOutcome.ADMITTED
    )
    original(core, capture, alias, expected)


@pytest.fixture(params=[False, True], ids=["remove-stale", "preserve-newer"])
def alias_replacement(
    request: pytest.FixtureRequest,
    evicted_unique: UniqueRead,
    monkeypatch: pytest.MonkeyPatch,
    faker: Faker,
) -> NonEmptyStr | None:
    if not request.param:
        return None
    core = evicted_unique["view"].database.manager.cache_core
    identity = faker.uuid4()
    original = type(core).discard_stale_alias
    monkeypatch.setattr(
        type(core),
        "discard_stale_alias",
        partialmethod(
            replace_before_cleanup,
            replacement=identity,
            original=original,
        ),
    )
    return identity


@pytest.mark.parametrize(
    "cursors",
    [
        (api, 1, 0, 256, {"budget_bytes": 256, "max_entries": 3, "max_key_bytes": 8192})
        for api in ("sync", "async")
    ],
    indirect=True,
    ids=["sync", "async"],
)
async def test_successful_namespace_fallback_retires_only_the_proven_stale_alias(
    evicted_unique: UniqueRead,
    rebound_origin: Mock,
    alias_replacement: NonEmptyStr | None,
) -> None:
    view = evicted_unique["view"]
    core = view.database.manager.cache_core
    email = evicted_unique["target"]["email"]
    expected = {"email": email, "v": 2}
    assert await resolved(view.find_one({"email": email}, {"_id": 0})) == expected
    assert (
        core.resolve_alias(view._namespace(), ("email",), (email,), None)
        == alias_replacement
    )
    alias = canonical_alias_key(("email",), (email,), None)
    assert core.lookup_namespace(
        view._namespace(), (alias, evicted_unique["shape"])
    ).hit
    before = core.snapshot()
    assert await resolved(view.find_one({"email": email}, {"_id": 0})) == expected
    after = core.snapshot()
    assert after.hits == before.hits + 1
    assert after.misses == before.misses
    assert rebound_origin.call_count == 1


async def read_operation(view: View, kind: str, query: BsonDict) -> object:
    if kind == "find_one":
        return await resolved(view.find_one(query))
    if kind == "count_documents":
        return await resolved(view.count_documents(query))
    if kind == "distinct":
        return await resolved(view.distinct("value", query))
    cursor = view.find(query) if kind == "find" else view.aggregate([{"$match": query}])
    return await materialize(cursor)


@pytest.mark.parametrize(
    "kind", ["find_one", "find", "aggregate", "count_documents", "distinct"]
)
@pytest.mark.parametrize(
    "cursors",
    [
        (api, 20, 0, 131072, {"max_entries": 2, "max_key_bytes": 8192})
        for api in ("sync", "async")
    ],
    indirect=True,
    ids=["sync", "async"],
)
async def test_limits_preserve_public_read_delivery_and_warm_hits(
    cursors: Binding, kind: str
) -> None:
    view = cursors["view"]
    query: BsonDict = {"value": {"$gte": 5}}
    first = await read_operation(view, kind, query)
    before = view.database.manager.snapshot()
    assert await read_operation(view, kind, query) == first
    after = view.database.manager.snapshot()
    assert after.hits == before.hits + 1
    assert after.misses == before.misses
    assert after.entry_count + after.alias_count <= 2
    large: BsonDict = {"value": {"$in": [5, "x" * 16384]}}
    first_large = await read_operation(view, kind, large)
    before_large = view.database.manager.snapshot()
    assert await read_operation(view, kind, large) == first_large
    after_large = view.database.manager.snapshot()
    assert after_large.hits == before_large.hits
    assert after_large.misses == before_large.misses + 1
    assert after_large.bypasses == before_large.bypasses
    assert after_large.entry_count + after_large.alias_count <= 2


def invalidation_observed(
    core: LocalCacheCore, database: NonEmptyStr, before: NonNegativeInt
) -> bool:
    return core.stream_cost_snapshot(database).invalidations > before


@pytest.fixture
async def unique_value(cursors: Binding) -> View:
    view = cursors["view"]
    await resolved(view.raw.create_index("value", unique=True))

    async def warmed() -> bool:
        before = view.database.manager.snapshot().hits
        assert await resolved(view.find_one({"value": 0})) == cursors["documents"][0]
        return view.database.manager.snapshot().hits > before

    await wait_until_async(warmed)
    return view


@pytest.mark.parametrize(
    "cursors",
    [
        (api, 2, 0, 131072, {"max_entries": maximum, "max_key_bytes": 8192})
        for api in ("sync", "async")
        for maximum in (1, 2)
    ],
    indirect=True,
    ids=["sync-one", "sync-pair", "async-one", "async-pair"],
)
async def test_unique_queries_hit_and_observe_processed_writes(
    unique_value: View,
) -> None:
    view = unique_value
    manager = view.database.manager
    before = manager.snapshot()
    original = await resolved(view.find_one({"value": 0}))
    assert isinstance(original, dict)
    assert manager.snapshot().hits == before.hits + 1
    for identity in (1, 0):
        invalidations = manager.cache_core.stream_cost_snapshot(
            view.database.name
        ).invalidations
        await resolved(
            view.raw.update_one({"_id": identity}, {"$set": {"payload": "changed"}})
        )
        await wait_until_async(
            partial(
                invalidation_observed,
                manager.cache_core,
                view.database.name,
                invalidations,
            )
        )
        observed_document = await resolved(view.find_one({"value": 0}))
        assert observed_document == (
            original if identity == 1 else {**original, "payload": "changed"}
        )
    snapshot = manager.snapshot()
    assert snapshot.max_entries is not None
    assert snapshot.entry_count + snapshot.alias_count <= snapshot.max_entries


@pytest.fixture
async def embedded_document(cursors: Binding, faker: Faker) -> BsonDict:
    view = cursors["view"]
    document: BsonDict = {
        "_id": {"tenant": faker.uuid4(), "sequence": 1},
        "email": faker.email(),
        "value": 1,
    }
    await resolved(view.raw.create_index("email", unique=True))
    await resolved(view.raw.insert_one(document))

    async def warmed() -> bool:
        before = view.database.manager.snapshot().hits
        assert await resolved(view.find_one({"email": document["email"]})) == document
        return view.database.manager.snapshot().hits > before

    await wait_until_async(warmed)
    return document


@pytest.mark.parametrize(
    "cursors",
    [
        (api, 1, 0, 131072, {"max_entries": maximum, "max_key_bytes": 8192})
        for api in ("sync", "async")
        for maximum in (None, 1, 2)
    ],
    indirect=True,
    ids=[
        "sync-disabled",
        "sync-one",
        "sync-pair",
        "async-disabled",
        "async-one",
        "async-pair",
    ],
)
async def test_embedded_identity_keeps_its_order_across_unique_and_id_reads(
    cursors: Binding,
    embedded_document: BsonDict,
) -> None:
    view = cursors["view"]
    before = view.database.manager.snapshot()
    matched_document = await resolved(
        view.find_one({"email": embedded_document["email"]})
    )
    assert matched_document == embedded_document
    assert isinstance(matched_document, dict)
    identity = matched_document["_id"]
    assert isinstance(identity, dict)
    assert tuple(identity) == ("tenant", "sequence")
    after = view.database.manager.snapshot()
    assert after.hits == before.hits + 1
    if after.max_entries != 1:
        assert (
            await resolved(view.find_one({"_id": embedded_document["_id"]}))
            == embedded_document
        )
        assert view.database.manager.snapshot().hits == after.hits + 1
