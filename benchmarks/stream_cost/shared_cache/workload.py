from __future__ import annotations

import asyncio
import queue
import random
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from benchmarks.stream_cost.measurement import scalar_latency_distribution

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from client_query_cache._types import (
        NonNegativeFloat,
        NonNegativeInt,
        PositiveFloat,
        PositiveInt,
    )

type Payload = dict[str, object]

_SLEEP_SLICE_SECONDS: Final = 1.0
_STOP: Final = -1


def key_order(seed: int, size: PositiveInt) -> tuple[NonNegativeInt, ...]:
    keys = list(range(size))
    random.Random(seed).shuffle(keys)
    return tuple(keys)


@dataclass(frozen=True, slots=True)
class Assignment:
    worker: NonNegativeInt
    workers: PositiveInt
    rate: PositiveFloat | None
    requests: NonNegativeInt
    keys: tuple[NonNegativeInt, ...]
    offset: NonNegativeInt = 0

    def ordinals(self) -> range:
        return range(self.worker, self.requests, self.workers)

    def key(self, ordinal: NonNegativeInt) -> NonNegativeInt:
        return self.keys[(ordinal + self.offset) % len(self.keys)]

    def due(self, start: NonNegativeFloat, ordinal: NonNegativeInt) -> NonNegativeFloat:
        assert self.rate is not None
        return start + ordinal / self.rate


@dataclass(slots=True)
class LoopResult:
    offered: NonNegativeInt = 0
    completed: NonNegativeInt = 0
    completed_in_window: NonNegativeInt = 0
    errors: NonNegativeInt = 0
    overflow: NonNegativeInt = 0
    outstanding_at_end: NonNegativeInt = 0
    max_dispatch_lateness: NonNegativeFloat = 0.0
    elapsed: NonNegativeFloat = 0.0
    latencies: list[NonNegativeFloat] = field(default_factory=list)
    error_types: dict[str, NonNegativeInt] = field(default_factory=dict)

    def record_error(self, error: BaseException) -> None:
        self.errors += 1
        name = type(error).__name__
        try:
            self.error_types[name] += 1
        except KeyError:
            self.error_types[name] = 1

    def summary(self) -> Payload:
        return {
            "offered": self.offered,
            "completed": self.completed,
            "completed_in_window": self.completed_in_window,
            "errors": self.errors,
            "error_types": self.error_types,
            "overflow": self.overflow,
            "outstanding_at_end": self.outstanding_at_end,
            "max_dispatch_lateness": self.max_dispatch_lateness,
            "elapsed": self.elapsed,
            "latency": scalar_latency_distribution(self.latencies)
            if self.latencies
            else None,
        }


def _sleep_until(deadline: NonNegativeFloat) -> None:
    while (remaining := deadline - time.monotonic()) > 0:
        time.sleep(min(remaining, _SLEEP_SLICE_SECONDS))


async def _async_sleep_until(deadline: NonNegativeFloat) -> None:
    while (remaining := deadline - time.monotonic()) > 0:  # noqa: ASYNC110 - Bound timer slack, not a polled condition.
        await asyncio.sleep(min(remaining, _SLEEP_SLICE_SECONDS))


def open_loop_sync(
    assignment: Assignment,
    start: NonNegativeFloat,
    read: Callable[[NonNegativeInt], object],
    *,
    concurrency: PositiveInt,
    outstanding_limit: PositiveInt,
    drain_seconds: PositiveFloat,
    record: bool,
) -> LoopResult:
    loop_result = LoopResult()
    pending: queue.SimpleQueue[tuple[NonNegativeInt, NonNegativeFloat]] = (
        queue.SimpleQueue()
    )
    lock = threading.Lock()
    outstanding = 0

    def execute() -> None:
        nonlocal outstanding
        while True:
            ordinal, due = pending.get()
            if ordinal == _STOP:
                return
            try:
                read(assignment.key(ordinal))
            except Exception as error:  # noqa: BLE001 - Every failed read is reported.
                with lock:
                    outstanding -= 1
                    loop_result.record_error(error)
                continue
            finished = time.monotonic()
            with lock:
                outstanding -= 1
                loop_result.completed += 1
                if record:
                    loop_result.latencies.append(finished - due)

    executors = tuple(
        threading.Thread(target=execute, daemon=True) for _ in range(concurrency)
    )
    for executor in executors:
        executor.start()
    for ordinal in assignment.ordinals():
        due = assignment.due(start, ordinal)
        _sleep_until(due)
        loop_result.offered += 1
        loop_result.max_dispatch_lateness = max(
            loop_result.max_dispatch_lateness, time.monotonic() - due
        )
        with lock:
            if outstanding >= outstanding_limit:
                loop_result.overflow += 1
                continue
            outstanding += 1
        pending.put((ordinal, due))
    end = start + assignment.requests / assignment.rate if assignment.rate else start
    _sleep_until(end)
    with lock:
        loop_result.outstanding_at_end = outstanding
        loop_result.completed_in_window = loop_result.completed
    for _ in executors:
        pending.put((_STOP, 0.0))
    deadline = time.monotonic() + drain_seconds
    for executor in executors:
        executor.join(max(0.0, deadline - time.monotonic()))
    loop_result.elapsed = time.monotonic() - start
    return loop_result


async def open_loop_async(
    assignment: Assignment,
    start: NonNegativeFloat,
    read: Callable[[NonNegativeInt], Awaitable[object]],
    *,
    concurrency: PositiveInt,
    outstanding_limit: PositiveInt,
    drain_seconds: PositiveFloat,
    record: bool,
) -> LoopResult:
    loop_result = LoopResult()
    pending: asyncio.Queue[tuple[NonNegativeInt, NonNegativeFloat]] = asyncio.Queue()
    outstanding = 0

    async def execute() -> None:
        nonlocal outstanding
        while True:
            ordinal, due = await pending.get()
            if ordinal == _STOP:
                return
            try:
                await read(assignment.key(ordinal))
            except Exception as error:  # noqa: BLE001 - Every failed read is reported.
                outstanding -= 1
                loop_result.record_error(error)
                continue
            outstanding -= 1
            loop_result.completed += 1
            if record:
                loop_result.latencies.append(time.monotonic() - due)

    executors = tuple(asyncio.create_task(execute()) for _ in range(concurrency))
    for ordinal in assignment.ordinals():
        due = assignment.due(start, ordinal)
        if due > time.monotonic():
            await _async_sleep_until(due)
        loop_result.offered += 1
        loop_result.max_dispatch_lateness = max(
            loop_result.max_dispatch_lateness, time.monotonic() - due
        )
        if outstanding >= outstanding_limit:
            loop_result.overflow += 1
            continue
        outstanding += 1
        pending.put_nowait((ordinal, due))
    end = start + assignment.requests / assignment.rate if assignment.rate else start
    await _async_sleep_until(end)
    loop_result.outstanding_at_end = outstanding
    loop_result.completed_in_window = loop_result.completed
    for _ in executors:
        pending.put_nowait((_STOP, 0.0))
    _done, unfinished = await asyncio.wait(executors, timeout=drain_seconds)
    for task in unfinished:
        task.cancel()
    loop_result.elapsed = time.monotonic() - start
    return loop_result


def closed_loop_sync(
    assignment: Assignment,
    start: NonNegativeFloat,
    seconds: PositiveFloat,
    read: Callable[[NonNegativeInt], object],
    concurrency: PositiveInt,
) -> LoopResult:
    loop_result = LoopResult()
    lock = threading.Lock()
    ordinals = iter(assignment.ordinals())
    end = start + seconds
    finished_at = [start]

    def execute() -> None:
        while time.monotonic() < end:
            with lock:
                ordinal = next(ordinals, None)
            if ordinal is None:
                return
            issued = time.monotonic()  # pytriage: TR11 (latency boundary)
            try:
                read(assignment.key(ordinal))
            except Exception as error:  # noqa: BLE001 - Every failed read is reported.
                with lock:
                    loop_result.record_error(error)
                continue
            finished = time.monotonic()
            with lock:
                loop_result.completed += 1
                loop_result.latencies.append(finished - issued)
                finished_at[0] = max(finished_at[0], finished)

    _sleep_until(start)
    executors = tuple(
        threading.Thread(target=execute, daemon=True) for _ in range(concurrency)
    )
    for executor in executors:
        executor.start()
    for executor in executors:
        executor.join()
    loop_result.offered = loop_result.completed + loop_result.errors
    loop_result.completed_in_window = loop_result.completed
    loop_result.elapsed = min(seconds, finished_at[0] - start)
    return loop_result


async def closed_loop_async(
    assignment: Assignment,
    start: NonNegativeFloat,
    seconds: PositiveFloat,
    read: Callable[[NonNegativeInt], Awaitable[object]],
    concurrency: PositiveInt,
) -> LoopResult:
    loop_result = LoopResult()
    ordinals = iter(assignment.ordinals())
    end = start + seconds
    finished_at = start

    async def execute() -> None:
        nonlocal finished_at
        while time.monotonic() < end:
            ordinal = next(ordinals, None)
            if ordinal is None:
                return
            issued = time.monotonic()  # pytriage: TR11 (latency boundary)
            try:
                await read(assignment.key(ordinal))
            except Exception as error:  # noqa: BLE001 - Every failed read is reported.
                loop_result.record_error(error)
                continue
            finished = time.monotonic()
            loop_result.completed += 1
            loop_result.latencies.append(finished - issued)
            finished_at = max(finished_at, finished)

    await _async_sleep_until(start)
    await asyncio.gather(*(execute() for _ in range(concurrency)))
    loop_result.offered = loop_result.completed + loop_result.errors
    loop_result.completed_in_window = loop_result.completed
    loop_result.elapsed = min(seconds, finished_at - start)
    return loop_result
