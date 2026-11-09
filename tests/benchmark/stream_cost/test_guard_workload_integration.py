from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from benchmarks.stream_cost import guard_workload
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.guard_workload import CASE_NAMES, PROFILES, run_case
from client_query_cache._core.stream_events import route_change_event
from client_query_cache._types import BsonDict, NonNegativeInt
from client_query_cache.asynchronous.collection import (
    CachedCollection as AsyncCachedCollection,
)
from client_query_cache.synchronous.collection import CachedCollection

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from typing import Any

    from client_query_cache import CacheCore, CacheCoreConfig
    from tests.conftest import MongoDbUri

pytestmark = pytest.mark.integration


def _uncached_find_one(
    collection: CachedCollection[BsonDict], query: Mapping[str, Any]
) -> BsonDict | None:
    return collection.raw.find_one(query)


def _wrong_find_one(
    collection: CachedCollection[BsonDict], query: Mapping[str, Any]
) -> BsonDict:
    document = collection.raw.find_one(query)
    assert document is not None
    document["padding"] = "wrong"
    return document


async def _uncached_async_find_one(
    collection: AsyncCachedCollection[BsonDict], query: Mapping[str, Any]
) -> BsonDict | None:
    return await collection.raw.find_one(query)


async def _wrong_async_find_one(
    collection: AsyncCachedCollection[BsonDict], query: Mapping[str, Any]
) -> BsonDict:
    document = await collection.raw.find_one(query)
    assert document is not None
    document["padding"] = "wrong"
    return document


def _uncached_find(
    collection: CachedCollection[BsonDict],
    query: Mapping[str, Any],
    *,
    sort: Sequence[tuple[str, int]],
    limit: NonNegativeInt,
) -> list[BsonDict]:
    return list(collection.raw.find(query, sort=sort, limit=limit))


def _ignore_event(_cache: CacheCore, _database: str, _event: BsonDict) -> bool:
    return False


@pytest.mark.parametrize("case", CASE_NAMES)
@pytest.mark.parametrize("profile", [profile.name for profile in PROFILES])
def test_guard_case_checks_real_cache_outcome(
    mongodb_uri: MongoDbUri,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    profile: str,
) -> None:
    configure = guard_workload._cache_config
    policies: list[bool] = []

    def configured(*, enable_telemetry: bool = True) -> CacheCoreConfig:
        config = configure(enable_telemetry=enable_telemetry)
        policies.append(config.enable_telemetry)
        return config

    monkeypatch.setattr(guard_workload, "_cache_config", configured)

    assert run_case(mongodb_uri, case, profile) > 0
    assert policies == [case not in {"sync_hit", "async_hit"}]


@pytest.mark.parametrize(
    ("case", "target", "replacement", "reason"),
    [
        ("find_admission", "find", _uncached_find, "admission was missing"),
        ("invalidation", "route_change_event", _ignore_event, "did not invalidate"),
    ],
)
def test_guard_rejects_invalid_outcome(
    mongodb_uri: MongoDbUri,
    monkeypatch: pytest.MonkeyPatch,
    *,
    case: str,
    target: str,
    replacement: Callable[..., object],
    reason: str,
) -> None:
    owner = guard_workload if target == "route_change_event" else CachedCollection
    monkeypatch.setattr(owner, target, replacement)
    with pytest.raises(BenchmarkSetupError, match=reason):
        run_case(mongodb_uri, case, "small")


@pytest.mark.parametrize(
    ("case", "owner", "bypass", "wrong"),
    [
        ("sync_hit", CachedCollection, _uncached_find_one, _wrong_find_one),
        ("sync_hit_telemetry", CachedCollection, _uncached_find_one, _wrong_find_one),
        (
            "async_hit",
            AsyncCachedCollection,
            _uncached_async_find_one,
            _wrong_async_find_one,
        ),
        (
            "async_hit_telemetry",
            AsyncCachedCollection,
            _uncached_async_find_one,
            _wrong_async_find_one,
        ),
    ],
)
@pytest.mark.parametrize("fault", ["bypass", "wrong-value"])
def test_hit_oracle_rejects_bypassed_or_incorrect_reads(
    mongodb_uri: MongoDbUri,
    monkeypatch: pytest.MonkeyPatch,
    *,
    case: str,
    owner: type[CachedCollection[BsonDict] | AsyncCachedCollection[BsonDict]],
    bypass: Callable[..., object],
    wrong: Callable[..., object],
    fault: str,
) -> None:
    replacement = bypass if fault == "bypass" else wrong
    reason = "hit was bypassed" if fault == "bypass" else "wrong data"
    monkeypatch.setattr(owner, "find_one", replacement)

    with pytest.raises(BenchmarkSetupError, match=reason):
        run_case(mongodb_uri, case, "small")


def test_invalidation_rejects_partial_eviction(
    mongodb_uri: MongoDbUri, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_id: object | None = None

    def route_only_first_entry(
        cache: CacheCore, database: str, event: BsonDict
    ) -> bool:
        nonlocal first_id
        key = event["documentKey"]
        assert isinstance(key, dict)
        if first_id is None:
            first_id = key["_id"]
        altered = dict(event)
        altered["documentKey"] = {"_id": first_id}
        return route_change_event(cache, database, altered)

    monkeypatch.setattr(guard_workload, "route_change_event", route_only_first_entry)
    with pytest.raises(BenchmarkSetupError, match="targeted entries survived"):
        run_case(mongodb_uri, "invalidation", "small")
