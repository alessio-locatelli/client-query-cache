from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from benchmarks.stream_cost import guard_workload
from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.guard_workload import CASE_NAMES, PROFILES, run_case
from client_query_cache._core.stream_events import route_change_event
from client_query_cache._types import NonNegativeInt
from client_query_cache.synchronous.collection import CachedCollection

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from typing import Any

    from client_query_cache._core.manager import CacheCore
    from tests.conftest import MongoDbUri

pytestmark = pytest.mark.integration


def _uncached_find_one(
    collection: CachedCollection[dict[str, Any]], query: Mapping[str, Any]
) -> dict[str, Any] | None:
    return collection.raw.find_one(query)


def _wrong_find_one(
    collection: CachedCollection[dict[str, Any]], query: Mapping[str, Any]
) -> dict[str, Any]:
    document = collection.raw.find_one(query)
    assert document is not None
    document["padding"] = "wrong"
    return document


def _uncached_find(
    collection: CachedCollection[dict[str, Any]],
    query: Mapping[str, Any],
    *,
    sort: Sequence[tuple[str, int]],
    limit: NonNegativeInt,
) -> list[dict[str, Any]]:
    return list(collection.raw.find(query, sort=sort, limit=limit))


def _ignore_event(_cache: CacheCore, _database: str, _event: dict[str, object]) -> bool:
    return False


@pytest.mark.parametrize("case", CASE_NAMES)
@pytest.mark.parametrize("profile", [profile.name for profile in PROFILES])
def test_guard_case_checks_real_cache_outcome(
    mongodb_uri: MongoDbUri, case: str, profile: str
) -> None:
    assert run_case(mongodb_uri, case, profile) > 0


@pytest.mark.parametrize(
    ("case", "target", "replacement", "reason"),
    [
        ("sync_hit", "find_one", _uncached_find_one, "sync hit was bypassed"),
        ("sync_hit", "find_one", _wrong_find_one, "wrong data"),
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


def test_invalidation_rejects_partial_eviction(
    mongodb_uri: MongoDbUri, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_id: object | None = None

    def route_only_first_entry(
        cache: CacheCore, database: str, event: dict[str, object]
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
