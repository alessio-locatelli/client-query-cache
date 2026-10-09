from __future__ import annotations

import argparse
import asyncio
import cProfile
import importlib
import inspect
import json
import logging
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock

from pymongo.errors import ConnectionFailure

from client_query_cache._core.manager import CacheCore
from client_query_cache._types import NonNegativeFloat, NonNegativeInt
from client_query_cache.asynchronous.streams import (
    ChangeStreamCoordinator as AsyncCoordinator,
)
from client_query_cache.synchronous.streams import ChangeStreamCoordinator
from tests.stream_fakes import (
    AsyncScriptedDatabase,
    AsyncScriptedStream,
    ScriptedDatabase,
    ScriptedStream,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

ACTIVATIONS = 10_000
WARMUP_BATCHES = 2
MEASURED_BATCHES = 20
GATE_SECONDS = 0.1


class Warnings(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def emit(self, _record: logging.LogRecord) -> None:
        self.count += 1


@dataclass(frozen=True, slots=True)
class Measurement:
    mode: str
    source: str
    healthy_seconds: NonNegativeFloat
    failed_seconds: NonNegativeFloat
    failure_attempts: NonNegativeInt
    failure_warnings: NonNegativeInt
    b_independent: bool
    b_seconds: NonNegativeFloat


def _batch_sync(coordinator: ChangeStreamCoordinator, name: str) -> NonNegativeFloat:
    started = time.perf_counter()
    for _ in range(ACTIVATIONS):
        coordinator.activate_database(name)
    return time.perf_counter() - started


async def _batch_async(coordinator: AsyncCoordinator, name: str) -> NonNegativeFloat:
    started = time.perf_counter()
    for _ in range(ACTIVATIONS):
        await coordinator.activate_database(name)
    return time.perf_counter() - started


def measure_sync(profile: Path | None, warnings: Warnings) -> Measurement:
    failed = ScriptedDatabase(
        "failed", [ConnectionFailure("startup unavailable")] * ACTIVATIONS
    )
    client = Mock()
    client.__getitem__ = Mock(
        side_effect={
            "healthy": ScriptedDatabase("healthy", [ScriptedStream([])]),
            "failed": failed,
        }.__getitem__
    )
    coordinator = ChangeStreamCoordinator(client, CacheCore())
    try:
        assert coordinator.activate_database("healthy") is not None
        samples = [
            _batch_sync(coordinator, "healthy")
            for _ in range(WARMUP_BATCHES + MEASURED_BATCHES)
        ]
        if profile is not None:
            profiler = cProfile.Profile()
            profiler.runcall(_batch_sync, coordinator, "healthy")
            profiler.dump_stats(str(profile))
        failed_seconds = _batch_sync(coordinator, "failed")
    finally:
        coordinator.close()
    failure_warnings = warnings.count
    assert failure_warnings == len(failed.watch_calls)
    entered = threading.Event()
    release = threading.Event()

    def pause(_index: NonNegativeInt) -> None:
        entered.set()
        release.wait()

    client.__getitem__ = Mock(
        side_effect={
            "a": ScriptedDatabase("a", [ScriptedStream([])], before_watch=pause),
            "b": ScriptedDatabase("b", [ScriptedStream([])]),
        }.__getitem__
    )
    coordinator = ChangeStreamCoordinator(client, CacheCore())
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(coordinator.activate_database, "a")
            entered.wait()
            started = time.perf_counter()

            def activate_b() -> NonNegativeFloat:
                assert coordinator.activate_database("b") is not None
                return time.perf_counter() - started

            second = executor.submit(activate_b)
            try:
                time.sleep(GATE_SECONDS)
                independent = second.done()
            finally:
                release.set()
            first.result()
            b_seconds = second.result()
    finally:
        coordinator.close()
    return Measurement(
        "synchronous",
        inspect.getfile(ChangeStreamCoordinator),
        statistics.median(samples[WARMUP_BATCHES:]),
        failed_seconds,
        len(failed.watch_calls),
        failure_warnings,
        independent,
        b_seconds,
    )


async def measure_async(profile: Path | None, warnings: Warnings) -> Measurement:
    failed = AsyncScriptedDatabase(
        "failed", [ConnectionFailure("startup unavailable")] * ACTIVATIONS
    )
    client = Mock()
    client.__getitem__ = Mock(
        side_effect={
            "healthy": AsyncScriptedDatabase("healthy", [AsyncScriptedStream([])]),
            "failed": failed,
        }.__getitem__
    )
    coordinator = AsyncCoordinator(client, CacheCore())
    try:
        assert await coordinator.activate_database("healthy") is not None
        samples = [
            await _batch_async(coordinator, "healthy")
            for _ in range(WARMUP_BATCHES + MEASURED_BATCHES)
        ]
        if profile is not None:
            profiler = cProfile.Profile()
            profiler.enable()
            await _batch_async(coordinator, "healthy")
            profiler.disable()
            profiler.dump_stats(str(profile))
        failed_seconds = await _batch_async(coordinator, "failed")
    finally:
        await coordinator.close()
    failure_warnings = warnings.count
    assert failure_warnings == len(failed.watch_calls)
    entered = threading.Event()
    release = threading.Event()

    async def pause(_index: NonNegativeInt) -> None:
        entered.set()
        await asyncio.to_thread(release.wait)

    client.__getitem__ = Mock(
        side_effect={
            "a": AsyncScriptedDatabase(
                "a", [AsyncScriptedStream([])], before_watch=pause
            ),
            "b": AsyncScriptedDatabase("b", [AsyncScriptedStream([])]),
        }.__getitem__
    )
    coordinator = AsyncCoordinator(client, CacheCore())
    try:
        first = asyncio.create_task(coordinator.activate_database("a"))
        await asyncio.to_thread(entered.wait)
        started = time.perf_counter()

        async def activate_b() -> NonNegativeFloat:
            assert await coordinator.activate_database("b") is not None
            return time.perf_counter() - started

        second = asyncio.create_task(activate_b())
        try:
            await asyncio.sleep(GATE_SECONDS)
            independent = second.done()
        finally:
            release.set()
        _, b_seconds = await asyncio.gather(first, second)
    finally:
        await coordinator.close()
    return Measurement(
        "asynchronous",
        inspect.getfile(AsyncCoordinator),
        statistics.median(samples[WARMUP_BATCHES:]),
        failed_seconds,
        len(failed.watch_calls),
        failure_warnings,
        independent,
        b_seconds,
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Measure scripted stream startup coordination."
    )
    parser.add_argument("mode", choices=("synchronous", "asynchronous"))
    parser.add_argument("--profile", type=Path)
    args = parser.parse_args(argv)
    logger = logging.getLogger(f"client_query_cache.{args.mode}.streams")
    warnings = Warnings()
    previous_handlers, previous_propagation = logger.handlers, logger.propagate
    logger.handlers = [warnings]
    logger.propagate = False
    try:
        measurement = (
            asyncio.run(measure_async(args.profile, warnings))
            if args.mode == "asynchronous"
            else measure_sync(args.profile, warnings)
        )
    finally:
        logger.handlers = previous_handlers
        logger.propagate = previous_propagation
    print(json.dumps(asdict(measurement)))


if __name__ == "__main__":
    # The baseline predates the initial-startup retry policy.
    try:
        activation = importlib.import_module(
            "client_query_cache._core.stream_activation"
        )
    except ModuleNotFoundError as error:
        if error.name != "client_query_cache._core.stream_activation":
            raise
    else:
        activation.__dict__["monotonic"] = lambda: 10.0
    main()
