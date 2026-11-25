from __future__ import annotations

import asyncio
import logging
import random
import threading
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from bson.codec_options import CodecOptions

from client_query_cache._core.stream_events import route_change_event
from client_query_cache._core.stream_health import RetryBackoff
from client_query_cache._core.stream_options import MINIMUM_SERVER_VERSION
from client_query_cache._types import BsonDict, NonNegativeFloat, NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import pytest
    from pymongo.asynchronous.database import AsyncDatabase
    from pymongo.synchronous.database import Database

    from client_query_cache._core.contracts import LocalCacheCore

SUPPORTED_SERVER_VERSION: list[NonNegativeInt] = [*MINIMUM_SERVER_VERSION, 0]
FAILING_MARKER = "fail"


@dataclass(slots=True)
class RecordingBackoff(RetryBackoff):
    attempts: list[NonNegativeInt] = field(default_factory=list)

    def next_delay(
        self,
        random_uniform: Callable[
            [NonNegativeFloat, NonNegativeFloat], NonNegativeFloat
        ] = random.uniform,
    ) -> NonNegativeFloat:
        self.attempts.append(self._attempt)
        return super().next_delay(random_uniform)


def inject_routing_failure(
    monkeypatch: pytest.MonkeyPatch, streams_module: str
) -> RuntimeError:
    failure = RuntimeError("injected routing failure")

    def fail_marked_events(
        cache: LocalCacheCore,
        database: str,
        event: BsonDict,
        **kwargs: Any,  # noqa: ANN401 - Forward the router's keyword options.
    ) -> bool:
        token = event["_id"]
        assert isinstance(token, dict)
        if token["tok"].startswith(FAILING_MARKER):
            raise failure
        return route_change_event(cache, database, event, **kwargs)

    monkeypatch.setattr(f"{streams_module}.route_change_event", fail_marked_events)
    return failure


def worker_failures(
    caplog: pytest.LogCaptureFixture, streams_module: str
) -> list[BaseException | None]:
    return [
        None if record.exc_info is None else record.exc_info[1]
        for record in caplog.records
        if record.name == streams_module and record.levelno == logging.ERROR
    ]


def _make_server_info(
    version_array: list[NonNegativeInt],
) -> Callable[[], object]:
    async def server_info() -> BsonDict:  # noqa: RUF029 - Satisfy the awaited callback interface.
        return {
            "version": ".".join(str(part) for part in version_array),
            "versionArray": version_array,
        }

    return server_info


class ScriptedStream:
    __slots__ = ("_close_error", "_closed_event", "_events", "closed", "resume_token")

    def __init__(
        self, events: list[object], *, close_error: Exception | None = None
    ) -> None:
        self._events = list(events)
        self._close_error = close_error
        self.resume_token: BsonDict | None = None
        self.closed = False
        self._closed_event = threading.Event()

    def next(self) -> BsonDict:
        if not self._events:
            self._closed_event.wait()
            raise StopIteration
        item = self._events.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, dict)
        try:
            resume_token = item["_id"]
        except KeyError:
            resume_token = self.resume_token
        self.resume_token = resume_token
        return item

    def close(self) -> None:
        self.closed = True
        self._closed_event.set()
        if self._close_error is not None:
            raise self._close_error


class ScriptedDatabase:
    __slots__ = (
        "_before_watch",
        "_script",
        "client",
        "codec_options",
        "name",
        "watch_calls",
    )

    def __init__(
        self,
        name: str,
        script: list[object],
        *,
        version_array: list[NonNegativeInt] | None = None,
        before_watch: Callable[[NonNegativeInt], None] | None = None,
    ) -> None:
        self.name = name
        self.codec_options: CodecOptions[Any] = CodecOptions()
        server_version = version_array or SUPPORTED_SERVER_VERSION
        self.client = SimpleNamespace(
            server_info=lambda: {
                "version": ".".join(map(str, server_version)),
                "versionArray": server_version,
            }
        )
        self._script = list(script)
        self.watch_calls: list[dict[str, object]] = []
        self._before_watch = before_watch

    def watch(self, _pipeline: object, **kwargs: object) -> object:
        index = len(self.watch_calls)
        self.watch_calls.append(kwargs)
        if self._before_watch is not None:
            self._before_watch(index)
        item = self._script[index]
        if isinstance(item, Exception):
            raise item
        return item


def as_database(fake: ScriptedDatabase) -> Database[Any]:
    return cast("Database[Any]", fake)


class AsyncScriptedStream:
    __slots__ = ("_close_error", "_closed_event", "_events", "closed", "resume_token")

    def __init__(
        self, events: list[object], *, close_error: Exception | None = None
    ) -> None:
        self._events = list(events)
        self._close_error = close_error
        self.resume_token: BsonDict | None = None
        self.closed = False
        self._closed_event = asyncio.Event()

    async def next(self) -> BsonDict:
        if not self._events:
            await self._closed_event.wait()
        item = self._events.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, dict)
        try:
            resume_token = item["_id"]
        except KeyError:
            resume_token = self.resume_token
        self.resume_token = resume_token
        return item

    async def close(self) -> None:
        self.closed = True
        self._closed_event.set()
        if self._close_error is not None:
            raise self._close_error


class AsyncScriptedDatabase:
    __slots__ = (
        "_before_watch",
        "_script",
        "client",
        "codec_options",
        "name",
        "watch_calls",
    )

    def __init__(
        self,
        name: str,
        script: list[object],
        *,
        version_array: list[NonNegativeInt] | None = None,
        before_watch: Callable[[NonNegativeInt], Awaitable[None]] | None = None,
    ) -> None:
        self.name = name
        self.codec_options: CodecOptions[Any] = CodecOptions()
        self.client = SimpleNamespace(
            server_info=_make_server_info(version_array or SUPPORTED_SERVER_VERSION)
        )
        self._script = list(script)
        self.watch_calls: list[dict[str, object]] = []
        self._before_watch = before_watch

    async def watch(self, _pipeline: object, **kwargs: object) -> object:
        index = len(self.watch_calls)
        self.watch_calls.append(kwargs)
        if self._before_watch is not None:
            await self._before_watch(index)
        item = self._script[index]
        if isinstance(item, Exception):
            raise item
        return item


def as_async_database(fake: AsyncScriptedDatabase) -> AsyncDatabase[Any]:
    return cast("AsyncDatabase[Any]", fake)
