from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

import bson
from bson.errors import BSONError
from pymongo.errors import OperationFailure, PyMongoError

from client_query_cache._core.errors import StreamLifecycleError, StreamStartupError
from client_query_cache._core.stream_events import (
    build_change_stream_pipeline,
    is_unresumable_change_stream_error,
    route_change_event,
)
from client_query_cache._core.stream_health import (
    RetryBackoff,
    StreamHealth,
    StreamHealthRegistry,
    StreamHealthSnapshot,
    StreamHealthStatus,
    public_stream_health,
)
from client_query_cache._core.stream_options import DEFAULT_MAX_AWAIT_TIME_MS

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pymongo import AsyncMongoClient
    from pymongo.asynchronous.change_stream import AsyncDatabaseChangeStream
    from pymongo.asynchronous.database import AsyncDatabase

    from client_query_cache._core.manager import CacheCore

MINIMUM_SERVER_VERSION = (8, 0)

logger = logging.getLogger(__name__)


class DatabaseStreamSupervisor:
    __slots__ = (
        "_backoff",
        "_cache",
        "_database",
        "_health",
        "_max_await_time_ms",
        "_resume_token",
        "_stop_event",
        "_stream",
        "_task",
    )

    def __init__(
        self,
        database: AsyncDatabase[Any],
        cache: CacheCore,
        *,
        backoff: RetryBackoff | None = None,
        max_await_time_ms: int = DEFAULT_MAX_AWAIT_TIME_MS,
    ) -> None:
        self._database = database
        self._cache = cache
        self._backoff = backoff if backoff is not None else RetryBackoff()
        self._max_await_time_ms = max_await_time_ms
        self._health = StreamHealth.STARTING
        self._stream: AsyncDatabaseChangeStream[Any] | None = None
        self._resume_token: Mapping[str, Any] | None = None
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._cache.set_database_available(self._database.name, available=False)

    @property
    def healthy(self) -> bool:
        return self._health is StreamHealth.HEALTHY

    def health_status(self) -> StreamHealthStatus:
        return public_stream_health(self._health)

    async def start(self) -> None:
        if self._health is not StreamHealth.STARTING:
            message = "start() may only be called once per supervisor instance"
            raise StreamLifecycleError(message)
        self._set_health(StreamHealth.CONNECTING)
        self._clear_namespaces_for_database()
        try:
            await self._ensure_server_supports_expanded_events()
            await self._open_stream(resume_token=None, use_start_after=False)
        except StreamStartupError:
            self._set_health(StreamHealth.CLOSED)
            raise
        except PyMongoError as exc:
            self._set_health(StreamHealth.CLOSED)
            message = (
                f"failed to open change stream for database {self._database.name!r}"
            )
            raise StreamStartupError(message) from exc
        except asyncio.CancelledError:
            self._set_health(StreamHealth.CLOSED)
            stream = self._stream
            if stream is not None:
                with contextlib.suppress(PyMongoError):
                    await stream.close()
            raise
        if self._stop_event.is_set():
            assert self._stream is not None
            with contextlib.suppress(PyMongoError):
                await self._stream.close()
            self._set_health(StreamHealth.CLOSED)
            message = "stop() was called while start() was still connecting"
            raise StreamLifecycleError(message)
        self._set_health(StreamHealth.HEALTHY)
        self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        self._stop_event.set()
        self._set_health(StreamHealth.CLOSED)
        task = self._task
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        stream = self._stream
        if stream is not None:
            try:
                await stream.close()
            except PyMongoError:
                logger.warning(
                    "change stream close failed during shutdown",
                    extra={"database": self._database.name},
                    exc_info=True,
                )
        self._set_health(StreamHealth.CLOSED)

    def _set_health(self, health: StreamHealth) -> None:
        if self._stop_event.is_set() and health is StreamHealth.HEALTHY:
            health = StreamHealth.CLOSED
        self._cache.set_database_available(
            self._database.name, available=health is StreamHealth.HEALTHY
        )
        self._health = health

    async def _ensure_server_supports_expanded_events(self) -> None:
        server_info = await self._database.client.server_info()
        version = tuple(server_info["versionArray"][:2])
        if version < MINIMUM_SERVER_VERSION:
            message = (
                f"MongoDB server version {server_info['version']} is not supported; "
                "client_query_cache requires MongoDB 8.0 or newer"
            )
            raise StreamStartupError(message)

    async def _open_stream(
        self, *, resume_token: Mapping[str, Any] | None, use_start_after: bool
    ) -> None:
        kwargs: dict[str, Any] = {
            "show_expanded_events": True,
            "max_await_time_ms": self._max_await_time_ms,
        }
        if resume_token is not None:
            if use_start_after:
                kwargs["start_after"] = resume_token
            else:
                kwargs["resume_after"] = resume_token
        previous_stream = self._stream
        self._stream = await self._database.watch(
            build_change_stream_pipeline(), **kwargs
        )
        if previous_stream is not None:
            with contextlib.suppress(PyMongoError):
                await previous_stream.close()
        if self._stop_event.is_set():
            with contextlib.suppress(PyMongoError):
                await self._stream.close()

    async def _interruptible_sleep(self, delay: float) -> bool:
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
        except TimeoutError:
            return False
        return True

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            assert self._stream is not None
            self._cache.record_stream_poll(self._database.name)
            try:
                event = await self._stream.next()
            except StopAsyncIteration, PyMongoError:
                await self._handle_stream_failure()
                continue
            self._resume_token = self._stream.resume_token
            must_reopen = route_change_event(self._cache, self._database.name, event)
            self._record_logical_event_bytes(event)
            if must_reopen:
                await self._reopen_after_invalidate()

    def _record_logical_event_bytes(self, event: Mapping[str, Any]) -> None:
        try:
            encoded_length = len(
                bson.encode(dict(event), codec_options=self._database.codec_options)
            )
        except BSONError, TypeError, ValueError:
            return
        self._cache.record_logical_event_bytes(self._database.name, encoded_length)

    async def _handle_stream_failure(self) -> None:
        if self._stop_event.is_set():
            return
        self._set_health(StreamHealth.RECONNECTING)
        if self._resume_token is None:
            self._clear_namespaces_for_database()
        await self._reopen_with_backoff(use_start_after=False)

    async def _reopen_after_invalidate(self) -> None:
        self._set_health(StreamHealth.RECONNECTING)
        await self._reopen_with_backoff(use_start_after=True)

    async def _reopen_with_backoff(self, *, use_start_after: bool) -> None:
        while not self._stop_event.is_set():
            try:
                await self._open_stream(
                    resume_token=self._resume_token, use_start_after=use_start_after
                )
            except PyMongoError as exc:
                if isinstance(
                    exc, OperationFailure
                ) and is_unresumable_change_stream_error(exc):
                    self._clear_namespaces_for_database()
                    self._resume_token = None
                    use_start_after = False
                    continue
                delay = self._backoff.next_delay()
                logger.warning(
                    "change stream reconnect failed, retrying with backoff",
                    extra={"database": self._database.name, "delay_seconds": delay},
                    exc_info=exc,
                )
                if await self._interruptible_sleep(delay):
                    return
                continue
            else:
                self._backoff.reset()
                if not self._stop_event.is_set():
                    self._set_health(StreamHealth.HEALTHY)
                return

    def _clear_namespaces_for_database(self) -> None:
        for namespace in self._cache.namespaces_for_database(self._database.name):
            self._cache.clear_namespace(namespace)
        self._cache.reset_stream_cost_statistics(self._database.name)


class ChangeStreamCoordinator:
    __slots__ = (
        "_cache",
        "_client",
        "_closed",
        "_health_registry",
        "_lock",
        "_max_await_time_ms",
        "_supervisors",
    )

    def __init__(
        self,
        client: AsyncMongoClient[Any],
        cache: CacheCore,
        *,
        max_await_time_ms: int = DEFAULT_MAX_AWAIT_TIME_MS,
    ) -> None:
        self._client = client
        self._max_await_time_ms = max_await_time_ms
        self._cache = cache
        self._supervisors: dict[str, DatabaseStreamSupervisor] = {}
        self._closed = False
        self._health_registry = StreamHealthRegistry()
        self._lock = asyncio.Lock()

    async def activate_database(self, name: str) -> DatabaseStreamSupervisor | None:
        async with self._lock:
            if self._closed:
                raise StreamLifecycleError("coordinator is closed")
            try:
                supervisor = self._supervisors[name]
            except KeyError:
                supervisor = DatabaseStreamSupervisor(
                    self._client[name],
                    self._cache,
                    max_await_time_ms=self._max_await_time_ms,
                )
                self._health_registry.record_starting(name, supervisor.health_status)
                try:
                    await supervisor.start()
                except StreamStartupError:
                    self._health_registry.record_startup_failure(name)
                    logger.warning(
                        "change stream startup failed for database %r; reads for "
                        "this database will bypass the cache",
                        name,
                        exc_info=True,
                    )
                    return None
                except asyncio.CancelledError:
                    self._health_registry.record_startup_failure(name)
                    raise
                self._supervisors[name] = supervisor
            return supervisor

    def stream_health_snapshot(self, database_name: str) -> StreamHealthSnapshot:
        return self._health_registry.snapshot(database_name)

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            self._health_registry.close()
            supervisors = list(self._supervisors.values())
            self._supervisors.clear()
        for supervisor in supervisors:
            await supervisor.stop()
