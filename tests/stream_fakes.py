from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from bson.codec_options import CodecOptions

from client_query_cache._types import BsonDict, NonNegativeInt

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from pymongo.asynchronous.database import AsyncDatabase
    from pymongo.synchronous.database import Database


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
        self.client = SimpleNamespace(
            server_info=lambda: {
                "version": ".".join(str(part) for part in (version_array or [8, 0, 4])),
                "versionArray": version_array or [8, 0, 4, 0],
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
            server_info=self._make_server_info(version_array or [8, 0, 4])
        )
        self._script = list(script)
        self.watch_calls: list[dict[str, object]] = []
        self._before_watch = before_watch

    @staticmethod
    def _make_server_info(
        version_array: list[NonNegativeInt],
    ) -> Callable[[], object]:
        async def server_info() -> BsonDict:  # noqa: RUF029
            return {
                "version": ".".join(str(part) for part in version_array),
                "versionArray": version_array,
            }

        return server_info

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
