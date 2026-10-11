from __future__ import annotations

import dataclasses
import importlib
import inspect
from contextlib import nullcontext
from datetime import datetime, timedelta, tzinfo
from typing import TYPE_CHECKING, Any, override
from unittest.mock import AsyncMock, Mock

import pytest
from bson.code import Code
from bson.codec_options import CodecOptions
from bson.errors import InvalidDocument
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from pymongo import AsyncMongoClient, MongoClient, ReadPreference
from pymongo.asynchronous.cursor import AsyncCursor
from pymongo.errors import ConnectionFailure
from pymongo.synchronous.cursor import Cursor

from client_query_cache import BypassReason, CacheManager
from client_query_cache._types import BsonDict, NonNegativeInt
from client_query_cache.asynchronous import CacheManager as AsyncCacheManager
from client_query_cache.otel import register_cache_metrics
from tests.cursor_helpers import materialize

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from client_query_cache import CachedCollection
    from client_query_cache.asynchronous import (
        CachedCollection as AsyncCachedCollection,
    )

type Manager = CacheManager[BsonDict] | AsyncCacheManager[BsonDict]
type Collection = CachedCollection[BsonDict] | AsyncCachedCollection[BsonDict]

pytestmark = pytest.mark.unit


@pytest.fixture(params=[False, True], ids=["sync", "async"])
async def manager(request: pytest.FixtureRequest) -> AsyncIterator[Manager]:
    if request.param:
        async_client = AsyncMongoClient[BsonDict](connect=False)
        async_manager = AsyncCacheManager(async_client)
        yield async_manager
        await async_manager.close()
        await async_client.close()
    else:
        with (
            MongoClient[BsonDict](connect=False) as client,
            CacheManager(client) as instance,
        ):
            yield instance


@pytest.fixture
def cached_collection(manager: Manager, monkeypatch: pytest.MonkeyPatch) -> Collection:
    collection = manager["observations"]["widgets"]
    is_async = isinstance(manager, AsyncCacheManager)
    mock_type = AsyncMock if is_async else Mock
    monkeypatch.setattr(type(manager._coordinator), "activate_database", mock_type())
    monkeypatch.setattr(
        type(collection.database.raw),
        "list_collections",
        mock_type(
            side_effect=AssertionError("request classification must not probe metadata")
        ),
    )
    monkeypatch.setattr(type(collection.raw), "find_one", mock_type(return_value=None))
    return collection


@pytest.mark.parametrize(
    ("options", "query", "projection", "secondary", "reason"),
    [
        pytest.param(
            {"session": Mock(), "comment": "options"},
            {"$where": "true"},
            None,
            True,
            BypassReason.SESSION,
            id="session-first",
        ),
        pytest.param(
            {"comment": "options"},
            {"$where": "true"},
            None,
            True,
            BypassReason.READ_PROFILE,
            id="profile-first",
        ),
        pytest.param(
            {"comment": "options"},
            {"$where": "true"},
            None,
            False,
            BypassReason.UNSUPPORTED_OPTIONS,
            id="options-first",
        ),
        pytest.param(
            {"sort": [("score", {"$meta": "textScore"})]},
            {"$where": "true"},
            None,
            False,
            BypassReason.UNSUPPORTED_OPTIONS,
            id="sort-first",
        ),
        pytest.param(
            {},
            {"$where": "true"},
            {"score": {"$meta": "textScore"}},
            False,
            BypassReason.UNSAFE_FILTER,
            id="filter-first",
        ),
        pytest.param(
            {},
            {},
            {"score": {"$meta": "textScore"}},
            False,
            BypassReason.UNSAFE_PROJECTION,
            id="projection",
        ),
        pytest.param(
            {},
            {"score": float("nan")},
            None,
            False,
            BypassReason.UNCANONICALIZABLE_KEY,
            id="key",
        ),
    ],
)
async def test_public_find_one_records_the_first_request_reason(
    cached_collection: Collection,
    options: dict[str, Any],
    query: BsonDict,
    projection: BsonDict | None,
    *,
    secondary: bool,
    reason: BypassReason,
) -> None:
    manager = cached_collection.database.manager
    if secondary:
        if isinstance(manager, AsyncCacheManager):
            cached_collection = manager.get_cached_collection(
                manager.client["observations"]["widgets"].with_options(
                    read_preference=ReadPreference.SECONDARY
                )
            )
        else:
            cached_collection = manager.get_cached_collection(
                manager.client["observations"]["widgets"].with_options(
                    read_preference=ReadPreference.SECONDARY
                )
            )
    returned = cached_collection.find_one(query, projection, **options)
    if inspect.isawaitable(returned):
        await returned
    snapshot = manager.snapshot()
    assert snapshot.bypasses == 1
    assert snapshot.misses == snapshot.hits == 0
    assert {
        record.reason: record.count for record in snapshot.bypass_reasons
    } == dict.fromkeys(BypassReason, 0) | {reason: 1}
    assert manager.stream_health_snapshot("observations").status == "not_started"


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        pytest.param(None, BypassReason.MISSING_COLLECTION, id="missing"),
        pytest.param({"type": "view"}, BypassReason.VIEW_COLLECTION, id="view"),
        pytest.param(
            {"type": "timeseries"}, BypassReason.TIME_SERIES_COLLECTION, id="timeseries"
        ),
        pytest.param(
            {"type": "future_collection_type"},
            BypassReason.METADATA_UNAVAILABLE,
            id="unknown-type",
        ),
        pytest.param(
            ConnectionFailure("metadata unavailable"),
            BypassReason.METADATA_UNAVAILABLE,
            id="metadata-error",
        ),
    ],
)
async def test_public_metadata_reasons_preserve_probe_lifetimes(
    cached_collection: Collection,
    monkeypatch: pytest.MonkeyPatch,
    entry: BsonDict | ConnectionFailure | None,
    reason: BypassReason,
) -> None:
    manager = cached_collection.database.manager
    probe: Mock = Mock()
    if isinstance(manager, AsyncCacheManager):
        probe = AsyncMock()
        cursor = Mock()
        cursor.to_list = AsyncMock(return_value=[] if entry is None else [entry])
        probe.return_value = cursor
    if isinstance(entry, ConnectionFailure):
        probe.side_effect = entry
    # Produce a fresh cursor for each actual probe.
    if not isinstance(manager, AsyncCacheManager) and not isinstance(
        entry, ConnectionFailure
    ):
        probe.side_effect = lambda **_kwargs: iter([] if entry is None else [entry])
    monkeypatch.setattr(type(cached_collection.database.raw), "list_collections", probe)
    for _ in range(2):
        returned = cached_collection.find_one({})
        if inspect.isawaitable(returned):
            await returned
    assert manager.snapshot().bypasses == 2
    assert (
        next(
            record.count
            for record in manager.snapshot().bypass_reasons
            if record.reason is reason
        )
        == 2
    )
    assert probe.call_count == (
        2
        if reason
        in {BypassReason.MISSING_COLLECTION, BypassReason.METADATA_UNAVAILABLE}
        else 1
    )


@pytest.mark.parametrize(
    "available", [False, True], ids=["watch-pending", "publication-pending"]
)
async def test_pending_activation_records_stream_unavailable(
    cached_collection: Collection,
    monkeypatch: pytest.MonkeyPatch,
    *,
    available: bool,
) -> None:
    manager = cached_collection.database.manager
    mock_type = AsyncMock if isinstance(manager, AsyncCacheManager) else Mock
    monkeypatch.setattr(
        type(manager._coordinator), "activate_database", mock_type(return_value=None)
    )
    manager.cache_core.set_database_available("observations", available=available)
    for _ in range(3):
        returned = cached_collection.find_one({})
        if inspect.isawaitable(returned):
            await returned
    snapshot = manager.snapshot()
    assert snapshot.bypasses == 3
    assert snapshot.misses == snapshot.hits == 0
    assert (
        next(
            record.count
            for record in snapshot.bypass_reasons
            if record.reason is BypassReason.STREAM_UNAVAILABLE
        )
        == 3
    )


def test_manager_metric_callbacks_are_local_and_read_only(
    manager: Manager,
) -> None:
    manager.cache_core.record_bypass(BypassReason.MISSING_COLLECTION)
    manager.cache_core.record_stream_poll("observations")
    before_cache = manager.snapshot()
    before_stream = manager.stream_cost_snapshot("observations")
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    register_cache_metrics(provider.get_meter("observability-test"), manager)
    for _ in range(2):
        measurements = reader.get_metrics_data()
        assert measurements is not None
    assert manager.snapshot() == before_cache
    assert manager.stream_cost_snapshot("observations") == before_stream
    assert manager.stream_health_snapshot("observations").status == "not_started"


@pytest.mark.parametrize(
    "package",
    [
        "client_query_cache",
        "client_query_cache.synchronous",
        "client_query_cache.asynchronous",
    ],
    ids=["top-level", "sync", "async"],
)
def test_inspection_types_are_public(package: str) -> None:
    module = importlib.import_module(package)
    assert module.BypassReason is BypassReason
    for name in (
        "CacheSnapshot",
        "BypassReasonCount",
        "StreamCostSnapshot",
        "StreamHealthSnapshot",
    ):
        assert dataclasses.is_dataclass(getattr(module, name))


@pytest.fixture
def raw_method(
    cached_collection: Collection,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    method = request.node.callspec.params["method"]
    is_async = isinstance(cached_collection.database.manager, AsyncCacheManager)
    if method == "find":
        monkeypatch.setattr(
            AsyncCursor if is_async else Cursor,
            "_refresh",
            (AsyncMock if is_async else Mock)(return_value=0),
        )
        return
    returned: object = (
        0 if method in {"count_documents", "estimated_document_count"} else []
    )
    if method == "aggregate" and is_async:
        cursor = Mock()
        cursor.to_list = AsyncMock(return_value=[])
        returned = cursor
    operation = (AsyncMock if is_async else Mock)(return_value=returned)
    monkeypatch.setattr(type(cached_collection.raw), method, operation)


@pytest.fixture
def eligibility_probe(
    cached_collection: Collection, monkeypatch: pytest.MonkeyPatch
) -> Mock:
    is_async = isinstance(cached_collection.database.manager, AsyncCacheManager)
    probe = (AsyncMock if is_async else Mock)(
        side_effect=AssertionError("failed preparation must skip eligibility")
    )
    monkeypatch.setattr(type(cached_collection), "_cache_ineligibility_reason", probe)
    return probe


@pytest.mark.usefixtures("raw_method")
@pytest.mark.parametrize(
    ("method", "arguments", "reason"),
    [
        pytest.param(
            "find", ({"$where": "true"},), BypassReason.UNSAFE_FILTER, id="find-filter"
        ),
        pytest.param(
            "find",
            ({}, {"score": {"$meta": "textScore"}}),
            BypassReason.UNSAFE_PROJECTION,
            id="find-projection",
        ),
        pytest.param(
            "count_documents",
            ({"$where": "true"},),
            BypassReason.UNSAFE_FILTER,
            id="count-filter",
        ),
        pytest.param(
            "distinct",
            ("score", {"$where": "true"}),
            BypassReason.UNSAFE_FILTER,
            id="distinct-filter",
        ),
        pytest.param(
            "aggregate",
            ([{"$sample": {"size": 1}}],),
            BypassReason.UNSAFE_PIPELINE,
            id="pipeline",
        ),
        pytest.param(
            "find",
            ({"score": float("nan")},),
            BypassReason.UNCANONICALIZABLE_KEY,
            id="find-key",
        ),
        pytest.param(
            "aggregate",
            ([{"$match": {"score": float("nan")}}],),
            BypassReason.UNCANONICALIZABLE_KEY,
            id="pipeline-key",
        ),
        pytest.param(
            "find",
            ({"score": float("nan")}, {"score": {"$meta": "textScore"}}),
            BypassReason.UNSAFE_PROJECTION,
            id="projection-before-key",
        ),
    ],
)
async def test_public_materialized_reads_classify_unsafe_shapes(
    cached_collection: Collection,
    eligibility_probe: Mock,
    method: str,
    arguments: tuple[object, ...],
    reason: BypassReason,
) -> None:
    returned = getattr(cached_collection, method)(*arguments)
    if method == "find":
        await materialize(returned)
    elif inspect.isawaitable(returned):
        await returned
    eligibility_probe.assert_not_called()
    snapshot = cached_collection.database.manager.snapshot()
    assert snapshot.bypasses == 1
    assert (
        next(
            record.count
            for record in snapshot.bypass_reasons
            if record.reason is reason
        )
        == 1
    )


@dataclasses.dataclass(slots=True)
class _UnhashableTimezone(tzinfo):
    @override
    def utcoffset(self, _dt: datetime | None) -> timedelta:
        return timedelta(0)

    @override
    def dst(self, _dt: datetime | None) -> timedelta:
        return timedelta(0)

    @override
    def tzname(self, _dt: datetime | None) -> str:
        return "UTC"


async def test_unhashable_timezone_constructs_and_bypasses(
    cached_collection: Collection,
) -> None:
    manager = cached_collection.database.manager
    timestamp = datetime.now(_UnhashableTimezone())
    assert timestamp.utcoffset() == timestamp.dst() == timedelta(0)
    assert timestamp.tzname() == "UTC"
    options: CodecOptions[BsonDict] = CodecOptions(
        tz_aware=True, tzinfo=_UnhashableTimezone()
    )
    collection: Collection
    if isinstance(manager, AsyncCacheManager):
        collection = manager.get_cached_collection(
            manager.client["observations"]["widgets"].with_options(
                codec_options=options
            )
        )
    else:
        collection = manager.get_cached_collection(
            manager.client["observations"]["widgets"].with_options(
                codec_options=options
            )
        )
    returned = collection.find_one({})
    if inspect.isawaitable(returned):
        await returned
    snapshot = manager.snapshot()
    assert snapshot.bypasses == 1
    assert (
        next(
            record.count
            for record in snapshot.bypass_reasons
            if record.reason is BypassReason.UNCANONICALIZABLE_KEY
        )
        == 1
    )


@pytest.mark.usefixtures("raw_method")
@pytest.mark.parametrize("method", ["find", "aggregate", "count_documents", "distinct"])
@pytest.mark.parametrize(
    ("condition", "reason"),
    [
        pytest.param("session", BypassReason.SESSION, id="session-first"),
        pytest.param("profile", BypassReason.READ_PROFILE, id="profile-first"),
        pytest.param("options", BypassReason.UNSUPPORTED_OPTIONS, id="options-first"),
        pytest.param("unsafe", None, id="unsafe-before-key"),
        pytest.param(
            "key", BypassReason.UNCANONICALIZABLE_KEY, id="key-before-metadata"
        ),
        pytest.param("code", BypassReason.UNCANONICALIZABLE_KEY, id="code-key"),
        pytest.param(
            "native-error", BypassReason.UNCANONICALIZABLE_KEY, id="native-error"
        ),
    ],
)
async def test_read_preparation_preserves_combined_bypass_precedence(
    cached_collection: Collection,
    eligibility_probe: Mock,
    raw_key_traversals: list[NonNegativeInt],
    monkeypatch: pytest.MonkeyPatch,
    *,
    method: str,
    condition: str,
    reason: BypassReason | None,
) -> None:
    manager = cached_collection.database.manager
    if condition == "profile":
        monkeypatch.setattr(
            cached_collection,
            "_collection",
            cached_collection.raw.with_options(
                read_preference=ReadPreference.SECONDARY
            ),
        )
    query: BsonDict = {"score": set() if condition == "native-error" else float("nan")}
    if condition == "code":
        query["score"] = Code("function() { return true; }")
    unsafe = condition not in {"key", "code", "native-error"}
    if unsafe:
        query["$expr"] = {"$rand": {}}
    pipeline = [{"$match": query}]
    if unsafe:
        pipeline.append({"$sample": {"size": 1}})
    options: dict[str, Any] = {}
    if condition == "session":
        options["session"] = Mock()
    elif condition == "options":
        options["comment"] = "native request"
    arguments: tuple[object, ...]
    if method == "find":
        arguments = (query, {"score": {"$meta": "textScore"}} if unsafe else None)
    elif method == "aggregate":
        arguments = (pipeline,)
    elif method == "distinct":
        arguments = ("score", query)
    else:
        arguments = (query,)
    if reason is None:
        reason = (
            BypassReason.UNSAFE_PIPELINE
            if method == "aggregate"
            else BypassReason.UNSAFE_FILTER
        )
    is_async = isinstance(manager, AsyncCacheManager)
    operation = (
        (AsyncCursor if is_async else Cursor)._refresh
        if method == "find"
        else getattr(type(cached_collection.raw), method)
    )
    assert isinstance(operation, Mock)
    if condition == "native-error":
        operation.side_effect = InvalidDocument("native unsupported value")
    raw_key_traversals.clear()
    with (
        pytest.raises(InvalidDocument, match="native unsupported value")
        if condition == "native-error"
        else nullcontext()
    ):
        returned = getattr(cached_collection, method)(*arguments, **options)
        if method == "find":
            assert returned._spec is query
            await materialize(returned)
        elif inspect.isawaitable(returned):
            await returned
    if method != "find":
        assert operation.call_args.args[-1] is arguments[-1]
    operation.assert_called_once()
    eligibility_probe.assert_not_called()
    assert raw_key_traversals in ([], [0]) if unsafe else raw_key_traversals == [1]
    snapshot = manager.snapshot()
    assert snapshot.bypasses == 1
    assert snapshot.hits == snapshot.misses == snapshot.entry_count == 0
    assert {record.reason: record.count for record in snapshot.bypass_reasons} == (
        dict.fromkeys(BypassReason, 0) | {reason: 1}
    )
