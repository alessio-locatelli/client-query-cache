from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

import bson
from bson.errors import BSONError
from pymongo.errors import OperationFailure, PyMongoError

from client_query_cache._core.errors import StreamLifecycleError, StreamStartupError
from client_query_cache._core.stream_activation import StreamActivation
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
from client_query_cache._types import MaxAwaitTimeMs

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pymongo import AsyncMongoClient
    from pymongo.asynchronous.change_stream import AsyncDatabaseChangeStream
    from pymongo.asynchronous.database import AsyncDatabase

    from client_query_cache._core.manager import CacheCore

MINIMUM_SERVER_VERSION = (8, 0)

logger = logging.getLogger(__name__)


async def _join_cleanup(task: asyncio.Task[None]) -> None:
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    task.result()
    if cancelled:
        raise asyncio.CancelledError


class DatabaseStreamSupervisor:
    __slots__ = (
        "_backoff",
        "_cache",
        "_closed_stream",
        "_database",
        "_health",
        "_max_await_time_ms",
        "_resume_token",
        "_shutdown_task",
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
        max_await_time_ms: MaxAwaitTimeMs = DEFAULT_MAX_AWAIT_TIME_MS,
    ) -> None:
        self._database = database
        self._cache = cache
        self._backoff = backoff if backoff is not None else RetryBackoff()
        self._max_await_time_ms = max_await_time_ms
        self._health = StreamHealth.STARTING
        self._stream: AsyncDatabaseChangeStream[Any] | None = None
        self._closed_stream: AsyncDatabaseChangeStream[Any] | None = None
        self._resume_token: Mapping[str, Any] | None = None
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._shutdown_task: asyncio.Task[None] | None = None
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
            await self.stop()
            raise
        if self._stop_event.is_set():
            await self.stop()
            message = "stop() was called while start() was still connecting"
            raise StreamLifecycleError(message)
        self._set_health(StreamHealth.HEALTHY)
        self._task = asyncio.ensure_future(self._run())

    def request_stop(self) -> None:
        self._stop_event.set()
        self._set_health(StreamHealth.CLOSED)
        if self._task is not None:
            self._task.cancel()

    async def stop(self) -> None:
        self.request_stop()
        if self._shutdown_task is None or (
            self._shutdown_task.done() and self._stream is not self._closed_stream
        ):
            self._shutdown_task = asyncio.create_task(self._finish_stop())
        await _join_cleanup(self._shutdown_task)

    async def _finish_stop(self) -> None:
        task = self._task
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
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
        self._closed_stream = stream
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
            try:
                await previous_stream.close()
            except PyMongoError:
                pass

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
            except StopAsyncIteration:
                await self._handle_stream_failure()
                continue
            except PyMongoError:
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
        except BSONError:
            return
        except ValueError:
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
        "_activations",
        "_cache",
        "_client",
        "_closed",
        "_health_registry",
        "_lock",
        "_max_await_time_ms",
        "_shutdown_task",
        "_supervisors",
    )

    def __init__(
        self,
        client: AsyncMongoClient[Any],
        cache: CacheCore,
        *,
        max_await_time_ms: MaxAwaitTimeMs = DEFAULT_MAX_AWAIT_TIME_MS,
    ) -> None:
        self._client = client
        self._max_await_time_ms = max_await_time_ms
        self._cache = cache
        self._activations: dict[
            str, StreamActivation[DatabaseStreamSupervisor, asyncio.Event]
        ] = {}
        self._supervisors: dict[str, DatabaseStreamSupervisor] = {}
        self._closed = False
        self._health_registry = StreamHealthRegistry()
        self._lock = asyncio.Lock()
        self._shutdown_task: asyncio.Task[None] | None = None

    async def activate_database(self, name: str) -> DatabaseStreamSupervisor | None:
        async with self._lock:
            if self._closed:
                raise StreamLifecycleError("coordinator is closed")
            try:
                return self._supervisors[name]
            except KeyError:
                pass
            try:
                activation = self._activations[name]
            except KeyError:
                activation = None
            if activation is not None and (
                activation.pending or not activation.retry.ready()
            ):
                return None
            supervisor = DatabaseStreamSupervisor(
                self._client[name],
                self._cache,
                max_await_time_ms=self._max_await_time_ms,
            )
            if activation is None:
                activation = StreamActivation(supervisor, asyncio.Event())
                self._activations[name] = activation
            else:
                activation.supervisor = supervisor
                activation.pending = True
                activation.completion.clear()
            self._health_registry.record_connecting(name)
        published = False
        try:
            try:
                await supervisor.start()
            except StreamStartupError:
                async with self._lock:
                    if not self._closed:
                        activation.retry.failed()
                        self._health_registry.record_startup_failure(name)
                logger.warning(
                    "change stream startup failed for database %r; reads for "
                    "this database will bypass the cache",
                    name,
                    exc_info=True,
                )
                return None
            async with self._lock:
                if self._closed:
                    raise StreamLifecycleError("coordinator is closed")
                self._supervisors[name] = supervisor
                del self._activations[name]
                self._health_registry.record_starting(name, supervisor.health_status)
                published = True
            return supervisor
        finally:
            if not published:
                try:
                    await supervisor.stop()
                finally:
                    async with self._lock:
                        if not self._closed:
                            self._health_registry.record_startup_failure(name)
                        activation.pending = False
                        activation.completion.set()
            else:
                activation.completion.set()

    def stream_health_snapshot(self, database_name: str) -> StreamHealthSnapshot:
        return self._health_registry.snapshot(database_name)

    async def close(self) -> None:
        if self._shutdown_task is None:
            self._closed = True
            self._health_registry.close()
            supervisors = tuple(self._supervisors.values())
            activations = tuple(self._activations.values())
            for supervisor in supervisors:
                supervisor.request_stop()
            for activation in activations:
                activation.supervisor.request_stop()
            self._shutdown_task = asyncio.create_task(
                self._finish_close(supervisors, activations)
            )
        await _join_cleanup(self._shutdown_task)

    async def _finish_close(
        self,
        supervisors: tuple[DatabaseStreamSupervisor, ...],
        activations: tuple[
            StreamActivation[DatabaseStreamSupervisor, asyncio.Event], ...
        ],
    ) -> None:
        for activation in activations:
            await activation.completion.wait()
        for supervisor in supervisors:
            await supervisor.stop()
        self._activations.clear()
        self._supervisors.clear()
