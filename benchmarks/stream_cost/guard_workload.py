from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from pymongo import AsyncMongoClient, MongoClient

from benchmarks.stream_cost.errors import BenchmarkSetupError
from benchmarks.stream_cost.generators import (
    MEDIUM_DOCUMENT_PROFILE,
    SMALL_DOCUMENT_PROFILE,
    DocumentSizeProfile,
    generate_seeded_documents,
)
from client_query_cache._core.stream_events import route_change_event
from client_query_cache.asynchronous.manager import CacheManager as AsyncCacheManager
from client_query_cache.synchronous.manager import CacheManager

if TYPE_CHECKING:
    from collections.abc import Generator

    from client_query_cache._core.snapshots import CacheSnapshot

PROFILES: tuple[DocumentSizeProfile, ...] = (
    SMALL_DOCUMENT_PROFILE,
    MEDIUM_DOCUMENT_PROFILE,
)
CASE_NAMES = ("sync_hit", "async_hit", "find_admission", "invalidation")
DOCUMENT_COUNT = 64
_HIT_OPERATIONS = 2048
_ADMISSION_OPERATIONS = 48
_INVALIDATION_ENTRIES = 24
_INVALIDATION_REPEATS = 64


def _checked(*, condition: bool, reason: str) -> None:
    if not condition:
        raise BenchmarkSetupError(reason)


def _delta(before: CacheSnapshot, after: CacheSnapshot, field: str) -> int:
    return int(getattr(after, field)) - int(getattr(before, field))


@contextmanager
def _seeded_collection(
    uri: str, profile: DocumentSizeProfile
) -> Generator[tuple[MongoClient[dict[str, Any]], list[dict[str, object]]]]:
    documents = generate_seeded_documents(profile, count=DOCUMENT_COUNT, seed=90210)
    with MongoClient[dict[str, Any]](uri) as client:
        client["guard"]["documents"].drop()
        client["guard"]["documents"].insert_many(documents)
        try:
            yield client, documents
        finally:
            client.drop_database("guard")


def _sync_hit(
    client: MongoClient[dict[str, Any]], documents: list[dict[str, object]]
) -> float:
    with CacheManager(client) as manager:
        cached = manager["guard"]["documents"]
        expected = documents[0]
        query = {"_id": expected["_id"]}
        _checked(
            condition=cached.find_one(query) == expected,
            reason="sync hit priming returned wrong data",
        )
        before = manager.cache_core.snapshot()
        started = time.perf_counter()
        actual = [cached.find_one(query) for _ in range(_HIT_OPERATIONS)]
        elapsed = time.perf_counter() - started
        after = manager.cache_core.snapshot()
        _checked(
            condition=all(value == expected for value in actual),
            reason="sync hit returned wrong data",
        )
        _checked(
            condition=_delta(before, after, "hits") == _HIT_OPERATIONS,
            reason="sync hit was bypassed",
        )
        _checked(
            condition=_delta(before, after, "bypasses") == 0,
            reason="sync hit was bypassed",
        )
        return elapsed


async def _async_hit(uri: str, documents: list[dict[str, object]]) -> float:
    async with (
        AsyncMongoClient[dict[str, Any]](uri) as client,
        AsyncCacheManager(client) as manager,
    ):
        cached = manager["guard"]["documents"]
        expected = documents[0]
        query = {"_id": expected["_id"]}
        _checked(
            condition=await cached.find_one(query) == expected,
            reason="async hit priming returned wrong data",
        )
        before = manager.cache_core.snapshot()
        started = time.perf_counter()
        actual = [await cached.find_one(query) for _ in range(_HIT_OPERATIONS)]
        elapsed = time.perf_counter() - started
        after = manager.cache_core.snapshot()
        _checked(
            condition=all(value == expected for value in actual),
            reason="async hit returned wrong data",
        )
        _checked(
            condition=_delta(before, after, "hits") == _HIT_OPERATIONS,
            reason="async hit was bypassed",
        )
        _checked(
            condition=_delta(before, after, "bypasses") == 0,
            reason="async hit was bypassed",
        )
        return elapsed


def _find_admission(
    client: MongoClient[dict[str, Any]], documents: list[dict[str, object]]
) -> float:
    with CacheManager(client) as manager:
        cached = manager["guard"]["documents"]
        before = manager.cache_core.snapshot()
        started = time.perf_counter()
        read_results = [
            cached.find({"index": {"$gte": index}}, sort=[("index", 1)], limit=4)
            for index in range(_ADMISSION_OPERATIONS)
        ]
        elapsed = time.perf_counter() - started
        after = manager.cache_core.snapshot()
        for index, result in enumerate(read_results):
            _checked(
                condition=result == documents[index : index + 4],
                reason="find admission returned wrong data",
            )
        _checked(
            condition=_delta(before, after, "misses") == _ADMISSION_OPERATIONS,
            reason="find admission was missing",
        )
        _checked(
            condition=_delta(before, after, "bypasses") == 0,
            reason="find admission was bypassed",
        )
        _checked(
            condition=after.entry_count >= _ADMISSION_OPERATIONS,
            reason="find result was not retained",
        )
        return elapsed


def _invalidation(
    client: MongoClient[dict[str, Any]], documents: list[dict[str, object]]
) -> float:
    with CacheManager(client) as manager:
        cached = manager["guard"]["documents"]
        ids = [document["_id"] for document in documents[:_INVALIDATION_ENTRIES]]
        for document, document_id in zip(
            documents[:_INVALIDATION_ENTRIES], ids, strict=True
        ):
            _checked(
                condition=cached.find_one({"_id": document_id}) == document,
                reason="invalidation priming returned wrong data",
            )
        before = manager.cache_core.snapshot()
        _checked(
            condition=before.entry_count >= _INVALIDATION_ENTRIES,
            reason="invalidation entries were not populated",
        )
        events = [
            {
                "operationType": "update",
                "ns": {"db": "guard", "coll": "documents"},
                "documentKey": {"_id": document_id},
                "wallTime": datetime.datetime.now(datetime.UTC),
            }
            for document_id in ids
            for _ in range(_INVALIDATION_REPEATS)
        ]
        stream_before = manager.cache_core.stream_cost_snapshot("guard")
        started = time.perf_counter()
        for event in events:
            route_change_event(manager.cache_core, "guard", event)
        elapsed = time.perf_counter() - started
        stream_after = manager.cache_core.stream_cost_snapshot("guard")
        _checked(
            condition=stream_after.invalidations - stream_before.invalidations
            == len(events),
            reason="change events did not invalidate",
        )
        before_refresh = manager.cache_core.snapshot()
        for document, document_id in zip(
            documents[:_INVALIDATION_ENTRIES], ids, strict=True
        ):
            _checked(
                condition=cached.find_one({"_id": document_id}) == document,
                reason="post-invalidation read returned wrong data",
            )
        after_refresh = manager.cache_core.snapshot()
        _checked(
            condition=_delta(before_refresh, after_refresh, "misses")
            == _INVALIDATION_ENTRIES,
            reason="some targeted entries survived invalidation",
        )
        _checked(
            condition=_delta(before_refresh, after_refresh, "hits") == 0,
            reason="some targeted entries survived invalidation",
        )
        return elapsed


def run_case(uri: str, case: str, profile_name: str) -> float:
    profile = next((item for item in PROFILES if item.name == profile_name), None)
    if profile is None or case not in CASE_NAMES:
        raise ValueError("unknown guard case or document profile")
    with _seeded_collection(uri, profile) as (client, documents):
        if case == "async_hit":
            return asyncio.run(_async_hit(uri, documents))
        cases = {
            "sync_hit": _sync_hit,
            "find_admission": _find_admission,
            "invalidation": _invalidation,
        }
        return cases[case](client, documents)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one bounded guard case")
    parser.add_argument("--uri", required=True)
    parser.add_argument("--case", required=True, choices=CASE_NAMES)
    parser.add_argument(
        "--profile", required=True, choices=[profile.name for profile in PROFILES]
    )
    arguments = parser.parse_args()
    elapsed_seconds = run_case(arguments.uri, arguments.case, arguments.profile)
    print(json.dumps({"elapsed_seconds": elapsed_seconds}))


if __name__ == "__main__":
    main()
