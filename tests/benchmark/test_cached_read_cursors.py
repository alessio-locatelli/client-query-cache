# Inspect candidate ownership while measuring cursor allocations.
from __future__ import annotations

import cProfile
import io
import json
import pstats
import statistics
import tracemalloc
from time import perf_counter, process_time
from typing import TYPE_CHECKING, Any, Literal

import pytest
from pymongo import AsyncMongoClient

from client_query_cache._core.canonical import canonicalize
from client_query_cache._core.codec import encode_value
from client_query_cache._core.cursor_capture import CursorCapture
from client_query_cache._core.find_reads import find_read_shape
from client_query_cache._core.keys import NamespaceId
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
    from collections.abc import Awaitable, Generator, Mapping

    from bson.codec_options import CodecOptions
    from pymongo.asynchronous.command_cursor import AsyncCommandCursor

    from client_query_cache._core.entries import LookupResult
    from client_query_cache._core.find_reads import FindReadShape
    from client_query_cache._core.manager import CacheCore
    from tests.cursor_fixtures import Binding, Document, ReadCommands, View

pytestmark = [pytest.mark.benchmark, pytest.mark.timeout(180)]
CACHED_CURSORS = (
    CachedCursor,
    AsyncCachedCursor,
    CachedCommandCursor,
    AsyncCachedCommandCursor,
)
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


@pytest.fixture(autouse=True)
def release_measurement_tracing() -> Generator[None]:
    yield
    tracemalloc.stop()


def api_name(view: View) -> Literal["sync", "async"]:
    return "async" if isinstance(view.raw.database.client, AsyncMongoClient) else "sync"


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
        elapsed: list[float] = []
        first_document: list[float] = []
        origin_counts: list[dict[str, int]] = []
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
            if isinstance(cursor, CACHED_CURSORS) and cursor._capture is not None:
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
            if isinstance(cursor, CACHED_CURSORS):
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
                    "api": api_name(view),
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
    with cProfile.Profile() as profiler:
        assert await materialize(construct("cold")) == documents
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
        if isinstance(cursor, CACHED_CURSORS) and cursor._capture is not None
    )
    assert retained <= PARTIAL_CURSORS * limit
    capture_ids = {
        id(cursor._capture)
        for cursor in partial
        if isinstance(cursor, CACHED_CURSORS) and cursor._capture is not None
    }
    for cursor in partial:
        await close_cursor(cursor)
        assert isinstance(cursor, CACHED_CURSORS)
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


def exact_find_lookup(
    core: CacheCore,
    namespace: NamespaceId,
    shape: FindReadShape,
    *,
    codec_options: CodecOptions[Any] | None = None,
) -> LookupResult:
    return core.lookup_namespace(
        namespace, shape.discriminator, codec_options=codec_options
    )


type FindLimitPhase = Literal["cold", "exact", "compatible", "incompatible", "bypass"]

FIND_LIMIT_CURSORS = pytest.mark.parametrize(
    "cursors",
    tuple(
        (api, 240, payload, 1024 * 1024)
        for api in ("sync", "async")
        for payload in (64, 4096)
    ),
    indirect=True,
    ids=["sync-small", "sync-near-cap", "async-small", "async-near-cap"],
)


async def measure_find_limit_phase(
    cursors: Binding,
    monkeypatch: pytest.MonkeyPatch,
    *,
    phase: FindLimitPhase,
    family_size: Literal[0, 1, 16],
    unrelated: Literal[0, 128],
    exact_only: bool = False,
    descending: bool = False,
) -> None:
    view = cursors["view"]
    core = view.database.manager.cache_core
    namespace = view._namespace()
    source_limits = tuple(range(240 - family_size + 1, 241)) if family_size else (0,)
    if descending:
        source_limits = tuple(reversed(source_limits))
    if exact_only:
        monkeypatch.setattr(type(core), "lookup_find", exact_find_lookup)
    requested = {
        "cold": 10,
        "exact": max(source_limits),
        "compatible": 10,
        "incompatible": -241,
        "bypass": 10,
    }[phase]
    expected = await materialize(view.raw.find({}, sort=[("_id", 1)], limit=requested))
    timings: list[float] = []
    command_counts: list[dict[str, int]] = []  # One count per execution.
    peaks: list[int] = []
    resident = core.snapshot()
    for repetition in range(REPETITIONS):
        core.clear_namespace(namespace)
        with monkeypatch.context() as warmup:
            warmup.setattr(type(core), "lookup_find", exact_find_lookup)
            for source_limit in source_limits:
                if phase != "cold":
                    await materialize(
                        view.find({}, sort=[("_id", 1)], limit=source_limit)
                    )
        assert sum(
            len(bucket) for bucket in core._namespace(namespace).find_families.values()
        ) == (0 if phase == "cold" else len(source_limits))
        for index in range(unrelated):
            unrelated_namespace = (
                namespace
                if index % 2
                else NamespaceId(namespace.database, f"unrelated-{index}")
            )
            core.admit_namespace(
                core.capture_namespace_generation(unrelated_namespace),
                ("unrelated", index),
                [],
            )
        resident = core.snapshot()
        cursors["commands"].commands.clear()
        options = {"batch_size": 7} if phase == "bypass" else {}
        if repetition == 0:
            tracemalloc.start()
        started = perf_counter()
        assert (
            await materialize(
                view.find({}, sort=[("_id", 1)], limit=requested, **options)
            )
            == expected
        )
        timings.append(perf_counter() - started)
        command_counts.append(counts(cursors["commands"]))
        if repetition == 0:
            _, peak = tracemalloc.get_traced_memory()
            peaks.append(peak)
            tracemalloc.stop()
        if phase == "exact" or (phase == "compatible" and not exact_only):
            assert not any(command_counts[-1].values())
            assert core.snapshot().used_bytes == resident.used_bytes
            assert core.snapshot().entry_count == resident.entry_count
        elif phase == "compatible":
            assert command_counts[-1]["find"] == 1
    print(
        json.dumps(
            {
                "limit_workload": True,
                "api": api_name(view),
                "payload": len(cursors["documents"][0]["payload"]),
                "phase": phase,
                "source_limit": min(source_limits),
                "admission_order": "descending" if descending else "ascending",
                "lookup_mode": "exact-only" if exact_only else "compatible",
                "request_limit": requested,
                "family_size": family_size,
                "unrelated": unrelated,
                "total_us": round(statistics.median(timings[1:]) * 1e6, 1),
                "heap_peak": peaks[0],
                "resident_before": resident.used_bytes,
                "resident_after": core.snapshot().used_bytes,
                "source_tokens": sum(
                    len(bucket)
                    for state in core._namespaces.values()
                    for bucket in state.find_families.values()
                ),
                "origin_per_read": command_counts[-1],
            }
        )
    )
    if phase == "compatible" and family_size == 1 and unrelated == 0 and not exact_only:
        with cProfile.Profile() as profiler:
            for _ in range(REPETITIONS):
                await materialize(view.find({}).sort("_id").limit(requested))
        profile = io.StringIO()
        pstats.Stats(profiler, stream=profile).sort_stats("tottime").print_stats(8)
        print(profile.getvalue())


@FIND_LIMIT_CURSORS
@pytest.mark.parametrize(
    "family_size", [0, 1, 16], ids=["unlimited", "one-limit", "many-limits"]
)
@pytest.mark.parametrize("unrelated", [0, 128], ids=["isolated", "unrelated"])
async def test_find_limit_measurements(
    cursors: Binding,
    monkeypatch: pytest.MonkeyPatch,
    *,
    family_size: Literal[0, 1, 16],
    unrelated: Literal[0, 128],
) -> None:
    for phase in ("cold", "exact", "incompatible", "bypass"):
        await measure_find_limit_phase(
            cursors,
            monkeypatch,
            phase=phase,
            family_size=family_size,
            unrelated=unrelated,
        )


@FIND_LIMIT_CURSORS
@pytest.mark.parametrize(
    ("family_size", "unrelated", "exact_only", "descending"),
    [
        (1, 0, True, False),
        (0, 0, False, False),
        (1, 0, False, False),
        (16, 0, False, False),
        (16, 0, False, True),
        (1, 128, False, False),
        (16, 128, False, False),
        (16, 128, False, True),
    ],
    ids=[
        "exact-only-control",
        "unlimited",
        "one-limit",
        "many-ascending",
        "many-descending",
        "one-limit-unrelated",
        "many-ascending-unrelated",
        "many-descending-unrelated",
    ],
)
async def test_find_limit_prefix_measurements(
    cursors: Binding,
    monkeypatch: pytest.MonkeyPatch,
    *,
    family_size: Literal[0, 1, 16],
    unrelated: Literal[0, 128],
    exact_only: bool,
    descending: bool,
) -> None:
    await measure_find_limit_phase(
        cursors,
        monkeypatch,
        phase="compatible",
        family_size=family_size,
        unrelated=unrelated,
        exact_only=exact_only,
        descending=descending,
    )


@pytest.mark.parametrize("predicates", [2, 32], ids=["small", "large"])
def test_scalar_filter_key_cost(predicates: Literal[2, 32]) -> None:
    filter_document = {f"field-{index}": None for index in range(predicates)}
    for order, selected in (
        ("exact", filter_document),
        ("permuted", dict(reversed(tuple(filter_document.items())))),
    ):
        timings: list[float] = []
        for _ in range(REPETITIONS):
            started = process_time()
            for _ in range(100):
                canonicalize(
                    find_read_shape(
                        selected, None, {"_id": 1}, 0, 0, collation=None, codec=None
                    ).discriminator
                )
            timings.append((process_time() - started) / 100)
        print(
            json.dumps(
                {
                    "filter_key_order": order,
                    "predicates": predicates,
                    "cpu_us": round(statistics.median(timings) * 1e6, 1),
                }
            )
        )
