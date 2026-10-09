from __future__ import annotations

import asyncio
import inspect
import time
from typing import TYPE_CHECKING

import pytest

from client_query_cache._types import PositiveFloat

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def wait_until(predicate: Callable[[], bool], *, timeout: PositiveFloat = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    pytest.fail(  # pragma: no cover (test timeout diagnostic)
        "condition was not met within the timeout"
    )


async def _poll(predicate: Callable[[], bool | Awaitable[bool]]) -> None:
    while True:
        satisfied = predicate()
        if inspect.isawaitable(satisfied):
            satisfied = await satisfied
        if satisfied:
            return
        await asyncio.sleep(0.05)


async def wait_until_async(
    predicate: Callable[[], bool | Awaitable[bool]],
    *,
    timeout_seconds: PositiveFloat = 15.0,
) -> None:
    try:
        async with asyncio.timeout(timeout_seconds):
            await _poll(predicate)
    except TimeoutError:  # pragma: no cover (test timeout diagnostic)
        pytest.fail("condition was not met within the timeout")


async def _value_satisfies[T](
    invoke: Callable[[], Awaitable[T]], predicate: Callable[[T], bool]
) -> bool:
    return predicate(await invoke())


async def wait_until_value_async[T](
    invoke: Callable[[], Awaitable[T]], predicate: Callable[[T], bool]
) -> None:
    await wait_until_async(lambda: _value_satisfies(invoke, predicate))
