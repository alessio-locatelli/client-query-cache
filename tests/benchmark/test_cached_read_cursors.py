# Inspect candidate ownership while measuring cursor allocations.
from __future__ import annotations

import cProfile
import io
import json
import pstats
import statistics
import tracemalloc
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal

import pytest
from pymongo import AsyncMongoClient

from client_query_cache._core.codec import encode_value
from client_query_cache._core.cursor_capture import CursorCapture
from client_query_cache.asynchronous.cursors import (
    CachedCommandCursor as AsyncCachedCommandCursor,
)
from client_query_cache.asynchronous.cursors import CachedCursor as AsyncCachedCursor
from client_query_cache.synchronous.cursors import CachedCommandCursor, CachedCursor
from tests.cursor_helpers import (
    ReadCursor,
    advance,
    close_cursor,
    live_capture_ids,
    materialize,
    resolve_cursor,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Mapping

    from pymongo.asynchronous.command_cursor import AsyncCommandCursor

    from tests.cursor_fixtures import Binding, Document, ReadCommands

pytestmark = [pytest.mark.benchmark, pytest.mark.timeout(180)]
REPETITIONS = 10
PARTIAL_CURSORS = 8
CONFIGURATIONS = (
    ("single", 10, 64, 1024 * 1024),
    ("multi-small", 240, 128, 1024 * 1024),
    ("multi-large", 240, 4096, 1024 * 1024),
    ("many", 4000, 1024, 8 * 1024 * 1024),
    ("capture-limit", 240, 4096, 32 * 1024),
    (
        "final-limit",
        1,
        64,
        135,
    ),  # One document fits its snapshot but not the stored list.
)


def counts(commands: ReadCommands) -> dict[str, int]:
    return {
        name: sum(name in command for command in commands.commands)
        for name in ("find", "aggregate", "getMore", "killCursors")
    }


@pytest.mark.parametrize(
    "cursors",
    [
        pytest.param((api, count, payload, limit), id=f"{api}-{name}")
        for api in ("sync", "async")
        for name, count, payload, limit in CONFIGURATIONS
    ],
    indirect=True,
)
@pytest.mark.parametrize("method", ["find", "aggregate"], ids=["find", "aggregate"])
async def test_cursor_measurements(
    cursors: Binding,
    method: Literal["find", "aggregate"],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = cursors["view"]
    core = view.database.manager.cache_core
    documents = cursors["documents"]
    limit = core.snapshot().max_entry_bytes
    can_admit = (
        sum(len(encode_value(document)) for document in documents) <= limit
        and len(encode_value(documents)) <= limit
    )

    def construct(
        phase: str,
    ) -> ReadCursor[Document] | Awaitable[AsyncCommandCursor[Document]]:
        collection = view.raw if phase == "native" else view
        if method == "find":
            if phase == "batch-bypass":
                return collection.find({}, sort=[("_id", 1)], batch_size=7)
            return collection.find({}, sort=[("_id", 1)])
        if phase == "batch-bypass":
            return collection.aggregate([{"$sort": {"_id": 1}}], batchSize=7)
        return collection.aggregate([{"$sort": {"_id": 1}}])

    original_append = CursorCapture.append
    for phase in ("native", "cold", "hit", "early-close", "batch-bypass"):
        if phase == "hit":
            if not can_admit:
                continue
            assert await materialize(construct("cold")) == documents
            assert core.snapshot().entry_count == 1
        elapsed: list[float] = []  # Filled by repetitions.
        first_document: list[float] = []  # Filled by repetitions.
        origin_counts: list[dict[str, int]] = []  # Filled by repetitions.
        retained_peak = 0
        before_hits = core.snapshot().hits
        for _ in range(REPETITIONS):
            if phase in {"cold", "early-close"}:
                core.clear_namespace(view._namespace())
            cursors["commands"].commands.clear()
            started = perf_counter()
            cursor = await resolve_cursor(construct(phase))
            first = await advance(cursor)
            first_document.append(perf_counter() - started)
            assert first == documents[0]
            if (
                isinstance(
                    cursor,
                    CachedCursor
                    | AsyncCachedCursor
                    | CachedCommandCursor
                    | AsyncCachedCommandCursor,
                )
                and cursor._capture is not None
            ):
                retained_peak = max(retained_peak, cursor._capture.retained_bytes)
                assert cursor._capture.retained_bytes <= limit
            if phase == "early-close":
                await close_cursor(cursor)
                assert core.snapshot().entry_count == 0
            else:
                assert await materialize(cursor) == documents[1:]
                if phase == "cold":
                    assert core.snapshot().entry_count == int(can_admit)
            elapsed.append(perf_counter() - started)
            origin_counts.append(counts(cursors["commands"]))
            if isinstance(
                cursor,
                CachedCursor
                | AsyncCachedCursor
                | CachedCommandCursor
                | AsyncCachedCommandCursor,
            ):
                assert cursor._capture is None
        hits = core.snapshot().hits - before_hits
        if phase in {"cold", "early-close"}:
            core.clear_namespace(view._namespace())
        retained_peak = 0

        def track_payload(capture: CursorCapture, document: Mapping[str, Any]) -> None:
            nonlocal retained_peak
            original_append(capture, document)
            retained_peak = max(retained_peak, capture.retained_bytes)
            assert capture.retained_bytes <= limit

        with monkeypatch.context() as hooks:
            hooks.setattr(CursorCapture, "append", track_payload)
            tracemalloc.start()
            measured = await resolve_cursor(construct(phase))
            if phase == "early-close":
                await advance(measured)
                await close_cursor(measured)
            else:
                assert await materialize(measured) == documents
            _, heap_peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        assert hits == (REPETITIONS if phase == "hit" else 0)
        if phase == "hit":
            assert all(sum(command.values()) == 0 for command in origin_counts)
        if phase == "early-close":
            assert all(command["getMore"] == 0 for command in origin_counts)
        print(
            json.dumps(
                {
                    "api": "async"
                    if isinstance(view.raw.database.client, AsyncMongoClient)
                    else "sync",
                    "method": method,
                    "count": len(documents),
                    "payload": len(documents[0]["payload"]),
                    "limit": limit,
                    "phase": phase,
                    "first_us": round(statistics.median(first_document) * 1e6, 1),
                    "total_us": round(statistics.median(elapsed) * 1e6, 1),
                    "heap_peak": heap_peak,
                    "retained_peak": retained_peak,
                    "hits": hits,
                    "origin_per_read": origin_counts[-1],
                }
            )
        )

    core.clear_namespace(view._namespace())
    profiler = cProfile.Profile()
    profiler.enable()
    assert await materialize(construct("cold")) == documents
    profiler.disable()
    profile = io.StringIO()
    pstats.Stats(profiler, stream=profile).sort_stats("tottime").print_stats(8)
    print(profile.getvalue())

    core.clear_namespace(view._namespace())
    tracemalloc.start()
    partial = [await resolve_cursor(construct("cold")) for _ in range(PARTIAL_CURSORS)]
    for cursor in partial:
        assert await materialize(cursor, min(50, len(documents))) == documents[:50]
    retained = sum(
        cursor._capture.retained_bytes
        for cursor in partial
        if isinstance(
            cursor,
            CachedCursor
            | AsyncCachedCursor
            | CachedCommandCursor
            | AsyncCachedCommandCursor,
        )
        and cursor._capture is not None
    )
    assert retained <= PARTIAL_CURSORS * limit
    capture_ids = {
        id(cursor._capture)
        for cursor in partial
        if isinstance(
            cursor,
            CachedCursor
            | AsyncCachedCursor
            | CachedCommandCursor
            | AsyncCachedCommandCursor,
        )
        and cursor._capture is not None
    }
    for cursor in partial:
        await close_cursor(cursor)
        assert isinstance(
            cursor,
            CachedCursor
            | AsyncCachedCursor
            | CachedCommandCursor
            | AsyncCachedCommandCursor,
        )
        assert cursor._capture is None
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert capture_ids.isdisjoint(live_capture_ids())
    print(
        json.dumps(
            {
                "concurrent_partial": PARTIAL_CURSORS,
                "retained": retained,
                "heap_peak": peak,
                "heap_after_close": current,
                "count": len(documents),
                "payload": len(documents[0]["payload"]),
            }
        )
    )
